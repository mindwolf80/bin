# NetMate

A Python-based network automation tool with a GUI interface for executing commands across multiple network devices simultaneously, featuring thread pooling for optimized performance.

## Features

- Execute commands on multiple network devices in parallel using thread pooling
- Configurable batch processing for efficient resource management
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
- See requirements.txt for detailed dependencies

## Installation

1. Clone the repository
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

### Thread Pool Settings
- Configure maximum concurrent threads (1-50)
- Set batch size for device processing (1-100)
- Access via Preferences > Network Settings

### Recommended Settings
- For stable networks: 10-20 threads, batch size 5-10
- For less stable networks: 5-10 threads, batch size 3-5
- Adjust based on:
  * Network stability
  * Device response times
  * System resources
  * Number of devices

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
- Batch-wise progress tracking

### Network Settings
- Thread pool configuration
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
- Adjust thread pool settings based on network and system capabilities
- Start with conservative thread/batch settings and increase gradually
- Monitor system resource usage when adjusting thread pool settings
- Save credentials for frequently used accounts
- Save sessions for common device groups and command sets
- Monitor execution progress in real-time
- Export results for documentation and analysis

## Performance Considerations

- Higher thread counts provide better parallelization but consume more system resources
- Larger batch sizes reduce overhead but increase memory usage
- Network stability and device response times should guide your settings
- Monitor system performance and adjust settings accordingly
