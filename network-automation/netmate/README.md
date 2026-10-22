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
- Command output logging
- Results export to CSV
- Pause/Resume functionality
- Dark mode support via QSS styling

## Requirements

- Python 3.9+ (PyQt6 requirement)
- See requirements.txt for detailed dependencies

## Installation

1. Clone the repository and change to `network-automation/netmate`
2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

1. Launch the application:
```bash
python main.py
```

2. Enter credentials and select device type
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

### Credential Management
- Passwords are never written to session files
- Save credentials securely using system keyring
- Load previously saved credentials from dropdown

### Session Management
- Save current session (devices, commands, mode)
- Load previous sessions

### Results
- View command execution results in real-time
- Export results to CSV
- View saved results in tabulated format

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
- View detailed execution logs
- Clear logs when needed
- Real-time progress updates

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
- `main.py`: PyQt6 GUI.

## Tests

```bash
pip install pytest
python -m pytest tests
```

Tests use a fake Netmiko connection; no network devices are required.

## Building

```bash
pip install pyinstaller
pyinstaller NetMate-1.2.1.spec
```

Output: `dist/NetMate-1.2.1.exe`.
