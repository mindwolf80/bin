# bin

A collection of network engineering tools, automation utilities, and supporting assets maintained by [@mindwolf80](https://github.com/mindwolf80).

## Repository Layout

```
.
├── network-automation/
│   ├── netmate/                     # PyQt6 GUI for multi-device command execution (Netmiko)
│   └── netops-docker/               # Alpine-based NetOps container (Netmiko, Scrapli, TextFSM)
├── network-diagnostics/
│   ├── cable-modem-monitor/         # Arris SB8200 DOCSIS signal-health grader
│   └── ip-connectivity-tester/      # Windows GUI for TCP/UDP reachability tests
├── data-visualization/
│   └── waveform-grapher/            # Streamlit dashboard for network speed-test CSVs
├── utilities/
│   ├── password-generator/          # Single-file, client-side password generator
│   └── youtube-transcript-extractor/# Desktop app to fetch and save YouTube transcripts
└── firmware/
    └── openwrt-mt7986-wo/           # MT7986 Wi-Fi offload firmware package (OpenWrt apk)
```

## Projects

| Project | Language / Stack | Description |
|---|---|---|
| [NetMate](network-automation/netmate) | Python, PyQt6, Netmiko | Parallel command execution across Cisco, Arista, Juniper, Palo Alto, F5, Fortinet, and Linux devices with session and credential management. |
| [NetOps Docker](network-automation/netops-docker) | Docker, Python 3.12 | Portable network automation workspace with proxy-aware launcher script. |
| [Cable Modem Monitor](network-diagnostics/cable-modem-monitor) | Python, Requests, BeautifulSoup | Scrapes Arris SB8200 status pages, grades every downstream/upstream channel, and logs history to CSV. |
| [IP Connectivity Tester](network-diagnostics/ip-connectivity-tester) | PowerShell (compiled) | Tests TCP/UDP ports against single IPs, lists, CIDR blocks, or ranges, with continuous-retry mode. |
| [Waveform Grapher](data-visualization/waveform-grapher) | Python, Streamlit, Plotly | Uploads speed-test CSV results and renders gauges and time-series charts. |
| [Password Generator](utilities/password-generator) | HTML, CSS, JavaScript | Offline, browser-based password generator. |
| [YouTube Transcript Extractor](utilities/youtube-transcript-extractor) | Python, ttkbootstrap | Fetches timestamped, paragraph-formatted transcripts and saves them as text. |
| [MT7986 WO Firmware](firmware/openwrt-mt7986-wo) | OpenWrt package | Wireless offload firmware for MediaTek Filogic MT7986 devices. |

## Getting Started

Each project is self-contained. Navigate to its directory and follow the local `README.md`.

```bash
git clone https://github.com/mindwolf80/bin.git
cd bin/<category>/<project>
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Prebuilt Binaries

Compiled executables (e.g. `NetMate-1.2.1.exe`, `YouTubeTranscriptExtractor`) are distributed through [GitHub Releases](https://github.com/mindwolf80/bin/releases) rather than committed to source.
