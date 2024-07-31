import os
import sys
import time
from datetime import datetime
from netmiko import ConnectHandler, NetMikoTimeoutException, NetMikoAuthenticationException
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QTextEdit, QPushButton,
                             QFileDialog, QMessageBox, QCheckBox, QSpacerItem, QSizePolicy, QProgressBar, QGridLayout,
                             QMenuBar, QMenu, QAction, QActionGroup, QDialog, QInputDialog, QDialogButtonBox, QToolTip)
from PyQt5.QtGui import QFont, QColor, QPalette
from PyQt5.QtCore import Qt
import pandas as pd
import warnings
from cryptography.utils import CryptographyDeprecationWarning

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning, module='paramiko')

# Suppress specific deprecation warnings
warnings.simplefilter("ignore", category=CryptographyDeprecationWarning)

# Global flag for canceling script execution
cancel_execution = False

# Option for creating individual logs
create_individual_logs = False

# Global variables for UI elements
commands_text_edit = None
direct_ip = None
direct_dns = None
press_key_to_continue = False
current_connection = None  # To hold the current active connection
cancellation_mode = "Graceful"  # Default to graceful cancellation
output_formats = {"csv": True, "xlsx": False, "txt": False}  # Default output formats, csv is default
skip_confirmation = False  # Default to showing confirmation dialog

# Define minimum required headers
required_headers = ["ip", "dns", "command"]

# Function to check headers
def check_headers(file_path):
    if file_path.endswith('.csv'):
        df = pd.read_csv(file_path)
    elif file_path.endswith('.xlsx'):
        df = pd.read_excel(file_path, engine='openpyxl')
    else:
        return False
    
    headers = df.columns.tolist()
    return all(header in headers for header in required_headers)

# Function to read device information from the selected file
def read_device_info(file_path):
    if not check_headers(file_path):
        raise ValueError("File format is incorrect. Ensure the file contains the required headers: ip, dns, command.")
    
    devices = {}
    if file_path.endswith('.csv') or file_path.endswith('.xlsx'):
        df = pd.read_csv(file_path) if file_path.endswith('.csv') else pd.read_excel(file_path, header=0, engine='openpyxl')
        for _, row in df.iterrows():
            ip, dns, command = row['ip'], row['dns'], row['command']
            command_list = command.split('\n')  # Split commands by newline characters
            if (ip, dns) in devices:
                devices[(ip, dns)].extend(command_list)
            else:
                devices[(ip, dns)] = command_list
    return devices

# Function to create directories if they do not exist
def create_directories():
    os.makedirs('logs/successful', exist_ok=True)
    os.makedirs('logs/failure', exist_ok=True)
    os.makedirs('logs/output', exist_ok=True)  # Directory for combined output files

