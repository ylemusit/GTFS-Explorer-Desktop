"""Contratos de la exploración encadenada ruta, viaje y parada."""

from pathlib import Path

from gtfs_explorer.application.queries.routes import RouteExplorerQueries
from gtfs_explorer.domain.ports import PageRequest
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.infrastructure.duckdb.repositories import DuckDbUnitOfWork


def _database(tmp_path: Path) -> ProjectDatabase:
    return ProjectDatabase(
        tmp_path / "project.duckdb",
        tmp_path / "temporary",
        settings=DatabaseSettings(memory_limit="128MB", max_temp_directory_size="128MB", threads=1),
    )


def _seed(database: ProjectDatabase) -> None:
    with database.connection() as connection:
        connection.executemany(
            "INSERT INTO gtfs_routes "
            "(source_filename, source_row, raw_values, route_id, agency_id, route_short_name, "
            "route_long_name, route_type, route_sort_order) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("routes.txt", 1, "{}", "R-A", "agency-a", "10", None, 3, 2),
                ("routes.txt", 2, "{}", "R-B", "agency-b", None, "Interurbana", 3, 1),
            ],
        )
        connection.executemany(
            "INSERT INTO gtfs_trips "
            "(source_filename, source_row, raw_values, route_id, service_id, trip_id, "
            "trip_headsign, trip_short_name, direction_id, shape_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("trips.txt", 1, "{}", "R-A", "weekday", "T-NULL", None, None, None, None),
                ("trips.txt", 2, "{}", "R-A", "weekday", "T-0-A", "Centro", None, 0, "S0"),
                ("trips.txt", 3, "{}", "R-A", "weekday", "T-0-B", "Centro", None, 0, "S0"),
                ("trips.txt", 4, "{}", "R-A", "weekday", "T-1", "Puerto", None, 1, "S1"),
                ("trips.txt", 5, "{}", "R-A", "weekend", "T-WE", None, None, 0, None),
            ],
        )
        connection.executemany(
            "INSERT INTO gtfs_stops "
            "(source_filename, source_row, raw_values, stop_id, stop_name) VALUES (?, ?, ?, ?, ?)",
            [
                ("stops.txt", 1, "{}", "S-NAMED", "Norte"),
                ("stops.txt", 2, "{}", "S-ID-ONLY", None),
            ],
        )
        connection.executemany(
            "INSERT INTO gtfs_stop_times "
            "(source_filename, source_row, raw_values, trip_id, arrival_time_lexeme, "
            "arrival_service_seconds, departure_time_lexeme, departure_service_seconds, stop_id, "
            "stop_sequence) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "stop_times.txt",
                    3,
                    "{}",
                    "T-0-A",
                    "25:15:00",
                    90900,
                    "25:16:00",
                    90960,
                    "S-NAMED",
                    20,
                ),
                (
                    "stop_times.txt",
                    1,
                    "{}",
                    "T-0-A",
                    "24:01:00",
                    86460,
                    "24:02:00",
                    86520,
                    "S-ID-ONLY",
                    10,
                ),
                ("stop_times.txt", 2, "{}", "T-0-A", None, None, None, None, "S-MISSING", 15),
            ],
        )


def test_route_explorer_chains_multiagency_services_directions_and_similar_trips(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    _seed(database)

    with DuckDbUnitOfWork(database) as unit_of_work:
        queries = RouteExplorerQueries(unit_of_work.route_explorer)
        routes = queries.routes(PageRequest(limit=1))
        services = queries.services_for_route("R-A", PageRequest())
        directions = queries.directions_for_route_service("R-A", "weekday", PageRequest())
        null_trips = queries.trips_for_route_service_direction(
            "R-A", "weekday", None, PageRequest()
        )
        zero_trips = queries.trips_for_route_service_direction("R-A", "weekday", 0, PageRequest())
        one_trips = queries.trips_for_route_service_direction("R-A", "weekday", 1, PageRequest())

    assert routes.total == 2
    assert routes.items[0].route_id == "R-A"
    assert routes.next_offset == 1
    assert [(item.service_id, item.trip_count) for item in services.items] == [
        ("weekday", 4),
        ("weekend", 1),
    ]
    assert [(item.direction_id, item.trip_count) for item in directions.items] == [
        (0, 2),
        (1, 1),
        (None, 1),
    ]
    assert [item.trip_id for item in null_trips.items] == ["T-NULL"]
    assert [item.trip_id for item in zero_trips.items] == ["T-0-A", "T-0-B"]
    assert [item.trip_id for item in one_trips.items] == ["T-1"]


def test_route_explorer_timeline_keeps_ids_orders_sequences_and_preserves_service_times(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    _seed(database)

    with DuckDbUnitOfWork(database) as unit_of_work:
        timeline = RouteExplorerQueries(unit_of_work.route_explorer).trip_timeline(
            "T-0-A", PageRequest(limit=2)
        )

    assert timeline.total == 3
    assert timeline.next_offset == 2
    assert [(item.stop_sequence, item.stop_id, item.stop_name) for item in timeline.items] == [
        (10, "S-ID-ONLY", None),
        (15, "S-MISSING", None),
    ]
    assert timeline.items[0].arrival_time == "24:01:00"
    assert timeline.items[0].arrival_service_seconds == 86460

    with DuckDbUnitOfWork(database) as unit_of_work:
        final_stop = (
            RouteExplorerQueries(unit_of_work.route_explorer)
            .trip_timeline("T-0-A", PageRequest(offset=2, limit=1))
            .items[0]
        )

    assert final_stop.stop_sequence == 20
    assert final_stop.arrival_time == "25:15:00"
    assert final_stop.arrival_service_seconds == 90900
    assert final_stop.departure_time == "25:16:00"
    assert final_stop.departure_service_seconds == 90960
