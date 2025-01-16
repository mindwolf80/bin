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
    def __init__(self):
        super().__init__()
        self.workers = []
        self.results = []
        self.completed_commands = 0
        self.total_commands = 0
        self.is_config_mode = False
        self._initUI()
        self._setupConnections()

    def _initUI(self):
        # Create common size policies
        expanding = QtWidgets.QSizePolicy.Expanding
        fixed = QtWidgets.QSizePolicy.Fixed
        self.expanding_fixed = QtWidgets.QSizePolicy(expanding, fixed)
        self.expanding_both = QtWidgets.QSizePolicy(expanding, expanding)

        self.setWindowTitle("NetMate")
        self.setGeometry(100, 100, 1000, 800)
        self.setMinimumSize(800, 600)  # Set minimum window size

        # Create central widget and main layout
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QtWidgets.QVBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # Create menu bar
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")

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

        # Create input fields with size policies
        credentials_layout = QtWidgets.QHBoxLayout()
        credentials_layout.setSpacing(10)

        username_layout = QtWidgets.QVBoxLayout()
        username_label = QtWidgets.QLabel("Username:")
        self.username_input = QtWidgets.QLineEdit()
        # Apply size policies
        self.username_input.setSizePolicy(self.expanding_fixed)
        username_layout.addWidget(username_label)
        username_layout.addWidget(self.username_input)

        password_layout = QtWidgets.QVBoxLayout()
        password_label = QtWidgets.QLabel("Password:")
        self.password_input = QtWidgets.QLineEdit()
        self.password_input.setSizePolicy(self.expanding_fixed)
        self.password_input.setEchoMode(QtWidgets.QLineEdit.Password)
        password_layout.addWidget(password_label)
        password_layout.addWidget(self.password_input)

        device_type_layout = QtWidgets.QVBoxLayout()
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
        device_type_layout.addWidget(device_type_label)
        device_type_layout.addWidget(self.device_type)

        credentials_layout.addLayout(username_layout)
        credentials_layout.addLayout(password_layout)
        credentials_layout.addLayout(device_type_layout)

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

        # Create buttons
        button_layout = QtWidgets.QHBoxLayout()

        # Run Button
        self.run_btn = QtWidgets.QPushButton("Run Commands")
        self.run_btn.setObjectName("run_btn")

        # Pause Button
        self.pause_btn = QtWidgets.QPushButton("Pause")
        self.pause_btn.setObjectName("pause_btn")
        self.pause_btn.setEnabled(True)  # Initially enabled

        # Stop Button
        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.stop_btn.setObjectName("stop_btn")
        self.stop_btn.setEnabled(True)  # Initially enabled

        # Clear Terminal Output Button
        self.clear_btn = QtWidgets.QPushButton("Clear Output")

        # Add buttons to layout
        button_layout.addWidget(self.run_btn)
        button_layout.addWidget(self.pause_btn)
        button_layout.addWidget(self.stop_btn)
        button_layout.addWidget(self.clear_btn)

        # Create output area with size policy
        output_label = QtWidgets.QLabel("Output:")
        self.output_area = QtWidgets.QTextEdit()
        self.output_area.setReadOnly(True)
        self.output_area.setSizePolicy(self.expanding_both)
        self.output_area.setMinimumHeight(200)

        # Create size grip
        size_grip = QtWidgets.QSizeGrip(central_widget)
        size_grip.setFixedSize(20, 20)

        # Create bottom layout for size grip
        bottom_layout = QtWidgets.QHBoxLayout()
        bottom_layout.addStretch()
        bottom_layout.addWidget(size_grip)

        # Add all layouts to main layout with proper spacing
        main_layout.addLayout(credentials_layout)
        main_layout.addLayout(input_area_layout)
        main_layout.addWidget(self.progress_bar)
        main_layout.addLayout(button_layout)
        main_layout.addWidget(output_label)
        main_layout.addWidget(self.output_area)
        main_layout.addLayout(bottom_layout)

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

        separator = "=" * 70
        if "CONNECTION ERROR" in command:
            self.output_area.append(f"\n{separator}")
            self.output_area.append(f"[{timestamp}] ERROR: {host}")
            self.output_area.append(f"{output}")
            self.output_area.append(f"{separator}")
        else:
            self.output_area.append(f"\n{separator}")
            ts = f"[{timestamp}]"
            self.output_area.append(f"{ts} Connected")
            self.output_area.append(f"to {host} as {username}")
            self.output_area.append(f"\n$ {command}")
            self.output_area.append(f"{output}")
            self.output_area.append(f"{separator}")

    def handle_progress(self, message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor = self.output_area.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        self.output_area.setTextCursor(cursor)
        ts = f"[{timestamp}]"
        self.output_area.append(f"\n{ts}\n{message}")

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
            error_msg = "\n[ERROR] Please enter username and password"
            self.output_area.append(error_msg)
            QtWidgets.QMessageBox.warning(
                self, "Error", "Please enter username and password"
            )
            return

        # Validate devices
        devices_text = self.devices_input.toPlainText().strip()
        if not devices_text:
            error_msg = "\n[ERROR] Please enter at least one device"
            self.output_area.append(error_msg)
            QtWidgets.QMessageBox.warning(
                self, "Error", "Please enter at least one device"
            )
            return

        # Parse and validate devices
        devices = [d.strip() for d in devices_text.split("\n") if d.strip()]
        if not devices:
            error_msg = "\n[ERROR] No valid devices found"
            self.output_area.append(error_msg)
            QtWidgets.QMessageBox.warning(self, "Error", "No valid devices found")
            return

        # Validate commands
        commands_text = self.commands_input.toPlainText().strip()
        if not commands_text:
            error_msg = "\n[ERROR] Please enter at least one command"
            self.output_area.append(error_msg)
            QtWidgets.QMessageBox.warning(
                self, "Error", "Please enter at least one command"
            )
            return

        # Parse and validate commands
        commands = [c.strip() for c in commands_text.split("\n") if c.strip()]
        if not commands:
            error_msg = "\n[ERROR] No valid commands found"
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
            f"[{timestamp}] Starting execution in {mode_str} Mode...\n"
            f"Devices: {len(devices)}, Commands: {len(commands)}"
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

        for device in devices:
            device_info = {
                "device_type": self.device_type.currentText(),
                "host": device.strip(),
                "username": self.username_input.text(),
                "password": self.password_input.text(),
            }

            worker = NetmikoWorker(device_info, commands, self.is_config_mode)
            worker.output_ready.connect(self.handle_output)
            worker.progress_update.connect(self.handle_progress)
            worker.command_completed.connect(self.update_progress)
            worker.finished.connect(lambda w=worker: self.handle_worker_finished(w))
            self.workers.append(worker)
            worker.start()

    def handle_worker_finished(self, worker):
        if worker in self.workers:
            self.workers.remove(worker)

        if not self.workers:
            self.run_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)  # Disable Pause button
            self.stop_btn.setEnabled(False)  # Disable Stop button
            self.progress_bar.hide()
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.output_area.append(f"\n[{ts}] Done")

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
            for worker in self.workers:
                if worker.isRunning():
                    worker.pause()
        else:
            # Change button to 'Pause' and resume workers
            self.pause_btn.setText("Pause")
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
        self.output_area.append(f"\n[{timestamp}] Execution stopped by user")

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
                except:
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
            except:
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
