"""Shared pytest setup: headless Qt and test isolation."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

# Must be set before the first QApplication is created (pytest-qt creates it lazily).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def isolated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Settings, session and log files are relative to the working directory."""
    monkeypatch.chdir(tmp_path)
    yield tmp_path
