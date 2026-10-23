"""A minimal SSH server that behaves like a Cisco IOS CLI, for integration tests.

Netmiko talks to it over a real TCP socket with real SSH (Paramiko server side),
so connection setup, authentication, session preparation, prompt detection,
command echo and config mode are exercised exactly as against a device.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from types import TracebackType

import paramiko
from paramiko.common import (
    AUTH_FAILED,
    AUTH_SUCCESSFUL,
    OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED,
    OPEN_SUCCEEDED,
)

HOSTNAME = "R1"
USERNAME = "admin"
PASSWORD = "cisco123"  # fixture credential for the local test server

SHOW_OUTPUTS: dict[str, str] = {
    "show version": (
        "Cisco IOS XE Software, Version 17.09.04a\n"
        "R1 uptime is 41 weeks, 2 days, 3 hours, 7 minutes\n"
        'System image file is "bootflash:packages.conf"'
    ),
    "show ip interface brief": (
        "Interface              IP-Address      OK? Method Status                Protocol\n"
        "GigabitEthernet1       10.0.0.1        YES NVRAM  up                    up\n"
        "GigabitEthernet2       unassigned      YES unset  administratively down down"
    ),
}
INVALID_INPUT = "                 ^\n% Invalid input detected at '^' marker."
SESSION_SETUP = {"terminal length 0", "terminal width 511", "terminal no monitor"}


class _Auth(paramiko.ServerInterface):
    def __init__(self, authorized_keys: frozenset[str], allow_password: bool) -> None:
        self.authorized_keys = authorized_keys  # base64 public key blobs
        self.allow_password = allow_password

    def check_auth_password(self, username: str, password: str) -> int:
        if self.allow_password and username == USERNAME and password == PASSWORD:
            return AUTH_SUCCESSFUL
        return AUTH_FAILED

    def check_auth_publickey(self, username: str, key: paramiko.PKey) -> int:
        if username == USERNAME and key.get_base64() in self.authorized_keys:
            return AUTH_SUCCESSFUL
        return AUTH_FAILED

    def get_allowed_auths(self, username: str) -> str:
        methods = ["publickey"] if self.authorized_keys else []
        if self.allow_password:
            methods.append("password")
        return ",".join(methods)

    def check_channel_request(self, kind: str, chanid: int) -> int:
        if kind == "session":
            return OPEN_SUCCEEDED
        return OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_pty_request(  # noqa: PLR0917 - signature fixed by paramiko
        self,
        channel: paramiko.Channel,
        term: bytes,
        width: int,
        height: int,
        pixelwidth: int,
        pixelheight: int,
        modes: bytes,
    ) -> bool:
        return True

    def check_channel_shell_request(self, channel: paramiko.Channel) -> bool:
        return True


class _IosShell:
    def __init__(self, chan: paramiko.Channel, delay: Callable[[str], float]) -> None:
        self.chan = chan
        self.delay = delay
        self.config_mode = False
        self.config_lines: list[str] = []
        self._last_cr = False

    @property
    def prompt(self) -> str:
        return f"{HOSTNAME}(config)#" if self.config_mode else f"{HOSTNAME}#"

    def send(self, text: str) -> None:
        self.chan.sendall(text.replace("\n", "\r\n").encode())

    def run(self) -> None:
        self.send(f"\n{self.prompt}")
        buf = ""
        while True:
            data = self.chan.recv(1024)
            if not data:
                return
            for ch in data.decode(errors="replace"):
                if ch == "\n" and self._last_cr:  # "\r\n" is one line ending
                    self._last_cr = False
                    continue
                self._last_cr = ch == "\r"
                if ch in "\r\n":
                    self.send("\n")
                    self.handle(buf.strip())
                    buf = ""
                else:
                    buf += ch
                    self.send(ch)  # echo, as a terminal does

    def handle(self, line: str) -> None:
        pause = self.delay(line)
        if pause:
            time.sleep(pause)
        out = self.respond(line)
        self.send((out + "\n" if out else "") + self.prompt)

    def respond(self, line: str) -> str:
        if not line or line in SESSION_SETUP:
            return ""
        if self.config_mode:
            return self._config(line)
        if line in {"configure terminal", "conf t"}:
            self.config_mode = True
            return "Enter configuration commands, one per line.  End with CNTL/Z."
        return SHOW_OUTPUTS.get(line, INVALID_INPUT)

    def _config(self, line: str) -> str:
        if line in {"end", "exit"}:
            self.config_mode = False
            return ""
        if line.startswith(("interface ", "description ", "hostname ", "no ", "ip ")):
            self.config_lines.append(line)
            return ""
        return INVALID_INPUT


def _no_delay(_line: str) -> float:
    return 0.0


class FakeIosServer:
    """Listens on 127.0.0.1:<ephemeral>; each connection gets its own IOS shell."""

    def __init__(
        self,
        delay: Callable[[str], float] | None = None,
        *,
        authorized_keys: Iterable[str | Path] = (),
        allow_password: bool = True,
    ) -> None:
        """`authorized_keys` are public key files (OpenSSH .pub format) allowed to log in."""
        self.authorized_keys = frozenset(
            Path(p).read_text(encoding="utf-8").split()[1] for p in authorized_keys
        )
        self.allow_password = allow_password
        self.host_key = paramiko.RSAKey.generate(2048)
        self.delay: Callable[[str], float] = delay or _no_delay
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(100)
        self.port: int = self.sock.getsockname()[1]
        self.shells: list[_IosShell] = []
        self.connections = 0
        self._lock = threading.Lock()
        self._closing = threading.Event()
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)

    def __enter__(self) -> FakeIosServer:
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._closing.set()
        self.sock.close()

    def _accept_loop(self) -> None:
        while not self._closing.is_set():
            try:
                client, _ = self.sock.accept()
            except OSError:
                return
            with self._lock:
                self.connections += 1
            threading.Thread(target=self._serve, args=(client,), daemon=True).start()

    def _serve(self, client: socket.socket) -> None:
        transport = paramiko.Transport(client)
        transport.add_server_key(self.host_key)
        try:
            transport.start_server(server=_Auth(self.authorized_keys, self.allow_password))
            chan = transport.accept(20)
            if chan is None:
                return
            shell = _IosShell(chan, self.delay)
            with self._lock:
                self.shells.append(shell)
            shell.run()
        except (EOFError, OSError, paramiko.SSHException):
            pass  # client went away
        finally:
            transport.close()


def closed_port() -> int:
    """A localhost port with nothing listening (connection refused)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
