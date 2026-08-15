"""Contrato del inspector de paradas basado exclusivamente en GTFS Schedule."""

from datetime import date
from pathlib import Path

from gtfs_explorer.application.queries.stops import StopInspectorQueries
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
            "INSERT INTO gtfs_stops (source_filename, source_row, raw_values, stop_id, stop_name, "
            "parent_station) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("stops.txt", 1, "{}", "STATION", "Estacion central", None),
                ("stops.txt", 2, "{}", "PLATFORM-A", "Anden A", "STATION"),
                ("stops.txt", 3, "{}", "EMPTY", "Sin viajes", None),
            ],
        )
        connection.executemany(
            "INSERT INTO gtfs_routes (source_filename, source_row, raw_values, route_id, "
            "agency_id, "
            "route_short_name, route_long_name, route_type, route_sort_order) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("routes.txt", 1, "{}", "R1", "A", "1", None, 3, 2),
                ("routes.txt", 2, "{}", "R2", "A", "2", None, 3, 1),
            ],
        )
        connection.executemany(
            "INSERT INTO gtfs_trips (source_filename, source_row, raw_values, route_id, "
            "service_id, "
            "trip_id, trip_headsign, trip_short_name, direction_id, shape_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("trips.txt", 1, "{}", "R1", "weekday", "T1", None, None, 0, None),
                ("trips.txt", 2, "{}", "R2", "weekend", "T2", None, None, 1, None),
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
                    1,
                    "{}",
                    "T1",
                    "08:00:00",
                    28800,
                    "08:01:00",
                    28860,
                    "PLATFORM-A",
                    1,
                ),
                (
                    "stop_times.txt",
                    2,
                    "{}",
                    "T2",
                    "25:00:00",
                    90000,
                    "25:01:00",
                    90060,
                    "PLATFORM-A",
                    2,
                ),
            ],
        )
        connection.execute(
            "INSERT INTO gtfs_calendar (source_filename, source_row, raw_values, service_id, "
            "monday, "
            "tuesday, wednesday, thursday, friday, saturday, sunday, start_date, end_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                "calendar.txt",
                1,
                "{}",
                "weekday",
                1,
                1,
                1,
                1,
                1,
                0,
                0,
                date(2026, 1, 1),
                date(2026, 12, 31),
            ],
        )
        connection.execute(
            "INSERT INTO gtfs_calendar_dates (source_filename, source_row, raw_values, service_id, "
            "date, "
            "exception_type) VALUES (?, ?, ?, ?, ?, ?)",
            ["calendar_dates.txt", 1, "{}", "weekend", date(2026, 1, 3), 1],
        )


def test_stop_inspector_includes_child_platforms_and_multiple_routes_with_paging(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    _seed(database)

    with DuckDbUnitOfWork(database) as unit_of_work:
        inspection = StopInspectorQueries(unit_of_work.stop_inspector).inspect(
            "STATION", page=PageRequest(limit=1)
        )

    assert inspection.stop is not None
    assert inspection.stop.stop_id == "STATION"
    assert inspection.service_date is None
    assert inspection.routes.total == 2
    assert inspection.routes.next_offset == 1
    assert [route.route_id for route in inspection.routes.items] == ["R2"]
    assert inspection.services.total == 2
    assert inspection.scheduled_events.total == 2
    assert inspection.scheduled_events.next_offset == 1
    event = inspection.scheduled_events.items[0]
    assert event.stop_id == "PLATFORM-A"
    assert event.departure_time == "08:01:00"
    assert event.departure_service_seconds == 28860


def test_stop_inspector_returns_empty_pages_for_stop_without_trips(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed(database)

    with DuckDbUnitOfWork(database) as unit_of_work:
        inspection = StopInspectorQueries(unit_of_work.stop_inspector).inspect(
            "EMPTY", page=PageRequest()
        )

    assert inspection.stop is not None
    assert inspection.routes.total == 0
    assert inspection.services.total == 0
    assert inspection.scheduled_events.total == 0


def test_stop_inspector_filters_scheduled_events_by_explicit_service_date(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed(database)

    with DuckDbUnitOfWork(database) as unit_of_work:
        inspection = StopInspectorQueries(unit_of_work.stop_inspector).inspect(
            "PLATFORM-A", service_date=date(2026, 1, 3), page=PageRequest()
        )

    assert inspection.service_date == date(2026, 1, 3)
    assert [event.trip_id for event in inspection.scheduled_events.items] == ["T2"]
    assert inspection.scheduled_events.items[0].departure_time == "25:01:00"