# Function to execute commands on devices
def execute_commands_on_devices(username, password, secret, use_secret, devices_file_path, log_text_edit, manual_commands=None, progress_bar=None):
    global cancel_execution
    global current_connection
    global direct_ip
    global direct_dns

    if direct_ip and direct_dns:
        devices = {(direct_ip, direct_dns): manual_commands.strip().split('\n') if manual_commands else []}
    else:
        try:
            devices = read_device_info(devices_file_path)
        except ValueError as e:
            log_text_edit.append(str(e))
            QMessageBox.warning(None, "File Error", str(e))
            return

    create_directories()
    
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    input_filename = os.path.splitext(os.path.basename(devices_file_path))[0] if devices_file_path else "manual_run"
    failed_devices_file = f'logs/failure/failed_devices_{timestamp}.txt'
    output_file_paths = {
        "csv": f'logs/output/{input_filename}_output_{timestamp}.csv',
        "xlsx": f'logs/output/{input_filename}_output_{timestamp}.xlsx',
        "txt": f'logs/output/{input_filename}_output_{timestamp}.txt'
    }
    
    total_devices = len(devices)
    progress_bar.setMaximum(total_devices)
    
    all_outputs = []
    any_success = False

    for index, ((ip, hostname), device_commands) in enumerate(devices.items()):
        if cancel_execution:
            log_text_edit.append("Execution canceled by user.\n")
            break
        
        if manual_commands and not (direct_ip and direct_dns):
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
                current_connection = ConnectHandler(**device)
                log_text_edit.append(f"Successfully connected to device {hostname} ({ip}).")
                QApplication.processEvents()
                if use_secret:
                    current_connection.enable()
                
                log_filename = f'logs/successful/{hostname}_{ip}_{timestamp}.txt'
                
                with open(log_filename, 'w') as log_file:
                    for command in device_commands:
                        if cancel_execution:
                            log_text_edit.append("Execution canceled by user.\n")
                            break
                        output = current_connection.send_command(command, expect_string=r'[>#]', read_timeout=60)
                        log_text_edit.append(f"Output from device {hostname} ({ip}) for command '{command}':\n{output}\n")
                        QApplication.processEvents()
                        if create_individual_logs:
                            log_file.write(f"Output from device {hostname} ({ip}) for command '{command}' at {timestamp}:\n{output}\n\n")
                        all_outputs.append([hostname, ip, command, output])
                
                current_connection.disconnect()
                current_connection = None
                success = True
                any_success = True
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
            log_text_edit.append(f"Failed to connect to device {hostname} ({ip}) after 2 attempts.\nCommon causes of this problem are:\n1. Incorrect credentials\n2. Incorrect hostname or IP address.\n3. Device might be down or account locked out.\n4. Wrong SSH port.\n5. Intermediate firewall blocking access.\n6. You need a break or vacation.\n")
            QApplication.processEvents()
            with open(failed_devices_file, 'a') as fd_file:
                fd_file.write(f"{timestamp} - {hostname} {ip}\n")
        
        progress_bar.setValue(index + 1)
        QApplication.processEvents()

    if any_success:
        # Save all outputs to the selected formats
        if output_formats["csv"]:
            df = pd.DataFrame(all_outputs, columns=["Hostname", "IP", "Command", "Output"])
            df.to_csv(output_file_paths["csv"], index=False)
        if output_formats["xlsx"]:
            df = pd.DataFrame(all_outputs, columns=["Hostname", "IP", "Command", "Output"])
            df.to_excel(output_file_paths["xlsx"], index=False, engine='openpyxl')
        if output_formats["txt"]:
            with open(output_file_paths["txt"], 'w') as txt_file:
                for hostname, ip, command, output in all_outputs:
                    txt_file.write(f"Hostname: {hostname}\nIP: {ip}\nCommand: {command}\nOutput:\n{output}\n\n")

    log_text_edit.append(f"\nScript execution completed. Please check the 'logs/successful' directory for detailed output and 'logs/failure' directory for any failed connections.\n")
    if any_success:
        log_text_edit.append(f"Combined output files saved at: \n")
        if output_formats["csv"]:
            log_text_edit.append(f"- {output_file_paths['csv']}\n")
        if output_formats["xlsx"]:
            log_text_edit.append(f"- {output_file_paths['xlsx']}\n")
        if output_formats["txt"]:
            log_text_edit.append(f"- {output_file_paths['txt']}\n")
    QApplication.processEvents()

    if any_success:
        # Save all outputs to the selected formats
        if output_formats["csv"]:
            df = pd.DataFrame(all_outputs, columns=["Hostname", "IP", "Command", "Output"])
            df.to_csv(output_file_paths["csv"], index=False)
        if output_formats["xlsx"]:
            df = pd.DataFrame(all_outputs, columns=["Hostname", "IP", "Command", "Output"])
            df.to_excel(output_file_paths["xlsx"], index=False, engine='openpyxl')
        if output_formats["txt"]:
            with open(output_file_paths["txt"], 'w') as txt_file:
                for hostname, ip, command, output in all_outputs:
                    txt_file.write(f"Hostname: {hostname}\nIP: {ip}\nCommand: {command}\nOutput:\n{output}\n\n")

    log_text_edit.append(f"\nScript execution completed. Please check the 'logs/successful' directory for detailed output and 'logs/failure' directory for any failed connections.\n")
    if any_success:
        log_text_edit.append(f"Combined output files saved at: \n")
        if output_formats["csv"]:
            log_text_edit.append(f"- {output_file_paths['csv']}\n")
        if output_formats["xlsx"]:
            log_text_edit.append(f"- {output_file_paths['xlsx']}\n")
        if output_formats["txt"]:
            log_text_edit.append(f"- {output_file_paths['txt']}\n")
    QApplication.processEvents()

