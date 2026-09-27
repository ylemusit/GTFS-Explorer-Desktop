"""P1-15: regresión contractual integral de las exportaciones productivas."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from gtfs_explorer.application.commands.import_feed import ImportFeed
from gtfs_explorer.application.editor_session import EditorSession
from gtfs_explorer.application.exporting import FeedExportLifecycle
from gtfs_explorer.domain.exporting import ExportDestinationError, ExportError
from gtfs_explorer.domain.operations import (
    OperationDisplayStatus,
    OperationStatus,
    OperationType,
    display_status,
)
from gtfs_explorer.domain.ports import PageRequest
from gtfs_explorer.domain.project import JobState, ProjectMetadata, ProjectStatus
from gtfs_explorer.domain.source import InputSource, InputSourceKind
from gtfs_explorer.domain.spec import load_schedule_spec
from gtfs_explorer.infrastructure.duckdb.database import ProjectDatabase
from gtfs_explorer.infrastructure.duckdb.repositories import DuckDbUnitOfWork
from gtfs_explorer.infrastructure.exporting.atomic_output import AtomicOutputWriter
from gtfs_explorer.presentation.desktop.exporter import (
    ExportFormat,
    ExportRequest,
    suggest_export_filename,
)
from gtfs_explorer.presentation.desktop.exporter.widget import _format_help
from gtfs_explorer.presentation.desktop.main_window import MainWindow
from tests.helpers.export_contract import (
    EXPORT_CAPABILITIES,
    ExportCapability,
    PreparedContractFeed,
    make_database,
    prepare_contract_feed,
)

EXPECTED_MINI_FILES = {
    "agency.txt",
    "attributions.txt",
    "calendar.txt",
    "calendar_dates.txt",
    "feed_info.txt",
    "frequencies.txt",
    "routes.txt",
    "shapes.txt",
    "stop_times.txt",
    "stops.txt",
    "transfers.txt",
    "trips.txt",
}


class _ProductiveExportHarness:
    """Ejecuta el compositor real sin crear una ventana Qt ni un mapa."""

    _export_feed = MainWindow._export_feed
    _write_feed_export = MainWindow._write_feed_export
    _write_revision_export = MainWindow._write_revision_export
    _mini_gtfs_tables = staticmethod(MainWindow._mini_gtfs_tables)

    def __init__(self, prepared: PreparedContractFeed) -> None:
        self._opened_project = SimpleNamespace(database=prepared.database)

    def _refresh_operation_history(self) -> None:
        pass


def _request(
    capability: ExportCapability,
    root: Path,
    *,
    prefix: str | None = None,
    spreadsheet_safe: bool = False,
) -> ExportRequest:
    suggested = suggest_export_filename(
        capability.format,
        route_ids={"A"},
        spreadsheet_safe=spreadsheet_safe,
    )
    if prefix is not None:
        suffix = (
            ("-spreadsheet-safe.csv" if spreadsheet_safe else "-faithful.csv")
            if capability.format is ExportFormat.CSV
            else capability.extension
        )
        suggested = f"{prefix}{suffix}"
    return ExportRequest(
        capability.format,
        root / suggested,
        route_ids=frozenset({"A"}),
        spreadsheet_safe=spreadsheet_safe,
    )


def _history_item(prepared: PreparedContractFeed, artifact_name: str | None = None) -> object:
    with DuckDbUnitOfWork(prepared.database) as unit_of_work:
        items = unit_of_work.operations.list_operations(
            prepared.project_id,
            PageRequest(limit=100),
            OperationType.EXPORT,
        ).items
    if artifact_name is None:
        assert len(items) == 1
        return items[0]
    matches = [item for item in items if item.artifact_name == artifact_name]
    assert len(matches) == 1
    return matches[0]


def _raw_export_detail(database: ProjectDatabase, operation_id: str) -> tuple[object, ...]:
    with database.connection() as connection:
        row = connection.execute(
            "SELECT o.operation_type, o.status, o.error_code, d.feed_id, "
            "d.export_format, d.artifact_name, d.artifact_sha256, d.artifact_size_bytes "
            "FROM operations o JOIN operation_export_details d "
            "ON d.operation_id = o.operation_id WHERE o.operation_id = ?",
            [operation_id],
        ).fetchone()
    assert row is not None
    return tuple(row)


def _assert_ledger_has_no_local_leaks(prepared: PreparedContractFeed) -> None:
    with prepared.database.connection() as connection:
        rows = connection.execute(
            "SELECT CAST(operation_id AS VARCHAR), CAST(project_id AS VARCHAR), "
            "CAST(operation_type AS VARCHAR), CAST(status AS VARCHAR), "
            "CAST(error_code AS VARCHAR), CAST(started_at AS VARCHAR) FROM operations "
            "UNION ALL "
            "SELECT CAST(operation_id AS VARCHAR), CAST(feed_id AS VARCHAR), "
            "CAST(export_format AS VARCHAR), CAST(artifact_name AS VARCHAR), "
            "CAST(artifact_sha256 AS VARCHAR), CAST(artifact_size_bytes AS VARCHAR) "
            "FROM operation_export_details"
        ).fetchall()
    _assert_no_local_leaks(json.dumps(rows, default=str).encode("utf-8"), prepared)


def _assert_manifest(
    capability: ExportCapability,
    destination: Path,
    manifest: object,
    prepared: PreparedContractFeed,
) -> dict[str, object]:
    assert manifest.artifact_name == destination.name  # type: ignore[attr-defined]
    assert manifest.manifest_name == f"{destination.name}.manifest.json"  # type: ignore[attr-defined]
    manifest_path = destination.with_name(manifest.manifest_name)  # type: ignore[attr-defined]
    assert manifest_path.is_file()
    manifest_bytes = manifest_path.read_bytes()
    _assert_no_local_leaks(manifest_bytes, prepared)
    payload = json.loads(manifest_bytes.decode("utf-8"))
    assert payload["artifact_name"] == destination.name
    assert payload["schema_version"] == 1
    assert payload["sha256"] == hashlib.sha256(destination.read_bytes()).hexdigest()
    assert payload["size_bytes"] == destination.stat().st_size
    if capability.manifest_metadata_keys:
        assert set(payload["metadata"]) == set(capability.manifest_metadata_keys)
    else:
        assert "metadata" not in payload
    return payload


def _assert_no_local_leaks(payload: bytes, prepared: PreparedContractFeed) -> None:
    private_tokens = (
        str(prepared.source_directory).encode("utf-8"),
        str(prepared.database.database_path).encode("utf-8"),
        Path.home().name.encode("utf-8"),
    )
    for token in private_tokens:
        assert token not in payload
    lowered = payload.lower()
    assert b"traceback" not in lowered
    assert b"secret" not in lowered


def _zip_rows(archive: ZipFile, filename: str) -> list[dict[str, str]]:
    text = archive.read(filename).decode("utf-8")
    return list(csv.DictReader(io.StringIO(text, newline="")))


def _assert_json_artifact(destination: Path, prepared: PreparedContractFeed) -> None:
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["selection"] == {"route_ids": ["A"], "trip_ids": [], "service_ids": []}
    assert [route["route_id"] for route in payload["routes"]] == ["A"]
    assert payload["routes"][0]["route_type"] == 715
    assert {trip["trip_id"] for trip in payload["trips"]} == {"A_TRIP_1", "A_TRIP_2"}
    assert {trip["service_id"] for trip in payload["trips"]} == {"S_A", "S_SPECIAL"}
    assert {stop["stop_id"] for stop in payload["stops"]} == {"SHARED", "A1", "A2"}
    shared_stop = next(stop for stop in payload["stops"] if stop["stop_id"] == "SHARED")
    assert shared_stop["parent_station"] == "STA"
    assert "B_ONLY" not in json.dumps(payload, ensure_ascii=False)
    assert payload["metadata"]["frequencies"][0]["start_time_lexeme"] == "25:00:00"
    assert payload["routes"][0]["short_name"] == "Línea Á"
    assert shared_stop["name"] == "Parada Ñ"
    assert any(
        event["arrival"] == "24:10:00" for trip in payload["trips"] for event in trip["stop_times"]
    )
    assert "source_row" not in json.dumps(payload, ensure_ascii=False)
    _assert_no_local_leaks(destination.read_bytes(), prepared)


def _assert_geojson_artifact(destination: Path, prepared: PreparedContractFeed) -> None:
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["type"] == "FeatureCollection"
    assert len(payload["features"]) == 4
    stop_features = {
        feature["properties"]["stop_id"]: feature
        for feature in payload["features"]
        if feature["properties"]["feature_kind"] == "stop"
    }
    assert set(stop_features) == {"SHARED", "A1", "A2"}
    assert stop_features["SHARED"]["geometry"] == {
        "type": "Point",
        "coordinates": [-5.801, 43.101],
    }
    shape_features = [
        feature
        for feature in payload["features"]
        if feature["properties"]["feature_kind"] == "shape"
    ]
    assert len(shape_features) == 1
    shape = shape_features[0]
    assert shape["properties"]["shape_id"] == "SH_A"
    assert shape["properties"]["geometry_source"] == "original"
    assert shape["geometry"] == {
        "type": "LineString",
        "coordinates": [[-5.801, 43.101], [-5.803, 43.103]],
    }
    assert all(
        "B_ONLY" not in json.dumps(feature, ensure_ascii=False) for feature in payload["features"]
    )
    assert all(
        "SH_B" not in json.dumps(feature, ensure_ascii=False) for feature in payload["features"]
    )
    # source_file/source_row son procedencia pública del contrato GeoJSON actual,
    # no una ruta interna: se comprueba que son basenames y filas físicas válidas.
    assert all("source_file" in feature["properties"] for feature in payload["features"])
    assert all(
        isinstance(feature["properties"]["source_row"], int) for feature in payload["features"]
    )
    _assert_no_local_leaks(destination.read_bytes(), prepared)


def _assert_csv_artifact(destination: Path, prepared: PreparedContractFeed) -> None:
    raw = destination.read_bytes()
    assert raw.startswith(b"route_id,route_short_name,route_long_name,route_type\r\n")
    text = raw.decode("utf-8")
    rows = list(csv.reader(io.StringIO(text, newline="")))
    assert rows == [
        ["route_id", "route_short_name", "route_long_name", "route_type"],
        ["A", "Línea Á", "Ruta A, UTF-8", "715"],
    ]
    assert '"Ruta A, UTF-8"' in text
    assert "source_row" not in text
    _assert_no_local_leaks(raw, prepared)


def _assert_mini_gtfs_artifact(destination: Path, prepared: PreparedContractFeed) -> None:
    with ZipFile(destination) as archive:
        assert set(archive.namelist()) == EXPECTED_MINI_FILES
        assert all("/" not in name and "\\" not in name for name in archive.namelist())
        routes = _zip_rows(archive, "routes.txt")
        assert [(row["route_id"], row["route_type"]) for row in routes] == [("A", "715")]
        trips = _zip_rows(archive, "trips.txt")
        assert {row["trip_id"] for row in trips} == {"A_TRIP_1", "A_TRIP_2"}
        assert {row["service_id"] for row in trips} == {"S_A", "S_SPECIAL"}
        stop_times = _zip_rows(archive, "stop_times.txt")
        assert len(stop_times) == 5
        assert [row["stop_id"] for row in stop_times if row["trip_id"] == "A_TRIP_1"] == [
            "SHARED",
            "A1",
            "SHARED",
        ]
        assert "24:10:00" in {row["arrival_time"] for row in stop_times}
        assert sum(row["stop_id"] == "SHARED" for row in stop_times) == 3
        stops = _zip_rows(archive, "stops.txt")
        assert {row["stop_id"] for row in stops} == {"STA", "SHARED", "A1", "A2"}
        assert any(row["stop_name"] == "Estación Ñ" for row in stops)
        assert {row["shape_id"] for row in _zip_rows(archive, "shapes.txt")} == {"SH_A"}
        assert {row["trip_id"] for row in _zip_rows(archive, "frequencies.txt")} == {"A_TRIP_1"}
        assert _zip_rows(archive, "frequencies.txt")[0]["start_time"] == "25:00:00"
        assert {row["to_route_id"] for row in _zip_rows(archive, "transfers.txt")} == {"A"}
        assert {row["service_id"] for row in _zip_rows(archive, "calendar.txt")} == {"S_A"}
        assert {row["service_id"] for row in _zip_rows(archive, "calendar_dates.txt")} == {
            "S_SPECIAL"
        }
        assert {row["attribution_id"] for row in _zip_rows(archive, "attributions.txt")} == {
            "GLOBAL",
            "A_ATTR",
        }
        archive_bytes = b"".join(archive.read(name) for name in archive.namelist())
    assert b"source_row" not in archive_bytes
    assert b"B_ONLY" not in archive_bytes
    _assert_no_local_leaks(destination.read_bytes(), prepared)

    target = make_database(destination.parent / "mini-reimport")
    result = ImportFeed(
        target,
        ProjectMetadata("mini-target", "Mini-GTFS target", ProjectStatus.READY),
        InputSource(destination, InputSourceKind.ARCHIVE),
        load_schedule_spec(
            Path(__file__).resolve().parents[1]
            / "schemas"
            / "gtfs_schedule"
            / "2026-04-27"
            / "spec.json"
        ),
        job_id="mini-target-job",
        feed_id="mini-target-feed",
    ).execute()
    assert result.state is JobState.READY
    assert result.issue_count == 0
    with target.connection() as connection:
        assert connection.execute("SELECT route_id, route_type FROM gtfs_routes").fetchall() == [
            ("A", 715)
        ]
        assert connection.execute("SELECT count(*) FROM gtfs_stop_times").fetchone() == (5,)
        assert connection.execute(
            "SELECT count(*) FROM gtfs_stop_times WHERE stop_id = 'SHARED'"
        ).fetchone() == (3,)
        assert connection.execute(
            "SELECT count(*) FROM gtfs_stops WHERE stop_id = 'B_ONLY'"
        ).fetchone() == (0,)
        assert connection.execute("SELECT status FROM validation_runs").fetchone() == ("VALID",)
        assert connection.execute("SELECT status FROM feeds").fetchone() == ("IMPORTED",)


def _assert_artifact(
    capability: ExportCapability, destination: Path, prepared: PreparedContractFeed
) -> None:
    assertions: dict[str, Callable[[Path, PreparedContractFeed], None]] = {
        "json_bundle": _assert_json_artifact,
        "geojson_feature_collection": _assert_geojson_artifact,
        "csv_route_view": _assert_csv_artifact,
        "mini_gtfs_zip": _assert_mini_gtfs_artifact,
    }
    assertions[capability.expected_artifact_kind](destination, prepared)


def _logical_artifact(capability: ExportCapability, destination: Path) -> object:
    if capability.expected_artifact_kind == "json_bundle":
        payload = json.loads(destination.read_text(encoding="utf-8"))
        payload["metadata"].pop("exported_at", None)
        return payload
    if capability.expected_artifact_kind == "geojson_feature_collection":
        return json.loads(destination.read_text(encoding="utf-8"))
    if capability.expected_artifact_kind == "csv_route_view":
        return tuple(csv.reader(io.StringIO(destination.read_text(encoding="utf-8"), newline="")))
    with ZipFile(destination) as archive:
        return tuple(
            (name, archive.read(name).decode("utf-8")) for name in sorted(archive.namelist())
        )


def test_export_capability_matrix_is_closed_and_help_remains_format_specific() -> None:
    assert {capability.format for capability in EXPORT_CAPABILITIES} == {
        ExportFormat.JSON,
        ExportFormat.CSV,
        ExportFormat.GEOJSON,
        ExportFormat.MINI_GTFS,
    }
    assert len(EXPORT_CAPABILITIES) == 4
    helps = set()
    for capability in EXPORT_CAPABILITIES:
        assert capability.supports_manifest
        assert capability.supports_subset
        help_text = _format_help(
            capability.format,
            route_ids=frozenset({"A"}),
            trip_ids=frozenset({"A_TRIP_1"}),
            service_ids=frozenset({"S_A"}),
            spreadsheet_safe=capability.format is ExportFormat.CSV,
        ).casefold()
        assert capability.description_fragment in help_text
        helps.add(help_text)
    assert len(helps) == len(EXPORT_CAPABILITIES)
    mini = next(
        capability
        for capability in EXPORT_CAPABILITIES
        if capability.format is ExportFormat.MINI_GTFS
    )
    assert mini.reimportable
    assert not any(
        capability.reimportable
        for capability in EXPORT_CAPABILITIES
        if capability.format is not ExportFormat.MINI_GTFS
    )


@pytest.mark.integration
def test_all_productive_formats_follow_lifecycle_manifest_history_privacy_and_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = prepare_contract_feed(tmp_path)
    with prepared.database.connection() as connection:
        connection.execute(
            "UPDATE gtfs_routes SET route_long_name = ? WHERE route_id = ?",
            ["Ruta A, UTF-8", "A"],
        )
        connection.execute(
            "UPDATE gtfs_stops SET stop_name = ? WHERE stop_id = ?",
            ["Parada Ñ", "SHARED"],
        )
    harness = _ProductiveExportHarness(prepared)
    running_observed: list[str] = []
    original_execute = FeedExportLifecycle.execute

    def observe_start(
        lifecycle: FeedExportLifecycle,
        database: ProjectDatabase,
        project_id: str,
        feed_id: str,
        export_format: str,
        writer: Callable[[str], object],
    ) -> object:
        def observe_running(operation_id: str) -> object:
            with database.connection() as connection:
                row = connection.execute(
                    "SELECT o.operation_type, o.status, d.feed_id, d.export_format, "
                    "d.artifact_name, d.artifact_sha256, d.artifact_size_bytes "
                    "FROM operations o JOIN operation_export_details d "
                    "ON d.operation_id = o.operation_id WHERE o.operation_id = ?",
                    [operation_id],
                ).fetchone()
            assert row == (
                OperationType.EXPORT.value,
                OperationStatus.RUNNING.value,
                feed_id,
                export_format,
                None,
                None,
                None,
            )
            running_observed.append(operation_id)
            return writer(operation_id)

        return original_execute(
            lifecycle,
            database,
            project_id,
            feed_id,
            export_format,
            observe_running,
        )

    monkeypatch.setattr(FeedExportLifecycle, "execute", observe_start)
    for capability in EXPORT_CAPABILITIES:
        request = _request(capability, tmp_path)
        result = harness._export_feed(request, lambda: False)
        assert result.manifest.artifact_name == request.destination.name
        assert request.destination.is_file()
        manifest = _assert_manifest(capability, request.destination, result.manifest, prepared)
        _assert_artifact(capability, request.destination, prepared)

        item = _history_item(prepared, request.destination.name)
        assert item.operation_type is OperationType.EXPORT
        assert item.status is OperationStatus.COMPLETED
        assert item.feed_id == prepared.feed_id
        assert item.export_format == capability.format.value
        assert item.artifact_name == request.destination.name
        assert item.artifact_sha256 == manifest["sha256"]
        assert item.artifact_size_bytes == manifest["size_bytes"]
        assert _raw_export_detail(prepared.database, item.operation_id) == (
            OperationType.EXPORT.value,
            OperationStatus.COMPLETED.value,
            None,
            prepared.feed_id,
            capability.format.value,
            request.destination.name,
            manifest["sha256"],
            manifest["size_bytes"],
        )
        _assert_ledger_has_no_local_leaks(prepared)
        assert "/" not in item.artifact_name and "\\" not in item.artifact_name
    assert len(running_observed) == len(EXPORT_CAPABILITIES)


@pytest.mark.integration
def test_original_working_copy_exports_through_the_editor_route(
    tmp_path: Path,
) -> None:
    """Abrir el editor no puede bloquear las exportaciones del feed original."""
    prepared = prepare_contract_feed(tmp_path)
    session = EditorSession.open(DuckDbUnitOfWork(prepared.database))
    harness = _ProductiveExportHarness(prepared)
    harness._editor_session = session  # type: ignore[attr-defined]
    try:
        assert session.working_revision_id == "original"
        requests = (
            ExportRequest(
                ExportFormat.JSON, tmp_path / "original.json", route_ids=frozenset({"A"})
            ),
            ExportRequest(ExportFormat.CSV, tmp_path / "original.csv", route_ids=frozenset({"A"})),
            ExportRequest(ExportFormat.COMPLETE_GTFS, tmp_path / "original.zip"),
            ExportRequest(ExportFormat.KML, tmp_path / "original.kml", route_ids=frozenset({"A"})),
            ExportRequest(ExportFormat.KMZ, tmp_path / "original.kmz", route_ids=frozenset({"A"})),
        )
        for request in requests:
            result = harness._export_feed(request, lambda: False)
            if request.format is ExportFormat.CSV:
                assert result.manifest.metadata["format"] == "csv_route_view"
                assert result.manifest.metadata["revision_id"] == "original"
            assert request.destination.is_file()
            assert request.destination.with_name(
                f"{request.destination.name}.manifest.json"
            ).is_file()
            assert result.manifest.artifact_name == request.destination.name
            history = _history_item(prepared, request.destination.name)
            assert history.status is OperationStatus.COMPLETED
    finally:
        session.close()


@pytest.mark.integration
def test_clean_editor_csv_preflight_preserves_revision_route_after_session_closes(
    tmp_path: Path,
) -> None:
    prepared = prepare_contract_feed(tmp_path)
    session = EditorSession.open(DuckDbUnitOfWork(prepared.database))
    request = ExportRequest(ExportFormat.CSV, tmp_path / "original.csv", route_ids=frozenset({"A"}))
    host = SimpleNamespace(
        _get_editor_session=lambda: session,
        _export_snapshot=MainWindow._export_snapshot,
    )
    try:
        snapshot = MainWindow._prepare_export_policy(host, request)
        assert snapshot is not None
        assert snapshot.source_working_copy is not None
        assert snapshot.source_working_copy is not session.working_copy
        assert snapshot.source_working_copy.entities == session.working_copy.entities
        assert not snapshot.source_is_draft
    finally:
        session.close()
    result = _ProductiveExportHarness(prepared)._export_feed(snapshot, lambda: False)
    assert result.manifest.metadata["format"] == "csv_route_view"
    assert result.manifest.metadata["revision_id"] == "original"
    assert request.destination.is_file()


@pytest.mark.integration
def test_same_selection_has_stable_logical_content_for_all_current_formats(tmp_path: Path) -> None:
    prepared = prepare_contract_feed(tmp_path)
    harness = _ProductiveExportHarness(prepared)
    for capability in EXPORT_CAPABILITIES:
        first = _request(capability, tmp_path, prefix=f"first-{capability.format.value}")
        second = _request(capability, tmp_path, prefix=f"second-{capability.format.value}")
        harness._export_feed(first, lambda: False)
        harness._export_feed(second, lambda: False)
        assert _logical_artifact(capability, first.destination) == _logical_artifact(
            capability, second.destination
        )


@pytest.mark.integration
def test_csv_productive_path_preserves_utf8_comma_ids_and_spreadsheet_safe_mode(
    tmp_path: Path,
) -> None:
    prepared = prepare_contract_feed(tmp_path)
    with prepared.database.connection() as connection:
        connection.execute(
            "UPDATE gtfs_routes SET route_long_name = ? WHERE route_id = ?",
            ["=Ruta A, Ñ", "A"],
        )
    harness = _ProductiveExportHarness(prepared)
    capability = next(
        capability for capability in EXPORT_CAPABILITIES if capability.format is ExportFormat.CSV
    )
    faithful = _request(capability, tmp_path, prefix="faithful")
    safe = _request(capability, tmp_path, prefix="safe", spreadsheet_safe=True)
    faithful_result = harness._export_feed(faithful, lambda: False)
    safe_result = harness._export_feed(safe, lambda: False)

    faithful_rows = list(
        csv.reader(io.StringIO(faithful.destination.read_text(encoding="utf-8"), newline=""))
    )
    safe_rows = list(
        csv.reader(io.StringIO(safe.destination.read_text(encoding="utf-8"), newline=""))
    )
    assert faithful_rows[1] == ["A", "Línea Á", "=Ruta A, Ñ", "715"]
    assert safe_rows[1] == ["A", "Línea Á", "'=Ruta A, Ñ", "715"]
    assert '"=Ruta A, Ñ"' in faithful.destination.read_text(encoding="utf-8")
    assert '"\'=Ruta A, Ñ"' in safe.destination.read_text(encoding="utf-8")
    assert _assert_manifest(capability, faithful.destination, faithful_result.manifest, prepared)[
        "metadata"
    ] == {
        "csv_delimiter": ",",
        "encoding": "utf-8",
        "formula_neutralization": False,
        "mode": "faithful",
        "utf8_bom": False,
    }
    assert _assert_manifest(capability, safe.destination, safe_result.manifest, prepared)[
        "metadata"
    ] == {
        "csv_delimiter": ",",
        "encoding": "utf-8",
        "formula_neutralization": True,
        "mode": "spreadsheet-safe",
        "utf8_bom": False,
    }
    assert "source_row" not in faithful.destination.read_text(encoding="utf-8")
    assert "source_row" not in safe.destination.read_text(encoding="utf-8")


@pytest.mark.integration
def test_completed_export_history_survives_reopen_without_filesystem_reconstruction(
    tmp_path: Path,
) -> None:
    prepared = prepare_contract_feed(tmp_path)
    harness = _ProductiveExportHarness(prepared)
    capability = next(
        capability for capability in EXPORT_CAPABILITIES if capability.format is ExportFormat.JSON
    )
    request = _request(capability, tmp_path)
    result = harness._export_feed(request, lambda: False)
    item_before = _history_item(prepared, request.destination.name)
    assert item_before.status is OperationStatus.COMPLETED
    request.destination.unlink()
    request.destination.with_name(result.manifest.manifest_name).unlink()

    reopened = ProjectDatabase(
        prepared.database.database_path,
        prepared.database.temporary_directory,
        settings=prepared.database.settings,
    )
    assert reopened.validate_compatible() == 11
    with DuckDbUnitOfWork(reopened) as unit_of_work:
        item_after = unit_of_work.operations.list_operations(
            prepared.project_id,
            PageRequest(limit=100),
            OperationType.EXPORT,
        ).items[0]
    assert item_after.operation_id == item_before.operation_id
    assert item_after.status is OperationStatus.COMPLETED
    assert item_after.feed_id == prepared.feed_id
    assert item_after.artifact_name == request.destination.name
    assert item_after.artifact_sha256 == result.manifest.sha256
    assert item_after.artifact_size_bytes == result.manifest.size_bytes


@pytest.mark.integration
def test_export_failure_before_publication_is_prepare_failed_and_private(
    tmp_path: Path,
) -> None:
    prepared = prepare_contract_feed(tmp_path)
    harness = _ProductiveExportHarness(prepared)
    capability = next(
        capability for capability in EXPORT_CAPABILITIES if capability.format is ExportFormat.JSON
    )
    request = ExportRequest(
        capability.format,
        tmp_path / "missing-directory" / "output.json",
        route_ids=frozenset({"A"}),
    )
    with pytest.raises(ExportDestinationError):
        harness._export_feed(request, lambda: False)
    assert not request.destination.exists()
    item = _history_item(prepared)
    assert item.status is OperationStatus.FAILED
    assert item.error_code == "EXPORT_PREPARE_FAILED"
    assert item.artifact_name is None
    assert item.artifact_sha256 is None
    assert item.artifact_size_bytes is None
    assert _raw_export_detail(prepared.database, item.operation_id) == (
        OperationType.EXPORT.value,
        OperationStatus.FAILED.value,
        "EXPORT_PREPARE_FAILED",
        prepared.feed_id,
        capability.format.value,
        None,
        None,
        None,
    )
    _assert_ledger_has_no_local_leaks(prepared)
    assert item.status is not OperationStatus.CANCELLED


@pytest.mark.integration
def test_export_failure_during_write_is_write_failed_without_partial_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = prepare_contract_feed(tmp_path)
    harness = _ProductiveExportHarness(prepared)
    capability = next(
        capability for capability in EXPORT_CAPABILITIES if capability.format is ExportFormat.JSON
    )
    request = _request(capability, tmp_path)

    def fail_write(*args: object, **kwargs: object) -> tuple[str, int]:
        raise ExportError("synthetic filesystem failure C:\\Users\\secret\\traceback")

    monkeypatch.setattr(AtomicOutputWriter, "_write_temporary", fail_write)
    with pytest.raises(ExportError):
        harness._export_feed(request, lambda: False)
    assert not request.destination.exists()
    assert not request.destination.with_name(f"{request.destination.name}.manifest.json").exists()
    item = _history_item(prepared)
    assert item.status is OperationStatus.FAILED
    assert item.error_code == "EXPORT_WRITE_FAILED"
    assert item.artifact_name is None
    assert _raw_export_detail(prepared.database, item.operation_id) == (
        OperationType.EXPORT.value,
        OperationStatus.FAILED.value,
        "EXPORT_WRITE_FAILED",
        prepared.feed_id,
        capability.format.value,
        None,
        None,
        None,
    )
    _assert_ledger_has_no_local_leaks(prepared)
    assert item.error_code not in {"CANCELLED"}
    with prepared.database.connection() as connection:
        ledger = connection.execute(
            "SELECT error_code FROM operations UNION ALL "
            "SELECT artifact_name FROM operation_export_details"
        ).fetchall()
    assert "synthetic filesystem failure" not in json.dumps(ledger)
    assert "traceback" not in json.dumps(ledger).casefold()


@pytest.mark.integration
def test_final_database_failure_after_publication_derives_interrupted_on_reopen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = prepare_contract_feed(tmp_path)
    harness = _ProductiveExportHarness(prepared)
    capability = next(
        capability for capability in EXPORT_CAPABILITIES if capability.format is ExportFormat.JSON
    )
    request = _request(capability, tmp_path)
    original_commit = DuckDbUnitOfWork.commit

    def fail_terminal_commit(unit_of_work: DuckDbUnitOfWork) -> None:
        row = unit_of_work._connection.execute(
            "SELECT artifact_name FROM operation_export_details "
            "WHERE artifact_name IS NOT NULL LIMIT 1"
        ).fetchone()
        if row is not None:
            raise RuntimeError("synthetic final database failure C:\\Users\\secret\\traceback")
        original_commit(unit_of_work)

    monkeypatch.setattr(DuckDbUnitOfWork, "commit", fail_terminal_commit)
    with pytest.raises(RuntimeError, match="final database failure"):
        harness._export_feed(request, lambda: False)
    assert request.destination.is_file()
    assert request.destination.with_name(f"{request.destination.name}.manifest.json").is_file()

    # La actualización final quedó en la UoW fallida; START sí estaba confirmado.
    item = _history_item(prepared)
    assert item.operation_type is OperationType.EXPORT
    assert item.status is OperationStatus.RUNNING
    assert item.artifact_name is None
    assert item.artifact_sha256 is None
    assert item.artifact_size_bytes is None

    reopened = ProjectDatabase(
        prepared.database.database_path,
        prepared.database.temporary_directory,
        settings=prepared.database.settings,
    )
    reopened.validate_compatible()
    with DuckDbUnitOfWork(reopened) as unit_of_work:
        recovered = unit_of_work.operations.list_operations(
            prepared.project_id,
            PageRequest(limit=100),
            OperationType.EXPORT,
        ).items[0]
    assert recovered.status is OperationStatus.RUNNING
    assert display_status(recovered, frozenset()) is OperationDisplayStatus.INTERRUPTED
    assert recovered.status is not OperationStatus.FAILED
    assert recovered.status is not OperationStatus.CANCELLED
