# main.py
import yaml
from netmiko import ConnectHandler
import os
from datetime import datetime
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import threading
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.panel import Panel

# Initialize Rich Console
console = Console()

# Setup logging with console and file handlers
logger = logging.getLogger("network_automation")
logger.setLevel(logging.INFO)

# File handler
fh = logging.FileHandler("network_automation.log")
fh.setLevel(logging.INFO)

# Console handler
ch = logging.StreamHandler()
ch.setLevel(logging.WARNING)

# Formatter
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
fh.setFormatter(formatter)
ch.setFormatter(formatter)

# Add handlers to logger
logger.addHandler(fh)
logger.addHandler(ch)


logger = logging.getLogger("network_automation")
logger.setLevel(logging.INFO)


# Load YAML configuration file
def load_config(file_path):
    """
    Load a YAML configuration file and set up the environment.

    Args:
        file_path (str): The path to the configuration file.

    Returns:
        dict: The configuration data.

    Raises:
        SystemExit: If the file is not found or there is a YAML parsing error.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            config = yaml.safe_load(file)

            # Ensure the 'results' directory exists
            results_dir = os.path.join(os.getcwd(), "results")
            os.makedirs(results_dir, exist_ok=True)

            # Check if text file generation is enabled
            generate_txt_files = config.get("generate_txt_files", False)
            if generate_txt_files:
                logger.info("Text file generation is enabled.")
                with open(
                    os.path.join(results_dir, "output.txt"), "w", encoding="utf-8"
                ) as txt_file:
                    txt_file.write("Sample content")
            else:
                logger.info("Text file generation is disabled.")

            # Always generate CSV and netmiko_log files
            with open(
                os.path.join(results_dir, "output.csv"),
                "w",
                newline="",
                encoding="utf-8",
            ) as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(["Header1", "Header2"])
                writer.writerow(["Row1Col1", "Row1Col2"])

            # Example of handling netmiko_log
            netmiko_log_path = os.path.join(results_dir, "netmiko_log.log")
            with open(netmiko_log_path, "w", encoding="utf-8") as log_file:
                log_file.write("Netmiko log content")

            # Check if pause after command is enabled
            pause_after_command = config.get("pause_after_command", False)
            if pause_after_command:
                logger.info("Pausing after each command is enabled.")

            return config
    except FileNotFoundError:
        logger.error(f"Configuration file '{file_path}' not found.")
        raise SystemExit(1)
    except yaml.YAMLError as exc:
        logger.error(f"Error parsing '{file_path}': {exc}")
        raise SystemExit(1)


# Example usage
config = load_config("config.yaml")

config = load_config("config.yaml")

credentials = config.get("credentials", {})
default_password = credentials.get("default_password")

groups_config = config.get("groups", {})
hosts_config = config.get("hosts", [])

# Prepare results directory
results_dir = "results"
os.makedirs(results_dir, exist_ok=True)
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

# Initialize CSV file
CSV_FILE = f"command_results_{timestamp}.csv"
csv_lock = threading.Lock()
csv_headers = ["Hostname", "Device Type", "Command", "Output", "Timestamp"]

with open(CSV_FILE, mode="w", newline="", encoding="utf-8") as csvfile:
    writer = csv.DictWriter(csvfile, fieldnames=csv_headers)
    writer.writeheader()


def display_hosts(hosts):
    table = Table(title="Available Devices", show_header=True, header_style="bold cyan")
    table.add_column("No.", style="dim", width=6)
    table.add_column("Hostname", style="bold")
    table.add_column("Device Type", style="green")
    table.add_column("Groups", style="magenta")

    for idx, host in enumerate(hosts, start=1):
        groups = ", ".join(host.get("groups", []))
        table.add_row(str(idx), host["hostname"], host["device_type"], groups)

    console.print(table)


def get_user_selection(hosts, max_retries=3):
    host_count = len(hosts)
    selected_indices = []
    retries = 0

    while retries < max_retries:
        selection = console.input(
            "\nEnter the numbers of the devices you want to manage "
            "(comma-separated, or 0 for all): "
        )

        if selection.strip() == "0":
            return hosts

        try:
            indices = [int(x.strip()) for x in selection.split(",")]
            for idx in indices:
                if 1 <= idx <= host_count:
                    selected_indices.append(idx - 1)
                else:
                    raise ValueError(f"Number {idx} is out of range.")
            if selected_indices:
                selected_hosts = [hosts[i] for i in selected_indices]
                return selected_hosts
        except ValueError as ve:
            console.print(
                f"[bold red]Invalid input: {ve}[/bold red]. Please try again."
            )
            retries += 1
            selected_indices = []  # Reset selections on invalid input

    console.print("[bold red]Maximum retries exceeded. Exiting.[/bold red]")
    exit(1)


def execute_commands(host):
    device = {
        "device_type": host["device_type"],
        "host": host["hostname"],
        "username": host["username"],
        "password": host.get("password", default_password),
        "secret": host.get("secret", ""),  # Enable password if needed
        "fast_cli": False,  # Set to False for better compatibility
    }

    output_file = os.path.join(results_dir, f"{host['hostname']}_{timestamp}.txt")

    try:
        logger.info(f"Connecting to {device['host']} ({device['device_type']})")
        connection = ConnectHandler(**device)
        if device["secret"]:
            connection.enable()
            logger.info(f"Entered enable mode on {device['host']}")

        # Aggregate commands from all groups the host belongs to
        all_commands = []
        for group in host.get("groups", []):
            group_commands = groups_config.get(group, {}).get("commands", [])
            all_commands.extend(group_commands)

        # Remove duplicate commands
        all_commands = list(set(all_commands))

        with open(output_file, "w") as f:
            for cmd in all_commands:
                try:
                    logger.info(f"Executing '{cmd}' on {device['host']}")
                    output = connection.send_command(cmd)
                    f.write(f"Command: {cmd}\nOutput:\n{output}\n{'-'*80}\n")

                    # Display output in terminal using Rich Panels with yellow commands
                    command_panel = Panel.fit(
                        f"Command: [yellow]{cmd}[/yellow]\n\n{output}",
                        title=f"[green]{device['host']}[/green]",
                        border_style="green",
                    )
                    console.print(command_panel)

                    # Write to CSV
                    with csv_lock:
                        with open(
                            CSV_FILE, mode="a", newline="", encoding="utf-8"
                        ) as csvfile:
                            writer = csv.DictWriter(csvfile, fieldnames=csv_headers)
                            writer.writerow(
                                {
                                    "Hostname": device["host"],
                                    "Device Type": device["device_type"],
                                    "Command": cmd,
                                    "Output": output,
                                    "Timestamp": datetime.now().strftime(
                                        "%Y-%m-%d %H:%M:%S"
                                    ),
                                }
                            )

                except Exception as cmd_exc:
                    logger.error(
                        f"Error executing '{cmd}' on {device['host']}': {cmd_exc}"
                    )
                    error_output = f"ERROR: {cmd_exc}"
                    f.write(f"Command: {cmd}\nOutput:\n{error_output}\n{'-'*80}\n")

                    # Display error in terminal using Rich Panels with yellow commands
                    error_panel = Panel.fit(
                        f"Command: [yellow]{cmd}[/yellow]\n\n{error_output}",
                        title=f"[red]{device['host']}[/red]",
                        border_style="red",
                    )
                    console.print(error_panel)

                    # Write error to CSV
                    with csv_lock:
                        with open(
                            CSV_FILE, mode="a", newline="", encoding="utf-8"
                        ) as csvfile:
                            writer = csv.DictWriter(csvfile, fieldnames=csv_headers)
                            writer.writerow(
                                {
                                    "Hostname": device["host"],
                                    "Device Type": device["device_type"],
                                    "Command": cmd,
                                    "Output": error_output,
                                    "Timestamp": datetime.now().strftime(
                                        "%Y-%m-%d %H:%M:%S"
                                    ),
                                }
                            )

        connection.disconnect()
        logger.info(f"Disconnected from {device['host']}")

    except Exception as e:
        logger.error(f"Failed to connect or execute commands on {device['host']}: {e}")
        error_message = f"Failed to connect or execute commands: {e}"
        # Display connection error in terminal using Rich Panels
        error_panel = Panel.fit(
            f"{error_message}", title=f"[red]{device['host']}[/red]", border_style="red"
        )
        console.print(error_panel)


def main():
    # Display all available hosts using Rich Table
    display_hosts(hosts_config)

    # Get user selection
    selected_hosts = get_user_selection(hosts_config)

    # Confirm selection using Rich Table
    table = Table(title="Selected Devices", show_header=True, header_style="bold cyan")
    table.add_column("No.", style="dim", width=6)
    table.add_column("Hostname", style="bold")
    table.add_column("Device Type", style="green")
    table.add_column("Groups", style="magenta")

    for idx, host in enumerate(selected_hosts, start=1):
        groups = ", ".join(host.get("groups", []))
        table.add_row(str(idx), host["hostname"], host["device_type"], groups)

    console.print(table)

    # Initialize Progress Bar using Rich
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        task = progress.add_task(
            "[green]Executing Commands...", total=len(selected_hosts)
        )

        # Use ThreadPoolExecutor for parallel execution
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {
                executor.submit(execute_commands, host): host for host in selected_hosts
            }
            for future in as_completed(futures):
                progress.advance(task)

    logger.info(
        "All tasks completed. Check the 'results' directory, CSV file, and 'network_automation.log' for details."
    )
    console.print(
        Panel.fit(
            "[bold green]All tasks completed![/bold green]\nCheck the 'results' directory, CSV file, and 'network_automation.log' for details."
        )
    )


if __name__ == "__main__":
    main()
