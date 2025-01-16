# NetMate

A Python-based network automation tool with a GUI interface for executing commands across multiple network devices simultaneously.

## Features

- Execute commands on multiple network devices in parallel
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

- Python 3.6+
- PyQt5
- Netmiko
- Keyring

## Installation

1. Clone the repository
2. Install dependencies:
```bash
pip install PyQt5 netmiko keyring
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

## Modes

- **Normal Mode**: Each command is executed separately
- **Config Mode**: Commands are executed as a configuration set

## Features Guide

### Credential Management
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

### Logging
- View detailed execution logs
- Clear logs when needed

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
- Save credentials for frequently used accounts
- Save sessions for common device groups and command sets
- Monitor execution progress in real-time
- Export results for documentation and analysis
