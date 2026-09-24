from __future__ import annotations

from pathlib import Path

from gtfs_explorer.domain.spec import FieldSpec, FileSpec, ScheduleSpec, load_schedule_spec
from gtfs_explorer.domain.validation import ValidationContext, ValidationRuleRegistry
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.infrastructure.validation.engine import ValidationEngine
from gtfs_explorer.infrastructure.validation.fields import FieldValidationRule
from gtfs_explorer.infrastructure.validation.references import ReferenceValidationRule

SPEC_PATH = Path("schemas/gtfs_schedule/2026-04-27/spec.json")


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


def test_real_stop_time_enums_accept_zero_and_reject_out_of_domain_values(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    specification = load_schedule_spec(SPEC_PATH)
    with database.connection() as connection:
        connection.execute(
            "INSERT INTO projects VALUES ('project', 'Test', 'READY', now(), now(), 8)"
        )
        connection.execute(
            "INSERT INTO feeds VALUES ('feed', 'project', 'test', 'hash', 'STRICT', '2026-04-27', "
            "'0.1.0', now(), 'READY')"
        )
        connection.execute(
            "CREATE TABLE stg_stop_times (source_row BIGINT, pickup_type VARCHAR, "
            "drop_off_type VARCHAR, start_pickup_drop_off_window VARCHAR, "
            "end_pickup_drop_off_window VARCHAR)"
        )
        for row, pickup_type, drop_off_type in (
            (2, "0", "0"),
            (3, "1", "1"),
            (4, "2", "2"),
            (5, "3", "3"),
            (6, "4", "4"),
        ):
            connection.execute(
                "INSERT INTO stg_stop_times VALUES (?, ?, ?, NULL, NULL)",
                [row, pickup_type, drop_off_type],
            )

        registry = ValidationRuleRegistry()
        registry.register(FieldValidationRule(connection, specification))
        result = ValidationEngine(registry).execute(
            connection,
            feed_id="feed",
            batch_id="batch",
        )
        issues = connection.execute(
            "SELECT rule_code, row_number, field_name FROM validation_issues "
            "WHERE batch_id = 'batch' ORDER BY position"
        ).fetchall()

    assert result.total_issue_count == 2
    assert issues == [
        (
            "GTFS_STOP_TIMES_TXT_PICKUP_TYPE_CONDITIONALLY_FORBIDDEN",
            6,
            "pickup_type",
        ),
        (
            "GTFS_STOP_TIMES_TXT_DROP_OFF_TYPE_CONDITIONALLY_FORBIDDEN",
            6,
            "drop_off_type",
        ),
    ]


def test_route_type_accepts_known_extensions_but_rejects_unknown_numeric_values(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    specification = load_schedule_spec(SPEC_PATH)
    with database.connection() as connection:
        connection.execute("CREATE TABLE stg_routes (source_row BIGINT, route_type VARCHAR)")
        connection.executemany(
            "INSERT INTO stg_routes VALUES (?, ?)", [(2, "3"), (3, "715"), (4, "1301"), (5, "999")]
        )
        issues = tuple(
            FieldValidationRule(connection, specification).evaluate(
                ValidationContext("feed", "batch")
            )
        )

    assert [(issue.row_number, issue.field_name) for issue in issues] == [(5, "route_type")]


def test_conditional_stop_time_enums_remain_coherent_with_semantics() -> None:
    specification = load_schedule_spec(SPEC_PATH)
    stop_times = specification.files["stop_times.txt"].fields

    assert specification.enums["GTFS_ENUM_STOP_TIMES_TXT_PICKUP_TYPE"] == (
        "0",
        "1",
        "2",
        "3",
    )
    assert specification.enums["GTFS_ENUM_STOP_TIMES_TXT_DROP_OFF_TYPE"] == (
        "0",
        "1",
        "2",
        "3",
    )
    assert stop_times["pickup_type"].rule_id == (
        "GTFS_STOP_TIMES_TXT_PICKUP_TYPE_CONDITIONALLY_FORBIDDEN"
    )
    assert stop_times["drop_off_type"].rule_id == (
        "GTFS_STOP_TIMES_TXT_DROP_OFF_TYPE_CONDITIONALLY_FORBIDDEN"
    )
    assert "pickup_type=0" in (stop_times["pickup_type"].condition or "")
    assert "drop_off_type=0" in (stop_times["drop_off_type"].condition or "")


def test_gtfs_023_field_enums_accept_corrected_values_and_reject_nine(tmp_path: Path) -> None:
    database = _database(tmp_path)
    specification = load_schedule_spec(SPEC_PATH)
    cases = (
        ("stops", "wheelchair_boarding", ("0", "1", "2")),
        ("routes", "continuous_pickup", ("0", "1", "2", "3")),
        ("routes", "continuous_drop_off", ("0", "1", "2", "3")),
        ("stop_times", "continuous_pickup", ("0", "1", "2", "3")),
        ("stop_times", "continuous_drop_off", ("0", "1", "2", "3")),
    )
    with database.connection() as connection:
        for table, field, values in cases:
            connection.execute(f"CREATE TABLE stg_{table} (source_row BIGINT, {field} VARCHAR)")
            connection.executemany(
                f"INSERT INTO stg_{table} VALUES (?, ?)",
                [*enumerate((*values, "", "9"), start=2)],
            )
            issues = tuple(
                FieldValidationRule(connection, specification).evaluate(
                    ValidationContext("feed", "batch")
                )
            )
            assert [(issue.file_name, issue.row_number, issue.field_name) for issue in issues] == [
                (f"{table}.txt", len(values) + 3, field)
            ]
            assert issues[0].severity.value == "ERROR"
            assert issues[0].category.value == "FIELD"
            assert issues[0].rule_code == specification.files[f"{table}.txt"].fields[field].rule_id
            connection.execute(f"DROP TABLE stg_{table}")


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
