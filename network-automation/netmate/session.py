"""Session files: devices, commands, mode and results. Passwords are never stored."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from engine import now
from table_widgets import ResultRow


class SessionError(ValueError):
    """The file is not a valid NetMate session."""


@dataclass
class Session:
    username: str = ""
    device_type: str = ""
    devices: str = ""
    commands: str = ""
    is_config_mode: bool = False
    results: list[ResultRow] = field(default_factory=list[ResultRow])
    completed_commands: int = 0
    total_commands: int = 0
    timestamp: str = field(default_factory=now)

    def to_json(self) -> str:
        data = {
            "username": self.username,
            "device_type": self.device_type,
            "devices": self.devices,
            "commands": self.commands,
            "is_config_mode": self.is_config_mode,
            "results": [r.as_dict() for r in self.results],
            "completed_commands": self.completed_commands,
            "total_commands": self.total_commands,
            "timestamp": self.timestamp,
        }
        return json.dumps(data, indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> Session:
        try:
            raw: object = json.loads(text)
        except ValueError as e:
            raise SessionError(f"not valid JSON: {e}") from e
        if not isinstance(raw, dict):
            raise SessionError("session file must contain a JSON object")
        data = cast("dict[str, Any]", raw)

        raw_results: object = data.get("results", [])
        if not isinstance(raw_results, list):
            raise SessionError("'results' must be a list")
        results: list[ResultRow] = []
        for i, item in enumerate(cast("list[object]", raw_results)):
            if not isinstance(item, dict):
                raise SessionError(f"results[{i}] must be an object")
            results.append(ResultRow.from_mapping(cast("dict[str, object]", item)))

        return cls(
            username=_text(data, "username"),
            device_type=_text(data, "device_type"),
            devices=_text(data, "devices"),
            commands=_text(data, "commands"),
            is_config_mode=data.get("is_config_mode") is True,
            results=results,
            completed_commands=_count(data, "completed_commands"),
            total_commands=_count(data, "total_commands"),
            timestamp=_text(data, "timestamp") or "Unknown",
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Session:
        return cls.from_json(path.read_text(encoding="utf-8"))


def _text(data: dict[str, Any], key: str) -> str:
    value: object = data.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise SessionError(f"'{key}' must be text")
    return value


def _count(data: dict[str, Any], key: str) -> int:
    value: object = data.get(key, 0)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SessionError(f"'{key}' must be a non-negative integer")
    return value
