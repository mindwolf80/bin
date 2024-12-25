import curses
import subprocess
import platform
import socket
from main import load_config  # Import necessary functions


def main_menu(stdscr):
    # Load configuration
    def load_configuration():
        try:
            return load_config("config.yaml")
        except Exception as e:
            stdscr.addstr(0, 0, f"Error loading configuration: {e}")
            stdscr.refresh()
            stdscr.getch()
            return None

    config = load_configuration()
    if config is None:
        return
    hosts_config = config.get("hosts", [])
    groups_config = config.get("groups", {})

    # Set up the menu
    menu = [
        "Preview Hosts",
        "Run Main App",
        "Test Connectivity",
        "Execute Commands for Specific Hosts",
        "Execute Group-Specific Commands",
        "View Groups and Associated Commands",
        "View Logs",
        "Reload Configuration",
        "Exit",
    ]
    current_row = 0

    # Function to print the menu
    def print_menu(stdscr, selected_row_idx):
        stdscr.clear()
        h, w = stdscr.getmaxyx()
        title = "Network Automation Tool"
        stdscr.attron(curses.color_pair(2))
        stdscr.addstr(1, w // 2 - len(title) // 2, title)
        stdscr.attroff(curses.color_pair(2))
        for idx, row in enumerate(menu):
            x = w // 2 - len(row) // 2
            y = h // 2 - len(menu) // 2 + idx
            if idx == selected_row_idx:
                stdscr.attron(curses.color_pair(1))
                stdscr.addstr(y, x, row)
                stdscr.attroff(curses.color_pair(1))
            else:
                stdscr.addstr(y, x, row)
        stdscr.addstr(h - 2, 0, "Use arrow keys to navigate and ENTER to select.")
        stdscr.refresh()

    # Function to preview hosts
    def preview_hosts(stdscr):
        stdscr.clear()
        stdscr.addstr(0, 0, "Previewing hosts from config.yaml:\n")
        if not hosts_config:
            stdscr.addstr(2, 0, "No hosts configured.")
        else:
            row = 2  # Start after the header
            for idx, host in enumerate(hosts_config, start=1):
                hostname = host.get("hostname", "N/A")
                device_type = host.get("device_type", "N/A")
                groups = (
                    ", ".join(host.get("groups", [])) if host.get("groups") else "None"
                )
                stdscr.addstr(row, 0, f"{idx}. Hostname: {hostname}")
                stdscr.addstr(row + 1, 0, f"   Device Type: {device_type}")
                stdscr.addstr(row + 2, 0, f"   Groups: {groups}")
                row += 4  # Add spacing between entries
        stdscr.addstr(row, 0, "Press any key to return to the menu.")
        stdscr.refresh()
        stdscr.getch()

    # Function to run main app
    def run_main_app(stdscr):
        stdscr.clear()
        stdscr.addstr(0, 0, "Running main app...\n")
        stdscr.refresh()
        try:
            process = subprocess.Popen(
                ["python", "dist/main.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            output_lines = []
            while True:
                output = process.stdout.readline()
                error = process.stderr.readline()
                if output == "" and error == "" and process.poll() is not None:
                    break
                if output:
                    output_lines.append(output.strip())
                if error:
                    output_lines.append(f"ERROR: {error.strip()}")

                stdscr.clear()
                for idx, line in enumerate(output_lines[-(stdscr.getmaxyx()[0] - 2) :]):
                    stdscr.addstr(idx, 0, line)
                stdscr.refresh()

            stdscr.addstr(
                stdscr.getmaxyx()[0] - 1,
                0,
                "Main app execution completed. Press any key to return to the menu.",
            )
        except Exception as e:
            stdscr.addstr(2, 0, f"Error running main app: {e}")
        finally:
            stdscr.refresh()
            stdscr.getch()

    # Function to test connectivity
    def test_connectivity(stdscr):
        stdscr.clear()
        stdscr.addstr(0, 0, "Testing connectivity to hosts:\n")
        row = 2
        ping_flag = "-n" if platform.system().lower() == "windows" else "-c"

        for host in hosts_config:
            hostname = host.get("hostname", "N/A")
            if hostname == "N/A":
                stdscr.addstr(row, 0, f"Host entry missing hostname.")
                row += 1
                continue

            # Initial ping test
            try:
                result = subprocess.run(
                    ["ping", ping_flag, "1", hostname],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                if result.returncode == 0:
                    stdscr.addstr(row, 0, f"{hostname}: Reachable via ping")
                else:
                    stdscr.addstr(
                        row, 0, f"{hostname}: Unreachable via ping, testing ports..."
                    )
                    row += 1
                    # Fall back to port testing
                    row = test_ports(stdscr, hostname, row)
            except Exception as e:
                stdscr.addstr(row, 0, f"{hostname}: Error - {e}")
            row += 2  # Add spacing between hosts

        stdscr.addstr(row, 0, "Press any key to return to the menu.")
        stdscr.refresh()
        stdscr.getch()

    # Function to test specific ports if ping fails
    def test_ports(stdscr, hostname, row):
        ports = [22, 80, 443]
        for port in ports:
            try:
                sock = socket.create_connection((hostname, port), timeout=2)
                stdscr.addstr(row, 0, f"   Port {port}: Open")
                sock.close()
            except socket.timeout:
                stdscr.addstr(row, 0, f"   Port {port}: Timed out")
            except socket.error as e:
                stdscr.addstr(row, 0, f"   Port {port}: Closed - {e}")
            row += 1
        return row

    # Initialize colors
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(2, curses.COLOR_CYAN, curses.COLOR_BLACK)

    # Main loop
    print_menu(stdscr, current_row)
    while True:
        key = stdscr.getch()
        if key == curses.KEY_UP and current_row > 0:
            current_row -= 1
        elif key == curses.KEY_DOWN and current_row < len(menu) - 1:
            current_row += 1
        elif key == curses.KEY_ENTER or key in [10, 13]:
            if current_row == len(menu) - 1:
                break  # Exit the program

            if current_row == 0:
                preview_hosts(stdscr)
            elif current_row == 1:
                run_main_app(stdscr)
            elif current_row == 2:
                test_connectivity(stdscr)

        print_menu(stdscr, current_row)


curses.wrapper(main_menu)
