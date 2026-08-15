"""Contrato de líneas y métricas geográficas de un viaje GTFS."""

from __future__ import annotations

from pathlib import Path

import pytest

from gtfs_explorer.application.queries.geometry import GeometryQueries
from gtfs_explorer.domain.geometry import TripShapeGeometry
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.infrastructure.duckdb.repositories import DuckDbUnitOfWork


def _database(tmp_path: Path) -> ProjectDatabase:
    path = tmp_path / "project.duckdb"
    return ProjectDatabase(
        path,
        tmp_path / "temporary",
        settings=DatabaseSettings(memory_limit="128MB", max_temp_directory_size="128MB", threads=1),
    )


def _seed(database: ProjectDatabase, *, shape_points: list[tuple[object, object]]) -> None:
    with database.connection() as connection:
        connection.execute(
            "INSERT INTO gtfs_trips (source_filename, source_row, raw_values, route_id, "
            "service_id, "
            "trip_id, shape_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ["trips.txt", 1, "{}", "R1", "weekday", "T1", "SH1"],
        )
        connection.executemany(
            "INSERT INTO gtfs_shapes (source_filename, source_row, raw_values, shape_id, "
            "shape_pt_lat, shape_pt_lon, shape_pt_sequence) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("shapes.txt", index, "{}", "SH1", latitude, longitude, index)
                for index, (latitude, longitude) in enumerate(shape_points, start=1)
            ],
        )
        connection.execute(
            "INSERT INTO gtfs_stops (source_filename, source_row, raw_values, stop_id, "
            "stop_lat, stop_lon) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ["stops.txt", 1, "{}", "S1", 0.1, 179.95],
        )
        connection.execute(
            "INSERT INTO gtfs_stop_times (source_filename, source_row, raw_values, trip_id, "
            "stop_id, "
            "stop_sequence) VALUES (?, ?, ?, ?, ?, ?)",
            ["stop_times.txt", 1, "{}", "T1", "S1", 1],
        )


def _query(database: ProjectDatabase) -> TripShapeGeometry:
    with DuckDbUnitOfWork(database) as unit_of_work:
        return GeometryQueries(unit_of_work.geometry).trip_shape("T1")


@pytest.mark.integration
def test_trip_shape_orders_points_and_handles_antimeridian_in_meters(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed(database, shape_points=[(0.0, -179.9), (0.0, 179.9), (0.0, -179.9)])

    geometry = _query(database)

    assert [point.longitude for point in geometry.coordinates] == [-179.9, 179.9, -179.9]
    assert geometry.length_meters == pytest.approx(44_478, rel=0.01)
    assert geometry.bbox is not None
    assert geometry.bbox.crosses_antimeridian is True
    assert geometry.distance_unit == "meters"
    assert geometry.length_method == "haversine_spherical_geodesic"
    assert geometry.distance_method == "local_azimuthal_equidistant_projection"
    assert geometry.stop_distances[0].distance_meters is not None
    assert geometry.stop_distances[0].distance_meters < 20_000


@pytest.mark.integration
def test_repeated_points_are_valid_and_do_not_add_artificial_length(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed(database, shape_points=[(43.0, -5.0), (43.0, -5.0), (43.001, -5.0)])

    geometry = _query(database)

    assert geometry.length_meters == pytest.approx(111.2, rel=0.01)
    assert not geometry.issues


@pytest.mark.integration
def test_short_or_invalid_shape_returns_issues_without_crashing(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed(database, shape_points=[(95.0, 1.0), (43.0, -5.0)])

    geometry = _query(database)

    assert geometry.coordinates == (geometry.coordinates[0],)
    assert geometry.length_meters is None
    assert geometry.stop_distances[0].distance_meters is None
    assert {issue.code for issue in geometry.issues} == {
        "SHAPE_COORDINATE_INVALID",
        "SHAPE_TOO_SHORT",
    }
