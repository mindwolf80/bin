# main.py
import csv
import json
import os
import sys
from datetime import datetime

from PyQt5 import QtCore, QtGui, QtWidgets

from handlers import NetmikoWorker


def resource_path(relative_path):
    """Get absolute path to resource, works for dev and PyInstaller."""
    base_path = getattr(sys, "_MEIPASS2", None)
    if base_path is None:
        base_path = getattr(sys, "_MEIPASS", None)
    if base_path:
        return os.path.join(base_path, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


class DeviceManager(QtWidgets.QMainWindow):
    # HTML color codes for different elements
    COLORS = {
        "timestamp": "#808080",  # Gray
        "error": "#dc2626",  # Red
        "success": "#16a34a",  # Green
        "command": "#60a5fa",  # Light blue
        "separator": "#475569",  # Slate gray
        "output": "#CBD5E1",  # Light gray for command output
    }

    def __init__(self):
        super().__init__()
        self.workers = []
        self.results = []
        self.completed_commands = 0
        self.total_commands = 0
        self.is_config_mode = False

        # Get the device pixel ratio for high DPI scaling
        self.pixel_ratio = QtWidgets.QApplication.instance().devicePixelRatio()
        # Base sizes that will be scaled
        self.base_sizes = {
            "window_width": 1000,
            "window_height": 800,
            "min_width": 800,
            "min_height": 600,
            "sidebar_width": 300,
            "font_size": 15,
            "padding": 10,
            "spacing": 10,
            "border_radius": 6,
        }

        self._initUI()
        self._setupConnections()

    def _initUI(self):
        # Create common size policies
        expanding = QtWidgets.QSizePolicy.Expanding
        fixed = QtWidgets.QSizePolicy.Fixed
        self.expanding_fixed = QtWidgets.QSizePolicy(expanding, fixed)
        self.expanding_both = QtWidgets.QSizePolicy(expanding, expanding)

        self.setWindowTitle("NetMate")
        # Scale window geometry and minimum size based on pixel ratio
        scaled_x = int(100 * self.pixel_ratio)
        scaled_y = int(100 * self.pixel_ratio)
        scaled_width = int(self.base_sizes["window_width"] * self.pixel_ratio)
        scaled_height = int(self.base_sizes["window_height"] * self.pixel_ratio)
        self.setGeometry(scaled_x, scaled_y, scaled_width, scaled_height)

        # Set minimum window size with scaling
        min_width = int(self.base_sizes["min_width"] * self.pixel_ratio)
        min_height = int(self.base_sizes["min_height"] * self.pixel_ratio)
        self.setMinimumSize(min_width, min_height)

        # Create central widget and main horizontal layout
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        main_horizontal_layout = QtWidgets.QHBoxLayout(central_widget)
        main_horizontal_layout.setSpacing(10)
        main_horizontal_layout.setContentsMargins(10, 10, 10, 10)

        # Create sidebar
        sidebar_widget = QtWidgets.QWidget()
        # Scale sidebar width
        scaled_sidebar_width = int(self.base_sizes["sidebar_width"] * self.pixel_ratio)
        sidebar_widget.setFixedWidth(scaled_sidebar_width)
        sidebar_widget.setObjectName("sidebar")  # For styling
        sidebar_layout = QtWidgets.QVBoxLayout(sidebar_widget)
        # Scale spacing and margins
        scaled_spacing = int(self.base_sizes["spacing"] * self.pixel_ratio)
        scaled_padding = int(self.base_sizes["padding"] * self.pixel_ratio)
        sidebar_layout.setSpacing(scaled_spacing)
        sidebar_layout.setContentsMargins(
            scaled_padding, scaled_padding, scaled_padding, scaled_padding
        )

        # Create main content area
        main_content_widget = QtWidgets.QWidget()
        main_content_layout = QtWidgets.QVBoxLayout(main_content_widget)
        main_content_layout.setSpacing(scaled_spacing)
        main_content_layout.setContentsMargins(0, 0, 0, 0)

        # Create menu bar
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")
        preferences_menu = menubar.addMenu("Preferences")

        # Add Network Settings submenu
        network_settings_action = preferences_menu.addAction("Network Settings")
        network_settings_action.triggered.connect(self.show_network_settings)

        # Create Mode submenu
        mode_submenu = file_menu.addMenu("Mode")
        config_mode_action = "Enable Config Mode"
        self.toggle_config_mode_action = mode_submenu.addAction(config_mode_action)
        self.toggle_config_mode_action.setCheckable(True)
        self.toggle_config_mode_action.triggered.connect(self.toggle_config_mode)

        # Create submenus under File menu
        credentials_submenu = file_menu.addMenu("Credentials")
        session_submenu = file_menu.addMenu("Session")
        results_submenu = file_menu.addMenu("Results")

        # Add actions to Credentials submenu
        # Add credentials actions
        tip = "Save"
        save_creds = credentials_submenu.addAction("Save Credentials")
        save_creds.setShortcut("Ctrl+S")
        save_creds.setStatusTip(tip)
        save_creds.triggered.connect(self.save_credentials)

        # Add load credentials action
        load_creds = credentials_submenu.addAction("Load Credentials")
        load_creds.triggered.connect(lambda: self.load_credentials())

        # Add actions to Session submenu
        save_session_action = session_submenu.addAction("Save Session")
        save_session_action.triggered.connect(self.save_session)
        load_session_action = session_submenu.addAction("Load Session")
        load_session_action.triggered.connect(self.load_session)

        # Add actions to Results submenu
        save_results_action = results_submenu.addAction("Save Results")
        save_results_action.triggered.connect(self.save_results)

        # Add "View Results" action
        view_results_action = results_submenu.addAction("View Results")
        view_results_action.triggered.connect(self.view_results)

        # Create Log menu
        log_menu = menubar.addMenu("Log")
        # Add actions to Log submenu
        view_log_action = log_menu.addAction("View Log")
        view_log_action.triggered.connect(self.view_log)
        clear_log_action = log_menu.addAction("Clear Log")
        clear_log_action.triggered.connect(self.clear_log)

        # Create credentials section in sidebar
        credentials_group = QtWidgets.QGroupBox("Credentials")
        credentials_group.setObjectName("sidebar-group")
        credentials_layout = QtWidgets.QVBoxLayout()

        # Username field
        username_label = QtWidgets.QLabel("Username:")
        self.username_input = QtWidgets.QLineEdit()
        self.username_input.setSizePolicy(self.expanding_fixed)

        # Password field
        password_label = QtWidgets.QLabel("Password:")
        self.password_input = QtWidgets.QLineEdit()
        self.password_input.setSizePolicy(self.expanding_fixed)
        self.password_input.setEchoMode(QtWidgets.QLineEdit.Password)

        # Device type field
        device_type_label = QtWidgets.QLabel("Device Type:")
        self.device_type = QtWidgets.QComboBox()
        self.device_type.setSizePolicy(self.expanding_fixed)
        self.device_type.addItems(
            [
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
            ]
        )

        # Add fields to credentials layout
        credentials_layout.addWidget(username_label)
        credentials_layout.addWidget(self.username_input)
        credentials_layout.addWidget(password_label)
        credentials_layout.addWidget(self.password_input)
        credentials_layout.addWidget(device_type_label)
        credentials_layout.addWidget(self.device_type)
        credentials_group.setLayout(credentials_layout)

        # Create text areas with size policies
        devices_layout = QtWidgets.QVBoxLayout()
        devices_label = QtWidgets.QLabel("Devices:")
        self.devices_input = QtWidgets.QTextEdit()
        self.devices_input.setSizePolicy(self.expanding_both)
        self.devices_input.setMinimumHeight(100)
        self.devices_input.setPlaceholderText(
            "Enter device IPs or hostnames\n(one per line)"
        )
        devices_layout.addWidget(devices_label)
        devices_layout.addWidget(self.devices_input)

        commands_layout = QtWidgets.QVBoxLayout()
        commands_label = QtWidgets.QLabel("Commands:")
        self.commands_input = QtWidgets.QTextEdit()
        self.commands_input.setSizePolicy(self.expanding_both)
        self.commands_input.setMinimumHeight(100)
        self.commands_input.setPlaceholderText(
            "Enter commands to execute\n(one per line)"
        )
        commands_layout.addWidget(commands_label)
        commands_layout.addWidget(self.commands_input)

        input_area_layout = QtWidgets.QHBoxLayout()
        input_area_layout.addLayout(devices_layout)
        input_area_layout.addLayout(commands_layout)

        # Create progress bar with size policy
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setSizePolicy(self.expanding_fixed)
        self.progress_bar.hide()

        # Create controls section in sidebar
        controls_group = QtWidgets.QGroupBox("Controls")
        controls_group.setObjectName("sidebar-group")
        controls_layout = QtWidgets.QVBoxLayout()

        # Create buttons with full width
        self.run_btn = QtWidgets.QPushButton("Run")
        self.run_btn.setObjectName("run_btn")
        self.pause_btn = QtWidgets.QPushButton("Pause")
        self.pause_btn.setObjectName("pause_btn")
        self.pause_btn.setEnabled(True)
        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.stop_btn.setObjectName("stop_btn")
        self.stop_btn.setEnabled(True)
        self.clear_btn = QtWidgets.QPushButton("Clear Output")
        self.clear_btn.setObjectName("clear_btn")

        # Add buttons to controls layout
        controls_layout.addWidget(self.run_btn)
        controls_layout.addWidget(self.pause_btn)
        controls_layout.addWidget(self.stop_btn)
        controls_layout.addWidget(self.clear_btn)
        controls_group.setLayout(controls_layout)

        # Create output area with size policy
        output_label = QtWidgets.QLabel("Output:")
        self.output_area = QtWidgets.QTextEdit()
        self.output_area.setReadOnly(True)
        self.output_area.setAcceptRichText(True)
        self.output_area.setSizePolicy(self.expanding_both)
        self.output_area.setMinimumHeight(200)

        # Create size grip
        size_grip = QtWidgets.QSizeGrip(central_widget)
        size_grip.setFixedSize(20, 20)

        # Create bottom layout for size grip
        bottom_layout = QtWidgets.QHBoxLayout()
        bottom_layout.addStretch()
        bottom_layout.addWidget(size_grip)

        # Add groups to sidebar
        sidebar_layout.addWidget(credentials_group)
        sidebar_layout.addWidget(controls_group)
        sidebar_layout.addWidget(self.progress_bar)
        sidebar_layout.addStretch()

        # Create splitter for resizable areas
        splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)

        # Create container for input area
        input_container = QtWidgets.QWidget()
        input_container.setLayout(input_area_layout)

        # Create container for output area
        output_container = QtWidgets.QWidget()
        output_layout = QtWidgets.QVBoxLayout(output_container)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.addWidget(output_label)
        output_layout.addWidget(self.output_area)

        # Add widgets to splitter
        splitter.addWidget(input_container)
        splitter.addWidget(output_container)

        # Set initial sizes (40% input, 60% output)
        splitter.setSizes([400, 600])

        # Add content to main area
        main_content_layout.addWidget(splitter)
        main_content_layout.addLayout(bottom_layout)

        # Add sidebar and main content to horizontal layout
        main_horizontal_layout.addWidget(sidebar_widget)
        main_horizontal_layout.addWidget(main_content_widget)

    def toggle_config_mode(self):
        """Toggle between normal and configuration mode."""
        self.is_config_mode = self.toggle_config_mode_action.isChecked()
        mode = "Configuration" if self.is_config_mode else "Normal"
        placeholder = f"Enter commands to execute ({mode} Mode)\n(one per line)"
        self.commands_input.setPlaceholderText(placeholder)

    def view_log(self):
        """View the contents of netmiko.log file."""
        try:
            if os.path.exists("netmiko.log"):
                with open("netmiko.log", "r", encoding="utf-8") as f:
                    log_content = f.read()

                log_window = QtWidgets.QMainWindow(self)
                log_window.setWindowTitle("Netmiko Log Viewer")
                log_window.setGeometry(200, 200, 800, 600)
                log_window.setMinimumSize(600, 400)

                central_widget = QtWidgets.QWidget()
                layout = QtWidgets.QVBoxLayout(central_widget)

                # Create log text area with proper size policies
                expanding = QtWidgets.QSizePolicy.Expanding
                log_text = QtWidgets.QTextEdit()
                log_text.setReadOnly(True)
                log_text.setPlainText(log_content)
                log_text.setSizePolicy(expanding, expanding)
                log_text.setMinimumHeight(300)
                log_text.setMinimumWidth(500)

                # Set size policies for the central widget
                central_widget.setSizePolicy(expanding, expanding)

                # Add size grip with proper alignment
                size_grip = QtWidgets.QSizeGrip(central_widget)
                size_grip.setFixedSize(20, 20)

                bottom_layout = QtWidgets.QHBoxLayout()
                bottom_layout.addStretch()
                bottom_layout.addWidget(size_grip)

                layout.addWidget(log_text)
                layout.addLayout(bottom_layout)

                log_window.setCentralWidget(central_widget)
                log_window.show()
            else:
                QtWidgets.QMessageBox.warning(self, "Error", "Log file not found.")
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Error", f"Failed to read log file: {str(e)}"
            )

    def clear_log(self):
        """Clear the contents of netmiko.log file."""
        try:
            log_file = "netmiko.log"
            if os.path.exists(log_file):
                # Show confirmation dialog
                reply = QtWidgets.QMessageBox.question(
                    self,
                    "Confirm Clear Log",
                    "Are you sure you want to clear the log file?",
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                    QtWidgets.QMessageBox.No,
                )

                if reply == QtWidgets.QMessageBox.Yes:
                    # Clear the log file and write a timestamp
                    with open(log_file, "w", encoding="utf-8") as f:
                        f.write(f"# Log cleared on {datetime.now()}\n")
                    QtWidgets.QMessageBox.information(
                        self, "Success", "Log file cleared successfully."
                    )
            else:
                QtWidgets.QMessageBox.warning(self, "Error", "Log file not found.")
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Error", f"Failed to clear log file: {str(e)}"
            )

    def _setupConnections(self):
        self.run_btn.clicked.connect(self.run_commands)
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.clear_btn.clicked.connect(self.clear_output)
        self.stop_btn.clicked.connect(self.stop_execution)

    def handle_output(self, username, host, command, output):
        result = {
            "username": username,
            "host": host,
            "command": command,
            "output": output,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.results.append(result)

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor = self.output_area.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        self.output_area.setTextCursor(cursor)

        separator = f'<span style="color: {self.COLORS["separator"]}">{"=" * 70}</span>'

        if "CONNECTION ERROR" in command or "ERROR" in command:
            self.output_area.append(f"\n{separator}")
            self.output_area.append(
                f'<span style="color: {self.COLORS["timestamp"]}">[{timestamp}]</span> '
                f'<span style="color: {self.COLORS["error"]}">ERROR: {host}</span>'
            )
            self.output_area.append(
                f'<span style="color: {self.COLORS["error"]}">{output}</span>'
            )
            self.output_area.append(separator)
        else:
            self.output_area.append(f"\n{separator}")
            # Timestamp and connection status
            self.output_area.append(
                f'<span style="color: {self.COLORS["timestamp"]}">[{timestamp}]</span> '
                f'<span style="color: {self.COLORS["success"]}">Connected</span>'
            )
            self.output_area.append(
                f'<span style="color: {self.COLORS["success"]}">to {host} as {username}</span>'
            )
            # Command with blue color
            self.output_area.append(
                f'\n<span style="color: {self.COLORS["command"]}">$ {command}</span>'
            )
            # Output in light gray
            self.output_area.append(
                f'<span style="color: {self.COLORS["output"]}">{output}</span>'
            )
            self.output_area.append(separator)

    def handle_progress(self, message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor = self.output_area.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        self.output_area.setTextCursor(cursor)
        # Format progress messages with timestamp in gray
        self.output_area.append(
            f'\n<span style="color: {self.COLORS["timestamp"]}">[{timestamp}]</span>\n{message}'
        )

    def update_progress(self):
        """Update progress bar when a command is completed."""
        self.completed_commands += 1
        self.progress_bar.setValue(self.completed_commands)
        # Update progress text
        percent = int((self.completed_commands / self.total_commands) * 100)
        progress_text = (
            f"{percent}% ({self.completed_commands}/{self.total_commands} commands)"
        )
        self.progress_bar.setFormat(progress_text)

    def run_commands(self):
        # Validate credentials
        username = self.username_input.text().strip()
        password = self.password_input.text().strip()
        if not username or not password:
            error_msg = (
                f'\n<span style="color: {self.COLORS["error"]}">'
                f"[ERROR] Please enter username and password</span>"
            )
            self.output_area.append(error_msg)
            QtWidgets.QMessageBox.warning(
                self, "Error", "Please enter username and password"
            )
            return

        # Validate devices
        devices_text = self.devices_input.toPlainText().strip()
        if not devices_text:
            error_msg = (
                f'\n<span style="color: {self.COLORS["error"]}">'
                f"[ERROR] Please enter at least one device</span>"
            )
            self.output_area.append(error_msg)
            QtWidgets.QMessageBox.warning(
                self, "Error", "Please enter at least one device"
            )
            return

        # Parse and validate devices
        devices = [d.strip() for d in devices_text.split("\n") if d.strip()]
        if not devices:
            error_msg = (
                f'\n<span style="color: {self.COLORS["error"]}">'
                f"[ERROR] No valid devices found</span>"
            )
            self.output_area.append(error_msg)
            QtWidgets.QMessageBox.warning(self, "Error", "No valid devices found")
            return

        # Validate commands
        commands_text = self.commands_input.toPlainText().strip()
        if not commands_text:
            error_msg = (
                f'\n<span style="color: {self.COLORS["error"]}">'
                f"[ERROR] Please enter at least one command</span>"
            )
            self.output_area.append(error_msg)
            QtWidgets.QMessageBox.warning(
                self, "Error", "Please enter at least one command"
            )
            return

        # Parse and validate commands
        commands = [c.strip() for c in commands_text.split("\n") if c.strip()]
        if not commands:
            error_msg = (
                f'\n<span style="color: {self.COLORS["error"]}">'
                f"[ERROR] No valid commands found</span>"
            )
            self.output_area.append(error_msg)
            QtWidgets.QMessageBox.warning(self, "Error", "No valid commands found")
            return

        # Clear output and initialize progress
        self.output_area.clear()
        self.results.clear()  # Clear previous results

        # Show start message
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        mode_str = "Configuration" if self.is_config_mode else "Normal"
        start_msg = (
            f'<span style="color: {self.COLORS["timestamp"]}">[{timestamp}]</span> '
            f'Starting execution in <span style="color: {self.COLORS["command"]}">'
            f"{mode_str} Mode</span>...\n"
            f'<span style="color: {self.COLORS["success"]}">Devices: {len(devices)}, '
            f"Commands: {len(commands)}</span>"
        )
        self.output_area.append(start_msg)

        # Initialize progress tracking
        self.completed_commands = 0
        # In config mode, treat all commands as one unit per device
        cmd_multiplier = 1 if self.is_config_mode else len(commands)
        self.total_commands = len(devices) * cmd_multiplier

        # Configure progress bar
        self.progress_bar.setMaximum(self.total_commands)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p% (%v/%m commands)")
        self.progress_bar.show()

        self.stop_btn.setEnabled(True)
        self.run_btn.setEnabled(False)

        # Create list of device info dictionaries
        devices_info = [
            {
                "device_type": self.device_type.currentText(),
                "host": device.strip(),
                "username": self.username_input.text(),
                "password": self.password_input.text(),
            }
            for device in devices
        ]

        # Create single worker for all devices
        worker = NetmikoWorker(devices_info, commands, self.is_config_mode)
        worker.output_ready.connect(self.handle_output)
        worker.progress_update.connect(self.handle_progress)
        worker.command_completed.connect(self.update_progress)
        worker.batch_completed.connect(self.handle_batch_completed)
        worker.finished.connect(lambda w=worker: self.handle_worker_finished(w))
        self.workers.append(worker)
        worker.start()

    def handle_batch_completed(self, completed_count):
        """Handle completion of a device batch."""
        self.completed_commands += completed_count
        self.progress_bar.setValue(self.completed_commands)
        # Update progress text
        percent = int((self.completed_commands / self.total_commands) * 100)
        progress_text = (
            f"{percent}% ({self.completed_commands}/{self.total_commands} commands)"
        )
        self.progress_bar.setFormat(progress_text)

    def handle_worker_finished(self, worker):
        if worker in self.workers:
            self.workers.remove(worker)

        if not self.workers:
            self.run_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)  # Disable Pause button
            self.stop_btn.setEnabled(False)  # Disable Stop button
            self.progress_bar.hide()
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.output_area.append(
                f'\n<span style="color: {self.COLORS["timestamp"]}">[{ts}]</span> '
                f'<span style="color: {self.COLORS["success"]}">Done</span>'
            )

    def toggle_pause(self):
        """Toggle the pause state of the workers."""
        if not self.workers:
            QtWidgets.QMessageBox.warning(
                self, "Error", "No running tasks to pause or resume."
            )
            return

        # Toggle based on current button text
        if self.pause_btn.text() == "Pause":
            # Change button to 'Resume' and pause workers
            self.pause_btn.setText("Resume")
            self.pause_btn.setObjectName("resume_btn")  # Change style
            self.pause_btn.setStyleSheet("""
                #resume_btn {
                    background-color: #3b82f6;
                    border: 1px solid #2563eb;
                }
                #resume_btn:hover {
                    background-color: #2563eb;
                }
                #resume_btn:pressed {
                    background-color: #1d4ed8;
                }
            """)
            for worker in self.workers:
                if worker.isRunning():
                    worker.pause()
        else:
            # Change button to 'Pause' and resume workers
            self.pause_btn.setText("Pause")
            self.pause_btn.setObjectName("pause_btn")  # Restore original style
            self.pause_btn.setStyleSheet("")  # Remove custom style to use QSS
            for worker in self.workers:
                if worker.isRunning():
                    worker.resume()

    def stop_execution(self):
        """Stops all worker threads."""
        for worker in self.workers:
            if worker.isRunning():
                worker.stop()  # Signal the thread to stop
                worker.wait()  # Wait for the thread to finish

        self.workers.clear()  # Clear the workers list

        self.run_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.progress_bar.hide()

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.output_area.append(
            f'\n<span style="color: {self.COLORS["timestamp"]}">[{timestamp}]</span> '
            f'<span style="color: {self.COLORS["error"]}">Execution stopped by user</span>'
        )

    def clear_output(self):
        self.output_area.clear()
        self.results.clear()
        self.progress_bar.hide()

    def save_results(self):
        if not self.results:
            QtWidgets.QMessageBox.warning(self, "Error", "No results to save")
            return

        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Results", "", "CSV Files (*.csv)"
        )

        if filename:
            try:
                with open(filename, "w", encoding="utf-8", newline="") as f:
                    writer = csv.DictWriter(
                        f,
                        fieldnames=[
                            "timestamp",
                            "username",
                            "host",
                            "command",
                            "output",
                        ],
                    )
                    writer.writeheader()
                    writer.writerows(self.results)

                QtWidgets.QMessageBox.information(
                    self, "Success", "Results saved successfully"
                )
            except Exception as e:
                QtWidgets.QMessageBox.critical(
                    self, "Error", f"Failed to save results: {str(e)}"
                )

    def view_results(self):
        """Display the results CSV in a properly formatted table."""
        try:
            # Increase CSV field size limit to 1MB
            csv.field_size_limit(1024 * 1024)  # 1MB in bytes

            # Path to the CSV file
            filename, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "Open Results File", "", "CSV Files (*.csv)"
            )

            if filename:  # Check if the user selected a file
                # Read the CSV content
                with open(filename, "r", encoding="utf-8") as file:
                    reader = csv.DictReader(file)
                    headers = reader.fieldnames  # Get headers
                    data = [row for row in reader]  # Read rows as dictionaries

                # Create a dialog window
                dialog = QtWidgets.QDialog(self)
                dialog.setWindowTitle("View Results")
                dialog.setGeometry(100, 100, 1000, 600)
                dialog.setMinimumSize(800, 400)

                layout = QtWidgets.QVBoxLayout(dialog)
                layout.setSpacing(10)
                layout.setContentsMargins(10, 10, 10, 10)

                # Create a table to display the CSV data
                table = QtWidgets.QTableWidget(dialog)
                table.setRowCount(len(data))
                table.setColumnCount(len(headers))
                table.setHorizontalHeaderLabels(headers)

                # Populate the table
                for row_idx, row in enumerate(data):
                    for col_idx, header in enumerate(headers):
                        value = row[header]  # Get cell value
                        # Handle multiline output
                        if header == "output":
                            value = value.replace("\\n", "\n")
                        item = QtWidgets.QTableWidgetItem(value.strip())
                        # Set text alignment
                        alignment = QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop
                        item.setTextAlignment(alignment)

                        # Set item flags
                        flags = QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled
                        item.setFlags(flags)
                        table.setItem(row_idx, col_idx, item)

                # Auto-resize rows and columns to fit content
                table.resizeColumnsToContents()
                table.resizeRowsToContents()

                # Enable word wrapping for multiline content
                table.setWordWrap(True)

                # Add size grip
                size_grip = QtWidgets.QSizeGrip(dialog)
                size_grip.setFixedSize(20, 20)

                bottom_layout = QtWidgets.QHBoxLayout()
                bottom_layout.addStretch()
                bottom_layout.addWidget(size_grip)

                # Add widgets to layout
                layout.addWidget(table)
                layout.addLayout(bottom_layout)

                dialog.setLayout(layout)
                dialog.exec_()  # Show the dialog

        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Error", f"Failed to open CSV file: {str(e)}"
            )

    def save_session(self):
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Session", "", "JSON Files (*.json)"
        )

        if filename:
            try:
                session = {
                    "username": self.username_input.text(),
                    "device_type": self.device_type.currentText(),
                    "devices": self.devices_input.toPlainText(),
                    "commands": self.commands_input.toPlainText(),
                    "is_config_mode": self.is_config_mode,
                }

                with open(filename, "w", encoding="utf-8") as f:
                    json.dump(session, f, indent=2)

                QtWidgets.QMessageBox.information(
                    self, "Success", "Session saved successfully"
                )
            except Exception as e:
                QtWidgets.QMessageBox.critical(
                    self, "Error", f"Failed to save session: {str(e)}"
                )

    def load_session(self):
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load Session", "", "JSON Files (*.json)"
        )

        if filename:
            try:
                with open(filename, "r", encoding="utf-8") as f:
                    session = json.load(f)

                self.username_input.setText(session.get("username", ""))
                self.devices_input.setPlainText(session.get("devices", ""))
                self.commands_input.setPlainText(session.get("commands", ""))

                device_type = session.get("device_type")
                if device_type:
                    index = self.device_type.findText(device_type)
                    if index >= 0:
                        self.device_type.setCurrentIndex(index)

                # Load config mode state
                is_config_mode = session.get("is_config_mode", False)
                self.toggle_config_mode_action.setChecked(is_config_mode)
                self.toggle_config_mode()

                QtWidgets.QMessageBox.information(
                    self, "Success", "Session loaded successfully"
                )
            except Exception as e:
                QtWidgets.QMessageBox.critical(
                    self, "Error", f"Failed to load session: {str(e)}"
                )

    def show_network_settings(self):
        """Show the network settings dialog."""
        dialog = NetworkSettingsDialog(self)
        dialog.exec_()

    def save_credentials(self):
        try:
            import keyring

            service_name = "NetMate"
            username = self.username_input.text().strip()
            password = self.password_input.text().strip()

            if username and password:
                # Save the credentials
                keyring.set_password(service_name, username, password)

                # Update the list of saved usernames
                try:
                    saved_users = keyring.get_password(service_name, "_saved_users_")
                    usernames = json.loads(saved_users) if saved_users else []
                except Exception:
                    usernames = []

                if username not in usernames:
                    usernames.append(username)
                    keyring.set_password(
                        service_name, "_saved_users_", json.dumps(usernames)
                    )

                QtWidgets.QMessageBox.information(
                    self, "Success", "Credentials saved successfully"
                )
            else:
                QtWidgets.QMessageBox.warning(
                    self, "Error", "Please enter username and password"
                )
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Error", f"Failed to save credentials: {str(e)}"
            )

    def load_credentials(self):
        try:
            import keyring

            service_name = "NetMate"

            # Get all saved usernames
            try:
                saved_users = keyring.get_password(service_name, "_saved_users_")
                usernames = json.loads(saved_users) if saved_users else []
            except Exception:
                usernames = []

            if not usernames:
                QtWidgets.QMessageBox.warning(
                    self,
                    "No Saved Credentials",
                    "No saved credentials found. Please save credentials first.",
                )
                return

            # Show dropdown with saved usernames
            username, ok = QtWidgets.QInputDialog.getItem(
                self,
                "Load Credentials",
                "Select username:",
                usernames,
                0,  # Current index
                False,  # Non-editable
            )

            if ok and username:
                password = keyring.get_password(service_name, username)
                if password:
                    self.username_input.setText(username)
                    self.password_input.setText(password)
                    QtWidgets.QMessageBox.information(
                        self, "Success", "Credentials loaded successfully"
                    )
                else:
                    QtWidgets.QMessageBox.warning(
                        self, "Error", "No saved credentials found for this username"
                    )
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Error", f"Failed to load credentials: {str(e)}"
            )


class NetworkSettingsDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Network Settings")
        self.setMinimumWidth(400)
        self.init_ui()
        self.load_settings()

    def init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        # Thread Pool Settings Group
        pool_group = QtWidgets.QGroupBox("Thread Pool Settings")
        pool_layout = QtWidgets.QVBoxLayout()

        # Maximum Threads
        threads_layout = QtWidgets.QHBoxLayout()
        threads_label = QtWidgets.QLabel("Maximum Threads:")
        self.max_threads = QtWidgets.QSpinBox()
        self.max_threads.setRange(1, 50)
        self.max_threads.setValue(10)
        threads_layout.addWidget(threads_label)
        threads_layout.addWidget(self.max_threads)

        # Batch Size
        batch_layout = QtWidgets.QHBoxLayout()
        batch_label = QtWidgets.QLabel("Batch Size:")
        self.batch_size = QtWidgets.QSpinBox()
        self.batch_size.setRange(1, 100)
        self.batch_size.setValue(5)
        batch_layout.addWidget(batch_label)
        batch_layout.addWidget(self.batch_size)

        pool_layout.addLayout(threads_layout)
        pool_layout.addLayout(batch_layout)
        pool_group.setLayout(pool_layout)

        # Connection Timeouts Group
        conn_group = QtWidgets.QGroupBox("Connection Timeouts")
        conn_layout = QtWidgets.QVBoxLayout()

        # SSH Check Timeout
        ssh_layout = QtWidgets.QHBoxLayout()
        ssh_label = QtWidgets.QLabel("SSH Check Timeout (s):")
        self.ssh_timeout = QtWidgets.QSpinBox()
        self.ssh_timeout.setRange(1, 10)
        self.ssh_timeout.setValue(3)
        ssh_layout.addWidget(ssh_label)
        ssh_layout.addWidget(self.ssh_timeout)

        # Connection Retry
        retry_layout = QtWidgets.QHBoxLayout()
        retry_label = QtWidgets.QLabel("Connection Retry (s):")
        self.conn_retry = QtWidgets.QSpinBox()
        self.conn_retry.setRange(5, 60)
        self.conn_retry.setValue(30)
        retry_layout.addWidget(retry_label)
        retry_layout.addWidget(self.conn_retry)

        conn_layout.addLayout(ssh_layout)
        conn_layout.addLayout(retry_layout)
        conn_group.setLayout(conn_layout)

        # Operation Timeouts Group
        op_group = QtWidgets.QGroupBox("Operation Timeouts")
        op_layout = QtWidgets.QVBoxLayout()

        # Command Read Timeout
        cmd_layout = QtWidgets.QHBoxLayout()
        cmd_label = QtWidgets.QLabel("Command Read (s):")
        self.cmd_timeout = QtWidgets.QSpinBox()
        self.cmd_timeout.setRange(30, 300)
        self.cmd_timeout.setValue(120)
        cmd_layout.addWidget(cmd_label)
        cmd_layout.addWidget(self.cmd_timeout)

        # Authentication Timeout
        auth_layout = QtWidgets.QHBoxLayout()
        auth_label = QtWidgets.QLabel("Authentication (s):")
        self.auth_timeout = QtWidgets.QSpinBox()
        self.auth_timeout.setRange(5, 60)
        self.auth_timeout.setValue(30)
        auth_layout.addWidget(auth_label)
        auth_layout.addWidget(self.auth_timeout)

        op_layout.addLayout(cmd_layout)
        op_layout.addLayout(auth_layout)
        op_group.setLayout(op_layout)

        # Add groups to main layout
        layout.addWidget(pool_group)
        layout.addWidget(conn_group)
        layout.addWidget(op_group)

        # Buttons
        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)

    def load_settings(self):
        """Load saved network settings."""
        try:
            if os.path.exists("network_settings.json"):
                with open("network_settings.json", "r") as f:
                    settings = json.load(f)
                    self.ssh_timeout.setValue(settings.get("ssh_timeout", 3))
                    self.conn_retry.setValue(settings.get("conn_retry", 30))
                    self.cmd_timeout.setValue(settings.get("cmd_timeout", 120))
                    self.auth_timeout.setValue(settings.get("auth_timeout", 30))
                    self.max_threads.setValue(settings.get("max_threads", 10))
                    self.batch_size.setValue(settings.get("batch_size", 5))
        except Exception as e:
            print(f"Error loading settings: {e}")

    def accept(self):
        """Save settings when OK is clicked."""
        settings = {
            "ssh_timeout": self.ssh_timeout.value(),
            "conn_retry": self.conn_retry.value(),
            "cmd_timeout": self.cmd_timeout.value(),
            "auth_timeout": self.auth_timeout.value(),
            "max_threads": self.max_threads.value(),
            "batch_size": self.batch_size.value(),
        }
        try:
            with open("network_settings.json", "w") as f:
                json.dump(settings, f, indent=2)
        except Exception as e:
            print(f"Error saving settings: {e}")
        super().accept()


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)

    # Dynamically load the QSS file
    try:
        qss_file = resource_path("styles.qss")
        with open(qss_file, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())
            print("QSS successfully applied.")
    except Exception as e:
        print(f"Failed to apply QSS: {e}")

    # Initialize and show the main window
    window = DeviceManager()
    window.show()
    sys.exit(app.exec_())
