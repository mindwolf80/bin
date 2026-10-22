# engine.py
"""GUI-independent Netmiko execution engine.

Runs commands against many devices in parallel and reports progress as
`Event` objects through a callback. The callback is invoked from worker
threads, so consumers (Qt, web, CLI) must marshal events to their own
thread if required.
"""
import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Dict, List, Optional

from netmiko import ConnectHandler
from netmiko.exceptions import (
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
)
from paramiko.ssh_exception import SSHException

logger = logging.getLogger("netmate.engine")

SETTINGS_FILE = "network_settings.json"

# Error markers per platform, matched per line (re.MULTILINE, case-insensitive).
_IOS_LIKE = r"^\s*%\s*(Invalid|Incomplete|Ambiguous|Unknown|Error|Bad)"
ERROR_PATTERNS: Dict[str, str] = {
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
DEFAULT_ERROR_PATTERN = "|".join(
    f"(?:{p})" for p in dict.fromkeys(ERROR_PATTERNS.values())
)

# Platforms whose candidate configuration is discarded unless committed.
COMMIT_PLATFORMS = {"juniper_junos", "paloalto_panos", "cisco_xr"}

# Connection failures worth retrying. Authentication failures are not.
_RETRYABLE = (NetmikoTimeoutException, SSHException, OSError)


@dataclass
class Settings:
    ssh_timeout: int = 3       # TCP/SSH connect timeout (s)
    conn_retry: int = 30       # retry budget (s); 1 attempt per 15 s
    cmd_timeout: int = 120     # per-command read timeout (s)
    auth_timeout: int = 30     # auth/banner timeout (s)
    max_threads: int = 10      # devices processed concurrently

    @property
    def connect_attempts(self) -> int:
        return max(1, self.conn_retry // 15)

    @classmethod
    def load(cls, path: str = SETTINGS_FILE) -> "Settings":
        settings = cls()
        try:
            if os.path.exists(path):
                with open(path, "r") as f:
                    data = json.load(f)
                for name in asdict(settings):
                    if isinstance(data.get(name), int):
                        setattr(settings, name, data[name])
        except Exception as e:
            logger.error(f"Error loading network settings: {e}")
        return settings


class EventKind(str, Enum):
    RUN_STARTED = "run_started"
    LOG = "log"                    # informational progress message
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
    ts: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["kind"] = self.kind.value
        return d


class Stopped(Exception):
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
        devices: List[dict],
        commands: List[str],
        on_event: Callable[[Event], None],
        config_mode: bool = False,
        settings: Optional[Settings] = None,
    ):
        self.devices = devices
        self.commands = [c for c in commands if isinstance(c, str) and c.strip()]
        self.on_event = on_event
        self.config_mode = config_mode
        self.settings = settings or Settings.load()

        self._stop = threading.Event()
        self._resume = threading.Event()
        self._resume.set()
        self._active: Dict[int, object] = {}
        self._active_lock = threading.Lock()

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
        """Stop the run and drop open sessions to unblock pending reads."""
        self._stop.set()
        self._resume.set()
        with self._active_lock:
            connections = list(self._active.values())
        for conn in connections:
            try:
                conn.disconnect()
            except Exception:
                pass

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
        results = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(self._run_device, d) for d in self.devices]
            for f in futures:
                results.append(f.result())

        ok = sum(1 for r in results if r)
        elapsed = time.perf_counter() - start
        state = "stopped" if self._stop.is_set() else "completed"
        message = (
            f"Execution {state}: {ok}/{len(self.devices)} devices succeeded "
            f"in {elapsed:.1f}s"
        )
        logger.info(message)
        self._emit(EventKind.RUN_FINISHED, message=message)

    def _run_device(self, device: dict) -> bool:
        host = device["host"]
        username = device.get("username", "")
        done = 0  # progress steps already emitted for this device

        def fail(message: str) -> bool:
            self._emit(
                EventKind.DEVICE_FAILED, host, username, message=message,
                steps=self.steps_per_device - done,
            )
            return False

        try:
            self._checkpoint()
            conn = self._connect(device)
        except Stopped:
            return fail("STOPPED: run stopped before completion")
        except NetmikoAuthenticationException as e:
            return fail(f"AUTH ERROR: {e}")
        except Exception as e:
            return fail(f"CONNECTION ERROR: {e}")

        key = id(conn)
        with self._active_lock:
            self._active[key] = conn
        try:
            self._emit(EventKind.CONNECTED, host, username, message=f"Connected to {host}")
            if self.config_mode:
                self._send_config(conn, device)
                done = 1
            else:
                for command in self.commands:
                    self._checkpoint()
                    self._send_command(conn, device, command)
                    done += 1
        except Stopped:
            return fail("STOPPED: run stopped before completion")
        except Exception as e:
            if self._stop.is_set():
                return fail("STOPPED: run stopped before completion")
            return fail(f"SESSION ERROR: {e}")
        finally:
            with self._active_lock:
                self._active.pop(key, None)
            try:
                conn.disconnect()
            except Exception:
                pass

        self._emit(EventKind.DEVICE_DONE, host, username, message=f"Completed {host}")
        return True

    def _connect(self, device: dict):
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
        for attempt in range(1, attempts + 1):
            self._checkpoint()
            try:
                self._emit(
                    EventKind.LOG, host, device.get("username", ""),
                    message=f"Connecting to {host} (attempt {attempt}/{attempts})",
                )
                return ConnectHandler(**params)
            except NetmikoAuthenticationException:
                raise  # subclasses SSHException; never retry bad credentials
            except _RETRYABLE as e:
                logger.warning(f"{host}: attempt {attempt}/{attempts} failed: {e}")
                if attempt == attempts:
                    raise
                if self._stop.wait(min(2 ** attempt, 10)):
                    raise Stopped()

    def _send_command(self, conn, device: dict, command: str) -> None:
        host, username = device["host"], device.get("username", "")
        output = conn.send_command(
            command,
            read_timeout=self.settings.cmd_timeout,
            strip_prompt=True,
            strip_command=True,
        )
        kind = (
            EventKind.COMMAND_FAILED
            if self.has_error(output, device.get("device_type", ""))
            else EventKind.COMMAND_OK
        )
        self._emit(kind, host, username, command=command, output=output, steps=1)

    def _send_config(self, conn, device: dict) -> None:
        host, username = device["host"], device.get("username", "")
        device_type = device.get("device_type", "")
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
            host, username, command="CONFIG MODE", output=output, steps=1,
        )

    @staticmethod
    def has_error(output: str, device_type: str = "") -> bool:
        pattern = ERROR_PATTERNS.get(device_type, DEFAULT_ERROR_PATTERN)
        return bool(output) and bool(
            re.search(pattern, output, flags=re.MULTILINE | re.IGNORECASE)
        )

    def _checkpoint(self) -> None:
        """Block while paused; raise if stopped."""
        self._resume.wait()
        if self._stop.is_set():
            raise Stopped()

    def _emit(self, kind: EventKind, host: str = "", username: str = "", **kw) -> None:
        try:
            self.on_event(Event(kind, host, username, **kw))
        except Exception as e:
            logger.error(f"Event handler failed: {e}")
