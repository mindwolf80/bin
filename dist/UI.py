import os
import yaml
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Button, Log
from textual.containers import Vertical
from rich.panel import Panel

CONFIG_FILE = "config.yaml"


class NetworkUI(App):
    """Terminal-inspired TUI for Network Automation."""

    CSS_PATH = "styles.css"  # Path to CSS for styling

    def compose(self) -> ComposeResult:
        """Compose the layout of the app."""
        yield Header()
        yield Vertical(
            Button("1. Create or Update Configuration", id="update_config"),
            Button("2. View Configuration", id="view_config"),
            Button("3. Execute Automation", id="execute"),
            Button("4. Exit", id="exit"),
            id="main_menu",
        )
        yield Log(highlight=True, id="output_log")  # Removed `markup` argument
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        button_id = event.button.id
        if button_id == "update_config":
            self.show_update_menu()
        elif button_id == "view_config":
            self.show_config()
        elif button_id == "execute":
            self.execute_main_script()
        elif button_id == "exit":
            self.exit()

    def show_update_menu(self) -> None:
        """Show the configuration update menu."""
        log = self.query_one("#output_log", Log)
        log.write("[cyan]Entering configuration update mode...[/cyan]")

        config = self.load_or_create_config()
        log.write("[yellow]Updating configuration...[/yellow]")

        # Add new host interactively (mocked for this example)
        new_host = {
            "hostname": "new-host.example.com",
            "device_type": "router",
            "username": "admin",
            "password": "admin123",
            "groups": ["group1", "group2"],
        }

        if "hosts" not in config:
            config["hosts"] = []
        config["hosts"].append(new_host)

        with open(CONFIG_FILE, "w", encoding="utf-8") as file:
            yaml.dump(config, file)

        log.write("[green]Configuration updated successfully![/green]")

    def show_config(self) -> None:
        """Display the current configuration."""
        log = self.query_one("#output_log", Log)
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as file:
                config = yaml.safe_load(file)
            panel = Panel(
                yaml.dump(config, default_flow_style=False),
                title="Current Configuration",
                border_style="green",
            )
            log.write(panel)
        except FileNotFoundError:
            log.write("[red]Configuration file not found![/red]")
        except yaml.YAMLError as e:
            log.write(f"[red]Error parsing configuration: {e}[/red]")

    def execute_main_script(self) -> None:
        """Execute the main.py script and show real-time output."""
        log = self.query_one("#output_log", Log)
        if not os.path.exists("main.py"):
            log.write("[red]main.py not found![/red]")
            return
        try:
            log.write("[cyan]Executing main.py...[/cyan]")
            exit_code = os.system("python main.py")
            if exit_code == 0:
                log.write("[green]main.py executed successfully![/green]")
            else:
                log.write(f"[red]main.py exited with code {exit_code}[/red]")
        except Exception as e:
            log.write(f"[red]Error executing main.py: {e}[/red]")

    def load_or_create_config(self) -> dict:
        """Load or create a configuration file."""
        if not os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "w", encoding="utf-8") as file:
                yaml.dump({"hosts": [], "groups": {}, "credentials": {}}, file)
        with open(CONFIG_FILE, "r", encoding="utf-8") as file:
            return yaml.safe_load(file)


if __name__ == "__main__":
    NetworkUI().run()
