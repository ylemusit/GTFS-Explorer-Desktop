from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from gtfs_explorer.application.commands.import_feed import ImportFeed, ImportFeedResult
from gtfs_explorer.domain.project import JobState, ProjectMetadata, ProjectStatus
from gtfs_explorer.domain.source import InputSource, InputSourceKind
from gtfs_explorer.domain.spec import load_schedule_spec
from gtfs_explorer.domain.subset import SubsetSelection, close_core_subset
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.infrastructure.duckdb.repositories.base import DuckDbCoreSubsetRepository
from gtfs_explorer.infrastructure.exporting.gtfs_subset import MiniGtfsSubsetExporter
from gtfs_explorer.presentation.desktop.main_window import MainWindow

SPEC_PATH = Path("schemas/gtfs_schedule/2026-04-27/spec.json")
FIXTURE_PATH = Path("tests/fixtures/specs/mini_gtfs_contract.json")


def _database(root: Path, name: str) -> ProjectDatabase:
    database = ProjectDatabase(
        root / name / "project.duckdb",
        root / name / "temporary",
        settings=DatabaseSettings(memory_limit="128MB", max_temp_directory_size="128MB"),
    )
    database.initialize()
    return database


def _project(name: str) -> ProjectMetadata:
    return ProjectMetadata(name, name, ProjectStatus.READY)


def _write_fixture(destination: Path) -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    for filename, table in fixture["tables"].items():
        with (destination / filename).open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=table["headers"], lineterminator="\n")
            writer.writeheader()
            writer.writerows(table["rows"])


def _import(
    database: ProjectDatabase,
    project: ProjectMetadata,
    source: Path,
    kind: InputSourceKind,
    job_id: str,
    feed_id: str,
) -> ImportFeedResult:
    return ImportFeed(
        database,
        project,
        InputSource(source, kind),
        load_schedule_spec(SPEC_PATH),
        job_id=job_id,
        feed_id=feed_id,
    ).execute()


def _rows(archive: ZipFile, filename: str) -> list[dict[str, str]]:
    text = archive.read(filename).decode("utf-8")
    return list(csv.DictReader(io.StringIO(text, newline="")))


@pytest.mark.integration
def test_mini_gtfs_contract_is_self_contained_and_reimportable_in_new_project(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write_fixture(source)
    specification = load_schedule_spec(SPEC_PATH)
    original = _database(tmp_path, "original")

    imported = _import(
        original,
        _project("original-project"),
        source,
        InputSourceKind.DIRECTORY,
        "source-job",
        "source-feed",
    )
    assert imported.state is JobState.READY
    assert imported.issue_count == 0

    first = tmp_path / "mini-a.zip"
    second = tmp_path / "mini-b.zip"
    with original.connection() as connection:
        source_model = DuckDbCoreSubsetRepository(connection).core_subset_source()
        subset = close_core_subset(source_model, SubsetSelection(frozenset({"A"})))
        tables = MainWindow._mini_gtfs_tables(connection, specification, subset)
        exporter = MiniGtfsSubsetExporter(specification)
        manifest = exporter.write(first, tables, expected=subset)
        exporter.write(second, tables, expected=subset)

    # El segundo ZIP se genera desde las tablas materializadas, no desde el
    # proyecto de destino; ambos artefactos deben ser lógicamente idénticos.
    assert first.read_bytes() == second.read_bytes()
    names = {
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
    with ZipFile(first) as archive:
        assert set(archive.namelist()) == names
        assert all("/" not in name and "\\" not in name for name in archive.namelist())
        assert "project.json" not in archive.namelist()
        assert "project.duckdb" not in archive.namelist()

        routes = _rows(archive, "routes.txt")
        assert [(row["route_id"], row["route_type"]) for row in routes] == [("A", "715")]

        trips = _rows(archive, "trips.txt")
        assert {row["trip_id"] for row in trips} == {"A_TRIP_1", "A_TRIP_2"}
        assert {row["service_id"] for row in trips} == {"S_A", "S_SPECIAL"}

        stop_times = _rows(archive, "stop_times.txt")
        assert len(stop_times) == 5
        assert [row["stop_id"] for row in stop_times if row["trip_id"] == "A_TRIP_1"] == [
            "SHARED",
            "A1",
            "SHARED",
        ]
        assert "24:10:00" in {row["arrival_time"] for row in stop_times}
        assert sum(row["stop_id"] == "SHARED" for row in stop_times) == 3

        stops = _rows(archive, "stops.txt")
        assert {row["stop_id"] for row in stops} >= {"STA", "SHARED", "A1", "A2"}
        assert "B_ONLY" not in {row["stop_id"] for row in stops}
        assert any(row["stop_name"] == "Estación Ñ" for row in stops)

        assert {row["shape_id"] for row in _rows(archive, "shapes.txt")} == {"SH_A"}
        assert {row["trip_id"] for row in _rows(archive, "frequencies.txt")} == {"A_TRIP_1"}
        assert {row["to_route_id"] for row in _rows(archive, "transfers.txt")} == {"A"}
        assert {row["service_id"] for row in _rows(archive, "calendar.txt")} == {"S_A"}
        assert {row["service_id"] for row in _rows(archive, "calendar_dates.txt")} == {"S_SPECIAL"}
        assert _rows(archive, "feed_info.txt")[0]["feed_start_date"] == "20260101"
        assert {row["attribution_id"] for row in _rows(archive, "attributions.txt")} == {
            "GLOBAL",
            "A_ATTR",
        }

    manifest_payload = json.loads(
        first.with_name(manifest.manifest_name).read_text(encoding="utf-8")
    )
    assert manifest_payload["artifact_name"] == first.name
    assert manifest_payload["sha256"] == hashlib.sha256(first.read_bytes()).hexdigest()
    assert manifest_payload["size_bytes"] == first.stat().st_size
    assert manifest_payload["metadata"]["format"] == "gtfs_schedule_zip"

    # Se cierra el contexto de origen antes de usar el ZIP. El destino tiene
    # otra DuckDB y solo conoce las filas publicadas en el artefacto.
    target = _database(tmp_path, "target")
    reimported = _import(
        target,
        _project("target-project"),
        first,
        InputSourceKind.ARCHIVE,
        "target-job",
        "target-feed",
    )
    assert reimported.state is JobState.READY
    assert reimported.issue_count == 0
    with target.connection() as connection:
        assert connection.execute("SELECT route_id FROM gtfs_routes").fetchall() == [("A",)]
        assert connection.execute("SELECT count(*) FROM validation_issues").fetchone() == (0,)
        assert connection.execute("SELECT status FROM validation_runs").fetchone() == ("VALID",)
        assert connection.execute("SELECT status FROM feeds").fetchone() == ("IMPORTED",)
        assert connection.execute(
            "SELECT count(*) FROM gtfs_stops WHERE stop_id = 'B_ONLY'"
        ).fetchone() == (0,)

    reopened = ProjectDatabase(
        target.database_path,
        target.temporary_directory,
        settings=target.settings,
    )
    reopened.validate_compatible()
