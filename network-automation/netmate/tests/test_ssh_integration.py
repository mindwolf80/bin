"""Engine against real SSH sessions (local fake IOS server), no mocks of Netmiko."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest

from engine import Engine, Event, EventKind, Settings
from tests.fake_ios import PASSWORD, USERNAME, FakeIosServer, closed_port

pytestmark = pytest.mark.integration


@pytest.fixture
def server() -> Iterator[FakeIosServer]:
    with FakeIosServer() as srv:
        yield srv


def ios(port: int, n: int = 1, password: str = PASSWORD) -> list[dict[str, Any]]:
    return [
        {
            "device_type": "cisco_ios",
            "host": "127.0.0.1",
            "port": port,
            "username": USERNAME,
            "password": password,
        }
        for _ in range(n)
    ]


def run(
    devices: list[dict[str, Any]],
    commands: list[str],
    *,
    config_mode: bool = False,
    **settings: int,
) -> list[Event]:
    events: list[Event] = []
    lock = threading.Lock()

    def collect(event: Event) -> None:
        with lock:
            events.append(event)

    Engine(devices, commands, collect, config_mode, Settings(**settings)).run()
    return events


def of(events: list[Event], kind: EventKind) -> list[Event]:
    return [e for e in events if e.kind is kind]


def test_show_commands_and_rejected_command(server: FakeIosServer) -> None:
    events = run(ios(server.port), ["show version", "show ip interface brief", "show bogus"])
    ok = of(events, EventKind.COMMAND_OK)
    assert [e.command for e in ok] == ["show version", "show ip interface brief"]
    assert "R1 uptime is 41 weeks" in ok[0].output
    assert "GigabitEthernet1" in ok[1].output
    (failed,) = of(events, EventKind.COMMAND_FAILED)
    assert failed.command == "show bogus"
    assert "% Invalid input" in failed.output
    assert len(of(events, EventKind.DEVICE_DONE)) == 1
    assert sum(e.steps for e in events) == 3


def test_config_mode_applies_configuration(server: FakeIosServer) -> None:
    events = run(
        ios(server.port),
        ["interface GigabitEthernet2", "description uplink to core"],
        config_mode=True,
    )
    (ok,) = of(events, EventKind.COMMAND_OK)
    assert ok.command == "CONFIG MODE"
    assert server.shells[0].config_lines == [
        "interface GigabitEthernet2",
        "description uplink to core",
    ]
    assert not server.shells[0].config_mode  # left config mode with "end"


def test_rejected_config_line_is_reported(server: FakeIosServer) -> None:
    events = run(ios(server.port), ["interface Gi2", "bogus statement"], config_mode=True)
    (failed,) = of(events, EventKind.COMMAND_FAILED)
    assert "% Invalid input" in failed.output


def test_wrong_password_fails_once_without_retry(server: FakeIosServer) -> None:
    events = run(ios(server.port, password="wrong"), ["show version"], conn_retry=60)
    (failed,) = of(events, EventKind.DEVICE_FAILED)
    assert failed.message.startswith("AUTH ERROR")
    assert server.connections == 1  # no lockout-inducing retries
    assert failed.steps == 1


def test_connection_refused_is_reported() -> None:
    start = time.perf_counter()
    events = run(ios(closed_port()), ["show version"], conn_retry=15, ssh_timeout=2)
    (failed,) = of(events, EventKind.DEVICE_FAILED)
    assert failed.message.startswith("CONNECTION ERROR")
    assert time.perf_counter() - start < 10


def test_read_timeout_is_a_session_error() -> None:
    with FakeIosServer(delay=lambda line: 10.0 if line == "show version" else 0.0) as srv:
        start = time.perf_counter()
        events = run(ios(srv.port), ["show version", "show ip interface brief"], cmd_timeout=2)
        # The broken session is dropped, not politely logged out of (device is still busy).
        assert time.perf_counter() - start < 6
    (failed,) = of(events, EventKind.DEVICE_FAILED)
    assert failed.message.startswith("SESSION ERROR")
    assert failed.steps == 2  # remaining progress is still accounted for


def test_many_devices_run_concurrently(server: FakeIosServer) -> None:
    start = time.perf_counter()
    events = run(ios(server.port, n=20), ["show version", "show ip interface brief"])
    elapsed = time.perf_counter() - start
    assert len(of(events, EventKind.COMMAND_OK)) == 40
    assert len(of(events, EventKind.DEVICE_DONE)) == 20
    assert server.connections == 20
    assert elapsed < 30


def test_stop_interrupts_a_running_command() -> None:
    with FakeIosServer(delay=lambda line: 30.0 if line == "show version" else 0.0) as srv:
        events: list[Event] = []
        engine = Engine(ios(srv.port, n=3), ["show version"], events.append, settings=Settings())
        t = threading.Thread(target=engine.run)
        t.start()
        deadline = time.monotonic() + 15
        while len(of(events, EventKind.CONNECTED)) < 3 and time.monotonic() < deadline:
            time.sleep(0.05)
        time.sleep(0.3)  # let the command reach the device
        start = time.perf_counter()
        engine.stop()
        t.join(timeout=10)
        assert not t.is_alive()
        assert time.perf_counter() - start < 5
    failed = of(events, EventKind.DEVICE_FAILED)
    assert len(failed) == 3
    assert all(e.message.startswith("STOPPED") for e in failed)
    assert len(of(events, EventKind.RUN_FINISHED)) == 1
