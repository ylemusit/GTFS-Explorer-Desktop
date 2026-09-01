"""Regresiones del cierre de hilos de importación."""

from __future__ import annotations

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from gtfs_explorer.presentation.desktop.import_adapter import ImportJobAdapter


def test_adapter_publishes_factory_error_after_worker_thread_finishes(
    application: QApplication,
) -> None:
    adapter = ImportJobAdapter()
    errors: list[str] = []
    loop = QEventLoop()
    adapter.failed.connect(lambda error: (errors.append(error), loop.quit()))
    QTimer.singleShot(5_000, loop.quit)

    def failing_factory(_on_progress: object) -> object:
        raise RuntimeError("specification unavailable")

    adapter.start(failing_factory)  # type: ignore[arg-type]
    loop.exec()

    assert errors == ["specification unavailable"]
    assert not adapter.is_running
