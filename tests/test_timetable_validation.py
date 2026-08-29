from __future__ import annotations

from pathlib import Path

import pytest

from gtfs_explorer.domain.validation import ValidationContext
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.infrastructure.validation.timetable import (
    TimetableValidationRule,
    _stop_time_conditions,
    _StopTime,
)


def _database(tmp_path: Path) -> ProjectDatabase:
    database = ProjectDatabase(
        tmp_path / "project.duckdb",
        tmp_path / "temporary",
        settings=DatabaseSettings(memory_limit="128MB", max_temp_directory_size="128MB", threads=1),
    )
    database.initialize()
    return database


def _issues(database: ProjectDatabase) -> list[tuple[str, int, str]]:
    with database.connection() as connection:
        return [
            (issue.rule_code, issue.row_number or 0, issue.field_name or "")
            for issue in TimetableValidationRule(connection).evaluate(
                ValidationContext("feed", "batch")
            )
        ]


def _insert_stop_time(
    database: ProjectDatabase,
    row: int,
    trip_id: str,
    sequence: int,
    arrival: int | None,
    departure: int | None,
    **values: int | str | None,
) -> None:
    columns = [
        "source_filename",
        "source_row",
        "raw_values",
        "trip_id",
        "arrival_service_seconds",
        "departure_service_seconds",
        "stop_id",
        "stop_sequence",
        "location_group_id",
        "location_id",
        "start_pickup_drop_off_window_service_seconds",
        "end_pickup_drop_off_window_service_seconds",
        "pickup_type",
        "drop_off_type",
        "continuous_pickup",
        "continuous_drop_off",
        "timepoint",
    ]
    defaults: dict[str, int | str | None] = {
        "stop_id": "S" + str(row),
        "stop_sequence": sequence,
        "location_group_id": None,
        "location_id": None,
        "start_pickup_drop_off_window_service_seconds": None,
        "end_pickup_drop_off_window_service_seconds": None,
        "pickup_type": None,
        "drop_off_type": None,
        "continuous_pickup": None,
        "continuous_drop_off": None,
        "timepoint": None,
    }
    defaults.update(values)
    payload = ["stop_times.txt", row, "{}", trip_id, arrival, departure]
    payload.extend(defaults[column] for column in columns[6:])
    with database.connection() as connection:
        placeholders = ", ".join("?" for _ in columns)
        connection.execute(
            f"INSERT INTO gtfs_stop_times ({', '.join(columns)}) VALUES ({placeholders})",
            payload,
        )


