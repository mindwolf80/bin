# handlers.py
import json
import logging
import os
import socket
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from netmiko import ConnectHandler
from netmiko.exceptions import (
    ConfigInvalidException,
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
)
from paramiko.ssh_exception import SSHException
from PyQt5 import QtCore

# Configure logging
logging.basicConfig(
    filename="netmiko.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)
logger = logging.getLogger("netmiko")


class DeviceBatch:
    def __init__(self, devices, commands, is_config_mode=False):
        self.devices = devices
        self.commands = commands
        self.is_config_mode = is_config_mode


class NetmikoWorker(QtCore.QThread):
    output_ready = QtCore.pyqtSignal(str, str, str, str)
    progress_update = QtCore.pyqtSignal(str)
    command_completed = QtCore.pyqtSignal()  # Signal for progress tracking
    batch_completed = QtCore.pyqtSignal(int)  # Signal for batch completion

    def __init__(self, devices_info, commands, is_config_mode=False):
        """Initialize the NetmikoWorker thread.

        Args:
            devices_info (list): List of device connection parameters
            commands (list): List of commands to execute
            is_config_mode (bool): Whether to execute commands in config mode
        """
        super().__init__()
        self.settings = self.load_network_settings()
        self.devices_info = devices_info
        self.commands = commands
        self.is_running = True
        self.is_config_mode = is_config_mode
        self._lock = threading.Lock()
        self.pause_event = threading.Event()
        self.pause_event.set()  # Initially not paused

    def load_network_settings(self):
        """Load network settings from JSON file."""
        try:
            if os.path.exists('network_settings.json'):
                with open('network_settings.json', 'r') as f:
                    settings = json.load(f)
                    return {
                        'ssh_timeout': settings.get('ssh_timeout', 3),
                        'conn_retry': settings.get('conn_retry', 30),
                        'cmd_timeout': settings.get('cmd_timeout', 120),
                        'auth_timeout': settings.get('auth_timeout', 30),
                        'max_threads': settings.get('max_threads', 10),
                        'batch_size': settings.get('batch_size', 5)
                    }
        except Exception as e:
            logger.error(f"Error loading network settings: {e}")
        return {
            'ssh_timeout': 3,
            'conn_retry': 30,
            'cmd_timeout': 120,
            'auth_timeout': 30,
            'max_threads': 10,
            'batch_size': 5
        }

    def check_ssh_port(self, host, port=22, timeout=None):
        """Check if the SSH port is accessible."""
        timeout = timeout or self.settings['ssh_timeout']
        try:
            with socket.create_connection((host, port), timeout=timeout):
                logger.info(f"SSH port {port} on {host} is accessible.")
                return True
        except socket.timeout:
            logger.error(f"Timeout while checking SSH port {port} on {host}.")
        except socket.error as e:
            logger.error(
                f"Socket error while checking SSH port {port} on {host}: {e}"
            )
        return False

    def process_device(self, device_info):
        """Process a single device with retries."""
        if not self.is_running:
            return None

        device_info = {
            **device_info,
            "fast_cli": False,
            "timeout": self.settings['auth_timeout'],
            "banner_timeout": self.settings['auth_timeout'],
            "auth_timeout": self.settings['auth_timeout'],
        }

        retries = max(1, self.settings['conn_retry'] // 15)
        for attempt in range(1, retries + 1):
            if not self.is_running:
                logger.info("Thread stopped before completion.")
                return None
            try:
                host = device_info["host"]
                username = device_info.get("username", "Unknown_User")

                logger.info(
                    f"Attempt {attempt}/{retries}: "
                    f"Initiating connection to {host}..."
                )
                self.progress_update.emit(
                    f"Establishing connection with {host} "
                    f"(Attempt {attempt}/{retries})..."
                )

                if not self.check_ssh_port(host):
                    error_msg = f"SSH port 22 is not accessible on {host}"
                    logger.error(error_msg)
                    self.output_ready.emit(
                        username,
                        host,
                        "CONNECTION ERROR",
                        error_msg,
                    )
                    return None

                net_connect = ConnectHandler(**device_info)
                if not self.is_running:
                    logger.info("Thread interrupted after connection.")
                    net_connect.disconnect()
                    return None

                logger.info(f"Connected to {host} on attempt {attempt}.")
                self.progress_update.emit(f"Connected to {host}.")

                try:
                    if self.is_config_mode:
                        self.execute_config_commands(net_connect, username, device_info)
                    else:
                        self.execute_normal_commands(net_connect, username, device_info)
                finally:
                    if net_connect:
                        net_connect.disconnect()
                return True

            except NetmikoAuthenticationException as e:
                self.handle_error("AUTH ERROR", host, e)
                return False
            except NetmikoTimeoutException as e:
                self.handle_error("TIMEOUT ERROR", host, e)
                if attempt == retries:
                    return False
            except SSHException as e:
                self.handle_error("SSH ERROR", host, e)
                if attempt == retries:
                    return False
            except Exception as e:
                self.handle_error("CRITICAL ERROR", host, e)
                return False
        return False

    def run(self):
        """Main execution logic for the thread using thread pool."""
        try:
            settings = self.load_network_settings()
            max_workers = settings.get('max_threads', 10)
            batch_size = settings.get('batch_size', 5)

            # Process devices in batches
            for i in range(0, len(self.devices_info), batch_size):
                if not self.is_running:
                    break

                batch = self.devices_info[i:i + batch_size]
                completed = 0

                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    # Submit all devices in the batch to the thread pool
                    future_to_device = {
                        executor.submit(self.process_device, device): device
                        for device in batch
                    }

                    # Process completed futures as they finish
                    for future in as_completed(future_to_device):
                        if not self.is_running:
                            break

                        device = future_to_device[future]
                        try:
                            success = future.result()
                            if success:
                                completed += 1
                        except Exception as e:
                            self.handle_error(
                                "EXECUTION ERROR",
                                device["host"],
                                str(e)
                            )

                    # Emit batch completion signal
                    self.batch_completed.emit(completed)

                    # Wait for pause if needed
                    self.pause_event.wait()

        except Exception as e:
            logger.error(f"Thread pool execution error: {str(e)}")
            self.progress_update.emit(f"Execution error: {str(e)}")

    def execute_normal_commands(self, net_connect, username, device_info):
        """Execute a list of commands in normal mode."""
        for command in self.commands:
            self.pause_event.wait()  # Wait if paused
            if not self.is_running:
                return

            try:
                with self._lock:
                    logger.debug(
                        "Executing command: {} on {}".format(
                            command, device_info["host"]
                        )
                    )
                    output = net_connect.send_command(
                        command,
                        read_timeout=self.settings['cmd_timeout'],
                        strip_prompt=True,
                        strip_command=True,
                    )

                if self.is_invalid_command(output):
                    error_msg = f"INVALID COMMAND: {command}"
                    logger.warning(error_msg)
                    self.output_ready.emit(
                        username,
                        device_info["host"],
                        command,
                        error_msg,
                    )
                else:
                    self.output_ready.emit(
                        username,
                        device_info["host"],
                        command,
                        output,
                    )
                    # Emit signal after command completion
                    self.command_completed.emit()

            except Exception as e:
                self.handle_error(
                    "COMMAND ERROR",
                    device_info["host"],
                    e,
                    command,
                )
                break

    @QtCore.pyqtSlot()
    def pause(self):
        """Pause the thread execution."""
        with self._lock:
            if self.pause_event.is_set():  # Only if currently running
                self.pause_event.clear()  # Pause the execution
                logger.info("Execution paused.")
                self.progress_update.emit("Execution paused...")

    @QtCore.pyqtSlot()
    def resume(self):
        """Resume the thread execution."""
        with self._lock:
            if not self.pause_event.is_set():  # Only if currently paused
                self.pause_event.set()  # Resume the execution
                logger.info("Execution resumed.")
                self.progress_update.emit("Execution resumed...")

    def execute_config_commands(self, net_connect, username, device_info):
        """Execute commands in configuration mode."""
        try:
            if not self.commands:
                raise ValueError("No configuration commands provided.")

            valid_commands = [
                cmd for cmd in self.commands
                if isinstance(cmd, str) and cmd.strip()
            ]
            if not valid_commands:
                raise ValueError("No valid configuration commands found.")

            logger.debug(
                f"Executing configuration commands on "
                f"{device_info['host']}."
            )
            try:
                # Enter config mode and verify
                if not net_connect.check_config_mode():
                    net_connect.config_mode()

                output = net_connect.send_config_set(
                    valid_commands,
                    cmd_verify=True,
                    read_timeout=self.settings['cmd_timeout']
                )

                # Exit config mode
                if net_connect.check_config_mode():
                    net_connect.exit_config_mode()

                # Check for common error patterns in output
                if self.is_invalid_command(output):
                    self.handle_error(
                        "CONFIG INVALID ERROR",
                        device_info["host"],
                        "One or more commands resulted in error",
                    )
                else:
                    self.output_ready.emit(
                        username,
                        device_info["host"],
                        "CONFIG MODE",
                        output,
                    )
                    # Only emit completion for successfully executed commands
                    self.command_completed.emit()

            except ConfigInvalidException as e:
                self.handle_error(
                    "CONFIG INVALID ERROR",
                    device_info["host"],
                    e,
                )
            except Exception as e:
                error_msg = f"Failed to execute config commands: {str(e)}"
                self.handle_error(
                    "CONFIG MODE ERROR",
                    device_info["host"],
                    error_msg,
                )

        except ValueError as e:
            self.handle_error(
                "CONFIG VALIDATION ERROR",
                device_info["host"],
                e,
            )
        except Exception as e:
            self.handle_error("CONFIG ERROR", device_info["host"], e)

    def _has_error_markers(self, line):
        """Check if a line contains error markers."""
        return line.strip().startswith("%") or "error" in line.lower()

    def is_invalid_command(self, output):
        """Check if the command output indicates an invalid command error."""
        error_indicators = {
            "% Invalid input detected",
            "Invalid command",
            "-ash: invalid",
            "not found",
            "% Error",
            "syntax error",
            "unknown command",
            "incomplete command",
            "ambiguous command",
            "% Unknown command",
            "% Incomplete command",
            "% Ambiguous command",
        }

        # Split output into lines and check each line
        output_lines = output.lower().splitlines()

        # Check for error patterns
        for line in output_lines:
            if any(err in line for err in error_indicators):
                return True

        # Check for suspiciously short output that might indicate an error
        if len(output_lines) <= 2 and output.strip():
            return any(self._has_error_markers(line) for line in output_lines)

        return False

    def handle_error(self, error_type, host, error, command=None):
        """Handle errors and emit appropriate signals."""
        error_msg = f"{error_type} on {host}: {error}"
        if command:
            error_msg += f" (Command: {command})"
        logger.error(error_msg)
        self.output_ready.emit(
            "Unknown_User",  # We don't have device_info in this context
            host,
            error_type,
            error_msg
        )

    def stop(self):
        """Gracefully stop the thread and clean up resources."""
        with self._lock:
            self.is_running = False
            self.pause_event.set()  # Ensure the thread can exit if paused

        logger.info("Stopping thread...")
        self.progress_update.emit("Thread stopping...")
        self.quit()  # Properly quit the QThread
