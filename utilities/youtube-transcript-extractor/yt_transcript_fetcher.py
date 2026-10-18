"""
YouTube Transcript Fetcher
--------------------------
Fetches the transcript (captions) of a YouTube video and displays it
in a readable, timestamped, paragraph format. Lets you save it as a
text file.

Requirements (run these once in a command prompt):
    pip install --upgrade youtube-transcript-api ttkbootstrap
"""

import re
import textwrap
import threading
import tkinter as tk
from tkinter import filedialog

import ttkbootstrap as ttk
from youtube_transcript_api import YouTubeTranscriptApi

# ----------------------------------------------------------------------
# Transcript fetching (compatible with both old and new library versions)
# ----------------------------------------------------------------------


def fetch_transcript_data(video_id):
    """
    Fetch the transcript for a video and return it as a list of
    dictionaries: [{"text": ..., "start": ..., "duration": ...}, ...]

    Works with the NEW library API (v1.0+) and falls back to the OLD
    one if an older version is installed.
    """
    # New API (youtube-transcript-api v1.0 and later)
    try:
        ytt_api = YouTubeTranscriptApi()
        fetched = ytt_api.fetch(video_id)
        return fetched.to_raw_data()
    except AttributeError:
        pass  # Older library version installed; try the old way below

    # Old API (pre-v1.0) - kept as a safety net
    return YouTubeTranscriptApi.get_transcript(video_id)


def friendly_error_message(error):
    """Turn library errors into plain-English status messages."""
    name = type(error).__name__

    messages = {
        "TranscriptsDisabled": (
            "Couldn't get captions. Either this video has captions "
            "turned off, or YouTube is temporarily blocking requests "
            "from your internet address. Try again later or try "
            "another video."
        ),
        "NoTranscriptFound": (
            "No transcript found for this video in a supported " "language."
        ),
        "VideoUnavailable": (
            "This video is unavailable (private, deleted, or " "region-locked)."
        ),
        "RequestBlocked": (
            "YouTube is blocking requests from your internet address "
            "right now. Wait a while and try again."
        ),
        "IpBlocked": (
            "YouTube is blocking requests from your internet address "
            "right now. Wait a while and try again."
        ),
        "AgeRestricted": (
            "This video is age-restricted, so its captions can't be " "fetched."
        ),
        "YouTubeDataUnparsable": (
            "YouTube changed something on their end and the transcript "
            "library can't read it. Run this in a command prompt to "
            "update: pip install --upgrade youtube-transcript-api"
        ),
    }

    return messages.get(name, f"Error: {error}")


# ----------------------------------------------------------------------
# Formatting helpers
# ----------------------------------------------------------------------


def format_timestamp(seconds):
    """Convert seconds to MM:SS format."""
    minutes = int(seconds // 60)
    remaining_seconds = int(seconds % 60)
    return f"{minutes:02d}:{remaining_seconds:02d}"


def format_transcript_text(transcript):
    """
    Format transcript entries into readable paragraphs:
    - Groups sentences into paragraphs (roughly 200-300 words)
    - Starts a new paragraph on topic-transition words or time gaps
    - Includes clear timestamp markers
    """
    if not transcript:
        return "No transcript data available."

    formatted_text = []
    current_paragraph = []
    last_timestamp = None
    sentence_count = 0
    word_count = 0

    def format_paragraph(texts, timestamp):
        """Wrap a paragraph to 80 characters with a leading timestamp."""
        if not texts:
            return ""
        full_text = " ".join(texts)
        return textwrap.fill(
            full_text,
            width=80,
            initial_indent=f"[{timestamp}] ",
            subsequent_indent=" " * 8,
            break_long_words=True,
            break_on_hyphens=True,
        )

    topic_transitions = [
        "next",
        "now",
        "however",
        "furthermore",
        "moreover",
        "in addition",
        "finally",
        "therefore",
        "consequently",
        "first",
        "second",
        "third",
        "last",
        "in conclusion",
    ]

    for entry in transcript:
        text = entry["text"].strip()
        if not text:
            continue

        sentences_in_text = len(
            [s for s in text.split() if s.endswith((".", "!", "?"))]
        )
        words_in_text = len(text.split())

        new_paragraph = current_paragraph and (
            sentence_count >= 8
            or word_count + words_in_text > 300
            or any(text.lower().startswith(p) for p in topic_transitions)
            or entry["start"] - last_timestamp > 5
        )

        if new_paragraph:
            formatted_text.append(
                format_paragraph(current_paragraph, format_timestamp(paragraph_start))
            )
            current_paragraph = [text]
            paragraph_start = entry["start"]
            sentence_count = sentences_in_text
            word_count = words_in_text
        else:
            if not current_paragraph:
                paragraph_start = entry["start"]
            current_paragraph.append(text)
            sentence_count += sentences_in_text
            word_count += words_in_text

        last_timestamp = entry["start"]

    if current_paragraph:
        formatted_text.append(
            format_paragraph(current_paragraph, format_timestamp(paragraph_start))
        )

    return "\n\n".join(formatted_text)


def extract_video_id(url_or_id):
    """Extract video ID from various YouTube URL formats, or accept a bare ID."""
    if not url_or_id:
        return None

    patterns = [
        # Standard, embed, shorts, and youtu.be URLs
        r"(?:v=|v/|embed/|shorts/|youtu\.be/)([a-zA-Z0-9_-]{11})",
        r"^([a-zA-Z0-9_-]{11})$",  # Direct video ID
    ]

    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)

    return None


