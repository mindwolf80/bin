"""
Arris SB8200 Signal Health Monitor
----------------------------------
Pulls the modem's connection status page, parses the channel tables,
and grades every channel in plain English so you don't have to decode
DOCSIS numbers yourself.

Grades used:
  GOOD      - comfortably inside spec
  OK        - inside spec, nothing to worry about
  MARGINAL  - drifting toward the edge, keep an eye on it
  BAD       - out of spec / needs attention

Each run also appends a summary line to modem_history.csv (same folder
as this script) so you build up evidence over time.
"""

import requests
import urllib3
import ssl
import re
import json
import csv
import base64
import time
import sys
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup

# ============ CONFIGURATION ============
MODEM_IP = "192.168.100.1"
USER = "YOUR_MODEM_USERNAME"
PASS = "YOUR_MODEM_PASSWORD"
DEBUG = False  # True = save raw HTML + verbose output
LOG_TO_CSV = True  # append a summary row to modem_history.csv each run
# =======================================


# ---------- TLS adapter so we can talk to the modem's old cipher suite ----------
class TLSAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.check_hostname = False
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ---------- helpers ----------
def to_float(text):
    """Pull the first number out of text like '4.5 dBmV' or '39.2 dB'. None if no number."""
    m = re.search(r"-?\d+\.?\d*", text or "")
    return float(m.group()) if m else None


def to_int(text):
    v = to_float(text)
    return int(v) if v is not None else None


# ---------- health grading (DOCSIS 3.1 / SB8200 guidelines) ----------
def grade_downstream(ch):
    """Return (grade, list_of_notes) for one downstream channel."""
    notes = []
    grade = "GOOD"

    power = to_float(ch.get("power"))
    snr = to_float(ch.get("snr"))
    uncorr = to_int(ch.get("uncorrectables"))
    is_ofdm = "ofdm" in (ch.get("modulation") or "").lower()

    # Power: ideal -7..+7, acceptable -10..+10, out of spec beyond -15..+15
    if power is not None:
        if power < -15 or power > 15:
            grade = "BAD"
            notes.append(f"power {power:+.1f} dBmV OUT OF SPEC")
        elif power < -10 or power > 10:
            grade = "MARGINAL"
            notes.append(f"power {power:+.1f} dBmV near limit")
        elif power < -7 or power > 7:
            if grade == "GOOD":
                grade = "OK"
            notes.append(f"power {power:+.1f} dBmV slightly off-center")

    # SNR/MER: QAM256 wants >= 33 dB (30 = danger). OFDM reports MER, wants ~35+.
    if snr is not None:
        low, danger = (35.0, 32.0) if is_ofdm else (33.0, 30.0)
        if snr < danger:
            grade = "BAD"
            notes.append(f"SNR {snr:.1f} dB TOO LOW")
        elif snr < low:
            if grade != "BAD":
                grade = "MARGINAL"
            notes.append(f"SNR {snr:.1f} dB on the low side")

    # Uncorrectables (cumulative since reboot)
    if uncorr:
        if uncorr > 10000:
            grade = "BAD"
            notes.append(f"{uncorr:,} uncorrectables")
        elif uncorr > 100:
            if grade != "BAD":
                grade = "MARGINAL"
            notes.append(f"{uncorr:,} uncorrectables")
        else:
            notes.append(f"{uncorr} uncorrectables (minor)")

    if ch.get("lock_status", "").lower() not in ("locked", ""):
        grade = "BAD"
        notes.append(f"not locked ({ch.get('lock_status')})")

    return grade, notes


def grade_upstream(ch):
    """Return (grade, list_of_notes) for one upstream channel."""
    notes = []
    grade = "GOOD"

    power = to_float(ch.get("power"))
    # Upstream: ideal 38..48, acceptable 35..51, out of spec beyond that.
    # High upstream power = modem shouting to be heard = return path trouble.
    if power is not None:
        if power < 35 or power > 51:
            grade = "BAD"
            notes.append(f"power {power:.1f} dBmV OUT OF SPEC")
        elif power > 48:
            grade = "MARGINAL"
            notes.append(f"power {power:.1f} dBmV getting high")
        elif power < 38:
            grade = "MARGINAL"
            notes.append(f"power {power:.1f} dBmV getting low")

    if ch.get("lock_status", "").lower() not in ("locked", ""):
        grade = "BAD"
        notes.append(f"not locked ({ch.get('lock_status')})")

    return grade, notes