def run_script(username_entry, password_entry, secret_entry, use_secret_checkbox, log_text_edit, progress_bar):
    global cancel_execution
    global direct_ip
    global direct_dns

    cancel_execution = False  # Reset cancel flag
    username = username_entry.text()
    password = password_entry.text()
    secret = secret_entry.text() if use_secret_checkbox.isChecked() else ''

    if not username or not password or not (devices_file_path_edit.text() or (direct_ip and direct_dns)):
        QMessageBox.warning(None, "Input Error", "Please enter all required fields: Username, Password, and Devices File or Direct IP/DNS.")
        return

    manual_commands = commands_text_edit.toPlainText().strip() if run_option == "manual" else None
    devices_file_path = devices_file_path_edit.text() if run_option == "file" else None
    
    if run_option == "manual" and not manual_commands:
        QMessageBox.warning(None, "Input Error", "Please enter commands for manual run.")
        return
    
    if not manual_commands and not devices_file_path and not (direct_ip and direct_dns):
        QMessageBox.warning(None, "Input Error", "Please enter commands or select a file.")
        return

    if not skip_confirmation:
        if not show_confirmation_dialog(username, password, secret, devices_file_path, manual_commands):
            return

    execute_commands_on_devices(username, password, secret, use_secret_checkbox.isChecked(), devices_file_path, log_text_edit, manual_commands, progress_bar)
    if press_key_to_continue:
        QMessageBox.information(None, "Press Key to Continue", "Press OK to continue.")
    
def clear_log(log_text_edit, progress_bar):
    log_text_edit.clear()
    progress_bar.reset()

def cancel_execution_function():
    global cancel_execution
    global current_connection

    cancel_execution = True
    if current_connection and cancellation_mode == "Forceful":
        current_connection.disconnect()
        current_connection = None

def clear_manual_commands():
    commands_text_edit.clear()

# Helper function to get the selected file type
run_option = "manual"

def set_run_option(option):
    global run_option
    run_option = option
    toggle_manual_command_input()

def toggle_create_individual_logs():
    global create_individual_logs
    create_individual_logs = not create_individual_logs

def toggle_press_key_to_continue():
    global press_key_to_continue
    press_key_to_continue = not press_key_to_continue

def toggle_manual_command_input():
    global commands_text_edit
    if run_option == "manual":
        commands_text_edit.setVisible(True)
    else:
        commands_text_edit.setVisible(False)

def set_cancellation_mode(mode):
    global cancellation_mode
    cancellation_mode = mode

def set_output_format(format):
    global output_formats
    global create_individual_logs
    if format in output_formats:
        output_formats[format] = not output_formats[format]
    elif format == "individual_logs":
        create_individual_logs = not create_individual_logs

def toggle_skip_confirmation():
    global skip_confirmation
    skip_confirmation = not skip_confirmation

