from __future__ import annotations

from pathlib import Path

import pytest

from gtfs_explorer.domain.source import InputSource, InputSourceKind
from gtfs_explorer.domain.spec import load_schedule_spec
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.infrastructure.importing.directory_source import DirectorySource
from gtfs_explorer.infrastructure.importing.normalizers.core import CoreNormalizer
from gtfs_explorer.infrastructure.importing.staging_loader import StagingLoader

SPEC_PATH = Path("schemas/gtfs_schedule/2026-04-27/spec.json")


def _database(tmp_path: Path) -> ProjectDatabase:
    return ProjectDatabase(
        tmp_path / "project.duckdb",
        tmp_path / "temporary",
        settings=DatabaseSettings(memory_limit="128MB", max_temp_directory_size="128MB"),
    )


def _stage(database: ProjectDatabase, source: Path) -> None:
    manifest = DirectorySource().inventory(InputSource(source, InputSourceKind.DIRECTORY))
    StagingLoader().load(database, source, manifest, load_schedule_spec(SPEC_PATH))


def _write(source: Path, filename: str, content: str) -> None:
    (source / filename).write_text(content, encoding="utf-8")


@pytest.mark.integration
def test_normalizes_core_with_typed_values_and_traceable_lexemes(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write(
        source,
        "agency.txt",
        "agency_name,agency_url,agency_timezone\nDemo,https://example.invalid,Europe/Madrid\n",
    )
    _write(source, "stops.txt", "stop_id,stop_name,stop_lat,stop_lon\nS1,North,43.1,-5.8\n")
    _write(source, "routes.txt", "route_id,route_short_name,route_type\nR1,1,3\n")
    _write(source, "trips.txt", "route_id,service_id,trip_id\nR1,weekday,T1\n")
    _write(
        source,
        "stop_times.txt",
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\nT1,25:01:02,25:01:02,S1,1\n",
    )
    _write(
        source,
        "calendar.txt",
        "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\nweekday,1,1,1,1,1,0,0,20260101,20261231\n",
    )
    database = _database(tmp_path)
    _stage(database, source)

    result = CoreNormalizer().normalize(database, load_schedule_spec(SPEC_PATH))

    assert result.issue_count == 0
    with database.connection() as connection:
        assert connection.execute(
            "SELECT arrival_time_lexeme, arrival_service_seconds FROM gtfs_stop_times"
        ).fetchone() == ("25:01:02", 90062)
        assert connection.execute(
            "SELECT start_date_lexeme, start_date FROM gtfs_calendar"
        ).fetchone() == ("20260101", __import__("datetime").date(2026, 1, 1))
        assert connection.execute(
            "SELECT raw_values->>'stop_lat', stop_lat FROM gtfs_stops"
        ).fetchone() == ("43.1", 43.1)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("route_type", "expected_route_type", "expected_issue_count"),
    [("715", 715, 0), ("999", None, 1)],
)
def test_preserves_gtfs_time_semantics_and_classifies_route_type(
    tmp_path: Path, route_type: str, expected_route_type: int | None, expected_issue_count: int
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write(
        source,
        "agency.txt",
        "agency_name,agency_url,agency_timezone\nDemo,https://example.invalid,Europe/Madrid\n",
    )
    _write(
        source,
        "stops.txt",
        "stop_id,stop_name,stop_lat,stop_lon\nS1,North,43.1,-5.8\nS2,South,43.2,-5.9\n",
    )
    _write(source, "routes.txt", f"route_id,route_short_name,route_type\nR1,1,{route_type}\n")
    _write(source, "trips.txt", "route_id,service_id,trip_id\nR1,weekday,T1\n")
    _write(
        source,
        "stop_times.txt",
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
        "T1,23:55:00,24:00:00,S1,1\n"
        "T1,24:30:00,,S2,2\n",
    )
    _write(
        source,
        "calendar.txt",
        "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
        "weekday,1,1,1,1,1,0,0,20260101,20261231\n",
    )
    database = _database(tmp_path)
    _stage(database, source)

    result = CoreNormalizer().normalize(database, load_schedule_spec(SPEC_PATH))

    assert result.issue_count == expected_issue_count
    with database.connection() as connection:
        assert connection.execute(
            "SELECT route_type, raw_values->>'route_type' FROM gtfs_routes"
        ).fetchone() == (expected_route_type, route_type)
        assert connection.execute(
            "SELECT arrival_time_lexeme, arrival_service_seconds, "
            "departure_time_lexeme, departure_service_seconds "
            "FROM gtfs_stop_times ORDER BY stop_sequence"
        ).fetchall() == [
            ("23:55:00", 86100, "24:00:00", 86400),
            ("24:30:00", 88200, "", None),
        ]


@pytest.mark.integration
def test_invalid_core_values_become_null_and_record_a_problem_without_replacing_prior_model(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write(
        source,
        "agency.txt",
        "agency_name,agency_url,agency_timezone\nDemo,https://example.invalid,Europe/Madrid\n",
    )
    _write(source, "routes.txt", "route_id,route_short_name,route_type\nR1,1,bus\n")
    _write(source, "trips.txt", "route_id,service_id,trip_id\nR1,weekday,T1\n")
    _write(
        source,
        "stop_times.txt",
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\nT1,24:00:00,wrong,S1,\n",
    )
    _write(source, "calendar_dates.txt", "service_id,date,exception_type\nweekday,20261340,1\n")
    database = _database(tmp_path)
    _stage(database, source)

    result = CoreNormalizer().normalize(database, load_schedule_spec(SPEC_PATH))

    assert result.issue_count == 4
    with database.connection() as connection:
        assert connection.execute("SELECT route_type FROM gtfs_routes").fetchone() == (None,)
        statement = (
            "SELECT departure_time_lexeme, departure_service_seconds, stop_sequence "
            "FROM gtfs_stop_times"
        )
        assert connection.execute(statement).fetchone() == ("wrong", None, None)
        assert connection.execute(
            "SELECT raw_value FROM normalization_issues WHERE field_name = 'departure_time'"
        ).fetchone() == ("wrong",)


@pytest.mark.integration
def test_normalization_rolls_back_if_insert_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write(
        source,
        "agency.txt",
        "agency_name,agency_url,agency_timezone\nDemo,https://example.invalid,Europe/Madrid\n",
    )
    _write(source, "routes.txt", "route_id,route_short_name,route_type\nR1,1,3\n")
    _write(source, "trips.txt", "route_id,service_id,trip_id\nR1,weekday,T1\n")
    _write(
        source,
        "stop_times.txt",
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\nT1,08:00:00,08:00:00,S1,1\n",
    )
    _write(source, "calendar_dates.txt", "service_id,date,exception_type\nweekday,20260101,1\n")
    database = _database(tmp_path)
    _stage(database, source)
    normalizer = CoreNormalizer()
    normalizer.normalize(database, load_schedule_spec(SPEC_PATH))
    monkeypatch.setattr(
        normalizer, "_normalize_file", lambda *args: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    with pytest.raises(RuntimeError, match="boom"):
        normalizer.normalize(database, load_schedule_spec(SPEC_PATH))

    with database.connection() as connection:
        assert connection.execute("SELECT count(*) FROM gtfs_agency").fetchone() == (1,)


@pytest.mark.integration
def test_gtfs_023_valid_enums_normalize_without_false_issues_and_invalid_values_remain_rejected(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write(
        source,
        "agency.txt",
        "agency_name,agency_url,agency_timezone\nDemo,https://example.invalid,Europe/Madrid\n",
    )
    _write(
        source,
        "stops.txt",
        "stop_id,stop_name,stop_lat,stop_lon,wheelchair_boarding\nS1,North,43.1,-5.8,0\n",
    )
    _write(
        source,
        "routes.txt",
        "route_id,route_short_name,route_type,continuous_pickup,continuous_drop_off\nR1,1,3,1,1\n",
    )
    _write(source, "trips.txt", "route_id,service_id,trip_id\nR1,weekday,T1\n")
    _write(
        source,
        "stop_times.txt",
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence,continuous_pickup,continuous_drop_off\n"
        "T1,08:00:00,08:00:00,S1,1,1,1\n",
    )
    _write(
        source,
        "calendar.txt",
        "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
        "weekday,1,1,1,1,1,0,0,20260101,20261231\n",
    )
    database = _database(tmp_path)
    _stage(database, source)

    result = CoreNormalizer().normalize(database, load_schedule_spec(SPEC_PATH))

    assert result.issue_count == 0
    with database.connection() as connection:
        assert connection.execute(
            "SELECT continuous_pickup, continuous_drop_off FROM gtfs_routes"
        ).fetchone() == (1, 1)
        assert connection.execute(
            "SELECT continuous_pickup, continuous_drop_off FROM gtfs_stop_times"
        ).fetchone() == (1, 1)
        assert connection.execute("SELECT wheelchair_boarding FROM gtfs_stops").fetchone() == (0,)

    _write(
        source,
        "routes.txt",
        "route_id,route_short_name,route_type,continuous_pickup,continuous_drop_off\nR1,1,3,9,1\n",
    )
    _stage(database, source)
    rejected = CoreNormalizer().normalize(database, load_schedule_spec(SPEC_PATH))

    assert rejected.issue_count == 1
    with database.connection() as connection:
        assert connection.execute("SELECT continuous_pickup FROM gtfs_routes").fetchone() == (None,)
        assert connection.execute(
            "SELECT issue_code, raw_value FROM normalization_issues "
            "WHERE field_name = 'continuous_pickup'"
        ).fetchone() == ("GTFS_TYPE_CONVERSION_INVALID", "9")
