from __future__ import annotations

from pathlib import Path

import pytest

from gtfs_explorer.domain.validation import ValidationContext, ValidationSeverity
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.infrastructure.validation.geometry import GeometryValidationRule


def _database(tmp_path: Path) -> ProjectDatabase:
    database = ProjectDatabase(
        tmp_path / "project.duckdb",
        tmp_path / "temporary",
        settings=DatabaseSettings(memory_limit="128MB", max_temp_directory_size="128MB", threads=1),
    )
    database.initialize()
    return database


def _issues(
    database: ProjectDatabase, *, threshold: float = 100.0
) -> list[tuple[str, ValidationSeverity, dict[str, object]]]:
    with database.connection() as connection:
        return [
            (issue.rule_code, issue.severity, dict(issue.message.parameters))
            for issue in GeometryValidationRule(
                connection, stop_shape_distance_threshold_meters=threshold
            ).evaluate(ValidationContext("feed", "batch"))
        ]


def _insert_shape(
    database: ProjectDatabase,
    source_row: int,
    shape_id: str,
    latitude: float,
    longitude: float,
    sequence: int,
) -> None:
    with database.connection() as connection:
        connection.execute(
            "INSERT INTO gtfs_shapes "
            "(source_filename, source_row, raw_values, shape_id, shape_pt_lat, shape_pt_lon, "
            "shape_pt_sequence) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ["shapes.txt", source_row, "{}", shape_id, latitude, longitude, sequence],
        )


def test_geometry_accepts_zero_coordinates_and_reports_only_contextual_distance(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    _insert_shape(database, 2, "SH1", 0.0, 0.0, 1)
    _insert_shape(database, 3, "SH1", 0.0, 0.01, 2)
    with database.connection() as connection:
        connection.execute(
            "INSERT INTO gtfs_stops (source_filename, source_row, raw_values, stop_id, "
            "stop_lat, stop_lon) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ["stops.txt", 2, "{}", "S1", 0.01, 0.005],
        )
        connection.execute(
            "INSERT INTO gtfs_trips (source_filename, source_row, raw_values, route_id, "
            "service_id, "
            "trip_id, shape_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ["trips.txt", 2, "{}", "R1", "W", "T1", "SH1"],
        )
        connection.execute(
            "INSERT INTO gtfs_stop_times (source_filename, source_row, raw_values, trip_id, "
            "stop_id, "
            "stop_sequence) VALUES (?, ?, ?, ?, ?, ?)",
            ["stop_times.txt", 2, "{}", "T1", "S1", 1],
        )

    issues = _issues(database, threshold=500.0)

    assert issues == [
        (
            "GTFS_STOP_SHAPE_DISTANCE_EXCEEDS_THRESHOLD",
            ValidationSeverity.WARNING,
            {
                "distance_meters": pytest.approx(1111.951, abs=1),
                "method": "local_azimuthal_equidistant_projection",
                "shape_id": "SH1",
                "stop_id": "S1",
                "threshold_meters": 500.0,
                "unit": "meters",
            },
        )
    ]


def test_geometry_reports_degenerate_shape_and_duplicate_sequence(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _insert_shape(database, 2, "SH1", 43.0, -5.0, 1)
    _insert_shape(database, 3, "SH1", 43.0, -5.0, 1)

    assert [code for code, _, _ in _issues(database)] == [
        "GTFS_SHAPE_DEGENERATE",
        "GTFS_SHAPE_SEQUENCE_DUPLICATED",
    ]


def test_geometry_rejects_non_positive_distance_threshold(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with database.connection() as connection:
        with pytest.raises(ValueError, match="umbral"):
            GeometryValidationRule(connection, stop_shape_distance_threshold_meters=0)
