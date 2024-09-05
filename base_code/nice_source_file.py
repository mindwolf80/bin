"""
Network Device Management Script with Forceful Cancel

This script manages network devices, executing commands and saving outputs.
It supports various device types and output formats, and includes a forceful cancel mechanism.
"""

import os
import re
import signal
import time
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from multiprocessing import Value, Manager
import threading
import sys  # For inline status updates
import keyboard

import warnings
import pandas as pd

from cryptography.utils import CryptographyDeprecationWarning
from netmiko import (
    ConnectHandler,
    NetmikoTimeoutException,
    NetmikoAuthenticationException,
)

# Suppress warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning, module="paramiko")
warnings.simplefilter("ignore", category=CryptographyDeprecationWarning)
warnings.filterwarnings(
    "ignore", category=CryptographyDeprecationWarning, module="paramiko"
)

# Global variables with initial assignment
CANCEL_EXECUTION = False
THREAD_POOL = None
ACTIVE_CONNECTIONS = []

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("general_log.log"),
        logging.StreamHandler(sys.stdout),  # Console output
    ],
)
logger = logging.getLogger(__name__)


class Config:
    """Configuration class for the script."""

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


def create_directories():
    """Create necessary directories for logs and outputs."""
    os.makedirs(Config.LOG_DIR, exist_ok=True)
    os.makedirs(Config.OUTPUT_SUBDIR, exist_ok=True)


def sanitize_filename(filename, max_length=255):
    """Sanitize filename by removing invalid characters and truncating."""
    sanitized = re.sub(r'[\/:*?"<>|]', "_", filename)
    return sanitized[:max_length]


