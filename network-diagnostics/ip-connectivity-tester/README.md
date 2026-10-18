# IP Connectivity Tester (TNCGE)

Windows Forms GUI, compiled from PowerShell, for testing TCP/UDP port reachability.

## Features

- Targets: single IP, comma/space-separated list, CIDR (`192.168.1.0/24`), or range (`192.168.1.1-192.168.1.10`)
- Ports: single, list (`22, 80, 443`), or range (`20-25`)
- Protocols: TCP, UDP (UDP requires a remote listener)
- **Keep Trying** mode with 1/2/5/10-second intervals
- Copy, clear, and reset controls

## Usage

Run `TNCGE.exe` on Windows (PowerShell 5.1+ / .NET Framework 4.x).

## Notes

The `.ps1` source is not currently tracked in this repository; adding it alongside the executable is recommended.
