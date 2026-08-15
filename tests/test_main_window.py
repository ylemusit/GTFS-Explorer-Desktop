import os
import threading
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from gtfs_explorer.application.commands.import_feed import ImportFeed
from gtfs_explorer.application.ui_state import UiAction, UiMode
from gtfs_explorer.domain.project import JobState, ProjectMetadata, ProjectStatus
from gtfs_explorer.domain.source import InputSource, InputSourceKind
from gtfs_explorer.domain.spec import load_schedule_spec
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.presentation.desktop.exporter import ExportFormat, ExportRequest
from gtfs_explorer.presentation.desktop.main_window import MainWindow
from tests.test_import_feed import _command, _write_fixture


@pytest.fixture(autouse=True)
def _replace_web_map_in_main_window_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aísla los flujos de ventana de Chromium; las capas se prueban por separado."""

    class FakeMap(QWidget):
        def __init__(self, _layers: object, _stop_selected: object) -> None:
            super().__init__()

        def clear(self) -> None:
            pass

        def show_trip(self, _trip_id: str) -> None:
            pass

        def select_stop(self, _stop_id: str) -> None:
            pass

    monkeypatch.setattr("gtfs_explorer.presentation.desktop.routes.widget.MapWidget", FakeMap)


def test_main_window_smoke_reflects_actions_from_ui_state(application: QApplication) -> None:
    window = MainWindow()
    assert window.ui_state.mode is UiMode.NO_PROJECT
    assert window._actions[UiAction.NEW_PROJECT].isEnabled()
    assert window._actions[UiAction.OPEN_PROJECT].isEnabled()
    assert not window._actions[UiAction.IMPORT_FEED].isEnabled()

    window.project_opened()
    assert window._actions[UiAction.IMPORT_FEED].isEnabled()
    assert window.statusBar().currentMessage() == ""
    window.close()
    window.deleteLater()
    application.processEvents()


def test_main_window_exposes_keyboard_actions_and_accessible_navigation(
    application: QApplication,
) -> None:
    window = MainWindow()
    assert window._navigation.accessibleName() == "Navegación"
    assert window._status_label.accessibleName() == "Estado de la aplicación"
    assert window._progress_bar.accessibleName() == "Progreso de importación"
    assert (
        window._actions[UiAction.NEW_PROJECT].shortcut().matches(QKeySequence.StandardKey.New)
        == QKeySequence.SequenceMatch.ExactMatch
    )
    assert (
        window._actions[UiAction.OPEN_PROJECT].shortcut().matches(QKeySequence.StandardKey.Open)
        == QKeySequence.SequenceMatch.ExactMatch
    )
    assert window._actions[UiAction.IMPORT_FEED].shortcut().toString() == "Ctrl+I"
    assert (
        window._help_action.shortcut().matches(QKeySequence.StandardKey.HelpContents)
        == QKeySequence.SequenceMatch.ExactMatch
    )
    window.close()
    window.deleteLater()
    application.processEvents()


def test_explorer_uses_the_available_vertical_space(application: QApplication) -> None:
    window = MainWindow()
    window.resize(1200, 800)
    window.show()
    window._show_section(1)
    application.processEvents()

    assert window._explore_tabs.height() >= 600
    assert window._explorer._map is not None
    assert window._explorer._map.height() >= 200

    window.close()
    window.deleteLater()
    application.processEvents()


def test_closing_during_a_job_requests_cooperative_cancellation(application: QApplication) -> None:
    cancelled: list[bool] = []
    window = MainWindow(cancel_active_job=lambda: cancelled.append(True))
    window.project_opened()
    window.job_started()
    window.show()

    assert not window.close()
    assert cancelled == [True]
    assert window.ui_state.mode is UiMode.JOB_CANCELLING
    assert window.isVisible()

    window.job_finished()
    assert window.close()
    window.deleteLater()
    application.processEvents()


def _database(tmp_path: Path) -> ProjectDatabase:
    return ProjectDatabase(
        tmp_path / "project.duckdb",
        tmp_path / "temporary",
        settings=DatabaseSettings(memory_limit="128MB", max_temp_directory_size="128MB"),
    )


def _wait_for_import(window: MainWindow) -> list[object]:
    completed: list[object] = []
    loop = QEventLoop()
    window._import_adapter.finished.connect(lambda result: (completed.append(result), loop.quit()))
    window._import_adapter.failed.connect(lambda _: loop.quit())
    QTimer.singleShot(10_000, loop.quit)
    loop.exec()
    return completed


@pytest.mark.integration
def test_import_smoke_runs_fixture_in_worker_without_blocking_ui(
    application: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write_fixture(source)
    database = _database(tmp_path)
    factory_threads: list[int] = []
    ui_ticks: list[bool] = []

    def factory(input_source: InputSource, on_progress: object) -> ImportFeed:
        factory_threads.append(threading.get_ident())
        return ImportFeed(
            database,
            ProjectMetadata("project-1", "Demo", ProjectStatus.READY),
            input_source,
            load_schedule_spec(Path("schemas/gtfs_schedule/2026-04-27/spec.json")),
            job_id="job-1",
            feed_id="feed-1",
            on_progress=on_progress,  # type: ignore[arg-type]
        )

    monkeypatch.setattr(QMessageBox, "information", lambda *args: QMessageBox.StandardButton.Ok)
    window = MainWindow(import_command_factory=factory)
    window.project_opened()
    QTimer.singleShot(0, lambda: ui_ticks.append(True))
    window.start_import(InputSource(source, InputSourceKind.DIRECTORY))
    completed = _wait_for_import(window)

    assert ui_ticks == [True]
    assert factory_threads and factory_threads[0] != threading.get_ident()
    assert completed and completed[0].state is JobState.READY
    assert window.ui_state.mode is UiMode.PROJECT_READY
    window.close()
    window.deleteLater()
    application.processEvents()


@pytest.mark.integration
def test_import_cancellation_reaches_worker_and_returns_to_project(
    application: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write_fixture(source)
    database = _database(tmp_path)

    def factory(input_source: InputSource, on_progress: object) -> ImportFeed:
        return ImportFeed(
            database,
            ProjectMetadata("project-1", "Demo", ProjectStatus.READY),
            input_source,
            load_schedule_spec(Path("schemas/gtfs_schedule/2026-04-27/spec.json")),
            job_id="job-1",
            feed_id="feed-1",
            on_progress=on_progress,  # type: ignore[arg-type]
        )

    monkeypatch.setattr(QMessageBox, "information", lambda *args: QMessageBox.StandardButton.Ok)
    window = MainWindow(import_command_factory=factory)
    window.project_opened()
    window.start_import(InputSource(source, InputSourceKind.DIRECTORY))
    window._request_cancellation()
    completed = _wait_for_import(window)

    assert completed and completed[0].state is JobState.CANCELLED
    assert window.ui_state.mode is UiMode.PROJECT_READY
    assert not window._progress_bar.isVisible()
    window.close()
    window.deleteLater()
    application.processEvents()


@pytest.mark.integration
def test_export_feed_connects_every_format_to_the_imported_project(
    application: QApplication, tmp_path: Path
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write_fixture(source)
    database = _database(tmp_path)
    assert _command(database, source).execute().state is JobState.READY

    window = MainWindow()
    window._opened_project = SimpleNamespace(database=database)
    exports = (
        (ExportFormat.JSON, tmp_path / "feed.json", "derivada"),
        (ExportFormat.GEOJSON, tmp_path / "feed.geojson", "compatible"),
        (ExportFormat.CSV, tmp_path / "routes-faithful.csv", "compatible"),
        (ExportFormat.MINI_GTFS, tmp_path / "mini.zip", "oficial"),
    )
    for format_, destination, classification in exports:
        result = window._export_feed(
            ExportRequest(format_, destination, route_ids=frozenset({"R1"})), lambda: False
        )
        assert result.classification == classification
        assert destination.is_file()
        assert result.manifest.artifact_name == destination.name

    window._opened_project = None
    window.close()
    window.deleteLater()
    application.processEvents()
