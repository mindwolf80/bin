import os
import sys
import threading
import time

import pytest
from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import engine  # noqa: E402
from engine import Engine, EventKind, Settings  # noqa: E402


class FakeConnection:
    """Stands in for a Netmiko connection; behaviour is driven by class attributes."""

    delay = 0.0
    outputs = {}
    live = 0
    peak = 0
    lock = threading.Lock()

    def __init__(self, **params):
        self.params = params
        self.closed = threading.Event()
        self.config_calls = []
        self.committed = False

    def send_command(self, command, **kw):
        with FakeConnection.lock:
            FakeConnection.live += 1
            FakeConnection.peak = max(FakeConnection.peak, FakeConnection.live)
        try:
            if self.closed.wait(self.delay):
                raise OSError("Socket is closed")
            return self.outputs.get(command, f"output of {command}")
        finally:
            with FakeConnection.lock:
                FakeConnection.live -= 1

    def send_config_set(self, commands, **kw):
        self.config_calls.append((list(commands), kw))
        return "\n".join(self.outputs.get(c, c) for c in commands)

    def commit(self):
        self.committed = True
        return "commit complete"

    def exit_config_mode(self):
        return ""

    def disconnect(self):
        self.closed.set()


@pytest.fixture(autouse=True)
def fake_netmiko(monkeypatch):
    FakeConnection.delay = 0.0
    FakeConnection.outputs = {}
    FakeConnection.live = FakeConnection.peak = 0
    created = []

    def factory(**params):
        conn = FakeConnection(**params)
        created.append(conn)
        return conn

    monkeypatch.setattr(engine, "ConnectHandler", factory)
    return created


def devices(n, device_type="cisco_ios"):
    return [
        {"device_type": device_type, "host": f"10.0.0.{i}", "username": "admin", "password": "x"}
        for i in range(n)
    ]


def run(devs, commands, config_mode=False, **settings):
    events = []
    eng = Engine(devs, commands, events.append, config_mode, Settings(**settings))
    eng.run()
    return eng, events


def kinds(events, kind):
    return [e for e in events if e.kind is kind]


def test_devices_and_commands_run_concurrently():
    FakeConnection.delay = 0.2
    start = time.perf_counter()
    eng, events = run(devices(10), ["show a", "show b"], max_threads=10)
    elapsed = time.perf_counter() - start
    assert FakeConnection.peak == 10
    assert elapsed < 1.0  # serial execution would take 4 s
    assert len(kinds(events, EventKind.COMMAND_OK)) == 20


def test_concurrency_is_bounded_by_max_threads():
    FakeConnection.delay = 0.05
    run(devices(12), ["show a"], max_threads=3)
    assert FakeConnection.peak == 3


def test_progress_steps_sum_to_total():
    eng, events = run(devices(4), ["a", "b", "c"])
    assert sum(e.steps for e in events) == eng.total_steps == 12
    assert len(kinds(events, EventKind.RUN_FINISHED)) == 1


def test_invalid_command_is_reported_and_run_continues():
    FakeConnection.outputs = {"bad": "% Invalid input detected at '^' marker."}
    _, events = run(devices(1), ["bad", "good"])
    failed = kinds(events, EventKind.COMMAND_FAILED)
    assert [e.command for e in failed] == ["bad"]
    assert [e.command for e in kinds(events, EventKind.COMMAND_OK)] == ["good"]
    assert failed[0].username == "admin"


@pytest.mark.parametrize(
    "device_type, output, expected",
    [
        ("cisco_ios", "% Invalid input detected", True),
        ("cisco_ios", "Interface   Status\n% of traffic", False),
        ("juniper_junos", "syntax error, expecting <command>.", True),
        ("paloalto_panos", "Invalid syntax.", True),
        ("linux", "bash: foo: command not found", True),
        ("linux", "total 0", False),
        ("unknown_type", "% Ambiguous command", True),
    ],
)
def test_error_detection(device_type, output, expected):
    assert Engine.has_error(output, device_type) is expected


