import os
import signal
from datetime import datetime
from netmiko import (
    ConnectHandler,
    NetmikoTimeoutException,
    NetmikoAuthenticationException,
)
import pandas as pd
import warnings
from cryptography.utils import CryptographyDeprecationWarning
import time
import logging
import re
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import Value
import colorama
from colorama import Fore, Back, Style
from art import text2art

colorama.init()

# --------------------- Colorama ---------------------
# Set the entire script to use a specific background and foreground color
print(Back.BLACK + Fore.WHITE)

# --------------------- Add ASCII Art Header ---------------------
header = text2art(
    "N.I.C.E v1.5.2", font="lean"
)  # Create header text with a specified font

# --------------------- Typewriter Animation ---------------------
for char in header:
    print(Fore.MAGENTA + char + Style.RESET_ALL, end="", flush=True)
    time.sleep(0.01)  # Adjust the delay for speed (0.01 seconds per character)

print()  # Move to the next line after the header is printed

# --------------------- Suppress Warnings ---------------------
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning, module="paramiko")
warnings.simplefilter("ignore", category=CryptographyDeprecationWarning)
warnings.filterwarnings(
    "ignore", category=CryptographyDeprecationWarning, module="paramiko"
)

# --------------------- Global Variables ---------------------
cancel_execution = False

