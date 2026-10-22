"""Tabular views: live run output, results files and the application log."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import ClassVar, TypeVar

from PyQt6 import QtCore, QtGui, QtWidgets

from app_logging import parse_log
from engine import Event, EventKind, now

Qt = QtCore.Qt
DETAIL_ROLE = Qt.ItemDataRole.UserRole + 1
STATUS_ROLE = Qt.ItemDataRole.UserRole + 2


class Status(str, Enum):
    OK = "OK"
    FAILED = "FAILED"
    ERROR = "ERROR"
    STOPPED = "STOPPED"
    CONNECTED = "CONNECTED"
    DONE = "DONE"
    INFO = "INFO"
    WARNING = "WARNING"

    @property
    def is_problem(self) -> bool:
        return self in {Status.FAILED, Status.ERROR, Status.STOPPED, Status.WARNING}


STATUS_COLORS: dict[Status, str] = {
    Status.OK: "#22c55e",
    Status.DONE: "#22c55e",
    Status.FAILED: "#ef4444",
    Status.ERROR: "#ef4444",
    Status.STOPPED: "#f59e0b",
    Status.WARNING: "#f59e0b",
    Status.CONNECTED: "#60a5fa",
    Status.INFO: "#94a3b8",
}
PROBLEM_ROW_TINT = "#3b1f2a"

LOG_LEVEL_STATUS: dict[str, Status] = {
    "DEBUG": Status.INFO,
    "INFO": Status.INFO,
    "WARNING": Status.WARNING,
    "ERROR": Status.ERROR,
    "CRITICAL": Status.ERROR,
}


def status_for_event(event: Event) -> Status:
    match event.kind:
        case EventKind.COMMAND_OK:
            return Status.OK
        case EventKind.COMMAND_FAILED:
            return Status.FAILED
        case EventKind.DEVICE_FAILED:
            return Status.STOPPED if event.message.startswith("STOPPED") else Status.ERROR
        case EventKind.CONNECTED:
            return Status.CONNECTED
        case EventKind.DEVICE_DONE:
            return Status.DONE
        case _:
            return Status.INFO


def status_from_text(text: str) -> Status:
    try:
        return Status(text.strip().upper())
    except ValueError:
        return Status.INFO


@dataclass(frozen=True)
class ResultRow:
    """One command result, as shown in the table and exported to CSV/sessions."""

    timestamp: str
    status: str
    username: str
    host: str
    command: str
    output: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "timestamp",
        "status",
        "username",
        "host",
        "command",
        "output",
    )

    @classmethod
    def from_event(cls, event: Event) -> ResultRow:
        if event.kind is EventKind.DEVICE_FAILED:
            label, _, detail = event.message.partition(":")
            command, output = label.strip(), detail.strip() or event.message
        else:
            command, output = event.command, event.output
        return cls(
            timestamp=event.ts,
            status=status_for_event(event).value,
            username=event.username,
            host=event.host,
            command=command,
            output=output,
        )

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> ResultRow:
        values = {name: str(data.get(name) or "") for name in cls.FIELDS}
        if not values["status"]:
            # Results saved before the status column existed.
            output = values["output"]
            failed = output.startswith("ERROR") or "ERROR" in values["command"]
            values["status"] = (Status.FAILED if failed else Status.OK).value
        return cls(**values)

    def as_dict(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in self.FIELDS}


# --------------------------------------------------------------------------- filtering


class RowFilterProxy(QtCore.QSortFilterProxyModel):
    """Case-insensitive search across all columns plus a status filter."""

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._needle = ""
        self._allowed: frozenset[Status] | None = None

    def set_search(self, text: str) -> None:
        self._needle = text.casefold().strip()
        self.invalidateFilter()

    def set_allowed(self, allowed: frozenset[Status] | None) -> None:
        self._allowed = allowed
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QtCore.QModelIndex) -> bool:
        model = self.sourceModel()
        if model is None:
            return True
        first = model.index(source_row, 0, source_parent)
        if self._allowed is not None and first.data(STATUS_ROLE) not in self._allowed:
            return False
        if not self._needle:
            return True
        for col in range(model.columnCount(source_parent)):
            idx = model.index(source_row, col, source_parent)
            text = idx.data(DETAIL_ROLE) or idx.data(Qt.ItemDataRole.DisplayRole) or ""
            if self._needle in str(text).casefold():
                return True
        return False


# --------------------------------------------------------------------------- base panel


class TablePanel(QtWidgets.QWidget):
    """Searchable, filterable table with a monospace detail pane for the selected row.

    Subclasses define `COLUMNS`, `STATUS_COLUMN`, `DETAIL_COLUMN` and `FILTERS`
    (label -> allowed statuses, or None for everything).
    """

    COLUMNS: ClassVar[Sequence[str]] = ()
    STATUS_COLUMN = 1
    DETAIL_COLUMN = -1
    FILTERS: ClassVar[dict[str, frozenset[Status] | None]] = {}
    STRETCH_COLUMN = -1

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._follow_tail = True

        self.model = QtGui.QStandardItemModel(0, len(self.COLUMNS), self)
        self.model.setHorizontalHeaderLabels(list(self.COLUMNS))
        self.proxy = RowFilterProxy(self)
        self.proxy.setSourceModel(self.model)

        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Search…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.proxy.set_search)

        self.filter_box = QtWidgets.QComboBox()
        self.filter_box.addItems(list(self.FILTERS))
        self.filter_box.currentTextChanged.connect(self._apply_filter)

        self.summary = QtWidgets.QLabel()
        self.summary.setObjectName("table_summary")
        self.summary.setTextFormat(Qt.TextFormat.RichText)

        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(self.filter_box)
        toolbar.addWidget(self.summary)

        self.view = QtWidgets.QTableView()
        self.view.setObjectName("results_table")
        self.view.setModel(self.proxy)
        self.view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.view.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.view.setAlternatingRowColors(True)
        self.view.setWordWrap(False)
        self.view.setShowGrid(False)
        self.view.setSortingEnabled(True)
        self.view.setTextElideMode(Qt.TextElideMode.ElideRight)
        vertical = self.view.verticalHeader()
        if vertical is not None:
            vertical.setVisible(False)
            vertical.setDefaultSectionSize(30)
        header = _required(self.view.horizontalHeader())
        header.setHighlightSections(False)
        header.setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        header.setSortIndicatorShown(True)
        self.view.sortByColumn(-1, Qt.SortOrder.AscendingOrder)

        selection = _required(self.view.selectionModel())
        selection.currentRowChanged.connect(self._show_detail)
        scrollbar = _required(self.view.verticalScrollBar())
        scrollbar.valueChanged.connect(self._track_tail)

        self.detail = QtWidgets.QPlainTextEdit()
        self.detail.setObjectName("detail_pane")
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("Select a row to see its full output")
        self.detail.setFont(
            QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)
        )
        self.detail.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)

        splitter = QtWidgets.QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.view)
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setChildrenCollapsible(False)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(toolbar)
        layout.addWidget(splitter)

        self._update_summary()

    # ----- public API -----

    def clear(self) -> None:
        self.model.removeRows(0, self.model.rowCount())
        self.detail.clear()
        self._follow_tail = True
        self._update_summary()

    def add_row(self, values: Sequence[str], status: Status, detail: str = "") -> None:
        brush = QtGui.QBrush(QtGui.QColor(STATUS_COLORS[status]))
        tint = QtGui.QBrush(QtGui.QColor(PROBLEM_ROW_TINT)) if status.is_problem else None
        items: list[QtGui.QStandardItem] = []
        for col, value in enumerate(values):
            full = value if col != self.DETAIL_COLUMN else (detail or value)
            item = QtGui.QStandardItem(_first_line(value) if col == self.DETAIL_COLUMN else value)
            item.setData(full, DETAIL_ROLE)
            item.setToolTip(_tooltip(full))
            if col == self.STATUS_COLUMN:
                item.setForeground(brush)
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if tint is not None:
                item.setBackground(tint)
            items.append(item)
        items[0].setData(status, STATUS_ROLE)
        self.model.appendRow(items)
        self._update_summary()
        if self._follow_tail:
            self.view.scrollToBottom()

    def fit_columns(self) -> None:
        self.view.resizeColumnsToContents()
        header = _required(self.view.horizontalHeader())
        for col in range(self.model.columnCount()):
            header.resizeSection(col, min(header.sectionSize(col), 420))

    def statuses(self) -> Counter[Status]:
        counts: Counter[Status] = Counter()
        for row in range(self.model.rowCount()):
            item = self.model.item(row, 0)
            if item is not None:
                counts[item.data(STATUS_ROLE)] += 1
        return counts

    # ----- internals -----

    def _apply_filter(self, label: str) -> None:
        self.proxy.set_allowed(self.FILTERS.get(label))

    def _show_detail(self, current: QtCore.QModelIndex, _previous: QtCore.QModelIndex) -> None:
        if not current.isValid():
            self.detail.clear()
            return
        row = self.proxy.mapToSource(current).row()
        parts: list[str] = []
        for col, name in enumerate(self.COLUMNS):
            item = self.model.item(row, col)
            if item is not None and col != self.DETAIL_COLUMN:
                parts.append(f"{name}: {item.text()}")
        body_item = self.model.item(row, self.DETAIL_COLUMN % len(self.COLUMNS))
        body = body_item.data(DETAIL_ROLE) if body_item is not None else ""
        self.detail.setPlainText("   ".join(parts) + "\n" + "─" * 72 + "\n" + str(body))

    def _track_tail(self, value: int) -> None:
        scrollbar = self.view.verticalScrollBar()
        if scrollbar is not None:
            self._follow_tail = value >= scrollbar.maximum() - 2

    def _update_summary(self) -> None:
        counts = self.statuses()
        chips = [
            f'<span style="color:{STATUS_COLORS[s]}"><b>{n}</b> {s.value.lower()}</span>'
            for s, n in sorted(counts.items(), key=lambda kv: list(Status).index(kv[0]))
            if n and s is not Status.INFO
        ]
        self.summary.setText("&nbsp;&nbsp;".join(chips) or "<span>No rows</span>")


# --------------------------------------------------------------------------- run output


class OutputPanel(TablePanel):
    """Live table of a run: one row per command result and progress event."""

    COLUMNS: ClassVar[Sequence[str]] = ("Time", "Status", "Host", "User", "Command", "Output")
    STATUS_COLUMN = 1
    DETAIL_COLUMN = 5
    FILTERS: ClassVar[dict[str, frozenset[Status] | None]] = {
        "All events": None,
        "Command results": frozenset({Status.OK, Status.FAILED, Status.ERROR, Status.STOPPED}),
        "Problems only": frozenset({Status.FAILED, Status.ERROR, Status.STOPPED, Status.WARNING}),
        "Progress messages": frozenset({Status.INFO, Status.CONNECTED, Status.DONE}),
    }

    def add_event(self, event: Event) -> ResultRow | None:
        """Add a row for `event`; returns the result record for command/device outcomes."""
        status = status_for_event(event)
        if event.kind in (EventKind.COMMAND_OK, EventKind.COMMAND_FAILED, EventKind.DEVICE_FAILED):
            result = ResultRow.from_event(event)
            self.add_result(result)
            return result
        self.add_message(event.message, status, host=event.host, user=event.username, ts=event.ts)
        return None

    def add_result(self, result: ResultRow) -> None:
        output = result.output
        line_count = output.count("\n") + 1 if output else 0
        summary = _first_line(output)
        if line_count > 1:
            summary = f"{summary}  [+{line_count - 1} lines]"
        self.add_row(
            (
                result.timestamp,
                result.status,
                result.host,
                result.username,
                result.command,
                summary,
            ),
            status_from_text(result.status),
            detail=output,
        )

    def add_message(
        self,
        message: str,
        status: Status = Status.INFO,
        *,
        host: str = "",
        user: str = "",
        ts: str | None = None,
    ) -> None:
        self.add_row((ts or now(), status.value, host, user, "", message), status, detail=message)

    def load_results(self, results: Iterable[ResultRow]) -> None:
        self.clear()
        for result in results:
            self.add_result(result)
        self.fit_columns()


# --------------------------------------------------------------------------- log viewer


class LogViewerDialog(QtWidgets.QDialog):
    """Application log rendered as a table, with level filter and search."""

    def __init__(self, log_path: Path, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.log_path = log_path
        self.setWindowTitle("NetMate Log")
        self.resize(1100, 650)
        self.setMinimumSize(700, 400)
        self.setSizeGripEnabled(True)

        self.panel = _LogPanel(self)
        refresh = QtWidgets.QPushButton("Refresh")
        refresh.clicked.connect(self.reload)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.accept)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(refresh)
        buttons.addWidget(close)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.panel)
        layout.addLayout(buttons)
        self.reload()

    def reload(self) -> None:
        text = self.log_path.read_text(encoding="utf-8", errors="replace")
        self.panel.clear()
        for rec in parse_log(text):
            status = LOG_LEVEL_STATUS.get(rec.level, Status.INFO)
            self.panel.add_row(
                (rec.timestamp, rec.level or "-", rec.logger, rec.thread, rec.message),
                status,
                detail=rec.message,
            )
        self.panel.fit_columns()
        self.panel.view.scrollToBottom()


class _LogPanel(TablePanel):
    COLUMNS: ClassVar[Sequence[str]] = ("Time", "Level", "Source", "Thread", "Message")
    STATUS_COLUMN = 1
    DETAIL_COLUMN = 4
    FILTERS: ClassVar[dict[str, frozenset[Status] | None]] = {
        "All levels": None,
        "Warnings and errors": frozenset({Status.WARNING, Status.ERROR}),
        "Errors only": frozenset({Status.ERROR}),
    }


# --------------------------------------------------------------------------- helpers

_T = TypeVar("_T")


def _required(value: _T | None) -> _T:
    """Qt stubs mark child accessors Optional; they are always set on a live view."""
    if value is None:
        raise RuntimeError("Qt view is missing a required child object")
    return value


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _tooltip(text: str, max_lines: int = 25) -> str:
    lines = text.splitlines()
    if len(lines) > max_lines:
        lines = [*lines[:max_lines], f"… ({len(lines) - max_lines} more lines)"]
    return "\n".join(lines)
