from __future__ import annotations

from pathlib import Path

from gtfs_explorer.domain.spec import FieldSpec, FileSpec, ScheduleSpec
from gtfs_explorer.domain.validation import ValidationContext
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.infrastructure.validation.fields import FieldValidationRule
from gtfs_explorer.infrastructure.validation.references import ReferenceValidationRule


def _database(tmp_path: Path) -> ProjectDatabase:
    database = ProjectDatabase(
        tmp_path / "project.duckdb",
        tmp_path / "temporary",
        settings=DatabaseSettings(memory_limit="128MB", max_temp_directory_size="128MB", threads=1),
    )
    database.initialize()
    return database


def _spec() -> ScheduleSpec:
    return ScheduleSpec(
        "test",
        {"url": "https://example.test"},
        {
            "stops.txt": FileSpec(
                "required",
                "FILE_STOPS",
                "https://example.test",
                None,
                {
                    "stop_id": FieldSpec(
                        "required", "ID", "STOP_ID", "https://example.test", (), None, None
                    ),
                    "stop_lat": FieldSpec(
                        "required", "Latitude", "STOP_LAT", "https://example.test", (), None, None
                    ),
                    "location_type": FieldSpec(
                        "optional",
                        "Enum",
                        "LOCATION_TYPE",
                        "https://example.test",
                        (),
                        "LOCATION",
                        None,
                    ),
                },
            ),
            "trips.txt": FileSpec(
                "required",
                "FILE_TRIPS",
                "https://example.test",
                None,
                {
                    "trip_id": FieldSpec(
                        "required", "ID", "TRIP_ID", "https://example.test", (), None, None
                    ),
                    "stop_id": FieldSpec(
                        "required",
                        "Foreign ID",
                        "TRIP_STOP",
                        "https://example.test",
                        ("stops.stop_id",),
                        None,
                        None,
                    ),
                },
            ),
        },
        {"LOCATION": ("0", "1")},
    )


def test_field_rule_reports_row_field_type_and_enum_issues(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with database.connection() as connection:
        connection.execute(
            "CREATE TABLE stg_stops (source_row BIGINT, stop_id VARCHAR, "
            "stop_lat VARCHAR, location_type VARCHAR)"
        )
        connection.execute("INSERT INTO stg_stops VALUES (7, 's1', '91', '9')")
        issues = tuple(
            FieldValidationRule(connection, _spec()).evaluate(ValidationContext("feed", "batch"))
        )

    assert [(issue.rule_code, issue.row_number, issue.field_name) for issue in issues] == [
        ("STOP_LAT", 7, "stop_lat"),
        ("LOCATION_TYPE", 7, "location_type"),
    ]


def test_reference_rule_uses_set_query_and_reports_missing_target(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with database.connection() as connection:
        connection.execute("CREATE TABLE stg_stops (source_row BIGINT, stop_id VARCHAR)")
        connection.execute("INSERT INTO stg_stops VALUES (2, 'known')")
        connection.execute(
            "CREATE TABLE stg_trips (source_row BIGINT, trip_id VARCHAR, stop_id VARCHAR)"
        )
        connection.execute("INSERT INTO stg_trips VALUES (4, 't1', 'missing')")
        issues = tuple(
            ReferenceValidationRule(connection, _spec()).evaluate(
                ValidationContext("feed", "batch")
            )
        )

    assert [(issue.rule_code, issue.row_number, issue.field_name) for issue in issues] == [
        ("TRIP_STOP", 4, "stop_id")
    ]
