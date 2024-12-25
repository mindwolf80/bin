from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Button, Static, TextLog
from textual.containers import Container
from textual.reactive import reactive
from rich.console import Console
from rich.table import Table
import subprocess
import platform
import socket
from dist.main import load_config, display_hosts  # Retain this import

console = Console()


class NetworkAutomationApp(App):
    CSS_PATH = "styles.css"  # Optional: Path to a CSS file for styling

    def __init__(self):
        super().__init__()
        self.config = load_config("config.yaml")
        self.hosts_config = self.config.get("hosts", [])
        self.groups_config = self.config.get("groups", {})
        self.output_log = reactive("")

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()
        yield Container(
            Static("Network Automation Tool", classes="title"),
            Button("Preview Hosts", id="preview_hosts"),
            Button("Run Main App", id="run_main_app"),
            Button("Test Connectivity", id="test_connectivity"),
            Button("View Groups and Commands", id="view_groups"),
            Button("Exit", id="exit"),
            TextLog(self.output_log, classes="output"),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "preview_hosts":
            self.preview_hosts()
        elif button_id == "run_main_app":
            self.run_main_app()
        elif button_id == "test_connectivity":
            self.test_connectivity()
        elif button_id == "view_groups":
            self.view_groups_and_commands()
        elif button_id == "exit":
            self.exit()

    def preview_hosts(self):
        self.output_log = "Previewing hosts from config.yaml:\n"
        if not self.hosts_config:
            self.output_log += "No hosts configured."
        else:
            display_hosts(self.hosts_config)  # Use the display_hosts function

    def run_main_app(self):
        self.output_log = "Running main app...\n"
        try:
            process = subprocess.Popen(
                ["python", "dist/main.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            for line in process.stdout:
                self.output_log += line.strip() + "\n"
            for line in process.stderr:
                self.output_log += f"ERROR: {line.strip()}\n"

            self.output_log += "\nMain app execution completed."
        except Exception as e:
            self.output_log += f"Error running main app: {e}"

    def test_connectivity(self):
        self.output_log = "Testing connectivity to hosts:\n"
        ping_flag = "-n" if platform.system().lower() == "windows" else "-c"

        for host in self.hosts_config:
            hostname = host.get("hostname", "N/A")
            if hostname == "N/A":
                self.output_log += "Host entry missing hostname.\n"
                continue

            try:
                result = subprocess.run(
                    ["ping", ping_flag, "1", hostname],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                if result.returncode == 0:
                    self.output_log += f"{hostname}: Reachable via ping\n"
                else:
                    self.output_log += (
                        f"{hostname}: Unreachable via ping, testing ports...\n"
                    )
                    self.test_ports(hostname)
            except Exception as e:
                self.output_log += f"{hostname}: Error - {e}\n"

    def test_ports(self, hostname):
        ports = [22, 80, 443]
        for port in ports:
            try:
                sock = socket.create_connection((hostname, port), timeout=2)
                self.output_log += f"   Port {port}: Open\n"
                sock.close()
            except socket.timeout:
                self.output_log += f"   Port {port}: Timed out\n"
            except socket.error as e:
                self.output_log += f"   Port {port}: Closed - {e}\n"

    def view_groups_and_commands(self):
        self.output_log = "Groups and Associated Commands:\n"
        if not self.groups_config:
            self.output_log += "No groups configured."
        else:
            for group, details in self.groups_config.items():
                commands = details.get("commands", [])
                self.output_log += f"Group: {group}\nCommands: {', '.join(commands)}\n"


if __name__ == "__main__":
    app = NetworkAutomationApp()
    app.run()
