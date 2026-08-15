from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from gtfs_explorer.domain.exporting import ExportCancelled
from gtfs_explorer.domain.source import InputSource, InputSourceKind
from gtfs_explorer.domain.spec import load_schedule_spec
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.infrastructure.exporting.json_exporter import (
    JsonBundleExporter,
    JsonExportSelection,
)
from gtfs_explorer.infrastructure.importing.directory_source import DirectorySource
from gtfs_explorer.infrastructure.importing.normalizers.core import CoreNormalizer
from gtfs_explorer.infrastructure.importing.normalizers.geometry import GeometryNormalizer
from gtfs_explorer.infrastructure.importing.normalizers.optional import OptionalNormalizer
from gtfs_explorer.infrastructure.importing.staging_loader import StagingLoader

SPEC_PATH = Path("schemas/gtfs_schedule/2026-04-27/spec.json")
FIXTURE_PATH = Path("tests/fixtures/specs/valid_full.json")
FIXED_NOW = datetime(2026, 8, 13, 10, 30, tzinfo=timezone.utc)


def _database(tmp_path: Path) -> ProjectDatabase:
    return ProjectDatabase(
        tmp_path / "project.duckdb",
        tmp_path / "temporary",
        settings=DatabaseSettings(memory_limit="128MB", max_temp_directory_size="128MB"),
    )


def _prepare(database: ProjectDatabase, tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    for filename, table in fixture["tables"].items():
        with (source / filename).open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=table["headers"], lineterminator="\n")
            writer.writeheader()
            writer.writerows(table["rows"])
    manifest = DirectorySource().inventory(InputSource(source, InputSourceKind.DIRECTORY))
    StagingLoader().load(database, source, manifest, load_schedule_spec(SPEC_PATH))
    CoreNormalizer().normalize(database, load_schedule_spec(SPEC_PATH))
    GeometryNormalizer().normalize(database, load_schedule_spec(SPEC_PATH))
    OptionalNormalizer().normalize(database, load_schedule_spec(SPEC_PATH))
    with database.connection() as connection:
        connection.execute(
            "INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?)",
            ["project", "Demo", "READY", FIXED_NOW, FIXED_NOW, 8],
        )
        connection.execute(
            "INSERT INTO feeds VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                "feed",
                "project",
                "fuente",
                "a" * 64,
                "STRICT",
                "2026-04-27",
                "0.1.0",
                FIXED_NOW,
                "IMPORTED",
            ],
        )


def _export(
    database: ProjectDatabase, destination: Path, selection: JsonExportSelection
) -> dict[str, object]:
    with database.connection() as connection:
        JsonBundleExporter(now=lambda: FIXED_NOW).write(
            connection, destination, feed_id="feed", selection=selection
        )
    return json.loads(destination.read_text(encoding="utf-8"))


@pytest.mark.integration
def test_exports_a_route_trip_and_its_stop_with_supported_optional_data(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _prepare(database, tmp_path)

    bundle = _export(database, tmp_path / "seleccion.json", JsonExportSelection(frozenset({"R1"})))

    assert set(bundle) == {
        "schema_version",
        "generator",
        "source",
        "selection",
        "agencies",
        "routes",
        "services",
        "stops",
        "shapes",
        "trips",
        "transfers",
        "metadata",
        "warnings",
    }
    assert bundle["schema_version"] == "1.0.0"
    assert bundle["routes"] == [
        {
            "agency_id": "A1",
            "route_id": "R1",
            "route_type": 3,
            "short_name": "1",
            "long_name": None,
            "description": None,
            "url": None,
            "color": None,
            "text_color": None,
        }
    ]
    assert [stop["stop_id"] for stop in bundle["stops"]] == ["S1"]
    assert [trip["trip_id"] for trip in bundle["trips"]] == ["T1"]
    assert bundle["shapes"][0]["points"][0]["sequence"] == 1
    assert bundle["transfers"] == []
    assert bundle["metadata"]["frequencies"][0]["start_time_lexeme"] == "25:00:00"
    assert bundle["metadata"]["attributions"][0]["organization_name"] == "Autoridad"
    assert bundle["warnings"] == []


@pytest.mark.integration
def test_keeps_gtfs_over_24_hours_unicode_and_a_stable_hash_without_local_paths(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    _prepare(database, tmp_path)
    with database.connection() as connection:
        connection.execute(
            "UPDATE gtfs_stops SET stop_name = ? WHERE stop_id = ?", ["Parada Ñ", "S1"]
        )
        connection.execute(
            "UPDATE gtfs_stop_times SET arrival_time_lexeme = ?, arrival_service_seconds = ?, "
            "departure_time_lexeme = ?, departure_service_seconds = ? WHERE trip_id = ?",
            ["25:00:00", 90_000, "25:00:00", 90_000, "T1"],
        )
    selection = JsonExportSelection(frozenset({"R1"}), frozenset({"T1"}))
    first = _export(database, tmp_path / "primero.json", selection)
    _export(database, tmp_path / "segundo.json", selection)

    assert first["stops"][0]["name"] == "Parada Ñ"
    assert first["trips"][0]["stop_times"][0]["arrival"] == "25:00:00"
    assert first["trips"][0]["stop_times"][0]["arrival_service_seconds"] == 90_000
    assert (
        hashlib.sha256((tmp_path / "primero.json").read_bytes()).hexdigest()
        == hashlib.sha256((tmp_path / "segundo.json").read_bytes()).hexdigest()
    )
    assert str(tmp_path) not in (tmp_path / "primero.json").read_text(encoding="utf-8")


@pytest.mark.integration
def test_streams_a_large_export_and_includes_an_omission_warning(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _prepare(database, tmp_path)
    with database.connection() as connection:
        connection.executemany(
            "INSERT INTO gtfs_stops (source_filename, source_row, raw_values, stop_id, stop_name, "
            "stop_lat, stop_lon) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("stops.txt", index + 100, "{}", f"S{index + 10}", f"Parada {index}", 43.0, -5.0)
                for index in range(1_500)
            ],
        )
        connection.executemany(
            "INSERT INTO gtfs_stop_times (source_filename, source_row, raw_values, trip_id, "
            "arrival_time_lexeme, arrival_service_seconds, departure_time_lexeme, "
            "departure_service_seconds, stop_id, stop_sequence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "stop_times.txt",
                    index + 100,
                    "{}",
                    "T1",
                    "25:00:00",
                    90_000,
                    "25:00:00",
                    90_000,
                    f"S{index + 10}",
                    index + 10,
                )
                for index in range(1_500)
            ],
        )
        connection.execute("UPDATE gtfs_shapes SET shape_pt_lat = NULL WHERE shape_id = ?", ["SH1"])

    bundle = _export(database, tmp_path / "grande.json", JsonExportSelection(frozenset({"R1"})))

    assert len(bundle["stops"]) == 1_501
    assert (tmp_path / "grande.json").stat().st_size > 100_000
    assert bundle["warnings"] == [
        {
            "code": "OMITTED_INVALID_RECORD",
            "message": "Se omitió un registro inválido del bundle.",
            "entity_type": "shape_point",
            "entity_id": "SH1",
        }
    ]


@pytest.mark.integration
def test_cancellation_does_not_publish_a_partial_json_bundle(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _prepare(database, tmp_path)
    destination = tmp_path / "cancelado.json"
    with database.connection() as connection:
        with pytest.raises(ExportCancelled):
            JsonBundleExporter(now=lambda: FIXED_NOW).write(
                connection,
                destination,
                feed_id="feed",
                selection=JsonExportSelection(frozenset({"R1"})),
                is_cancelled=lambda: True,
            )
    assert not destination.exists()
