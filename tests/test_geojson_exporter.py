from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from gtfs_explorer.domain.exporting import ExportCancelled
from gtfs_explorer.domain.source import InputSource, InputSourceKind
from gtfs_explorer.domain.spec import load_schedule_spec
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.infrastructure.exporting.geojson_exporter import (
    GeoJsonExporter,
    GeoJsonExportSelection,
)
from gtfs_explorer.infrastructure.importing.directory_source import DirectorySource
from gtfs_explorer.infrastructure.importing.normalizers.core import CoreNormalizer
from gtfs_explorer.infrastructure.importing.normalizers.geometry import GeometryNormalizer
from gtfs_explorer.infrastructure.importing.staging_loader import StagingLoader

SPEC_PATH = Path("schemas/gtfs_schedule/2026-04-27/spec.json")
FIXTURE_PATH = Path("tests/fixtures/specs/valid_full.json")


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
    specification = load_schedule_spec(SPEC_PATH)
    manifest = DirectorySource().inventory(InputSource(source, InputSourceKind.DIRECTORY))
    StagingLoader().load(database, source, manifest, specification)
    CoreNormalizer().normalize(database, specification)
    GeometryNormalizer().normalize(database, specification)


def _export(database: ProjectDatabase, destination: Path) -> dict[str, object]:
    with database.connection() as connection:
        GeoJsonExporter().write(
            connection,
            destination,
            selection=GeoJsonExportSelection(frozenset({"R1"})),
            include_bbox=True,
        )
    return json.loads(destination.read_text(encoding="utf-8"))


@pytest.mark.integration
def test_exports_traceable_rfc_7946_stops_and_original_shapes(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _prepare(database, tmp_path)

    result = _export(database, tmp_path / "seleccion.geojson")

    assert result["type"] == "FeatureCollection"
    assert result["bbox"] == [-5.9, 43.1, -5.8, 43.2]
    assert result["features"][0] == {
        "type": "Feature",
        "properties": {
            "feature_kind": "stop",
            "stop_id": "S1",
            "stop_name": "Norte",
            "source_file": "stops.txt",
            "source_row": 2,
        },
        "geometry": {"type": "Point", "coordinates": [-5.8, 43.1]},
    }
    shape = result["features"][1]
    assert shape["geometry"] == {
        "type": "LineString",
        "coordinates": [[-5.8, 43.1], [-5.9, 43.2]],
    }
    assert shape["properties"]["geometry_source"] == "original"


@pytest.mark.integration
def test_omits_invalid_and_degenerate_geometry_without_nan_or_infinity(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _prepare(database, tmp_path)
    with database.connection() as connection:
        connection.execute("UPDATE gtfs_stops SET stop_lat = 'NaN' WHERE stop_id = 'S1'")
        connection.execute("UPDATE gtfs_shapes SET shape_pt_lat = NULL WHERE shape_pt_sequence = 2")

    result = _export(database, tmp_path / "sin-invalidos.geojson")

    assert result["features"] == []
    assert "bbox" not in result
    assert "NaN" not in json.dumps(result)


@pytest.mark.integration
def test_keeps_unicode_and_cancellation_does_not_publish_partial_geojson(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _prepare(database, tmp_path)
    with database.connection() as connection:
        connection.execute(
            "UPDATE gtfs_stops SET stop_name = ? WHERE stop_id = ?", ["Parada Ñ", "S1"]
        )
    result = _export(database, tmp_path / "unicode.geojson")
    assert result["features"][0]["properties"]["stop_name"] == "Parada Ñ"

    destination = tmp_path / "cancelado.geojson"
    with database.connection() as connection:
        with pytest.raises(ExportCancelled):
            GeoJsonExporter().write(
                connection,
                destination,
                selection=GeoJsonExportSelection(frozenset({"R1"})),
                is_cancelled=lambda: True,
            )
    assert not destination.exists()
