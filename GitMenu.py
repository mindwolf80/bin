"""
A TUI (Text User Interface) Git management tool built with urwid.
Provides an interactive menu for common Git operations.
"""

import os
import subprocess
from typing import Callable, List, Optional, Union

import urwid


def is_git_repo() -> bool:
    """Check if current directory is a git repository."""
    try:
        subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            check=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def run_git_command(command: Union[str, List[str]]) -> str:
    """Execute a git command and return its output."""
    try:
        # Convert string command to list if needed
        cmd_list = command.split() if isinstance(command, str) else command

        # Check if it's not a git repo and not git init
        if not is_git_repo() and not (cmd_list[0] == "git" and cmd_list[1] == "init"):
            return "Error: Not a git repository. Please initialize git first using the Setup menu."

        result = subprocess.run(
            cmd_list,
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0 and result.stderr:
            return f"Error: {result.stderr.strip()}"

        return result.stdout.strip() or "Command completed successfully."
    except Exception as e:
        return f"Error: {str(e)}"


class GitMenu:
    """Interactive Git menu interface using urwid."""

    def __init__(self):
        self.palette = [
            ("reversed", "standout", ""),
            ("header", "white", "dark blue"),
            ("menu", "black", "light gray"),
            ("error", "light red", "black"),
            ("success", "light green", "black"),
        ]
        self.loop = urwid.MainLoop(None, self.palette)
        self.main_menu()

    def menu_button(self, caption: str, callback: Callable) -> urwid.AttrMap:
        """Create a menu button with the given caption and callback."""
        button = urwid.Button(caption)
        urwid.connect_signal(button, "click", callback)
        return urwid.AttrMap(button, "menu", focus_map="reversed")

    def sub_menu(self, caption: str, choices: List[urwid.Widget]) -> List[urwid.Widget]:
        """Create a submenu with the given caption and choices."""
        return [
            urwid.AttrMap(urwid.Text(caption), "header"),
            urwid.Divider(),
            *choices,
            urwid.Divider(),
            self.menu_button("Back to Main Menu", self.main_menu),
        ]

    def exit_program(self, _button: Optional[urwid.Button] = None) -> None:
        """Exit the program."""
        raise urwid.ExitMainLoop()

    def get_input(self, prompt: str, callback: Callable) -> None:
        """Show an input dialog with the given prompt and callback."""
        edit = urwid.Edit(prompt)
        done = self.menu_button("OK", lambda _: callback(edit.edit_text))
        cancel = self.menu_button("Cancel", lambda _: self.main_menu())

        pile = urwid.Pile([edit, urwid.Divider(), done, cancel])
        self.loop.widget = urwid.Filler(pile)

    def show_output(
        self, output: str, show_menu_callback: Optional[Callable] = None
    ) -> None:
        """Show command output or error message."""
        style = "error" if output.startswith("Error") else "success"
        text = urwid.AttrMap(urwid.Text(output), style)
        back = self.menu_button(
            "Back",
            lambda _: show_menu_callback() if show_menu_callback else self.main_menu(),
        )
        self.loop.widget = urwid.Filler(urwid.Pile([text, urwid.Divider(), back]))

    def setup_menu(self, _button: Optional[urwid.Button] = None) -> None:
        """Show the Git setup menu."""
        choices = [
            self.menu_button(
                "Initialize Git Repository",
                lambda _: self.show_output(
                    run_git_command(["git", "init"]), self.setup_menu
                ),
            ),
            self.menu_button(
                "Configure User Name",
                lambda _: self.get_input(
                    "Enter your Git user name: ",
                    lambda name: self.show_output(
                        run_git_command(["git", "config", "user.name", name]),
                        self.setup_menu,
                    ),
                ),
            ),
            self.menu_button(
                "Configure User Email",
                lambda _: self.get_input(
                    "Enter your Git email: ",
                    lambda email: self.show_output(
                        run_git_command(["git", "config", "user.email", email]),
                        self.setup_menu,
                    ),
                ),
            ),
        ]
        self.loop.widget = urwid.Filler(
            urwid.Pile(self.sub_menu("=== Setup Commands ===", choices))
        )

    def workflow_menu(self, _button: Optional[urwid.Button] = None) -> None:
        """Show the Git workflow menu."""
        choices = [
            self.menu_button(
                "Add All Files",
                lambda _: self.show_output(
                    run_git_command(["git", "add", "."]), self.workflow_menu
                ),
            ),
            self.menu_button(
                "Commit Changes",
                lambda _: self.get_input(
                    "Enter commit message: ",
                    lambda msg: self.show_output(
                        run_git_command(["git", "commit", "-m", msg]),
                        self.workflow_menu,
                    ),
                ),
            ),
            self.menu_button(
                "Push Changes",
                lambda _: self.show_output(
                    run_git_command(["git", "push"]), self.workflow_menu
                ),
            ),
        ]
        self.loop.widget = urwid.Filler(
            urwid.Pile(self.sub_menu("=== Basic Workflow Commands ===", choices))
        )

    def sync_menu(self, _button: Optional[urwid.Button] = None) -> None:
        """Show the Git sync menu."""
        choices = [
            self.menu_button(
                "Pull Changes",
                lambda _: self.show_output(
                    run_git_command(["git", "pull"]), self.sync_menu
                ),
            ),
            self.menu_button(
                "Fetch Updates",
                lambda _: self.show_output(
                    run_git_command(["git", "fetch"]), self.sync_menu
                ),
            ),
        ]
        self.loop.widget = urwid.Filler(
            urwid.Pile(self.sub_menu("=== Sync Commands ===", choices))
        )

    def remotes_menu(self, _button: Optional[urwid.Button] = None) -> None:
        """Show the Git remotes menu."""
        choices = [
            self.menu_button(
                "List Remotes",
                lambda _: self.show_output(
                    run_git_command(["git", "remote", "-v"]), self.remotes_menu
                ),
            ),
            self.menu_button(
                "Add Remote",
                lambda _: self.get_input(
                    "Enter remote URL: ",
                    lambda url: self.show_output(
                        run_git_command(["git", "remote", "add", "origin", url]),
                        self.remotes_menu,
                    ),
                ),
            ),
        ]
        self.loop.widget = urwid.Filler(
            urwid.Pile(self.sub_menu("=== Remote Management ===", choices))
        )

    def status_menu(self, _button: Optional[urwid.Button] = None) -> None:
        """Show Git status."""
        output = run_git_command(["git", "status"])
        self.show_output(output, self.main_menu)

    def help_menu(self, _button: Optional[urwid.Button] = None) -> None:
        """Show the help menu."""
        help_text = """=== Git Menu Help ===

Navigation:
- Use UP/DOWN arrow keys to navigate
- Press ENTER to select an option
- Press Q to quit
- Press ESC to go back

Available Commands:
1. Setup
   - Initialize new repository
   - Configure user name and email
2. Basic Workflow
   - Add files to staging
   - Commit changes
   - Push to remote
3. Sync
   - Pull changes
   - Fetch updates
4. Remotes
   - List remote repositories
   - Add new remote
5. Status
   - View repository status"""

        self.show_output(help_text, self.main_menu)

    def main_menu(self, _button: Optional[urwid.Button] = None) -> None:
        """Show the main menu."""
        header_text = f"""============================================
                Git Menu
============================================
Directory: {os.getcwd()}
Status: {"Git repository" if is_git_repo() else "Not a Git repository"}
============================================"""

        header = urwid.AttrMap(urwid.Text(header_text), "header")
        menu_items = [
            self.menu_button("Setup", self.setup_menu),
            self.menu_button("Basic Workflow", self.workflow_menu),
            self.menu_button("Sync", self.sync_menu),
            self.menu_button("Remotes", self.remotes_menu),
            self.menu_button("Status", self.status_menu),
            self.menu_button("Help", self.help_menu),
            urwid.Divider(),
            self.menu_button("Exit", self.exit_program),
        ]

        self.loop.widget = urwid.Filler(
            urwid.Pile([header, urwid.Divider()] + menu_items)
        )

    def run(self) -> None:
        """Start the Git menu interface."""
        self.loop.run()


if __name__ == "__main__":
    GitMenu().run()
