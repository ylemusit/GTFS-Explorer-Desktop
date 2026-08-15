"""Integración de la normalización de geometría y opcionales prioritarios."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from gtfs_explorer.domain.source import InputSource, InputSourceKind
from gtfs_explorer.domain.spec import load_schedule_spec
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.infrastructure.importing.directory_source import DirectorySource
from gtfs_explorer.infrastructure.importing.normalizers.geometry import GeometryNormalizer
from gtfs_explorer.infrastructure.importing.normalizers.optional import OptionalNormalizer
from gtfs_explorer.infrastructure.importing.staging_loader import StagingLoader

SPEC_PATH = Path("schemas/gtfs_schedule/2026-04-27/spec.json")


def _database(tmp_path: Path) -> ProjectDatabase:
    return ProjectDatabase(
        tmp_path / "project.duckdb",
        tmp_path / "temporary",
        settings=DatabaseSettings(memory_limit="128MB", max_temp_directory_size="128MB"),
    )


def _stage(database: ProjectDatabase, source: Path) -> None:
    manifest = DirectorySource().inventory(InputSource(source, InputSourceKind.DIRECTORY))
    StagingLoader().load(database, source, manifest, load_schedule_spec(SPEC_PATH))


def _write(source: Path, filename: str, content: str) -> None:
    (source / filename).write_text(content, encoding="utf-8")


def _write_fixture(source: Path, fixture_name: str) -> None:
    fixture_path = Path("tests/fixtures/specs") / f"{fixture_name}.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    for filename, table in fixture["tables"].items():
        headers = table["headers"]
        rows = table["rows"]
        with (source / filename).open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=headers, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)


@pytest.mark.integration
def test_normalizes_supported_full_fixture_with_ordered_shapes_and_visible_metadata(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write_fixture(source, "valid_full")
    database = _database(tmp_path)
    _stage(database, source)

    geometry = GeometryNormalizer().normalize(database, load_schedule_spec(SPEC_PATH))
    optional = OptionalNormalizer().normalize(database, load_schedule_spec(SPEC_PATH))

    assert geometry.row_count == 2
    assert geometry.issue_count == 0
    assert optional.row_counts == {
        "frequencies.txt": 1,
        "transfers.txt": 1,
        "feed_info.txt": 1,
        "attributions.txt": 1,
    }
    assert optional.issue_count == 0
    with database.connection() as connection:
        assert connection.execute(
            "SELECT shape_pt_sequence FROM gtfs_shapes WHERE shape_id = 'SH1' "
            "ORDER BY shape_pt_sequence"
        ).fetchall() == [(1,), (2,)]
        assert connection.execute(
            "SELECT start_time_lexeme, start_time_service_seconds, end_time_service_seconds, "
            "headway_secs, exact_times FROM gtfs_frequencies"
        ).fetchone() == ("25:00:00", 90000, 93600, 600, 1)
        assert connection.execute(
            "SELECT from_stop_id, to_stop_id, from_route_id, to_route_id, from_trip_id, "
            "to_trip_id, transfer_type, min_transfer_time FROM gtfs_transfers"
        ).fetchone() == ("S1", "S2", "R1", "R2", "T1", "T2", 2, 120)
        assert connection.execute(
            "SELECT feed_publisher_name, feed_start_date, feed_version FROM gtfs_feed_info"
        ).fetchone() == ("Operador", __import__("datetime").date(2026, 1, 1), "2026.1")
        assert connection.execute(
            "SELECT organization_name, is_producer, is_operator, is_authority "
            "FROM gtfs_attributions"
        ).fetchone() == ("Autoridad", 1, 0, 1)


@pytest.mark.integration
def test_optional_edge_cases_keep_transfer_values_and_report_invalid_conversions(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write(
        source,
        "shapes.txt",
        "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\nSH1,invalid,-5.8,one\n",
    )
    _write(
        source,
        "frequencies.txt",
        "trip_id,start_time,end_time,headway_secs,exact_times\nT1,24:00:00,bad,0,7\n",
    )
    _write(
        source,
        "transfers.txt",
        "from_stop_id,to_stop_id,transfer_type,min_transfer_time\n,,5,\n",
    )
    _write(
        source,
        "feed_info.txt",
        "feed_publisher_name,feed_publisher_url,feed_lang,feed_start_date\n"
        "Operador,https://example.invalid,es,20261340\n",
    )
    _write(
        source,
        "attributions.txt",
        "organization_name,is_producer\nAutoridad,2\n",
    )
    database = _database(tmp_path)
    _stage(database, source)

    geometry = GeometryNormalizer().normalize(database, load_schedule_spec(SPEC_PATH))
    optional = OptionalNormalizer().normalize(database, load_schedule_spec(SPEC_PATH))

    assert geometry.issue_count == 2
    assert optional.issue_count == 5
    with database.connection() as connection:
        assert connection.execute(
            "SELECT shape_pt_lat, shape_pt_sequence FROM gtfs_shapes"
        ).fetchone() == (None, None)
        assert connection.execute(
            "SELECT end_time_lexeme, end_time_service_seconds, headway_secs, exact_times "
            "FROM gtfs_frequencies"
        ).fetchone() == ("bad", None, None, None)
        assert connection.execute(
            "SELECT from_stop_id, to_stop_id, transfer_type, min_transfer_time FROM gtfs_transfers"
        ).fetchone() == (None, None, 5, None)
        assert connection.execute(
            "SELECT feed_start_date_lexeme, feed_start_date FROM gtfs_feed_info"
        ).fetchone() == ("20261340", None)
        assert connection.execute("SELECT is_producer FROM gtfs_attributions").fetchone() == (None,)
