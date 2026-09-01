"""Adaptador Qt para ejecutar una importación sin bloquear la interfaz."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QThread, Signal, Slot

from gtfs_explorer.application.commands.import_feed import ImportFeed, ImportFeedResult
from gtfs_explorer.application.jobs.import_job import CancelToken, ImportProgress


class _ImportWorker(QObject):
    """Construye y ejecuta el comando exclusivamente en el thread de trabajo."""

    started = Signal()
    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self, command_factory: Callable[[Callable[[ImportProgress], None]], ImportFeed]
    ) -> None:
        super().__init__()
        self._command_factory = command_factory
        self._token = CancelToken()
        self.result: ImportFeedResult | None = None
        self.error: str | None = None

    def cancel(self) -> None:
        """Solicita la cancelación cooperativa desde el hilo de interfaz."""
        self._token.cancel()

    @Slot()
    def run(self) -> None:
        self.started.emit()
        try:
            command = self._command_factory(self.progress.emit)
            self.result = command.execute(self._token)
            self.finished.emit(self.result)
        except Exception as error:
            self.error = str(error) or type(error).__name__
            self.failed.emit(self.error)


class ImportJobAdapter(QObject):
    """Propiedad de la UI para un único trabajo de importación activo."""

    started = Signal()
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
        worker.started.connect(self.started)
        worker.progress.connect(self.progress)
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

    @Slot()
    def _clear_finished_thread(self) -> None:
        worker = self._worker
        result = worker.result if worker is not None else None
        error = worker.error if worker is not None else None
        self._worker = None
        self._thread = None
        if result is not None:
            self.finished.emit(result)
        elif error is not None:
            self.failed.emit(error)
