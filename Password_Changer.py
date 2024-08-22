import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import csv
import os
import logging
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
import threading
import warnings
import sys
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
    REQUIRED_HEADERS = ["ip", "dns", "current_password", "new_password", "device_type"]
    LOG_DIR = os.path.join(os.getcwd(), "logs")


class PasswordChangeApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Network Device Password Change")
        self.geometry("1280x720")
        self.configure(padx=20, pady=20)

        self.create_widgets()
        self.stop_flag = threading.Event()
        self.active_connections = []
        self.safety_net_sessions = {}

        logging.basicConfig(
            filename="password_change.log",
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
        )
        self.logger = logging.getLogger(__name__)

        # Redirect stdout to the terminal text widget
        sys.stdout = TextRedirector(self.terminal_text)

    def create_widgets(self):
        # File selection
        self.file_frame = ttk.Frame(self)
        self.file_frame.pack(fill=tk.X, pady=10)

        self.file_label = ttk.Label(self.file_frame, text="CSV File:")
        self.file_label.pack(side=tk.LEFT)

        self.file_entry = ttk.Entry(self.file_frame, width=50, font=("Segoe UI", 11))
        self.file_entry.pack(side=tk.LEFT, padx=5, ipady=2)

        self.file_button = ttk.Button(
            self.file_frame, text="Browse", command=self.browse_file
        )
        self.file_button.pack(side=tk.LEFT)

        # Username input
        self.username_frame = ttk.Frame(self)
        self.username_frame.pack(fill=tk.X, pady=10)

        self.username_label = ttk.Label(self.username_frame, text="Username:")
        self.username_label.pack(side=tk.LEFT)

        self.username_entry = ttk.Entry(
            self.username_frame, width=30, font=("Segoe UI", 11)
        )
        self.username_entry.pack(side=tk.LEFT, padx=5, ipady=2)

        # Password input
        self.password_frame = ttk.Frame(self)
        self.password_frame.pack(fill=tk.X, pady=10)

        self.password_label = ttk.Label(self.password_frame, text="Password:")
        self.password_label.pack(side=tk.LEFT)

        self.password_entry = ttk.Entry(
            self.password_frame, show="*", width=30, font=("Segoe UI", 11)
        )
        self.password_entry.pack(side=tk.LEFT, padx=5, ipady=2)

        self.show_password_var = tk.BooleanVar()
        self.show_password_check = ttk.Checkbutton(
            self.password_frame,
            text="Show Password",
            variable=self.show_password_var,
            command=self.toggle_password_visibility,
        )
        self.show_password_check.pack(side=tk.LEFT)

        # Mock Terminal display
        self.terminal_frame = ttk.Frame(self)
        self.terminal_frame.pack(fill=tk.BOTH, expand=True, pady=10)

        self.terminal_text = tk.Text(
            self.terminal_frame,
            height=20,
            width=90,
            bg="black",
            fg="#90EE90",
            font=("Consolas", 12),
        )
        self.terminal_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.terminal_scrollbar = ttk.Scrollbar(
            self.terminal_frame, orient="vertical", command=self.terminal_text.yview
        )
        self.terminal_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.terminal_text.configure(yscrollcommand=self.terminal_scrollbar.set)

        # Control buttons
        self.button_frame = ttk.Frame(self)
        self.button_frame.pack(fill=tk.X, pady=10)

        self.start_button = ttk.Button(
            self.button_frame,
            text="Start Password Change",
            command=self.start_password_change,
        )
        self.start_button.pack(side=tk.LEFT, padx=5)

        self.stop_button = ttk.Button(
            self.button_frame,
            text="Stop",
            command=self.stop_password_change,
            state=tk.DISABLED,
        )
        self.stop_button.pack(side=tk.LEFT, padx=5)

        self.rollback_button = ttk.Button(
            self.button_frame,
            text="Rollback Passwords",
            command=self.rollback_passwords,
            state=tk.DISABLED,
        )
        self.rollback_button.pack(side=tk.LEFT, padx=5)

        # Progress bar
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(
            self, variable=self.progress_var, maximum=100
        )
        self.progress_bar.pack(fill=tk.X, pady=10)

    def browse_file(self):
        filename = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv")])
        if filename:
            self.file_entry.delete(0, tk.END)
            self.file_entry.insert(0, filename)

    def toggle_password_visibility(self):
        if self.show_password_var.get():
            self.password_entry.config(show="")
        else:
            self.password_entry.config(show="*")

    def start_password_change(self):
        csv_file = self.file_entry.get()
        username = self.username_entry.get()
        password = self.password_entry.get()

        if not csv_file or not username or not password:
            messagebox.showerror("Error", "Please fill in all fields.")
            return

        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.rollback_button.config(state=tk.DISABLED)
        self.progress_var.set(0)
        self.stop_flag.clear()

        self.password_change_thread = threading.Thread(
            target=self.run_password_change, args=(csv_file, username, password)
        )
        self.password_change_thread.start()

    def stop_password_change(self):
        self.stop_flag.set()
        self.log_message("Stopping password change process...")
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.rollback_button.config(state=tk.NORMAL)

    def rollback_passwords(self):
        csv_file = self.file_entry.get()
        username = self.username_entry.get()
        password = self.password_entry.get()

        if not csv_file or not username or not password:
            messagebox.showerror("Error", "Please fill in all fields.")
            return

        if messagebox.askyesno(
            "Confirm Rollback", "Are you sure you want to rollback all passwords?"
        ):
            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.DISABLED)
            self.rollback_button.config(state=tk.DISABLED)
            self.progress_var.set(0)
            self.stop_flag.clear()

            self.rollback_thread = threading.Thread(
                target=self.run_rollback, args=(csv_file, username, password)
            )
            self.rollback_thread.start()

    def run_password_change(self, csv_file, username, password):
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
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.rollback_button.config(state=tk.NORMAL)

    def run_rollback(self, csv_file, username, password):
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
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.rollback_button.config(state=tk.NORMAL)

    def read_device_list(self, file_path):
        devices = []
        with open(file_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Skip lines that start with '#'
                if not row["ip"].strip().startswith("#"):
                    devices.append(row)
        return devices

    def change_password(self, device, username, password):
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
        try:
            connection = self.safety_net_sessions.get(device["ip"])
            if not connection:
                self.log_message(
                    f"No safety net session found for {device['ip']}. Attempting to create a new connection."
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
                    f"Rollback verification failed for {device['ip']}. Manual intervention may be required."
                )

            connection.disconnect()
            if device["ip"] in self.safety_net_sessions:
                del self.safety_net_sessions[device["ip"]]

        except Exception as e:
            self.log_message(
                f"Error rolling back password for {device['ip']}: {str(e)}"
            )

    def connect_to_device(self, device, username, password):
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
        elif device_type == DeviceType.LINUX.value:
            connection.send_command(
                f"echo -e '{new_password}\n{new_password}' | passwd"
            )
        elif device_type == DeviceType.F5_LINUX.value:
            connection.send_command(
                f"passwd root <<EOF\n{new_password}\n{new_password}\nEOF"
            )
        elif (
            device_type == DeviceType.F5_LTM.value
            or device_type == DeviceType.F5_TMSH.value
        ):
            connection.send_command(f"modify /auth user root password {new_password}")
        else:
            raise ValueError(f"Unsupported device type: {device_type}")

    def execute_password_rollback(self, connection, device):
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
        elif device_type == DeviceType.LINUX.value:
            connection.send_command(
                f"echo -e '{original_password}\n{original_password}' | passwd"
            )
        elif device_type == DeviceType.F5_LINUX.value:
            connection.send_command(
                f"passwd root <<EOF\n{original_password}\n{original_password}\nEOF"
            )
        elif (
            device_type == DeviceType.F5_LTM.value
            or device_type == DeviceType.F5_TMSH.value
        ):
            connection.send_command(
                f"modify /auth user root password {original_password}"
            )
        else:
            raise ValueError(f"Unsupported device type: {device_type}")

    def cleanup_safety_net_sessions(self):
        for ip, session in self.safety_net_sessions.items():
            try:
                session.disconnect()
                self.log_message(f"Closed safety net session for {ip}")
            except Exception as e:
                self.log_message(f"Error closing safety net session for {ip}: {str(e)}")
        self.safety_net_sessions.clear()

    def log_message(self, message):
        self.terminal_text.insert(tk.END, message + "\n")
        self.terminal_text.see(tk.END)
        self.logger.info(message)


class TextRedirector(object):
    def __init__(self, widget):
        self.widget = widget

    def write(self, message):
        self.widget.insert(tk.END, message)
        self.widget.see(tk.END)

    def flush(self):
        pass  # This is required for compatibility with Python's logging system.


if __name__ == "__main__":
    app = PasswordChangeApp()
    app.mainloop()
