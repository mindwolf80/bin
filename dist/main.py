import os
import yaml
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import threading
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.panel import Panel
from netmiko import ConnectHandler

# Initialize Rich Console
console = Console()

# Setup logging
logger = logging.getLogger("network_automation")
logger.setLevel(logging.INFO)

# File handler setup
fh = logging.FileHandler("network_automation.log")
fh.setLevel(logging.INFO)

# Console handler setup
ch = logging.StreamHandler()
ch.setLevel(logging.WARNING)

# Formatter setup
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
fh.setFormatter(formatter)
ch.setFormatter(formatter)

# Add handlers to logger
logger.addHandler(fh)
logger.addHandler(ch)


def load_config(file_path: str) -> dict:
    """
    Load a YAML configuration file, ensure the 'results' directory exists,
    and check for specific configuration settings.

    :param file_path: Path to the YAML configuration file.
    :return: Dictionary containing the configuration settings.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            config = yaml.safe_load(file)

        # Ensure the 'results' directory exists
        results_dir = os.path.join(os.getcwd(), "results")
        os.makedirs(results_dir, exist_ok=True)

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


def execute_commands(host, config):
    device = {
        "device_type": host["device_type"],
        "host": host["hostname"],
        "username": host["username"],
        "password": host.get(
            "password", config.get("credentials", {}).get("default_password")
        ),
        "secret": host.get("secret", ""),
        "fast_cli": False,
    }

    try:
        logger.info(f"Connecting to {device['host']} ({device['device_type']})")
        connection = ConnectHandler(**device)
        if device["secret"]:
            connection.enable()
            logger.info(f"Entered enable mode on {device['host']}")

        all_commands = []
        for group in host.get("groups", []):
            group_commands = config.get("groups", {}).get(group, {}).get("commands", [])
            all_commands.extend(group_commands)

        all_commands = list(set(all_commands))

        if all_commands:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = os.path.join("results", f"{host['hostname']}_{timestamp}.txt")
            csv_file = os.path.join("results", f"command_results_{timestamp}.csv")

            with open(output_file, "w") as f, open(
                csv_file, mode="a", newline="", encoding="utf-8"
            ) as csvfile:
                writer = csv.DictWriter(
                    csvfile,
                    fieldnames=[
                        "Hostname",
                        "Device Type",
                        "Command",
                        "Output",
                        "Timestamp",
                    ],
                )
                writer.writeheader()

                for cmd in all_commands:
                    try:
                        logger.info(f"Executing '{cmd}' on {device['host']}")
                        output = connection.send_command(cmd)
                        f.write(f"Command: {cmd}\nOutput:\n{output}\n{'-'*80}\n")

                        command_panel = Panel.fit(
                            f"Command: [yellow]{cmd}[/yellow]\n\n{output}",
                            title=f"[green]{device['host']}[/green]",
                            border_style="green",
                        )
                        console.print(command_panel)

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

                        error_panel = Panel.fit(
                            f"Command: [yellow]{cmd}[/yellow]\n\n{error_output}",
                            title=f"[red]{device['host']}[/red]",
                            border_style="red",
                        )
                        console.print(error_panel)

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
        error_panel = Panel.fit(
            f"{error_message}", title=f"[red]{device['host']}[/red]", border_style="red"
        )
        console.print(error_panel)


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


def main():
    config = load_config("config.yaml")
    hosts_config = config.get("hosts", [])

    display_hosts(hosts_config)
    selected_hosts = get_user_selection(hosts_config)

    table = Table(title="Selected Devices", show_header=True, header_style="bold cyan")
    table.add_column("No.", style="dim", width=6)
    table.add_column("Hostname", style="bold")
    table.add_column("Device Type", style="green")
    table.add_column("Groups", style="magenta")

    for idx, host in enumerate(selected_hosts, start=1):
        groups = ", ".join(host.get("groups", []))
        table.add_row(str(idx), host["hostname"], host["device_type"], groups)

    console.print(table)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        task = progress.add_task(
            "[green]Executing Commands...", total=len(selected_hosts)
        )

        with ThreadPoolExecutor(max_workers=6) as executor:  # Set max workers to 6
            futures = {
                executor.submit(execute_commands, host, config): host
                for host in selected_hosts
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
