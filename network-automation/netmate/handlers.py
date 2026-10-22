"""Qt bridge for the execution engine (see engine.py)."""

from __future__ import annotations

import logging
from typing import Any

from PyQt6 import QtCore

from engine import Engine, Event, EventKind

logger = logging.getLogger("netmate.worker")


class NetmikoWorker(QtCore.QThread):
    """Runs an Engine on a background thread and re-emits its events as Qt signals."""

    event_received = QtCore.pyqtSignal(object)  # engine.Event
    progress_advanced = QtCore.pyqtSignal(int)  # completed progress steps

    def __init__(
        self,
        devices_info: list[dict[str, Any]],
        commands: list[str],
        is_config_mode: bool = False,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.engine = Engine(devices_info, commands, self._on_event, config_mode=is_config_mode)

    @property
    def total_steps(self) -> int:
        return self.engine.total_steps

    def run(self) -> None:
        try:
            self.engine.run()
        except Exception as e:
            logger.exception("Execution error")
            self.event_received.emit(
                Event(EventKind.DEVICE_FAILED, message=f"EXECUTION ERROR: {e}")
            )

    def _on_event(self, event: Event) -> None:
        # Called from engine worker threads; signal emission is thread-safe
        # and delivered to the GUI thread via queued connections.
        self.event_received.emit(event)
        if event.steps:
            self.progress_advanced.emit(event.steps)

    def pause(self) -> None:
        self.engine.pause()

    def resume(self) -> None:
        self.engine.resume()

    def stop(self) -> None:
        self.engine.stop()
