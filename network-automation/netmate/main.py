"""NetMate: PyQt6 GUI for running commands across many network devices."""

from __future__ import annotations

import csv
import ctypes.util
import json
import logging
import os
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import cast

import keyring
from keyring.errors import KeyringError
from PyQt6 import QtCore, QtGui, QtWidgets

from app_logging import LOG_FILE, configure_logging
from engine import Event, Settings, now
from handlers import NetmikoWorker
from session import Session, SessionError
from table_widgets import LogViewerDialog, OutputPanel, ResultRow, Status

APP_NAME = "NetMate"
__version__ = "1.3.0"
KEYRING_SERVICE = "NetMate"
KEYRING_INDEX = "_saved_users_"
CSV_FIELD_LIMIT = 10 * 1024 * 1024  # device output can be large

DEVICE_TYPES = (
    "arista_eos",
    "cisco_apic",
    "cisco_asa",
    "cisco_ios",
    "cisco_xe",
    "cisco_nxos",
    "cisco_ftd",
    "f5_linux",
    "f5_ltm",
    "f5_tmsh",
    "fortinet",
    "juniper_junos",
    "linux",
    "paloalto_panos",
)

logger = logging.getLogger("netmate.gui")

Button = QtWidgets.QMessageBox.StandardButton


def resource_path(relative_path: str) -> Path:
    """Absolute path to a bundled resource; works for dev and PyInstaller."""
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) / relative_path if base else Path(__file__).resolve().parent / relative_path


def file_stamp() -> str:
    return datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")


def reveal_in_file_manager(path: Path) -> None:
    QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path.parent)))


def spin_row(
    label: str, lo: int, hi: int, value: int
) -> tuple[QtWidgets.QHBoxLayout, QtWidgets.QSpinBox]:
    row = QtWidgets.QHBoxLayout()
    spin = QtWidgets.QSpinBox()
    spin.setRange(lo, hi)
    spin.setValue(value)
    row.addWidget(QtWidgets.QLabel(label))
    row.addWidget(spin)
    return row, spin


class NetworkSettingsDialog(QtWidgets.QDialog):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Network Settings")
        self.setMinimumWidth(400)
        self.settings = Settings.load()
        self._init_ui()

    def _init_ui(self) -> None:
        s = self.settings
        layout = QtWidgets.QVBoxLayout(self)

        pool_group = QtWidgets.QGroupBox("Concurrency")
        pool_layout = QtWidgets.QVBoxLayout(pool_group)
        row, self.max_threads = spin_row("Concurrent Devices:", 1, 50, s.max_threads)
        pool_layout.addLayout(row)

        conn_group = QtWidgets.QGroupBox("Connection Timeouts")
        conn_layout = QtWidgets.QVBoxLayout(conn_group)
        row, self.ssh_timeout = spin_row("SSH Connect Timeout (s):", 1, 10, s.ssh_timeout)
        conn_layout.addLayout(row)
        row, self.conn_retry = spin_row("Connection Retry (s):", 5, 60, s.conn_retry)
        conn_layout.addLayout(row)

        op_group = QtWidgets.QGroupBox("Operation Timeouts")
        op_layout = QtWidgets.QVBoxLayout(op_group)
        row, self.cmd_timeout = spin_row("Command Read (s):", 30, 300, s.cmd_timeout)
        op_layout.addLayout(row)
        row, self.auth_timeout = spin_row("Authentication (s):", 5, 60, s.auth_timeout)
        op_layout.addLayout(row)

        layout.addWidget(pool_group)
        layout.addWidget(conn_group)
        layout.addWidget(op_group)

        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def accept(self) -> None:
        settings = Settings(
            ssh_timeout=self.ssh_timeout.value(),
            conn_retry=self.conn_retry.value(),
            cmd_timeout=self.cmd_timeout.value(),
            auth_timeout=self.auth_timeout.value(),
            max_threads=self.max_threads.value(),
        )
        try:
            settings.save()
        except OSError as e:
            logger.exception("Failed to save network settings")
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to save settings: {e}")
            return
        super().accept()


