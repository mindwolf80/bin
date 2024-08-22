"""Network Device Password Change Application using ttkbootstrap."""

import csv
import logging
import os
import threading
import warnings
from concurrent.futures import ThreadPoolExecutor
from enum import Enum

import ttkbootstrap as ttk
from ttkbootstrap.constants import BOTH, LEFT, RIGHT, END, DISABLED, NORMAL, Y
from ttkbootstrap.dialogs import Messagebox
from tkinter.filedialog import askopenfilename
from cryptography.utils import CryptographyDeprecationWarning
from netmiko import ConnectHandler

# Suppress warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning, module="paramiko")
warnings.simplefilter("ignore", category=CryptographyDeprecationWarning)
warnings.filterwarnings(
    "ignore", category=CryptographyDeprecationWarning, module="paramiko"
)


class DeviceType(Enum):
    """Enumeration of supported device types."""

    AUTODETECT = "autodetect"
    ARISTA_EOS = "arista_eos"
    CISCO_ASA = "cisco_asa"
    CISCO_FTD = "cisco_ftd"
    CISCO_IOS = "cisco_ios"
    CISCO_NXOS = "cisco_nxos"
    CISCO_S200 = "cisco_s200"
    CISCO_S300 = "cisco_s300"
    F5_LINUX = "f5_linux"
    F5_LTM = "f5_ltm"
    F5_TMSH = "f5_tmsh"
    JUNIPER_JUNOS = "juniper_junos"
    LINUX = "linux"
    PALOALTO_PANOS = "paloalto_panos"


class Config:
    """Configuration class for the application."""

    REQUIRED_HEADERS = ["ip", "dns", "current_password", "new_password", "device_type"]
    LOG_DIR = os.path.join(os.getcwd(), "logs")


