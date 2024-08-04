import os
import time
from datetime import datetime
import pandas as pd
from netmiko import ConnectHandler, NetmikoTimeoutException, NetmikoAuthenticationException
from cryptography.utils import CryptographyDeprecationWarning
import warnings
from tqdm import tqdm

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning, module='paramiko')
warnings.simplefilter("ignore", category=CryptographyDeprecationWarning)
warnings.filterwarnings("ignore", category=CryptographyDeprecationWarning, module='paramiko')

# Global variable to control execution
cancel_execution = False

# Configuration and utility functions
class Config:
    DEVICE_TYPES = ['cisco_asa', 'cisco_ftd', 'cisco_nxos', 'cisco_ios', 'f5_linux', 'f5_tmsh', 'linux', 'paloalto_panos']
    OUTPUT_FORMATS = {"csv": True, "xlsx": False, "txt": False}
    REQUIRED_HEADERS = ["ip", "dns", "command"]
    LOG_DIR = 'logs'
    OUTPUT_SUBDIR = 'output'
    FAILURE_SUBDIR = 'failure'

def create_directories():
    os.makedirs(os.path.join(Config.LOG_DIR, Config.FAILURE_SUBDIR), exist_ok=True)
    os.makedirs(os.path.join(Config.LOG_DIR, Config.OUTPUT_SUBDIR), exist_ok=True)

# Device Manager class
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
        if file_path.endswith('.csv') or file_path.endswith('.xlsx'):
            df = pd.read_csv(file_path) if file_path.endswith('.csv') else pd.read_excel(file_path, header=0, engine='openpyxl')
            for _, row in df.iterrows():
                ip, dns, command = row['ip'], row['dns'], row['command']
                command_list = command.split('\n')
                if (ip, dns) in devices:
                    devices[(ip, dns)].extend(command_list)
                else:
                    devices[(ip, dns)] = command_list
        return devices

# Device Connection class
class DeviceConnection:
    def __init__(self, device):
        self.device = device
        self.connection = None

    def connect(self):
        try:
            self.connection = ConnectHandler(**self.device)
            print(f"Connected to device {self.device['ip']}.\n")
        except (NetmikoTimeoutException, NetmikoAuthenticationException) as e:
            print(f"Failed to connect to device {self.device['ip']}: {e}\n")
        return self.connection

    def disconnect(self):
        if self.connection:
            self.connection.disconnect()

    def execute_commands(self, commands):
        outputs = []
        for command in commands:
            output = self.connection.send_command(command, expect_string=r'[>#]', read_timeout=60)
            print(f"Output for command '{command}':\n{output}\n")
            outputs.append(output)
        return outputs

# Output Manager class
class OutputManager:
    @staticmethod
    def save_output_to_csv(outputs, output_file_path):
        df = pd.DataFrame(outputs, columns=["Hostname", "IP", "Command", "Output"])
        df.to_csv(output_file_path, index=False)

    @staticmethod
    def save_output_to_xlsx(outputs, output_file_path):
        df = pd.DataFrame(outputs, columns=["Hostname", "IP", "Command", "Output"])
        df.to_excel(output_file_path, index=False, engine='openpyxl')

    @staticmethod
    def save_output_to_txt(outputs, output_file_path):
        with open(output_file_path, 'w') as file:
            for output in outputs:
                file.write(output + "\n")

# Function to display selected options
def display_options(username, password, action_choice, devices, selected_device_type, pause_option, timeout, input_file_name, output_formats):
    print("\nYou have selected the following options:")
    print(f"Username: {username}")
    print(f"Password: {'*' * len(password)}")
    print(f"Action Choice: {action_choice}")
    if action_choice == 'direct':
        for (ip, dns), commands in devices.items():
            print(f"Direct IP: {ip}, DNS: {dns}")
            print("Commands:")
            for command in commands:
                print(f"  {command}")
        print("Output File Name: manual_entry")
    elif action_choice == 'file':
        print(f"Devices File Path: {input_file_name}")
    print(f"Device Type: {selected_device_type}")
    print(f"Pause Option: {pause_option}")
    if pause_option == 'timeout':
        print(f"Timeout: {timeout} seconds")
    print(f"Output Formats: {', '.join([fmt for fmt, selected in output_formats.items() if selected])}")
    print("\nPress 1 to run the script or 9 to cancel.")

