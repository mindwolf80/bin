# NetMate

A Python-based network automation tool with a GUI interface for executing commands across multiple network devices simultaneously.

## Features

- Execute commands on multiple network devices in parallel (configurable concurrency)
- Per-platform detection of rejected commands
- Support for various network device types (Cisco, Arista, Juniper, etc.)
- Configuration and normal operation modes
- Secure credential management
- Session saving and loading
- Progress tracking and execution control
- Live results table: colour-coded status per command, search, status filters and a full-output detail pane
- Structured, size-rotated application log with a tabular log viewer
- Results export to CSV
- Pause/Resume functionality
- Dark mode support via QSS styling

## Requirements

- Python 3.10+
- Linux on X11 only: the `libxcb-cursor0` system package (Qt 6.5+ requirement). NetMate checks
  for it at startup and prints the install command if it is missing.
- See requirements.txt for detailed dependencies

## Installation

1. Clone the repository and change to `network-automation/netmate`
2. Install dependencies (exact tested versions; use `requirements.txt` for the minimum ranges):
```bash
pip install -r requirements.lock
```

## Usage

1. Launch the application:
```bash
python main.py
```

2. Enter a username, choose *Password* or *SSH key / agent* login, and select the device type
3. Add device IPs/hostnames (one per line)
4. Enter commands to execute (one per line)
5. Click "Run Commands" to start execution

## Performance Optimization

### Concurrency
- Configure the number of devices processed concurrently (1-50)
- A new device starts as soon as any running device finishes
- Commands on a single device always run in order over one SSH session
- Access via Preferences > Network Settings

### Recommended Settings
- For stable networks: 10-20 concurrent devices
- For less stable networks: 5-10 concurrent devices
- Adjust based on:
  * Network stability
  * Device response times
  * System resources
  * Number of devices

## Modes

- **Normal Mode**: Each command is executed separately
- **Config Mode**: Commands are executed as a configuration set. On commit-based platforms (Juniper JunOS, Palo Alto PAN-OS, IOS-XR) the set is committed when no errors are detected; on JunOS a rejected set is rolled back with `rollback 0`. Configuration is not saved to startup-config on other platforms.

## Features Guide

### SSH Key Login (no password)
- Set *Login With* to **SSH key / agent**; the password field is not needed
- *Key File* blank: uses `~/.ssh/id_ed25519`, `id_ecdsa` or `id_rsa` (first found), and ssh-agent
- Or pick any private key with the **…** button; enter *Key Passphrase* only if the key is encrypted
- The key and passphrase are checked before any device is contacted, so a wrong passphrase fails
  once with a clear message instead of on every device
- Sessions remember the login method and key path; passphrases are never saved

### Credential Management
- Passwords are never written to session files
- Save credentials securely using system keyring
- Load previously saved credentials from dropdown

### Session Management
- Save current session (devices, commands, mode)
- Load previous sessions

### Results
- Every command result and progress event is a row in the Output table: Time, Status, Host, User, Command, Output
- Status is colour-coded (OK, FAILED, ERROR, STOPPED, CONNECTED, INFO); failed rows are tinted
- Filter by *Command results*, *Problems only* or *Progress messages*, or search across all columns
- Select a row to see the complete device output in the monospace detail pane
- Export results to CSV (includes a `status` column); *View Results* opens a CSV in the same table

### Execution Control
- Pause/Resume command execution
- Stop execution at any time
- Clear output and start fresh
- Batch-wise progress tracking

### Network Settings
- Concurrency
- Connection timeouts
- SSH settings
- Operation timeouts

### Logging
- Written to `netmate.log`, rotated at 5 MB with 5 backups
- Format: `time | level | source | thread | message`; tracebacks are kept with their record
- *Log > View Log* shows the log as a table with level filter, search and detail pane

## Device Support

- Arista EOS
- Cisco IOS/IOS-XE/NX-OS/ASA/APIC
- F5 Linux/LTM/TMSH
- Fortinet
- Juniper JunOS
- Linux
- Palo Alto PANOS

## Tips

- Use Configuration Mode for related commands that need to be executed as a set
- Adjust concurrency based on network and system capabilities
- Start with conservative concurrency and increase gradually
- Save credentials for frequently used accounts
- Save sessions for common device groups and command sets
- Monitor execution progress in real-time
- Export results for documentation and analysis

## Performance Considerations

- Higher concurrency finishes large runs faster but opens more simultaneous SSH sessions
- Authentication failures are not retried (avoids account lockouts); connection timeouts are retried with backoff
- Network stability and device response times should guide your settings
- Monitor system performance and adjust settings accordingly

## Architecture

- `engine.py`: GUI-independent execution engine. Emits structured `Event` objects through a callback; usable from Qt, a web backend or a CLI.
- `handlers.py`: Qt bridge that runs the engine on a `QThread` and re-emits events as signals.
- `table_widgets.py`: Output, results and log tables (Qt model/view with filtering).
- `app_logging.py`: Rotating log setup and log parser.
- `auth.py`: Password / SSH key / ssh-agent login options and key validation.
- `session.py`: Validated session files.
- `main.py`: PyQt6 GUI.

## Development

```bash
pip install -r requirements-dev.txt
ruff check . && ruff format --check .   # lint + format
pyright                                 # type check (same engine as Pylance)
python -m pytest                        # tests
```

Ruff, Pyright/Pylance and pytest are configured in `pyproject.toml`, so the editor and CI use the same rules.
Tests use a fake Netmiko connection; no network devices are required. GUI tests use `pytest-qt`
(set `QT_QPA_PLATFORM=offscreen` on headless machines).

## Building

```bash
pip install pyinstaller
pyinstaller NetMate-1.4.0.spec
```

Output: `dist/NetMate-1.4.0.exe` (Windows) or `dist/NetMate-1.4.0` (Linux/macOS).
