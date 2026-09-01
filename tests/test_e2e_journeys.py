"""P1-23: journeys E2E pequeños sobre la arquitectura productiva local."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import pytest
from PySide6.QtCore import QEventLoop, Qt, QTimer, QUrl
from PySide6.QtWidgets import QApplication, QComboBox, QFileDialog, QMessageBox, QWidget

from gtfs_explorer.application.commands.create_project import CreateProject
from gtfs_explorer.application.commands.import_feed import ImportFeed, ImportFeedResult
from gtfs_explorer.application.commands.open_project import (
    OpenProject,
    ProjectWriterLockedError,
)
from gtfs_explorer.application.jobs.import_job import ImportPhase, ImportProgress
from gtfs_explorer.application.map_policy import MapAvailability, MapMode, MapRequestPolicy
from gtfs_explorer.application.ui_state import UiAction
from gtfs_explorer.domain.operations import OperationStatus, OperationType
from gtfs_explorer.domain.ports import PageRequest
from gtfs_explorer.domain.project import FeedStatus, JobState, ProjectMetadata, ProjectStatus
from gtfs_explorer.domain.source import InputSource, InputSourceKind
from gtfs_explorer.domain.spec import load_schedule_spec
from gtfs_explorer.infrastructure.duckdb.database import DatabaseCorruptionError, ProjectDatabase
from gtfs_explorer.infrastructure.duckdb.repositories import DuckDbUnitOfWork
from gtfs_explorer.infrastructure.filesystem.project_descriptor import (
    ProjectDescriptor,
    save_project_descriptor,
)
from gtfs_explorer.infrastructure.maps.offline_library import OfflineMapLibrary
from gtfs_explorer.presentation.desktop.exporter import ExportFormat
from gtfs_explorer.presentation.desktop.main_window import MainWindow
from gtfs_explorer.presentation.desktop.map.widget import MapNetworkInterceptor

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "schemas" / "gtfs_schedule" / "2026-04-27" / "spec.json"
FIXTURE_DIRECTORY = ROOT / "tests" / "fixtures" / "specs"


class _FunctionalMap(QWidget):
    """Sustituto funcional del WebEngine para el runner Qt offscreen.

    Ejecuta la consulta real de capas y conserva el contrato de modo, paquete,
    selección y overlay. El render pixel-perfect pertenece al smoke gráfico
    separado y no es un criterio de esta suite.
    """

    def __init__(self, layers_for_trip: Callable[[str], object], _on_stop_selected: object) -> None:
        super().__init__()
        self._layers_for_trip = layers_for_trip
        self.mode = MapMode.AUTO
        self.status_text = "Mapa: no disponible · sin paquete local."
        self.managed_package: object | None = None
        self.last_trip_id: str | None = None
        self.last_payload: object | None = None
        self.selected_stop_id: str | None = None

    def clear(self) -> None:
        self.last_trip_id = None
        self.last_payload = None
        self.selected_stop_id = None

    def show_trip(self, trip_id: str) -> None:
        self.last_trip_id = trip_id
        self.last_payload = self._layers_for_trip(trip_id)

    def select_stop(self, stop_id: str) -> None:
        self.selected_stop_id = stop_id

    def set_mode(self, mode: MapMode | str) -> str:
        self.mode = MapMode(mode)
        if self.managed_package is not None:
            self.status_text = "Mapa · Offline · PMTiles"
        elif self.mode is MapMode.OFFLINE:
            self.status_text = "Mapa: offline · sin paquete local."
        elif self.mode is MapMode.ONLINE:
            self.status_text = "Mapa: online · sin proveedor activo."
        else:
            self.status_text = "Mapa: no disponible · sin paquete local."
        return self.status_text

    def set_managed_map(self, _library: OfflineMapLibrary, package: object) -> None:
        self.managed_package = package
        self.status_text = "Mapa · Offline · PMTiles"

    def clear_managed_map(self) -> None:
        self.managed_package = None
        self.set_mode(self.mode)


@pytest.fixture
def e2e_runtime(application: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Aísla la biblioteca global de mapas y los diálogos que bloquearían Qt."""
    assert QApplication.instance() is application
    map_root = tmp_path / "map-library"
    monkeypatch.setattr(
        "gtfs_explorer.infrastructure.maps.offline_library.default_map_library_path",
        lambda: map_root,
    )
    monkeypatch.setattr(
        "gtfs_explorer.presentation.desktop.routes.widget.MapWidget", _FunctionalMap
    )
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Ok,
    )
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Ok,
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )


@dataclass
class _ProgressGate:
    """Pausa un worker en una fase productiva sin dejar una espera indefinida."""

    predicate: Callable[[ImportProgress], bool]
    reached: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)
    entered: bool = False
    progress: list[ImportProgress] = field(default_factory=list)

    def forward(
        self, progress: ImportProgress, downstream: Callable[[ImportProgress], None]
    ) -> None:
        downstream(progress)
        self.progress.append(progress)
        if not self.entered and self.predicate(progress):
            self.entered = True
            self.reached.set()
            if not self.release.wait(timeout=10):
                raise TimeoutError("La barrera E2E de importación no se liberó a tiempo.")


