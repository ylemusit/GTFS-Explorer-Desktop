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