# --------------------- Logging Configuration ---------------------
logging.basicConfig(
    filename=os.path.join(os.getcwd(), "general_log.log"),
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# --------------------- Configuration Class ---------------------
class Config:
    """Configuration class for device types and output formats."""

    DEVICE_TYPES = {
        "arista_eos": "Arista Extensible Operating System (EOS)",
        "cisco_asa": "Cisco Adaptive Security Appliance (ASA)",
        "cisco_ftd": "Cisco Firepower Threat Defense (FTD)",
        "cisco_ios": "Cisco Internetwork Operating System (IOS)",
        "cisco_nxos": "Cisco Nexus Operating System (NX-OS)",
        "cisco_s200": "Cisco Small Business 200 Series",
        "cisco_s300": "Cisco Small Business 300 Series",
        "f5_linux": "F5 Networks Linux",
        "f5_ltm": "F5 Local Traffic Manager (LTM)",
        "f5_tmsh": "F5 Traffic Management Shell (TMSH)",
        "linux": "Linux/Unix Operating System",
        "paloalto_panos": "Palo Alto Networks (PAN-OS)",
        "autodetect": "SSH Autodetect (Last Resort)",
    }

    OUTPUT_FORMATS = {"csv": True, "xlsx": False, "txt": False}
    REQUIRED_HEADERS = ["ip", "dns", "command"]
    LOG_DIR = os.path.join(os.getcwd(), "logs")
    OUTPUT_SUBDIR = os.path.join(LOG_DIR, "output")


# --------------------- Utility Functions ---------------------
def get_valid_int_input(prompt, min_val, max_val):
    """
    Get a valid integer input from the user within a specified range.

    Args:
        prompt (str): The input prompt message.
        min_val (int): Minimum valid value.
        max_val (int): Maximum valid value.

    Returns:
        int: The validated integer input.
    """
    while True:
        try:
            value = int(input(Fore.CYAN + prompt + Style.RESET_ALL))
            if min_val <= value <= max_val:
                return value
            else:
                print(
                    Fore.RED
                    + f"Please enter a number between {min_val} and {max_val}."
                    + Style.RESET_ALL
                )
        except ValueError:
            print(
                Fore.RED
                + "❌ Invalid input. Please enter a valid number."
                + Style.RESET_ALL
            )


def get_credentials():
    """
    Prompt the user for credentials if they are not already stored in environment variables.
    """
    username = os.getenv("NICE_USERNAME")
    password = os.getenv("NICE_PASSWORD")

    if not username or not password:
        print(
            Fore.YELLOW + "\n------ Enter your credentials ------\n" + Style.RESET_ALL
        )
        username = input(Fore.CYAN + " 👤 Enter Username: " + Style.RESET_ALL).strip()
        password = input(Fore.CYAN + " 🔒 Enter Password: " + Style.RESET_ALL).strip()

        os.environ["NICE_USERNAME"] = username
        os.environ["NICE_PASSWORD"] = password

    return username, password


def display_options(
    username,
    password,
    action_choice,
    devices,
    selected_device_type,
    pause_option,
    timeout,
    input_file_name,
    output_formats,
    use_parallel,
):
    """
    Display the current configuration options selected by the user.

    Args:
        username (str): Username for device login.
        password (str): Password for device login.
        action_choice (str): Action chosen by the user (direct or file).
        devices (dict): Dictionary of devices and their commands.
        selected_device_type (str): Selected device type.
        pause_option (str): Pause option between device processing.
        timeout (int): Timeout duration between device processing.
        input_file_name (str): Name of the input file.
        output_formats (dict): Output formats selected.
        use_parallel (bool): Whether to use parallel execution.
    """
    print("\n------ ⚙️  Current Configuration ------\n")
    print(f"👤 Username: {username}")
    print(f"🔒 Password: {'*' * len(password)}")
    print(f"📂 Action Choice: {action_choice}")
    print(f"💻 Device Type: {selected_device_type}")
    print(f"⏸️ Pause Option: {pause_option}")
    print(f"⏱️ Timeout: {timeout}")
    print(f"📄 Input File Name: {input_file_name}")

    selected_formats = []
    if output_formats["csv"]:
        selected_formats.append("CSV")
    if output_formats["xlsx"]:
        selected_formats.append("XLSX")
    if output_formats["txt"]:
        selected_formats.append("TXT")
    print(
        f"💾 Output Formats: {', '.join(selected_formats) if selected_formats else 'None selected'}"
    )

    print(f"🔄 Parallel Execution: {use_parallel}")
    print("\n1. ✔️ Proceed")
    print("2. ✏️  Edit Options")


def edit_options():
    """
    Display the edit options menu and get the user's choice.

    Returns:
        str: The user's choice as a string.
    """
    print("\n------ ⚙️  Edit Options ------\n")
    print("1. 💻 Device Type")
    print("2. 👤 Username/Password")
    print("3. 📂 Action Choice")
    print("4. 📄 Device Info")
    print("5. ⏸️ Pause Option")
    print("6. 💾 Output Formats")
    print("7. 🔄 Parallel Execution")
    print("8. ✔️  Done Editing")
    return input(
        Fore.CYAN + "\nSelect an option to edit (enter number): " + Style.RESET_ALL
    ).strip()


def create_directories():
    """
    Create necessary directories for logs and output files.
    """
    os.makedirs(Config.LOG_DIR, exist_ok=True)
    os.makedirs(Config.OUTPUT_SUBDIR, exist_ok=True)


def sanitize_filename(filename, max_length=255):
    """
    Sanitize a filename by removing or replacing invalid characters.

    Args:
        filename (str): The filename to sanitize.
        max_length (int): Maximum allowed length for the filename.

    Returns:
        str: The sanitized filename.
    """
    sanitized = re.sub(r'[\/:*?"<>|]', "_", filename)
    return sanitized[:max_length]


def is_valid_ip(ip):
    """
    Validate if the input string is a valid IP address.

    Args:
        ip (str): The IP address to validate.

    Returns:
        bool: True if the IP address is valid, False otherwise.
    """
    pattern = re.compile(r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$")
    return pattern.match(ip) is not None


def format_output(device, outputs):
    """
    Format the outputs for a device to include IP and DNS with each command output.

    Args:
        device (dict): A dictionary containing device details like IP and DNS.
        outputs (list): A list of command outputs for the device.

    Returns:
        list: A formatted list where each command output is associated with the device IP and DNS.
    """
    formatted = []
    ip = device["ip"]
    dns = device.get("dns", "")  # Use get to avoid KeyError if 'dns' is not present
    for i, output in enumerate(outputs):
        if i == 0:
            formatted.append([ip, dns, output])
        else:
            formatted.append(["", "", output])
    return formatted


# --------------------- Device Management ---------------------
class DeviceManager:
    """Class for managing device information from input files."""

    @staticmethod
    def check_headers(file_path):
        """
        Check if the input file contains the required headers.

        Args:
            file_path (str): Path to the input file.

        Returns:
            bool: True if the required headers are present, False otherwise.
        """
        if file_path.endswith(".csv"):
            df = pd.read_csv(file_path)
        elif file_path.endswith(".xlsx"):
            df = pd.read_excel(file_path, engine="openpyxl")
        else:
            return False
        headers = df.columns.tolist()
        return all(header in headers for header in Config.REQUIRED_HEADERS)

    @staticmethod
    def read_device_info(file_path):
        """
        Read device information from a file and store it in a dictionary.

        Args:
            file_path (str): Path to the input file.

        Returns:
            dict: A dictionary containing devices and their commands.
        """
        if not DeviceManager.check_headers(file_path):
            raise ValueError(
                "❌ File format is incorrect. Ensure the file contains the required headers: ip, dns, command."
            )
        devices = {}
        df = (
            pd.read_csv(file_path)
            if file_path.endswith(".csv")
            else pd.read_excel(file_path, engine="openpyxl")
        )
        for _, row in df.iterrows():
            ip, dns, command = row["ip"], row["dns"], row["command"]
            command_list = command.split("\n")
            if (ip, dns) in devices:
                devices[(ip, dns)].extend(command_list)
            else:
                devices[(ip, dns)] = command_list
        return devices


# --------------------- Device Connection Handling ---------------------
class DeviceConnection:
    """Class to manage connections to devices and execute commands."""

    def __init__(self, device):
        self.device = device
        self.connection = None

    def connect(self):
        """
        Establish a connection to the device.

        Returns:
            ConnectHandler: The connection object if successful, None otherwise.
        """
        try:
            connect_params = {
                k: v for k, v in self.device.items() if k != "dns"
            }  # Remove 'dns' key
            self.connection = ConnectHandler(**connect_params)
            logging.info(f"Connected to device {self.device['ip']}.")
            if self.device["device_type"] == "cisco_asa":
                self.connection.enable()
                logging.info(f"Entered enable mode on {self.device['ip']}.")
        except (NetmikoTimeoutException, NetmikoAuthenticationException) as e:
            logging.error(f"Failed to connect to device {self.device['ip']}: {e}")
            self.connection = None
        return self.connection

    def disconnect(self):
        """Disconnect from the device."""
        if self.connection:
            self.connection.disconnect()
            logging.info(f"Disconnected from device {self.device['ip']}.")

    def execute_commands(self, commands):
        """
        Execute a list of commands on the connected device.

        Args:
            commands (list): List of commands to execute.

        Returns:
            list: List of command outputs.
        """
        if not self.connection:
            logging.error(
                f"Cannot execute commands on device {self.device['ip']} because the connection was not established."
            )
            return []

        outputs = []
        for command in commands:
            try:
                output = self.connection.send_command(command)
                outputs.append(output)
            except Exception as e:
                logging.error(
                    f"Error executing command '{command}' on device {self.device['ip']}: {e}"
                )
                outputs.append(f"Error executing command '{command}': {e}")

        return outputs


# --------------------- Output Management ---------------------
class OutputManager:
    """Class for managing output files."""

    @staticmethod
    def save_output_to_csv(outputs, output_file_path):
        """Save the command outputs to a CSV file."""
        os.makedirs(os.path.dirname(output_file_path), exist_ok=True)
        df = pd.DataFrame(outputs, columns=["IP", "DNS", "Output"])
        df.to_csv(output_file_path, index=False)

    @staticmethod
    def save_output_to_xlsx(outputs, output_file_path):
        """Save the command outputs to an XLSX file."""
        os.makedirs(os.path.dirname(output_file_path), exist_ok=True)
        df = pd.DataFrame(outputs, columns=["IP", "DNS", "Output"])
        df.to_excel(output_file_path, index=False, engine="openpyxl")

    @staticmethod
    def save_output_to_txt(outputs, output_file_path):
        """Save the command outputs to a TXT file."""
        os.makedirs(os.path.dirname(output_file_path), exist_ok=True)
        with open(output_file_path, "w") as file:
            for output in outputs:
                file.write("\n".join(output) + "\n")


# --------------------- Workflow Execution ---------------------
def execute_workflow(
    devices,
    username,
    password,
    output_formats,
    device_type,
    pause_option,
    timeout,
    input_file_name,
    use_parallel=False,
):
    """Execute the workflow based on user input."""
    create_directories()
    all_outputs = []
    any_success = False

    progress = Value("i", 0)
    device_progress = tqdm(
        total=len(devices), desc="Processing devices", position=0, leave=True
    )

    def process_device(device_info):
        """Process a single device."""
        (ip, dns), commands = device_info
        device = {
            "device_type": device_type,
            "ip": ip,
            "dns": dns,  # Include DNS
            "username": username,
            "password": password,
        }
        if device_type == "cisco_asa":
            device["secret"] = password

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
            if pause_option == "timeout" and timeout > 0:
                logging.info(f"Pausing for {timeout} seconds...")
                time.sleep(timeout)
            elif pause_option == "keypress":
                input("\nPress Enter to continue to the next device...\n")

            device_progress.update(1)
    device_progress.close()

    if any_success:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        sanitized_dns = sanitize_filename(last_dns)
        base_name = (
            f"{last_ip}_{sanitized_dns}"
            if input_file_name == "manual_entry"
            else os.path.splitext(os.path.basename(input_file_name))[0]
        )
        output_file_paths = {
            "csv": os.path.join(
                Config.LOG_DIR,
                Config.OUTPUT_SUBDIR,
                f"{base_name}_output_{timestamp}.csv",
            ),
            "xlsx": os.path.join(
                Config.LOG_DIR,
                Config.OUTPUT_SUBDIR,
                f"{base_name}_output_{timestamp}.xlsx",
            ),
            "txt": os.path.join(
                Config.LOG_DIR,
                Config.OUTPUT_SUBDIR,
                f"{base_name}_output_{timestamp}.txt",
            ),
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


# --------------------- Script Execution ---------------------
def run_script():
    """Run the script and manage user interaction."""
    global cancel_execution

    # Initialize variables
    selected_device_type = None
    action_choice = None
    devices = {}
    input_file_name = None
    pause_option = None
    timeout = 0
    output_formats = {"csv": False, "xlsx": False, "txt": False}
    use_parallel = False

    # Get credentials once and store them in environment variables
    username, password = get_credentials()

    # Collect inputs
    while True:
        print(Fore.YELLOW + "------ 🖧  Available device types ------" + Style.RESET_ALL)
        for i, (key, desc) in enumerate(Config.DEVICE_TYPES.items()):
            print(f"{i + 1}. {desc}")

        device_type_index = (
            get_valid_int_input(
                "\nSelect device type (enter number): \n",
                1,
                len(Config.DEVICE_TYPES),
            )
            - 1
        )
        selected_device_type = list(Config.DEVICE_TYPES.keys())[device_type_index]
        break

    while True:
        print(Fore.YELLOW + "\n------ Choose action ------\n" + Style.RESET_ALL)
        print("🖧  1. Direct session")
        print("📂 2. File list")
        action_choice = (
            input(Fore.CYAN + "\nSelect action (enter number): \n" + Style.RESET_ALL)
            .strip()
            .lower()
        )
        if action_choice == "1":
            action_choice = "direct"
        elif action_choice == "2":
            action_choice = "file"
        else:
            print(Fore.RED + "❌ Invalid choice. Please try again." + Style.RESET_ALL)
            continue
        break

    while True:
        if action_choice == "direct":
            while True:
                direct_ip = input(
                    Fore.CYAN + "\nEnter the IP address: " + Style.RESET_ALL
                ).strip()
                if is_valid_ip(direct_ip):
                    break
                else:
                    print(
                        Fore.RED
                        + "❌ Invalid IP address. Please try again."
                        + Style.RESET_ALL
                    )
            direct_dns = input(Fore.CYAN + "Enter the DNS: " + Style.RESET_ALL).strip()

            print(
                Fore.YELLOW
                + "\nEnter the commands one by one. Type 'done' when you are finished: \n"
                + Style.RESET_ALL
            )
            commands = []
            while True:
                command = input(Fore.CYAN + "> " + Style.RESET_ALL).strip()
                if command.lower() == "done":
                    break
                commands.append(command)
            devices[(direct_ip, direct_dns)] = commands
            input_file_name = "manual_entry"
        elif action_choice == "file":
            devices_file_path = (
                input(Fore.CYAN + "\nEnter Devices File Path: \n" + Style.RESET_ALL)
                .strip()
                .strip('"')
            )
            try:
                devices_file_path = os.path.normpath(devices_file_path)
                devices = DeviceManager.read_device_info(devices_file_path)
                input_file_name = devices_file_path
            except ValueError as e:
                print(Fore.RED + str(e) + Style.RESET_ALL)
                print(Fore.RED + "❌ Please try again." + Style.RESET_ALL)
        break

    # Selection of pause option
    while True:
        print(Fore.YELLOW + "\n------ Select pause option ------\n" + Style.RESET_ALL)
        print("⏱️  1. Timeout")
        print("⌨️  2. Keypress")
        print("⏭️  3. No pause")
        pause_choice = (
            input(
                Fore.CYAN + "\nSelect pause option (enter number): \n" + Style.RESET_ALL
            )
            .strip()
            .lower()
        )

        if pause_choice == "1":
            pause_option = "timeout"
            timeout = get_valid_int_input(
                "\nEnter timeout between device connections (0-60 seconds): \n", 0, 60
            )
            break  # Exit after setting the timeout
        elif pause_choice == "2":
            pause_option = "keypress"
            timeout = 0
            break  # Exit after selecting keypress
        elif pause_choice == "3":
            pause_option = "none"
            timeout = 0
            break  # Exit after selecting no pause
        else:
            print(Fore.RED + "❌ Invalid choice. Please try again." + Style.RESET_ALL)

    # Selection of output formats
    while True:
        print(
            Fore.YELLOW + "\n------ Select output format(s) ------\n" + Style.RESET_ALL
        )
        print("1. 📈 CSV")
        print("2. 📗 XLSX")
        print("3. 📝 TXT")
        print("4. ✔️ Done selecting")

        format_choices = (
            input(
                Fore.CYAN
                + "Select output format(s) (e.g., 1,3 for CSV and TXT): "
                + Style.RESET_ALL
            )
            .strip()
            .split(",")
        )

        for format_choice in format_choices:
            format_choice = format_choice.strip()
            if format_choice == "1":
                output_formats["csv"] = True
                print(Fore.GREEN + "✔️ CSV format selected." + Style.RESET_ALL)
            elif format_choice == "2":
                output_formats["xlsx"] = True
                print(Fore.GREEN + "✔️ XLSX format selected." + Style.RESET_ALL)
            elif format_choice == "3":
                output_formats["txt"] = True
                print(Fore.GREEN + "✔️ TXT format selected." + Style.RESET_ALL)
            elif format_choice == "4":
                break
            else:
                print(
                    Fore.RED
                    + f"❌ Invalid format choice: {format_choice}. Please try again."
                    + Style.RESET_ALL
                )

        if "4" in format_choices:
            if not any(output_formats.values()):
                print(
                    Fore.RED
                    + "❌ Please select at least one output format."
                    + Style.RESET_ALL
                )
                continue
            break  # Exit loop if user is done selecting formats

    use_parallel = (
        input(
            Fore.CYAN
            + "Enable parallel execution for device connections and commands? (yes/no): "
            + Style.RESET_ALL
        )
        .strip()
        .lower()
        == "yes"
    )

    # Display summary and edit options
    while True:
        display_options(
            username,
            password,
            action_choice,
            devices,
            selected_device_type,
            pause_option,
            timeout,
            input_file_name,
            output_formats,
            use_parallel,
        )
        user_choice = input(
            Fore.CYAN + "\nSelect an option: " + Style.RESET_ALL
        ).strip()
        if user_choice == "1":
            break
        elif user_choice == "2":
            category_choice = edit_options()
            if category_choice == "1":
                while True:
                    print(
                        Fore.YELLOW
                        + "\n\n------ 🖧  Available device types ------\n"
                        + Style.RESET_ALL
                    )
                    for i, (key, desc) in enumerate(Config.DEVICE_TYPES.items()):
                        print(f"{i + 1}. {desc}")
                    device_type_index = (
                        get_valid_int_input(
                            Fore.CYAN
                            + "\nSelect device type (enter number): \n"
                            + Style.RESET_ALL,
                            1,
                            len(Config.DEVICE_TYPES),
                        )
                        - 1
                    )
                    selected_device_type = list(Config.DEVICE_TYPES.keys())[
                        device_type_index
                    ]
                    break
            elif category_choice == "2":
                while True:
                    username = input(
                        Fore.CYAN + "👤 Enter Username: " + Style.RESET_ALL
                    ).strip()
                    password = input(
                        Fore.CYAN + "🔒 Enter Password: " + Style.RESET_ALL
                    ).strip()
                    os.environ["NICE_USERNAME"] = username
                    os.environ["NICE_PASSWORD"] = password
                    break
            elif category_choice == "3":
                while True:
                    print(
                        Fore.YELLOW
                        + "\n------ Choose action ------\n"
                        + Style.RESET_ALL
                    )
                    print("🖧 1. Direct session")
                    print("📂 2. File list")
                    action_choice = (
                        input(
                            Fore.CYAN
                            + "Select action (enter number): "
                            + Style.RESET_ALL
                        )
                        .strip()
                        .lower()
                    )
                    if action_choice == "1":
                        action_choice = "direct"
                    elif action_choice == "2":
                        action_choice = "file"
                    else:
                        print(
                            Fore.RED
                            + "❌ Invalid choice. Please try again."
                            + Style.RESET_ALL
                        )
                        continue
                    break
            elif category_choice == "4":
                devices = {}
                while True:
                    if action_choice == "direct":
                        while True:
                            direct_ip = input(
                                Fore.CYAN + "\nEnter the IP address: " + Style.RESET_ALL
                            ).strip()
                            if is_valid_ip(direct_ip):
                                break
                            else:
                                print(
                                    Fore.RED
                                    + "❌ Invalid IP address. Please try again."
                                    + Style.RESET_ALL
                                )
                            direct_dns = input(
                                Fore.CYAN + "Enter the DNS: " + Style.RESET_ALL
                            ).strip()

                            print(
                                Fore.YELLOW
                                + "Enter the commands one by one. Type 'done' when you are finished:"
                                + Style.RESET_ALL
                            )
                            commands = []
                            while True:
                                command = input(
                                    Fore.CYAN + "> " + Style.RESET_ALL
                                ).strip()
                                if command.lower() == "done":
                                    break
                                commands.append(command)
                            devices[(direct_ip, direct_dns)] = commands
                            input_file_name = "manual_entry"
                    elif action_choice == "file":
                        devices_file_path = (
                            input(
                                Fore.CYAN
                                + "Enter Devices File Path: "
                                + Style.RESET_ALL
                            )
                            .strip()
                            .strip('"')
                        )
                        try:
                            devices_file_path = os.path.normpath(devices_file_path)
                            devices = DeviceManager.read_device_info(devices_file_path)
                            input_file_name = devices_file_path
                        except ValueError as e:
                            print(Fore.RED + str(e) + Style.RESET_ALL)
                            print(Fore.RED + "❌ Please try again." + Style.RESET_ALL)
                    break
            elif category_choice == "5":
                while True:
                    print(
                        Fore.YELLOW
                        + "\n------ Select pause option ------\n"
                        + Style.RESET_ALL
                    )
                    print("⏱️ 1. Timeout")
                    print("⌨️ 2. Keypress")
                    print("⏭️ 3. No pause")
                    pause_choice = (
                        input(
                            Fore.CYAN
                            + "\nSelect pause option (enter number): \n"
                            + Style.RESET_ALL
                        )
                        .strip()
                        .lower()
                    )
                    if pause_choice == "1":
                        pause_option = "timeout"
                        timeout = get_valid_int_input(
                            Fore.CYAN
                            + "\nEnter timeout between device connections (0-60 seconds): \n"
                            + Style.RESET_ALL,
                            0,
                            60,
                        )
                    elif pause_choice == "2":
                        pause_option = "keypress"
                        timeout = 0
                    elif pause_choice == "3":
                        pause_option = "none"
                        timeout = 0
                    else:
                        print(
                            Fore.RED
                            + "\n❌ Invalid choice. Please try again. \n"
                            + Style.RESET_ALL
                        )
                        continue
                    break
            elif category_choice == "6":
                while True:
                    break
            elif category_choice == "7":
                use_parallel = (
                    input(
                        Fore.CYAN
                        + "\n------ Enable parallel execution for device connections and commands? (yes/no) ------\n"
                        + Style.RESET_ALL
                    )
                    .strip()
                    .lower()
                    == "yes"
                )
            elif category_choice == "8":
                break
        else:
            print(
                Fore.RED + "\n❌ Invalid choice. Please try again. \n" + Style.RESET_ALL
            )

    execute_workflow(
        devices,
        username,
        password,
        output_formats,
        selected_device_type,
        pause_option,
        timeout,
        input_file_name,
        use_parallel,
    )


def graceful_exit(signal, frame):
    """Handle graceful exit on signal interrupt."""
    global cancel_execution
    print(Fore.YELLOW + "\nGracefully exiting the script..." + Style.RESET_ALL)
    cancel_execution = True


if __name__ == "__main__":
    signal.signal(signal.SIGINT, graceful_exit)
    while True:
        run_script()
        choice = (
            input(
                Fore.CYAN
                + "\n\nPress 'Enter' to run another session or type 'exit' to close the program: \n"
                + Style.RESET_ALL
            )
            .strip()
            .lower()
        )
        if choice == "exit":
            print(
                Fore.YELLOW + "Script terminated gracefully. Goodbye!" + Style.RESET_ALL
            )
            break

# At the end of the script, reset the colors
print(Style.RESET_ALL)