def test_auth_failure_is_not_retried(monkeypatch):
    calls = []

    def factory(**params):
        calls.append(params)
        raise NetmikoAuthenticationException("bad password")

    monkeypatch.setattr(engine, "ConnectHandler", factory)
    eng, events = run(devices(1), ["a", "b"], conn_retry=60)
    assert len(calls) == 1
    (failed,) = kinds(events, EventKind.DEVICE_FAILED)
    assert failed.message.startswith("AUTH ERROR")
    assert failed.steps == 2


def test_timeout_is_retried_then_succeeds(monkeypatch):
    calls = []

    def factory(**params):
        calls.append(params)
        if len(calls) == 1:
            raise NetmikoTimeoutException("timed out")
        return FakeConnection(**params)

    monkeypatch.setattr(engine, "ConnectHandler", factory)
    monkeypatch.setattr(engine.threading.Event, "wait", lambda self, t=None: self.is_set())
    _, events = run(devices(1), ["a"], conn_retry=30)
    assert len(calls) == 2
    assert len(kinds(events, EventKind.COMMAND_OK)) == 1


def test_connection_params_use_settings(fake_netmiko):
    run(devices(1), ["a"], ssh_timeout=4, auth_timeout=20)
    params = fake_netmiko[0].params
    assert params["conn_timeout"] == 4
    assert params["auth_timeout"] == 20
    assert "expect_string" not in params


def test_config_mode_sends_single_set(fake_netmiko):
    eng, events = run(devices(2), ["interface x", "description y"], config_mode=True)
    for conn in fake_netmiko:
        (cmds, kw), = conn.config_calls
        assert cmds == ["interface x", "description y"]
        assert "expect_string" not in kw and "error_pattern" not in kw
        assert not conn.committed
    assert sum(e.steps for e in events) == eng.total_steps == 2


def test_config_mode_commits_on_junos(fake_netmiko):
    run(devices(1, "juniper_junos"), ["set system host-name r1"], config_mode=True)
    assert fake_netmiko[0].committed


def test_config_mode_rolls_back_rejected_junos_config(fake_netmiko):
    FakeConnection.outputs = {"set bogus": "syntax error."}
    _, events = run(devices(1, "juniper_junos"), ["set bogus"], config_mode=True)
    conn = fake_netmiko[0]
    assert not conn.committed
    assert conn.config_calls[-1][0] == ["rollback 0"]
    assert len(kinds(events, EventKind.COMMAND_FAILED)) == 1


def test_stop_interrupts_blocked_commands():
    FakeConnection.delay = 30
    events = []
    eng = Engine(devices(3), ["slow", "next"], events.append, settings=Settings())
    t = threading.Thread(target=eng.run)
    t.start()
    while FakeConnection.live < 3:
        time.sleep(0.01)
    eng.stop()
    t.join(timeout=5)
    assert not t.is_alive()
    failed = kinds(events, EventKind.DEVICE_FAILED)
    assert len(failed) == 3 and all(e.message.startswith("STOPPED") for e in failed)
    assert sum(e.steps for e in events) == eng.total_steps


def test_pause_blocks_until_resume():
    events = []
    eng = Engine(devices(1), ["a"], events.append, settings=Settings())
    eng.pause()
    t = threading.Thread(target=eng.run)
    t.start()
    time.sleep(0.2)
    assert not kinds(events, EventKind.COMMAND_OK)
    eng.resume()
    t.join(timeout=5)
    assert len(kinds(events, EventKind.COMMAND_OK)) == 1


def test_settings_load_ignores_legacy_keys(tmp_path):
    path = tmp_path / "s.json"
    path.write_text('{"max_threads": 25, "batch_size": 5, "cmd_timeout": "bad"}')
    s = Settings.load(str(path))
    assert s.max_threads == 25 and s.cmd_timeout == 120
