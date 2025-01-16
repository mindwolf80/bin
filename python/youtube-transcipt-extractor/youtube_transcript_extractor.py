import tkinter as tk
from tkinter import filedialog
import re
import ttkbootstrap as ttk
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound
)


def format_timestamp(seconds):
    """Convert seconds to MM:SS format"""
    minutes = int(seconds // 60)
    remaining_seconds = int(seconds % 60)
    return f"{minutes:02d}:{remaining_seconds:02d}"


def format_transcript_text(transcript):
    """
    Format transcript entries into readable paragraphs.
    Combines consecutive entries that are part of the same sentence.
    """
    if not transcript:
        return "No transcript data available."
        
    formatted_text = []
    current_paragraph = []

    for entry in transcript:
        text = entry["text"].strip()
        timestamp = format_timestamp(entry["start"])

        # Check if current paragraph should end
        ends_sentence = (
            current_paragraph and
            any(current_paragraph[-1].endswith(p) for p in ".!?")
        )
        if ends_sentence:
            paragraph_text = " ".join(current_paragraph)
            formatted_text.append(f"[{timestamp}] {paragraph_text}")
            current_paragraph = [text]
        else:
            current_paragraph.append(text)

    # Add any remaining text
    if current_paragraph:
        paragraph_text = " ".join(current_paragraph)
        formatted_text.append(f"[{timestamp}] {paragraph_text}")

    return "\n\n".join(formatted_text)


def extract_video_id(url_or_id):
    """Extract video ID from various YouTube URL formats or return the ID"""
    if not url_or_id:
        return None
        
    # Common YouTube URL patterns
    patterns = [
        # Standard, embed, youtu.be URLs
        r'(?:v=|v/|embed/|youtu.be/)([a-zA-Z0-9_-]{11})',
        r'^[a-zA-Z0-9_-]{11}$'  # Direct video ID
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)
    
    return None


def get_youtube_transcript(video_id, output_file=None):
    """
    Fetches and saves a YouTube video transcript as a readable text file.

    Args:
        video_id (str): YouTube video ID
        output_file (str, optional): Path to save the transcript text file

    Returns:
        list: Dictionary list containing transcript data.
    """
    try:
        # Fetch the transcript
        transcript = YouTubeTranscriptApi.get_transcript(video_id)

        # Format the transcript
        formatted_transcript = format_transcript_text(transcript)

        # Print the transcript to the console
        print("Transcript retrieved successfully:")
        print(formatted_transcript)

        # Save to file if output_file is provided
        if output_file:
            with open(output_file, "w", encoding="utf-8") as file:
                file.write(formatted_transcript)
            print(f"\nTranscript saved to: {output_file}")

        return transcript
    except Exception as e:
        print(f"An error occurred: {e}")
        return None


class TranscriptApp:
    def __init__(self, root):
        self.root = root
        self.root.title("YouTube Transcript Fetcher")
        self.root.geometry("800x600")
        self.root.minsize(600, 400)  # Set minimum window size

        # Configure grid weights for main window
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        # Create main frame
        self.main_frame = ttk.Frame(root, padding="10")
        self.main_frame.grid(row=0, column=0, sticky="nsew")

        # Configure grid weights for main frame
        self.main_frame.grid_rowconfigure(1, weight=1)  # Transcript row
        self.main_frame.grid_columnconfigure(0, weight=1)

        # URL input frame with grid
        self.url_frame = ttk.Frame(self.main_frame)
        self.url_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.url_frame.grid_columnconfigure(1, weight=1)  # Entry expands

        # URL label
        self.url_label = ttk.Label(
            self.url_frame, text="YouTube URL:", width=12
        )
        self.url_label.grid(row=0, column=0, padx=(0, 5))

        # Entry with placeholder
        self.url_entry = ttk.Entry(self.url_frame)
        placeholder = (
            "Paste YouTube URL "
            "(e.g., youtube.com/watch?v=... or youtu.be/...)"
        )
        self.url_entry.insert(0, placeholder)
        
        def on_focus_in(e):
            if self.url_entry.get() == placeholder:
                self.url_entry.delete(0, tk.END)
                
        def on_focus_out(e):
            if not self.url_entry.get():
                self.url_entry.insert(0, placeholder)
                
        self.url_entry.bind("<FocusIn>", on_focus_in)
        self.url_entry.bind("<FocusOut>", on_focus_out)
        self.url_entry.grid(row=0, column=1, sticky="ew")
        self.url_entry.bind("<Return>", lambda e: self.fetch_transcript())

        # Fetch button
        self.fetch_btn = ttk.Button(
            self.url_frame,
            text="Fetch Transcript",
            command=self.fetch_transcript,
            style="primary.TButton",
        )
        self.fetch_btn.grid(row=0, column=2, padx=(5, 0))

        # Transcript display with grid
        self.transcript_frame = ttk.Frame(self.main_frame)
        self.transcript_frame.grid(row=1, column=0, sticky="nsew")
        self.transcript_frame.grid_rowconfigure(0, weight=1)
        self.transcript_frame.grid_columnconfigure(0, weight=1)

        # Text area
        self.transcript_text = tk.Text(
            self.transcript_frame, wrap=tk.WORD, font=("Segoe UI", 10)
        )
        help_text = (
            "Transcript will appear here with timestamps. "
            "Use Ctrl+A to select all, Ctrl+C to copy."
        )
        self.transcript_text.insert("1.0", help_text)
        self.transcript_text.configure(state="disabled")
        self.transcript_text.grid(row=0, column=0, sticky="nsew")
        
        # Bind keyboard shortcuts
        self.transcript_text.bind("<Control-a>", self.select_all)
        self.transcript_text.bind("<Control-A>", self.select_all)

        # Scrollbar
        self.scrollbar = ttk.Scrollbar(
            self.transcript_frame,
            orient=tk.VERTICAL,
            command=self.transcript_text.yview,
        )
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.transcript_text["yscrollcommand"] = self.scrollbar.set

        # Bottom frame for buttons and status
        self.bottom_frame = ttk.Frame(self.main_frame)
        self.bottom_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        # Status label column expands
        self.bottom_frame.grid_columnconfigure(1, weight=1)

        # Save button
        self.save_btn = ttk.Button(
            self.bottom_frame,
            text="Save Transcript (Ctrl+S)",
            command=self.save_transcript,
            style="secondary.TButton",
        )
        self.save_btn.grid(row=0, column=0)
        
        # Bind Ctrl+S to save
        self.root.bind("<Control-s>", lambda e: self.save_transcript())
        self.root.bind("<Control-S>", lambda e: self.save_transcript())

        # Status label
        self.status_label = ttk.Label(
            self.bottom_frame,
            text="",
            wraplength=0,  # Dynamic wraplength
        )
        self.status_label.grid(row=0, column=1, sticky="ew", padx=10)

        # Sizegrip
        self.sizegrip = ttk.Sizegrip(self.bottom_frame)
        self.sizegrip.grid(row=0, column=2, sticky="se")

        # Bind resize event to update status label wraplength
        self.root.bind("<Configure>", self._on_window_resize)
        
        # Initialize tooltips list for cleanup
        self.tooltips = []

    def fetch_transcript(self):
        input_text = self.url_entry.get().strip()
        if not input_text:
            self.show_status("Enter a YouTube URL or video ID", "danger")
            return
            
        video_id = extract_video_id(input_text)
        if not video_id:
            self.show_status(
                "Invalid YouTube URL or video ID format", 
                "danger"
            )
            return

        try:
            transcript = get_youtube_transcript(video_id)
            if not transcript:
                self.show_status(
                    "Failed to retrieve transcript data", 
                    "danger"
                )
                return
                
            formatted_transcript = format_transcript_text(transcript)
            self.transcript_text.configure(state="normal")
            self.transcript_text.delete(1.0, tk.END)
            self.transcript_text.insert(tk.END, formatted_transcript)
            self.transcript_text.configure(state="disabled")
            self.show_status("Transcript fetched successfully!", "success")

        except (TranscriptsDisabled, NoTranscriptFound) as e:
            self.show_status(
                f"Error: {str(e)}. Check if captions exist.",
                "danger"
            )
        except Exception as e:
            self.show_status(f"Error: {str(e)}", "danger")

    def save_transcript(self):
        transcript_text = self.transcript_text.get(1.0, tk.END).strip()
        placeholder = (
            "Transcript will appear here with timestamps. "
            "Use Ctrl+A to select all, Ctrl+C to copy."
        )
        if not transcript_text or transcript_text == placeholder:
            self.show_status("No transcript to save", "warning")
            return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )

        if file_path:
            try:
                self.transcript_text.configure(state="normal")
                with open(file_path, "w", encoding="utf-8") as file:
                    file.write(self.transcript_text.get(1.0, tk.END))
                self.transcript_text.configure(state="disabled")
                self.show_status(f"Saved transcript to {file_path}", "success")
            except Exception as e:
                self.show_status(f"Error saving file: {str(e)}", "danger")
    
    def select_all(self, event=None):
        """Select all text in transcript area"""
        self.transcript_text.tag_add(tk.SEL, "1.0", tk.END)
        self.transcript_text.mark_set(tk.INSERT, "1.0")
        self.transcript_text.see(tk.INSERT)
        return "break"  # Prevent default binding

    def _on_window_resize(self, event):
        """Update status label wraplength when window is resized"""
        if event.widget == self.root:
            width = (
                self.bottom_frame.winfo_width() - 
                self.save_btn.winfo_width() - 40
            )
            self.status_label.configure(wraplength=max(width, 200))

    def show_status(self, message, style="primary"):
        """Show status message with appropriate style"""
        self.status_label.config(text=message, style=f"{style}.TLabel")


if __name__ == "__main__":
    root = ttk.Window(themename="darkly")
    app = TranscriptApp(root)
    root.mainloop()