class PasswordChangeApp(ttk.Window):
    """Main application class for the Network Device Password Change tool."""

    def __init__(self):
        """Initialize the PasswordChangeApp."""
        super().__init__(themename="darkly")

        self.title("Network Device Password Change")
        self.geometry("800x800")
        self.configure(padx=20, pady=20)

        self.create_widgets()
        self.stop_flag = threading.Event()
        self.active_connections = []
        self.safety_net_sessions = {}

        logging.basicConfig(
            filename="password_change.log",
            level=logging.DEBUG,
            format="%(asctime)s - %(levelname)s - %(message)s",
        )
        self.logger = logging.getLogger(__name__)

    def create_widgets(self):
        """Create and arrange the GUI widgets."""
        # File selection
        self.file_frame = ttk.Frame(self)
        self.file_frame.pack(fill=BOTH, pady=10)

        self.file_label = ttk.Label(self.file_frame, text="CSV File:")
        self.file_label.pack(side=LEFT)

        self.file_entry = ttk.Entry(self.file_frame, width=50)
        self.file_entry.pack(side=LEFT, padx=5)

        self.file_button = ttk.Button(
            self.file_frame, text="Browse", command=self.browse_file
        )
        self.file_button.pack(side=LEFT)

        # Username input
        self.username_frame = ttk.Frame(self)
        self.username_frame.pack(fill=BOTH, pady=10)

        self.username_label = ttk.Label(self.username_frame, text="Username:")
        self.username_label.pack(side=LEFT)

        self.username_entry = ttk.Entry(self.username_frame, width=30)
        self.username_entry.pack(side=LEFT, padx=5)

        # Password input
        self.password_frame = ttk.Frame(self)
        self.password_frame.pack(fill=BOTH, pady=10)

        self.password_label = ttk.Label(self.password_frame, text="Password:")
        self.password_label.pack(side=LEFT)

        self.password_entry = ttk.Entry(self.password_frame, show="*", width=30)
        self.password_entry.pack(side=LEFT, padx=5)

        self.show_password_var = ttk.BooleanVar()
        self.show_password_check = ttk.Checkbutton(
            self.password_frame,
            text="Show Password",
            variable=self.show_password_var,
            command=self.toggle_password_visibility,
        )
        self.show_password_check.pack(side=LEFT)

        # Log display
        self.log_frame = ttk.Frame(self)
        self.log_frame.pack(fill=BOTH, expand=True, pady=10)

        self.log_label = ttk.Label(self.log_frame, text="Logs:")
        self.log_label.pack()

        self.log_text = ttk.Text(self.log_frame, height=20, width=90)
        self.log_text.pack(side=LEFT, fill=BOTH, expand=True)

        self.log_scrollbar = ttk.Scrollbar(
            self.log_frame, orient="vertical", command=self.log_text.yview
        )
        self.log_scrollbar.pack(side=RIGHT, fill=Y)

        self.log_text.configure(yscrollcommand=self.log_scrollbar.set)

        # Control buttons
        self.button_frame = ttk.Frame(self)
        self.button_frame.pack(fill=BOTH, pady=10)

        self.start_button = ttk.Button(
            self.button_frame,
            text="Start Password Change",
            command=self.start_password_change,
        )
        self.start_button.pack(side=LEFT, padx=5)

        self.stop_button = ttk.Button(
            self.button_frame,
            text="Stop",
            command=self.stop_password_change,
            state=DISABLED,
        )
        self.stop_button.pack(side=LEFT, padx=5)

        self.rollback_button = ttk.Button(
            self.button_frame,
            text="Rollback Passwords",
            command=self.rollback_passwords,
            state=DISABLED,
        )
        self.rollback_button.pack(side=LEFT, padx=5)

        # Progress bar
        self.progress_var = ttk.DoubleVar()
        self.progress_bar = ttk.Progressbar(
            self, variable=self.progress_var, maximum=100
        )
        self.progress_bar.pack(fill=BOTH, pady=10)

    def browse_file(self):
        """Open a file dialog to select a CSV file."""
        filename = askopenfilename(filetypes=[("CSV Files", "*.csv")])
        if filename:
            self.file_entry.delete(0, END)
            self.file_entry.insert(0, filename)

    def toggle_password_visibility(self):
        """Toggle the visibility of the password entry."""
        if self.show_password_var.get():
            self.password_entry.configure(show="")
        else:
            self.password_entry.configure(show="*")

    def start_password_change(self):
        """Initiate the password change process."""
        csv_file = self.file_entry.get()
        username = self.username_entry.get()
        password = self.password_entry.get()

        if not csv_file or not username or not password:
            Messagebox.show_error("Please fill in all fields.", "Error")
            return

        self.start_button.configure(state=DISABLED)
        self.stop_button.configure(state=NORMAL)
        self.rollback_button.configure(state=DISABLED)
        self.progress_var.set(0)
        self.stop_flag.clear()

        self.password_change_thread = threading.Thread(
            target=self.run_password_change, args=(csv_file, username, password)
        )
        self.password_change_thread.start()

    def stop_password_change(self):
        """Stop the ongoing password change process."""
        self.stop_flag.set()
        self.log_message("Stopping password change process...")
        self.start_button.configure(state=NORMAL)
        self.stop_button.configure(state=DISABLED)
        self.rollback_button.configure(state=NORMAL)

    def rollback_passwords(self):
        """Initiate the password rollback process."""
        csv_file = self.file_entry.get()
        username = self.username_entry.get()
        password = self.password_entry.get()

        if not csv_file or not username or not password:
            Messagebox.show_error("Please fill in all fields.", "Error")
            return

        if Messagebox.show_question(
            "Are you sure you want to rollback all passwords?", "Confirm Rollback"
        ):
            self.start_button.configure(state=DISABLED)
            self.stop_button.configure(state=DISABLED)
            self.rollback_button.configure(state=DISABLED)
            self.progress_var.set(0)
            self.stop_flag.clear()

            self.rollback_thread = threading.Thread(
                target=self.run_rollback, args=(csv_file, username, password)
            )
            self.rollback_thread.start()

    def run_password_change(self, csv_file, username, password):
        """Execute the password change process for all devices."""
        devices = self.read_device_list(csv_file)
        total_devices = len(devices)

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(self.change_password, device, username, password)
                for device in devices
            ]
            for i, future in enumerate(futures):
                if self.stop_flag.is_set():
                    self.log_message("Password change process stopped.")
                    break
                try:
                    future.result()
                except Exception as e:
                    self.log_message(f"Error changing password: {str(e)}")
                self.progress_var.set((i + 1) / total_devices * 100)

        self.cleanup_safety_net_sessions()

        if not self.stop_flag.is_set():
            self.log_message("Password change process completed.")
        self.start_button.configure(state=NORMAL)
        self.stop_button.configure(state=DISABLED)
        self.rollback_button.configure(state=NORMAL)

    def run_rollback(self, csv_file, username, password):
        """Execute the password rollback process for all devices."""
        devices = self.read_device_list(csv_file)
        total_devices = len(devices)

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(self.rollback_password, device, username, password)
                for device in devices
            ]
            for i, future in enumerate(futures):
                if self.stop_flag.is_set():
                    self.log_message("Password rollback process stopped.")
                    break
                try:
                    future.result()
                except Exception as e:
                    self.log_message(f"Error rolling back password: {str(e)}")
                self.progress_var.set((i + 1) / total_devices * 100)

        if not self.stop_flag.is_set():
            self.log_message("Password rollback process completed.")
        self.start_button.configure(state=NORMAL)
        self.stop_button.configure(state=DISABLED)
        self.rollback_button.configure(state=NORMAL)

    def read_device_list(self, file_path):
        """Read the list of devices from a CSV file."""
        devices = []
        with open(file_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Skip lines that start with '#'
                if not row["ip"].strip().startswith("#"):
                    devices.append(row)
        return devices

    def change_password(self, device, username, password):
        """Change the password for a single device."""
        try:
            # First session
            connection1 = self.connect_to_device(device, username, password)
            self.log_message(f"Connected to {device['ip']} (Session 1)")

            # Safety net session
            connection2 = self.connect_to_device(device, username, password)
            self.log_message(f"Connected to {device['ip']} (Safety Net Session)")
            self.safety_net_sessions[device["ip"]] = connection2

            if device["device_type"] == DeviceType.CISCO_ASA.value:
                connection1.enable()

            self.execute_password_change(connection1, device)

            # Verify new password
            verification_success = self.verify_new_password(
                device, username, device["new_password"]
            )

            if verification_success:
                self.log_message(
                    f"Password changed and verified successfully for {device['ip']}"
                )
                connection2.disconnect()
                del self.safety_net_sessions[device["ip"]]
            else:
                self.log_message(
                    f"Password verification failed for {device['ip']}. Initiating rollback."
                )
                self.rollback_password_single_device(device, username, password)

            connection1.disconnect()

        except Exception as e:
            self.log_message(f"Error changing password for {device['ip']}: {str(e)}")

    def verify_new_password(self, device, username, new_password):
        """Verify the new password by attempting to connect."""
        for i in range(2):
            try:
                test_connection = self.connect_to_device(device, username, new_password)
                self.log_message(
                    f"Verification login {i+1} successful for {device['ip']}"
                )
                test_connection.disconnect()
            except Exception as e:
                self.log_message(
                    f"Verification login {i+1} failed for {device['ip']}: {str(e)}"
                )
                return False
        return True

    def rollback_password_single_device(self, device, username, password):
        """Rollback the password change for a single device."""
        try:
            connection = self.safety_net_sessions.get(device["ip"])
            if not connection:
                self.log_message(
                    f"No safety net session for {device['ip']}. Creating new connection."
                )
                connection = self.connect_to_device(device, username, password)

            self.log_message(f"Initiating rollback for {device['ip']}")

            if device["device_type"] == DeviceType.CISCO_ASA.value:
                connection.enable()

            self.execute_password_rollback(connection, device)

            self.log_message(f"Password rolled back successfully for {device['ip']}")

            rollback_verification = self.verify_new_password(
                device, username, device["current_password"]
            )
            if rollback_verification:
                self.log_message(f"Rollback verified successfully for {device['ip']}")
            else:
                self.log_message(
                    f"Rollback verification failed for {device['ip']}. Manual intervention required."
                )

            connection.disconnect()
            if device["ip"] in self.safety_net_sessions:
                del self.safety_net_sessions[device["ip"]]

        except Exception as e:
            self.log_message(
                f"Error rolling back password for {device['ip']}: {str(e)}"
            )

    def connect_to_device(self, device, username, password):
        """Establish a connection to a device."""
        device_params = {
            "device_type": device["device_type"],
            "ip": device["ip"],
            "username": username,
            "password": password,
        }
        if device["device_type"] == DeviceType.CISCO_ASA.value:
            device_params["secret"] = password
        connection = ConnectHandler(**device_params)
        return connection

    def execute_password_change(self, connection, device):
        """Execute the password change command on the device."""
        device_type = device["device_type"]
        new_password = device["new_password"]

        if device_type == DeviceType.CISCO_IOS.value:
            connection.send_config_set(
                [f"username {device['username']} password {new_password}"]
            )
        elif device_type == DeviceType.JUNIPER_JUNOS.value:
            connection.send_config_set(
                [
                    f"set system root-authentication plain-text-password {new_password}",
                    "commit",
                ]
            )
        elif device_type == DeviceType.ARISTA_EOS.value:
            connection.send_config_set(
                [f"username {device['username']} secret {new_password}"]
            )
        elif device_type == DeviceType.CISCO_ASA.value:
            connection.send_config_set(
                [f"username {device['username']} password {new_password}"]
            )
        elif device_type == DeviceType.CISCO_NXOS.value:
            connection.send_config_set(
                [f"username {device['username']} password {new_password}"]
            )
        elif device_type == DeviceType.PALOALTO_PANOS.value:
            connection.send_command(f"set password {new_password}")
        else:
            raise ValueError(f"Unsupported device type: {device_type}")

    def execute_password_rollback(self, connection, device):
        """Execute the password rollback command on the device."""
        device_type = device["device_type"]
        original_password = device["current_password"]

        if device_type == DeviceType.CISCO_IOS.value:
            connection.send_config_set(
                [f"username {device['username']} password {original_password}"]
            )
        elif device_type == DeviceType.JUNIPER_JUNOS.value:
            connection.send_config_set(
                [
                    f"set system root-authentication plain-text-password {original_password}",
                    "commit",
                ]
            )
        elif device_type == DeviceType.ARISTA_EOS.value:
            connection.send_config_set(
                [f"username {device['username']} secret {original_password}"]
            )
        elif device_type == DeviceType.CISCO_ASA.value:
            connection.send_config_set(
                [f"username {device['username']} password {original_password}"]
            )
        elif device_type == DeviceType.CISCO_NXOS.value:
            connection.send_config_set(
                [f"username {device['username']} password {original_password}"]
            )
        elif device_type == DeviceType.PALOALTO_PANOS.value:
            connection.send_command(f"set password {original_password}")
        else:
            raise ValueError(f"Unsupported device type: {device_type}")

    def cleanup_safety_net_sessions(self):
        """Close all safety net sessions."""
        for ip, session in self.safety_net_sessions.items():
            try:
                session.disconnect()
                self.log_message(f"Closed safety net session for {ip}")
            except Exception as e:
                self.log_message(f"Error closing safety net session for {ip}: {str(e)}")
        self.safety_net_sessions.clear()

    def log_message(self, message):
        """Log a message to both the GUI and the log file."""
        self.log_text.insert(END, message + "\n")
        self.log_text.see(END)
        self.logger.info(message)


if __name__ == "__main__":
    app = PasswordChangeApp()
    app.mainloop()
