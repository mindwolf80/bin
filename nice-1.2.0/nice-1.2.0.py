import os
import sys
import time
from datetime import datetime
from netmiko import ConnectHandler, NetMikoTimeoutException, NetMikoAuthenticationException
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QTextEdit, QPushButton,
                             QFileDialog, QMessageBox, QCheckBox, QRadioButton, QButtonGroup, QSpacerItem, QSizePolicy,
                             QProgressBar, QGridLayout)
from PyQt5.QtGui import QFont, QColor, QPalette
from PyQt5.QtCore import Qt
import pandas as pd
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning, module='paramiko')

# Global flag for canceling script execution
cancel_execution = False

# Define minimum required headers
required_headers = ['ip', 'dns', 'command']

# Function to check headers
def check_headers(file_path, file_type):
    if file_type == 'csv':
        df = pd.read_csv(file_path)
    elif file_type == 'xlsx':
        df = pd.read_excel(file_path, engine='openpyxl')
    else:
        return False
    
    headers = df.columns.tolist()
    return all(header in headers for header in required_headers)

# Function to read device information from the selected file
def read_device_info(file_path, file_type):
    if not check_headers(file_path, file_type):
        raise ValueError("File format is incorrect. Ensure the file contains the required headers: 'ip', 'dns', 'command'.")
    
    devices = {}
    if file_type == 'txt':
        with open(file_path, 'r') as file:
            lines = file.readlines()
            current_device = None
            commands = []

            for line in lines:
                stripped_line = line.strip()
                if stripped_line.startswith("# Device Info:"):
                    if current_device:
                        ip, dns = current_device
                        if (ip, dns) in devices:
                            devices[(ip, dns)].extend(commands)
                        else:
                            devices[(ip, dns)] = commands
                    device_info = stripped_line.split(": ")[1]
                    ip, dns = device_info.split(',')
                    current_device = (ip, dns)
                    commands = []
                elif current_device:
                    commands.append(stripped_line)
            
            if current_device:  # Add the last device if the file doesn't end with a blank line
                ip, dns = current_device
                if (ip, dns) in devices:
                    devices[(ip, dns)].extend(commands)
                else:
                    devices[(ip, dns)] = commands
    elif file_type == 'csv' or file_type == 'xlsx':
        df = pd.read_csv(file_path) if file_type == 'csv' else pd.read_excel(file_path, header=0, engine='openpyxl')
        for _, row in df.iterrows():
            ip, dns, command = row[0], row[1], row[2]
            if (ip, dns) in devices:
                devices[(ip, dns)].append(command)
            else:
                devices[(ip, dns)] = [command]
    return devices

# Function to create directories if they do not exist
def create_directories():
    os.makedirs('logs/successful', exist_ok=True)
    os.makedirs('logs/failure', exist_ok=True)

