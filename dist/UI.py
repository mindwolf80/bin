import curses
import subprocess
from main import load_config, display_hosts  # Import necessary functions


def main_menu(stdscr):
    # Clear screen
    stdscr.clear()

    # Load configuration
    config = load_config("config.yaml")
    hosts_config = config.get("hosts", [])
    skip_prompts = config.get("skip_prompts", False)

    # Set up the menu
    menu = ["Preview Hosts", "Run Main App", "Exit"]
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

    # Function to show a confirmation prompt
    def confirm_action(stdscr, action):
        stdscr.clear()
        stdscr.addstr(0, 0, f"Are you sure you want to {action}? (y/n)")
        stdscr.refresh()
        while True:
            key = stdscr.getch()
            if key in [ord("y"), ord("Y")]:
                return True
            elif key in [ord("n"), ord("N")]:
                return False

    # Function to preview hosts using display_hosts
    def preview_hosts(stdscr):
        stdscr.clear()
        stdscr.addstr(0, 0, "Previewing hosts from config.yaml:\n")
        stdscr.refresh()
        try:
            display_hosts(hosts_config)  # Use the display_hosts function
        except Exception as e:
            stdscr.addstr(2, 0, f"Error displaying hosts: {e}")
        stdscr.addstr("\nPress any key to return to the menu.")
        stdscr.refresh()
        stdscr.getch()

    # Function to run main app and display output
    def run_main_app(stdscr):
        stdscr.clear()
        stdscr.addstr(0, 0, "Running main app...\n")
        stdscr.refresh()

        # Run main.py as a subprocess
        process = subprocess.Popen(
            ["python", "dist/main.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        # Display output in real-time
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

            # Display the last few lines of output
            stdscr.clear()
            for idx, line in enumerate(output_lines[-(stdscr.getmaxyx()[0] - 2) :]):
                stdscr.addstr(idx, 0, line)
            stdscr.refresh()

        stdscr.addstr(
            stdscr.getmaxyx()[0] - 1,
            0,
            "Main app execution completed. Press any key to return to the menu.",
        )
        stdscr.refresh()
        stdscr.getch()

    # Initialize colors
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(2, curses.COLOR_CYAN, curses.COLOR_BLACK)

    # Print the initial menu
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

            action = menu[current_row]

            if current_row == 1 and not skip_prompts:
                if not confirm_action(stdscr, action):
                    continue

            if current_row == 0:
                # Preview hosts
                preview_hosts(stdscr)
            elif current_row == 1:
                # Run main app
                run_main_app(stdscr)

        print_menu(stdscr, current_row)


curses.wrapper(main_menu)
