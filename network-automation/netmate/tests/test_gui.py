"""GUI workflows driven through the real widgets (headless Qt).

Modal dialogs are replaced with recorders so the tests never block; everything
else (worker thread, engine, table, files) is the production code path.
"""

from __future__ import annotations

import csv
import json
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

import keyring
import pytest
from keyring.backend import KeyringBackend
from PyQt6 import QtCore, QtGui, QtWidgets
from pytestqt.qtbot import QtBot

import engine
import main
from app_logging import LOG_FILE
from engine import Settings
from table_widgets import LogViewerDialog, Status
from tests.fake_ios import PASSWORD, USERNAME, FakeIosServer

Button = QtWidgets.QMessageBox.StandardButton


# --------------------------------------------------------------------------- fakes


class Device:
    """Fake Netmiko connection; commands named 'slow' poll like Netmiko for 30 s."""

    def __init__(self, **params: Any) -> None:
        self.host: str = params["host"]

    def read_channel(self) -> str:
        return ""

    def write_channel(self, out_data: str) -> None:
        pass

    def send_command(self, command: str, **_kw: Any) -> str:
        if command == "slow":
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                self.read_channel()
                time.sleep(0.01)
        if command == "bad":
            return "% Invalid input detected at '^' marker."
        return f"{self.host}: {command} ok\nsecond line"

    def send_config_set(self, commands: list[str], **_kw: Any) -> str:
        return "\n".join(f"{self.host}(config)# {c}" for c in commands)

    def commit(self) -> str:
        return "commit complete"

    def exit_config_mode(self) -> str:
        return ""

    def disconnect(self) -> None:
        pass


class MemoryKeyring(KeyringBackend):
    priority: ClassVar[float] = 1  # type: ignore[misc]

    def __init__(self) -> None:
        super().__init__()
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.store.pop((service, username), None)


@dataclass
class Dialogs:
    """Records message boxes and answers file dialogs."""

    messages: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    save_path: str = ""
    open_path: str = ""
    item: str = ""
    opened_urls: list[str] = field(default_factory=list[str])

    def kinds(self) -> list[str]:
        return [k for k, _ in self.messages]


@pytest.fixture
def dialogs(monkeypatch: pytest.MonkeyPatch) -> Dialogs:
    d = Dialogs()
    box = QtWidgets.QMessageBox

    def recorder(kind: str) -> Any:
        def show(_parent: object, _title: str, text: str, *_a: object) -> Button:
            d.messages.append((kind, text))
            return Button.Yes

        return staticmethod(show)

    for kind in ("information", "warning", "critical", "question"):
        monkeypatch.setattr(box, kind, recorder(kind))
    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getSaveFileName", staticmethod(lambda *_a: (d.save_path, ""))
    )
    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getOpenFileName", staticmethod(lambda *_a: (d.open_path, ""))
    )
    monkeypatch.setattr(
        QtWidgets.QInputDialog, "getItem", staticmethod(lambda *_a: (d.item, bool(d.item)))
    )

    def open_url(url: QtCore.QUrl) -> bool:
        d.opened_urls.append(url.toLocalFile())
        return True

    monkeypatch.setattr(QtGui.QDesktopServices, "openUrl", staticmethod(open_url))
    monkeypatch.setattr(QtWidgets.QDialog, "exec", no_exec)
    return d


def no_exec(_self: QtWidgets.QDialog) -> int:
    return 0


@pytest.fixture
def window(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, dialogs: Dialogs
) -> Iterator[main.DeviceManager]:
    monkeypatch.setattr(engine, "ConnectHandler", Device)
    w = main.DeviceManager()
    qtbot.addWidget(w)
    w.username_input.setText("admin")
    w.password_input.setText("secret")
    w.devices_input.setPlainText("r1\nr2\n")
    w.commands_input.setPlainText("show ver\nbad")
    yield w
    w.close()  # stops any worker still running


def finish(qtbot: QtBot, w: main.DeviceManager, timeout: int = 10_000) -> None:
    qtbot.waitUntil(lambda: w.run_btn.isEnabled() and not w.workers, timeout=timeout)


def statuses(w: main.DeviceManager) -> list[str]:
    return sorted(f"{r.host}:{r.command}:{r.status}" for r in w.results)


# --------------------------------------------------------------------------- runs