# Function to execute commands on devices
def execute_commands_on_devices(username, password, secret, use_secret, devices_file_path, file_type, log_text_edit, manual_commands=None, progress_bar=None):
    global cancel_execution
    try:
        devices = read_device_info(devices_file_path, file_type)
    except ValueError as e:
        log_text_edit.append(str(e))
        QMessageBox.warning(None, "File Error", str(e))
        return
    
    create_directories()
    
    failed_devices_file = 'logs/failure/failed_devices.txt'
    
    total_devices = len(devices)
    progress_bar.setMaximum(total_devices)
    
    for index, ((ip, hostname), device_commands) in enumerate(devices.items()):
        if cancel_execution:
            log_text_edit.append("Execution canceled by user.\n")
            break
        
        if manual_commands:
            device_commands = manual_commands.strip().split('\n')
            
        device = {
            'device_type': 'cisco_ios',  # Change this if you use a different device type
            'ip': ip,
            'username': username,
            'password': password,
            'secret': secret,
        }
        
        success = False
        for attempt in range(2):  # Try up to 2 times
            if cancel_execution:
                log_text_edit.append("Execution canceled by user.\n")
                break
            try:
                log_text_edit.append(f"Attempting to connect to device {hostname} ({ip}) (Attempt {attempt + 1})...")
                QApplication.processEvents()
                connection = ConnectHandler(**device)
                log_text_edit.append(f"Successfully connected to device {hostname} ({ip}).")
                QApplication.processEvents()
                if use_secret:
                    connection.enable()
                
                timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                log_filename = f'logs/successful/{hostname}_{ip}_{timestamp}.txt'
                
                with open(log_filename, 'w') as log_file:
                    for command in device_commands:
                        if cancel_execution:
                            log_text_edit.append("Execution canceled by user.\n")
                            break
                        output = connection.send_command(command, expect_string=r'[>#]', read_timeout=60)
                        log_text_edit.append(f"Output from device {hostname} ({ip}) for command '{command}':\n{output}\n")
                        QApplication.processEvents()
                        log_file.write(f"Output from device {hostname} ({ip}) for command '{command}' at {timestamp}:\n{output}\n\n")
                
                connection.disconnect()
                success = True
                break
            except (NetMikoTimeoutException, NetMikoAuthenticationException) as e:
                log_text_edit.append(f"Attempt {attempt + 1} failed to connect to device {hostname} ({ip}): {e}\n")
                QApplication.processEvents()
                time.sleep(5)  # Wait 5 seconds before retrying
            except Exception as e:
                log_text_edit.append(f"An unexpected error occurred: {e}\n")
                QApplication.processEvents()
                break
        
        if not success and not cancel_execution:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            log_text_edit.append(f"Failed to connect to device {hostname} ({ip}) after 2 attempts.\nCommon causes of this problem are:\n1. Incorrect hostname or IP address.\n2. Wrong TCP port.\n3. Intermediate firewall blocking access.\n4. Device might be down.\n")
            QApplication.processEvents()
            with open(failed_devices_file, 'a') as fd_file:
                fd_file.write(f"{timestamp} - {hostname} {ip}\n")

        # Add a 5-second delay before moving to the next device
        if index < total_devices - 1:  # Don't delay after the last device
            log_text_edit.append(f"Waiting 5 seconds before moving to the next device...\n")
            QApplication.processEvents()
            time.sleep(5)
        
        progress_bar.setValue(index + 1)
        QApplication.processEvents()

    log_text_edit.append("\nScript execution completed. Please check the 'logs/successful' directory for detailed output and 'logs/failure' directory for any failed connections.\n")
    QApplication.processEvents()

def run_script(username_entry, password_entry, secret_entry, commands_text_edit, use_secret_checkbox, command_option_radio_group, devices_file_path_edit, file_type_radio_group, log_text_edit, progress_bar):
    global cancel_execution
    cancel_execution = False  # Reset cancel flag
    username = username_entry.text()
    password = password_entry.text()
    secret = secret_entry.text() if use_secret_checkbox.isChecked() else ''
    devices_file_path = devices_file_path_edit.text()

    if not username or not password or not devices_file_path:
        QMessageBox.warning(None, "Input Error", "Please enter all required fields: Username, Password, and Devices File.")
        return

    manual_commands = commands_text_edit.toPlainText().strip() if command_option_radio_group.checkedId() == 1 else None
    file_type = file_type_radio_group.checkedButton().text().lower() if devices_file_path else None
    
    if not manual_commands and not devices_file_path:
        QMessageBox.warning(None, "Input Error", "Please enter commands or select a file.")
        return

    confirm = QMessageBox.question(None, "Confirm Commands", f"You have entered the following commands:\n\n{manual_commands or 'From File'}\n\nDo you want to proceed with these commands?", QMessageBox.Yes | QMessageBox.No)
    if confirm == QMessageBox.Yes:
        execute_commands_on_devices(username, password, secret, use_secret_checkbox.isChecked(), devices_file_path, file_type, log_text_edit, manual_commands, progress_bar)

def clear_log(log_text_edit, progress_bar):
    log_text_edit.clear()
    progress_bar.reset()

def cancel_execution_function():
    global cancel_execution
    cancel_execution = True

