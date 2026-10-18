# Cable Modem Monitor

Signal-health monitor for the **Arris SB8200** DOCSIS 3.1 cable modem. Logs in to the modem's web interface, parses the downstream/upstream channel tables, and grades each channel.

| Grade | Meaning |
|---|---|
| `GOOD` | Comfortably inside spec |
| `OK` | Inside spec |
| `MARGINAL` | Drifting toward the edge of spec |
| `BAD` | Out of spec / needs attention |

Each run appends a summary row to `modem_history.csv` in the script directory.

## Requirements

- Python 3.9+
- `pip install -r requirements.txt`

## Configuration

Edit the configuration block at the top of `cable_modem_stats.py`:

```python
MODEM_IP = "192.168.100.1"
USER = "YOUR_MODEM_USERNAME"
PASS = "YOUR_MODEM_PASSWORD"
DEBUG = False        # save raw HTML + verbose output
LOG_TO_CSV = True    # append a summary row to modem_history.csv
```

Do not commit real credentials.

## Usage

```bash
python cable_modem_stats.py
```
