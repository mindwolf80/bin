"""Engine unit tests with a fake Netmiko connection (fast, no sockets)."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, ClassVar

import pytest
from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException

import engine
from engine import Engine, Event, EventKind, Settings


class FakeConnection:
    """Stands in for a Netmiko connection; behaviour is driven by class attributes.

    Like Netmiko, a command waits for output by polling read_channel(), so the
    engine's stop guard applies to it exactly as it does to a real session.
    """

    delay: ClassVar[float] = 0.0
    outputs: ClassVar[dict[str, str]] = {}
    live: ClassVar[int] = 0
    peak: ClassVar[int] = 0
    lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self, **params: Any) -> None:
        self.params = params
        self.config_calls: list[tuple[list[str], dict[str, Any]]] = []
        self.committed = False
        self.disconnected = False

    def read_channel(self) -> str:
        return ""

    def write_channel(self, out_data: str) -> None:
        pass

    def send_command(self, command: str, **_kw: Any) -> str:
        with FakeConnection.lock:
            FakeConnection.live += 1
            FakeConnection.peak = max(FakeConnection.peak, FakeConnection.live)
        try:
            deadline = time.monotonic() + self.delay
            while time.monotonic() < deadline:
                self.read_channel()
                time.sleep(0.01)
            return self.outputs.get(command, f"output of {command}")
        finally:
            with FakeConnection.lock:
                FakeConnection.live -= 1

    def send_config_set(self, commands: list[str], **kw: Any) -> str:
        self.config_calls.append((list(commands), kw))
        return "\n".join(self.outputs.get(c, c) for c in commands)

    def commit(self) -> str:
        self.committed = True
        return "commit complete"

    def exit_config_mode(self) -> str:
        return ""

    def disconnect(self) -> None:
        self.disconnected = True


@pytest.fixture(autouse=True)
def fake_netmiko(monkeypatch: pytest.MonkeyPatch) -> list[FakeConnection]:
    FakeConnection.delay = 0.0
    FakeConnection.outputs = {}
    FakeConnection.live = FakeConnection.peak = 0
    created: list[FakeConnection] = []

    def factory(**params: Any) -> FakeConnection:
        conn = FakeConnection(**params)
        created.append(conn)
        return conn

    monkeypatch.setattr(engine, "ConnectHandler", factory)
    return created


def no_wait(self: threading.Event, timeout: float | None = None) -> bool:
    """Skip retry backoff sleeps."""
    return self.is_set()


def devices(n: int, device_type: str = "cisco_ios") -> list[dict[str, Any]]:
    return [
        {"device_type": device_type, "host": f"10.0.0.{i}", "username": "admin", "password": "x"}
        for i in range(n)
    ]


def run(
    devs: list[dict[str, Any]],
    commands: list[str],
    config_mode: bool = False,
    **settings: int,
) -> tuple[Engine, list[Event]]:
    events: list[Event] = []
    eng = Engine(devs, commands, events.append, config_mode, Settings(**settings))
    eng.run()
    return eng, events


def kinds(events: list[Event], kind: EventKind) -> list[Event]:
    return [e for e in events if e.kind is kind]


def test_devices_and_commands_run_concurrently() -> None:
    FakeConnection.delay = 0.2
    start = time.perf_counter()
    _, events = run(devices(10), ["show a", "show b"], max_threads=10)
    elapsed = time.perf_counter() - start
    assert FakeConnection.peak == 10
    assert elapsed < 1.5  # serial execution would take 4 s
    assert len(kinds(events, EventKind.COMMAND_OK)) == 20


def test_concurrency_is_bounded_by_max_threads() -> None:
    FakeConnection.delay = 0.05
    run(devices(12), ["show a"], max_threads=3)
    assert FakeConnection.peak == 3


def test_progress_steps_sum_to_total() -> None:
    eng, events = run(devices(4), ["a", "b", "c"])
    assert sum(e.steps for e in events) == eng.total_steps == 12
    assert len(kinds(events, EventKind.RUN_FINISHED)) == 1


def test_blank_commands_are_ignored() -> None:
    eng, _ = run(devices(1), ["show a", "  ", ""])
    assert eng.commands == ["show a"]


def test_empty_inputs_are_rejected() -> None:
    with pytest.raises(ValueError, match="No devices"):
        Engine([], ["a"], lambda _e: None, settings=Settings()).run()
    with pytest.raises(ValueError, match="No valid commands"):
        Engine(devices(1), [" "], lambda _e: None, settings=Settings()).run()


def test_invalid_command_is_reported_and_run_continues() -> None:
    FakeConnection.outputs = {"bad": "% Invalid input detected at '^' marker."}
    _, events = run(devices(1), ["bad", "good"])
    failed = kinds(events, EventKind.COMMAND_FAILED)
    assert [e.command for e in failed] == ["bad"]
    assert [e.command for e in kinds(events, EventKind.COMMAND_OK)] == ["good"]
    assert failed[0].username == "admin"


def test_parsed_output_is_rendered_as_text(monkeypatch: pytest.MonkeyPatch) -> None:
    def parsed(_self: FakeConnection, _command: str, **_kw: Any) -> list[dict[str, str]]:
        return [{"intf": "Gi1", "status": "up"}]

    monkeypatch.setattr(FakeConnection, "send_command", parsed)
    _, events = run(devices(1), ["show ip int brief"])
    (ok,) = kinds(events, EventKind.COMMAND_OK)
    assert '"intf": "Gi1"' in ok.output


@pytest.mark.parametrize(
    ("device_type", "output", "expected"),
    [
        ("cisco_ios", "% Invalid input detected", True),
        ("cisco_ios", "Interface   Status\n% of traffic", False),
        ("cisco_asa", "ERROR: % Invalid input detected", True),
        ("juniper_junos", "syntax error, expecting <command>.", True),
        ("paloalto_panos", "Invalid syntax.", True),
        ("fortinet", "Command fail. Return code -61", True),
        ("linux", "bash: foo: command not found", True),
        ("linux", "total 0", False),
        ("unknown_type", "% Ambiguous command", True),
        ("cisco_ios", "", False),
    ],
)
def test_error_detection(device_type: str, output: str, expected: bool) -> None:
    assert Engine.has_error(output, device_type) is expected


def test_auth_failure_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def factory(**params: Any) -> FakeConnection:
        calls.append(params)
        raise NetmikoAuthenticationException("bad password")

    monkeypatch.setattr(engine, "ConnectHandler", factory)
    _, events = run(devices(1), ["a", "b"], conn_retry=60)
    assert len(calls) == 1
    (failed,) = kinds(events, EventKind.DEVICE_FAILED)
    assert failed.message.startswith("AUTH ERROR")
    assert failed.steps == 2


def test_timeout_is_retried_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def factory(**params: Any) -> FakeConnection:
        calls.append(params)
        if len(calls) == 1:
            raise NetmikoTimeoutException("timed out")
        return FakeConnection(**params)

    monkeypatch.setattr(engine, "ConnectHandler", factory)
    monkeypatch.setattr(threading.Event, "wait", no_wait)
    _, events = run(devices(1), ["a"], conn_retry=30)
    assert len(calls) == 2
    assert len(kinds(events, EventKind.COMMAND_OK)) == 1


def test_retries_exhausted_reports_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def factory(**params: Any) -> FakeConnection:
        calls.append(params)
        raise NetmikoTimeoutException("timed out")

    monkeypatch.setattr(engine, "ConnectHandler", factory)
    monkeypatch.setattr(threading.Event, "wait", no_wait)
    _, events = run(devices(1), ["a"], conn_retry=45)
    assert len(calls) == 3
    (failed,) = kinds(events, EventKind.DEVICE_FAILED)
    assert failed.message.startswith("CONNECTION ERROR")


def test_connection_params_use_settings(fake_netmiko: list[FakeConnection]) -> None:
    run(devices(1), ["a"], ssh_timeout=4, auth_timeout=20)
    params = fake_netmiko[0].params
    assert params["conn_timeout"] == 4
    assert params["auth_timeout"] == 20
    assert "expect_string" not in params


def test_every_connection_is_disconnected(fake_netmiko: list[FakeConnection]) -> None:
    FakeConnection.outputs = {"bad": "% Invalid input"}
    run(devices(5), ["good", "bad"])
    assert len(fake_netmiko) == 5
    assert all(c.disconnected for c in fake_netmiko)


def test_config_mode_sends_single_set(fake_netmiko: list[FakeConnection]) -> None:
    eng, events = run(devices(2), ["interface x", "description y"], config_mode=True)
    for conn in fake_netmiko:
        ((cmds, kw),) = conn.config_calls
        assert cmds == ["interface x", "description y"]
        assert "expect_string" not in kw
        assert "error_pattern" not in kw
        assert not conn.committed
    assert sum(e.steps for e in events) == eng.total_steps == 2


def test_config_mode_commits_on_junos(fake_netmiko: list[FakeConnection]) -> None:
    run(devices(1, "juniper_junos"), ["set system host-name r1"], config_mode=True)
    assert fake_netmiko[0].committed


def test_config_mode_rolls_back_rejected_junos_config(
    fake_netmiko: list[FakeConnection],
) -> None:
    FakeConnection.outputs = {"set bogus": "syntax error."}
    _, events = run(devices(1, "juniper_junos"), ["set bogus"], config_mode=True)
    conn = fake_netmiko[0]
    assert not conn.committed
    assert conn.config_calls[-1][0] == ["rollback 0"]
    assert len(kinds(events, EventKind.COMMAND_FAILED)) == 1


def test_stop_interrupts_blocked_commands() -> None:
    FakeConnection.delay = 30
    events: list[Event] = []
    eng = Engine(devices(3), ["slow", "next"], events.append, settings=Settings())
    t = threading.Thread(target=eng.run)
    t.start()
    deadline = time.monotonic() + 5
    while FakeConnection.live < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    start = time.perf_counter()
    eng.stop()
    t.join(timeout=5)
    assert not t.is_alive()
    assert time.perf_counter() - start < 1
    failed = kinds(events, EventKind.DEVICE_FAILED)
    assert len(failed) == 3
    assert all(e.message.startswith("STOPPED") for e in failed)
    assert sum(e.steps for e in events) == eng.total_steps


def test_stop_before_start_runs_nothing(fake_netmiko: list[FakeConnection]) -> None:
    events: list[Event] = []
    eng = Engine(devices(4), ["a"], events.append, settings=Settings())
    eng.stop()
    eng.run()
    assert not fake_netmiko
    assert len(kinds(events, EventKind.DEVICE_FAILED)) == 4
    assert sum(e.steps for e in events) == eng.total_steps


def test_pause_blocks_until_resume() -> None:
    events: list[Event] = []
    eng = Engine(devices(1), ["a"], events.append, settings=Settings())
    eng.pause()
    assert eng.is_paused
    t = threading.Thread(target=eng.run)
    t.start()
    time.sleep(0.2)
    assert not kinds(events, EventKind.COMMAND_OK)
    eng.resume()
    t.join(timeout=5)
    assert len(kinds(events, EventKind.COMMAND_OK)) == 1


def test_failing_event_handler_does_not_break_run() -> None:
    seen: list[Event] = []

    def handler(event: Event) -> None:
        seen.append(event)
        raise RuntimeError("consumer bug")

    Engine(devices(2), ["a"], handler, settings=Settings()).run()
    assert any(e.kind is EventKind.RUN_FINISHED for e in seen)


def test_event_to_dict_is_json_friendly() -> None:
    d = Event(EventKind.COMMAND_OK, "h", "u", command="c").to_dict()
    assert d["kind"] == "command_ok"
    assert d["host"] == "h"


def test_settings_load_ignores_legacy_and_invalid_keys(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    path.write_text(
        '{"max_threads": 25, "batch_size": 5, "cmd_timeout": "bad", "ssh_timeout": true}'
    )
    s = Settings.load(path)
    assert s.max_threads == 25
    assert s.cmd_timeout == 120
    assert s.ssh_timeout == 3


@pytest.mark.parametrize("content", ["not json", "[1, 2]", ""])
def test_settings_load_survives_corrupt_file(tmp_path: Path, content: str) -> None:
    path = tmp_path / "s.json"
    path.write_text(content)
    assert Settings.load(path) == Settings()


def test_settings_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    Settings(max_threads=7, cmd_timeout=90).save(path)
    assert Settings.load(path) == Settings(max_threads=7, cmd_timeout=90)


def test_connect_attempts_from_retry_budget() -> None:
    assert Settings(conn_retry=5).connect_attempts == 1
    assert Settings(conn_retry=30).connect_attempts == 2
    assert Settings(conn_retry=60).connect_attempts == 4
