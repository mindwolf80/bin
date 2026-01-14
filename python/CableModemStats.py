import requests
from bs4 import BeautifulSoup
import json
import urllib3
import ssl
import re
from datetime import datetime
import base64

# This class forces the connection to use older ciphers that the modem understands
class TLSAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        # Lower security level to allow older modem ciphers
        ctx.set_ciphers('DEFAULT@SECLEVEL=1')
        # Allow older TLS versions if necessary - using TLSv1_2 to avoid deprecation warning
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.check_hostname = False
        kwargs['ssl_context'] = ctx
        return super(TLSAdapter, self).init_poolmanager(*args, **kwargs)

# Disable SSL warnings for the modem's self-signed cert
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# CONFIGURATION
MODEM_IP = "192.168.100.1"
USER = "username"
PASS = "password"
DEBUG = False  # Set to True to save HTML for debugging

def get_modem_stats():
    session = requests.Session()
    # Apply our custom security "downgrade" to this session
    session.mount('https://', TLSAdapter())
    
    try:
        # Create Basic Auth header
        credentials = f"{USER}:{PASS}"
        auth_hash = base64.b64encode(credentials.encode()).decode()
        headers = {'Authorization': f'Basic {auth_hash}'}
        
        # PRE-FLIGHT: Visit base page first to establish session cookie
        if DEBUG:
            print("DEBUG: Performing pre-flight request to establish session...")
        session.get(f"https://{MODEM_IP}/", verify=False, timeout=10)
        
        # Step 1: Get the CSRF token with retry logic
        login_url = f"https://{MODEM_IP}/cmconnectionstatus.html?login_{auth_hash}"
        token = None
        max_retries = 3
        
        for attempt in range(max_retries):
            if DEBUG and attempt > 0:
                print(f"DEBUG: Token retrieval attempt {attempt + 1}/{max_retries}")
            
            response = session.get(login_url, headers=headers, verify=False, timeout=10, allow_redirects=False)
            token = response.text.strip()
            
            if DEBUG:
                print(f"DEBUG: Got token (attempt {attempt + 1}): {token}")
            
            # Check if token is valid
            if token and len(token) >= 10:
                break
            
            # Wait a bit before retrying
            if attempt < max_retries - 1:
                import time
                time.sleep(0.5)
        
        if not token or len(token) < 10:
            return {"error": "Failed to get authentication token after retries"}
        
        # Step 2: Now fetch the connection status page with the token
        status_url = f"https://{MODEM_IP}/cmconnectionstatus.html?ct_{token}"
        
        # Use the same session with cookies preserved
        response = session.get(status_url, headers=headers, verify=False, timeout=10)
        response.raise_for_status()
        
        # Debug: Save HTML for inspection
        if DEBUG:
            with open('modem_page.html', 'w', encoding='utf-8') as f:
                f.write(response.text)
            print("DEBUG: Saved HTML to modem_page.html for inspection")
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Check if we got redirected to login page
        if 'login' in response.text.lower() and 'username' in response.text.lower() and 'password' in response.text.lower():
            return {"error": "Authentication failed - redirected to login page"}
        
        stats = {
            "timestamp": datetime.now().isoformat(),
            "downstream": [],
            "upstream": []
        }

        # Parsing tables - Arris modems typically have multiple tables
        tables = soup.find_all('table')
        
        if DEBUG:
            print(f"DEBUG: Found {len(tables)} tables")
        
        for idx, table in enumerate(tables):
            # Get all text in the table to help identify it
            table_text = table.get_text().lower()
            
            if DEBUG:
                print(f"\nDEBUG: Table {idx} preview: {table_text[:100]}...")
            
            # Find table headers - look for row with <strong> tags in <td> elements
            headers = []
            rows = table.find_all('tr')
            header_row_idx = 0
            
            for i, row in enumerate(rows):
                # Skip the title row (th colspan)
                if row.find('th'):
                    continue
                    
                # Check if this row contains headers
                tds = row.find_all('td')
                if tds and len(tds) > 1:  # Must have multiple columns
                    # Get the text from all cells
                    row_text = [td.text.strip().lower() for td in tds]
                    
                    # Check if this looks like a header row (contains common header keywords)
                    header_keywords = ['channel', 'frequency', 'power', 'lock', 'status', 'modulation', 'snr', 'type']
                    keyword_count = sum(1 for text in row_text if any(kw in text for kw in header_keywords))
                    
                    if DEBUG:
                        print(f"DEBUG: Row {i}: {len(tds)} tds, texts: {row_text[:3]}... keyword_count={keyword_count}")
                    
                    # If most cells contain header keywords, this is the header row
                    if keyword_count >= len(tds) // 2:
                        headers = row_text
                        header_row_idx = i + 1  # Data starts after header row
                        if DEBUG:
                            print(f"DEBUG: Found header row at index {i}, data starts at {header_row_idx}")
                        break
            
            if DEBUG and headers:
                print(f"DEBUG: Headers: {headers}")
            
            # Downstream Bonded Channels
            if any('downstream' in h for h in headers) or 'downstream' in table_text[:200]:
                # For Arris SB8200, use known header structure if headers weren't found
                if not headers or 'channel' not in ' '.join(headers):
                    headers = ['channel id', 'lock status', 'modulation', 'frequency', 'power', 'snr/mer', 'corrected', 'uncorrectables']
                    header_row_idx = 1  # Data starts at row 1 (after title row)
                
                if DEBUG:
                    print(f"DEBUG: Processing downstream table with {len(rows)} rows, starting at row {header_row_idx}")
                    print(f"DEBUG: Using headers: {headers}")
                
                # Find header indices
                channel_idx = next((i for i, h in enumerate(headers) if 'channel id' in h or 'channel' in h), 0)
                freq_idx = next((i for i, h in enumerate(headers) if 'frequency' in h), -1)
                power_idx = next((i for i, h in enumerate(headers) if 'power' in h), -1)
                snr_idx = next((i for i, h in enumerate(headers) if 'snr' in h or 'mer' in h), -1)
                modulation_idx = next((i for i, h in enumerate(headers) if 'modulation' in h), -1)
                lock_idx = next((i for i, h in enumerate(headers) if 'lock' in h), -1)
                corrected_idx = next((i for i, h in enumerate(headers) if 'corrected' in h and 'uncorrect' not in h), -1)
                uncorrect_idx = next((i for i, h in enumerate(headers) if 'uncorrect' in h), -1)
                
                for row in rows[header_row_idx:]:  # Start from data rows
                    cols = row.find_all('td')
                    # Skip rows with strong tags (headers)
                    if cols and not any(col.find('strong') for col in cols):
                        if len(cols) >= 3:  # At least some data
                            channel_data = {
                                "channel_id": cols[channel_idx].text.strip() if channel_idx < len(cols) else "",
                            }
                            if lock_idx >= 0 and lock_idx < len(cols):
                                channel_data["lock_status"] = cols[lock_idx].text.strip()
                            if modulation_idx >= 0 and modulation_idx < len(cols):
                                channel_data["modulation"] = cols[modulation_idx].text.strip()
                            if freq_idx >= 0 and freq_idx < len(cols):
                                channel_data["frequency"] = cols[freq_idx].text.strip()
                            if power_idx >= 0 and power_idx < len(cols):
                                channel_data["power"] = cols[power_idx].text.strip()
                            if snr_idx >= 0 and snr_idx < len(cols):
                                channel_data["snr"] = cols[snr_idx].text.strip()
                            if corrected_idx >= 0 and corrected_idx < len(cols):
                                channel_data["corrected"] = cols[corrected_idx].text.strip()
                            if uncorrect_idx >= 0 and uncorrect_idx < len(cols):
                                channel_data["uncorrectables"] = cols[uncorrect_idx].text.strip()
                            
                            # Only add if we have meaningful data
                            if channel_data.get("power") or channel_data.get("snr"):
                                stats["downstream"].append(channel_data)
            
            # Upstream Bonded Channels
            elif any('upstream' in h for h in headers) or 'upstream' in table_text[:200]:
                # For Arris SB8200, use known header structure if headers weren't found
                if not headers or 'channel' not in ' '.join(headers):
                    headers = ['channel', 'channel id', 'lock status', 'us channel type', 'frequency', 'width', 'power']
                    header_row_idx = 1  # Data starts at row 1 (after title row)
                
                if DEBUG:
                    print(f"DEBUG: Processing upstream table with {len(rows)} rows, starting at row {header_row_idx}")
                    print(f"DEBUG: Using headers: {headers}")
                
                # Find header indices
                channel_idx = next((i for i, h in enumerate(headers) if 'channel' == h), 0)
                channel_id_idx = next((i for i, h in enumerate(headers) if 'channel id' in h), -1)
                freq_idx = next((i for i, h in enumerate(headers) if 'frequency' in h), -1)
                power_idx = next((i for i, h in enumerate(headers) if 'power' in h), -1)
                type_idx = next((i for i, h in enumerate(headers) if 'type' in h), -1)
                lock_idx = next((i for i, h in enumerate(headers) if 'lock' in h), -1)
                width_idx = next((i for i, h in enumerate(headers) if 'width' in h), -1)
                
                for row in rows[header_row_idx:]:  # Start from data rows
                    cols = row.find_all('td')
                    # Skip rows with strong tags (headers)
                    if cols and not any(col.find('strong') for col in cols):
                        if len(cols) >= 3:  # At least some data
                            channel_data = {
                                "channel": cols[channel_idx].text.strip() if channel_idx < len(cols) else "",
                            }
                            if channel_id_idx >= 0 and channel_id_idx < len(cols):
                                channel_data["channel_id"] = cols[channel_id_idx].text.strip()
                            if lock_idx >= 0 and lock_idx < len(cols):
                                channel_data["lock_status"] = cols[lock_idx].text.strip()
                            if type_idx >= 0 and type_idx < len(cols):
                                channel_data["type"] = cols[type_idx].text.strip()
                            if freq_idx >= 0 and freq_idx < len(cols):
                                channel_data["frequency"] = cols[freq_idx].text.strip()
                            if width_idx >= 0 and width_idx < len(cols):
                                channel_data["width"] = cols[width_idx].text.strip()
                            if power_idx >= 0 and power_idx < len(cols):
                                channel_data["power"] = cols[power_idx].text.strip()
                            
                            # Only add if we have meaningful data
                            if channel_data.get("power"):
                                stats["upstream"].append(channel_data)

        return stats

    except Exception as e:
        if DEBUG:
            import traceback
            print(f"DEBUG: Exception details:\n{traceback.format_exc()}")
        return {"error": str(e)}

