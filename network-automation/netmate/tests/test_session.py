"""Session file round-trip and validation."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from session import Session, SessionError
from table_widgets import ResultRow


def sample() -> Session:
    return Session(
        username="netops",
        device_type="cisco_ios",
        devices="10.0.0.1\n10.0.0.2",
        commands="show version",
        is_config_mode=True,
        results=[ResultRow("t", "OK", "netops", "10.0.0.1", "show version", "IOS XE\nline 2")],
        completed_commands=2,
        total_commands=2,
    )


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "s.json"
    original = sample()
    original.save(path)
    assert Session.load(path) == original


def test_password_is_never_written() -> None:
    assert "password" not in json.loads(sample().to_json())


def test_unicode_output_survives(tmp_path: Path) -> None:
    s = sample()
    s.results = [ResultRow("t", "OK", "u", "h", "c", "Ünïcødé ✓ 日本")]
    s.save(tmp_path / "s.json")
    assert Session.load(tmp_path / "s.json").results[0].output == "Ünïcødé ✓ 日本"


def test_legacy_session_with_output_and_password_keys() -> None:
    legacy = {
        "username": "u",
        "password": "secret",
        "output": "[ts] plain text log",
        "results": [
            {"timestamp": "t", "username": "u", "host": "h", "command": "c", "output": "x"}
        ],
    }
    s = Session.from_json(json.dumps(legacy))
    assert s.username == "u"
    assert s.results[0].status == "OK"
    assert s.timestamp == "Unknown"


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("not json", "not valid JSON"),
        ("[]", "JSON object"),
        ('{"results": {}}', "'results' must be a list"),
        ('{"results": ["x"]}', "results[0] must be an object"),
        ('{"total_commands": "abc"}', "'total_commands'"),
        ('{"completed_commands": -1}', "'completed_commands'"),
        ('{"completed_commands": true}', "'completed_commands'"),
        ('{"username": 42}', "'username' must be text"),
    ],
)
def test_malformed_sessions_raise_session_error(content: str, message: str) -> None:
    with pytest.raises(SessionError, match=re.escape(message)):
        Session.from_json(content)