# ---------- scraping ----------
def get_modem_stats():
    session = requests.Session()
    session.mount("https://", TLSAdapter())

    try:
        credentials = f"{USER}:{PASS}"
        auth_hash = base64.b64encode(credentials.encode()).decode()
        headers = {"Authorization": f"Basic {auth_hash}"}

        # Pre-flight to establish session cookie
        session.get(f"https://{MODEM_IP}/", verify=False, timeout=10)

        # Step 1: CSRF token (with retries)
        login_url = f"https://{MODEM_IP}/cmconnectionstatus.html?login_{auth_hash}"
        token = None
        for attempt in range(3):
            r = session.get(
                login_url,
                headers=headers,
                verify=False,
                timeout=10,
                allow_redirects=False,
            )
            token = r.text.strip()
            if DEBUG:
                print(f"DEBUG: token attempt {attempt+1}: {token[:40]}")
            # A real token is a short alphanumeric string, not an HTML page
            if r.status_code == 200 and 10 <= len(token) <= 128 and token.isalnum():
                break
            token = None
            time.sleep(0.5)

        if not token:
            return {"error": "Failed to get a valid authentication token after retries"}

        # Step 2: fetch status page
        status_url = f"https://{MODEM_IP}/cmconnectionstatus.html?ct_{token}"
        r = session.get(status_url, headers=headers, verify=False, timeout=10)
        r.raise_for_status()

        if DEBUG:
            Path("modem_page.html").write_text(r.text, encoding="utf-8")
            print("DEBUG: saved modem_page.html")

        text_lower = r.text.lower()
        if (
            "login" in text_lower
            and "username" in text_lower
            and "password" in text_lower
        ):
            return {"error": "Authentication failed - redirected to login page"}

        return parse_status_page(r.text)

    except Exception as e:
        if DEBUG:
            import traceback

            traceback.print_exc()
        return {"error": str(e)}
    finally:
        session.close()


# Column spec: output_key -> keywords that identify the header cell
DS_COLUMNS = {
    "channel_id": ["channel id", "channel"],
    "lock_status": ["lock"],
    "modulation": ["modulation"],
    "frequency": ["frequency"],
    "power": ["power"],
    "snr": ["snr", "mer"],
    "corrected": ["corrected"],  # matched only if 'uncorrect' not in header
    "uncorrectables": ["uncorrect"],
}
US_COLUMNS = {
    "channel": ["channel"],
    "channel_id": ["channel id"],
    "lock_status": ["lock"],
    "type": ["type"],
    "frequency": ["frequency"],
    "width": ["width"],
    "power": ["power"],
}


def map_columns(headers, spec):
    """Map output keys to column indices based on header keywords."""
    idx = {}
    for key, keywords in spec.items():
        for i, h in enumerate(headers):
            if key == "corrected" and "uncorrect" in h:
                continue
            if (
                key == "channel_id"
                and "channel id" not in h
                and "channel id" in " ".join(headers)
            ):
                # prefer exact 'channel id' column when it exists
                if "channel id" not in h:
                    continue
            if any(kw in h for kw in keywords):
                idx[key] = i
                break
    return idx


def parse_table(rows, header_row_idx, headers, spec):
    """Generic channel-table parser. Returns list of dicts."""
    col_idx = map_columns(headers, spec)
    out = []
    for row in rows[header_row_idx:]:
        cols = row.find_all("td")
        if not cols or any(c.find("strong") for c in cols) or len(cols) < 3:
            continue
        entry = {}
        for key, i in col_idx.items():
            if i < len(cols):
                entry[key] = cols[i].text.strip()
        if entry.get("power") or entry.get("snr"):
            out.append(entry)
    return out


def parse_status_page(html):
    soup = BeautifulSoup(html, "html.parser")
    stats = {"timestamp": datetime.now().isoformat(), "downstream": [], "upstream": []}

    for table in soup.find_all("table"):
        table_text = table.get_text().lower()
        rows = table.find_all("tr")

        # find header row
        headers, header_row_idx = [], 0
        header_keywords = [
            "channel",
            "frequency",
            "power",
            "lock",
            "status",
            "modulation",
            "snr",
            "type",
        ]
        for i, row in enumerate(rows):
            if row.find("th"):
                continue
            tds = row.find_all("td")
            if len(tds) > 1:
                row_text = [td.text.strip().lower() for td in tds]
                hits = sum(1 for t in row_text if any(k in t for k in header_keywords))
                if hits >= len(tds) // 2:
                    headers, header_row_idx = row_text, i + 1
                    break

        if any("downstream" in h for h in headers) or "downstream" in table_text[:200]:
            if not headers or "channel" not in " ".join(headers):
                headers = [
                    "channel id",
                    "lock status",
                    "modulation",
                    "frequency",
                    "power",
                    "snr/mer",
                    "corrected",
                    "uncorrectables",
                ]
                header_row_idx = 1
            stats["downstream"] = parse_table(rows, header_row_idx, headers, DS_COLUMNS)

        elif any("upstream" in h for h in headers) or "upstream" in table_text[:200]:
            if not headers or "channel" not in " ".join(headers):
                headers = [
                    "channel",
                    "channel id",
                    "lock status",
                    "us channel type",
                    "frequency",
                    "width",
                    "power",
                ]
                header_row_idx = 1
            stats["upstream"] = parse_table(rows, header_row_idx, headers, US_COLUMNS)

    return stats


