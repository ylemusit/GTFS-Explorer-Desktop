"""Contrato de resolución de calendarios GTFS por fecha."""

from datetime import date
from pathlib import Path

from gtfs_explorer.domain.service_calendar import (
    CalendarException,
    CalendarRule,
    ServiceCalendar,
    ServicePeriod,
)
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.infrastructure.duckdb.repositories import DuckDbUnitOfWork


def _database(tmp_path: Path) -> ProjectDatabase:
    return ProjectDatabase(
        tmp_path / "project.duckdb",
        tmp_path / "temporary",
        settings=DatabaseSettings(memory_limit="128MB", max_temp_directory_size="128MB", threads=1),
    )


def test_service_calendar_applies_weekends_and_exceptions_with_removal_precedence() -> None:
    calendar = ServiceCalendar(
        rules=(
            CalendarRule(
                "weekday",
                (True, True, True, True, True, False, False),
                ServicePeriod(date(2026, 1, 1), date(2026, 12, 31)),
            ),
        ),
        exceptions=(
            CalendarException("weekend_extra", date(2026, 1, 3), 1),
            CalendarException("weekday", date(2026, 1, 5), 2),
        ),
    )

    assert calendar.service_ids_on(date(2026, 1, 3)) == ("weekend_extra",)
    assert calendar.service_ids_on(date(2026, 1, 5)) == ()


def test_service_calendar_supports_calendar_dates_only_empty_ranges_and_extreme_dates() -> None:
    calendar = ServiceCalendar(
        exceptions=(
            CalendarException("first", date.min, 1),
            CalendarException("last", date.max, 1),
        )
    )

    assert calendar.service_ids_on(date.min) == ("first",)
    assert calendar.service_ids_on(date.max) == ("last",)
    assert calendar.period() == ServicePeriod(date.min, date.max)
    assert ServiceCalendar().period() is None


def test_duckdb_service_calendar_query_uses_exceptions_and_calendar_dates_only(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    with database.connection() as connection:
        connection.executemany(
            "INSERT INTO gtfs_calendar "
            "(source_filename, source_row, raw_values, service_id, monday, tuesday, wednesday, "
            "thursday, friday, saturday, sunday, start_date, end_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
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
                )
            ],
        )
        connection.executemany(
            "INSERT INTO gtfs_calendar_dates "
            "(source_filename, source_row, raw_values, service_id, date, exception_type) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("calendar_dates.txt", 1, "{}", "weekday", date(2026, 1, 5), 2),
                ("calendar_dates.txt", 2, "{}", "special", date(2026, 1, 3), 1),
            ],
        )

    with DuckDbUnitOfWork(database) as unit_of_work:
        assert unit_of_work.service_calendar.service_ids_on(date(2026, 1, 3)) == ("special",)
        assert unit_of_work.service_calendar.service_ids_on(date(2026, 1, 5)) == ()
        assert unit_of_work.service_calendar.service_period() == ServicePeriod(
            date(2026, 1, 1), date(2026, 12, 31)
        )
