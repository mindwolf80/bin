"""GUI-independent Netmiko execution engine.

Runs commands against many devices in parallel and reports progress as
`Event` objects through a callback. The callback is invoked from worker
threads, so consumers (Qt, web, CLI) must marshal events to their own
thread if required.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, cast

from netmiko import BaseConnection, ConnectHandler
from netmiko.exceptions import (
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
)
from paramiko.ssh_exception import SSHException

logger = logging.getLogger("netmate.engine")

SETTINGS_FILE = Path("network_settings.json")
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

# Error markers per platform, matched per line (re.MULTILINE, case-insensitive).
_IOS_LIKE = r"^\s*%\s*(Invalid|Incomplete|Ambiguous|Unknown|Error|Bad)"
ERROR_PATTERNS: dict[str, str] = {
    "arista_eos": _IOS_LIKE,
    "cisco_ios": _IOS_LIKE,
    "cisco_xe": _IOS_LIKE,
    "cisco_nxos": _IOS_LIKE + r"|^\s*% Invalid command",
    "cisco_asa": _IOS_LIKE + r"|^\s*ERROR:",
    "cisco_ftd": _IOS_LIKE + r"|^\s*ERROR:",
    "cisco_apic": r"^\s*Error:|Invalid command",
    "juniper_junos": r"^\s*(syntax error|unknown command|error:)",
    "paloalto_panos": r"Invalid syntax|Unknown command|^\s*Server error",
    "fortinet": r"Command fail|Unknown action|command parse error",
    "f5_tmsh": r"Syntax Error|Data Input Error",
    "f5_ltm": r"Syntax Error|Data Input Error",
    "f5_linux": r"command not found|No such file or directory|Permission denied",
    "linux": r"command not found|No such file or directory|Permission denied",
}
DEFAULT_ERROR_PATTERN = "|".join(f"(?:{p})" for p in dict.fromkeys(ERROR_PATTERNS.values()))

# Platforms whose candidate configuration is discarded unless committed.
COMMIT_PLATFORMS = frozenset({"juniper_junos", "paloalto_panos", "cisco_xr"})

# Connection failures worth retrying. Authentication failures are not.
_RETRYABLE = (NetmikoTimeoutException, SSHException, OSError)

STOPPED_MESSAGE = "STOPPED: run stopped before completion"


def now() -> str:
    """Local wall-clock timestamp used on every event and result row."""
    return datetime.now().astimezone().strftime(TIMESTAMP_FORMAT)


@dataclass
class Settings:
    """Execution settings persisted to `network_settings.json`."""

    ssh_timeout: int = 3  # TCP/SSH connect timeout (s)
    conn_retry: int = 30  # retry budget (s); 1 attempt per 15 s
    cmd_timeout: int = 120  # per-command read timeout (s)
    auth_timeout: int = 30  # auth/banner timeout (s)
    max_threads: int = 10  # devices processed concurrently

    @property
    def connect_attempts(self) -> int:
        return max(1, self.conn_retry // 15)

    @classmethod
    def load(cls, path: Path | str = SETTINGS_FILE) -> Settings:
        """Load settings, keeping defaults for missing or invalid values."""
        settings = cls()
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return settings
        except (OSError, ValueError):
            logger.exception("Error loading network settings from %s", path)
            return settings
        if not isinstance(data, dict):
            return settings
        values = cast("dict[str, object]", data)
        for f in fields(settings):
            value = values.get(f.name)
            if isinstance(value, int) and not isinstance(value, bool):
                setattr(settings, f.name, value)
        return settings

    def save(self, path: Path | str = SETTINGS_FILE) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")


class EventKind(str, Enum):
    RUN_STARTED = "run_started"
    LOG = "log"  # informational progress message
    CONNECTED = "connected"
    COMMAND_OK = "command_ok"
    COMMAND_FAILED = "command_failed"
    DEVICE_FAILED = "device_failed"  # connection/auth/session failure
    DEVICE_DONE = "device_done"
    RUN_FINISHED = "run_finished"


@dataclass(frozen=True)
class Event:
    kind: EventKind
    host: str = ""
    username: str = ""
    command: str = ""
    output: str = ""
    message: str = ""
    steps: int = 0  # progress units this event completes
    ts: str = field(default_factory=now)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["kind"] = self.kind.value
        return d


class StoppedError(Exception):
    """Raised inside a device worker when the run is stopped."""


class Engine:
    """Executes commands on devices concurrently.

    Args:
        devices: Netmiko connection dicts (device_type, host, username, password, ...).
        commands: Commands to run on every device.
        on_event: Callback receiving every `Event`; called from worker threads.
        config_mode: Send commands as one configuration set per device.
        settings: Execution settings; loaded from disk if omitted.
    """

    def __init__(
        self,
        devices: list[dict[str, Any]],
        commands: list[str],
        on_event: Callable[[Event], None],
        config_mode: bool = False,
        settings: Settings | None = None,
    ) -> None:
        self.devices = devices
        self.commands = [c for c in commands if c.strip()]
        self.on_event = on_event
        self.config_mode = config_mode
        self.settings = settings or Settings.load()

        self._stop = threading.Event()
        self._resume = threading.Event()
        self._resume.set()

    # ----- control (thread-safe) -----

    @property
    def steps_per_device(self) -> int:
        return 1 if self.config_mode else len(self.commands)

    @property
    def total_steps(self) -> int:
        return len(self.devices) * self.steps_per_device

    @property
    def is_paused(self) -> bool:
        return not self._resume.is_set()

    def pause(self) -> None:
        if not self.is_paused:
            self._resume.clear()
            self._emit(EventKind.LOG, message="Execution paused")

    def resume(self) -> None:
        if self.is_paused:
            self._resume.set()
            self._emit(EventKind.LOG, message="Execution resumed")

    def stop(self) -> None:
        """Stop the run. In-flight commands abort at their next channel read."""
        self._stop.set()
        self._resume.set()

    # ----- execution -----

    def run(self) -> None:
        """Run to completion (blocking). Emits RUN_FINISHED exactly once."""
        if not self.devices:
            raise ValueError("No devices provided")
        if not self.commands:
            raise ValueError("No valid commands to execute")

        start = time.perf_counter()
        workers = max(1, min(self.settings.max_threads, len(self.devices)))
        self._emit(
            EventKind.RUN_STARTED,
            message=(
                f"Starting {len(self.devices)} devices, "
                f"{len(self.commands)} commands, {workers} concurrent"
            ),
        )
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="netmate") as pool:
            results = list(pool.map(self._run_device, self.devices))

        ok = sum(results)
        elapsed = time.perf_counter() - start
        state = "stopped" if self._stop.is_set() else "completed"
        message = f"Execution {state}: {ok}/{len(self.devices)} devices succeeded in {elapsed:.1f}s"
        logger.info(message)
        self._emit(EventKind.RUN_FINISHED, message=message)

    def _run_device(self, device: dict[str, Any]) -> bool:
        host: str = device["host"]
        username: str = device.get("username", "")
        done = 0  # progress steps already emitted for this device
        conn: BaseConnection | None = None
        # Set on any failure so the logout below skips talking to a broken session.
        abort = threading.Event()
        try:
            self._checkpoint()
            conn = self._connect(device, abort)
            self._emit(EventKind.CONNECTED, host, username, message=f"Connected to {host}")
            if self.config_mode:
                self._send_config(conn, device)
                done = 1
            else:
                for command in self.commands:
                    self._checkpoint()
                    self._send_command(conn, device, command)
                    done += 1
        except StoppedError:
            abort.set()
            message = STOPPED_MESSAGE
        except NetmikoAuthenticationException as e:
            message = f"AUTH ERROR: {e}"
        except Exception as e:
            abort.set()
            if self._stop.is_set():
                message = STOPPED_MESSAGE
            else:
                stage = "SESSION" if conn is not None else "CONNECTION"
                logger.exception("%s: %s failure", host, stage.lower())
                message = f"{stage} ERROR: {e}"
        else:
            self._emit(EventKind.DEVICE_DONE, host, username, message=f"Completed {host}")
            return True
        finally:
            if conn is not None:
                _disconnect(conn)

        logger.warning("%s: %s", host, message)
        self._emit(
            EventKind.DEVICE_FAILED,
            host,
            username,
            message=message,
            steps=self.steps_per_device - done,
        )
        return False

    def _connect(self, device: dict[str, Any], abort: threading.Event) -> BaseConnection:
        s = self.settings
        params = {
            **device,
            "conn_timeout": s.ssh_timeout,
            "auth_timeout": s.auth_timeout,
            "banner_timeout": s.auth_timeout,
            "timeout": s.auth_timeout,
        }
        host = device["host"]
        attempts = s.connect_attempts
        attempt = 1
        while True:
            self._checkpoint()
            self._emit(
                EventKind.LOG,
                host,
                device.get("username", ""),
                message=f"Connecting to {host} (attempt {attempt}/{attempts})",
            )
            try:
                return _guard_io(ConnectHandler(**params), self._stop, abort)
            except NetmikoAuthenticationException:
                raise  # subclasses SSHException; never retry bad credentials
            except _RETRYABLE as e:
                logger.warning("%s: attempt %d/%d failed: %s", host, attempt, attempts, e)
                if attempt >= attempts:
                    raise
                if self._stop.wait(min(2**attempt, 10)):
                    raise StoppedError from e
            attempt += 1

    def _send_command(self, conn: BaseConnection, device: dict[str, Any], command: str) -> None:
        host, username = device["host"], device.get("username", "")
        output = _as_text(
            conn.send_command(
                command,
                read_timeout=self.settings.cmd_timeout,
                strip_prompt=True,
                strip_command=True,
            )
        )
        kind = (
            EventKind.COMMAND_FAILED
            if self.has_error(output, device.get("device_type", ""))
            else EventKind.COMMAND_OK
        )
        self._emit(kind, host, username, command=command, output=output, steps=1)

    def _send_config(self, conn: BaseConnection, device: dict[str, Any]) -> None:
        host, username = device["host"], device.get("username", "")
        device_type: str = device.get("device_type", "")
        self._checkpoint()
        output = conn.send_config_set(
            self.commands,
            read_timeout=self.settings.cmd_timeout,
            cmd_verify=True,
            exit_config_mode=device_type not in COMMIT_PLATFORMS,
        )
        failed = self.has_error(output, device_type)
        if device_type in COMMIT_PLATFORMS:
            if failed:
                # Discard the rejected candidate instead of committing it.
                if device_type == "juniper_junos":
                    output += "\n" + conn.send_config_set(
                        ["rollback 0"],
                        enter_config_mode=False,
                        exit_config_mode=False,
                    )
            else:
                output += "\n" + conn.commit()
                failed = self.has_error(output, device_type)
            conn.exit_config_mode()
        self._emit(
            EventKind.COMMAND_FAILED if failed else EventKind.COMMAND_OK,
            host,
            username,
            command="CONFIG MODE",
            output=output,
            steps=1,
        )

    @staticmethod
    def has_error(output: str, device_type: str = "") -> bool:
        pattern = ERROR_PATTERNS.get(device_type, DEFAULT_ERROR_PATTERN)
        return bool(output) and bool(re.search(pattern, output, flags=re.MULTILINE | re.IGNORECASE))

    def _checkpoint(self) -> None:
        """Block while paused; raise if stopped."""
        self._resume.wait()
        if self._stop.is_set():
            raise StoppedError

    def _emit(self, kind: EventKind, host: str = "", username: str = "", **kw: Any) -> None:
        try:
            self.on_event(Event(kind, host, username, **kw))
        except Exception:
            logger.exception("Event handler failed")


def _as_text(output: object) -> str:
    """Netmiko returns parsed structures when TextFSM/TTP parsing is enabled."""
    if isinstance(output, str):
        return output
    return json.dumps(output, indent=2, default=str)


def _guard_io(conn: BaseConnection, *flags: threading.Event) -> BaseConnection:
    """Make the connection's channel I/O raise StoppedError once any flag is set.

    Netmiko waits for output by polling read_channel() until read_timeout, and
    netmiko connections are not thread-safe, so Stop cannot close them from the
    GUI thread. Guarding the instance's own reads and writes aborts a running
    command within one poll interval, on the worker thread that owns it.
    """
    read_channel, write_channel = conn.read_channel, conn.write_channel

    def guarded_read() -> str:
        if any(f.is_set() for f in flags):
            raise StoppedError
        return read_channel()

    def guarded_write(out_data: str) -> None:
        if any(f.is_set() for f in flags):
            raise StoppedError
        write_channel(out_data)

    conn.read_channel = guarded_read
    conn.write_channel = guarded_write
    return conn


def _disconnect(conn: BaseConnection) -> None:
    # After Stop or a failure the graceful logout is skipped (guarded I/O raises)
    # and the socket is closed; netmiko already swallows errors from its cleanup.
    with contextlib.suppress(Exception):
        conn.disconnect()
