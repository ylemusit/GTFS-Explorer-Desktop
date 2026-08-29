from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from gtfs_explorer.domain.exporting import ExportError
from gtfs_explorer.domain.spec import load_schedule_spec
from gtfs_explorer.domain.subset import (
    CoreStop,
    CoreSubsetSource,
    CoreTrip,
    SubsetSelection,
    close_core_subset,
)
from gtfs_explorer.infrastructure.exporting.gtfs_subset import MiniGtfsSubsetExporter, MiniGtfsTable

SPEC_PATH = Path("schemas/gtfs_schedule/2026-04-27/spec.json")


def _expected():
    return close_core_subset(
        CoreSubsetSource(
            route_agencies=(("R1", "A1"),),
            trips=(CoreTrip("T1", "R1", "weekday"),),
            stop_times=(("T1", "S1"),),
            stops=(CoreStop("S1", None),),
            calendar_service_ids=frozenset({"weekday"}),
            calendar_date_service_ids=frozenset(),
            agency_ids=frozenset({"A1"}),
        ),
        SubsetSelection(frozenset({"R1"})),
    )


def _table(name: str, headers: tuple[str, ...], *rows: tuple[str, ...]) -> MiniGtfsTable:
    return MiniGtfsTable(name, headers, rows)


def _tables(route_type: str = "3") -> tuple[MiniGtfsTable, ...]:
    return (
        _table(
            "agency.txt",
            ("agency_id", "agency_name", "agency_url", "agency_timezone"),
            ("A1", "Operador", "https://example.invalid", "Europe/Madrid"),
        ),
        _table(
            "calendar.txt",
            (
                "service_id",
                "monday",
                "tuesday",
                "wednesday",
                "thursday",
                "friday",
                "saturday",
                "sunday",
                "start_date",
                "end_date",
            ),
            ("weekday", "1", "1", "1", "1", "1", "0", "0", "20260101", "20261231"),
        ),
        _table(
            "routes.txt",
            ("route_id", "agency_id", "route_short_name", "route_type"),
            ("R1", "A1", "1", route_type),
        ),
        _table(
            "stops.txt",
            ("stop_id", "stop_name", "stop_lat", "stop_lon"),
            ("S1", "Norte", "43.1", "-5.8"),
        ),
        _table(
            "trips.txt",
            ("route_id", "service_id", "trip_id", "shape_id"),
            ("R1", "weekday", "T1", "SH1"),
        ),
        _table(
            "stop_times.txt",
            ("trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"),
            ("T1", "08:00:00", "08:00:00", "S1", "1"),
        ),
        _table(
            "shapes.txt",
            ("shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"),
            ("SH1", "43.1", "-5.8", "1"),
            ("SH1", "43.2", "-5.9", "2"),
        ),
        _table(
            "frequencies.txt",
            ("trip_id", "start_time", "end_time", "headway_secs", "exact_times"),
            ("T1", "25:00:00", "26:00:00", "600", "1"),
        ),
        _table(
            "feed_info.txt",
            (
                "feed_publisher_name",
                "feed_publisher_url",
                "feed_lang",
                "feed_start_date",
                "feed_end_date",
                "feed_version",
            ),
            ("Operador", "https://example.invalid", "es", "20260101", "20261231", "2026.1"),
        ),
        _table(
            "attributions.txt",
            (
                "attribution_id",
                "organization_name",
                "is_producer",
                "is_operator",
                "is_authority",
                "attribution_url",
            ),
            ("ATTR1", "Autoridad", "1", "0", "1", "https://example.invalid/attribution"),
        ),
    )


@pytest.mark.integration
def test_mini_gtfs_is_rooted_reimported_deterministic_and_matches_selection(tmp_path: Path) -> None:
    exporter = MiniGtfsSubsetExporter(load_schedule_spec(SPEC_PATH))
    first = tmp_path / "mini-a.zip"
    second = tmp_path / "mini-b.zip"

    manifest = exporter.write(first, tuple(reversed(_tables())), expected=_expected())
    exporter.write(second, _tables(), expected=_expected())

    assert first.read_bytes() == second.read_bytes()
    with ZipFile(first) as archive:
        assert archive.namelist() == sorted(table.filename for table in _tables())
        assert all("/" not in name for name in archive.namelist())
        assert (
            list(csv.reader(io.TextIOWrapper(archive.open("feed_info.txt"), encoding="utf-8")))[1][
                0
            ]
            == "Operador"
        )
        assert (
            list(csv.reader(io.TextIOWrapper(archive.open("attributions.txt"), encoding="utf-8")))[
                1
            ][0]
            == "ATTR1"
        )
    assert json.loads((tmp_path / manifest.manifest_name).read_text())["metadata"] == {
        "formal_validation": "not_available",
        "format": "gtfs_schedule_zip",
        "internal_revalidation": "passed",
    }


@pytest.mark.integration
def test_mini_gtfs_roundtrip_preserves_known_extended_route_type(tmp_path: Path) -> None:
    destination = tmp_path / "extended.zip"

    MiniGtfsSubsetExporter(load_schedule_spec(SPEC_PATH)).write(
        destination, _tables("715"), expected=_expected()
    )

    with ZipFile(destination) as archive:
        rows = list(csv.reader(io.TextIOWrapper(archive.open("routes.txt"), encoding="utf-8")))
    assert rows[1][3] == "715"


@pytest.mark.integration
def test_no_final_artifact_or_manifest_appears_when_revalidation_fails(tmp_path: Path) -> None:
    tables = list(_tables())
    tables[tables.index(next(table for table in tables if table.filename == "stops.txt"))] = _table(
        "stops.txt",
        ("stop_id", "stop_name", "stop_lat", "stop_lon"),
        ("OTHER", "Otra", "43.1", "-5.8"),
    )
    destination = tmp_path / "invalid.zip"

    with pytest.raises(ExportError, match="reimportación interna"):
        MiniGtfsSubsetExporter(load_schedule_spec(SPEC_PATH)).write(
            destination, tables, expected=_expected()
        )

    assert not destination.exists()
    assert not destination.with_name("invalid.zip.manifest.json").exists()
