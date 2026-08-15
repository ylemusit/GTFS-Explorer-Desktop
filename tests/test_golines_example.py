from __future__ import annotations

import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pytest

from gtfs_explorer.application.commands.import_feed import ImportFeed
from gtfs_explorer.domain.project import JobState, ProjectMetadata, ProjectStatus
from gtfs_explorer.domain.source import InputSource, InputSourceKind
from gtfs_explorer.domain.spec import load_schedule_spec
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "build_golines_example.py"


def _module():
    specification = importlib.util.spec_from_file_location("build_golines_example", SCRIPT)
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def _catalog(path: Path) -> None:
    stops = [
        {
            "stopId": "S1",
            "name": "Oviedo",
            "latitude": 43.36,
            "longitude": -5.85,
            "sequence": 1,
            "arrival": "08:00:00",
            "departure": "08:00:00",
        },
        {
            "stopId": "S2",
            "name": "Gijón",
            "latitude": 43.53,
            "longitude": -5.66,
            "sequence": 2,
            "arrival": "08:30:00",
            "departure": "08:30:00",
        },
    ]
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "generatedAt": "2026-08-07T00:00:00Z",
                "sourceUrl": "https://example.test/source",
                "routes": [
                    {
                        "id": "centrobus-og1",
                        "shortName": "OG1",
                        "longName": "Oviedo → Gijón",
                        "officialPage": "https://example.test/og1",
                    }
                ],
                "trips": [
                    {
                        "id": "T1",
                        "routeId": "centrobus-og1",
                        "serviceId": "Fuente A",
                        "directionId": "0",
                        "headsign": "Gijón",
                        "shapeId": "SH1",
                        "stops": stops,
                    },
                    {
                        "id": "T2",
                        "routeId": "centrobus-og1",
                        "serviceId": "Fuente B",
                        "directionId": "0",
                        "headsign": "Gijón",
                        "shapeId": "SH1",
                        "stops": [
                            {**stop, "arrival": "09:00:00", "departure": "09:00:00"}
                            if index == 0
                            else {**stop, "arrival": "09:30:00", "departure": "09:30:00"}
                            for index, stop in enumerate(stops)
                        ],
                    },
                ],
                "shapes": {"SH1": [[43.36, -5.85], [43.45, -5.75], [43.53, -5.66]]},
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.integration
def test_golines_example_is_deterministic_and_importable(tmp_path: Path) -> None:
    module = _module()
    catalog = tmp_path / "centrobus_repository.json"
    _catalog(catalog)
    first = tmp_path / "first.gtfs.zip"
    second = tmp_path / "second.gtfs.zip"

    counts = module.build_gtfs(
        catalog,
        first,
        route_ids=("centrobus-og1",),
        trips_per_route=2,
    )
    module.build_gtfs(
        catalog,
        second,
        route_ids=("centrobus-og1",),
        trips_per_route=2,
    )

    assert first.read_bytes() == second.read_bytes()
    assert counts == {
        "routes": 1,
        "trips": 2,
        "stops": 2,
        "stop_times": 4,
        "shape_points": 3,
        "route_ids": ["centrobus-og1"],
    }
    with zipfile.ZipFile(first) as archive:
        assert set(archive.namelist()) == {
            "agency.txt",
            "attributions.txt",
            "calendar.txt",
            "calendar_dates.txt",
            "feed_info.txt",
            "routes.txt",
            "shapes.txt",
            "stop_times.txt",
            "stops.txt",
            "trips.txt",
        }

    database = ProjectDatabase(
        tmp_path / "project.duckdb",
        tmp_path / "temporary",
        settings=DatabaseSettings(memory_limit="128MB", max_temp_directory_size="128MB"),
    )
    result = ImportFeed(
        database,
        ProjectMetadata("golines-demo", "GoLines demo", ProjectStatus.READY),
        InputSource(first, InputSourceKind.ARCHIVE),
        load_schedule_spec(ROOT / "schemas" / "gtfs_schedule" / "2026-04-27" / "spec.json"),
        job_id="golines-job",
        feed_id="golines-feed",
    ).execute()

    assert result.state is JobState.READY
    assert result.issue_count == 0