def show_confirmation_dialog(username, password, secret, devices_file_path, manual_commands):
    dialog = QDialog()
    dialog.setWindowTitle("Confirm Selections")
    dialog.setMinimumSize(400, 300)
    layout = QVBoxLayout(dialog)

    info_label = QLabel("Please confirm the following selections before proceeding:")
    info_label.setFont(QFont("Arial", 11))
    layout.addWidget(info_label)

    selected_formats = [fmt.upper() for fmt, selected in output_formats.items() if selected and fmt != "individual_logs"]
    format_str = ', '.join(selected_formats)
    
    individual_logs_str = "Yes" if create_individual_logs else "No"

    selection_details = f"""
    <b>Username:</b> {username}<br>
    <b>Password:</b> {'*' * len(password)}<br>
    <b>Enable Secret:</b> {'*' * len(secret) if secret else 'None'}<br>
    <b>Device File Path:</b> {devices_file_path or 'Direct IP Input'}<br>
    <b>Manual Commands:</b> {manual_commands or 'None'}<br>
    <b>Output Format:</b> {format_str}<br>
    <b>Cancellation Mode:</b> {cancellation_mode}<br>
    <b>Create Individual Logs:</b> {individual_logs_str}<br>
    <b>Press Key to Continue:</b> {'Yes' if press_key_to_continue else 'No'}<br>
    """

    details_label = QLabel(selection_details)
    details_label.setFont(QFont("Arial", 11))
    layout.addWidget(details_label)

    skip_checkbox = QCheckBox("Skip this confirmation in the future")
    skip_checkbox.setFont(QFont("Arial", 11))
    skip_checkbox.stateChanged.connect(toggle_skip_confirmation)
    layout.addWidget(skip_checkbox)

    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)

    dialog.setLayout(layout)
    result = dialog.exec_()
    return result == QDialog.Accepted

