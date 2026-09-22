import os
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QWidget,
)

import gtfs_explorer.presentation.desktop.main_window as main_window_module
from gtfs_explorer.application.commands.create_project import CreateProject
from gtfs_explorer.application.commands.import_feed import ImportFeed, ImportFeedResult
from gtfs_explorer.application.commands.open_project import OpenProject
from gtfs_explorer.application.jobs.import_job import ImportPhase, ImportProgress, ProgressMode
from gtfs_explorer.application.map_policy import MapMode
from gtfs_explorer.application.ui_state import UiAction, UiMode
from gtfs_explorer.domain.exporting import ExportError
from gtfs_explorer.domain.operations import (
    OperationDisplayStatus,
    OperationStatus,
    OperationType,
    display_status,
)
from gtfs_explorer.domain.ports import PageRequest
from gtfs_explorer.domain.project import (
    FeedMetadata,
    FeedStatus,
    JobState,
    ProjectMetadata,
    ProjectStatus,
)
from gtfs_explorer.domain.source import InputSource, InputSourceKind
from gtfs_explorer.domain.spec import load_schedule_spec
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.infrastructure.duckdb.repositories import DuckDbUnitOfWork
from gtfs_explorer.infrastructure.filesystem.project_descriptor import (
    ProjectDescriptor,
    save_project_descriptor,
)
from gtfs_explorer.infrastructure.logging import configure_logging
from gtfs_explorer.presentation.desktop.exporter import ExportFormat, ExportRequest
from gtfs_explorer.presentation.desktop.main_window import (
    MainWindow,
    _ValidationReportJob,
    _ValidationReportSignals,
    run_window,
)
from tests.test_import_feed import _command, _write_fixture


