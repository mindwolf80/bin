"""Tabular output, result records and log parsing (no devices needed)."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import pytest
from PyQt6 import QtCore, QtGui
from pytestqt.qtbot import QtBot

from app_logging import configure_logging, parse_log
from engine import Event, EventKind
from table_widgets import LogViewerDialog, OutputPanel, ResultRow, Status, status_for_event


def cell(model: QtGui.QStandardItemModel, row: int, col: int) -> str:
    item = model.item(row, col)
    assert item is not None
    return item.text()


def ok(output: str = "Version 1\nline 2") -> Event:
    return Event(EventKind.COMMAND_OK, "10.0.0.1", "admin", command="show ver", output=output)


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        (ok(), Status.OK),
        (Event(EventKind.COMMAND_FAILED, "h", output="% Invalid"), Status.FAILED),
        (Event(EventKind.DEVICE_FAILED, "h", message="AUTH ERROR: bad"), Status.ERROR),
        (Event(EventKind.DEVICE_FAILED, "h", message="STOPPED: run stopped"), Status.STOPPED),
        (Event(EventKind.CONNECTED, "h"), Status.CONNECTED),
        (Event(EventKind.DEVICE_DONE, "h"), Status.DONE),
        (Event(EventKind.LOG, message="x"), Status.INFO),
    ],
)
def test_status_for_event(event: Event, expected: Status) -> None:
    assert status_for_event(event) is expected


def test_device_failure_becomes_result_with_error_type_as_command() -> None:
    row = ResultRow.from_event(
        Event(EventKind.DEVICE_FAILED, "r1", "admin", message="CONNECTION ERROR: timed out")
    )
    assert (row.status, row.command, row.output) == ("ERROR", "CONNECTION ERROR", "timed out")


def test_legacy_results_without_status_column() -> None:
    legacy: dict[str, object] = {
        "timestamp": "t",
        "username": "u",
        "host": "h",
        "command": "c",
        "output": "x",
    }
    assert ResultRow.from_mapping(legacy).status == "OK"
    failed = {**legacy, "output": "ERROR: command rejected by device"}
    assert ResultRow.from_mapping(failed).status == "FAILED"


def test_output_panel_rows_filters_and_detail(qtbot: QtBot) -> None:
    panel = OutputPanel()
    qtbot.addWidget(panel)
    panel.add_event(Event(EventKind.CONNECTED, "10.0.0.1", "admin", message="Connected"))
    result = panel.add_event(ok())
    panel.add_event(Event(EventKind.COMMAND_FAILED, "10.0.0.2", "admin", command="bad", output="%"))

    assert result is not None
    assert result.status == "OK"
    assert panel.model.rowCount() == 3
    # Output column shows the first line plus a count; the full text is kept for the detail pane.
    assert cell(panel.model, 1, 5) == "Version 1  [+1 lines]"

    panel.filter_box.setCurrentText("Problems only")
    assert panel.proxy.rowCount() == 1
    panel.filter_box.setCurrentText("Command results")
    assert panel.proxy.rowCount() == 2
    panel.filter_box.setCurrentText("All events")
    panel.search.setText("10.0.0.2")
    assert panel.proxy.rowCount() == 1
    panel.search.setText("LINE 2")  # case-insensitive, matches hidden full output
    assert panel.proxy.rowCount() == 1

    panel.search.clear()
    panel.view.selectRow(1)
    assert "line 2" in panel.detail.toPlainText()
    assert panel.statuses()[Status.OK] == 1
    assert "1</b> ok" in panel.summary.text()

    panel.clear()
    assert panel.model.rowCount() == 0
    assert panel.detail.toPlainText() == ""


def test_sorting_by_host(qtbot: QtBot) -> None:
    panel = OutputPanel()
    qtbot.addWidget(panel)
    for host in ("10.0.0.3", "10.0.0.1", "10.0.0.2"):
        panel.add_result(ResultRow("t", "OK", "u", host, "c", "o"))
    panel.view.sortByColumn(2, QtCore.Qt.SortOrder.AscendingOrder)
    hosts = [panel.proxy.index(r, 2).data() for r in range(3)]
    assert hosts == ["10.0.0.1", "10.0.0.2", "10.0.0.3"]


def test_large_run_stays_responsive(qtbot: QtBot) -> None:
    panel = OutputPanel()
    qtbot.addWidget(panel)
    big_output = "\n".join(f"line {i}" for i in range(500))
    start = time.perf_counter()
    for i in range(2000):
        panel.add_result(
            ResultRow("t", "OK", "u", f"10.0.{i // 250}.{i % 250}", "show run", big_output)
        )
    elapsed = time.perf_counter() - start
    assert panel.model.rowCount() == 2000
    assert elapsed < 10


def test_parse_log_current_and_legacy_formats() -> None:
    text = (
        "2026-10-22 10:00:00 | INFO     | netmate.engine | netmate_0 | Execution completed\n"
        "2026-10-22 10:00:01 | ERROR    | netmate.engine | netmate_1 | r1: session failure\n"
        "Traceback (most recent call last):\n"
        "  OSError: Socket is closed\n"
        "2024-01-01 09:00:00,123 WARNING: legacy line\n"
        "# Log cleared on 2026-10-22\n"
        "\n"
    )
    rows = parse_log(text)
    assert [r.level for r in rows] == ["INFO", "ERROR", "WARNING"]
    assert rows[1].thread == "netmate_1"
    assert rows[1].message.endswith("OSError: Socket is closed")
    assert rows[2].message == "legacy line"


def test_parse_log_orphan_continuation_line() -> None:
    rows = parse_log("garbage without a timestamp\n")
    assert rows[0].message == "garbage without a timestamp"


def test_configured_log_round_trips_into_viewer(qtbot: QtBot, tmp_path: Path) -> None:
    log_path = tmp_path / "netmate.log"
    configure_logging(log_path)
    configure_logging(log_path)  # idempotent: no duplicate lines
    logging.getLogger("netmate.test").warning("device %s unreachable", "r9")
    for handler in logging.getLogger("netmate").handlers:
        handler.flush()
    assert log_path.read_text(encoding="utf-8").count("device r9 unreachable") == 1

    dialog = LogViewerDialog(log_path)
    qtbot.addWidget(dialog)
    model = dialog.panel.model
    last = model.rowCount() - 1
    assert cell(model, last, 1) == "WARNING"
    assert cell(model, last, 4) == "device r9 unreachable"
    dialog.panel.filter_box.setCurrentText("Errors only")
    assert dialog.panel.proxy.rowCount() == 0
