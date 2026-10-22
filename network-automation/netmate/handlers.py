# handlers.py
"""Qt bridge for the execution engine (see engine.py)."""
import logging

from PyQt6 import QtCore

from engine import Engine, Event, EventKind

# Configure logging
logging.basicConfig(
    filename="netmiko.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)
logger = logging.getLogger("netmate")


class NetmikoWorker(QtCore.QThread):
    """Runs an Engine on a background thread and re-emits its events as Qt signals."""

    output_ready = QtCore.pyqtSignal(str, str, str, str)  # username, host, command, output
    progress_update = QtCore.pyqtSignal(str)
    progress_advanced = QtCore.pyqtSignal(int)  # completed progress steps

    def __init__(self, devices_info, commands, is_config_mode=False):
        super().__init__()
        self.engine = Engine(
            devices_info, commands, self._on_event, config_mode=is_config_mode
        )

    @property
    def total_steps(self):
        return self.engine.total_steps

    def run(self):
        try:
            self.engine.run()
        except Exception as e:
            logger.error(f"Execution error: {e}")
            self.progress_update.emit(f"Execution error: {e}")

    def _on_event(self, event: Event):
        # Called from engine worker threads; signal emission is thread-safe
        # and delivered to the GUI thread via queued connections.
        kind = event.kind
        if kind in (EventKind.COMMAND_OK, EventKind.COMMAND_FAILED):
            output = event.output
            if kind is EventKind.COMMAND_FAILED:
                output = f"ERROR: command rejected by device\n{output}"
            self.output_ready.emit(event.username, event.host, event.command, output)
        elif kind is EventKind.DEVICE_FAILED:
            error_type = event.message.split(":", 1)[0]
            self.output_ready.emit(
                event.username, event.host, error_type, event.message
            )
        else:
            self.progress_update.emit(event.message)
        if event.steps:
            self.progress_advanced.emit(event.steps)

    @QtCore.pyqtSlot()
    def pause(self):
        self.engine.pause()

    @QtCore.pyqtSlot()
    def resume(self):
        self.engine.resume()

    def stop(self):
        self.engine.stop()
