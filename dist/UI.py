import curses
from main import load_config, display_hosts, main  # Import necessary functions


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
        for idx, row in enumerate(menu):
            x = w // 2 - len(row) // 2
            y = h // 2 - len(menu) // 2 + idx
            if idx == selected_row_idx:
                stdscr.attron(curses.color_pair(1))
                stdscr.addstr(y, x, row)
                stdscr.attroff(curses.color_pair(1))
            else:
                stdscr.addstr(y, x, row)
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

    # Function to preview hosts
    def preview_hosts(stdscr):
        stdscr.clear()
        stdscr.addstr(0, 0, "Previewing hosts from config.yaml:\n")
        y = 2
        for idx, host in enumerate(hosts_config, start=1):
            stdscr.addstr(y, 0, f"{idx}. Hostname: {host.get('hostname', 'N/A')}")
            stdscr.addstr(y + 1, 0, f"   Device Type: {host.get('device_type', 'N/A')}")
            stdscr.addstr(y + 2, 0, f"   Groups: {', '.join(host.get('groups', []))}")
            y += 4
        stdscr.addstr(y, 0, "Press any key to return to the menu.")
        stdscr.refresh()
        stdscr.getch()

    # Initialize colors
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_WHITE)

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

            if not skip_prompts:
                if not confirm_action(stdscr, action):
                    continue

            if current_row == 0:
                # Preview hosts
                preview_hosts(stdscr)
            elif current_row == 1:
                # Run main app
                stdscr.clear()
                stdscr.addstr(0, 0, "Running main app...")
                stdscr.refresh()
                main()  # Directly call the main function from main.py
                stdscr.addstr(
                    2,
                    0,
                    "Main app execution completed. Press any key to return to the menu.",
                )
                stdscr.getch()

        print_menu(stdscr, current_row)


curses.wrapper(main_menu)
