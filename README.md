
---

# Net Interactive Command Executor

 Overview

The Net Interactive Command Executor is a Python application designed to facilitate the execution of network commands on devices using the Netmiko library. This script allows users to input device information and commands either manually or via a file, and it provides a graphical user interface (GUI) for ease of use.

 Features

- GUI Interface: Built using PyQt5, the application offers a modern interface for interacting with network devices.
- Device Command Execution: Connects to network devices using Netmiko, executes commands, and logs outputs.
- File Support: Reads device information and commands from TXT, CSV, or XLSX files.
- Logging: Provides detailed logging of successful and failed command executions.
- Progress Tracking: Displays progress updates and handles user cancellation.

 Requirements

- Python 3.x
- PyQt5
- Netmiko
- pandas
- cryptography

 Installation

1. Clone the Repository:
   
   git clone https://github.com/mindwolf80/Lab.git
   cd Lab
   

2. Install Dependencies:
   
   pip install -r requirements.txt
   

   *Create a `requirements.txt` file with the following content if it does not exist:*
   
   pyqt5
   netmiko
   pandas
   cryptography
   

 Usage

1. Run the Application:
   
   python nice.py (via cmd/shell)
    
	 OR
	 
   nice.exe

2. Using the GUI:
   - Enter Device Credentials: Provide the username, password, and enable secret if needed.
   - Select Device File: Choose a file containing device information and commands.
   - Input Commands: You can enter commands manually or load them from the selected file.
   - Execute Commands: Click the "Run" button to start executing commands on the devices.
   - Monitor Progress: View the progress and logs in the GUI.

3. Files and Logging:
   - Successful Logs: Stored in the `logs/successful/` directory.
   - Failed Logs: Stored in the `logs/failure/failed_devices.txt`.

 Script Functions

- `read_device_info(file_path, file_type)`: Reads device information and commands from a file.
- `create_directories()`: Creates necessary directories for logging.
- `execute_commands_on_devices(...)`: Executes commands on devices and handles connections.
- `run_script(...)`: Executes the main logic for running commands based on user input.
- `clear_log(log_text_edit, progress_bar)`: Clears the log and resets the progress bar.
- `cancel_execution_function()`: Sets a flag to cancel the execution of commands.

 Troubleshooting

# Common Issues

1. Failed to Connect to Device:
   - Possible Causes:
     - Incorrect IP address or hostname.
     - Device is not reachable or down.
     - Network issues or firewall blocking access.
   - Solutions:
     - Verify the IP address and hostname in your device file.
     - Check device status and network connectivity.
     - Ensure that there are no firewalls blocking the connection.

2. Authentication Errors:
   - Possible Causes:
     - Incorrect username or password.
     - Wrong enable secret.
   - Solutions:
     - Double-check the username and password.
     - Ensure the correct enable secret is provided if required.

3. Command Execution Errors:
   - Possible Causes:
     - Incorrect command syntax.
     - Commands not supported on the device.
   - Solutions:
     - Review the command syntax and ensure compatibility with the device.

4. GUI Not Displaying Properly:
   - Possible Causes:
     - Missing or incompatible PyQt5 installation.
   - Solutions:
     - Ensure PyQt5 is installed correctly with `pip install pyqt5`.
     - Verify that you are using a compatible version of Python and PyQt5.

5. File Reading Issues:
   - Possible Causes:
     - Incorrect file path or format.
     - Corrupted or improperly formatted file.
   - Solutions:
     - Check the file path and ensure it is correct.
     - Verify the file format and content. For CSV and XLSX, ensure proper formatting.

# Additional Help

- Consult the Documentation: Refer to the [Netmiko Documentation](https://netmiko.readthedocs.io/) for details on supported devices and commands.
- Check Logs: Review the log files in `logs/successful/` and `logs/failure/` for detailed error messages.
- Contact Support: If you encounter persistent issues, consider reaching out for help on forums or communities related to Netmiko and PyQt5.

 License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

---