# Function to create the GUI with a modern theme
def create_gui():
    global commands_text_edit
    global direct_ip
    global direct_dns
    global devices_file_path_edit
    
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

    menu_bar = QMenuBar()
    main_layout.setMenuBar(menu_bar)

    device_menu = QMenu("Device Input", root)
    menu_bar.addMenu(device_menu)

    timeout_menu = QMenu("Timeout Settings", root)
    menu_bar.addMenu(timeout_menu)

    output_menu = QMenu("Output Format", root)
    menu_bar.addMenu(output_menu)

    run_menu = QMenu("Run Commands", root)
    menu_bar.addMenu(run_menu)

    cancellation_menu = QMenu("Cancellation Mode", root)
    menu_bar.addMenu(cancellation_menu)

    options_menu = QMenu("Options", root)
    menu_bar.addMenu(options_menu)

    skip_confirmation_action = QAction("Skip Confirmation", root, checkable=True)
    skip_confirmation_action.triggered.connect(toggle_skip_confirmation)
    options_menu.addAction(skip_confirmation_action)

    # Device Input Actions
    direct_ip_action = QAction("Direct IP Input", root, checkable=True)
    direct_ip_action.triggered.connect(lambda: input_direct_ip())
    device_menu.addAction(direct_ip_action)

    file_selection_action = QAction("File Selection", root, checkable=True)
    file_selection_action.triggered.connect(lambda: browse_file())
    device_menu.addAction(file_selection_action)

    device_action_group = QActionGroup(root)
    device_action_group.addAction(direct_ip_action)
    device_action_group.addAction(file_selection_action)
    device_action_group.setExclusive(True)

    # Timeout Settings Actions
    custom_timeout_action = QAction("Custom Timeout", root, checkable=True)
    custom_timeout_action.triggered.connect(lambda: set_custom_timeout())
    timeout_menu.addAction(custom_timeout_action)

    press_key_action = QAction("Press Key to Continue", root, checkable=True)
    press_key_action.triggered.connect(lambda: toggle_press_key_to_continue())
    timeout_menu.addAction(press_key_action)

    timeout_action_group = QActionGroup(root)
    timeout_action_group.addAction(custom_timeout_action)
    timeout_action_group.addAction(press_key_action)
    timeout_action_group.setExclusive(False)

    # Output Format Actions
    csv_output_action = QAction("CSV", root, checkable=True)
    csv_output_action.setChecked(True)  # Default to CSV
    csv_output_action.triggered.connect(lambda: set_output_format("csv"))
    output_menu.addAction(csv_output_action)

    xlsx_output_action = QAction("XLSX", root, checkable=True)
    xlsx_output_action.triggered.connect(lambda: set_output_format("xlsx"))
    output_menu.addAction(xlsx_output_action)

    txt_output_action = QAction("TXT", root, checkable=True)
    txt_output_action.triggered.connect(lambda: set_output_format("txt"))
    output_menu.addAction(txt_output_action)

    create_logs_action = QAction("Create Individual Logs", root, checkable=True)
    create_logs_action.setChecked(False)  # Set default to not creating individual logs
    create_logs_action.triggered.connect(lambda: set_output_format("individual_logs"))
    output_menu.addAction(create_logs_action)

    output_format_action_group = QActionGroup(root)
    output_format_action_group.addAction(csv_output_action)
    output_format_action_group.addAction(xlsx_output_action)
    output_format_action_group.addAction(txt_output_action)
    output_format_action_group.addAction(create_logs_action)
    output_format_action_group.setExclusive(False)

    # Run Commands Actions
    run_manually_action = QAction("Run Manually", root, checkable=True)
    run_manually_action.triggered.connect(lambda: set_run_option("manual"))
    run_menu.addAction(run_manually_action)

    run_from_file_action = QAction("Run from File", root, checkable=True)
    run_from_file_action.triggered.connect(lambda: set_run_option("file"))
    run_menu.addAction(run_from_file_action)

    run_action_group = QActionGroup(root)
    run_action_group.addAction(run_manually_action)
    run_action_group.addAction(run_from_file_action)
    run_action_group.setExclusive(True)

    # Cancellation Mode Actions
    graceful_cancel_action = QAction("Graceful", root, checkable=True)
    graceful_cancel_action.triggered.connect(lambda: set_cancellation_mode("Graceful"))
    graceful_cancel_action.setChecked(True)  # Set default to Graceful
    cancellation_menu.addAction(graceful_cancel_action)

    forceful_cancel_action = QAction("Forceful", root, checkable=True)
    forceful_cancel_action.triggered.connect(lambda: set_cancellation_mode("Forceful"))
    cancellation_menu.addAction(forceful_cancel_action)

    cancellation_action_group = QActionGroup(root)
    cancellation_action_group.addAction(graceful_cancel_action)
    cancellation_action_group.addAction(forceful_cancel_action)
    cancellation_action_group.setExclusive(True)

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

    devices_file_path_edit = QLineEdit()  # Define the variable to hold the file path
    devices_file_path_edit.setVisible(False)  # Hide the file path edit since it's set via menu

    button_layout = QHBoxLayout()

    button_height = 40  # Adjust button height to fit nicely
    button_width = 140  # Adjust button width to fit nicely

    # Create spacer items for spacing between buttons
    spacer_item_small = QSpacerItem(20, 20, QSizePolicy.Fixed, QSizePolicy.Minimum)
    spacer_item_large = QSpacerItem(40, 20, QSizePolicy.Fixed, QSizePolicy.Minimum)

    run_button = QPushButton("Run")
    run_button.setFont(font)
    run_button.setStyleSheet("background-color: #4aff47; color: black; border-radius: 10px; padding: 10px;")
    run_button.setFixedSize(button_width, button_height)
    button_layout.addWidget(run_button)
    button_layout.addItem(spacer_item_small)

    clear_button = QPushButton("CTO")
    clear_button.setFont(font)
    clear_button.setStyleSheet("background-color: #479aff; color: black; border-radius: 10px; padding: 10px;")
    clear_button.setFixedSize(button_width, button_height)
    button_layout.addWidget(clear_button)
    button_layout.addItem(spacer_item_small)

    clear_commands_button = QPushButton("CMC")
    clear_commands_button.setFont(font)
    clear_commands_button.setStyleSheet("background-color: #ffbf47; color: black; border-radius: 10px; padding: 10px;")
    clear_commands_button.setFixedSize(button_width, button_height)
    button_layout.addWidget(clear_commands_button)
    button_layout.addItem(spacer_item_small)

    cancel_button = QPushButton("Cancel")
    cancel_button.setFont(font)
    cancel_button.setStyleSheet("background-color: #ff5947; color: black; border-radius: 10px; padding: 10px;")
    cancel_button.setFixedSize(button_width, button_height)
    button_layout.addWidget(cancel_button)

    button_spacer = QHBoxLayout()
    button_spacer.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
    button_spacer.addLayout(button_layout)
    button_spacer.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

    grid_layout.addLayout(button_spacer, 8, 0, 1, 3)  # Position the buttons in the grid layout, row 8, spanning 3 columns

    run_button.clicked.connect(lambda: run_script(username_entry, password_entry, secret_entry, use_secret_checkbox, log_text_edit, progress_bar))
    clear_button.clicked.connect(lambda: clear_log(log_text_edit, progress_bar))
    clear_commands_button.clicked.connect(clear_manual_commands)
    cancel_button.clicked.connect(cancel_execution_function)

    commands_text_edit = QTextEdit()
    commands_text_edit.setStyleSheet("background-color: #000000; color: #ffffff; border: 1px solid #767676; padding: 5px;")
    commands_text_edit.setFont(QFont("Consolas", 12))  # Set the font to Consolas
    commands_text_edit.setVisible(False)  # Hide manual commands input box by default
    main_layout.addWidget(commands_text_edit)

    progress_bar = QProgressBar()
    progress_bar.setStyleSheet("background-color: #2e2e2e; color: #ffffff; border: 1px solid #767676; padding: 5px;")
    progress_bar.setFont(input_font)
    main_layout.addWidget(progress_bar)

    log_text_edit = QTextEdit()
    log_text_edit.setReadOnly(True)
    log_text_edit.setStyleSheet("background-color: #000000; color: #ffffff; border: 1px solid #767676; padding: 5px;")
    log_text_edit.setFont(QFont("Consolas", 12))  # Set the font to Consolas
    main_layout.addWidget(log_text_edit)

    root.setLayout(main_layout)
    root.resize(1280, 720)  # Set the initial size to 1280x720
    root.show()
    sys.exit(app.exec_())

