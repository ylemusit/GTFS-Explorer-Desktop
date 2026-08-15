"""Adaptador Qt para ejecutar una importación sin bloquear la interfaz."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QThread, Signal, Slot

from gtfs_explorer.application.commands.import_feed import ImportFeed, ImportFeedResult
from gtfs_explorer.application.jobs.import_job import CancelToken, ImportProgress


class _ImportWorker(QObject):
    """Construye y ejecuta el comando exclusivamente en el thread de trabajo."""

    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self, command_factory: Callable[[Callable[[ImportProgress], None]], ImportFeed]
    ) -> None:
        super().__init__()
        self._command_factory = command_factory
        self._token = CancelToken()

    def cancel(self) -> None:
        """Solicita la cancelación cooperativa desde el hilo de interfaz."""
        self._token.cancel()

    @Slot()
    def run(self) -> None:
        try:
            command = self._command_factory(self.progress.emit)
            self.finished.emit(command.execute(self._token))
        except Exception as error:
            self.failed.emit(str(error) or type(error).__name__)


class ImportJobAdapter(QObject):
    """Propiedad de la UI para un único trabajo de importación activo."""

    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: _ImportWorker | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None

    def start(
        self, command_factory: Callable[[Callable[[ImportProgress], None]], ImportFeed]
    ) -> None:
        if self.is_running:
            raise RuntimeError("Ya hay una importación en curso.")
        thread = QThread()
        worker = _ImportWorker(command_factory)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.progress)
        worker.finished.connect(self._complete)
        worker.failed.connect(self._fail)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_finished_thread)
        self._thread = thread
        self._worker = worker
        thread.start()

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def _complete(self, result: ImportFeedResult) -> None:
        self.finished.emit(result)

    def _fail(self, message: str) -> None:
        self.failed.emit(message)

    @Slot()
    def _clear_finished_thread(self) -> None:
        self._worker = None
        self._thread = None
