# YouTube Transcript Extractor

Desktop application (tkinter + ttkbootstrap) that fetches a YouTube video's captions and displays them as timestamped paragraphs, with export to `.txt`.

## Requirements

- Python 3.9+
- `pip install -r requirements.txt`

## Usage

```bash
python yt_transcript_fetcher.py
```

Paste a YouTube URL or video ID and click **Fetch**. Compatible with both `youtube-transcript-api` v1.0+ and earlier releases.

## Building a Standalone Binary

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --icon extract.ico --name YouTubeTranscriptExtractor yt_transcript_fetcher.py
```

Output: `dist/YouTubeTranscriptExtractor`.
