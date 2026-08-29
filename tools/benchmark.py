"""Benchmark formal P1-21: medir, localizar y clasificar sin umbrales rígidos.

Autor: Yeison Arbey Carrillo Lemus.
Todos los derechos reservados.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from gtfs_explorer.application.commands.import_feed import ImportFeed, ImportFeedResult
from gtfs_explorer.application.commands.open_project import OpenProject
from gtfs_explorer.application.jobs.import_job import CancelToken, ImportPhase
from gtfs_explorer.application.queries.map_layers import map_layers_for_trip
from gtfs_explorer.application.queries.raw import RawInspectorQueries
from gtfs_explorer.application.queries.validation import ValidationQueries
from gtfs_explorer.domain.ports import PageRequest
from gtfs_explorer.domain.project import (
    FeedMetadata,
    FeedStatus,
    ImportJobMetadata,
    JobState,
    ProjectMetadata,
    ProjectStatus,
)
from gtfs_explorer.domain.raw import RawQuery, RawSort
from gtfs_explorer.domain.source import InputSource, InputSourceKind, SourceManifest
from gtfs_explorer.domain.spec import ScheduleSpec, load_schedule_spec
from gtfs_explorer.domain.subset import CoreSubset, SubsetSelection, close_core_subset
from gtfs_explorer.domain.validation import (
    ValidationIssueFilter,
    ValidationRuleRegistry,
)
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.infrastructure.duckdb.repositories import DuckDbUnitOfWork
from gtfs_explorer.infrastructure.duckdb.repositories.base import (
    DuckDbCoreSubsetRepository,
    DuckDbGeometryRepository,
    DuckDbRawInspectorRepository,
    DuckDbRouteExplorerRepository,
    DuckDbValidationRepository,
)
from gtfs_explorer.infrastructure.exporting.csv_exporter import CsvExporter
from gtfs_explorer.infrastructure.exporting.geojson_exporter import (
    GeoJsonExporter,
    GeoJsonExportSelection,
)
from gtfs_explorer.infrastructure.exporting.gtfs_subset import (
    MiniGtfsSubsetExporter,
    MiniGtfsTable,
)
from gtfs_explorer.infrastructure.exporting.json_exporter import (
    JsonBundleExporter,
    JsonExportSelection,
)
from gtfs_explorer.infrastructure.filesystem.project_descriptor import (
    ProjectDescriptor,
    save_project_descriptor,
)
from gtfs_explorer.infrastructure.importing.directory_source import DirectorySource
from gtfs_explorer.infrastructure.importing.normalizers.core import CoreNormalizer
from gtfs_explorer.infrastructure.importing.normalizers.geometry import GeometryNormalizer
from gtfs_explorer.infrastructure.importing.normalizers.optional import OptionalNormalizer
from gtfs_explorer.infrastructure.importing.staging_loader import StagingLoader
from gtfs_explorer.infrastructure.validation.best_practices import BestPracticeValidationRule
from gtfs_explorer.infrastructure.validation.engine import ValidationEngine, ValidationRunResult
from gtfs_explorer.infrastructure.validation.fields import FieldValidationRule
from gtfs_explorer.infrastructure.validation.geometry import GeometryValidationRule
from gtfs_explorer.infrastructure.validation.references import ReferenceValidationRule
from gtfs_explorer.infrastructure.validation.structure import StructureValidationRule
from gtfs_explorer.infrastructure.validation.timetable import TimetableValidationRule
from gtfs_explorer.performance import PROFILES, BenchmarkProfile, generate_feed
from gtfs_explorer.product import IDENTITY, runtime_build_id

SPEC = Path(__file__).parents[1] / f"schemas/gtfs_schedule/{IDENTITY.gtfs_spec_revision}/spec.json"
REPOSITORY_ROOT = Path(__file__).parents[1]

SCENARIOS = (
    "generate",
    "zip",
    "workspace",
    "import",
    "validation",
    "reopen",
    "raw",
    "relational",
    "validation_queries",
    "map",
    "csv",
    "json",
    "geojson",
    "mini_gtfs",
    "export",
)
DEFAULT_SCENARIOS = frozenset(SCENARIOS)
DEFAULT_MAX_DURATION = 900.0
NORMALIZED_SETUP_SCENARIOS = frozenset(
    {
        "validation",
        "reopen",
        "relational",
        "validation_queries",
        "map",
        "csv",
        "json",
        "geojson",
        "mini_gtfs",
        "export",
    }
)
CLASSIFICATIONS = {
    "generate": "BENCHMARK_GENERATOR",
    "zip": "BENCHMARK_HARNESS",
    "workspace": "BENCHMARK_HARNESS",
    "import": "PRODUCT_IMPORT",
    "validation": "PRODUCT_VALIDATION",
    "reopen": "PRODUCT_QUERY",
    "raw": "PRODUCT_QUERY",
    "relational": "PRODUCT_QUERY",
    "validation_queries": "PRODUCT_QUERY",
    "map": "PRODUCT_QUERY",
    "csv": "PRODUCT_EXPORT",
    "json": "PRODUCT_EXPORT",
    "geojson": "PRODUCT_EXPORT",
    "mini_gtfs": "PRODUCT_EXPORT",
    "export": "PRODUCT_EXPORT",
}


class EventRecorder:
    """Registra eventos de fase sin emitir datos de máquina ni filas individuales."""

    def __init__(self, *, emit: bool = False) -> None:
        self.started = time.perf_counter()
        self.events: list[dict[str, object]] = []
        self.phases: dict[str, dict[str, float]] = {}
        self._emit = emit

    def record(self, event: str, phase: str | None = None, **values: object) -> None:
        payload: dict[str, object] = {
            "event": event,
            "elapsed": round(time.perf_counter() - self.started, 6),
        }
        if phase is not None:
            payload["phase"] = phase
        payload.update(values)
        self.events.append(payload)
        if self._emit:
            print(
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                file=sys.stderr,
                flush=True,
            )

    def scenario_start(self) -> None:
        self.record("scenario_start")

    def phase_start(self, phase: str) -> float:
        started = time.perf_counter()
        self.record("phase_start", phase)
        start_elapsed = self.events[-1]["elapsed"]
        self.phases[phase] = {"start_elapsed": float(start_elapsed)}
        return started

    def phase_end(self, phase: str, started: float) -> None:
        duration = time.perf_counter() - started
        elapsed = time.perf_counter() - self.started
        self.record("phase_end", phase, duration_seconds=round(duration, 6))
        summary = self.phases.setdefault(phase, {})
        summary["duration_seconds"] = round(duration, 6)
        summary["end_elapsed"] = round(elapsed, 6)

    def measure(self, phase: str, function: Callable[[], object]) -> object:
        started = self.phase_start(phase)
        try:
            return function()
        finally:
            self.phase_end(phase, started)


class ObservedImportFeed(ImportFeed):
    """Instrumentación del harness sobre los límites existentes de ImportFeed."""

    def __init__(self, *args: object, recorder: EventRecorder, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self._recorder = recorder
        self._active_phase: str | None = None
        self._active_started: float | None = None

    def _start(self, phase: ImportPhase, token: CancelToken) -> None:
        if self._active_phase is not None and self._active_started is not None:
            self._recorder.phase_end(self._active_phase, self._active_started)
        super()._start(phase, token)
        self._active_phase = str(phase)
        self._active_started = self._recorder.phase_start(str(phase))

    def execute(self, cancel_token: CancelToken | None = None) -> ImportFeedResult:
        try:
            return super().execute(cancel_token)
        finally:
            if self._active_phase is not None and self._active_started is not None:
                self._recorder.phase_end(self._active_phase, self._active_started)
                self._active_phase = None
                self._active_started = None


class TimedMiniGtfsExporter(MiniGtfsSubsetExporter):
    """Añade solo el tiempo de reimportación al contrato Mini-GTFS existente."""

    def __init__(self, *args: object, recorder: EventRecorder, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self._recorder = recorder

    def _revalidate(
        self, archive: Path, expected: CoreSubset, is_cancelled: Callable[[], bool]
    ) -> None:
        revalidate = super()._revalidate
        self._recorder.measure(
            "mini_gtfs.reimport",
            lambda: revalidate(archive, expected, is_cancelled),
        )


def _profile_metadata(profile: BenchmarkProfile) -> dict[str, object]:
    return {"profile": profile.name, "dataset_counts": profile.counts()}


def _measure(function: Callable[[], object], iterations: int = 1) -> dict[str, object]:
    values: list[float] = []
    last: object = None
    for _ in range(iterations):
        started = time.perf_counter()
        last = function()
        values.append(time.perf_counter() - started)
    result: dict[str, object] = {
        "median_seconds": round(statistics.median(values), 6),
        "min_seconds": round(min(values), 6),
        "max_seconds": round(max(values), 6),
        "iterations": len(values),
    }
    if isinstance(last, dict):
        result.update(last)
    return result


def _database(workspace: Path) -> ProjectDatabase:
    return ProjectDatabase(
        workspace / "data.duckdb",
        workspace / "temp",
        settings=DatabaseSettings(memory_limit="1GB", max_temp_directory_size="1GB", threads=1),
    )


def _directory_size(directory: Path) -> int:
    if not directory.exists():
        return 0
    return sum(
        path.stat().st_size
        for path in directory.rglob("*")
        if path.is_file() and not path.is_symlink()
    )


def _process_memory() -> dict[str, int] | None:
    """Obtiene la memoria del worker sin introducir una dependencia de runtime."""
    if platform.system() != "Windows":
        return None

    class _ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("page_fault_count", ctypes.c_ulong),
            ("peak_working_set_size", ctypes.c_size_t),
            ("working_set_size", ctypes.c_size_t),
            ("quota_peak_paged_pool_usage", ctypes.c_size_t),
            ("quota_paged_pool_usage", ctypes.c_size_t),
            ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
            ("quota_non_paged_pool_usage", ctypes.c_size_t),
            ("pagefile_usage", ctypes.c_size_t),
            ("peak_pagefile_usage", ctypes.c_size_t),
        ]

    try:
        counters = _ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        process = ctypes.windll.kernel32.GetCurrentProcess()  # type: ignore[attr-defined]
        success = ctypes.windll.psapi.GetProcessMemoryInfo(  # type: ignore[attr-defined]
            process, ctypes.byref(counters), counters.cb
        )
    except (AttributeError, OSError):
        return None
    if not success:
        return None
    return {
        "working_set_bytes": int(counters.working_set_size),
        "peak_working_set_bytes": int(counters.peak_working_set_size),
        "pagefile_bytes": int(counters.pagefile_usage),
        "peak_pagefile_bytes": int(counters.peak_pagefile_usage),
    }


def _compress_feed(feed: Path, destination: Path) -> int:
    with ZipFile(destination, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(feed.glob("*.txt"), key=lambda item: item.name.casefold()):
            info = ZipInfo(path.name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, path.read_bytes())
    return destination.stat().st_size


def _manifest(feed: Path) -> SourceManifest:
    return DirectorySource().inventory(InputSource(feed, InputSourceKind.DIRECTORY))


def _project() -> ProjectMetadata:
    return ProjectMetadata("p1-21-project", "P1-21 benchmark", ProjectStatus.READY)


def _save_feed_metadata(
    database: ProjectDatabase, manifest: SourceManifest, spec: ScheduleSpec
) -> None:
    feed = FeedMetadata(
        "p1-21-feed",
        "p1-21-project",
        "feed",
        manifest.manifest_sha256,
        InputSourceKind.DIRECTORY.value,
        spec.revision,
        FeedStatus.IMPORTED,
    )
    with DuckDbUnitOfWork(database) as unit_of_work:
        unit_of_work.projects.save_metadata(_project())
        unit_of_work.feeds.save_metadata(feed)
        unit_of_work.import_jobs.save_metadata(
            ImportJobMetadata("p1-21-job", "p1-21-feed", JobState.READY, "COMMITTING", 1.0)
        )
    project_directory = database.database_path.parent
    save_project_descriptor(
        project_directory / "project.json",
        ProjectDescriptor.from_metadata(_project(), feed, project_directory),
    )


def _prepare_staging(
    database: ProjectDatabase,
    feed: Path,
    spec: ScheduleSpec,
    recorder: EventRecorder,
) -> SourceManifest:
    manifest = recorder.measure("setup.preflight", lambda: _manifest(feed))
    recorder.measure(
        "setup.staging",
        lambda: StagingLoader().load(database, feed, manifest, spec),
    )
    return manifest  # type: ignore[return-value]


def _prepare_normalized(
    database: ProjectDatabase,
    feed: Path,
    spec: ScheduleSpec,
    recorder: EventRecorder,
) -> SourceManifest:
    manifest = _prepare_staging(database, feed, spec, recorder)
    recorder.measure("setup.normalizing.core", lambda: CoreNormalizer().normalize(database, spec))
    recorder.measure(
        "setup.normalizing.geometry", lambda: GeometryNormalizer().normalize(database, spec)
    )
    recorder.measure(
        "setup.normalizing.optional", lambda: OptionalNormalizer().normalize(database, spec)
    )
    recorder.measure("setup.metadata", lambda: _save_feed_metadata(database, manifest, spec))
    return manifest


def _validate(
    database: ProjectDatabase,
    manifest: SourceManifest,
    feed: Path,
    spec: ScheduleSpec,
) -> ValidationRunResult:
    registry = ValidationRuleRegistry()
    registry.register(StructureValidationRule(manifest, feed, spec))
    with database.connection() as connection:
        registry.register(FieldValidationRule(connection, spec))
        registry.register(ReferenceValidationRule(connection, spec))
        registry.register(TimetableValidationRule(connection))
        registry.register(GeometryValidationRule(connection))
        registry.register(BestPracticeValidationRule(connection))
        return ValidationEngine(registry).execute(
            connection,
            feed_id="p1-21-feed",
            batch_id="p1-21-validation",
        )


def _run_full_import(
    database: ProjectDatabase, feed: Path, spec: ScheduleSpec, recorder: EventRecorder
) -> ImportFeedResult:
    command = ObservedImportFeed(
        database,
        _project(),
        InputSource(feed, InputSourceKind.DIRECTORY),
        spec,
        job_id="p1-21-job",
        feed_id="p1-21-feed",
        recorder=recorder,
    )
    result = recorder.measure("product_import", command.execute)
    return result  # type: ignore[return-value]


def _open_and_close(database: ProjectDatabase) -> None:
    with OpenProject(database.database_path.parent, settings=database.settings).execute():
        pass


def _query_raw(database: ProjectDatabase, spec: ScheduleSpec) -> dict[str, object]:
    with database.connection() as connection:
        page = RawInspectorQueries(DuckDbRawInspectorRepository(connection, spec)).query(
            RawQuery(
                "stops.txt",
                ("stop_id", "stop_name"),
                sort=(RawSort("stop_id"),),
                page_size=100,
            )
        )
    return {"rows": len(page.rows), "has_next_page": page.next_page_token is not None}


def _query_relational(database: ProjectDatabase) -> dict[str, object]:
    with database.connection() as connection:
        repository = DuckDbRouteExplorerRepository(connection)
        routes = repository.routes(PageRequest(limit=100))
        services = repository.services_for_route("R0", PageRequest(limit=100))
        timeline = repository.trip_timeline("T0_0", PageRequest(limit=100))
    return {"routes": routes.total, "services": services.total, "timeline_rows": timeline.total}


def _query_validation(database: ProjectDatabase) -> dict[str, object]:
    with database.connection() as connection:
        queries = ValidationQueries(DuckDbValidationRepository(connection))
        page = queries.issues(ValidationIssueFilter(feed_id="p1-21-feed"), PageRequest(limit=100))
        files = queries.files(feed_id="p1-21-feed")
    return {"rows": len(page.items), "total_rows": page.total, "files": len(files)}


def _query_map(database: ProjectDatabase) -> dict[str, object]:
    with database.connection() as connection:
        geometry = DuckDbGeometryRepository(connection).trip_shape("T0_0")
        layers = map_layers_for_trip(geometry)
    return {
        "shape_points": len(geometry.coordinates),
        "stop_points": len(geometry.stops),
        "shape_features": len(layers.shapes.get("features", [])),
        "stop_features": len(layers.stops.get("features", [])),
    }


def _rows_for_csv(
    database: ProjectDatabase,
) -> tuple[tuple[str, ...], tuple[tuple[str | None, ...], ...]]:
    with database.connection() as connection:
        rows = connection.execute(
            "SELECT route_id, route_short_name, route_type FROM gtfs_routes "
            "ORDER BY route_id, source_row"
        ).fetchall()
    return (
        ("route_id", "route_short_name", "route_type"),
        tuple(tuple(None if value is None else str(value) for value in row) for row in rows),
    )


def _export_csv(database: ProjectDatabase, destination: Path) -> dict[str, object]:
    headers, rows = _rows_for_csv(database)
    manifest = CsvExporter().write(destination, headers=headers, rows=rows, overwrite=True)
    return {"artifact_name": manifest.artifact_name, "size_bytes": manifest.size_bytes}


def _export_json(database: ProjectDatabase, destination: Path) -> dict[str, object]:
    with database.connection() as connection:
        manifest = JsonBundleExporter(now=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc)).write(
            connection,
            destination,
            feed_id="p1-21-feed",
            selection=JsonExportSelection(frozenset({"R0"})),
            overwrite=True,
        )
    return {"artifact_name": manifest.artifact_name, "size_bytes": manifest.size_bytes}


def _export_geojson(database: ProjectDatabase, destination: Path) -> dict[str, object]:
    with database.connection() as connection:
        manifest = GeoJsonExporter().write(
            connection,
            destination,
            selection=GeoJsonExportSelection(frozenset({"R0"})),
            include_bbox=True,
            overwrite=True,
        )
    return {"artifact_name": manifest.artifact_name, "size_bytes": manifest.size_bytes}


def _mini_tables(
    connection: object, spec: ScheduleSpec, subset: CoreSubset
) -> tuple[MiniGtfsTable, ...]:
    filters = (
        ("agency.txt", "gtfs_agency", "agency_id", subset.agency_ids, "agency_id, source_row"),
        ("routes.txt", "gtfs_routes", "route_id", subset.route_ids, "route_id, source_row"),
        ("trips.txt", "gtfs_trips", "trip_id", subset.trip_ids, "trip_id, source_row"),
        ("stops.txt", "gtfs_stops", "stop_id", subset.stop_ids, "stop_id, source_row"),
        (
            "stop_times.txt",
            "gtfs_stop_times",
            "trip_id",
            subset.trip_ids,
            "trip_id, stop_sequence NULLS LAST, source_row",
        ),
        (
            "calendar.txt",
            "gtfs_calendar",
            "service_id",
            subset.calendar_service_ids,
            "service_id, source_row",
        ),
    )
    tables: list[MiniGtfsTable] = []
    for filename, table, column, values, order_by in filters:
        if not values:
            continue
        placeholders = ",".join("?" for _ in values)
        rows = connection.execute(  # type: ignore[attr-defined]
            f"SELECT raw_values FROM {table} WHERE {column} IN ({placeholders}) "
            f"ORDER BY {order_by}",
            sorted(values),
        ).fetchall()
        headers = tuple(spec.files[filename].fields)
        tables.append(
            MiniGtfsTable(
                filename,
                headers,
                tuple(tuple(json.loads(row[0]).get(header) for header in headers) for row in rows),
            )
        )
    if subset.trip_ids:
        placeholders = ",".join("?" for _ in subset.trip_ids)
        rows = connection.execute(  # type: ignore[attr-defined]
            "SELECT raw_values FROM gtfs_shapes WHERE shape_id IN "
            f"(SELECT DISTINCT shape_id FROM gtfs_trips WHERE trip_id IN ({placeholders}) "
            "AND shape_id IS NOT NULL) ORDER BY shape_id, shape_pt_sequence NULLS LAST, source_row",
            sorted(subset.trip_ids),
        ).fetchall()
        if rows:
            filename = "shapes.txt"
            headers = tuple(spec.files[filename].fields)
            tables.append(
                MiniGtfsTable(
                    filename,
                    headers,
                    tuple(
                        tuple(json.loads(row[0]).get(header) for header in headers) for row in rows
                    ),
                )
            )
    return tuple(tables)


def _export_mini_gtfs(
    database: ProjectDatabase, spec: ScheduleSpec, destination: Path, recorder: EventRecorder
) -> dict[str, object]:
    with database.connection() as connection:
        source = DuckDbCoreSubsetRepository(connection).core_subset_source()
        subset = close_core_subset(source, SubsetSelection(frozenset({"R0"})))
        tables = _mini_tables(connection, spec, subset)
    manifest = TimedMiniGtfsExporter(spec, recorder=recorder).write(
        destination,
        tables,
        expected=subset,
        overwrite=True,
    )
    return {
        "artifact_name": manifest.artifact_name,
        "size_bytes": manifest.size_bytes,
        "subset_counts": dict(subset.report.counts),
    }


def _run_exports(
    database: ProjectDatabase, spec: ScheduleSpec, output: Path, recorder: EventRecorder
) -> dict[str, object]:
    return {
        "csv": recorder.measure(
            "export.csv", lambda: _export_csv(database, output / "routes-faithful.csv")
        ),
        "json": recorder.measure(
            "export.json", lambda: _export_json(database, output / "route-r0.json")
        ),
        "geojson": recorder.measure(
            "export.geojson", lambda: _export_geojson(database, output / "route-r0.geojson")
        ),
        "mini_gtfs": recorder.measure(
            "export.mini_gtfs",
            lambda: _export_mini_gtfs(database, spec, output / "route-r0.zip", recorder),
        ),
    }


def _record_resource_metrics(
    report: dict[str, object],
    profile: BenchmarkProfile,
    recorder: EventRecorder,
    feed: Path,
    workspace: Path,
    output: Path,
) -> None:
    report["storage"] = {
        "feed_bytes": _directory_size(feed),
        "workspace_bytes": _directory_size(workspace),
        "output_bytes": _directory_size(output),
    }
    storage = report["storage"]
    if isinstance(storage, dict):
        storage["total_bytes"] = sum(
            int(value) for value in storage.values() if isinstance(value, int)
        )

    dataset_rows = sum(profile.counts().values())
    phase_rows = {
        "generate": dataset_rows,
        "STAGING": dataset_rows,
        "setup.staging": dataset_rows,
        "NORMALIZING": dataset_rows,
        "setup.normalizing.core": dataset_rows,
        "VALIDATING": dataset_rows,
        "validation": dataset_rows,
        "setup.validation": dataset_rows,
    }
    throughput: dict[str, object] = {
        "basis": "sum(dataset_counts)",
        "rows": dataset_rows,
        "rows_per_second": {},
    }
    rows_per_second = throughput["rows_per_second"]
    assert isinstance(rows_per_second, dict)
    for phase, rows in phase_rows.items():
        phase_result = recorder.phases.get(phase)
        if phase_result is None:
            continue
        duration = phase_result.get("duration_seconds")
        if isinstance(duration, (int, float)) and duration > 0:
            rows_per_second[phase] = round(rows / duration, 3)
    if rows_per_second:
        report["throughput"] = throughput

    memory = _process_memory()
    report["memory"] = memory if memory is not None else {"available": False}


def _run_single(
    profile_name: str,
    scenario: str,
    *,
    root: Path | None = None,
    emit_events: bool = False,
) -> dict[str, object]:
    profile = PROFILES[profile_name]
    recorder = EventRecorder(emit=emit_events)
    recorder.scenario_start()
    own_root: tempfile.TemporaryDirectory[str] | None = None
    if root is None:
        own_root = tempfile.TemporaryDirectory(prefix="gtfs-p1-21-")
        working_root = Path(own_root.name)
    else:
        working_root = root
    feed = working_root / "feed"
    workspace = working_root / "workspace"
    output = working_root / "output"
    output.mkdir(parents=True, exist_ok=True)
    spec = load_schedule_spec(SPEC)
    report: dict[str, object] = {
        **_profile_metadata(profile),
        "scenario": scenario,
        "classification": CLASSIFICATIONS[scenario],
        "status": "PASS",
    }
    try:
        if scenario == "workspace":
            database = _database(workspace)
            recorder.measure("workspace", database.initialize)
            report["schema_version"] = database.validate_compatible()
        else:
            preparation = recorder.measure("generate", lambda: generate_feed(feed, profile))
            report["preparation"] = {"counts": preparation}
            report["feed_file_count"] = len(tuple(feed.glob("*.txt")))
            if scenario == "generate":
                pass
            elif scenario == "zip":
                report["zip_size_bytes"] = recorder.measure(
                    "zip", lambda: _compress_feed(feed, output / "feed.zip")
                )
            else:
                database = _database(workspace)
                recorder.measure("workspace", database.initialize)
                if scenario == "import":
                    result = _run_full_import(database, feed, spec, recorder)
                    report["product_state"] = str(result.state)
                    report["issue_count"] = result.issue_count
                    report["import_result"] = str(result.state)
                    if result.state is not JobState.READY:
                        report["status"] = "ERROR"
                elif scenario == "raw":
                    _prepare_staging(database, feed, spec, recorder)
                    report["query"] = recorder.measure(
                        "query.raw", lambda: _measure(lambda: _query_raw(database, spec), 5)
                    )
                elif scenario in NORMALIZED_SETUP_SCENARIOS:
                    manifest = _prepare_normalized(database, feed, spec, recorder)
                    if scenario == "validation":
                        validation = recorder.measure(
                            "validation", lambda: _validate(database, manifest, feed, spec)
                        )
                        report["validation_state"] = str(validation.state)
                        report["issue_count"] = validation.total_issue_count
                        report["validation"] = {
                            "batch_id": validation.batch_id,
                            "state": str(validation.state),
                            "total_issue_count": validation.total_issue_count,
                            "stored_issue_count": validation.stored_issue_count,
                            "omitted_issue_count": validation.omitted_issue_count,
                        }
                    elif scenario == "reopen":
                        report["reopen"] = recorder.measure(
                            "open.reopen", lambda: _measure(lambda: _open_and_close(database), 3)
                        )
                    elif scenario == "relational":
                        report["query"] = recorder.measure(
                            "query.relational",
                            lambda: _measure(lambda: _query_relational(database), 5),
                        )
                    elif scenario == "validation_queries":
                        recorder.measure(
                            "setup.validation",
                            lambda: _validate(database, manifest, feed, spec),
                        )
                        report["query"] = recorder.measure(
                            "query.validation",
                            lambda: _measure(lambda: _query_validation(database), 5),
                        )
                    elif scenario == "map":
                        report["query"] = recorder.measure(
                            "query.map", lambda: _measure(lambda: _query_map(database), 3)
                        )
                    elif scenario == "csv":
                        report["export"] = recorder.measure(
                            "export.csv",
                            lambda: _export_csv(database, output / "routes-faithful.csv"),
                        )
                    elif scenario == "json":
                        report["export"] = recorder.measure(
                            "export.json", lambda: _export_json(database, output / "route-r0.json")
                        )
                    elif scenario == "geojson":
                        report["export"] = recorder.measure(
                            "export.geojson",
                            lambda: _export_geojson(database, output / "route-r0.geojson"),
                        )
                    elif scenario == "mini_gtfs":
                        report["export"] = recorder.measure(
                            "export.mini_gtfs",
                            lambda: _export_mini_gtfs(
                                database, spec, output / "route-r0.zip", recorder
                            ),
                        )
                    elif scenario == "export":
                        report["exports"] = _run_exports(database, spec, output, recorder)
    except Exception as error:
        report["status"] = "ERROR"
        report["error_type"] = type(error).__name__
    finally:
        report["events"] = recorder.events
        report["phases"] = recorder.phases
        report["elapsed_seconds"] = round(time.perf_counter() - recorder.started, 6)
        _record_resource_metrics(report, profile, recorder, feed, workspace, output)
        if own_root is not None:
            own_root.cleanup()
    return report


def _event_lines(stderr: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for line in stderr.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("event"), str):
            events.append(value)
    return events


def _phases_from_events(events: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    phases: dict[str, dict[str, object]] = {}
    for event in events:
        phase = event.get("phase")
        if not isinstance(phase, str):
            continue
        if event.get("event") == "phase_start":
            phases[phase] = {
                "start_elapsed": event.get("elapsed"),
                "status": "RUNNING",
            }
        elif event.get("event") == "phase_end":
            summary = phases.setdefault(phase, {})
            summary.pop("status", None)
            summary["duration_seconds"] = event.get("duration_seconds")
            summary["end_elapsed"] = event.get("elapsed")
    return phases


def _timeout_report(
    profile_name: str, scenario: str, elapsed: float, stderr: str
) -> dict[str, object]:
    events = _event_lines(stderr)
    return {
        **_profile_metadata(PROFILES[profile_name]),
        "scenario": scenario,
        "classification": CLASSIFICATIONS[scenario],
        "status": "TIMEOUT",
        "elapsed_seconds": round(elapsed, 6),
        "events": events,
        "phases": _phases_from_events(events),
        "storage": {"available": False, "reason": "worker_terminated_before_final_metrics"},
        "memory": {"available": False},
    }


def _run_isolated_scenario(
    profile_name: str, scenario: str, max_duration: float
) -> dict[str, object]:
    root = Path(tempfile.mkdtemp(prefix="gtfs-p1-21-worker-"))
    command = [
        sys.executable,
        "-u",
        str(Path(__file__).resolve()),
        "--worker",
        "--profile",
        profile_name,
        "--scenario",
        scenario,
        "--temp-root",
        str(root),
    ]
    started = time.perf_counter()
    process = subprocess.Popen(
        command,
        cwd=REPOSITORY_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    worker_stdout = ""
    stderr = ""
    try:
        worker_stdout, stderr = process.communicate(timeout=max_duration)
    except subprocess.TimeoutExpired:
        process.kill()
        worker_stdout, stderr = process.communicate()
        return _timeout_report(profile_name, scenario, time.perf_counter() - started, stderr)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    try:
        result = json.loads(worker_stdout)
    except json.JSONDecodeError:
        events = _event_lines(stderr)
        return {
            **_profile_metadata(PROFILES[profile_name]),
            "scenario": scenario,
            "classification": CLASSIFICATIONS[scenario],
            "status": "ERROR",
            "error_type": "WorkerOutputError",
            "events": events,
            "phases": _phases_from_events(events),
        }
    if not isinstance(result, dict):
        events = _event_lines(stderr)
        return {
            **_profile_metadata(PROFILES[profile_name]),
            "scenario": scenario,
            "classification": CLASSIFICATIONS[scenario],
            "status": "ERROR",
            "error_type": "WorkerOutputError",
            "events": events,
            "phases": _phases_from_events(events),
        }
    return result


def _base_report(profile_name: str, results: dict[str, dict[str, object]]) -> dict[str, object]:
    profile = PROFILES[profile_name]
    report: dict[str, object] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "product": IDENTITY.name,
        "app_version": IDENTITY.version,
        "build_id": runtime_build_id(),
        "gtfs_spec_revision": IDENTITY.gtfs_spec_revision,
        "python_version": sys.version.split()[0],
        "duckdb_version": __import__("duckdb").__version__,
        "platform": {
            "os": platform.system(),
            "release": platform.release(),
            "architecture": platform.machine(),
            "cpu_logical": os.cpu_count(),
        },
        **_profile_metadata(profile),
        "scenarios": results,
        "import_result": results.get("import", {}).get("product_state"),
    }
    zip_result = results.get("zip")
    if zip_result is not None:
        report["zip_size_bytes"] = zip_result.get("zip_size_bytes")
    return report


def _run_matrix_direct(profile_name: str, scenarios: set[str]) -> dict[str, object]:
    results = {scenario: _run_single(profile_name, scenario) for scenario in sorted(scenarios)}
    return _base_report(profile_name, results)


def _run_matrix_isolated(
    profile_name: str, scenarios: set[str], max_duration: float
) -> dict[str, object]:
    results: dict[str, dict[str, object]] = {}
    for scenario in sorted(scenarios):
        results[scenario] = _run_isolated_scenario(profile_name, scenario, max_duration)
    return _base_report(profile_name, results)


def run(
    profile_name: str, scenarios: set[str] | None = None, *, max_duration: float | None = None
) -> dict[str, object]:
    """Ejecuta escenarios, individualmente cuando se solicita un límite."""
    selected = set(DEFAULT_SCENARIOS) if scenarios is None else set(scenarios)
    unknown = selected - set(SCENARIOS)
    if unknown:
        raise ValueError(f"Escenarios desconocidos: {', '.join(sorted(unknown))}.")
    if max_duration is None:
        return _run_matrix_direct(profile_name, selected)
    if max_duration <= 0:
        raise ValueError("El límite por escenario debe ser positivo.")
    return _run_matrix_isolated(profile_name, selected, max_duration)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=sorted(PROFILES), default="small")
    parser.add_argument(
        "--scenario",
        action="append",
        choices=SCENARIOS,
        help="Puede repetirse; cada escenario se ejecuta en un temporal aislado.",
    )
    parser.add_argument(
        "--max-duration",
        type=float,
        default=DEFAULT_MAX_DURATION,
        help="Límite en segundos por escenario (por defecto: 900).",
    )
    parser.add_argument(
        "--json", type=Path, help="Escribe el resultado fuera del workspace temporal."
    )
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--temp-root", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    selected = set(args.scenario) if args.scenario else set(DEFAULT_SCENARIOS)
    if args.worker:
        if len(selected) != 1 or args.temp_root is None:
            parser.error("El worker requiere exactamente un escenario y un temporal.")
        report = _run_single(
            args.profile,
            next(iter(selected)),
            root=args.temp_root,
            emit_events=True,
        )
    else:
        report = run(args.profile, selected, max_duration=args.max_duration)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    scenarios_report = report.get("scenarios", {})
    if isinstance(scenarios_report, dict) and any(
        isinstance(value, dict) and value.get("status") == "ERROR"
        for value in scenarios_report.values()
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