# Function to create the GUI with a modern theme
def create_gui():
    app = QApplication(sys.argv)
    root = QWidget()
    root.setWindowTitle("Net Interactive Command Executor")

    # Set up modern style
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(53, 53, 53))
    palette.setColor(QPalette.WindowText, QColor(255, 255, 255))
    palette.setColor(QPalette.Base, QColor(15, 15, 15))
    palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
    palette.setColor(QPalette.ToolTipBase, QColor(255, 255, 255))
    palette.setColor(QPalette.ToolTipText, QColor(255, 255, 255))
    palette.setColor(QPalette.Text, QColor(255, 255, 255))
    palette.setColor(QPalette.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ButtonText, QColor(255, 255, 255))
    palette.setColor(QPalette.BrightText, QColor(255, 0, 0))
    palette.setColor(QPalette.Highlight, QColor(142, 45, 197).lighter())
    palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    app.setPalette(palette)

    font = QFont()
    font.setPointSize(10)
    font.setFamily("Arial")

    input_font = QFont("Arial", 12)  # Set the input font size to 12

    main_layout = QVBoxLayout()

    grid_layout = QGridLayout()
    main_layout.addLayout(grid_layout)

    input_height = 35  # Set the desired height for all input boxes

    username_label = QLabel("Username:")
    username_label.setFont(font)
    username_entry = QLineEdit()
    username_entry.setFont(input_font)
    username_entry.setStyleSheet("background-color: #2e2e2e; color: #ffffff; border: 1px solid #767676; padding: 5px;")
    username_entry.setFixedHeight(input_height)
    grid_layout.addWidget(username_label, 0, 0)
    grid_layout.addWidget(username_entry, 0, 1)

    password_label = QLabel("Password:")
    password_label.setFont(font)
    password_entry = QLineEdit()
    password_entry.setFont(input_font)
    password_entry.setStyleSheet("background-color: #2e2e2e; color: #ffffff; border: 1px solid #767676; padding: 5px;")
    password_entry.setEchoMode(QLineEdit.Password)
    password_entry.setFixedHeight(input_height)
    grid_layout.addWidget(password_label, 1, 0)
    grid_layout.addWidget(password_entry, 1, 1)

    show_password_checkbox = QCheckBox("Show Password")
    show_password_checkbox.setFont(font)
    show_password_checkbox.setStyleSheet("color: #ffffff;")
    show_password_checkbox.stateChanged.connect(lambda: [
        password_entry.setEchoMode(QLineEdit.Normal if show_password_checkbox.isChecked() else QLineEdit.Password),
        secret_entry.setEchoMode(QLineEdit.Normal if show_password_checkbox.isChecked() else QLineEdit.Password)
    ])
    grid_layout.addWidget(show_password_checkbox, 1, 2)

    use_secret_checkbox = QCheckBox("Use Enable Secret")
    use_secret_checkbox.setFont(font)
    use_secret_checkbox.setStyleSheet("color: #ffffff;")
    grid_layout.addWidget(use_secret_checkbox, 2, 2)

    secret_label = QLabel("Enable Secret:")
    secret_label.setFont(font)
    secret_entry = QLineEdit()
    secret_entry.setFont(input_font)
    secret_entry.setStyleSheet("background-color: #2e2e2e; color: #ffffff; border: 1px solid #767676; padding: 5px;")
    secret_entry.setEchoMode(QLineEdit.Password)
    secret_entry.setFixedHeight(input_height)
    grid_layout.addWidget(secret_label, 3, 0)
    grid_layout.addWidget(secret_entry, 3, 1)

    show_secret_checkbox = QCheckBox("Show Secret")
    show_secret_checkbox.setFont(font)
    show_secret_checkbox.setStyleSheet("color: #ffffff;")
    show_secret_checkbox.setVisible(False)
    grid_layout.addWidget(show_secret_checkbox, 3, 2)

    def toggle_secret_entry():
        secret_label.setVisible(use_secret_checkbox.isChecked())
        secret_entry.setVisible(use_secret_checkbox.isChecked())
        show_secret_checkbox.setVisible(use_secret_checkbox.isChecked())

    use_secret_checkbox.stateChanged.connect(toggle_secret_entry)

    # Hide the secret entry components by default
    toggle_secret_entry()

    devices_file_label = QLabel("Devices File:")
    devices_file_label.setFont(font)
    devices_file_path_edit = QLineEdit()
    devices_file_path_edit.setFont(input_font)
    devices_file_path_edit.setStyleSheet("background-color: #2e2e2e; color: #ffffff; border: 1px solid #767676; padding: 5px;")
    devices_file_path_edit.setFixedHeight(input_height)
    devices_file_button = QPushButton("Browse")
    devices_file_button.setFont(input_font)
    devices_file_button.setStyleSheet("background-color: #FBBF24; color: black; border-radius: 10px; padding: 5px;")
    devices_file_button.clicked.connect(lambda: devices_file_path_edit.setText(QFileDialog.getOpenFileName(None, "Select Devices File")[0]))
    grid_layout.addWidget(devices_file_label, 4, 0)
    grid_layout.addWidget(devices_file_path_edit, 4, 1)
    grid_layout.addWidget(devices_file_button, 4, 2)

    file_type_radio_group = QButtonGroup()
    file_type_radio_txt = QRadioButton("TXT")
    file_type_radio_csv = QRadioButton("CSV")
    file_type_radio_xlsx = QRadioButton("XLSX")
    file_type_radio_group.addButton(file_type_radio_txt)
    file_type_radio_group.addButton(file_type_radio_csv)
    file_type_radio_group.addButton(file_type_radio_xlsx)
    file_type_radio_txt.setChecked(True)

    file_type_layout = QHBoxLayout()
    file_type_layout.addWidget(file_type_radio_txt)
    file_type_layout.addWidget(file_type_radio_csv)
    file_type_layout.addWidget(file_type_radio_xlsx)
    grid_layout.addLayout(file_type_layout, 5, 1, 1, 2)

    command_option_radio_group = QButtonGroup()
    enter_commands_radio = QRadioButton("Enter Commands Manually")
    enter_commands_radio.setFont(font)
    read_commands_radio = QRadioButton("Read Commands from File")
    read_commands_radio.setFont(font)
    command_option_radio_group.addButton(enter_commands_radio, 1)
    command_option_radio_group.addButton(read_commands_radio, 2)
    enter_commands_radio.setChecked(True)
    
    enter_commands_radio.setStyleSheet("color: #ffffff;")
    read_commands_radio.setStyleSheet("color: #ffffff;")
    grid_layout.addWidget(enter_commands_radio, 6, 0, 1, 2)
    grid_layout.addWidget(read_commands_radio, 7, 0, 1, 2)

    button_layout = QHBoxLayout()

    button_height = 50  # Adjust button height to fit nicely
    button_width = 150  # Adjust button width to fit nicely

    # Create spacer item for fixed spacing
    spacer_item = QSpacerItem(40, 20, QSizePolicy.Fixed, QSizePolicy.Minimum)

    run_button = QPushButton("Run")
    run_button.setFont(font)
    run_button.setStyleSheet("background-color: #10B981; color: black; border-radius: 10px; padding: 10px;")
    run_button.setFixedSize(button_width, button_height)  # Adjust button size
    button_layout.addWidget(run_button)
    button_layout.addItem(spacer_item)  # Add fixed spacing

    clear_button = QPushButton("Clear Screen")
    clear_button.setFont(font)
    clear_button.setStyleSheet("background-color: #FF6347; color: black; border-radius: 10px; padding: 10px;")
    clear_button.setFixedSize(button_width, button_height)  # Adjust button size
    button_layout.addWidget(clear_button)
    button_layout.addItem(spacer_item)  # Add fixed spacing

    cancel_button = QPushButton("Cancel")
    cancel_button.setFont(font)
    cancel_button.setStyleSheet("background-color: #DC143C; color: black; border-radius: 10px; padding: 10px;")
    cancel_button.setFixedSize(button_width, button_height)  # Adjust button size
    button_layout.addWidget(cancel_button)

    button_spacer = QHBoxLayout()
    button_spacer.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
    button_spacer.addLayout(button_layout)
    button_spacer.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

    grid_layout.addLayout(button_spacer, 8, 0, 1, 3)  # Position the buttons in the grid layout, row 8, spanning 3 columns

    run_button.clicked.connect(lambda: run_script(username_entry, password_entry, secret_entry, commands_text_edit, use_secret_checkbox, command_option_radio_group, devices_file_path_edit, file_type_radio_group, log_text_edit, progress_bar))
    clear_button.clicked.connect(lambda: clear_log(log_text_edit, progress_bar))
    cancel_button.clicked.connect(cancel_execution_function)

    commands_text_edit = QTextEdit()
    commands_text_edit.setStyleSheet("background-color: #2e2e2e; color: #ffffff; border: 1px solid #767676; padding: 5px;")
    commands_text_edit.setFont(input_font)  # Set the font size to 12 for command inputs
    main_layout.addWidget(commands_text_edit)

    progress_bar = QProgressBar()
    progress_bar.setStyleSheet("background-color: #2e2e2e; color: #ffffff; border: 1px solid #767676; padding: 5px;")
    progress_bar.setFont(input_font)
    main_layout.addWidget(progress_bar)

    log_text_edit = QTextEdit()
    log_text_edit.setReadOnly(True)
    log_text_edit.setStyleSheet("background-color: #2e2e2e; color: #ffffff; border: 1px solid #767676; padding: 5px;")
    log_text_edit.setFont(input_font)  # Set the font size to 12 for run output
    main_layout.addWidget(log_text_edit)

    root.setLayout(main_layout)
    root.resize(1280, 720)  # Set the initial size to 1280x720
    root.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    create_gui()
