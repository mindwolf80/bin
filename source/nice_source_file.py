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

import pandas as pd
import warnings
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

# Global variables
cancel_execution = False
thread_pool = None
active_connections = []

# Logging configuration
logging.basicConfig(
    filename="general_log.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
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


def is_valid_ip(ip):
    """Check if the given IP address is valid."""
    pattern = re.compile(r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$")
    return pattern.match(ip) is not None


def format_output(device, outputs):
    """Format the output for a device."""
    formatted = []
    ip = device["ip"]
    dns = device.get("dns", "")
    for i, output in enumerate(outputs):
        if i == 0:
            formatted.append([ip, dns, output])
        else:
            formatted.append(["", "", output])
    return formatted


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


class DeviceConnection:
    """Manages connections to network devices."""

    def __init__(self, device):
        """Initialize DeviceConnection with device information."""
        self.device = device
        self.connection = None

    def connect(self):
        """Establish a connection to the device."""
        try:
            connect_params = {k: v for k, v in self.device.items() if k != "dns"}
            self.connection = ConnectHandler(**connect_params)
            logging.info(f"Connected to device {self.device['ip']}.")
            active_connections.append(self.connection)
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
            try:
                self.connection.disconnect()
                logging.info(f"Disconnected from device {self.device['ip']}.")
            except Exception as e:
                logging.error(f"Error disconnecting from {self.device['ip']}: {e}")
            finally:
                if self.connection in active_connections:
                    active_connections.remove(self.connection)

    def execute_commands(self, commands):
        """Execute commands on the connected device."""
        if not self.connection:
            logging.error(
                f"Cannot execute commands on device {self.device['ip']} "
                f"because the connection was not established."
            )
            return []

        outputs = []
        for command in commands:
            if cancel_execution:
                logging.info(f"Execution canceled for device {self.device['ip']}.")
                break
            try:
                output = self.connection.send_command(command)
                outputs.append(output)
            except Exception as e:
                logging.error(
                    f"Error executing command '{command}' on device "
                    f"{self.device['ip']}: {e}"
                )
                outputs.append(f"Error executing command '{command}': {e}")

        return outputs


class OutputManager:
    """Manages output saving in different formats."""

    @staticmethod
    def save_output_to_csv(outputs, output_file_path):
        """Save output to CSV file."""
        os.makedirs(os.path.dirname(output_file_path), exist_ok=True)
        df = pd.DataFrame(outputs, columns=["IP", "DNS", "Output"])
        df.to_csv(output_file_path, index=False)

    @staticmethod
    def save_output_to_xlsx(outputs, output_file_path):
        """Save output to Excel file."""
        os.makedirs(os.path.dirname(output_file_path), exist_ok=True)
        df = pd.DataFrame(outputs, columns=["IP", "DNS", "Output"])
        df.to_excel(output_file_path, index=False, engine="openpyxl")

    @staticmethod
    def save_output_to_txt(outputs, output_file_path):
        """Save output to text file."""
        os.makedirs(os.path.dirname(output_file_path), exist_ok=True)
        with open(output_file_path, "w") as file:
            for output in outputs:
                file.write("\n".join(output) + "\n")


def process_device(device_info, username, password, device_type, progress, results):
    """Process a single device."""
    global cancel_execution
    if cancel_execution:
        return

    (ip, dns), commands = device_info
    device = {
        "device_type": device_type,
        "ip": ip,
        "dns": dns,
        "username": username,
        "password": password,
    }
    if device_type == "cisco_asa":
        device["secret"] = password

    connection = DeviceConnection(device)
    if connection.connect():
        outputs = connection.execute_commands(commands)
        formatted_output = format_output(device, outputs)
        connection.disconnect()
        with progress.get_lock():
            progress.value += 1
        results.append((ip, dns, formatted_output, True))
    else:
        with progress.get_lock():
            progress.value += 1
        results.append((ip, dns, [], False))


def save_outputs(all_outputs, output_formats, last_ip, last_dns, input_file_name):
    """Save outputs in specified formats."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    sanitized_dns = sanitize_filename(last_dns)
    base_name = (
        f"{last_ip}_{sanitized_dns}"
        if input_file_name == "manual_entry"
        else os.path.splitext(os.path.basename(input_file_name))[0]
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
    """Execute the main workflow for device management."""
    global thread_pool, cancel_execution
    create_directories()
    all_outputs = []
    any_success = False
    last_ip = last_dns = None

    progress = Value("i", 0)
    manager = Manager()
    results = manager.list()

    if use_parallel and len(devices) > 1:
        thread_pool = ThreadPoolExecutor(max_workers=min(10, len(devices)))
        futures = []
        for device_info in devices.items():
            future = thread_pool.submit(
                process_device,
                device_info,
                username,
                password,
                device_type,
                progress,
                results,
            )
            futures.append(future)

        for future in futures:
            if cancel_execution:
                break
            future.result()  # Wait for each future to complete
    else:
        for device_info in devices.items():
            if cancel_execution:
                logging.info("Execution canceled by user.")
                break
            process_device(
                device_info, username, password, device_type, progress, results
            )
            if pause_option == "timeout" and timeout > 0:
                logging.info(f"Pausing for {timeout} seconds...")
                time.sleep(timeout)
            elif pause_option == "keypress":
                input("Press Enter to continue to the next device...")

    for ip, dns, output, success in results:
        if success:
            any_success = True
            all_outputs.extend(output)
            last_ip, last_dns = ip, dns

    if any_success and not cancel_execution:
        output_file_paths = save_outputs(
            all_outputs, output_formats, last_ip, last_dns, input_file_name
        )
        logging.info("Combined output files saved at:")
        for format, path in output_file_paths.items():
            if output_formats[format]:
                logging.info(f"- {path}")

    logging.info("Script execution completed.")


def forceful_cancel():
    """Forcefully cancel all operations."""
    global cancel_execution, thread_pool, active_connections

    cancel_execution = True
    logging.info("Forceful cancel initiated.")

    # Cancel all ongoing threads
    if thread_pool:
        thread_pool.shutdown(wait=False)

    # Force close all active connections
    for conn in active_connections:
        try:
            conn.disconnect()
        except Exception as e:
            logging.error(f"Error forcefully closing connection: {e}")

    # Clear the active connections list
    active_connections.clear()

    # Use os._exit to forcefully terminate the script
    logging.info("Forcefully terminating the script.")
    os._exit(1)


def setup_cancel_button():
    """Set up a separate thread to listen for the cancel button press."""

    def cancel_listener():
        input("Press Enter to forcefully cancel all operations...")
        forceful_cancel()

    cancel_thread = threading.Thread(target=cancel_listener)
    cancel_thread.daemon = True
    cancel_thread.start()


if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda signum, frame: forceful_cancel())

    # Set up the cancel button listener
    setup_cancel_button()

    # Set up your variables here
    devices = DeviceManager.read_device_info("path_to_your_device_file.csv")
    username = "your_username"
    password = "your_password"
    output_formats = {"csv": True, "xlsx": False, "txt": False}
    device_type = "cisco_ios"  # or whatever device type you're using
    pause_option = "none"
    timeout = 0
    input_file_name = "path_to_your_device_file.csv"
    use_parallel = True

    # Call the main function
    execute_workflow(
        devices,
        username,
        password,
        output_formats,
        device_type,
        pause_option,
        timeout,
        input_file_name,
        use_parallel,
    )