def test_timetable_accepts_service_times_after_midnight_and_loops(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _insert_stop_time(database, 2, "T1", 1, 25 * 3600, 25 * 3600 + 60, stop_id="LOOP")
    _insert_stop_time(database, 3, "T1", 2, 26 * 3600, 26 * 3600 + 60, stop_id="LOOP")

    assert _issues(database) == []


def test_timetable_reports_duplicate_sequence_and_real_time_regression(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _insert_stop_time(database, 2, "T1", 1, 8 * 3600, 8 * 3600 + 60)
    _insert_stop_time(database, 3, "T1", 1, 8 * 3600, 7 * 3600 + 59)

    assert _issues(database) == [
        ("GTFS_STOP_SEQUENCE_DUPLICATED", 3, "stop_sequence"),
        ("GTFS_STOP_TIME_DEPARTURE_BEFORE_ARRIVAL", 3, "departure_time"),
        ("GTFS_STOP_TIME_SEQUENCE_REGRESSION", 3, "arrival_time"),
    ]


def test_timetable_requires_scheduled_times_at_timepoints_and_validates_windows(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    _insert_stop_time(database, 2, "T1", 1, None, None, timepoint=1)
    _insert_stop_time(
        database,
        3,
        "T1",
        2,
        9 * 3600,
        9 * 3600,
        location_group_id="G1",
        stop_id=None,
        start_pickup_drop_off_window_service_seconds=10 * 3600,
        end_pickup_drop_off_window_service_seconds=9 * 3600,
        pickup_type=0,
        drop_off_type=0,
        continuous_pickup=2,
        continuous_drop_off=3,
    )

    assert [code for code, _, _ in _issues(database)] == [
        "GTFS_STOP_TIME_TIMEPOINT_SCHEDULE_REQUIRED",
        "GTFS_STOP_TIME_WINDOW_ORDER_INVALID",
        "GTFS_STOP_TIME_WINDOW_WITH_SCHEDULED_TIME",
        "GTFS_STOP_TIME_WINDOW_PICKUP_FORBIDDEN",
        "GTFS_STOP_TIME_WINDOW_DROP_OFF_FORBIDDEN",
        "GTFS_STOP_TIME_WINDOW_CONTINUOUS_PICKUP_FORBIDDEN",
        "GTFS_STOP_TIME_WINDOW_CONTINUOUS_DROP_OFF_FORBIDDEN",
        "GTFS_STOP_TIME_TERMINAL_ARRIVAL_REQUIRED",
    ]


@pytest.mark.parametrize(
    ("pickup_type", "drop_off_type", "expected_window_issues"),
    [
        (
            0,
            0,
            {"GTFS_STOP_TIME_WINDOW_PICKUP_FORBIDDEN", "GTFS_STOP_TIME_WINDOW_DROP_OFF_FORBIDDEN"},
        ),
        (3, 1, {"GTFS_STOP_TIME_WINDOW_PICKUP_FORBIDDEN"}),
        (1, 0, {"GTFS_STOP_TIME_WINDOW_DROP_OFF_FORBIDDEN"}),
        (None, None, set()),
    ],
)
def test_timetable_applies_pickup_and_drop_off_conditions_only_with_windows(
    tmp_path: Path,
    pickup_type: int | None,
    drop_off_type: int | None,
    expected_window_issues: set[str],
) -> None:
    database = _database(tmp_path)
    _insert_stop_time(
        database,
        2,
        "T1",
        1,
        None,
        None,
        pickup_type=pickup_type,
        drop_off_type=drop_off_type,
        start_pickup_drop_off_window_service_seconds=10 * 3600,
        end_pickup_drop_off_window_service_seconds=11 * 3600,
    )

    actual = {
        code
        for code, _, _ in _issues(database)
        if code
        in {
            "GTFS_STOP_TIME_WINDOW_PICKUP_FORBIDDEN",
            "GTFS_STOP_TIME_WINDOW_DROP_OFF_FORBIDDEN",
        }
    }
    assert actual == expected_window_issues


def test_timetable_allows_regular_pickup_and_drop_off_without_windows(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _insert_stop_time(database, 2, "T1", 1, 8 * 3600, 8 * 3600, pickup_type=0, drop_off_type=0)

    assert {
        code
        for code, _, _ in _issues(database)
        if code
        in {
            "GTFS_STOP_TIME_WINDOW_PICKUP_FORBIDDEN",
            "GTFS_STOP_TIME_WINDOW_DROP_OFF_FORBIDDEN",
        }
    } == set()


@pytest.mark.parametrize("empty_window", [None, "", "   "])
@pytest.mark.parametrize("pickup_type,drop_off_type", [(0, 0), (3, 0), (0, 1)])
def test_timetable_treats_absent_empty_and_whitespace_windows_as_absent(
    empty_window: int | str | None, pickup_type: int, drop_off_type: int
) -> None:
    row = _StopTime(
        source_row=2,
        trip_id="T1",
        arrival=None,
        departure=None,
        stop_id="S1",
        location_group_id=None,
        location_id=None,
        sequence=1,
        window_start=empty_window,
        window_end=empty_window,
        pickup_type=pickup_type,
        drop_off_type=drop_off_type,
        continuous_pickup=None,
        continuous_drop_off=None,
        timepoint=None,
    )

    assert {
        issue.rule_code
        for issue in _stop_time_conditions((row,))
        if issue.rule_code
        in {
            "GTFS_STOP_TIME_WINDOW_PICKUP_FORBIDDEN",
            "GTFS_STOP_TIME_WINDOW_DROP_OFF_FORBIDDEN",
        }
    } == set()


@pytest.mark.parametrize("pickup_type,drop_off_type", [(0, 0), (3, 1), (1, 0)])
def test_timetable_rejects_pickup_and_drop_off_values_with_informed_window(
    pickup_type: int, drop_off_type: int
) -> None:
    row = _StopTime(
        source_row=2,
        trip_id="T1",
        arrival=None,
        departure=None,
        stop_id="S1",
        location_group_id=None,
        location_id=None,
        sequence=1,
        window_start=10 * 3600,
        window_end=11 * 3600,
        pickup_type=pickup_type,
        drop_off_type=drop_off_type,
        continuous_pickup=None,
        continuous_drop_off=None,
        timepoint=None,
    )

    actual = {
        issue.rule_code
        for issue in _stop_time_conditions((row,))
        if issue.rule_code
        in {
            "GTFS_STOP_TIME_WINDOW_PICKUP_FORBIDDEN",
            "GTFS_STOP_TIME_WINDOW_DROP_OFF_FORBIDDEN",
        }
    }
    expected = set()
    if pickup_type in (0, 3):
        expected.add("GTFS_STOP_TIME_WINDOW_PICKUP_FORBIDDEN")
    if drop_off_type == 0:
        expected.add("GTFS_STOP_TIME_WINDOW_DROP_OFF_FORBIDDEN")
    assert actual == expected


def test_timetable_reports_invalid_frequency_window(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with database.connection() as connection:
        connection.execute(
            "INSERT INTO gtfs_frequencies (source_filename, source_row, raw_values, trip_id, "
            "start_time_service_seconds, end_time_service_seconds) VALUES (?, ?, ?, ?, ?, ?)",
            ["frequencies.txt", 2, "{}", "T1", 10 * 3600, 10 * 3600],
        )

    assert _issues(database) == [("GTFS_FREQUENCY_TIME_RANGE_INVALID", 2, "end_time")]
