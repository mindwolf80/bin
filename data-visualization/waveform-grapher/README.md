# Waveform Grapher

Streamlit dashboard ("Network Performance Dashboard") for visualizing network speed-test results from CSV.

## Requirements

- Python 3.9+
- `pip install -r requirements.txt`

## Usage

```bash
streamlit run waveform_grapher.py
```

Upload a CSV containing columns such as `Download Speed (Mbps)` and `Upload Speed (Mbps)`. The dashboard renders gauge indicators and time-series charts.