def is_valid_ip(ip_address):
    """Check if the given IP address is valid."""
    pattern = re.compile(r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$")
    return pattern.match(ip_address) is not None


def format_device_output(device, outputs):
    """Format the output for a device."""
    formatted_output = []
    ip_address = device["ip"]
    dns_name = device.get("dns", "")
    for i, output in enumerate(outputs):
        if i == 0:
            formatted_output.append([ip_address, dns_name, output])
        else:
            formatted_output.append(["", "", output])
    return formatted_output


class DeviceManager:
    """Manages device information and file operations."""

    @staticmethod
    def check_headers(file_path):
        """Check if the file has the required headers."""
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
        """Read device information from the given file."""
        if not DeviceManager.check_headers(file_path):
            raise ValueError(
                "File format is incorrect. Ensure the file contains "
                "the required headers: ip, dns, command."
            )
        devices_info = {}
        df = (
            pd.read_csv(file_path)
            if file_path.endswith(".csv")
            else pd.read_excel(file_path, engine="openpyxl")
        )
        for _, row in df.iterrows():
            ip_address, dns_name, command = row["ip"], row["dns"], row["command"]
            command_list = command.split("\n")
            if (ip_address, dns_name) in devices_info:
                devices_info[(ip_address, dns_name)].extend(command_list)
            else:
                devices_info[(ip_address, dns_name)] = command_list
        return devices_info


class DeviceConnection:
    """Manages connections to network devices."""

    def __init__(self, device_config):
        """Initialize DeviceConnection with device information."""
        self.device_config = device_config
        self.connection = None

    def connect(self):
        """Establish a connection to the device."""
        try:
            connect_params = {k: v for k, v in self.device_config.items() if k != "dns"}
            self.connection = ConnectHandler(**connect_params)
            sys.stdout.write("Connected!\n")
            sys.stdout.flush()
            logger.info("Connected to device %s.", self.device_config["ip"])
            ACTIVE_CONNECTIONS.append(self.connection)
            if self.device_config["device_type"] == "cisco_asa":
                self.connection.enable()
                logger.info("Entered enable mode on %s.", self.device_config["ip"])
        except (NetmikoTimeoutException, NetmikoAuthenticationException) as e:
            sys.stdout.write("Failed to connect!\n")
            sys.stdout.flush()
            logger.error(
                "Failed to connect to device %s: %s", self.device_config["ip"], e
            )
            self.connection = None
        return self.connection

    def disconnect(self):
        """Disconnect from the device."""
        if self.connection:
            try:
                self.connection.disconnect()
                sys.stdout.write(f"Disconnected from {self.device_config['ip']}.\n")
                sys.stdout.flush()
                logger.info("Disconnected from device %s.", self.device_config["ip"])
            except Exception as e:
                logger.error(
                    "Error disconnecting from %s: %s", self.device_config["ip"], e
                )
            finally:
                if self.connection in ACTIVE_CONNECTIONS:
                    ACTIVE_CONNECTIONS.remove(self.connection)

    def execute_commands(self, command_list):
        """Execute commands on the connected device."""
        if not self.connection:
            sys.stdout.write("Connection not established!\n")
            sys.stdout.flush()
            logger.error(
                "Cannot execute commands on device %s because the connection was not established.",
                self.device_config["ip"],
            )
            return []

        outputs = []
        for command in command_list:
            sys.stdout.write(f"Executing command: {command}... ")
            sys.stdout.flush()

            try:
                output = self.connection.send_command(command)
                sys.stdout.write("Done.\n")
                sys.stdout.flush()
                outputs.append(output)
                logger.info(
                    "Executed command on device %s: %s",
                    self.device_config["ip"],
                    command,
                )
            except Exception as e:
                sys.stdout.write("Failed!\n")
                sys.stdout.flush()
                logger.error(
                    "Error executing command '%s' on device %s: %s",
                    command,
                    self.device_config["ip"],
                    e,
                )
                outputs.append(f"Error executing command '{command}': {e}")

        return outputs


class OutputManager:
    """Manages output saving in different formats."""

    @staticmethod
    def save_output_to_csv(formatted_outputs, output_file_path):
        """Save output to CSV file."""
        os.makedirs(os.path.dirname(output_file_path), exist_ok=True)
        df = pd.DataFrame(formatted_outputs, columns=["IP", "DNS", "Output"])
        df.to_csv(output_file_path, index=False)

    @staticmethod
    def save_output_to_xlsx(formatted_outputs, output_file_path):
        """Save output to Excel file."""
        os.makedirs(os.path.dirname(output_file_path), exist_ok=True)
        df = pd.DataFrame(formatted_outputs, columns=["IP", "DNS", "Output"])
        df.to_excel(output_file_path, index=False, engine="openpyxl")

    @staticmethod
    def save_output_to_txt(formatted_outputs, output_file_path):
        """Save output to text file."""
        os.makedirs(os.path.dirname(output_file_path), exist_ok=True)
        with open(output_file_path, "w", encoding="utf-8") as file:
            for output in formatted_outputs:
                file.write("\n".join(output) + "\n")


def process_device(
    device_info, username, password, device_type, progress_tracker, result_list
):
    """Process a single device."""
    global CANCEL_EXECUTION
    if CANCEL_EXECUTION:
        return

    (ip_address, dns_name), commands = device_info

    # Inline status update before connecting
    sys.stdout.write(f"Connecting to {ip_address} ({dns_name})... ")
    sys.stdout.flush()

    device_config = {
        "device_type": device_type,
        "ip": ip_address,
        "dns": dns_name,
        "username": username,
        "password": password,
    }
    if device_type == "cisco_asa":
        device_config["secret"] = password

    device_conn = DeviceConnection(device_config)
    if device_conn.connect():
        command_outputs = device_conn.execute_commands(commands)
        formatted_output = format_device_output(device_config, command_outputs)
        device_conn.disconnect()
        with progress_tracker.get_lock():
            progress_tracker.value += 1
        result_list.append((ip_address, dns_name, formatted_output, True))
    else:
        with progress_tracker.get_lock():
            progress_tracker.value += 1
        result_list.append((ip_address, dns_name, [], False))


def save_all_outputs(all_outputs, output_formats, last_ip, last_dns, input_filename):
    """Save outputs in specified formats."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    sanitized_dns = sanitize_filename(last_dns)
    base_name = (
        f"{last_ip}_{sanitized_dns}"
        if input_filename == "manual_entry"
        else os.path.splitext(os.path.basename(input_filename))[0]
    )
    output_file_paths = {
        "csv": os.path.join(
            Config.LOG_DIR, Config.OUTPUT_SUBDIR, f"{base_name}_output_{timestamp}.csv"
        ),
        "xlsx": os.path.join(
            Config.LOG_DIR, Config.OUTPUT_SUBDIR, f"{base_name}_output_{timestamp}.xlsx"
        ),
        "txt": os.path.join(
            Config.LOG_DIR, Config.OUTPUT_SUBDIR, f"{base_name}_output_{timestamp}.txt"
        ),
    }
    if output_formats["csv"]:
        OutputManager.save_output_to_csv(all_outputs, output_file_paths["csv"])
    if output_formats["xlsx"]:
        OutputManager.save_output_to_xlsx(all_outputs, output_file_paths["xlsx"])
    if output_formats["txt"]:
        OutputManager.save_output_to_txt(all_outputs, output_file_paths["txt"])
    return output_file_paths


def execute_workflow(
    device_list,
    username,
    password,
    output_formats,
    device_type,
    pause_choice=False,
    timeout_duration=0,
    input_filename="",
    parallel_execution=False,
):
    """Execute the main workflow for device management."""
    global THREAD_POOL, CANCEL_EXECUTION
    create_directories()
    combined_outputs = []
    any_success = False
    last_ip = last_dns = None

    progress_tracker = Value("i", 0)
    manager = Manager()
    result_list = manager.list()

    logger.info("Starting workflow execution...")

    if parallel_execution and len(device_list) > 1:
        THREAD_POOL = ThreadPoolExecutor(max_workers=min(10, len(device_list)))
        futures = []
        for device_info in device_list.items():
            future = THREAD_POOL.submit(
                process_device,
                device_info,
                username,
                password,
                device_type,
                progress_tracker,
                result_list,
            )
            futures.append(future)

        for future in futures:
            if CANCEL_EXECUTION:
                break
            future.result()  # Wait for each future to complete
    else:
        for device_info in device_list.items():
            if CANCEL_EXECUTION:
                logger.info("Execution canceled by user.")
                break
            process_device(
                device_info,
                username,
                password,
                device_type,
                progress_tracker,
                result_list,
            )
            # Implement timeout between devices
            if 0 <= timeout_duration <= 1800:  # 0 to 30 minutes in seconds
                logger.info(
                    "Pausing for %d seconds between devices...", timeout_duration
                )
                time.sleep(timeout_duration)

            # Implement user-triggered pause
            if pause_choice:
                input("Press Enter to continue to the next device...")

    for ip_address, dns_name, output, success in result_list:
        if success:
            any_success = True
            combined_outputs.extend(output)
            last_ip, last_dns = ip_address, dns_name

    if any_success and not CANCEL_EXECUTION:
        output_file_paths = save_all_outputs(
            combined_outputs, output_formats, last_ip, last_dns, input_filename
        )
        logger.info("Combined output files saved at:")
        for fmt, path in output_file_paths.items():
            if output_formats[fmt]:
                logger.info("- %s", path)

    logger.info("Script execution completed.")


def forceful_cancel():
    """Forcefully cancels all operations."""
    global CANCEL_EXECUTION
    CANCEL_EXECUTION = True
    logger.info("Forceful cancel initiated.")

    if THREAD_POOL:
        THREAD_POOL.shutdown(wait=False)

    for conn in ACTIVE_CONNECTIONS:
        try:
            conn.disconnect()
        except Exception as e:
            logger.error("Error forcefully closing connection: %s", e)

    ACTIVE_CONNECTIONS.clear()
    logger.info("Forcefully terminating the script.")
    os._exit(1)


def setup_cancel_button_listener():
    """Set up a separate thread to listen for the 'q' key press."""

    def cancel_listener():
        logger.info("Press 'q' at any time to forcefully cancel all operations.")
        while True:
            if keyboard.is_pressed("q"):
                forceful_cancel()
                break

    cancel_thread = threading.Thread(target=cancel_listener)
    cancel_thread.daemon = True
    cancel_thread.start()


# Replace the original listener setup with the new one.
if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda signum, frame: forceful_cancel())

    # Set up the 'q' key listener for cancel
    setup_cancel_button_listener()

    # Set up your variables here
    device_list = DeviceManager.read_device_info(
        "example.csv"
    )  # these must match within the quotes
    username = "your_username"
    password = "your_password"
    output_formats = {"csv": True, "xlsx": False, "txt": False}  # Default csv
    device_type = "cisco_ios"  # from devices list lines 58-70
    pause_choice = False  # pause or break inbetween devices.
    timeout_duration = 0  # min=0, max=1800 (30mins)
    input_filename = "example.csv"  # these must match in the quotes
    parallel_execution = False  # Default False=serial, True=parallel

    # Call the main function
    execute_workflow(
        device_list,
        username,
        password,
        output_formats,
        device_type,
        pause_choice,
        timeout_duration,
        input_filename,
        parallel_execution,
    )