def test_run_end_to_end(qtbot: QtBot, window: main.DeviceManager) -> None:
    window.run_btn.click()
    assert not window.run_btn.isEnabled()
    assert window.pause_btn.isEnabled()
    assert window.stop_btn.isEnabled()
    finish(qtbot, window)

    assert statuses(window) == [
        "r1:bad:FAILED",
        "r1:show ver:OK",
        "r2:bad:FAILED",
        "r2:show ver:OK",
    ]
    assert window.completed_commands == window.total_commands == 4
    assert not window.pause_btn.isEnabled()
    assert not window.stop_btn.isEnabled()
    assert window.progress_bar.isHidden()
    counts = window.output.statuses()
    assert counts[Status.OK] == 2
    assert counts[Status.FAILED] == 2


def test_second_run_clears_previous_results(qtbot: QtBot, window: main.DeviceManager) -> None:
    window.run_btn.click()
    finish(qtbot, window)
    window.commands_input.setPlainText("show ver")
    window.run_btn.click()
    finish(qtbot, window)
    assert statuses(window) == ["r1:show ver:OK", "r2:show ver:OK"]


@pytest.mark.parametrize(
    ("field_name", "message"),
    [
        ("username_input", "username and password"),
        ("password_input", "username and password"),
        ("devices_input", "at least one device"),
        ("commands_input", "at least one command"),
    ],
)
def test_validation_blocks_run(
    window: main.DeviceManager, dialogs: Dialogs, field_name: str, message: str
) -> None:
    widget = getattr(window, field_name)
    if isinstance(widget, QtWidgets.QLineEdit):
        widget.setText("")
    else:
        widget.setPlainText("   \n  ")
    window.run_btn.click()
    assert not window.workers
    assert window.run_btn.isEnabled()
    assert dialogs.kinds() == ["warning"]
    assert message in dialogs.messages[0][1]
    assert window.output.statuses()[Status.ERROR] == 1


def test_config_mode_counts_one_step_per_device(qtbot: QtBot, window: main.DeviceManager) -> None:
    window.toggle_config_mode_action.trigger()
    assert window.is_config_mode
    assert "Configuration Mode" in window.commands_input.placeholderText()
    window.run_btn.click()
    assert window.total_commands == 2


def test_pause_and_resume(qtbot: QtBot, window: main.DeviceManager) -> None:
    window.run_btn.click()
    window.pause_btn.click()
    assert window.pause_btn.text() == "Resume"
    assert window.pause_btn.objectName() == "resume_btn"
    window.pause_btn.click()
    assert window.pause_btn.text() == "Pause"
    finish(qtbot, window)
    assert len(window.results) == 4


def test_pause_button_works_on_every_run(qtbot: QtBot, window: main.DeviceManager) -> None:
    for _ in range(2):
        window.run_btn.click()
        assert window.pause_btn.isEnabled()
        assert window.pause_btn.text() == "Pause"
        finish(qtbot, window)


def test_stop_interrupts_long_commands(qtbot: QtBot, window: main.DeviceManager) -> None:
    window.commands_input.setPlainText("slow\nshow ver")
    window.run_btn.click()
    qtbot.wait(300)
    start = time.perf_counter()
    window.stop_btn.click()
    assert time.perf_counter() - start < 3
    assert window.run_btn.isEnabled()
    finish(qtbot, window, timeout=2000)
    assert len(window.results) == 2
    assert all(r.status == "STOPPED" for r in window.results)
    assert window.output.statuses()[Status.STOPPED] == 3  # 2 devices + "stopped by user"


def test_close_during_run_stops_workers(qtbot: QtBot, window: main.DeviceManager) -> None:
    window.commands_input.setPlainText("slow")
    window.run_btn.click()
    worker = window.workers[0]
    qtbot.wait(200)
    start = time.perf_counter()
    window.close()
    assert time.perf_counter() - start < 3
    assert worker.isFinished()


def test_clear_output(qtbot: QtBot, window: main.DeviceManager) -> None:
    window.run_btn.click()
    finish(qtbot, window)
    window.clear_btn.click()
    assert window.output.model.rowCount() == 0
    assert not window.results


# --------------------------------------------------------------------------- files


def test_session_round_trip(
    qtbot: QtBot, window: main.DeviceManager, dialogs: Dialogs, tmp_path: Path
) -> None:
    window.device_type.setCurrentText("juniper_junos")
    window.toggle_config_mode_action.trigger()
    window.run_btn.click()
    finish(qtbot, window)
    assert [r.status for r in window.results] == ["OK", "OK"]  # one config set per device
    path = tmp_path / "s.json"
    dialogs.save_path = str(path)
    window.save_session()
    assert "secret" not in path.read_text(encoding="utf-8")
    assert [Path(u) for u in dialogs.opened_urls] == [tmp_path]

    fresh = main.DeviceManager()
    qtbot.addWidget(fresh)
    dialogs.open_path = str(path)
    fresh.load_session()
    assert fresh.username_input.text() == "admin"
    assert fresh.password_input.text() == ""
    assert fresh.device_type.currentText() == "juniper_junos"
    assert fresh.is_config_mode
    assert fresh.devices_input.toPlainText() == "r1\nr2\n"
    assert statuses(fresh) == statuses(window)
    assert fresh.output.model.rowCount() == len(window.results)