@pytest.fixture(autouse=True)
def _replace_web_map_in_main_window_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aísla los flujos de ventana de Chromium; las capas se prueban por separado."""

    class FakeMap(QWidget):
        def __init__(self, _layers: object, _stop_selected: object) -> None:
            super().__init__()
            self.mode = MapMode.AUTO
            self.status_text = "Mapa: no disponible · sin paquete local."

        def clear(self) -> None:
            pass

        def show_trip(self, _trip_id: str) -> None:
            pass

        def select_stop(self, _stop_id: str) -> None:
            pass

        def set_mode(self, mode: MapMode) -> str:
            self.mode = mode
            self.status_text = f"Mapa: {mode.value}."
            return self.status_text

    monkeypatch.setattr("gtfs_explorer.presentation.desktop.routes.widget.MapWidget", FakeMap)


def test_main_window_smoke_reflects_actions_from_ui_state(application: QApplication) -> None:
    window = MainWindow()
    assert not application.windowIcon().isNull()
    assert not window.windowIcon().isNull()
    assert window.ui_state.mode is UiMode.NO_PROJECT
    assert window._project_identity_label.text() == "Sin proyecto abierto"
    assert window._overview._project_name.text() == "Sin proyecto abierto"
    assert window._actions[UiAction.NEW_PROJECT].isEnabled()
    assert window._actions[UiAction.OPEN_PROJECT].isEnabled()
    assert not window._actions[UiAction.IMPORT_FEED].isEnabled()

    window.project_opened()
    assert window._actions[UiAction.IMPORT_FEED].isEnabled()
    assert window.statusBar().currentMessage() == ""
    window.close()
    window.deleteLater()
    application.processEvents()


def test_main_window_maximization_uses_work_area_and_can_be_restored(
    application: QApplication,
) -> None:
    window = MainWindow()
    window.showMaximized()
    application.processEvents()

    screen = window.screen()
    assert screen is not None
    available = screen.availableGeometry()
    assert window.isMaximized()
    assert window.geometry().bottom() <= available.bottom()

    window.showNormal()
    application.processEvents()
    assert not window.isMaximized()

    window.showMinimized()
    application.processEvents()
    assert window.isMinimized()
    window.showNormal()
    application.processEvents()
    assert not window.isMinimized()

    window.showMaximized()
    application.processEvents()
    assert window.isMaximized()
    window.close()
    application.processEvents()


@pytest.mark.parametrize("logical_size", [(1366, 768), (1600, 900), (1920, 1080)])
def test_maximized_page_switches_never_escape_available_geometry(
    application: QApplication, logical_size: tuple[int, int]
) -> None:
    """Las páginas no deben renegociar el tamaño de una ventana maximizada."""
    window = MainWindow()
    window.resize(*logical_size)
    window.showMaximized()
    application.processEvents()
    screen = window.screen()
    assert screen is not None
    available = screen.availableGeometry()
    initial_frame = window.frameGeometry()

    for row in (0, 1, 2, 3, 0, 1):
        window._navigation.setCurrentRow(row)
        application.processEvents()
        assert window.isMaximized()
        frame = window.frameGeometry()
        assert frame.left() >= available.left()
        assert frame.top() >= available.top()
        assert frame.right() <= available.right()
        assert frame.bottom() <= available.bottom()
        assert frame.size() == initial_frame.size()

    window.close()
    application.processEvents()


def test_run_window_requests_native_maximized_start(
    application: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[MainWindow] = []
    original_show_maximized = MainWindow.showMaximized

    def record_show_maximized(window: MainWindow) -> None:
        original_show_maximized(window)
        shown.append(window)

    monkeypatch.setattr(MainWindow, "showMaximized", record_show_maximized)
    monkeypatch.setattr(
        "gtfs_explorer.presentation.desktop.main_window.StartupIntroDialog.exec",
        lambda _dialog: 0,
    )
    monkeypatch.setattr(QApplication, "exec", lambda _application: 0)

    assert run_window() == 0
    assert shown
    assert shown[0].isMaximized()
    shown[0].close()
    application.processEvents()


def test_run_window_can_suppress_welcome_explicitly(
    application: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "gtfs_explorer.presentation.desktop.main_window.StartupIntroDialog",
        lambda: pytest.fail("No debe construirse la bienvenida"),
    )
    monkeypatch.setattr(QApplication, "exec", lambda _application: 0)

    assert run_window(show_welcome=False) == 0


def test_project_identity_tracks_open_close_switch_and_long_workspace(
    application: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_a_directory = tmp_path / ("workspace-a-" + ("x" * 80))
    project_b_directory = tmp_path / "workspace-b"
    project_a_directory.mkdir()
    project_b_directory.mkdir()
    project_a = CreateProject(project_a_directory).execute()
    project_a.close()
    project_b = CreateProject(project_b_directory).execute()
    project_b.close()

    window = MainWindow()
    window._opened_project = OpenProject(project_a_directory).execute()
    window.project_opened()
    assert window._project_identity_label.text().startswith("Proyecto: workspace-a-")
    assert "…" in window._project_identity_label.text()
    assert window._workspace_status_label.text().startswith("Workspace: …")
    assert window._overview._project_workspace.text() == str(project_a_directory)
    assert window._project_identity_label.toolTip() == window._opened_project.descriptor.name
    assert window._workspace_status_label.toolTip() == str(project_a_directory)

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(project_b_directory))
    window._choose_project()
    assert window._opened_project is not None
    assert window._overview._project_name.text() == window._opened_project.descriptor.name
    assert window._overview._project_workspace.text() == str(project_b_directory)
    assert str(project_a_directory) not in window._workspace_status_label.text()

    window._close_project()
    assert window._project_identity_label.text() == "Sin proyecto abierto"
    assert window._workspace_status_label.text() == ""
    assert window._overview._project_workspace.text() == "—"

    window._opened_project = OpenProject(project_a_directory).execute()
    window.project_opened()
    assert window._overview._project_name.text() == window._opened_project.descriptor.name
    assert window._overview._project_workspace.text() == str(project_a_directory)
    window._close_project()
    window.deleteLater()
    application.processEvents()


def test_map_mode_preference_survives_project_change_and_is_visible(
    application: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_a_directory = tmp_path / "workspace-a"
    project_b_directory = tmp_path / "workspace-b"
    project_a_directory.mkdir()
    project_b_directory.mkdir()
    project_a = CreateProject(project_a_directory).execute()
    project_a.close()
    project_b = CreateProject(project_b_directory).execute()
    project_b.close()

    window = MainWindow()
    window._opened_project = OpenProject(project_a_directory).execute()
    window.project_opened()
    window._map_mode_combo.setCurrentIndex(1)

    assert window._map_mode_combo.currentData() == MapMode.OFFLINE
    assert "offline" in window._map_policy_status.text()

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(project_b_directory))
    window._choose_project()

    assert window._map_mode_combo.currentData() == MapMode.OFFLINE
    assert window._explorer._map.mode is MapMode.OFFLINE
    assert "offline" in window._map_policy_status.text()
    window._close_project()
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


def test_status_bar_prioritizes_application_state_and_keeps_project_context_separate(
    application: QApplication,
) -> None:
    window = MainWindow()
    assert window._status_label.text() == "Sin proyecto"

    window.project_opened()
    assert window._status_label.text() == "Listo"
    window.job_started()
    assert window._status_label.text() == "Trabajo en curso…"
    window._state = window._state.cancellation_requested()
    window._apply_state()
    assert window._status_label.text() == "Cancelando…"
    window.job_finished()
    assert window._status_label.text() == "Listo"
    assert window._project_identity_label.text() == "Sin proyecto abierto"
    window.close()
    window.deleteLater()
    application.processEvents()


def test_status_bar_reserves_compact_workspace_at_supported_widths(
    application: QApplication,
) -> None:
    window = MainWindow()
    for width, height in ((1366, 768), (1600, 900), (1920, 1080)):
        window.resize(width, height)
        application.processEvents()
        assert window._workspace_status_label.width() <= 300
        assert window._status_label.width() > 0
    window.close()
    window.deleteLater()
    application.processEvents()


def test_reproduce_a3_contextual_validation_keeps_sidebar_navigable(
    application: QApplication, tmp_path: Path
) -> None:
    project_directory = tmp_path / "project"
    project_directory.mkdir()
    project = CreateProject(project_directory).execute()
    source = tmp_path / "source"
    source.mkdir()
    _write_fixture(source)
    assert _command(project.database, source).execute().state is JobState.READY
    window = MainWindow()
    window._opened_project = project
    window.project_opened()
    window.show()

    contextual = next(
        button
        for button in window._overview.findChildren(QPushButton)
        if button.text() == "Ver incidencias de validación"
    )
    contextual.click()
    application.processEvents()

    assert window._navigation.currentRow() == 2
    assert window._navigation.isEnabled()
    assert window.focusWidget() is window._navigation
    assert window._validation.isVisible()
    assert "Estado:" in window._validation._summary.text()
    for row in (0, 1, 3, 0, 2, 1, 2, 3, 2, 0):
        window._navigation.setCurrentRow(row)
        application.processEvents()
        assert window._navigation.currentRow() == row
        assert window._navigation.isEnabled()
        assert window._overview.isVisible() is (row == 0)
        assert window._explore_tabs.isVisible() is (row == 1)
        assert window._validation.isVisible() is (row == 2)
        assert window._exporter.isVisible() is (row == 3)

    window._close_project()
    window.deleteLater()
    application.processEvents()


def test_a3_sidebar_navigation_without_feed_remains_enabled(
    application: QApplication, tmp_path: Path
) -> None:
    project_directory = tmp_path / "project"
    project_directory.mkdir()
    project = CreateProject(project_directory).execute()
    window = MainWindow()
    window._opened_project = project
    window.project_opened()

    for row in (2, 0, 1, 3, 0):
        window._navigation.setCurrentRow(row)
        application.processEvents()
        assert window._navigation.isEnabled()
        assert window._navigation.currentRow() == row

    window._close_project()
    window.deleteLater()
    application.processEvents()


@pytest.mark.parametrize("logical_size", [(1366, 768), (1600, 900), (1920, 1080)])
def test_b3_primary_views_keep_essential_controls_inside_their_layout(
    application: QApplication, logical_size: tuple[int, int]
) -> None:
    window = MainWindow()
    window.resize(*logical_size)
    window.show()
    application.processEvents()

    window._settings_dock.show()
    application.processEvents()
    settings_scroll = window._settings_dock.findChild(QScrollArea, "settingsScrollArea")
    assert settings_scroll is not None
    assert settings_scroll.widgetResizable()
    assert settings_scroll.verticalScrollBarPolicy().value != 1  # ScrollBarAlwaysOff

    for row, view in (
        (0, window._overview),
        (1, window._explore_tabs),
        (2, window._validation),
        (3, window._exporter),
    ):
        window._navigation.setCurrentRow(row)
        application.processEvents()
        assert view.isVisible()
        assert view.width() > 0 and view.height() > 0
        inspected_view = view.currentWidget() if hasattr(view, "currentWidget") else view
        assert inspected_view is not None
        for control in inspected_view.findChildren(QPushButton):
            assert control.isVisible(), f"control inaccesible en {type(inspected_view).__name__}"

    # La vista de Validación conserva el acceso a todos sus filtros y acciones
    # aunque se reduzca el ancho lógico disponible (caso representativo de DPI).
    window._navigation.setCurrentRow(2)
    application.processEvents()
    validation = window._validation
    for control in (
        validation._severity,
        validation._category,
        validation._file_filter,
        validation._search,
        validation._previous,
        validation._next,
        validation._go_to_raw,
        validation._help,
        validation._export,
    ):
        assert control.isVisible()
        assert validation.rect().contains(control.geometry().center())

    window.close()
    application.processEvents()


def test_p1_02_import_context_shows_feed_phase_progress_and_elapsed(
    application: QApplication, tmp_path: Path
) -> None:
    clock = iter((100.0, 100.0, 112.9, 112.9))
    window = MainWindow(elapsed_clock=lambda: next(clock))
    window.project_opened()
    window.job_started()
    window._begin_import_context(InputSource(tmp_path / "new-feed.zip", InputSourceKind.ARCHIVE))

    assert "new-feed.zip" in window._import_context_label.text()
    assert not window._import_timer.isActive()

    window._import_job_started()
    window._show_import_progress(
        ImportProgress(ImportPhase.STAGING, completed_steps=1, total_steps=5)
    )
    window._update_import_elapsed()

    assert "Feed: new-feed.zip" in window._import_context_label.text()
    assert "Fase: Carga" in window._import_context_label.text()
    assert "Progreso: 20 %" in window._import_context_label.text()
    assert "Tiempo transcurrido: 00:12" in window._import_context_label.text()
    assert window._import_timer.isActive()
    window._clear_import_context()
    assert not window._import_timer.isActive()
    assert window._import_context_label.text() == ""
    window.job_finished()
    window.close()
    window.deleteLater()
    application.processEvents()


def test_p1_a2_immediate_feedback_and_duplicate_import_blocked(
    application: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = MainWindow()
    window.project_opened()
    started: list[bool] = []
    warnings: list[str] = []
    monkeypatch.setattr(window._import_adapter, "start", lambda _factory: started.append(True))
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, _title, message, *_args: warnings.append(message),
    )
    source_path = tmp_path / "ctm-mallorca-es.zip"
    with ZipFile(source_path, "w") as archive:
        archive.writestr("routes.txt", "route_id\nR1\n")

    window.start_import(InputSource(source_path, InputSourceKind.ARCHIVE))

    assert "Importando" in window._import_context_label.text()
    assert "ctm-mallorca-es.zip" in window._import_context_label.text()
    assert "Preparando importación…" in window._import_context_label.text()
    assert not window._actions[UiAction.IMPORT_FEED].isEnabled()
    assert window._actions[UiAction.CANCEL_JOB].isEnabled()
    assert started == [True]
    assert warnings == []
    window._clear_import_context()
    window.job_finished()
    window.close()
    window.deleteLater()
    application.processEvents()


def test_p1_a2_volume_warning_uses_cheap_zip_metadata(
    application: QApplication, tmp_path: Path
) -> None:
    archive_path = tmp_path / "large.zip"
    with ZipFile(archive_path, "w") as archive:
        for index in range(128):
            archive.writestr(f"file-{index}.txt", "x")
    source = InputSource(archive_path, InputSourceKind.ARCHIVE)
    assert MainWindow._is_high_volume_source(source)
    assert not MainWindow._is_high_volume_source(InputSource(tmp_path, InputSourceKind.DIRECTORY))


def test_p1_a2_terminal_feedback_includes_elapsed_state_and_issues(
    application: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    messages: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda _parent, _title, message, *_args: messages.append(message),
    )
    window = MainWindow(elapsed_clock=lambda: 125.0)
    window.project_opened()
    window.job_started()
    window._begin_import_context(InputSource(Path("feed.zip"), InputSourceKind.ARCHIVE))
    window._import_job_started()
    window._import_finished(ImportFeedResult("job", "feed", JobState.INVALID, 3))
    assert messages
    assert "Importación completada con incidencias" in messages[-1]
    assert "Duración: 00:00" in messages[-1]
    assert "Estado: INVALID" in messages[-1]
    assert "Incidencias: 3" in messages[-1]
    window.close()
    window.deleteLater()
    application.processEvents()


def test_p1_22_staging_context_is_indeterminate_and_shows_real_rows(
    application: QApplication, tmp_path: Path
) -> None:
    window = MainWindow()
    window.project_opened()
    window.job_started()
    window._begin_import_context(InputSource(tmp_path / "feed", InputSourceKind.DIRECTORY))
    window._import_job_started()
    window._show_import_progress(
        ImportProgress(
            ImportPhase.STAGING,
            completed_steps=1,
            total_steps=5,
            detail="stop_times.txt",
            completed=178250,
            unit="filas",
            mode=ProgressMode.INDETERMINATE,
        )
    )

    assert window._progress_bar.minimum() == 0
    assert window._progress_bar.maximum() == 0
    assert "Detalle: stop_times.txt" in window._import_context_label.text()
    assert "Actividad: 178.250 filas" in window._import_context_label.text()
    assert "%" not in window._import_context_label.text()
    window._clear_import_context()
    window.job_finished()
    window.close()
    window.deleteLater()
    application.processEvents()


def test_p1_02_cancellation_keeps_active_feed_until_worker_completion(
    application: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(QMessageBox, "information", lambda *args: QMessageBox.StandardButton.Ok)
    window = MainWindow()
    window.project_opened()
    window.job_started()
    window._begin_import_context(InputSource(tmp_path / "new.zip", InputSourceKind.ARCHIVE))
    window._import_job_started()

    window._request_cancellation()
    assert window.ui_state.mode is UiMode.JOB_CANCELLING
    assert "Cancelando…" in window._import_context_label.text()
    assert "Feed: new.zip" in window._import_context_label.text()

    window._import_finished(ImportFeedResult("job-1", "feed-1", JobState.CANCELLED, 0))
    assert not window._import_timer.isActive()
    assert window._import_context_label.text() == ""
    window.close()
    window.deleteLater()
    application.processEvents()


def test_p1_02_reimport_replaces_transient_feed_and_resets_elapsed(
    application: QApplication, tmp_path: Path
) -> None:
    window = MainWindow(elapsed_clock=lambda: 50.0)
    window.project_opened()
    window.job_started()
    window._begin_import_context(InputSource(tmp_path / "old.zip", InputSourceKind.ARCHIVE))
    window._import_job_started()
    window._show_import_progress(ImportProgress(ImportPhase.VALIDATING, 3, 5))

    window._clear_import_context()
    window.job_finished()
    window.job_started()
    window._begin_import_context(InputSource(tmp_path / "new.zip", InputSourceKind.ARCHIVE))

    assert "Feed: new.zip" in window._import_context_label.text()
    assert "old.zip" not in window._import_context_label.text()
    assert "Fase: Preparación" in window._import_context_label.text()
    assert "Progreso: 0 %" in window._import_context_label.text()
    assert not window._import_timer.isActive()
    window.job_finished()
    window.close()
    window.deleteLater()
    application.processEvents()


def test_p1_02_failure_and_project_close_clear_runtime_context(
    application: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    errors: list[str] = []
    monkeypatch.setattr(
        MainWindow,
        "_show_error",
        lambda _window, message, **_kwargs: errors.append(message),
    )
    window = MainWindow(elapsed_clock=lambda: 50.0)
    window.project_opened()
    window.job_started()
    window._begin_import_context(InputSource(tmp_path / "failing.zip", InputSourceKind.ARCHIVE))
    window._import_job_started()

    window._import_failed("error sintético")
    assert errors == ["No se pudo iniciar la importación: error sintético"]
    assert not window._import_timer.isActive()
    assert window._import_context_label.text() == ""

    window.job_started()
    window._begin_import_context(InputSource(tmp_path / "closing.zip", InputSourceKind.ARCHIVE))
    window._import_job_started()
    window._close_project()
    assert not window._import_timer.isActive()
    assert window._import_context_label.text() == ""
    window.deleteLater()
    application.processEvents()


def test_invalid_import_is_presented_as_inspection_state_not_technical_error(
    application: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = MainWindow()
    window.project_opened()
    window.job_started()
    messages: list[tuple[object, ...]] = []
    errors: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *args: messages.append(args) or QMessageBox.StandardButton.Ok,
    )
    monkeypatch.setattr(window, "_show_error", errors.append)

    window._import_finished(ImportFeedResult("job-1", "feed-1", JobState.INVALID, 2))

    assert messages
    assert "incidencias" in str(messages[0][2]).lower()
    assert errors == []
    assert window.ui_state.mode is UiMode.PROJECT_READY
    window.close()
    window.deleteLater()
    application.processEvents()


def test_ui_error_dialog_does_not_expose_traceback(
    application: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    logger = configure_logging(tmp_path)
    monkeypatch.setattr(QMessageBox, "exec", lambda _dialog: QMessageBox.StandardButton.Ok)

    def fail_if_traceback_is_added(_dialog: QMessageBox, _text: str) -> None:
        raise AssertionError("El traceback técnico no debe entrar en el diálogo normal.")

    monkeypatch.setattr(QMessageBox, "setDetailedText", fail_if_traceback_is_added)
    window = MainWindow(logger=logger, logs_directory=tmp_path)
    window._show_error(
        "No se ha podido abrir el proyecto.",
        operation="open_project",
        exception=RuntimeError("causa técnica sintética"),
    )
    logger.handlers[0].flush()
    content = (tmp_path / "gtfs-explorer.log").read_text(encoding="utf-8")
    assert "causa técnica sintética" in content
    window.deleteLater()
    application.processEvents()
    for handler in logger.handlers:
        handler.close()


def test_close_commit_failure_keeps_project_references_recoverable(
    application: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FailingSession:
        dirty = False
        editing_session = None

        def close(self) -> None:
            raise RuntimeError("controlled commit failure")

    class OpenProject:
        def close(self) -> None:
            raise AssertionError("the project must remain open after commit failure")

    window = MainWindow()
    session = FailingSession()
    opened = OpenProject()
    window._editor_session = session  # type: ignore[assignment]
    window._opened_project = opened  # type: ignore[assignment]
    errors: list[str] = []
    monkeypatch.setattr(window, "_show_error", lambda message, **_kwargs: errors.append(message))

    assert not window._close_project()
    assert window._editor_session is session
    assert window._opened_project is opened
    assert errors
    window.deleteLater()
    application.processEvents()


def test_project_can_close_and_reopen_in_the_same_window_lifecycle(
    application: QApplication, tmp_path: Path
) -> None:
    project_directory = tmp_path / "project"
    project_directory.mkdir()
    opened = CreateProject(project_directory).execute()
    window = MainWindow()
    window._opened_project = opened
    window.project_opened()

    window._close_project()

    assert window.ui_state.mode is UiMode.NO_PROJECT
    assert window._opened_project is None
    assert (project_directory / "project.json").is_file()
    assert (project_directory / "data.duckdb").is_file()
    assert not (project_directory / ".writer.lock").exists()

    reopened = OpenProject(project_directory).execute()
    window._opened_project = reopened
    window.project_opened()
    window._close_project()

    assert window.ui_state.mode is UiMode.NO_PROJECT
    assert (project_directory / "data.duckdb").is_file()
    window.deleteLater()
    application.processEvents()


def test_p0_005_close_resets_transient_project_ui_context(application: QApplication) -> None:
    window = MainWindow()
    window.project_opened()
    window._raw_inspector._fields = {"stops.txt": ("stop_id", "stop_name")}
    window._raw_inspector._files.blockSignals(True)
    window._raw_inspector._files.addItem("stops.txt")
    window._raw_inspector._files.blockSignals(False)
    window._raw_inspector._filter.setText("A-stop")
    window._validation._severity.setCurrentIndex(1)
    window._validation._category.setCurrentIndex(1)
    window._exporter._routes.setPlainText("R-A")
    window._exporter._trips.setPlainText("T-A")
    window._exporter._services.setPlainText("S-A")
    window._exporter._destination.setText("A-output.json")
    window._navigation.setCurrentRow(3)
    window._explore_tabs.setCurrentWidget(window._raw_inspector)

    window._close_project()

    assert window.ui_state.mode is UiMode.NO_PROJECT
    assert window._raw_inspector._filter.text() == ""
    assert window._raw_inspector._files.count() == 0
    assert window._raw_inspector._model.rowCount() == 0
    assert window._validation._severity.currentIndex() == 0
    assert window._validation._category.currentIndex() == 0
    assert window._validation._table.rowCount() == 0
    assert window._validation._detail.toPlainText() == ""
    assert window._exporter.request().route_ids == frozenset()
    assert window._exporter.request().trip_ids == frozenset()
    assert window._exporter.request().service_ids == frozenset()
    assert window._exporter.request().destination == Path(".")
    assert window._navigation.currentRow() == 0
    assert window._explore_tabs.currentWidget() is window._explorer
    assert not window._navigation.isEnabled()
    window.deleteLater()
    application.processEvents()


def _dirty_project_ui(window: MainWindow, *, marker: str) -> None:
    """Prepara un contexto visible que solo puede pertenecer al proyecto actual."""
    window._raw_inspector._fields = {f"{marker}.txt": ("id", "name")}
    window._raw_inspector._files.blockSignals(True)
    window._raw_inspector._files.addItem(f"{marker}.txt")
    window._raw_inspector._files.blockSignals(False)
    window._raw_inspector._filter.setText(f"{marker}-raw")
    window._validation._severity.setCurrentIndex(1)
    window._validation._category.setCurrentIndex(1)
    window._exporter._routes.setPlainText(f"{marker}-route")
    window._exporter._trips.setPlainText(f"{marker}-trip")
    window._exporter._services.setPlainText(f"{marker}-service")
    window._exporter._destination.setText(f"{marker}-output.json")
    window._explorer._routes.addItem(f"{marker} route")
    window._explorer._routes.setCurrentIndex(0)
    window._explore_tabs.setCurrentWidget(window._raw_inspector)
    window._navigation.setCurrentRow(3)


def _assert_clean_project_ui(window: MainWindow) -> None:
    assert window._raw_inspector._filter.text() == ""
    assert window._raw_inspector._files.count() == 0
    assert window._raw_inspector._model.rowCount() == 0
    assert window._validation._severity.currentIndex() == 0
    assert window._validation._category.currentIndex() == 0
    assert window._exporter.request().route_ids == frozenset()
    assert window._exporter.request().trip_ids == frozenset()
    assert window._exporter.request().service_ids == frozenset()
    assert window._exporter.request().destination == Path(".")
    assert window._explorer._routes.count() == 0
    assert window._explore_tabs.currentWidget() is window._explorer
    assert window._navigation.currentRow() == 0


def test_p0_005_real_open_project_resets_a_before_presenting_b(
    application: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "project-a").mkdir()
    (tmp_path / "project-b").mkdir()
    project_a = CreateProject(tmp_path / "project-a").execute()
    project_b = CreateProject(tmp_path / "project-b").execute()
    project_a_id = project_a.descriptor.project_id
    project_a.close()
    project_b.close()

    window = MainWindow()
    window._opened_project = OpenProject(tmp_path / "project-a").execute()
    window.project_opened()
    _dirty_project_ui(window, marker="A")
    window.setStyleSheet("QLabel { color: rgb(17, 34, 51); }")
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *args: str(tmp_path / "project-b")
    )

    window._choose_project()

    assert window._opened_project is not None
    assert window._opened_project.descriptor.project_id != ""
    assert window._opened_project.descriptor.project_id != project_a_id
    _assert_clean_project_ui(window)
    assert window.styleSheet() == "QLabel { color: rgb(17, 34, 51); }"
    window._close_project()
    window.deleteLater()
    application.processEvents()


def test_p0_005_real_new_project_does_not_inherit_a_ui_context(
    application: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "project-a").mkdir()
    project_a = CreateProject(tmp_path / "project-a").execute()
    project_a.close()
    new_directory = tmp_path / "project-b"
    new_directory.mkdir()

    window = MainWindow()
    window._opened_project = OpenProject(tmp_path / "project-a").execute()
    window.project_opened()
    _dirty_project_ui(window, marker="A")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(new_directory))

    window._choose_new_project()

    assert window._opened_project is not None
    assert window._opened_project.descriptor.project_id != ""
    assert window._overview._project_name.text() == window._opened_project.descriptor.name
    assert window._overview._project_workspace.text() == str(new_directory)
    _assert_clean_project_ui(window)
    assert window.ui_state.mode is not UiMode.NO_PROJECT
    window._close_project()
    window.deleteLater()
    application.processEvents()


def test_p0_005_invalid_open_leaves_no_project_instead_of_mixing_a_and_b(
    application: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "project-a").mkdir()
    project_a = CreateProject(tmp_path / "project-a").execute()
    project_a.close()
    invalid_project = tmp_path / "invalid-project"
    invalid_project.mkdir()
    errors: list[str] = []

    window = MainWindow()
    window._opened_project = OpenProject(tmp_path / "project-a").execute()
    window.project_opened()
    _dirty_project_ui(window, marker="A")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(invalid_project))
    monkeypatch.setattr(
        window,
        "_show_error",
        lambda message, **_kwargs: errors.append(str(message)),
    )

    window._choose_project()

    assert errors
    assert window._opened_project is None
    assert window.ui_state.mode is UiMode.NO_PROJECT
    assert window._project_identity_label.text() == "Sin proyecto abierto"
    assert window._overview._project_name.text() == "Sin proyecto abierto"
    assert str(tmp_path / "project-a") not in window._project_identity_label.text()
    _assert_clean_project_ui(window)
    assert not window._navigation.isEnabled()
    window.deleteLater()
    application.processEvents()


def test_p0_005_real_reopen_same_project_preserves_data_but_not_transient_ui(
    application: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_directory = tmp_path / "project-a"
    project_directory.mkdir()
    opened = CreateProject(project_directory).execute()
    project_id = opened.descriptor.project_id
    opened.close()

    window = MainWindow()
    window._opened_project = OpenProject(project_directory).execute()
    window.project_opened()
    _dirty_project_ui(window, marker="A")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(project_directory))

    window._choose_project()

    assert window._opened_project is not None
    assert window._opened_project.descriptor.project_id == project_id
    assert (project_directory / "project.json").is_file()
    assert (project_directory / "data.duckdb").is_file()
    _assert_clean_project_ui(window)
    window._close_project()
    window.deleteLater()
    application.processEvents()


def test_project_identity_uses_recovered_legacy_descriptor(
    application: QApplication, tmp_path: Path
) -> None:
    project_directory = tmp_path / "legacy-project"
    project_directory.mkdir()
    opened = CreateProject(project_directory).execute()
    project_id = opened.descriptor.project_id
    with DuckDbUnitOfWork(opened.database) as unit_of_work:
        unit_of_work.feeds.save_metadata(
            FeedMetadata(
                "feed-1",
                project_id,
                "legacy-feed.zip",
                "a" * 64,
                "strict",
                "2026-04-27",
                FeedStatus.IMPORTED,
            )
        )
        metadata = unit_of_work.projects.metadata()
        assert metadata is not None
        save_project_descriptor(
            project_directory / "project.json",
            ProjectDescriptor.from_metadata(metadata, None, project_directory),
        )
    opened.close()

    window = MainWindow()
    window._opened_project = OpenProject(project_directory).execute()
    window.project_opened()

    assert window._overview._project_name.text() == window._opened_project.descriptor.name
    assert window._overview._project_workspace.text() == str(project_directory)
    assert window._opened_project.descriptor.feed_id == "feed-1"
    window._close_project()
    window.deleteLater()
    application.processEvents()


def test_imported_feed_metadata_is_written_to_descriptor_before_reopen(
    application: QApplication, tmp_path: Path
) -> None:
    project_directory = tmp_path / "project"
    project_directory.mkdir()
    opened = CreateProject(project_directory).execute()
    with DuckDbUnitOfWork(opened.database) as unit_of_work:
        unit_of_work.feeds.save_metadata(
            FeedMetadata(
                "feed-1",
                opened.descriptor.project_id,
                "synthetic.zip",
                "a" * 64,
                "strict",
                "2026-04-27",
                FeedStatus.IMPORTED,
            )
        )
    window = MainWindow()
    window._opened_project = opened
    window.project_opened()
    window._synchronize_project_descriptor()
    opened.close()
    window._opened_project = None
    window.project_closed()

    reopened = OpenProject(project_directory).execute()
    assert reopened.descriptor.feed_id == "feed-1"
    reopened.close()
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
    assert not window._import_adapter.is_running
    assert not window._progress_bar.isVisible()
    window.close()
    window.deleteLater()
    application.processEvents()


@contextmanager
def _empty_connection() -> object:
    yield object()


@pytest.mark.parametrize(
    ("choice", "expected_mode"),
    (("full", "full"), ("summary", "summary"), ("cancel", None)),
)
def test_large_validation_report_dialog_dispatches_only_the_selected_mode(
    application: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    choice: str,
    expected_mode: str | None,
) -> None:
    class FakeExporter:
        def estimate(self, _connection: object, **_kwargs: object) -> tuple[int, int]:
            return (1_001, 2_097_152)

    class DecisionDialog:
        ButtonRole = QMessageBox.ButtonRole
        StandardButton = QMessageBox.StandardButton

        def __init__(self, *_args: object) -> None:
            self.full: object | None = None
            self.summary: object | None = None
            self._clicked: object | None = None

        def setWindowTitle(self, _title: str) -> None:
            pass

        def setText(self, text: str) -> None:
            assert "1,001" in text and "2.0 MB" in text

        def addButton(self, label: object, _role: object = None) -> object:
            button = object()
            if label == "Generar informe completo":
                self.full = button
            elif label == "Generar solo resumen":
                self.summary = button
            return button

        def exec(self) -> int:
            self._clicked = {"full": self.full, "summary": self.summary, "cancel": None}[choice]
            return 0

        def clickedButton(self) -> object | None:
            return self._clicked

    started: list[object] = []
    starter = SimpleNamespace(start=started.append)
    monkeypatch.setattr(main_window_module, "ValidationReportExporter", FakeExporter)
    monkeypatch.setattr(main_window_module, "QMessageBox", DecisionDialog)
    monkeypatch.setattr(
        main_window_module, "QThreadPool", SimpleNamespace(globalInstance=lambda: starter)
    )
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *_args: (str(tmp_path / "validation.html"), "HTML (*.html)"),
    )
    window = MainWindow()
    window._opened_project = SimpleNamespace(database=SimpleNamespace(connection=_empty_connection))

    window._export_validation_report("batch", main_window_module.ValidationIssueFilter())

    assert len(started) == (0 if expected_mode is None else 1)
    if expected_mode is not None:
        assert started[0]._mode == expected_mode
        progress = window._validation_report_job[2]
        window._validation_report_cancelled(progress)
    assert getattr(window, "_validation_report_job", None) is None
    window._opened_project = None
    window.close()
    window.deleteLater()
    application.processEvents()


def test_validation_report_progress_and_cancel_are_bound_to_the_active_worker(
    application: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeExporter:
        def estimate(self, _connection: object, **_kwargs: object) -> tuple[int, int]:
            return (5, 4096)

    started: list[object] = []
    monkeypatch.setattr(main_window_module, "ValidationReportExporter", FakeExporter)
    monkeypatch.setattr(
        main_window_module,
        "QThreadPool",
        SimpleNamespace(globalInstance=lambda: SimpleNamespace(start=started.append)),
    )
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *_args: (str(tmp_path / "validation.html"), "HTML (*.html)"),
    )
    window = MainWindow()
    window._opened_project = SimpleNamespace(database=SimpleNamespace(connection=_empty_connection))

    window._export_validation_report("batch", main_window_module.ValidationIssueFilter())

    job, signals, progress, cancel_token = window._validation_report_job
    assert started == [job]
    signals.progress.emit(3, 5)
    assert (progress.value(), progress.maximum()) == (3, 5)
    progress.canceled.emit()
    assert cancel_token.is_set()
    window._validation_report_cancelled(progress)
    assert window._validation_report_job is None
    window._opened_project = None
    window.close()
    window.deleteLater()
    application.processEvents()


def test_validation_report_worker_reports_success_failure_and_cancellation(
    application: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[tuple[str, object]] = []

    @contextmanager
    def connection() -> object:
        yield object()

    database = SimpleNamespace(connection=connection)

    class FakeExporter:
        outcome = "success"

        def write(self, _connection: object, _destination: Path, **kwargs: object) -> None:
            on_progress = kwargs["on_progress"]
            assert callable(on_progress)
            on_progress(500, 500)
            if self.outcome == "failure":
                raise RuntimeError("expected failure")

    monkeypatch.setattr(main_window_module, "ValidationReportExporter", FakeExporter)

    def run(outcome: str, cancelled: bool = False) -> None:
        FakeExporter.outcome = outcome
        token = threading.Event()
        if cancelled:
            token.set()
        signals = _ValidationReportSignals()
        signals.progress.connect(
            lambda current, total: events.append(("progress", (current, total)))
        )
        signals.succeeded.connect(lambda path: events.append(("success", path)))
        signals.failed.connect(lambda message: events.append(("failure", message)))
        signals.cancelled.connect(lambda: events.append(("cancelled", None)))
        _ValidationReportJob(
            database,
            tmp_path / f"{outcome}.html",
            "batch",
            "html",
            main_window_module.ValidationReportFilter(),
            "full",
            False,
            token,
            signals,
        ).run()

    run("success")
    run("failure")
    run("success", cancelled=True)

    assert events == [
        ("progress", (500, 500)),
        ("success", tmp_path / "success.html"),
        ("progress", (500, 500)),
        ("failure", "expected failure"),
        ("progress", (500, 500)),
        ("cancelled", None),
    ]


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
        (
            ExportFormat.MINI_GTFS,
            tmp_path / "mini.zip",
            "GTFS Schedule validado localmente",
        ),
    )
    for format_, destination, classification in exports:
        result = window._export_feed(
            ExportRequest(format_, destination, route_ids=frozenset({"R1"})), lambda: False
        )
        assert result.classification == classification
        assert destination.is_file()
        assert result.manifest.artifact_name == destination.name

    with DuckDbUnitOfWork(database) as unit_of_work:
        history = unit_of_work.operations.list_operations(
            "project-1", PageRequest(), OperationType.EXPORT
        )
    assert history.total == 4
    assert {item.export_format for item in history.items} == {
        format_.value for format_, _, _ in exports
    }
    assert all(item.status is OperationStatus.COMPLETED for item in history.items)
    assert all(item.feed_id == "feed-1" for item in history.items)
    assert all(item.artifact_name and "/" not in item.artifact_name for item in history.items)
    assert all(item.artifact_sha256 and len(item.artifact_sha256) == 64 for item in history.items)
    assert all(item.artifact_size_bytes and item.artifact_size_bytes > 0 for item in history.items)

    window._opened_project = None
    window.close()
    window.deleteLater()
    application.processEvents()


@pytest.mark.integration
def test_export_failure_is_recorded_without_leaking_exception_or_path(
    application: QApplication, tmp_path: Path
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write_fixture(source)
    database = _database(tmp_path)
    assert _command(database, source).execute().state is JobState.READY
    window = MainWindow()
    window._opened_project = SimpleNamespace(database=database)

    with pytest.raises(Exception):
        window._export_feed(
            ExportRequest(
                ExportFormat.JSON, tmp_path / "missing" / "feed.json", route_ids=frozenset({"R1"})
            ),
            lambda: False,
        )

    with DuckDbUnitOfWork(database) as unit_of_work:
        items = unit_of_work.operations.list_operations(
            "project-1", PageRequest(), OperationType.EXPORT
        ).items
    assert len(items) == 1
    assert items[0].status is OperationStatus.FAILED
    assert items[0].error_code == "EXPORT_PREPARE_FAILED"
    assert items[0].artifact_name is None
    assert "\\" not in (items[0].error_code or "")
    window._opened_project = None
    window.close()
    window.deleteLater()
    application.processEvents()


@pytest.mark.integration
def test_export_filesystem_failure_is_failed_and_keeps_previous_outputs(
    application: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write_fixture(source)
    database = _database(tmp_path)
    assert _command(database, source).execute().state is JobState.READY
    window = MainWindow()
    window._opened_project = SimpleNamespace(database=database)

    def fail_write(*args: object, **kwargs: object) -> tuple[str, int]:
        raise ExportError("synthetic filesystem failure")

    monkeypatch.setattr(
        "gtfs_explorer.infrastructure.exporting.atomic_output.AtomicOutputWriter._write_temporary",
        fail_write,
    )
    with pytest.raises(ExportError):
        window._export_feed(
            ExportRequest(ExportFormat.JSON, tmp_path / "feed.json", route_ids=frozenset({"R1"})),
            lambda: False,
        )

    with DuckDbUnitOfWork(database) as unit_of_work:
        item = unit_of_work.operations.list_operations(
            "project-1", PageRequest(), OperationType.EXPORT
        ).items[0]
    assert item.status is OperationStatus.FAILED
    assert item.error_code == "EXPORT_WRITE_FAILED"
    assert not (tmp_path / "feed.json").exists()
    assert not (tmp_path / "feed.json.manifest.json").exists()
    window._opened_project = None
    window.close()
    window.deleteLater()
    application.processEvents()


@pytest.mark.integration
def test_export_db_failure_after_publish_stays_running_and_reopens_as_interrupted(
    application: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write_fixture(source)
    database = _database(tmp_path)
    assert _command(database, source).execute().state is JobState.READY
    window = MainWindow()
    window._opened_project = SimpleNamespace(database=database)
    original_commit = DuckDbUnitOfWork.commit
    commits = 0

    def fail_terminal_commit(unit_of_work: DuckDbUnitOfWork) -> None:
        nonlocal commits
        commits += 1
        if commits == 5:
            raise RuntimeError("synthetic database failure after publication")
        original_commit(unit_of_work)

    monkeypatch.setattr(DuckDbUnitOfWork, "commit", fail_terminal_commit)
    destination = tmp_path / "published.json"
    with pytest.raises(RuntimeError, match="after publication"):
        window._export_feed(
            ExportRequest(ExportFormat.JSON, destination, route_ids=frozenset({"R1"})),
            lambda: False,
        )
    assert destination.is_file()
    assert (tmp_path / "published.json.manifest.json").is_file()

    monkeypatch.setattr(DuckDbUnitOfWork, "commit", original_commit)
    with DuckDbUnitOfWork(database) as unit_of_work:
        item = unit_of_work.operations.list_operations(
            "project-1", PageRequest(), OperationType.EXPORT
        ).items[0]
    assert item.status is OperationStatus.RUNNING
    assert item.artifact_name is None
    assert display_status(item, frozenset()) is OperationDisplayStatus.INTERRUPTED
    window._opened_project = None
    window.close()
    window.deleteLater()
    application.processEvents()