def input_direct_ip():
    global direct_ip
    global direct_dns

    dialog = QDialog()
    dialog.setWindowTitle("Direct IP Input")
    dialog.setMinimumSize(400, 200)  # Set a minimum size for the dialog
    layout = QVBoxLayout(dialog)

    label_font = QFont("Arial", 11)  # Set font size for labels
    input_font = QFont("Arial", 9)  # Set font size for input boxes

    ip_label = QLabel("Enter IP Address:")
    ip_label.setFont(label_font)
    ip_entry = QLineEdit()
    ip_entry.setFont(input_font)

    dns_label = QLabel("Enter DNS:")
    dns_label.setFont(label_font)
    dns_entry = QLineEdit()
    dns_entry.setFont(input_font)

    spacer = QSpacerItem(20, 30, QSizePolicy.Minimum, QSizePolicy.Expanding)

    buttons_layout = QHBoxLayout()
    ok_button = QPushButton("OK")
    cancel_button = QPushButton("Cancel")

    buttons_layout.addWidget(ok_button)
    buttons_layout.addWidget(cancel_button)

    layout.addWidget(ip_label)
    layout.addWidget(ip_entry)
    layout.addWidget(dns_label)
    layout.addWidget(dns_entry)
    layout.addItem(spacer)
    layout.addLayout(buttons_layout)

    def on_ok():
        global direct_ip
        global direct_dns
        direct_ip = ip_entry.text()
        direct_dns = dns_entry.text()
        if direct_ip and direct_dns:
            dialog.accept()

    ok_button.clicked.connect(on_ok)
    cancel_button.clicked.connect(dialog.reject)

    dialog.exec_()

def browse_file():
    global devices_file_path_edit

    file_path, _ = QFileDialog.getOpenFileName(None, "Select Devices File")
    if file_path:
        devices_file_path_edit.setText(file_path)

def set_custom_timeout():
    timeout, ok = QInputDialog.getInt(None, "Custom Timeout", "Enter timeout value (0-60 seconds):", min=0, max=60)
    if ok:
        # Add code to handle custom timeout
        pass

if __name__ == "__main__":
    create_gui()
