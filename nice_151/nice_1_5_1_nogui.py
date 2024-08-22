import os
import signal
from datetime import datetime
from netmiko import ConnectHandler, NetmikoTimeoutException, NetmikoAuthenticationException
import pandas as pd
import warnings
from cryptography.utils import CryptographyDeprecationWarning
import time
import logging
import re
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import Value

# Suppress warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning, module='paramiko')
warnings.simplefilter("ignore", category=CryptographyDeprecationWarning)
warnings.filterwarnings("ignore", category=CryptographyDeprecationWarning, module='paramiko')

# Global variable to control execution
cancel_execution = False

# Configure logging
logging.basicConfig(
    filename='general_log.log',
    level=logging.WARNING,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class Config:
    DEVICE_TYPES = [
        'cisco_asa', 'cisco_ftd', 'cisco_nxos', 'cisco_ios',
        'f5_linux', 'f5_tmsh', 'linux', 'paloalto_panos'
    ]
    OUTPUT_FORMATS = {"csv": True, "xlsx": False, "txt": False}
    REQUIRED_HEADERS = ["ip", "dns", "command"]
    LOG_DIR = 'logs'
    OUTPUT_SUBDIR = 'output'

def get_valid_int_input(prompt, min_val, max_val):
    while True:
        try:
            value = int(input(prompt))
            if min_val <= value <= max_val:
                return value
            else:
                print(f"Please enter a number between {min_val} and {max_val}.")
        except ValueError:
            print("Invalid input. Please enter a valid number.")

def display_options(username, password, action_choice, devices, selected_device_type, pause_option, timeout, input_file_name, output_formats, use_parallel):
    print("\nCurrent Configuration:")
    print(f"Username: {username}")
    print(f"Password: {'*' * len(password)}")
    print(f"Action Choice: {action_choice}")
    print(f"Device Type: {selected_device_type}")
    print(f"Pause Option: {pause_option}")
    print(f"Timeout: {timeout}")
    print(f"Input File Name: {input_file_name}")
    print(f"Output Formats: {output_formats}")
    print(f"Parallel Execution: {use_parallel}")
    print("\n1. Proceed")
    print("2. Edit Options")
    print("Select an option:")

def edit_options():
    print("\nEdit Options:")
    print("1. Device Type")
    print("2. Username/Password")
    print("3. Action Choice")
    print("4. Device Info")
    print("5. Pause Option")
    print("6. Output Formats")
    print("7. Parallel Execution")
    print("8. Done Editing")
    return input("Select an option to edit (enter number): ").strip()

def create_directories():
    os.makedirs(os.path.join(Config.LOG_DIR, Config.OUTPUT_SUBDIR), exist_ok=True)

def sanitize_filename(filename, max_length=255):
    sanitized = re.sub(r'[\/:*?"<>|]', '_', filename)
    return sanitized[:max_length]

def is_valid_ip(ip):
    pattern = re.compile(r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$")
    return pattern.match(ip) is not None

class DeviceManager:
    @staticmethod
    def check_headers(file_path):
        if file_path.endswith('.csv'):
            df = pd.read_csv(file_path)
        elif file_path.endswith('.xlsx'):
            df = pd.read_excel(file_path, engine='openpyxl')
        else:
            return False
        headers = df.columns.tolist()
        return all(header in headers for header in Config.REQUIRED_HEADERS)

    @staticmethod
    def read_device_info(file_path):
        if not DeviceManager.check_headers(file_path):
            raise ValueError("File format is incorrect. Ensure the file contains the required headers: ip, dns, command.")
        devices = {}
        df = pd.read_csv(file_path) if file_path.endswith('.csv') else pd.read_excel(file_path, engine='openpyxl')
        for _, row in df.iterrows():
            ip, dns, command = row['ip'], row['dns'], row['command']
            command_list = command.split('\n')
            if (ip, dns) in devices:
                devices[(ip, dns)].extend(command_list)
            else:
                devices[(ip, dns)] = command_list
        return devices

class DeviceConnection:
    def __init__(self, device):
        self.device = device
        self.connection = None

    def connect(self):
        try:
            connect_params = {k: v for k, v in self.device.items() if k != 'dns'}  # Remove 'dns' key
            self.connection = ConnectHandler(**connect_params)
            logging.info(f"Connected to device {self.device['ip']}.")
            if self.device['device_type'] == 'cisco_asa':
                self.connection.enable()
                logging.info(f"Entered enable mode on {self.device['ip']}.")
        except (NetmikoTimeoutException, NetmikoAuthenticationException) as e:
            logging.error(f"Failed to connect to device {self.device['ip']}: {e}")
            self.connection = None
        return self.connection

    def disconnect(self):
        if self.connection:
            self.connection.disconnect()
            logging.info(f"Disconnected from device {self.device['ip']}.")

    def execute_commands(self, commands):
        if not self.connection:
            logging.error(f"Cannot execute commands on device {self.device['ip']} because the connection was not established.")
            return []

        outputs = []
        for command in commands:
            try:
                output = self.connection.send_command(command)
                outputs.append(output)
            except Exception as e:
                logging.error(f"Error executing command '{command}' on device {self.device['ip']}: {e}")
                outputs.append(f"Error executing command '{command}': {e}")

        return outputs

def format_output(device, outputs):
    formatted = []
    ip = device['ip']
    dns = device.get('dns', '')  # Use get to avoid KeyError
    for i, output in enumerate(outputs):
        if i == 0:
            formatted.append([ip, dns, output])
        else:
            formatted.append(["", "", output])
    return formatted

class OutputManager:
    @staticmethod
    def save_output_to_csv(outputs, output_file_path):
        os.makedirs(os.path.dirname(output_file_path), exist_ok=True)
        df = pd.DataFrame(outputs, columns=["IP", "DNS", "Output"])
        df.to_csv(output_file_path, index=False)

    @staticmethod
    def save_output_to_xlsx(outputs, output_file_path):
        os.makedirs(os.path.dirname(output_file_path), exist_ok=True)
        df = pd.DataFrame(outputs, columns=["IP", "DNS", "Output"])
        df.to_excel(output_file_path, index=False, engine='openpyxl')

    @staticmethod
    def save_output_to_txt(outputs, output_file_path):
        os.makedirs(os.path.dirname(output_file_path), exist_ok=True)
        with open(output_file_path, 'w') as file:
            for output in outputs:
                file.write("\n".join(output) + "\n")

def execute_workflow(devices, username, password, output_formats, device_type, pause_option, timeout, input_file_name, use_parallel=False):
    create_directories()
    all_outputs = []
    any_success = False

    progress = Value('i', 0)
    device_progress = tqdm(total=len(devices), desc="Processing devices", position=0, leave=True)

    def process_device(device_info):
        (ip, dns), commands = device_info
        device = {
            'device_type': device_type,
            'ip': ip,
            'dns': dns,  # Make sure to include dns
            'username': username,
            'password': password,
        }
        if device_type == 'cisco_asa':
            device['secret'] = password

        connection = DeviceConnection(device)
        if connection.connect():
            outputs = connection.execute_commands(commands)
            formatted_output = format_output(device, outputs)
            all_outputs.extend(formatted_output)
            connection.disconnect()
            with progress.get_lock():
                progress.value += 1
            return ip, dns, True
        with progress.get_lock():
            progress.value += 1
        return ip, dns, False

    if use_parallel and len(devices) > 1:
        with ThreadPoolExecutor() as executor:
            results = list(executor.map(process_device, devices.items()))
            for ip, dns, success in results:
                if success:
                    any_success = True
                    last_ip = ip
                    last_dns = dns
                device_progress.update(1)
    else:
        for device_info in devices.items():
            if cancel_execution:
                logging.info("Execution canceled by user.")
                break
            ip, dns, success = process_device(device_info)
            if success:
                any_success = True
                last_ip = ip
                last_dns = dns
            if pause_option == 'timeout' and timeout > 0:
                logging.info(f"Pausing for {timeout} seconds...")
                time.sleep(timeout)
            elif pause_option == 'keypress':
                input("Press Enter to continue to the next device...")

            device_progress.update(1)
    device_progress.close()

    if any_success:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        sanitized_dns = sanitize_filename(last_dns)
        base_name = f"{last_ip}_{sanitized_dns}" if input_file_name == "manual_entry" else os.path.splitext(os.path.basename(input_file_name))[0]
        output_file_paths = {
            "csv": os.path.join(Config.LOG_DIR, Config.OUTPUT_SUBDIR, f'{base_name}_output_{timestamp}.csv'),
            "xlsx": os.path.join(Config.LOG_DIR, Config.OUTPUT_SUBDIR, f'{base_name}_output_{timestamp}.xlsx'),
            "txt": os.path.join(Config.LOG_DIR, Config.OUTPUT_SUBDIR, f'{base_name}_output_{timestamp}.txt')
        }
        if output_formats["csv"]:
            OutputManager.save_output_to_csv(all_outputs, output_file_paths["csv"])
        if output_formats["xlsx"]:
            OutputManager.save_output_to_xlsx(all_outputs, output_file_paths["xlsx"])
        if output_formats["txt"]:
            OutputManager.save_output_to_txt(all_outputs, output_file_paths["txt"])

    logging.info("Script execution completed.")
    if any_success:
        logging.info("Combined output files saved at:")
        if output_formats["csv"]:
            logging.info(f"- {output_file_paths['csv']}")
        if output_formats["xlsx"]:
            logging.info(f"- {output_file_paths['xlsx']}")
        if output_formats["txt"]:
            logging.info(f"- {output_file_paths['txt']}")

def run_script():
    global cancel_execution

    os.system('cls' if os.name == 'nt' else 'clear')  # Clear the screen

    # Initialize variables
    selected_device_type = None
    username = None
    password = None
    action_choice = None
    devices = {}
    input_file_name = None
    pause_option = None
    timeout = 0
    output_formats = {"csv": False, "xlsx": False, "txt": False}
    use_parallel = False

    # Collect inputs
    while True:
        print("Available device types:")
        for i, dt in enumerate(Config.DEVICE_TYPES):
            print(f"{i + 1}. {dt}")

        device_type_index = get_valid_int_input("Select device type (enter number): ", 1, len(Config.DEVICE_TYPES)) - 1
        selected_device_type = Config.DEVICE_TYPES[device_type_index]
        break

    while True:
        username = input("Enter Username: ").strip()
        password = input("Enter Password: ").strip()
        break

    while True:
        print("Choose action:")
        print("1. Direct session")
        print("2. File list")
        action_choice = input("Select action (enter number): ").strip().lower()
        if action_choice == '1':
            action_choice = 'direct'
        elif action_choice == '2':
            action_choice = 'file'
        else:
            print("Invalid choice. Please try again.")
            continue
        break

    while True:
        if action_choice == 'direct':
            while True:
                direct_ip = input("Enter the IP address: ").strip()
                if is_valid_ip(direct_ip):
                    break
                else:
                    print("Invalid IP address. Please try again.")
            direct_dns = input("Enter the DNS: ").strip()

            print("Enter the commands one by one. Type 'done' when you are finished:")
            commands = []
            while True:
                command = input("> ").strip()
                if command.lower() == 'done':
                    break
                commands.append(command)
            devices[(direct_ip, direct_dns)] = commands
            input_file_name = "manual_entry"
        elif action_choice == 'file':
            devices_file_path = input("Enter Devices File Path: ").strip().strip('"')
            try:
                devices_file_path = os.path.normpath(devices_file_path)
                devices = DeviceManager.read_device_info(devices_file_path)
                input_file_name = devices_file_path
            except ValueError as e:
                print(str(e))
                print("Please try again.")
        break

    while True:
        print("Select pause option:")
        print("1. Timeout")
        print("2. Keypress")
        print("3. No pause")
        pause_choice = input("Select pause option (enter number): ").strip().lower()
        if pause_choice == '1':
            pause_option = 'timeout'
            timeout = get_valid_int_input("Enter timeout between device connections (0-60 seconds): ", 0, 60)
        elif pause_choice == '2':
            pause_option = 'keypress'
            timeout = 0
        elif pause_choice == '3':
            pause_option = 'none'
            timeout = 0
        else:
            print("Invalid choice. Please try again.")
            continue
        break

    while True:
        print("Select output format(s):")
        print("1. CSV")
        print("2. XLSX")
        print("3. TXT")
        print("4. Done selecting")
        while True:
            format_choice = input("Select output format (enter number): ").strip().lower()
            if format_choice == '1':
                output_formats["csv"] = True
                print("CSV format selected.")
            elif format_choice == '2':
                output_formats["xlsx"] = True
                print("XLSX format selected.")
            elif format_choice == '3':
                output_formats["txt"] = True
                print("TXT format selected.")
            elif format_choice == '4':
                if not any(output_formats.values()):
                    print("Please select at least one output format.")
                else:
                    break
            else:
                print("Invalid format choice. Please try again.")
        break

    use_parallel = input("Enable parallel execution for device connections and commands? (yes/no): ").strip().lower() == 'yes'

    # Display summary and edit options
    while True:
        display_options(username, password, action_choice, devices, selected_device_type, pause_option, timeout, input_file_name, output_formats, use_parallel)
        user_choice = input().strip()
        if user_choice == '1':
            break
        elif user_choice == '2':
            category_choice = edit_options()
            if category_choice == '1':
                while True:
                    print("Available device types:")
                    for i, dt in enumerate(Config.DEVICE_TYPES):
                        print(f"{i + 1}. {dt}")
                    device_type_index = get_valid_int_input("Select device type (enter number): ", 1, len(Config.DEVICE_TYPES)) - 1
                    selected_device_type = Config.DEVICE_TYPES[device_type_index]
                    break
            elif category_choice == '2':
                while True:
                    username = input("Enter Username: ").strip()
                    password = input("Enter Password: ").strip()
                    break
            elif category_choice == '3':
                while True:
                    print("Choose action:")
                    print("1. Direct session")
                    print("2. File list")
                    action_choice = input("Select action (enter number): ").strip().lower()
                    if action_choice == '1':
                        action_choice = 'direct'
                    elif action_choice == '2':
                        action_choice = 'file'
                    else:
                        print("Invalid choice. Please try again.")
                        continue
                    break
            elif category_choice == '4':
                devices = {}
                while True:
                    if action_choice == 'direct':
                        while True:
                            direct_ip = input("Enter the IP address: ").strip()
                            if is_valid_ip(direct_ip):
                                break
                            else:
                                print("Invalid IP address. Please try again.")
                        direct_dns = input("Enter the DNS: ").strip()

                        print("Enter the commands one by one. Type 'done' when you are finished:")
                        commands = []
                        while True:
                            command = input("> ").strip()
                            if command.lower() == 'done':
                                break
                            commands.append(command)
                        devices[(direct_ip, direct_dns)] = commands
                        input_file_name = "manual_entry"
                    elif action_choice == 'file':
                        devices_file_path = input("Enter Devices File Path: ").strip().strip('"')
                        try:
                            devices_file_path = os.path.normpath(devices_file_path)
                            devices = DeviceManager.read_device_info(devices_file_path)
                            input_file_name = devices_file_path
                        except ValueError as e:
                            print(str(e))
                            print("Please try again.")
                    break
            elif category_choice == '5':
                while True:
                    print("Select pause option:")
                    print("1. Timeout")
                    print("2. Keypress")
                    print("3. No pause")
                    pause_choice = input("Select pause option (enter number): ").strip().lower()
                    if pause_choice == '1':
                        pause_option = 'timeout'
                        timeout = get_valid_int_input("Enter timeout between device connections (0-60 seconds): ", 0, 60)
                    elif pause_choice == '2':
                        pause_option = 'keypress'
                        timeout = 0
                    elif pause_choice == '3':
                        pause_option = 'none'
                        timeout = 0
                    else:
                        print("Invalid choice. Please try again.")
                        continue
                    break
            elif category_choice == '6':
                while True:
                    print("Select output format(s):")
                    print("1. CSV")
                    print("2. XLSX")
                    print("3. TXT")
                    print("4. Done selecting")
                    output_formats = {"csv": False, "xlsx": False, "txt": False}
                    while True:
                        format_choice = input("Select output format (enter number): ").strip().lower()
                        if format_choice == '1':
                            output_formats["csv"] = True
                            print("CSV format selected.")
                        elif format_choice == '2':
                            output_formats["xlsx"] = True
                            print("XLSX format selected.")
                        elif format_choice == '3':
                            output_formats["txt"] = True
                            print("TXT format selected.")
                        elif format_choice == '4':
                            if not any(output_formats.values()):
                                print("Please select at least one output format.")
                            else:
                                break
                        else:
                            print("Invalid format choice. Please try again.")
                    break
            elif category_choice == '7':
                use_parallel = input("Enable parallel execution for device connections and commands? (yes/no): ").strip().lower() == 'yes'
            elif category_choice == '8':
                break
        else:
            print("Invalid choice. Please try again.")

    execute_workflow(devices, username, password, output_formats, selected_device_type, pause_option, timeout, input_file_name, use_parallel)

def graceful_exit(signal, frame):
    global cancel_execution
    print("\nGracefully exiting the script...")
    cancel_execution = True

if __name__ == "__main__":
    signal.signal(signal.SIGINT, graceful_exit)
    while True:
        run_script()
        choice = input("Press 'Enter' to run another session or type 'exit' to close the program: ").strip().lower()
        if choice == 'exit':
            print("Script terminated gracefully. Goodbye!")
            break