class DeviceManager(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.workers: list[NetmikoWorker] = []
        self.results: list[ResultRow] = []
        self.completed_commands = 0
        self.total_commands = 0
        self.is_config_mode = False

        self._init_ui()
        self._setup_connections()
        self._set_running(running=False)

    # ------------------------------------------------------------------ UI

    def _init_ui(self) -> None:
        self.setWindowTitle(APP_NAME)
        # Qt 6 scales logical pixels for high-DPI screens automatically.
        self.resize(1200, 760)
        self.setMinimumSize(900, 560)

        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QtWidgets.QHBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        self._init_menus()
        main_layout.addWidget(self._build_sidebar())
        main_layout.addWidget(self._build_content())
        self.setStatusBar(QtWidgets.QStatusBar())

    def _build_sidebar(self) -> QtWidgets.QWidget:
        """Credentials, run controls and progress."""
        expanding_fixed = QtWidgets.QSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed
        )
        sidebar_widget = QtWidgets.QWidget()
        sidebar_widget.setFixedWidth(300)
        sidebar_widget.setObjectName("sidebar")
        sidebar_layout = QtWidgets.QVBoxLayout(sidebar_widget)
        sidebar_layout.setSpacing(10)
        sidebar_layout.setContentsMargins(10, 10, 10, 10)

        credentials_group = QtWidgets.QGroupBox("Credentials")
        credentials_group.setObjectName("sidebar-group")
        credentials_layout = QtWidgets.QVBoxLayout(credentials_group)
        self.username_input = QtWidgets.QLineEdit()
        self.username_input.setSizePolicy(expanding_fixed)
        self.password_input = QtWidgets.QLineEdit()
        self.password_input.setSizePolicy(expanding_fixed)
        self.password_input.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.device_type = QtWidgets.QComboBox()
        self.device_type.setSizePolicy(expanding_fixed)
        self.device_type.addItems(list(DEVICE_TYPES))
        for label, widget in (
            ("Username:", self.username_input),
            ("Password:", self.password_input),
            ("Device Type:", self.device_type),
        ):
            credentials_layout.addWidget(QtWidgets.QLabel(label))
            credentials_layout.addWidget(widget)

        controls_group = QtWidgets.QGroupBox("Controls")
        controls_group.setObjectName("sidebar-group")
        controls_layout = QtWidgets.QVBoxLayout(controls_group)
        self.run_btn = QtWidgets.QPushButton("Run")
        self.run_btn.setObjectName("run_btn")
        self.pause_btn = QtWidgets.QPushButton("Pause")
        self.pause_btn.setObjectName("pause_btn")
        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.stop_btn.setObjectName("stop_btn")
        self.clear_btn = QtWidgets.QPushButton("Clear Output")
        self.clear_btn.setObjectName("clear_btn")
        for btn in (self.run_btn, self.pause_btn, self.stop_btn, self.clear_btn):
            controls_layout.addWidget(btn)

        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setSizePolicy(expanding_fixed)
        self.progress_bar.hide()

        sidebar_layout.addWidget(credentials_group)
        sidebar_layout.addWidget(controls_group)
        sidebar_layout.addWidget(self.progress_bar)
        sidebar_layout.addStretch()
        return sidebar_widget

    def _build_content(self) -> QtWidgets.QWidget:
        """Device and command inputs above the output table."""
        expanding = QtWidgets.QSizePolicy.Policy.Expanding
        expanding_both = QtWidgets.QSizePolicy(expanding, expanding)

        self.devices_input = QtWidgets.QPlainTextEdit()
        self.devices_input.setSizePolicy(expanding_both)
        self.devices_input.setMinimumHeight(100)
        self.devices_input.setPlaceholderText("Enter device IPs or hostnames\n(one per line)")
        self.commands_input = QtWidgets.QPlainTextEdit()
        self.commands_input.setSizePolicy(expanding_both)
        self.commands_input.setMinimumHeight(100)
        self.commands_input.setPlaceholderText("Enter commands to execute\n(one per line)")

        input_area_layout = QtWidgets.QHBoxLayout()
        for label, widget in (("Devices:", self.devices_input), ("Commands:", self.commands_input)):
            column = QtWidgets.QVBoxLayout()
            column.addWidget(QtWidgets.QLabel(label))
            column.addWidget(widget)
            input_area_layout.addLayout(column)
        input_container = QtWidgets.QWidget()
        input_container.setLayout(input_area_layout)

        # Output table
        self.output = OutputPanel()
        self.output.setSizePolicy(expanding_both)
        self.output.setMinimumHeight(240)
        output_container = QtWidgets.QWidget()
        output_layout = QtWidgets.QVBoxLayout(output_container)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.addWidget(QtWidgets.QLabel("Output:"))
        output_layout.addWidget(self.output)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        splitter.addWidget(input_container)
        splitter.addWidget(output_container)
        splitter.setSizes([300, 700])

        main_content_widget = QtWidgets.QWidget()
        main_content_layout = QtWidgets.QVBoxLayout(main_content_widget)
        main_content_layout.setContentsMargins(0, 0, 0, 0)
        main_content_layout.addWidget(splitter)
        return main_content_widget

    def _init_menus(self) -> None:
        menubar = QtWidgets.QMenuBar(self)
        self.setMenuBar(menubar)

        file_menu = QtWidgets.QMenu("File", self)
        credentials_menu = QtWidgets.QMenu("Credentials", self)
        session_menu = QtWidgets.QMenu("Session", self)
        results_menu = QtWidgets.QMenu("Results", self)
        for sub in (credentials_menu, session_menu, results_menu):
            file_menu.addMenu(sub)
        options_menu = QtWidgets.QMenu("Options", self)
        preferences_menu = QtWidgets.QMenu("Preferences", self)
        log_menu = QtWidgets.QMenu("Log", self)
        for menu in (file_menu, options_menu, preferences_menu, log_menu):
            menubar.addMenu(menu)

        self._action(credentials_menu, "Save Credentials", self.save_credentials, "Ctrl+S")
        self._action(credentials_menu, "Load Credentials", self.load_credentials)
        self._action(session_menu, "Save Session", self.save_session)
        self._action(session_menu, "Load Session", self.load_session)
        self._action(results_menu, "Save Results", self.save_results)
        self._action(results_menu, "View Results", self.view_results)
        self.toggle_config_mode_action = self._action(
            options_menu, "Enable Config Mode", self.toggle_config_mode
        )
        self.toggle_config_mode_action.setCheckable(True)
        self._action(preferences_menu, "Network Settings", self.show_network_settings)
        self._action(log_menu, "View Log", self.view_log)
        self._action(log_menu, "Clear Log", self.clear_log)

    def _action(
        self,
        menu: QtWidgets.QMenu,
        text: str,
        slot: Callable[[], None],
        shortcut: str | None = None,
    ) -> QtGui.QAction:
        action = QtGui.QAction(text, self)
        if shortcut:
            action.setShortcut(QtGui.QKeySequence(shortcut))
        action.triggered.connect(lambda _checked=False: slot())
        menu.addAction(action)
        return action

    def _setup_connections(self) -> None:
        self.run_btn.clicked.connect(self.run_commands)
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.clear_btn.clicked.connect(self.clear_output)
        self.stop_btn.clicked.connect(self.stop_execution)

    def _set_running(self, *, running: bool) -> None:
        self.run_btn.setEnabled(not running)
        self.pause_btn.setEnabled(running)
        self.stop_btn.setEnabled(running)
        self._set_pause_label(paused=False)
        if not running:
            self.progress_bar.hide()

    def _set_pause_label(self, *, paused: bool) -> None:
        # The object name selects the QSS rule (#pause_btn / #resume_btn).
        self.pause_btn.setText("Resume" if paused else "Pause")
        self.pause_btn.setObjectName("resume_btn" if paused else "pause_btn")
        style = self.pause_btn.style()
        if style is not None:
            style.unpolish(self.pause_btn)
            style.polish(self.pause_btn)

    def _status(self, message: str) -> None:
        bar = self.statusBar()
        if bar is not None:
            bar.showMessage(message, 8000)

    def _warn(self, message: str) -> None:
        self.output.add_message(message, Status.ERROR)
        QtWidgets.QMessageBox.warning(self, "Error", message)

    # ------------------------------------------------------------------ execution

    def toggle_config_mode(self) -> None:
        self.is_config_mode = self.toggle_config_mode_action.isChecked()
        mode = "Configuration" if self.is_config_mode else "Normal"
        self.commands_input.setPlaceholderText(
            f"Enter commands to execute ({mode} Mode)\n(one per line)"
        )

    def handle_event(self, event: Event) -> None:
        result = self.output.add_event(event)
        if result is not None:
            self.results.append(result)

    def advance_progress(self, steps: int) -> None:
        """Advance the progress bar by completed (or skipped) steps."""
        self.completed_commands += steps
        self.progress_bar.setValue(self.completed_commands)
        total = max(self.total_commands, 1)
        percent = int(self.completed_commands / total * 100)
        self.progress_bar.setFormat(
            f"{percent}% ({self.completed_commands}/{self.total_commands} commands)"
        )

    def run_commands(self) -> None:
        username = self.username_input.text().strip()
        password = self.password_input.text()
        if not username or not password:
            self._warn("Please enter username and password")
            return

        devices = _lines(self.devices_input.toPlainText())
        if not devices:
            self._warn("Please enter at least one device")
            return

        commands = _lines(self.commands_input.toPlainText())
        if not commands:
            self._warn("Please enter at least one command")
            return

        self.output.clear()
        self.results.clear()
        mode_str = "Configuration" if self.is_config_mode else "Normal"
        self.output.add_message(
            f"Starting execution in {mode_str} Mode — "
            f"{len(devices)} devices, {len(commands)} commands"
        )

        self.completed_commands = 0
        # In config mode, all commands are one unit per device.
        self.total_commands = len(devices) * (1 if self.is_config_mode else len(commands))
        self.progress_bar.setMaximum(self.total_commands)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p% (%v/%m commands)")
        self.progress_bar.show()

        devices_info = [
            {
                "device_type": self.device_type.currentText(),
                "host": device,
                "username": username,
                "password": password,
            }
            for device in devices
        ]
        logger.info(
            "Run started by %s: %d devices, %d commands, mode=%s",
            username,
            len(devices),
            len(commands),
            mode_str,
        )

        worker = NetmikoWorker(devices_info, commands, self.is_config_mode, parent=self)
        worker.event_received.connect(self.handle_event)
        worker.progress_advanced.connect(self.advance_progress)
        worker.finished.connect(lambda w=worker: self.handle_worker_finished(w))
        self.workers.append(worker)
        self._set_running(running=True)
        worker.start()

    def handle_worker_finished(self, worker: NetmikoWorker) -> None:
        if worker in self.workers:
            self.workers.remove(worker)
        worker.deleteLater()
        if not self.workers:
            self._set_running(running=False)
            ok = sum(1 for r in self.results if r.status == Status.OK.value)
            self._status(f"Done: {ok}/{len(self.results)} results OK")

    def toggle_pause(self) -> None:
        if not self.workers:
            QtWidgets.QMessageBox.warning(self, "Error", "No running tasks to pause or resume.")
            return
        pausing = self.pause_btn.text() == "Pause"
        self._set_pause_label(paused=pausing)
        for worker in self.workers:
            if worker.isRunning():
                if pausing:
                    worker.pause()
                else:
                    worker.resume()

    def stop_execution(self) -> None:
        """Stop all running workers and wait for them to unwind."""
        workers = list(self.workers)
        for worker in workers:
            worker.stop()
        for worker in workers:
            worker.wait()
        self.output.add_message("Execution stopped by user", Status.STOPPED)
        self._set_running(running=False)

    def clear_output(self) -> None:
        self.output.clear()
        self.results.clear()
        self.progress_bar.hide()

    def closeEvent(self, a0: QtGui.QCloseEvent | None) -> None:
        # A QThread destroyed while running aborts the process.
        for worker in self.workers:
            worker.stop()
        for worker in self.workers:
            worker.wait()
        super().closeEvent(a0)

    # ------------------------------------------------------------------ sessions

    def save_session(self) -> None:
        """Save devices, commands, mode and results (never the password) to JSON."""
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Session", f"netmate_session_{file_stamp()}.json", "JSON Files (*.json)"
        )
        if not filename:
            return
        path = Path(filename)
        session = Session(
            username=self.username_input.text(),
            device_type=self.device_type.currentText(),
            devices=self.devices_input.toPlainText(),
            commands=self.commands_input.toPlainText(),
            is_config_mode=self.is_config_mode,
            results=list(self.results),
            completed_commands=self.completed_commands,
            total_commands=self.total_commands,
        )
        try:
            session.save(path)
        except OSError as e:
            logger.exception("Failed to save session to %s", path)
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to save session: {e}")
            return
        QtWidgets.QMessageBox.information(self, "Success", f"Session saved to:\n{path}")
        reveal_in_file_manager(path)

    def load_session(self) -> None:
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load Session", "", "JSON Files (*.json)"
        )
        if not filename:
            return
        try:
            session = Session.load(Path(filename))
        except (OSError, SessionError) as e:
            logger.warning("Failed to load session %s: %s", filename, e)
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to load session: {e}")
            return

        self.username_input.setText(session.username)
        self.devices_input.setPlainText(session.devices)
        self.commands_input.setPlainText(session.commands)
        index = self.device_type.findText(session.device_type)
        if index >= 0:
            self.device_type.setCurrentIndex(index)
        self.toggle_config_mode_action.setChecked(session.is_config_mode)
        self.toggle_config_mode()

        self.results = session.results
        self.output.load_results(session.results)
        self.completed_commands = session.completed_commands
        self.total_commands = session.total_commands
        QtWidgets.QMessageBox.information(
            self, "Success", f"Session from {session.timestamp} loaded"
        )

    # ------------------------------------------------------------------ credentials

    def _saved_usernames(self) -> list[str]:
        try:
            raw = keyring.get_password(KEYRING_SERVICE, KEYRING_INDEX)
            names: object = json.loads(raw) if raw else []
        except (KeyringError, ValueError):
            logger.exception("Could not read saved usernames from keyring")
            return []
        if not isinstance(names, list):
            return []
        return [n for n in cast("list[object]", names) if isinstance(n, str)]

    def save_credentials(self) -> None:
        """Save credentials to the OS keyring."""
        username = self.username_input.text().strip()
        password = self.password_input.text()
        if not username or not password:
            QtWidgets.QMessageBox.warning(self, "Error", "Please enter username and password")
            return
        try:
            keyring.set_password(KEYRING_SERVICE, username, password)
            usernames = self._saved_usernames()
            if username not in usernames:
                usernames.append(username)
                keyring.set_password(KEYRING_SERVICE, KEYRING_INDEX, json.dumps(usernames))
        except KeyringError as e:
            logger.exception("Failed to save credentials")
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to save credentials: {e}")
            return
        QtWidgets.QMessageBox.information(self, "Success", "Credentials saved successfully")

    def load_credentials(self) -> None:
        """Load credentials from the OS keyring."""
        usernames = self._saved_usernames()
        if not usernames:
            QtWidgets.QMessageBox.warning(
                self,
                "No Saved Credentials",
                "No saved credentials found. Please save credentials first.",
            )
            return
        username, ok = QtWidgets.QInputDialog.getItem(
            self, "Load Credentials", "Select username:", usernames, 0, False
        )
        if not ok or not username:
            return
        try:
            password = keyring.get_password(KEYRING_SERVICE, username)
        except KeyringError as e:
            logger.exception("Failed to load credentials")
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to load credentials: {e}")
            return
        if not password:
            QtWidgets.QMessageBox.warning(
                self, "Error", "No saved credentials found for this username"
            )
            return
        self.username_input.setText(username)
        self.password_input.setText(password)
        QtWidgets.QMessageBox.information(self, "Success", "Credentials loaded successfully")

    # ------------------------------------------------------------------ results

    def save_results(self) -> None:
        """Export results to CSV."""
        if not self.results:
            QtWidgets.QMessageBox.warning(self, "Error", "No results to save")
            return
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Results", f"netmate_results_{file_stamp()}.csv", "CSV Files (*.csv)"
        )
        if not filename:
            return
        path = Path(filename)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(ResultRow.FIELDS))
                writer.writeheader()
                writer.writerows(r.as_dict() for r in self.results)
        except OSError as e:
            logger.exception("Failed to save results to %s", path)
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to save results: {e}")
            return
        QtWidgets.QMessageBox.information(self, "Success", f"Results saved to:\n{path}")
        reveal_in_file_manager(path)

    def view_results(self) -> None:
        """Open a results CSV in the same table view used for live output."""
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open Results File", "", "CSV Files (*.csv)"
        )
        if not filename:
            return
        csv.field_size_limit(CSV_FIELD_LIMIT)
        try:
            with Path(filename).open(encoding="utf-8", newline="") as f:
                rows = [ResultRow.from_mapping(row) for row in csv.DictReader(f)]
        except (OSError, csv.Error) as e:
            logger.exception("Failed to open results %s", filename)
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to open CSV file: {e}")
            return

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(f"Results — {Path(filename).name}")
        dialog.resize(1100, 650)
        dialog.setMinimumSize(800, 400)
        dialog.setSizeGripEnabled(True)
        panel = OutputPanel(dialog)
        panel.load_results(rows)
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.addWidget(panel)
        dialog.exec()

    # ------------------------------------------------------------------ log & settings

    def view_log(self) -> None:
        if not LOG_FILE.exists():
            QtWidgets.QMessageBox.warning(self, "Error", "Log file not found.")
            return
        try:
            LogViewerDialog(LOG_FILE, self).exec()
        except OSError as e:
            logger.exception("Failed to read log file")
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to read log file: {e}")

    def clear_log(self) -> None:
        if not LOG_FILE.exists():
            QtWidgets.QMessageBox.warning(self, "Error", "Log file not found.")
            return
        reply = QtWidgets.QMessageBox.question(
            self,
            "Confirm Clear Log",
            "Are you sure you want to clear the log file?",
            Button.Yes | Button.No,
            Button.No,
        )
        if reply != Button.Yes:
            return
        try:
            LOG_FILE.write_text(f"# Log cleared on {now()}\n", encoding="utf-8")
        except OSError as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to clear log file: {e}")
            return
        QtWidgets.QMessageBox.information(self, "Success", "Log file cleared successfully.")

    def show_network_settings(self) -> None:
        NetworkSettingsDialog(self).exec()


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _log_uncaught(
    exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None
) -> None:
    logger.critical("Unhandled exception", exc_info=(exc_type, exc, tb))
    sys.__excepthook__(exc_type, exc, tb)