@pytest.mark.parametrize("content", ["{broken", '{"total_commands": "x"}', '{"results": [1]}'])
def test_load_malformed_session_shows_error(
    window: main.DeviceManager, dialogs: Dialogs, tmp_path: Path, content: str
) -> None:
    path = tmp_path / "bad.json"
    path.write_text(content, encoding="utf-8")
    dialogs.open_path = str(path)
    window.load_session()
    assert dialogs.kinds() == ["critical"]
    assert window.username_input.text() == "admin"  # state untouched


def test_cancelled_file_dialogs_do_nothing(window: main.DeviceManager, dialogs: Dialogs) -> None:
    window.save_session()
    window.load_session()
    window.view_results()
    assert dialogs.messages == []


def test_results_csv_export_and_view(
    qtbot: QtBot,
    window: main.DeviceManager,
    dialogs: Dialogs,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window.run_btn.click()
    finish(qtbot, window)
    path = tmp_path / "results.csv"
    dialogs.save_path = str(path)
    window.save_results()

    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0]) == ["timestamp", "status", "username", "host", "command", "output"]
    assert sorted(r["status"] for r in rows) == ["FAILED", "FAILED", "OK", "OK"]
    assert any("\nsecond line" in r["output"] for r in rows)  # multi-line output preserved

    shown: list[int] = []

    def capture(self: QtWidgets.QDialog) -> int:
        panel = self.findChild(main.OutputPanel)
        assert panel is not None
        shown.append(panel.model.rowCount())
        return 0

    monkeypatch.setattr(QtWidgets.QDialog, "exec", capture)
    dialogs.open_path = str(path)
    window.view_results()
    assert shown == [4]


def test_save_results_without_results_warns(window: main.DeviceManager, dialogs: Dialogs) -> None:
    window.save_results()
    assert dialogs.kinds() == ["warning"]