def _materialize_fixture(destination: Path, fixture_id: str) -> None:
    specification = json.loads(
        (FIXTURE_DIRECTORY / f"{fixture_id}.json").read_text(encoding="utf-8")
    )
    destination.mkdir(parents=True, exist_ok=True)
    for filename, table in specification["tables"].items():
        with (destination / filename).open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(
                output,
                fieldnames=table["headers"],
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(table["rows"])


def _project_metadata(window: MainWindow) -> ProjectMetadata:
    opened = window._opened_project
    assert opened is not None
    return ProjectMetadata(
        opened.descriptor.project_id,
        opened.descriptor.name,
        ProjectStatus(opened.descriptor.status),
    )


def _configure_factory(
    configuration: list[tuple[ProjectDatabase, ProjectMetadata]],
    *,
    gates_by_call: dict[int, _ProgressGate] | None = None,
    feed_ids: tuple[str, ...] = (),
    job_ids: tuple[str, ...] = (),
    has_free_space: Callable[[int], bool] | None = None,
) -> Callable[[InputSource, Callable[[ImportProgress], None]], ImportFeed]:
    calls = 0

    def factory(
        input_source: InputSource, on_progress: Callable[[ImportProgress], None]
    ) -> ImportFeed:
        nonlocal calls
        index = calls
        calls += 1
        database, metadata = configuration[0]
        gate = (gates_by_call or {}).get(index)

        def progress(value: ImportProgress) -> None:
            if gate is None:
                on_progress(value)
            else:
                gate.forward(value, on_progress)

        return ImportFeed(
            database,
            metadata,
            input_source,
            load_schedule_spec(SPEC_PATH),
            job_id=job_ids[index] if index < len(job_ids) else f"e2e-job-{index + 1}",
            feed_id=feed_ids[index] if index < len(feed_ids) else f"e2e-feed-{index + 1}",
            on_progress=progress,
            has_free_space=has_free_space,
        )

    return factory


def _pump_until(
    application: QApplication, predicate: Callable[[], bool], timeout: float = 10
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        application.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    application.processEvents()
    return predicate()


def _start_and_wait(
    application: QApplication,
    window: MainWindow,
    source: InputSource,
    *,
    through_request: bool = False,
    timeout: float = 15,
) -> ImportFeedResult:
    completed: list[ImportFeedResult] = []
    errors: list[str] = []
    loop = QEventLoop()

    def finished(result: object) -> None:
        if isinstance(result, ImportFeedResult):
            completed.append(result)
        loop.quit()

    def failed(message: str) -> None:
        errors.append(message)
        loop.quit()

    window._import_adapter.finished.connect(finished)
    window._import_adapter.failed.connect(failed)
    timer = QTimer(window)
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    try:
        if through_request:
            window._request_import(source)
        else:
            window.start_import(source)
        timer.start(round(timeout * 1000))
        if not completed and not errors:
            loop.exec()
    finally:
        timer.stop()
        timer.deleteLater()
        window._import_adapter.finished.disconnect(finished)
        window._import_adapter.failed.disconnect(failed)

    if errors:
        pytest.fail(f"El adaptador E2E no pudo iniciar la importación: {errors[0]}")
    if not completed:
        if window._import_adapter.is_running:
            window._request_cancellation()
            _pump_until(application, lambda: not window._import_adapter.is_running, timeout=5)
        pytest.fail(
            "Timeout E2E esperando importación: "
            f"fase={window._import_phase!s}, detalle={window._import_detail!r}, "
            f"adaptador_activo={window._import_adapter.is_running}"
        )
    return completed[0]


def _close_window(application: QApplication, window: MainWindow) -> None:
    if window._import_adapter.is_running:
        window._request_cancellation()
        _pump_until(application, lambda: not window._import_adapter.is_running, timeout=5)
    if window._opened_project is not None:
        window._close_project()
    window.close()
    window.deleteLater()
    application.processEvents()


def _create_project_from_ui(
    window: MainWindow,
    directory: Path,
    selection: list[Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    selection[:] = [directory]
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_args: str(selection[0]))
    window._choose_new_project()
    assert window._opened_project is not None
    assert window._opened_project.directory == directory.resolve()


def _synchronise_descriptor(opened: object, project: Path) -> None:
    # El helper se usa solo con OpenedProject producido por CreateProject.
    opened_project = opened
    database = getattr(opened_project, "database")
    with DuckDbUnitOfWork(database) as unit_of_work:
        metadata = unit_of_work.projects.metadata()
        feed = unit_of_work.feeds.latest_metadata()
        assert metadata is not None
        descriptor = ProjectDescriptor.from_metadata(metadata, feed, project)
    save_project_descriptor(project / "project.json", descriptor)


def _seed_project(project: Path, fixture_id: str) -> tuple[str, str]:
    project.mkdir(parents=True)
    source = project.parent / f"{project.name}-source"
    _materialize_fixture(source, fixture_id)
    opened = CreateProject(project, name=f"E2E {fixture_id}").execute()
    metadata = ProjectMetadata(
        opened.descriptor.project_id,
        opened.descriptor.name,
        ProjectStatus(opened.descriptor.status),
    )
    result = ImportFeed(
        opened.database,
        metadata,
        InputSource(source, InputSourceKind.DIRECTORY),
        load_schedule_spec(SPEC_PATH),
        job_id=f"seed-{fixture_id}",
        feed_id=f"seed-{fixture_id}-feed",
    ).execute()
    assert result.state in {JobState.READY, JobState.INVALID}
    _synchronise_descriptor(opened, project)
    project_id = opened.descriptor.project_id
    feed_id = result.feed_id
    opened.close()
    return project_id, feed_id


def _select_combo_data(combo: QComboBox, attribute: str, expected: object) -> None:
    for index in range(combo.count()):
        value = combo.itemData(index)
        if getattr(value, attribute, object()) == expected:
            combo.setCurrentIndex(index)
            return
    pytest.fail(f"No se encontró {attribute}={expected!r} en el selector.")


def _assert_raw_row(window: MainWindow, *, trip_id: str, stop_id: str, source_row: str) -> None:
    raw = window._raw_inspector
    file_index = raw._files.findText("stop_times.txt")
    assert file_index >= 0
    raw._files.setCurrentIndex(file_index)
    model = raw._model
    for row in range(model.rowCount()):
        values = [
            str(model.data(model.index(row, column)) or "") for column in range(model.columnCount())
        ]
        if len(values) > 4 and values[1] == trip_id and values[4] == stop_id:
            assert values[0] == source_row
            assert raw._table.model().headerData(0, Qt.Orientation.Horizontal) == "Fila fuente"
            return
    pytest.fail(f"No se encontró la fila RAW {trip_id}/{stop_id}.")


def _export_from_ui(
    window: MainWindow, format_: ExportFormat, route_id: str, destination: Path
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    window._navigation.setCurrentRow(3)
    exporter = window._exporter
    format_index = exporter._format.findData(format_.value)
    assert format_index >= 0
    exporter._format.setCurrentIndex(format_index)
    exporter._routes.setPlainText(route_id)
    exporter._destination.setText(str(destination))
    artifact = exporter.request().destination
    assert exporter._export.isEnabled()
    # El journey técnico valida el artefacto y su reimportación; la UX modal
    # de finalización tiene cobertura focal propia.
    exporter._show_export_completed = lambda *_args: None  # type: ignore[method-assign]
    exporter._execute()
    assert artifact.is_file()
    manifest = artifact.with_name(f"{artifact.name}.manifest.json")
    assert manifest.is_file()
    return artifact


def _assert_manifest_private(artifact: Path, project: Path) -> dict[str, Any]:
    manifest = artifact.with_name(f"{artifact.name}.manifest.json")
    raw = manifest.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    assert payload["artifact_name"] == artifact.name
    assert payload["sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert payload["size_bytes"] == artifact.stat().st_size
    for private in (str(project), str(Path.home()), "traceback", "secret"):
        assert private.casefold().encode("utf-8") not in raw.lower()
    return payload


def _write_raster_pmtiles(path: Path) -> None:
    header = bytearray(264)
    header[:8] = b"PMTiles\x03"
    header[99] = 2
    header[100] = 0
    header[101] = 14
    for index, value in enumerate((-6.0, 42.9, -5.6, 43.3)):
        encoded = int(value * 10_000_000).to_bytes(4, "little", signed=True)
        start = 102 + index * 4
        header[start : start + 4] = encoded
    path.write_bytes(header)


@pytest.mark.e2e
def test_e2e_01_happy_path_valid_real_ui_journey(
    application: QApplication,
    e2e_runtime: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "happy-project"
    source = tmp_path / "happy-source"
    _materialize_fixture(source, "mini_gtfs_contract")
    selection = [project]
    window = MainWindow()
    try:
        _create_project_from_ui(window, project, selection, monkeypatch)
        gate = _ProgressGate(
            lambda progress: progress.phase is ImportPhase.STAGING
            and progress.completed is not None
        )
        configuration = [
            (window._opened_project.database, _project_metadata(window))  # type: ignore[union-attr]
        ]
        window._import_command_factory = _configure_factory(
            configuration,
            gates_by_call={0: gate},
            feed_ids=("happy-feed",),
            job_ids=("happy-job",),
        )
        # La barrera hace observable el flujo real de progreso sin medir tiempos exactos.
        input_source = InputSource(source, InputSourceKind.DIRECTORY)
        completed: list[ImportFeedResult] = []
        loop = QEventLoop()

        def collect(result: object) -> None:
            if isinstance(result, ImportFeedResult):
                completed.append(result)
            loop.quit()

        connected = False
        try:
            window._import_adapter.finished.connect(collect)
            connected = True
            window._request_import(input_source)
            assert _pump_until(application, gate.reached.is_set, timeout=10)
            application.processEvents()
            assert "Fase: Carga" in window._import_context_label.text()
            assert "Detalle:" in window._import_context_label.text()
            assert "Actividad:" in window._import_context_label.text()
            assert "Tiempo transcurrido:" in window._import_context_label.text()
            assert window._progress_bar.minimum() == 0
            assert window._progress_bar.maximum() == 0
            gate.release.set()
            QTimer.singleShot(15_000, loop.quit)
            if not completed:
                loop.exec()
        finally:
            gate.release.set()
            if connected:
                window._import_adapter.finished.disconnect(collect)
        assert completed and completed[0].state is JobState.READY
        assert window.ui_state.mode.value == "PROJECT_READY"
        assert not window._import_adapter.is_running
        assert not window._progress_bar.isVisible()
        assert window._import_context_label.text() == ""
        assert window._overview._feed_import_status.text() == "Completada"
        assert window._overview._feed_validation_status.text() in {
            "VALID",
            "VALID_WITH_WARNINGS",
        }

        window._navigation.setCurrentRow(1)
        explorer = window._explorer
        _select_combo_data(explorer._routes, "route_id", "A")
        _select_combo_data(explorer._services, "service_id", "S_A")
        assert explorer._directions.count() > 0
        explorer._directions.setCurrentIndex(0)
        _select_combo_data(explorer._trips, "trip_id", "A_TRIP_1")
        assert explorer._timeline._table.rowCount() == 3
        assert explorer._timeline._table.item(1, 3).text() == "24:10:00"
        explorer._timeline._table.selectRow(1)
        assert "A1" in explorer._stops._headline.text()
        assert getattr(explorer._map, "last_trip_id", None) == "A_TRIP_1"
        payload = getattr(explorer._map, "last_payload", None)
        assert payload is not None
        assert "A_TRIP_1" in json.dumps(getattr(payload, "shapes"), ensure_ascii=False)

        window._explore_tabs.setCurrentWidget(window._raw_inspector)
        _assert_raw_row(window, trip_id="A_TRIP_1", stop_id="A1", source_row="3")

        artifact = _export_from_ui(window, ExportFormat.JSON, "A", tmp_path / "exports" / "happy")
        _assert_manifest_private(artifact, project)
        assert window._operation_history._table.rowCount() == 2
        assert all(
            window._operation_history._table.item(row, 3).text() == "Completada"
            for row in range(window._operation_history._table.rowCount())
        )

        project_id = window._opened_project.descriptor.project_id  # type: ignore[union-attr]
        window._close_project()
        assert not (project / ".writer.lock").exists()
        selection[:] = [project]
        window._choose_project()
        assert window._opened_project is not None
        assert window._opened_project.descriptor.project_id == project_id
        assert window._overview._feed_name.text() == source.name
        assert window._overview._feed_validation_status.text() in {
            "VALID",
            "VALID_WITH_WARNINGS",
        }
        assert window._operation_history._table.rowCount() == 2
        window._navigation.setCurrentRow(1)
        assert {
            window._explorer._routes.itemText(i).split(" (")[1].split(")", 1)[0]
            for i in range(window._explorer._routes.count())
        } == {"A", "B"}
        window._navigation.setCurrentRow(2)
        assert any(
            status in window._validation._summary.text()
            for status in ("VALID", "VALID_WITH_WARNINGS")
        )
    finally:
        _close_window(application, window)


@pytest.mark.e2e
def test_e2e_02_invalid_feed_is_imported_and_inspectable(
    application: QApplication,
    e2e_runtime: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "invalid-project"
    source = tmp_path / "invalid-source"
    _materialize_fixture(source, "invalid_core")
    selection = [project]
    window = MainWindow()
    try:
        _create_project_from_ui(window, project, selection, monkeypatch)
        result = _start_and_wait(
            application,
            window,
            InputSource(source, InputSourceKind.DIRECTORY),
            through_request=True,
        )
        assert result.state is JobState.INVALID
        assert window.ui_state.mode.value == "PROJECT_READY"
        assert window._overview._feed_import_status.text() == "Completada"
        assert window._overview._feed_validation_status.text() == "INVALID"
        assert int(window._overview._feed_issue_count.text()) > 0
        assert window._operation_history._table.rowCount() == 1
        assert window._operation_history._table.item(0, 3).text() == "Completada"
        assert "Inválido" in window._operation_history._table.item(0, 2).text()

        window._navigation.setCurrentRow(2)
        assert window._validation._table.rowCount() > 0
        assert "INVALID" in window._validation._summary.text()
        issue_row = next(
            row
            for row in range(window._validation._table.rowCount())
            if window._validation._table.item(row, 4).text() == "stop_times.txt"
        )
        window._validation._table.selectRow(issue_row)
        assert "stop_times.txt" in window._validation._detail.toPlainText()
        assert "MISSING_STOP" in window._validation._detail.toPlainText()
        window._validation._go_to_raw.click()
        assert window._explore_tabs.currentWidget() is window._raw_inspector
        _assert_raw_row(window, trip_id="T1", stop_id="MISSING_STOP", source_row="2")

        # El contrato actual permite exportar el feed importado aunque sea INVALID;
        # la validación se conserva como resultado separado y el ledger termina COMPLETED.
        export = _export_from_ui(window, ExportFormat.JSON, "R1", tmp_path / "exports" / "invalid")
        assert _assert_manifest_private(export, project)["artifact_name"] == export.name
        assert window._operation_history._table.rowCount() == 2
    finally:
        _close_window(application, window)


@pytest.mark.e2e
def test_e2e_03_first_import_cancellation_is_clean_and_project_continues(
    application: QApplication,
    e2e_runtime: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "cancel-first-project"
    source = tmp_path / "cancel-first-source"
    _materialize_fixture(source, "valid_full")
    selection = [project]
    window = MainWindow()
    try:
        _create_project_from_ui(window, project, selection, monkeypatch)
        gate = _ProgressGate(
            lambda progress: progress.phase is ImportPhase.STAGING and progress.completed is None
        )
        configuration = [(window._opened_project.database, _project_metadata(window))]  # type: ignore[union-attr]
        window._import_command_factory = _configure_factory(
            configuration,
            gates_by_call={0: gate},
            feed_ids=("cancelled-first", "continued-feed"),
            job_ids=("cancelled-first-job", "continued-job"),
        )
        source_input = InputSource(source, InputSourceKind.DIRECTORY)
        completed: list[ImportFeedResult] = []
        loop = QEventLoop()
        window._import_adapter.finished.connect(
            lambda result: (completed.append(result), loop.quit())
        )
        window.start_import(source_input)
        assert _pump_until(application, gate.reached.is_set, timeout=10)
        application.processEvents()
        assert window._actions[UiAction.CANCEL_JOB].isEnabled()
        assert "Fase: Carga" in window._import_context_label.text()
        window._request_cancellation()
        assert window.ui_state.mode.value == "JOB_CANCELLING"
        assert "Cancelando…" in window._import_context_label.text()
        assert not window._actions[UiAction.CANCEL_JOB].isEnabled()
        gate.release.set()
        QTimer.singleShot(15_000, loop.quit)
        if not completed:
            loop.exec()
        assert completed and completed[0].state is JobState.CANCELLED
        assert window.ui_state.mode.value == "PROJECT_READY"
        assert window._import_context_label.text() == ""
        assert not window._progress_bar.isVisible()
        assert not window._import_adapter.is_running

        with window._opened_project.database.connection() as connection:  # type: ignore[union-attr]
            assert connection.execute(
                "SELECT status FROM feeds WHERE feed_id = ?", ["cancelled-first"]
            ).fetchone() == ("CANCELLED",)
            assert connection.execute("SELECT count(*) FROM gtfs_routes").fetchone() == (0,)
            assert connection.execute("SELECT status FROM operations").fetchone() == (
                OperationStatus.CANCELLED.value,
            )

        continued = _start_and_wait(application, window, source_input)
        assert continued.state is JobState.READY
        assert window._actions[UiAction.IMPORT_FEED].isEnabled()
        with window._opened_project.database.connection() as connection:  # type: ignore[union-attr]
            assert connection.execute(
                "SELECT status FROM feeds WHERE feed_id = ?", ["continued-feed"]
            ).fetchone() == ("IMPORTED",)
            assert connection.execute("SELECT count(*) FROM gtfs_routes").fetchone()[0] > 0
            statuses = connection.execute(
                "SELECT status FROM operations ORDER BY started_at"
            ).fetchall()
        assert statuses == [(OperationStatus.CANCELLED.value,), (OperationStatus.COMPLETED.value,)]
    finally:
        _close_window(application, window)


@pytest.mark.e2e
def test_e2e_04_cancelled_reimport_keeps_previous_feed_through_reopen(
    application: QApplication,
    e2e_runtime: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "cancel-reimport-project"
    source_a = tmp_path / "feed-a-source"
    source_b = tmp_path / "feed-b-source"
    _materialize_fixture(source_a, "mini_gtfs_contract")
    _materialize_fixture(source_b, "valid_core")
    selection = [project]
    window = MainWindow()
    try:
        _create_project_from_ui(window, project, selection, monkeypatch)
        gate = _ProgressGate(
            lambda progress: progress.phase is ImportPhase.STAGING and progress.completed is None
        )
        configuration = [(window._opened_project.database, _project_metadata(window))]  # type: ignore[union-attr]
        window._import_command_factory = _configure_factory(
            configuration,
            gates_by_call={1: gate},
            feed_ids=("feed-a", "feed-b"),
            job_ids=("job-a", "job-b"),
        )
        first = _start_and_wait(
            application, window, InputSource(source_a, InputSourceKind.DIRECTORY)
        )
        assert first.state is JobState.READY
        second_results: list[ImportFeedResult] = []
        loop = QEventLoop()
        window._import_adapter.finished.connect(
            lambda result: (second_results.append(result), loop.quit())
        )
        window.start_import(InputSource(source_b, InputSourceKind.DIRECTORY))
        assert _pump_until(application, gate.reached.is_set, timeout=10)
        window._request_cancellation()
        gate.release.set()
        QTimer.singleShot(15_000, loop.quit)
        if not second_results:
            loop.exec()
        assert second_results and second_results[0].state is JobState.CANCELLED
        assert window.ui_state.mode.value == "PROJECT_READY"

        with DuckDbUnitOfWork(window._opened_project.database) as unit_of_work:  # type: ignore[union-attr]
            feed = unit_of_work.feeds.latest_metadata()
            assert feed is not None
            assert feed.feed_id == "feed-a"
            assert feed.status is FeedStatus.IMPORTED
            assert unit_of_work.route_explorer.routes(PageRequest(limit=100)).items
            operations = unit_of_work.operations.list_operations(
                window._opened_project.descriptor.project_id,  # type: ignore[union-attr]
                PageRequest(limit=100),
                OperationType.IMPORT,
            ).items
        assert [operation.status for operation in operations] == [
            OperationStatus.CANCELLED,
            OperationStatus.COMPLETED,
        ]

        project_id = window._opened_project.descriptor.project_id  # type: ignore[union-attr]
        window._close_project()
        selection[:] = [project]
        window._choose_project()
        assert window._opened_project is not None
        assert window._opened_project.descriptor.project_id == project_id
        assert window._overview._feed_name.text() == source_a.name
        assert window._overview._feed_import_status.text() == "Completada"
        assert window._overview._feed_validation_status.text() in {
            "VALID",
            "VALID_WITH_WARNINGS",
        }
        assert window._operation_history._table.rowCount() == 2
        window._navigation.setCurrentRow(1)
        assert window._explorer._routes.count() == 2
        assert "A_TRIP_1" in window._explorer._trips.itemText(0)
    finally:
        _close_window(application, window)


@pytest.mark.e2e
def test_e2e_05_ui_exports_publish_manifests_history_and_reimport_mini_gtfs(
    application: QApplication,
    e2e_runtime: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "exports-project"
    source = tmp_path / "exports-source"
    _materialize_fixture(source, "mini_gtfs_contract")
    selection = [project]
    window = MainWindow()
    try:
        _create_project_from_ui(window, project, selection, monkeypatch)
        result = _start_and_wait(
            application, window, InputSource(source, InputSourceKind.DIRECTORY)
        )
        assert result.state is JobState.READY
        export_root = tmp_path / "exports"
        formats = (
            ExportFormat.JSON,
            ExportFormat.CSV,
            ExportFormat.GEOJSON,
            ExportFormat.MINI_GTFS,
        )
        artifacts = {
            format_: _export_from_ui(window, format_, "A", export_root / format_.value)
            for format_ in formats
        }
        for artifact in artifacts.values():
            _assert_manifest_private(artifact, project)

        with DuckDbUnitOfWork(window._opened_project.database) as unit_of_work:  # type: ignore[union-attr]
            operations = unit_of_work.operations.list_operations(
                window._opened_project.descriptor.project_id,  # type: ignore[union-attr]
                PageRequest(limit=100),
                OperationType.EXPORT,
            ).items
        assert len(operations) == 4
        assert all(operation.status is OperationStatus.COMPLETED for operation in operations)
        assert {operation.artifact_name for operation in operations} == {
            artifact.name for artifact in artifacts.values()
        }
        assert all(
            operation.artifact_name is not None
            and "/" not in operation.artifact_name
            and "\\" not in operation.artifact_name
            for operation in operations
        )

        mini = artifacts[ExportFormat.MINI_GTFS]
        target_directory = tmp_path / "mini-target"
        target_directory.mkdir()
        target = CreateProject(target_directory, name="E2E Mini target").execute()
        try:
            metadata = ProjectMetadata(
                target.descriptor.project_id,
                target.descriptor.name,
                ProjectStatus(target.descriptor.status),
            )
            target_result = ImportFeed(
                target.database,
                metadata,
                InputSource(mini, InputSourceKind.ARCHIVE),
                load_schedule_spec(SPEC_PATH),
                job_id="mini-reimport-job",
                feed_id="mini-reimport-feed",
            ).execute()
        finally:
            target.close()
        assert target_result.state is JobState.READY
        assert target_result.issue_count == 0
        with target.database.connection() as connection:
            counts = {
                "rutas": connection.execute("SELECT count(*) FROM gtfs_routes").fetchone()[0],
                "servicios": connection.execute(
                    "SELECT count(*) FROM (SELECT service_id FROM gtfs_calendar UNION "
                    "SELECT service_id FROM gtfs_calendar_dates)"
                ).fetchone()[0],
                "viajes": connection.execute("SELECT count(*) FROM gtfs_trips").fetchone()[0],
                "paradas": connection.execute("SELECT count(*) FROM gtfs_stops").fetchone()[0],
                "validation": connection.execute("SELECT status FROM validation_runs").fetchone()[
                    0
                ],
            }
        assert counts == {
            "rutas": 1,
            "servicios": 2,
            "viajes": 2,
            "paradas": 4,
            "validation": "VALID",
        }
    finally:
        _close_window(application, window)


@pytest.mark.e2e
def test_e2e_06_switching_projects_clears_feed_dependent_context(
    application: QApplication,
    e2e_runtime: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    _seed_project(project_b, "invalid_core")
    source_a = tmp_path / "project-a-source"
    _materialize_fixture(source_a, "mini_gtfs_contract")
    selection = [project_a]
    window = MainWindow()
    try:
        _create_project_from_ui(window, project_a, selection, monkeypatch)
        result = _start_and_wait(
            application, window, InputSource(source_a, InputSourceKind.DIRECTORY)
        )
        assert result.state is JobState.READY
        window._map_mode_combo.setCurrentIndex(1)
        window._navigation.setCurrentRow(1)
        _select_combo_data(window._explorer._routes, "route_id", "A")
        _select_combo_data(window._explorer._services, "service_id", "S_A")
        window._explorer._directions.setCurrentIndex(0)
        _select_combo_data(window._explorer._trips, "trip_id", "A_TRIP_1")
        _assert_raw_row(window, trip_id="A_TRIP_1", stop_id="A1", source_row="3")
        assert "A_TRIP_1" in json.dumps(getattr(window._explorer._map, "last_payload"), default=str)
        window._navigation.setCurrentRow(3)
        window._exporter._routes.setPlainText("A")
        window._exporter._destination.setText("A-output.json")
        assert window._exporter.request().route_ids == frozenset({"A"})

        selection[:] = [project_b]
        window._choose_project()
        assert window._opened_project is not None
        assert window._map_mode_combo.currentData() == MapMode.OFFLINE
        route_ids = {
            getattr(window._explorer._routes.itemData(i), "route_id", None)
            for i in range(window._explorer._routes.count())
        }
        assert route_ids == {"R1"}
        assert "A" not in route_ids
        assert window._explorer._trips.count() > 0
        assert "A_TRIP_1" not in " ".join(
            window._explorer._trips.itemText(i) for i in range(window._explorer._trips.count())
        )
        assert window._raw_inspector._filter.text() == ""
        _assert_raw_row(window, trip_id="T1", stop_id="MISSING_STOP", source_row="2")
        window._navigation.setCurrentRow(2)
        assert "INVALID" in window._validation._summary.text()
        assert "A_TRIP_1" not in window._validation._detail.toPlainText()
        assert "A" not in json.dumps(getattr(window._explorer._map, "last_payload"), default=str)
        window._navigation.setCurrentRow(3)
        assert window._exporter.request().route_ids == frozenset()
        assert window._exporter.request().destination == Path(".")
    finally:
        _close_window(application, window)


@pytest.mark.e2e
def test_e2e_07_close_reopen_rebuilds_all_durable_views(
    application: QApplication,
    e2e_runtime: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "reopen-project"
    source = tmp_path / "reopen-source"
    _materialize_fixture(source, "valid_full")
    selection = [project]
    window = MainWindow()
    try:
        _create_project_from_ui(window, project, selection, monkeypatch)
        result = _start_and_wait(
            application, window, InputSource(source, InputSourceKind.DIRECTORY)
        )
        assert result.state is JobState.READY
        artifact = _export_from_ui(window, ExportFormat.JSON, "R1", tmp_path / "exports" / "reopen")
        project_id = window._opened_project.descriptor.project_id  # type: ignore[union-attr]
        feed_id = result.feed_id
        window._close_project()
        assert not (project / ".writer.lock").exists()
        selection[:] = [project]
        window._choose_project()

        assert window._opened_project is not None
        assert window._opened_project.descriptor.project_id == project_id
        with DuckDbUnitOfWork(window._opened_project.database) as unit_of_work:
            feed = unit_of_work.feeds.latest_metadata()
            assert feed is not None
            assert feed.feed_id == feed_id
            assert feed.status is FeedStatus.IMPORTED
            routes = unit_of_work.route_explorer.routes(PageRequest(limit=100)).items
            assert {route.route_id for route in routes} == {"R1", "R2"}
            operations = unit_of_work.operations.list_operations(
                project_id, PageRequest(limit=100)
            ).items
        assert len(operations) == 2
        assert all(operation.status is OperationStatus.COMPLETED for operation in operations)
        assert artifact.is_file()
        assert _assert_manifest_private(artifact, project)["artifact_name"] == artifact.name
        window._navigation.setCurrentRow(1)
        assert window._explorer._routes.count() == 2
        window._navigation.setCurrentRow(2)
        assert any(
            status in window._validation._summary.text()
            for status in ("VALID", "VALID_WITH_WARNINGS")
        )
        _assert_raw_row(window, trip_id="T1", stop_id="S1", source_row="2")
        descriptor = json.loads((project / "project.json").read_text(encoding="utf-8"))
        assert descriptor["project_id"] == project_id
        assert descriptor["feed"]["feed_id"] == feed_id
    finally:
        _close_window(application, window)


@pytest.mark.e2e
def test_e2e_08_subprocess_lock_blocks_second_writer_and_releases_after_exit(
    tmp_path: Path,
) -> None:
    project = tmp_path / "locked-project"
    project.mkdir()
    opened = CreateProject(project).execute()
    opened.close()
    child_code = """
from pathlib import Path
import sys
from gtfs_explorer.application.commands.open_project import OpenProject
opened = OpenProject(Path(sys.argv[1])).execute()
print('READY', flush=True)
input()
opened.close()
"""
    environment = os.environ.copy()
    source_root = str((ROOT / "src").resolve())
    environment["PYTHONPATH"] = os.pathsep.join(
        item for item in (source_root, environment.get("PYTHONPATH", "")) if item
    )
    holder = subprocess.Popen(
        [sys.executable, "-c", child_code, str(project)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=ROOT,
        env=environment,
    )
    ready: list[str] = []
    ready_event = threading.Event()

    def read_ready() -> None:
        assert holder.stdout is not None
        ready.append(holder.stdout.readline().strip())
        ready_event.set()

    reader = threading.Thread(target=read_ready, daemon=True)
    reader.start()
    try:
        assert ready_event.wait(timeout=5), "El proceso titular no confirmó el lock en 5 s."
        assert ready == ["READY"]
        with pytest.raises(ProjectWriterLockedError, match="en uso"):
            OpenProject(project).execute()
    finally:
        if holder.poll() is None:
            try:
                assert holder.stdin is not None
                holder.stdin.write("\n")
                holder.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
        try:
            holder.wait(timeout=5)
        except subprocess.TimeoutExpired:
            holder.terminate()
            holder.wait(timeout=5)
        if holder.stdin is not None:
            holder.stdin.close()
        if holder.stderr is not None:
            holder.stderr.close()
        reader.join(timeout=1)
    with OpenProject(project).execute() as reopened:
        assert reopened.directory == project.resolve()
    assert not (project / ".writer.lock").exists()


@pytest.mark.e2e
def test_e2e_09_safe_recovery_rebuilds_descriptor_and_blocks_destructive_open(
    tmp_path: Path,
) -> None:
    recoverable = tmp_path / "recoverable-project"
    project_id, feed_id = _seed_project(recoverable, "valid_full")
    database_before = (recoverable / "data.duckdb").read_bytes()
    (recoverable / "project.json").write_text("{invalid", encoding="utf-8")

    with OpenProject(recoverable).execute() as reopened:
        assert reopened.descriptor.project_id == project_id
        assert reopened.descriptor.feed_id == feed_id
        with DuckDbUnitOfWork(reopened.database) as unit_of_work:
            assert unit_of_work.feeds.latest_metadata() is not None
            assert unit_of_work.route_explorer.routes(PageRequest(limit=100)).items
    assert (recoverable / "data.duckdb").read_bytes() == database_before
    descriptor = json.loads((recoverable / "project.json").read_text(encoding="utf-8"))
    assert descriptor["project_id"] == project_id
    assert descriptor["feed"]["feed_id"] == feed_id
    snapshots = list((recoverable / "recovery").iterdir())
    assert snapshots
    report = json.loads((snapshots[0] / "recovery-report.json").read_text(encoding="utf-8"))
    assert "recoverable-project" not in json.dumps(report)
    assert "traceback" not in json.dumps(report).casefold()

    unrecoverable = tmp_path / "unrecoverable-project"
    _seed_project(unrecoverable, "valid_core")
    database = unrecoverable / "data.duckdb"
    descriptor_before = (unrecoverable / "project.json").read_bytes()
    database.write_bytes(b"not-a-duckdb")
    database_corrupt = database.read_bytes()
    with pytest.raises(DatabaseCorruptionError, match="corrupta"):
        OpenProject(unrecoverable).execute()
    assert database.read_bytes() == database_corrupt
    assert (unrecoverable / "project.json").read_bytes() == descriptor_before


@pytest.mark.e2e
def test_e2e_10_offline_map_uses_local_pmtiles_keeps_overlay_and_blocks_remote_context(
    application: QApplication,
    e2e_runtime: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "map-project"
    source = tmp_path / "map-source"
    pmtiles = tmp_path / "local-map.pmtiles"
    _materialize_fixture(source, "mini_gtfs_contract")
    _write_raster_pmtiles(pmtiles)
    selection = [project]
    window = MainWindow()
    try:
        _create_project_from_ui(window, project, selection, monkeypatch)
        result = _start_and_wait(
            application, window, InputSource(source, InputSourceKind.DIRECTORY)
        )
        assert result.state is JobState.READY
        window._map_mode_combo.setCurrentIndex(1)
        assert window._map_mode_combo.currentData() == MapMode.OFFLINE
        window._navigation.setCurrentRow(1)
        assert getattr(window._explorer._map, "last_trip_id", None) == "A_TRIP_1"
        overlay_before = json.dumps(getattr(window._explorer._map, "last_payload"), default=str)
        assert "A_TRIP_1" in overlay_before

        monkeypatch.setattr(
            QFileDialog,
            "getOpenFileName",
            lambda *_args, **_kwargs: (str(pmtiles), "PMTiles (*.pmtiles)"),
        )
        window._import_pmtiles()
        assert getattr(window._explorer._map, "managed_package", None) is not None
        assert "Offline" in window._explorer.map_status
        overlay_after = json.dumps(getattr(window._explorer._map, "last_payload"), default=str)
        assert "A_TRIP_1" in overlay_after
        assert "A1" in overlay_after

        policy = MapRequestPolicy(
            MapMode.OFFLINE,
            local_origin="http://127.0.0.1:43123",
        )
        policy.set_active_availability(MapAvailability.LOCAL)
        interceptor = MapNetworkInterceptor(policy)

        class Request:
            def __init__(self, url: str) -> None:
                self.url = url
                self.blocked = False

            def requestUrl(self) -> QUrl:  # noqa: N802 - API Qt
                return QUrl(self.url)

            def block(self, value: bool) -> None:
                self.blocked = value

        local = Request("http://127.0.0.1:43123/session/style.json")
        remote = Request("https://tiles.example/12/1/2.pbf?trip_id=A_TRIP_1")
        interceptor.interceptRequest(local)
        interceptor.interceptRequest(remote)
        assert not local.blocked
        assert remote.blocked
        assert interceptor.blocked_requests == 1
        assert not hasattr(interceptor, "blocked_urls")
    finally:
        _close_window(application, window)


@pytest.mark.e2e
def test_e2e_11_technical_import_error_is_failed_without_fake_ready_state(
    application: QApplication,
    e2e_runtime: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "technical-error-project"
    source = tmp_path / "technical-error.zip"
    with ZipFile(source, "w") as archive:
        archive.writestr("routes.txt", "route_id,route_type\nR1,3\n")
    selection = [project]
    window = MainWindow()
    errors: list[str] = []
    try:
        _create_project_from_ui(window, project, selection, monkeypatch)
        configuration = [(window._opened_project.database, _project_metadata(window))]  # type: ignore[union-attr]
        window._import_command_factory = _configure_factory(
            configuration,
            feed_ids=("technical-failure",),
            job_ids=("technical-failure-job",),
            has_free_space=lambda _required: False,
        )
        monkeypatch.setattr(
            window,
            "_show_error",
            lambda message, **_kwargs: errors.append(str(message)),
        )
        result = _start_and_wait(
            application,
            window,
            InputSource(source, InputSourceKind.ARCHIVE),
        )
        assert result.state is JobState.FAILED
        assert window.ui_state.mode.value == "PROJECT_READY"
        assert not window._import_adapter.is_running
        assert window._import_context_label.text() == ""
        assert not window._progress_bar.isVisible()
        assert errors
        assert str(source) not in " ".join(errors)
        assert "traceback" not in " ".join(errors).casefold()
        with window._opened_project.database.connection() as connection:  # type: ignore[union-attr]
            assert connection.execute("SELECT status FROM feeds").fetchone() == ("FAILED",)
            assert connection.execute("SELECT count(*) FROM gtfs_routes").fetchone() == (0,)
            assert connection.execute("SELECT status FROM operations").fetchone() == (
                OperationStatus.FAILED.value,
            )
        assert window._operation_history._table.rowCount() == 1
        assert window._operation_history._table.item(0, 3).text() == "Fallida"
    finally:
        _close_window(application, window)