def missing_linux_qt_dependency() -> str | None:
    """Qt >= 6.5 aborts (core dump) on X11 without libxcb-cursor; detect it first."""
    if not sys.platform.startswith("linux"):
        return None
    platform = os.environ.get("QT_QPA_PLATFORM", "")
    uses_xcb = platform == "xcb" or (not platform and not os.environ.get("WAYLAND_DISPLAY"))
    if uses_xcb and ctypes.util.find_library("xcb-cursor") is None:
        return (
            "NetMate needs the libxcb-cursor library to open its window on X11.\n"
            "Install it with your package manager, for example:\n"
            "  Debian/Ubuntu: sudo apt install libxcb-cursor0\n"
            "  Fedora/RHEL:   sudo dnf install xcb-util-cursor"
        )
    return None


def main() -> int:
    configure_logging()
    sys.excepthook = _log_uncaught
    problem = missing_linux_qt_dependency()
    if problem:
        logger.critical(problem.replace("\n", " "))
        print(problem, file=sys.stderr)
        return 1
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setWindowIcon(QtGui.QIcon(str(resource_path("network.ico"))))

    qss_file = resource_path("styles.qss")
    try:
        app.setStyleSheet(qss_file.read_text(encoding="utf-8"))
    except OSError:
        logger.exception("Failed to apply stylesheet %s", qss_file)

    window = DeviceManager()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