# ---------- output ----------
def fmt_mhz(freq_text):
    hz = to_float(freq_text)
    return f"{hz/1e6:.1f} MHz" if hz else (freq_text or "")


def print_report(stats):
    all_warnings = []

    print(f"\n{'='*100}")
    print(f"MODEM SIGNAL HEALTH  -  {stats['timestamp']}")
    print(f"{'='*100}")

    # ----- Downstream -----
    if stats["downstream"]:
        print(f"\nDOWNSTREAM  ({len(stats['downstream'])} channels)")
        print(f"{'-'*100}")
        print(
            f"{'Ch':<5} {'Mod':<10} {'Freq':<12} {'Power':<12} {'SNR':<10} "
            f"{'Uncorr':<10} {'STATUS':<9} Notes"
        )
        print(f"{'-'*100}")
        for ch in stats["downstream"]:
            grade, notes = grade_downstream(ch)
            if grade in ("MARGINAL", "BAD"):
                all_warnings.append(
                    f"DS ch {ch.get('channel_id','?')}: " + "; ".join(notes)
                )
            print(
                f"{ch.get('channel_id',''):<5} "
                f"{ch.get('modulation',''):<10} "
                f"{fmt_mhz(ch.get('frequency')):<12} "
                f"{ch.get('power',''):<12} "
                f"{ch.get('snr',''):<10} "
                f"{ch.get('uncorrectables',''):<10} "
                f"{grade:<9} "
                f"{'; '.join(notes)}"
            )

    # ----- Upstream -----
    if stats["upstream"]:
        print(f"\nUPSTREAM  ({len(stats['upstream'])} channels)")
        print(f"{'-'*100}")
        print(
            f"{'Ch':<5} {'Type':<18} {'Freq':<12} {'Width':<12} "
            f"{'Power':<12} {'STATUS':<9} Notes"
        )
        print(f"{'-'*100}")
        for ch in stats["upstream"]:
            grade, notes = grade_upstream(ch)
            if grade in ("MARGINAL", "BAD"):
                all_warnings.append(
                    f"US ch {ch.get('channel_id','?')}: " + "; ".join(notes)
                )
            print(
                f"{ch.get('channel_id') or ch.get('channel',''):<5} "
                f"{ch.get('type',''):<18} "
                f"{fmt_mhz(ch.get('frequency')):<12} "
                f"{fmt_mhz(ch.get('width')):<12} "
                f"{ch.get('power',''):<12} "
                f"{grade:<9} "
                f"{'; '.join(notes)}"
            )

    # ----- Verdict -----
    print(f"\n{'='*100}")
    if all_warnings:
        print(f"ATTENTION NEEDED ({len(all_warnings)} items):")
        for w in all_warnings:
            print(f"  ! {w}")
    else:
        print("VERDICT: All channels healthy. Nothing to worry about.")
    print(f"{'='*100}\n")

    return all_warnings


def log_csv(stats, warnings):
    """Append one summary row per run - builds trend history for ISP evidence."""
    csv_path = Path(__file__).parent / "modem_history.csv"
    ds = stats["downstream"]
    us = stats["upstream"]
    ds_powers = [
        to_float(c.get("power")) for c in ds if to_float(c.get("power")) is not None
    ]
    ds_snrs = [to_float(c.get("snr")) for c in ds if to_float(c.get("snr")) is not None]
    us_powers = [
        to_float(c.get("power")) for c in us if to_float(c.get("power")) is not None
    ]
    total_uncorr = sum(to_int(c.get("uncorrectables")) or 0 for c in ds)

    row = {
        "timestamp": stats["timestamp"],
        "ds_channels": len(ds),
        "us_channels": len(us),
        "ds_power_min": min(ds_powers) if ds_powers else "",
        "ds_power_max": max(ds_powers) if ds_powers else "",
        "ds_snr_min": min(ds_snrs) if ds_snrs else "",
        "us_power_max": max(us_powers) if us_powers else "",
        "total_uncorrectables": total_uncorr,
        "warnings": len(warnings),
    }
    new_file = not csv_path.exists()
    with open(csv_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if new_file:
            writer.writeheader()
        writer.writerow(row)


# ---------- main ----------
if __name__ == "__main__":
    result = get_modem_stats()

    if "error" in result:
        print(f"\nERROR: {result['error']}\n")
        sys.exit(1)

    warnings = print_report(result)

    if LOG_TO_CSV:
        log_csv(result, warnings)

    # exit 1 if anything is BAD so schedulers can detect trouble
    if any("OUT OF SPEC" in w or "TOO LOW" in w or "not locked" in w for w in warnings):
        sys.exit(1)
