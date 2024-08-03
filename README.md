
---

# Net Interactive Command Executor

This script automates the process of connecting to network devices, executing commands, and saving the output to various file formats. It supports multiple device types and allows the user to choose between direct session input and file-based input.

## Features

- Supports various network device types (Cisco ASA, Cisco IOS, Linux, etc.).
- Connects to devices via SSH using Netmiko.
- Executes a list of commands on each device.
- Saves output in CSV, XLSX, and TXT formats.
- Provides progress updates using tqdm progress bars.
- Allows for pause options between device connections.

## Requirements

- Python 3.x
- Required Python Packages:
  - pandas
  - netmiko
  - cryptography
  - tqdm
  - openpyxl

## Installation

1. Install Python: Download and install Python from the [official Python website](https://www.python.org/).
2. Create a Virtual Environment (Optional but recommended):
   
   python -m venv myenv
   source myenv/bin/activate   # On Windows use myenv\Scripts\activate
   
3. Install Required Packages:
   
   pip install pandas netmiko cryptography tqdm openpyxl
   
4. Suggested Packages:

   pip install pip-review pyinstaller ruff
   
5. PY ► EXE:

   pyinstaller --clean --onefile --noconsole --name=nice-1.4.0.exe nice_1_4_0_nogui.py

   

## Usage

1. Save the script to a file named nice_1_4_nogui.py.
2. Run the script:
   
   py nice_1_4_nogui.py
   

3. Follow the on-screen prompts to:
   - Select device type.
   - Enter authentication details.
   - Choose between direct session or file list.
   - If using file list, provide the file path.
   - Select pause option.
   - Choose output format(s).

## File Format

- CSV or XLSX File Requirements:
  - The file must contain the following headers: ip,dns,command. (no space in-between comma delimiters)

## Example

To run the script and connect to a Linux device, follow these steps:

1. Select linux as the device type.
2. Enter your SSH username and password.
3. Choose direct session or file list.
4. Enter the commands to execute or provide the file path.
5. Choose the pause option between connections.
6. Select the desired output format(s).
7. Confirm and run the script.

The script will display progress updates and save the output to the specified format(s).

## License

This project is licensed under the MIT License.

## Acknowledgements

This script utilizes the following open-source libraries:
- [Netmiko](https://github.com/ktbyers/netmiko)
- [pandas](https://github.com/pandas-dev/pandas)
- [tqdm](https://github.com/tqdm/tqdm)
- [openpyxl](https://openpyxl.readthedocs.io/)

---

