"""Application log file: rotating handler setup and a parser for the log viewer."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FILE = Path("netmate.log")
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(threadName)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5

# Matches LOG_FORMAT, and the legacy "<asctime> <LEVEL>: <message>" format.
_RECORD = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?:,\d+)?\s+"
    r"(?:"
    r"\|\s*(?P<level>[A-Z]+)\s*\|\s*(?P<logger>[^|]*?)\s*\|\s*(?P<thread>[^|]*?)\s*\|\s?"
    r"|(?P<legacy_level>[A-Z]+):\s?"
    r")"
    r"(?P<message>.*)$"
)


@dataclass
class LogRecordRow:
    timestamp: str
    level: str
    logger: str
    thread: str
    message: str


class _NetmateFileHandler(RotatingFileHandler):
    """Marker subclass so configure_logging() can detect it already ran."""


def configure_logging(path: Path = LOG_FILE, level: int = logging.INFO) -> None:
    """Send all `netmate.*` logs to a size-rotated file. Safe to call more than once."""
    root = logging.getLogger("netmate")
    if any(isinstance(h, _NetmateFileHandler) for h in root.handlers):
        return
    handler = _NetmateFileHandler(
        path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
    root.addHandler(handler)
    root.setLevel(level)
    # Netmiko/Paramiko warnings (host keys, channel errors) are useful context.
    for name in ("netmiko", "paramiko"):
        lib = logging.getLogger(name)
        lib.addHandler(handler)
        lib.setLevel(logging.WARNING)


def parse_log(text: str) -> list[LogRecordRow]:
    """Split log text into records; continuation lines (tracebacks) join the previous one."""
    rows: list[LogRecordRow] = []
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        m = _RECORD.match(line)
        if m:
            rows.append(
                LogRecordRow(
                    timestamp=m["ts"],
                    level=m["level"] or m["legacy_level"],
                    logger=m["logger"] or "",
                    thread=m["thread"] or "",
                    message=m["message"],
                )
            )
        elif rows:
            rows[-1].message += "\n" + line
        else:
            rows.append(LogRecordRow("", "", "", "", line))
    return rows