def test_view_legacy_results_csv(
    window: main.DeviceManager, dialogs: Dialogs, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "old.csv"
    path.write_text(
        "timestamp,username,host,command,output\n"
        't,u,h,show ver,"line1\nline2"\n'
        "t,u,h,AUTH ERROR,ERROR: bad password\n",
        encoding="utf-8",
    )
    statuses_seen: list[str] = []

    def capture(self: QtWidgets.QDialog) -> int:
        panel = self.findChild(main.OutputPanel)
        assert panel is not None
        statuses_seen.extend(
            panel.model.item(r, 1).text()  # type: ignore[union-attr]
            for r in range(panel.model.rowCount())
        )
        return 0

    monkeypatch.setattr(QtWidgets.QDialog, "exec", capture)
    dialogs.open_path = str(path)
    window.view_results()
    assert statuses_seen == ["OK", "FAILED"]


def test_view_and_clear_log(
    qtbot: QtBot, window: main.DeviceManager, dialogs: Dialogs, monkeypatch: pytest.MonkeyPatch
) -> None:
    window.view_log()
    assert dialogs.kinds() == ["warning"]  # no log file yet

    LOG_FILE.write_text(
        "2026-10-22 10:00:00 | ERROR    | netmate.engine | netmate_0 | r1: boom\n", encoding="utf-8"
    )
    rows: list[int] = []

    def capture(self: QtWidgets.QDialog) -> int:
        if isinstance(self, LogViewerDialog):
            rows.append(self.panel.model.rowCount())
        return 0

    monkeypatch.setattr(QtWidgets.QDialog, "exec", capture)
    window.view_log()
    assert rows == [1]

    window.clear_log()
    assert LOG_FILE.read_text(encoding="utf-8").startswith("# Log cleared on ")
    assert dialogs.kinds()[-1] == "information"


# --------------------------------------------------------------------------- settings & credentials


def test_network_settings_dialog_saves(window: main.DeviceManager, qtbot: QtBot) -> None:
    dialog = main.NetworkSettingsDialog(window)
    qtbot.addWidget(dialog)
    dialog.max_threads.setValue(25)
    dialog.cmd_timeout.setValue(200)
    dialog.accept()
    assert Settings.load() == Settings(max_threads=25, cmd_timeout=200)
    reopened = main.NetworkSettingsDialog(window)
    qtbot.addWidget(reopened)
    assert reopened.max_threads.value() == 25


def test_run_uses_saved_settings(qtbot: QtBot, window: main.DeviceManager) -> None:
    Settings(max_threads=1).save()
    window.run_btn.click()
    assert window.workers[0].engine.settings.max_threads == 1
    finish(qtbot, window)


def test_credentials_save_and_load(window: main.DeviceManager, dialogs: Dialogs) -> None:
    previous = keyring.get_keyring()
    keyring.set_keyring(MemoryKeyring())
    try:
        window.save_credentials()
        window.username_input.setText("other")
        window.password_input.setText("pw2")
        window.save_credentials()
        assert json.loads(keyring.get_password("NetMate", "_saved_users_") or "[]") == [
            "admin",
            "other",
        ]

        window.username_input.clear()
        window.password_input.clear()
        dialogs.item = "admin"
        window.load_credentials()
        assert window.username_input.text() == "admin"
        assert window.password_input.text() == "secret"
    finally:
        keyring.set_keyring(previous)


def test_load_credentials_with_none_saved(window: main.DeviceManager, dialogs: Dialogs) -> None:
    previous = keyring.get_keyring()
    keyring.set_keyring(MemoryKeyring())
    try:
        window.load_credentials()
        assert dialogs.kinds() == ["warning"]
    finally:
        keyring.set_keyring(previous)


def test_menus_are_wired(window: main.DeviceManager) -> None:
    menubar = window.menuBar()
    assert menubar is not None
    titles = [a.text() for a in menubar.actions()]
    assert titles == ["File", "Options", "Preferences", "Log"]
    actions = {a.text() for a in window.findChildren(QtGui.QAction)}
    for expected in (
        "Save Credentials",
        "Load Credentials",
        "Save Session",
        "Load Session",
        "Save Results",
        "View Results",
        "Enable Config Mode",
        "Network Settings",
        "View Log",
        "Clear Log",
    ):
        assert expected in actions


def test_stylesheet_resolves_next_to_code() -> None:
    assert main.resource_path("styles.qss").is_file()


# --------------------------------------------------------------------------- real SSH


@pytest.mark.integration
def test_gui_against_real_ssh_device(
    qtbot: QtBot, dialogs: Dialogs, monkeypatch: pytest.MonkeyPatch
) -> None:
    with FakeIosServer() as server:
        real_connect = engine.ConnectHandler

        def with_port(**params: Any) -> Any:
            return real_connect(**params, port=server.port)

        monkeypatch.setattr(engine, "ConnectHandler", with_port)
        w = main.DeviceManager()
        qtbot.addWidget(w)
        w.username_input.setText(USERNAME)
        w.password_input.setText(PASSWORD)
        w.device_type.setCurrentText("cisco_ios")
        w.devices_input.setPlainText("127.0.0.1\n127.0.0.1\n127.0.0.1")
        w.commands_input.setPlainText("show version\nshow ip interface brief\nshow bogus")
        w.run_btn.click()
        finish(qtbot, w, timeout=60_000)

    assert len(w.results) == 9
    counts = w.output.statuses()
    assert counts[Status.OK] == 6
    assert counts[Status.FAILED] == 3
    assert counts[Status.CONNECTED] == 3
    assert any("R1 uptime is 41 weeks" in r.output for r in w.results)


@pytest.mark.parametrize(
    ("platform", "env", "lib", "expect_problem"),
    [
        ("linux", {}, None, True),
        ("linux", {}, "libxcb-cursor.so.0", False),
        ("linux", {"WAYLAND_DISPLAY": "wayland-0"}, None, False),
        ("linux", {"QT_QPA_PLATFORM": "offscreen"}, None, False),
        ("linux", {"QT_QPA_PLATFORM": "xcb", "WAYLAND_DISPLAY": "w"}, None, True),
        ("win32", {}, None, False),
    ],
)
def test_linux_qt_dependency_check(
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    env: dict[str, str],
    lib: str | None,
    expect_problem: bool,
) -> None:
    monkeypatch.setattr(main.sys, "platform", platform)
    for key in ("QT_QPA_PLATFORM", "WAYLAND_DISPLAY"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    def find_library(_name: str) -> str | None:
        return lib

    monkeypatch.setattr(main.ctypes.util, "find_library", find_library)
    assert (main.missing_linux_qt_dependency() is not None) is expect_problem
