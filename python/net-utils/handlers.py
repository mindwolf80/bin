# handlers.py
import contextlib
import functools
import json
import logging
import os
import re
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import List, Optional

from netmiko import ConnectHandler
from netmiko.exceptions import (
    ConfigInvalidException,
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
)
from paramiko.ssh_exception import SSHException
from PyQt6 import QtCore

# Configure logging
logging.basicConfig(
    filename="netmiko.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)
logger = logging.getLogger("netmiko")


def log_execution_time(func):
    """Decorator to log function execution time."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            execution_time = time.perf_counter() - start_time
            logger.info(
                f"{func.__name__} completed in {execution_time:.2f} seconds"
            )
            return result
        except Exception as e:
            execution_time = time.perf_counter() - start_time
            logger.error(
                f"{func.__name__} failed after {execution_time:.2f} seconds: {e}"
            )
            raise
    return wrapper


def retry_on_exception(retries=3, delay=1):
    """Decorator to retry a function on exception."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == retries - 1:
                        logger.error(
                            f"Failed after {retries} attempts: {e}"
                        )
                        raise
                    logger.warning(
                        f"Attempt {attempt + 1} failed: {e}. Retrying..."
                    )
                    time.sleep(delay)
            return None
        return wrapper
    return decorator


@dataclass(frozen=True)
class DeviceBatch:
    """Immutable device batch configuration."""
    devices: List[dict]
    commands: List[str]
    is_config_mode: bool = False

    def __post_init__(self):
        """Validate the batch configuration."""
        if not self.devices:
            raise ValueError("Device list cannot be empty")
        if not self.commands:
            raise ValueError("Command list cannot be empty")


class NetmikoWorker(QtCore.QThread):
    """Worker thread for executing network device commands."""
    
    # Use slots to reduce memory usage
    __slots__ = (
        'settings', 'devices_info', 'commands', 'is_running',
        'is_config_mode', '_lock', 'pause_event', '_error_patterns'
    )

    # Qt6 style signal declarations using new Signal class
    output_ready = QtCore.pyqtSignal(str, str, str, str)
    progress_update = QtCore.pyqtSignal(str)
    command_completed = QtCore.pyqtSignal()  # Signal for progress tracking
    batch_completed = QtCore.pyqtSignal(int)  # Signal for batch completion

    # Common error patterns and prompts as class variables
    _ERROR_PATTERNS = {
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

    # Common command prompts to strip
    _PROMPT_PATTERNS = {
        r"[\r\n]+[\w\-\.]+[#>][\s]*$",  # Basic Cisco/Linux style (hostname# or hostname>)
        r"[\r\n]+\S+@\S+:[~\w\d\/\-\.]+[#\$][\s]*$",  # Linux/Unix style (user@host:path$)
        r"[\r\n]+<[\w\-\.]+>[\s]*$",  # Juniper/XML style (<hostname>)
        r"[\r\n]+\[[\w\-\.]+\][#>][\s]*$",  # Bracket style ([hostname]#)
        r"[\r\n]+[\w\-\.]+\(config[\w\-\.]*\)#[\s]*$",  # Cisco config mode
        r"[\r\n]+[\w\-\.]+\([\w\-\.]+\)#[\s]*$",  # General config/context mode
    }

    def __init__(self, devices_info: List[dict], commands: List[str], is_config_mode: bool = False):
        """Initialize the NetmikoWorker thread.

        Args:
            devices_info: List of device connection parameters
            commands: List of commands to execute
            is_config_mode: Whether to execute commands in config mode
        """
        super().__init__()
        self.settings = self._load_network_settings()
        self.devices_info = devices_info
        self.commands = commands
        self.is_running = True
        self.is_config_mode = is_config_mode
        self._lock = threading.Lock()
        self.pause_event = threading.Event()
        self.pause_event.set()  # Initially not paused
        self._error_patterns = self._ERROR_PATTERNS

    @functools.lru_cache(maxsize=1)
    def _load_network_settings(self) -> dict:
        """Load and cache network settings from JSON file."""
        default_settings = {
            'ssh_timeout': 3,
            'conn_retry': 30,
            'cmd_timeout': 120,
            'auth_timeout': 30,
            'max_threads': 10,
            'batch_size': 5
        }
        
        try:
            if os.path.exists('network_settings.json'):
                with open('network_settings.json', 'r') as f:
                    settings = json.load(f)
                    return {
                        'ssh_timeout': settings.get('ssh_timeout', default_settings['ssh_timeout']),
                        'conn_retry': settings.get('conn_retry', default_settings['conn_retry']),
                        'cmd_timeout': settings.get('cmd_timeout', default_settings['cmd_timeout']),
                        'auth_timeout': settings.get('auth_timeout', default_settings['auth_timeout']),
                        'max_threads': settings.get('max_threads', default_settings['max_threads']),
                        'batch_size': settings.get('batch_size', default_settings['batch_size'])
                    }
        except Exception as e:
            logger.error(f"Error loading network settings: {e}")
        
        return default_settings

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

    @contextlib.contextmanager
    def device_connection(self, device_info: dict):
        """Context manager for handling device connections."""
        net_connect = None
        try:
            net_connect = ConnectHandler(**device_info)
            yield net_connect
        finally:
            if net_connect:
                try:
                    net_connect.disconnect()
                except Exception as e:
                    logger.error(f"Error disconnecting from device: {e}")

    @log_execution_time
    @retry_on_exception(retries=3)
    def process_device(self, device_info: dict) -> Optional[bool]:
        """Process a single device with retries and timing."""
        if not self.is_running:
            return None

        # Prepare device connection info
        connection_info = {
            **device_info,
            "fast_cli": False,
            "timeout": self.settings['auth_timeout'],
            "banner_timeout": self.settings['auth_timeout'],
            "auth_timeout": self.settings['auth_timeout'],
        }

        host = device_info["host"]
        username = device_info.get("username", "Unknown_User")
        retries = max(1, self.settings['conn_retry'] // 15)

        for attempt in range(1, retries + 1):
            if not self.is_running:
                logger.info("Thread stopped before completion.")
                return None

            try:
                # Log connection attempt
                logger.info(
                    f"Attempt {attempt}/{retries}: "
                    f"Initiating connection to {host}..."
                )
                self.progress_update.emit(
                    f"Establishing connection with {host} "
                    f"(Attempt {attempt}/{retries})..."
                )

                # Check SSH port accessibility
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

                # Use context manager for device connection
                with self.device_connection(connection_info) as net_connect:
                    if not self.is_running:
                        logger.info("Thread interrupted after connection.")
                        return None

                    logger.info(f"Connected to {host} on attempt {attempt}.")
                    self.progress_update.emit(f"Connected to {host}.")

                    # Execute commands based on mode
                    if self.is_config_mode:
                        self.execute_config_commands(net_connect, username, device_info)
                    else:
                        self.execute_normal_commands(net_connect, username, device_info)

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

    @log_execution_time
    def run(self):
        """Main execution logic for the thread using thread pool with device-based batch processing."""
        try:
            settings = self._load_network_settings()  # Use cached settings
            max_workers = settings['max_threads']
            batch_size = settings['batch_size']

            # Pre-validate devices and commands
            if not self.devices_info:
                raise ValueError("No devices provided")
            if not self.commands:
                raise ValueError("No commands provided")

            # Validate commands once for all devices
            valid_commands = [cmd for cmd in self.commands if isinstance(cmd, str) and cmd.strip()]
            if not valid_commands:
                raise ValueError("No valid commands to execute")

            # Create device batches for parallel processing
            device_batches = [
                self.devices_info[i:i + batch_size]
                for i in range(0, len(self.devices_info), batch_size)
            ]

            total_devices = len(self.devices_info)
            total_batches = len(device_batches)
            logger.info(
                f"Processing {total_devices} devices in {total_batches} batches "
                f"({len(valid_commands)} commands per device)"
            )
            self.progress_update.emit(
                f"Starting execution with {total_devices} devices..."
            )

            # Process device batches with thread pool
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                for batch_num, device_batch in enumerate(device_batches, 1):
                    if not self.is_running:
                        logger.info("Execution stopped by user")
                        break

                    batch_size = len(device_batch)
                    logger.info(
                        f"Processing device batch {batch_num}/{total_batches} "
                        f"({batch_size} devices, {len(valid_commands)} commands each)"
                    )
                    self.progress_update.emit(
                        f"Processing device batch {batch_num} of {total_batches}..."
                    )

                    # Submit each device in the batch to thread pool
                    futures = {
                        executor.submit(self.process_device, device): device
                        for device in device_batch
                    }

                    # Track batch completion
                    completed = 0
                    failed = 0

                    # Process completed device futures
                    for future in as_completed(futures):
                        if not self.is_running:
                            break

                        device = futures[future]
                        try:
                            if future.result():
                                completed += 1
                            else:
                                failed += 1
                        except Exception as e:
                            failed += 1
                            self.handle_error(
                                "EXECUTION ERROR",
                                device["host"],
                                str(e)
                            )

                    # Log batch completion statistics
                    logger.info(
                        f"Device batch {batch_num} completed: "
                        f"{completed} succeeded, {failed} failed"
                    )
                    self.batch_completed.emit(completed)

                    # Wait for pause if needed
                    self.pause_event.wait()

            # Log final statistics
            logger.info(
                f"Execution completed: {total_devices} devices processed "
                f"with {len(valid_commands)} commands each"
            )
            self.progress_update.emit("Execution completed")

        except Exception as e:
            error_msg = f"Thread pool execution error: {str(e)}"
            logger.error(error_msg)
            self.progress_update.emit(error_msg)
            raise

    @log_execution_time
    def execute_normal_commands(self, net_connect, username: str, device_info: dict) -> None:
        """Execute a list of commands in normal mode with optimized error handling."""
        host = device_info["host"]
        total_commands = len(self.commands)
        
        logger.info(f"Executing {total_commands} commands on {host}")
        self.progress_update.emit(f"Executing commands on {host}...")

        # Pre-validate commands
        valid_commands = [cmd for cmd in self.commands if isinstance(cmd, str) and cmd.strip()]
        if not valid_commands:
            self.handle_error(
                "VALIDATION ERROR",
                host,
                "No valid commands to execute"
            )
            return

        for index, command in enumerate(valid_commands, 1):
            # Check execution state
            self.pause_event.wait()
            if not self.is_running:
                logger.info(f"Command execution stopped on {host}")
                return

            try:
                # Execute command with timeout and error handling
                with self._lock:
                    logger.debug(
                        f"Executing command {index}/{total_commands} "
                        f"on {host}: {command}"
                    )
                    output = net_connect.send_command(
                        command,
                        read_timeout=self.settings['cmd_timeout'],
                        strip_prompt=True,
                        strip_command=True,
                        expect_string=r"[#>$\]][\s]*$"  # Match common prompt endings
                    )

                    # Additional prompt stripping for various device types
                    for pattern in self._PROMPT_PATTERNS:
                        output = re.sub(pattern, "", output)

                # Validate command output
                if self.is_invalid_command(output):
                    error_msg = (
                        f"Invalid command: {command}\n"
                        f"Output indicates an error or invalid syntax"
                    )
                    logger.warning(f"{error_msg} on {host}")
                    self.output_ready.emit(
                        username,
                        host,
                        command,
                        error_msg,
                    )
                    continue  # Continue with next command instead of breaking

                # Process successful output
                self.output_ready.emit(
                    username,
                    host,
                    command,
                    output,
                )
                self.command_completed.emit()
                
                # Log progress
                logger.debug(
                    f"Command {index}/{total_commands} completed successfully on {host}"
                )

            except Exception as e:
                error_msg = f"Failed to execute command: {command}"
                logger.error(f"{error_msg} on {host}: {str(e)}")
                self.handle_error(
                    "COMMAND ERROR",
                    host,
                    e,
                    command,
                )
                # Continue with next command instead of breaking
                continue

        logger.info(f"Completed all commands on {host}")

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

    @log_execution_time
    def execute_config_commands(self, net_connect, username: str, device_info: dict) -> None:
        """Execute commands in configuration mode with optimized error handling and logging."""
        host = device_info["host"]
        
        try:
            # Pre-validate commands
            valid_commands = [cmd for cmd in self.commands if isinstance(cmd, str) and cmd.strip()]
            if not valid_commands:
                raise ValueError("No valid configuration commands found")

            total_commands = len(valid_commands)
            logger.info(f"Executing {total_commands} configuration commands on {host}")
            self.progress_update.emit(f"Entering configuration mode on {host}...")

            try:
                # Enter configuration mode with verification
                if not net_connect.check_config_mode():
                    logger.debug(f"Entering config mode on {host}")
                    net_connect.config_mode()
                    if not net_connect.check_config_mode():
                        raise ConfigInvalidException("Failed to enter configuration mode")

                # Execute configuration commands with progress tracking
                logger.debug(f"Sending configuration commands to {host}")
                output = net_connect.send_config_set(
                    valid_commands,
                    cmd_verify=True,
                    read_timeout=self.settings['cmd_timeout'],
                    error_pattern=self._ERROR_PATTERNS,  # Use class-level error patterns
                    expect_string=r"[#>$\]][\s]*$"  # Match common prompt endings
                )

                # Additional prompt stripping for various device types
                for pattern in self._PROMPT_PATTERNS:
                    output = re.sub(pattern, "", output)

                # Safely exit configuration mode
                try:
                    if net_connect.check_config_mode():
                        logger.debug(f"Exiting config mode on {host}")
                        net_connect.exit_config_mode()
                except Exception as e:
                    logger.warning(f"Error exiting config mode on {host}: {e}")

                # Validate command output
                if self.is_invalid_command(output):
                    error_msg = (
                        "One or more configuration commands resulted in error.\n"
                        "Please check the output for specific error messages."
                    )
                    logger.error(f"Configuration error on {host}: {error_msg}")
                    self.handle_error(
                        "CONFIG INVALID ERROR",
                        host,
                        error_msg,
                    )
                else:
                    # Process successful output
                    logger.info(f"Successfully executed {total_commands} configuration commands on {host}")
                    self.output_ready.emit(
                        username,
                        host,
                        "CONFIG MODE",
                        output,
                    )
                    self.command_completed.emit()

            except ConfigInvalidException as e:
                error_msg = f"Configuration mode error: {str(e)}"
                logger.error(f"{error_msg} on {host}")
                self.handle_error(
                    "CONFIG INVALID ERROR",
                    host,
                    error_msg,
                )
            except Exception as e:
                error_msg = f"Failed to execute configuration commands: {str(e)}"
                logger.error(f"{error_msg} on {host}")
                self.handle_error(
                    "CONFIG MODE ERROR",
                    host,
                    error_msg,
                )

        except ValueError as e:
            error_msg = f"Configuration validation error: {str(e)}"
            logger.error(f"{error_msg} on {host}")
            self.handle_error(
                "CONFIG VALIDATION ERROR",
                host,
                error_msg,
            )
        except Exception as e:
            error_msg = f"Unexpected error in configuration mode: {str(e)}"
            logger.error(f"{error_msg} on {host}")
            self.handle_error(
                "CONFIG ERROR",
                host,
                error_msg,
            )

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