# Function to execute the workflow
def execute_workflow(devices, username, password, output_formats, device_type, pause_option, timeout, input_file_name):
    create_directories()
    all_outputs = []
    any_success = False

    device_progress = tqdm(total=len(devices), desc="Processing devices", position=0, leave=True)

    for index, ((ip, dns), commands) in enumerate(devices.items()):
        if cancel_execution:
            print("Execution canceled by user.\n")
            break
        
        device = {
            'device_type': device_type,
            'ip': ip,
            'username': username,
            'password': password,
        }
        
        if device_type == 'cisco_asa':
            device['secret'] = password  # Automatically use the same password as the enable secret
        
        connection = DeviceConnection(device)
        if connection.connect():
            outputs = connection.execute_commands(commands)
            all_outputs.extend([[dns, ip, cmd, out] for cmd, out in zip(commands, outputs)])
            connection.disconnect()
            any_success = True

        if pause_option == 'timeout' and timeout > 0:
            print(f"Pausing for {timeout} seconds...")
            time.sleep(timeout)
        elif pause_option == 'keypress':
            input("Press Enter to continue to the next device...")

        device_progress.update(1)
    
    device_progress.close()

    if any_success:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        if input_file_name == "manual_entry":
            base_name = f"{ip}_{dns}"
        else:
            base_name = os.path.splitext(os.path.basename(input_file_name))[0]
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

    print("\nScript execution completed.\n")
    if any_success:
        print("Combined output files saved at:\n")
        if output_formats["csv"]:
            print(f"- {output_file_paths['csv']}\n")
        if output_formats["xlsx"]:
            print(f"- {output_file_paths['xlsx']}\n")
        if output_formats["txt"]:
            print(f"- {output_file_paths['txt']}\n")

# Main function to run the script
def run_script():
    global cancel_execution

    os.system('cls' if os.name == 'nt' else 'clear')  # Clear the screen

    print("Available device types:")
    for i, dt in enumerate(Config.DEVICE_TYPES):
        print(f"{i + 1}. {dt}")

    device_type_index = int(input("Select device type (enter number): ")) - 1
    if device_type_index < 0 or device_type_index >= len(Config.DEVICE_TYPES):
        print("Invalid selection. Defaulting to linux.")
        selected_device_type = 'linux'
    else:
        selected_device_type = Config.DEVICE_TYPES[device_type_index]

    username = input("Enter Username: ")
    password = input("Enter Password: ")

    while True:
        print("Choose action:")
        print("1. Direct session")
        print("2. File list")
        action_choice = input("Select action (enter number): ").strip().lower()

        if action_choice == '1':
            action_choice = 'direct'
            break
        elif action_choice == '2':
            action_choice = 'file'
            break
        else:
            print("Invalid action choice. Please try again.")

    devices = {}
    while True:
        if action_choice == 'direct':
            direct_ip = input("Enter the IP address: ").strip()
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
            break
        elif action_choice == 'file':
            devices_file_path = input("Enter Devices File Path: ").strip().strip('"')
            if not username or not password or not devices_file_path:
                print("Please enter all required fields: Username, Password, and Devices File.")
                continue
            try:
                devices_file_path = os.path.normpath(devices_file_path)
                devices = DeviceManager.read_device_info(devices_file_path)
                input_file_name = devices_file_path
                break
            except ValueError as e:
                print(str(e))
                print("Please try again.")

    while True:
        print("Select pause option:")
        print("1. Timeout")
        print("2. Keypress")
        print("3. No pause")
        pause_choice = input("Select pause option (enter number): ").strip().lower()
        if pause_choice == '1':
            pause_option = 'timeout'
            timeout = int(input("Enter timeout between device connections (0-60 seconds): ").strip())
            break
        elif pause_choice == '2':
            pause_option = 'keypress'
            timeout = 0
            break
        elif pause_choice == '3':
            pause_option = 'none'
            timeout = 0
            break
        else:
            print("Invalid pause option. Please try again.")

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
        if any(output_formats.values()):
            break

    display_options(username, password, action_choice, devices, selected_device_type, pause_option, timeout, input_file_name, output_formats)
    user_choice = input().strip()
    if user_choice != '1':
        print("Operation cancelled.")
        return

    execute_workflow(devices, username, password, output_formats, selected_device_type, pause_option, timeout, input_file_name)

if __name__ == "__main__":
    while True:
        run_script()
        choice = input("Press 'Enter' to run another session or type 'exit' to close the window: ").strip().lower()
        if choice == 'exit':
            break