if __name__ == "__main__":
    result = get_modem_stats()
    print(json.dumps(result, indent=4))
    
    # Print summary and tables
    if "error" not in result:
        print(f"\n{'='*80}")
        print(f"SUMMARY - {result['timestamp']}")
        print(f"{'='*80}")
        print(f"Downstream channels: {len(result['downstream'])}")
        print(f"Upstream channels: {len(result['upstream'])}")
        
        if result['downstream']:
            powers = [float(ch['power'].replace(' dBmV', '')) for ch in result['downstream'] if 'power' in ch]
            snrs = [float(ch['snr'].replace(' dB', '')) for ch in result['downstream'] if 'snr' in ch]
            if powers:
                print(f"Downstream Power: min={min(powers):.1f} dBmV, max={max(powers):.1f} dBmV, avg={sum(powers)/len(powers):.1f} dBmV")
            if snrs:
                print(f"Downstream SNR: min={min(snrs):.1f} dB, max={max(snrs):.1f} dB, avg={sum(snrs)/len(snrs):.1f} dB")
        
        if result['upstream']:
            powers = [float(ch['power'].replace(' dBmV', '')) for ch in result['upstream'] if 'power' in ch]
            if powers:
                print(f"Upstream Power: min={min(powers):.1f} dBmV, max={max(powers):.1f} dBmV, avg={sum(powers)/len(powers):.1f} dBmV")
        
        # Print Downstream Table
        if result['downstream']:
            print(f"\n{'='*80}")
            print("DOWNSTREAM BONDED CHANNELS")
            print(f"{'='*80}")
            print(f"{'Ch ID':<6} {'Status':<8} {'Mod':<8} {'Frequency':<14} {'Power':<10} {'SNR':<8} {'Corrected':<12} {'Uncorr':<10}")
            print(f"{'-'*80}")
            for ch in result['downstream']:
                ch_id = ch.get('channel_id', '')
                status = ch.get('lock_status', '')
                mod = ch.get('modulation', '')
                freq = ch.get('frequency', '').replace(' Hz', '')
                power = ch.get('power', '')
                snr = ch.get('snr', '')
                corrected = ch.get('corrected', '')
                uncorr = ch.get('uncorrectables', '')
                print(f"{ch_id:<6} {status:<8} {mod:<8} {freq:<14} {power:<10} {snr:<8} {corrected:<12} {uncorr:<10}")
        
        # Print Upstream Table
        if result['upstream']:
            print(f"\n{'='*80}")
            print("UPSTREAM BONDED CHANNELS")
            print(f"{'='*80}")
            print(f"{'Ch':<4} {'Ch ID':<6} {'Status':<8} {'Type':<18} {'Frequency':<12} {'Width':<12} {'Power':<10}")
            print(f"{'-'*80}")
            for ch in result['upstream']:
                channel = ch.get('channel', '')
                ch_id = ch.get('channel_id', '')
                status = ch.get('lock_status', '')
                ch_type = ch.get('type', '')
                freq = ch.get('frequency', '').replace(' Hz', '')
                width = ch.get('width', '').replace(' Hz', '')
                power = ch.get('power', '')
                print(f"{channel:<4} {ch_id:<6} {status:<8} {ch_type:<18} {freq:<12} {width:<12} {power:<10}")
        
        print(f"{'='*80}\n")