# ----------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------

PLACEHOLDER_URL = "Paste YouTube URL (e.g., youtube.com/watch?v=... or youtu.be/...)"
PLACEHOLDER_TEXT = (
    "Transcript will appear here with timestamps. "
    "Use Ctrl+A to select all, Ctrl+C to copy."
)


class TranscriptApp:
    def __init__(self, root):
        self.root = root
        self.root.title("YouTube Transcript Fetcher")
        self.root.geometry("800x600")
        self.root.minsize(600, 400)

        self.has_transcript = False  # Track whether real content is loaded

        # Configure grid weights for main window
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        # Main frame
        self.main_frame = ttk.Frame(root, padding="10")
        self.main_frame.grid(row=0, column=0, sticky="nsew")
        self.main_frame.grid_rowconfigure(1, weight=1)
        self.main_frame.grid_columnconfigure(0, weight=1)

        # --- URL input row ---
        self.url_frame = ttk.Frame(self.main_frame)
        self.url_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.url_frame.grid_columnconfigure(1, weight=1)

        self.url_label = ttk.Label(self.url_frame, text="YouTube URL:", width=12)
        self.url_label.grid(row=0, column=0, padx=(0, 5))

        self.url_entry = ttk.Entry(self.url_frame)
        self.url_entry.insert(0, PLACEHOLDER_URL)

        def on_focus_in(_event):
            if self.url_entry.get() == PLACEHOLDER_URL:
                self.url_entry.delete(0, tk.END)

        def on_focus_out(_event):
            if not self.url_entry.get():
                self.url_entry.insert(0, PLACEHOLDER_URL)

        self.url_entry.bind("<FocusIn>", on_focus_in)
        self.url_entry.bind("<FocusOut>", on_focus_out)
        self.url_entry.grid(row=0, column=1, sticky="ew")
        self.url_entry.bind("<Return>", lambda e: self.fetch_transcript())

        self.fetch_btn = ttk.Button(
            self.url_frame,
            text="Fetch Transcript",
            command=self.fetch_transcript,
            style="primary.TButton",
        )
        self.fetch_btn.grid(row=0, column=2, padx=(5, 0))

        # --- Transcript display ---
        self.transcript_frame = ttk.Frame(self.main_frame)
        self.transcript_frame.grid(row=1, column=0, sticky="nsew")
        self.transcript_frame.grid_rowconfigure(0, weight=1)
        self.transcript_frame.grid_columnconfigure(0, weight=1)

        self.transcript_text = tk.Text(
            self.transcript_frame, wrap=tk.WORD, font=("Segoe UI", 10)
        )
        self.transcript_text.insert("1.0", PLACEHOLDER_TEXT)
        self.transcript_text.configure(state="disabled")
        self.transcript_text.grid(row=0, column=0, sticky="nsew")

        self.transcript_text.bind("<Control-a>", self.select_all)
        self.transcript_text.bind("<Control-A>", self.select_all)

        self.scrollbar = ttk.Scrollbar(
            self.transcript_frame,
            orient=tk.VERTICAL,
            command=self.transcript_text.yview,
        )
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.transcript_text["yscrollcommand"] = self.scrollbar.set

        # --- Bottom row: save button, status, sizegrip ---
        self.bottom_frame = ttk.Frame(self.main_frame)
        self.bottom_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.bottom_frame.grid_columnconfigure(1, weight=1)

        self.save_btn = ttk.Button(
            self.bottom_frame,
            text="Save Transcript (Ctrl+S)",
            command=self.save_transcript,
            style="secondary.TButton",
        )
        self.save_btn.grid(row=0, column=0)

        self.root.bind("<Control-s>", lambda e: self.save_transcript())
        self.root.bind("<Control-S>", lambda e: self.save_transcript())

        self.status_label = ttk.Label(self.bottom_frame, text="", wraplength=0)
        self.status_label.grid(row=0, column=1, sticky="ew", padx=10)

        self.sizegrip = ttk.Sizegrip(self.bottom_frame)
        self.sizegrip.grid(row=0, column=2, sticky="se")

        self.root.bind("<Configure>", self._on_window_resize)

    # ------------------------------------------------------------------
    # Fetching (runs in a background thread so the window never freezes)
    # ------------------------------------------------------------------

    def fetch_transcript(self):
        input_text = self.url_entry.get().strip()
        if not input_text or input_text == PLACEHOLDER_URL:
            self.show_status("Enter a YouTube URL or video ID", "danger")
            return

        video_id = extract_video_id(input_text)
        if not video_id:
            self.show_status("Invalid YouTube URL or video ID format", "danger")
            return

        # Disable the button so it can't be double-clicked mid-fetch
        self.fetch_btn.configure(state="disabled", text="Fetching...")
        self.show_status("Fetching transcript... please wait.", "info")

        thread = threading.Thread(
            target=self._fetch_worker, args=(video_id,), daemon=True
        )
        thread.start()

    def _fetch_worker(self, video_id):
        """Runs in the background. Never touches the GUI directly."""
        try:
            transcript = fetch_transcript_data(video_id)
            formatted = format_transcript_text(transcript)
            self.root.after(0, self._fetch_done, formatted, None)
        except Exception as error:
            self.root.after(0, self._fetch_done, None, error)

    def _fetch_done(self, formatted, error):
        """Runs on the main GUI thread once fetching finishes."""
        self.fetch_btn.configure(state="normal", text="Fetch Transcript")

        if error is not None:
            self.show_status(friendly_error_message(error), "danger")
            return

        self.transcript_text.configure(state="normal")
        self.transcript_text.delete("1.0", tk.END)
        self.transcript_text.insert(tk.END, formatted)
        self.transcript_text.configure(state="disabled")
        self.has_transcript = True
        self.show_status("Transcript fetched successfully!", "success")

    # ------------------------------------------------------------------
    # Saving
    # ------------------------------------------------------------------

    def save_transcript(self):
        if not self.has_transcript:
            self.show_status("No transcript to save", "warning")
            return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )

        if file_path:
            try:
                content = self.transcript_text.get("1.0", tk.END).rstrip()
                with open(file_path, "w", encoding="utf-8") as file:
                    file.write(content + "\n")
                self.show_status(f"Saved transcript to {file_path}", "success")
            except Exception as error:
                self.show_status(f"Error saving file: {error}", "danger")

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def select_all(self, _event=None):
        """Select all text in the transcript area."""
        self.transcript_text.tag_add(tk.SEL, "1.0", tk.END)
        self.transcript_text.mark_set(tk.INSERT, "1.0")
        self.transcript_text.see(tk.INSERT)
        return "break"

    def _on_window_resize(self, event):
        """Keep the status label wrapping nicely when the window resizes."""
        if event.widget == self.root:
            width = self.bottom_frame.winfo_width() - self.save_btn.winfo_width() - 40
            self.status_label.configure(wraplength=max(width, 200))

    def show_status(self, message, style="primary"):
        """Show a status message with the given color style."""
        self.status_label.config(text=message, style=f"{style}.TLabel")


if __name__ == "__main__":
    root = ttk.Window(themename="darkly")
    app = TranscriptApp(root)
    root.mainloop()
