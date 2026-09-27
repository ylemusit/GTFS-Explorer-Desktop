"""Integración focal del editor con lifecycle y DuckDB."""

from pathlib import Path

import pytest

from gtfs_explorer.application.editor_session import EditorSession, RevisionConfirmationError
from gtfs_explorer.domain.changesets import (
    EditorCommand,
    EditorCommandKind,
    ImpactResolutionRequired,
    RouteWorkspaceState,
)
from gtfs_explorer.domain.spec import load_schedule_spec
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.infrastructure.duckdb.repositories import DuckDbUnitOfWork
from gtfs_explorer.infrastructure.duckdb.repositories.editor import DuckDbEditorRepository
from gtfs_explorer.infrastructure.exporting.revision import WorkingCopyGtfsBuilder

_SPEC_PATH = Path("schemas/gtfs_schedule/2026-04-27/spec.json")


def _database(tmp_path: Path) -> ProjectDatabase:
    database = ProjectDatabase(
        tmp_path / "data.duckdb",
        tmp_path / "temp",
        settings=DatabaseSettings(memory_limit="256MB"),
    )
    with database.connection() as connection:
        connection.execute(
            "INSERT INTO gtfs_stops VALUES ('stops.txt', 1, '{}', 's1', NULL, 'Centro', "
            "NULL, NULL, 40.0, -3.0, NULL, NULL, 0, NULL, NULL, NULL, NULL, NULL, NULL)"
        )
    return database


def test_editor_round_trip_recovery_undo_redo_and_discard_preserve_original(tmp_path: Path) -> None:
    database = _database(tmp_path)
    command = EditorCommand(
        EditorCommandKind.MOVE_STOP,
        ("gtfs_stops", "s1"),
        {
            "source_filename": "stops.txt",
            "source_row": 1,
            "raw_values": "{}",
            "stop_id": "s1",
            "stop_code": None,
            "stop_name": "Centro",
            "tts_stop_name": None,
            "stop_desc": None,
            "stop_lat": 40.0,
            "stop_lon": -3.0,
            "zone_id": None,
            "stop_url": None,
            "location_type": 0,
            "parent_station": None,
            "stop_timezone": None,
            "wheelchair_boarding": None,
            "level_id": None,
            "platform_code": None,
            "stop_access": None,
        },
        {
            "source_filename": "stops.txt",
            "source_row": 1,
            "raw_values": "{}",
            "stop_id": "s1",
            "stop_code": None,
            "stop_name": "Centro",
            "tts_stop_name": None,
            "stop_desc": None,
            "stop_lat": 41.0,
            "stop_lon": -3.0,
            "zone_id": None,
            "stop_url": None,
            "location_type": 0,
            "parent_station": None,
            "stop_timezone": None,
            "wheelchair_boarding": None,
            "level_id": None,
            "platform_code": None,
            "stop_access": None,
        },
    )
    with DuckDbUnitOfWork(database) as unit_of_work:
        session = EditorSession.open(unit_of_work)
        session.apply(command)
        assert session.working_copy.dirty
    with DuckDbUnitOfWork(database) as unit_of_work:
        session = EditorSession.open(unit_of_work)
        assert session.working_copy.get(("gtfs_stops", "s1"))["stop_lat"] == 41.0
        session.undo()
        session.redo()
        session.discard()
    with database.connection() as connection:
        assert connection.execute(
            "SELECT stop_lat FROM gtfs_stops WHERE stop_id = 's1'"
        ).fetchone() == (40.0,)


def test_save_draft_is_durable_across_a_later_rollback_and_remains_a_draft(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    with DuckDbUnitOfWork(database) as unit_of_work:
        session = EditorSession.open(unit_of_work)
        before = session.working_copy.get(("gtfs_stops", "s1"))
        assert before is not None
        after = dict(before)
        after["stop_lat"] = 41.0
        session.apply(
            EditorCommand(EditorCommandKind.MOVE_STOP, ("gtfs_stops", "s1"), before, after)
        )
        session.save_draft()
        assert session.working_revision_id == "original"
        unit_of_work.rollback()

    with DuckDbUnitOfWork(database) as unit_of_work:
        recovered = EditorSession.open(unit_of_work)
        assert recovered.working_copy.get(("gtfs_stops", "s1"))["stop_lat"] == 41.0
        assert recovered.working_revision_id == "original"
        assert recovered.data_draft_dirty
        assert not recovered.workspace_dirty
    with database.connection() as connection:
        query = "SELECT stop_lat FROM gtfs_stops WHERE stop_id = 's1'"
        assert connection.execute(query).fetchone() == (40.0,)


def _full_database(tmp_path: Path) -> ProjectDatabase:
    database = ProjectDatabase(
        tmp_path / "full.duckdb",
        tmp_path / "temp",
        settings=DatabaseSettings(memory_limit="256MB"),
    )
    with database.connection() as connection:
        connection.execute(
            "INSERT INTO gtfs_agency (source_filename, source_row, raw_values, agency_id, "
            "agency_name, agency_timezone) VALUES ('agency.txt', 1, '{}', 'A1', 'Operador', "
            "'Europe/Madrid')"
        )
        connection.executemany(
            "INSERT INTO gtfs_stops (source_filename, source_row, raw_values, stop_id, "
            "stop_name, stop_lat, stop_lon) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("stops.txt", 1, "{}", "S1", "Centro", 40.0, -3.0),
                ("stops.txt", 2, "{}", "S2", "Norte", 40.1, -3.1),
            ],
        )
        connection.execute(
            "INSERT INTO gtfs_routes (source_filename, source_row, raw_values, route_id, "
            "agency_id, route_short_name, route_type) VALUES ('routes.txt', 1, '{}', 'R1', "
            "'A1', '1', 3)"
        )
        connection.execute(
            "INSERT INTO gtfs_trips (source_filename, source_row, raw_values, route_id, "
            "service_id, trip_id, shape_id) VALUES ('trips.txt', 1, '{}', 'R1', 'W1', 'T1', 'SH1')"
        )
        connection.executemany(
            "INSERT INTO gtfs_stop_times (source_filename, source_row, raw_values, trip_id, "
            "arrival_time_lexeme, arrival_service_seconds, departure_time_lexeme, "
            "departure_service_seconds, stop_id, stop_sequence) VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "stop_times.txt",
                    1,
                    "{}",
                    "T1",
                    "24:00:00",
                    86400,
                    "24:00:00",
                    86400,
                    "S1",
                    1,
                ),
                (
                    "stop_times.txt",
                    2,
                    "{}",
                    "T1",
                    "25:00:00",
                    90000,
                    "25:01:00",
                    90060,
                    "S2",
                    2,
                ),
            ],
        )
        connection.execute(
            "INSERT INTO gtfs_calendar (source_filename, source_row, raw_values, service_id, "
            "monday, start_date, end_date) VALUES ('calendar.txt', 1, '{}', 'W1', 1, "
            "DATE '2026-01-01', DATE '2026-12-31')"
        )
        connection.execute(
            "INSERT INTO gtfs_calendar_dates (source_filename, source_row, raw_values, "
            "service_id, date, exception_type) VALUES ('calendar_dates.txt', 1, '{}', 'W1', "
            "DATE '2026-01-06', 2)"
        )
        connection.execute(
            "INSERT INTO gtfs_shapes (source_filename, source_row, raw_values, shape_id, "
            "shape_pt_lat, shape_pt_lon, shape_pt_sequence) VALUES ('shapes.txt', 1, '{}', "
            "'SH1', 40.0, -3.0, 1)"
        )
        connection.execute(
            "INSERT INTO gtfs_frequencies (source_filename, source_row, raw_values, trip_id, "
            "start_time_service_seconds, end_time_service_seconds, headway_secs) VALUES "
            "('frequencies.txt', 1, '{}', 'T1', 28800, 32400, 600)"
        )
        connection.execute(
            "INSERT INTO gtfs_transfers (source_filename, source_row, raw_values, from_stop_id, "
            "to_stop_id, transfer_type) VALUES ('transfers.txt', 1, '{}', 'S1', 'S2', 0)"
        )
        connection.execute(
            "INSERT INTO gtfs_feed_info (source_filename, source_row, raw_values, feed_lang) "
            "VALUES ('feed_info.txt', 1, '{}', 'es')"
        )
        connection.execute(
            "INSERT INTO gtfs_attributions (source_filename, source_row, raw_values, "
            "attribution_id, agency_id, route_id, organization_name) VALUES ('attributions.txt', "
            "1, '{}', 'AT1', 'A1', 'R1', 'Autoridad')"
        )
    return database


def test_editor_integrates_schedule_geometry_operators_and_dependencies(tmp_path: Path) -> None:
    database = _full_database(tmp_path)
    with DuckDbUnitOfWork(database) as unit_of_work:
        session = EditorSession.open(unit_of_work)
        original = session.working_copy.original
        assert {table for table, _ in original} >= {
            "gtfs_agency",
            "gtfs_routes",
            "gtfs_trips",
            "gtfs_stop_times",
            "gtfs_calendar",
            "gtfs_calendar_dates",
            "gtfs_shapes",
            "gtfs_attributions",
        }

        edits = (
            (
                EditorCommandKind.UPDATE_ROUTE,
                ("gtfs_routes", "R1"),
                "route_long_name",
                "Circular",
            ),
            (EditorCommandKind.UPDATE_TRIP, ("gtfs_trips", "T1"), "trip_headsign", "Centro"),
            (
                EditorCommandKind.UPDATE_STOP_TIME,
                ("gtfs_stop_times", "1"),
                "departure_time_lexeme",
                "25:02:00",
            ),
            (EditorCommandKind.UPDATE_SERVICE, ("gtfs_calendar", "W1"), "monday", 0),
            (EditorCommandKind.MOVE_SHAPE_POINT, ("gtfs_shapes", "1"), "shape_pt_lat", 40.2),
            (
                EditorCommandKind.UPDATE_AGENCY,
                ("gtfs_agency", "A1"),
                "agency_name",
                "Operador nuevo",
            ),
            (
                EditorCommandKind.UPDATE_ATTRIBUTION,
                ("gtfs_attributions", "AT1"),
                "organization_name",
                "Autoridad nueva",
            ),
        )
        for kind, entity_key, field, value in edits:
            before = session.working_copy.get(entity_key)
            assert before is not None
            after = dict(before)
            after[field] = value
            command = EditorCommand(kind, entity_key, before, after)
            session.apply(command, impact=session.preview_impact(command))

        assert (
            session.working_copy.get(("gtfs_stop_times", "1"))["departure_time_lexeme"]
            == "25:02:00"
        )
        assert (
            session.working_copy.get(("gtfs_stop_times", "2"))["arrival_time_lexeme"] == "25:00:00"
        )
        assert session.working_copy.get(("gtfs_shapes", "1"))["shape_pt_lat"] == 40.2
        assert session.working_copy.dirty

    with DuckDbUnitOfWork(database) as unit_of_work:
        session = EditorSession.open(unit_of_work)
        assert session.working_copy.get(("gtfs_calendar", "W1"))["monday"] == 0
        assert session.working_copy.get(("gtfs_calendar_dates", "1"))["date"].year == 2026
        session.discard()
        assert session.working_copy.entities == session.working_copy.original

    with database.connection() as connection:
        assert connection.execute("SELECT route_long_name FROM gtfs_routes").fetchone() == (None,)
        assert connection.execute("SELECT monday FROM gtfs_calendar").fetchone() == (1,)
        assert connection.execute("SELECT shape_pt_lat FROM gtfs_shapes").fetchone() == (40.0,)
        assert connection.execute("SELECT count(*) FROM editor_deltas").fetchone() == (0,)


def test_delete_stop_requires_impact_and_explicit_dependency_resolution(tmp_path: Path) -> None:
    database = _full_database(tmp_path)
    with DuckDbUnitOfWork(database) as unit_of_work:
        session = EditorSession.open(unit_of_work)
        before = session.working_copy.get(("gtfs_stops", "S1"))
        assert before is not None
        command = EditorCommand(EditorCommandKind.DELETE_STOP, ("gtfs_stops", "S1"), before, None)
        impact = session.preview_impact(command)

        assert ("gtfs_stop_times", "1") in impact.affected_entities
        assert ("gtfs_trips", "T1") in impact.affected_entities
        assert ("gtfs_routes", "R1") in impact.affected_entities
        assert ("gtfs_calendar", "W1") in impact.affected_entities
        assert ("gtfs_shapes", "1") in impact.affected_entities
        assert ("gtfs_stop_times", "1") in impact.required_entity_changes

        with pytest.raises(ImpactResolutionRequired):
            session.apply(command, impact=impact)

        prepared = session.prepare_command(command, impact, resolution="delete_stop_times")
        session.apply(prepared)
        assert session.working_copy.get(("gtfs_stops", "S1")) is None
        assert session.working_copy.get(("gtfs_stop_times", "1")) is None
        assert session.working_copy.get(("gtfs_trips", "T1")) is not None

        session.undo()
        assert session.working_copy.get(("gtfs_stops", "S1")) is not None
        assert session.working_copy.get(("gtfs_stop_times", "1")) is not None
        session.redo()
        assert session.working_copy.get(("gtfs_stops", "S1")) is None


def test_delete_route_requires_explicit_trip_and_dependency_operation(tmp_path: Path) -> None:
    database = _full_database(tmp_path)
    with DuckDbUnitOfWork(database) as unit_of_work:
        session = EditorSession.open(unit_of_work)
        before = session.working_copy.get(("gtfs_routes", "R1"))
        assert before is not None
        command = EditorCommand(EditorCommandKind.DELETE_ROUTE, ("gtfs_routes", "R1"), before, None)
        impact = session.preview_impact(command)

        assert ("gtfs_trips", "T1") in impact.required_entity_changes
        assert ("gtfs_stop_times", "1") in impact.affected_entities
        with pytest.raises(ImpactResolutionRequired):
            session.apply(command, impact=impact)

        prepared = session.prepare_command(
            command, impact, resolution="delete_trips_and_stop_times"
        )
        session.apply(prepared)
        assert session.working_copy.get(("gtfs_routes", "R1")) is None
        assert session.working_copy.get(("gtfs_trips", "T1")) is None
        assert session.working_copy.get(("gtfs_stop_times", "1")) is None
        assert session.working_copy.get(("gtfs_stops", "S1")) is not None
        assert session.working_copy.get(("gtfs_shapes", "1")) is not None


def test_route_workspace_state_is_explicit_and_recovered_with_draft(tmp_path: Path) -> None:
    database = _full_database(tmp_path)
    with DuckDbUnitOfWork(database) as unit_of_work:
        session = EditorSession.open(unit_of_work)
        session.set_route_workspace_state(
            RouteWorkspaceState("R1", visible=True, active=True, editable=True)
        )
        assert session.can_edit_route("R1")
        session.set_route_workspace_state(
            RouteWorkspaceState("R1", visible=True, active=True, editable=True, locked=True)
        )
        assert not session.can_edit_route("R1")

    with DuckDbUnitOfWork(database) as unit_of_work:
        session = EditorSession.open(unit_of_work)
        assert session.working_copy.route_state("R1").locked
        assert not session.can_edit_route("R1")
        session.discard()

    with database.connection() as connection:
        assert connection.execute("SELECT count(*) FROM editor_route_state").fetchone() == (1,)


def test_route_workspace_state_uses_specialized_upsert_without_full_persist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = _full_database(tmp_path)

    def fail_full_persist(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("El estado visual no debe usar persist() integral.")

    monkeypatch.setattr(DuckDbEditorRepository, "persist", fail_full_persist)
    with DuckDbUnitOfWork(database) as unit_of_work:
        session = EditorSession.open(unit_of_work)
        session.set_route_workspace_state(
            RouteWorkspaceState("R1", visible=True, active=True, editable=True)
        )

        assert len(session.working_copy.entity_index.by_table["gtfs_routes"]) == 1
        assert unit_of_work.connection.execute(
            "SELECT visible, active, editable FROM editor_route_state WHERE route_id = 'R1'"
        ).fetchone() == (True, True, True)
        assert unit_of_work.connection.execute("SELECT count(*) FROM editor_deltas").fetchone() == (
            0,
        )
        assert unit_of_work.connection.execute(
            "SELECT count(*) FROM editor_history"
        ).fetchone() == (0,)


def test_route_id_change_requires_explicit_reference_updates(tmp_path: Path) -> None:
    database = _full_database(tmp_path)
    with DuckDbUnitOfWork(database) as unit_of_work:
        session = EditorSession.open(unit_of_work)
        session.set_route_workspace_state(RouteWorkspaceState("R1", active=True, editable=True))
        before = session.working_copy.get(("gtfs_routes", "R1"))
        assert before is not None
        after = dict(before)
        after["route_id"] = "R2"
        command = EditorCommand(
            EditorCommandKind.UPDATE_ROUTE, ("gtfs_routes", "R1"), before, after
        )
        impact = session.preview_impact(command)

        assert "update_route_references" in impact.resolution_options
        with pytest.raises(ImpactResolutionRequired):
            session.apply(command, impact=impact)

        prepared = session.prepare_command(
            command,
            impact,
            resolution="update_route_references",
            replacement_id="R2",
        )
        session.apply(prepared)
        assert session.working_copy.get(("gtfs_routes", "R1"))["route_id"] == "R2"
        assert session.working_copy.get(("gtfs_trips", "T1"))["route_id"] == "R2"
        assert session.working_copy.get(("gtfs_attributions", "AT1"))["route_id"] == "R2"
        assert session.can_edit_route("R2")
        assert not session.can_edit_route("R1")
        session.undo()
        assert session.can_edit_route("R1")
        session.redo()
        assert session.can_edit_route("R2")


def test_revision_builder_closes_dependencies_and_preserves_gtfs_lexemes(
    tmp_path: Path,
) -> None:
    database = _full_database(tmp_path)
    specification = load_schedule_spec(_SPEC_PATH)
    with DuckDbUnitOfWork(database) as unit_of_work:
        session = EditorSession.open(unit_of_work)
        preview = WorkingCopyGtfsBuilder(session.working_copy, specification).preview(
            revision_id="revision-1"
        )

    assert preview.subset.route_ids == frozenset({"R1"})
    assert {table.filename for table in preview.tables} >= {
        "agency.txt",
        "routes.txt",
        "trips.txt",
        "stop_times.txt",
        "stops.txt",
        "calendar.txt",
        "calendar_dates.txt",
        "shapes.txt",
        "frequencies.txt",
        "transfers.txt",
        "attributions.txt",
    }
    stop_times = next(table for table in preview.tables if table.filename == "stop_times.txt")
    positions = {field: index for index, field in enumerate(stop_times.headers)}
    assert stop_times.rows[0][positions["arrival_time"]] == "24:00:00"
    assert stop_times.rows[1][positions["arrival_time"]] == "25:00:00"
    calendar = next(table for table in preview.tables if table.filename == "calendar.txt")
    calendar_positions = {field: index for index, field in enumerate(calendar.headers)}
    assert calendar.rows[0][calendar_positions["start_date"]] == "20260101"
    assert not preview.omitted_entities


def test_confirm_revision_promotes_working_copy_and_keeps_original_immutable(
    tmp_path: Path,
) -> None:
    database = _full_database(tmp_path)
    with DuckDbUnitOfWork(database) as unit_of_work:
        session = EditorSession.open(unit_of_work)
        before = session.working_copy.get(("gtfs_routes", "R1"))
        assert before is not None
        after = dict(before)
        after["route_long_name"] = "Revisión confirmada"
        command = EditorCommand(
            EditorCommandKind.UPDATE_ROUTE, ("gtfs_routes", "R1"), before, after
        )
        session.apply(command, impact=session.preview_impact(command))
        assert session.dirty

        revision_id = session.confirm_revision("revision-1")
        assert revision_id == "revision-1"
        assert session.working_revision_id == "revision-1"
        assert not session.dirty
        assert session.working_copy.original[("gtfs_routes", "R1")]["route_long_name"] is None

    with DuckDbUnitOfWork(database) as unit_of_work:
        session = EditorSession.open(unit_of_work)
        assert session.working_revision_id == "revision-1"
        assert session.working_copy.get(("gtfs_routes", "R1"))["route_long_name"] == (
            "Revisión confirmada"
        )
        assert session.working_copy.original[("gtfs_routes", "R1")]["route_long_name"] is None
        assert session.revisions()[0][0] == "revision-1"

        current = session.working_copy.get(("gtfs_routes", "R1"))
        assert current is not None
        updated = dict(current)
        updated["route_long_name"] = "Borrador posterior"
        session.apply(
            EditorCommand(EditorCommandKind.UPDATE_ROUTE, ("gtfs_routes", "R1"), current, updated),
            impact=session.preview_impact(
                EditorCommand(
                    EditorCommandKind.UPDATE_ROUTE, ("gtfs_routes", "R1"), current, updated
                )
            ),
        )
        assert session.dirty
        session.discard()
        assert session.working_copy.get(("gtfs_routes", "R1"))["route_long_name"] == (
            "Revisión confirmada"
        )

    with database.connection() as connection:
        assert connection.execute(
            "SELECT route_long_name FROM gtfs_routes WHERE route_id = 'R1'"
        ).fetchone() == (None,)
        assert connection.execute("SELECT count(*) FROM editor_deltas").fetchone() == (0,)
        revisions = {
            row[0]
            for row in connection.execute("SELECT revision_id FROM editor_revisions").fetchall()
        }
        assert revisions == {"revision-1"}
        assert connection.execute(
            "SELECT parent_revision_id, delta_reference, delta_count "
            "FROM editor_revisions WHERE revision_id = 'revision-1'"
        ).fetchone() == ("original", "revision-1", 1)
        assert connection.execute(
            "SELECT table_name, entity_id, deleted FROM editor_revision_deltas "
            "WHERE revision_id = 'revision-1'"
        ).fetchall() == [("gtfs_routes", "R1", False)]
        revision_columns = {
            row[0]
            for row in connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'editor_revisions'"
            ).fetchall()
        }
        assert "entities_json" not in revision_columns


def test_confirm_revision_blocks_integrity_errors(tmp_path: Path) -> None:
    database = _full_database(tmp_path)
    with DuckDbUnitOfWork(database) as unit_of_work:
        session = EditorSession.open(unit_of_work)
        before = session.working_copy.get(("gtfs_stops", "S1"))
        assert before is not None
        after = dict(before)
        after["stop_lat"] = 91.0
        session.apply(
            EditorCommand(EditorCommandKind.MOVE_STOP, ("gtfs_stops", "S1"), before, after)
        )
        with pytest.raises(RevisionConfirmationError):
            session.confirm_revision("invalid-revision")
        assert session.dirty


def test_save_concentrates_validation_on_dirty_publication(tmp_path: Path) -> None:
    database = _full_database(tmp_path)
    with DuckDbUnitOfWork(database) as unit_of_work:
        session = EditorSession.open(unit_of_work)
        validations: list[object] = []
        original_validate = session.validate

        def observe_validation(*args: object, **kwargs: object) -> object:
            validations.append((args, kwargs))
            return original_validate()

        session.validate = observe_validation  # type: ignore[method-assign]
        assert session.save() is None
        assert validations == []

        before = session.working_copy.get(("gtfs_routes", "R1"))
        assert before is not None
        after = dict(before)
        after["route_long_name"] = "Pendiente"
        command = EditorCommand(
            EditorCommandKind.UPDATE_ROUTE, ("gtfs_routes", "R1"), before, after
        )
        session.apply(command, impact=session.preview_impact(command))
        session.undo()
        session.redo()
        assert validations == []

        revision_id = session.save("save-1")
        assert revision_id == "save-1"
        assert len(validations) == 1
        assert not session.data_draft_dirty


def test_revision_chain_reconstructs_original_plus_small_immutable_deltas(
    tmp_path: Path,
) -> None:
    database = _full_database(tmp_path)
    with DuckDbUnitOfWork(database) as unit_of_work:
        session = EditorSession.open(unit_of_work)
        first_before = session.working_copy.get(("gtfs_routes", "R1"))
        assert first_before is not None
        first_after = dict(first_before)
        first_after["route_long_name"] = "Primera revisión"
        first_command = EditorCommand(
            EditorCommandKind.UPDATE_ROUTE,
            ("gtfs_routes", "R1"),
            first_before,
            first_after,
        )
        session.apply(first_command, impact=session.preview_impact(first_command))
        session.confirm_revision("revision-1")

        second_before = session.working_copy.get(("gtfs_routes", "R1"))
        assert second_before is not None
        second_after = dict(second_before)
        second_after["route_long_name"] = "Segunda revisión"
        second_command = EditorCommand(
            EditorCommandKind.UPDATE_ROUTE,
            ("gtfs_routes", "R1"),
            second_before,
            second_after,
        )
        session.apply(second_command, impact=session.preview_impact(second_command))
        session.confirm_revision("revision-2")

    with DuckDbUnitOfWork(database) as unit_of_work:
        session = EditorSession.open(unit_of_work)
        assert session.working_revision_id == "revision-2"
        assert session.working_copy.get(("gtfs_routes", "R1"))["route_long_name"] == (
            "Segunda revisión"
        )

    with database.connection() as connection:
        assert connection.execute(
            "SELECT revision_id, parent_revision_id, delta_count "
            "FROM editor_revisions ORDER BY revision_id"
        ).fetchall() == [("revision-1", "original", 1), ("revision-2", "revision-1", 1)]
        assert connection.execute(
            "SELECT revision_id, table_name, entity_id, deleted "
            "FROM editor_revision_deltas ORDER BY revision_id"
        ).fetchall() == [
            ("revision-1", "gtfs_routes", "R1", False),
            ("revision-2", "gtfs_routes", "R1", False),
        ]


def test_legacy_stop_delta_schema_migrates_without_touching_gtfs_original(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with DuckDbUnitOfWork(database) as unit_of_work:
        session = EditorSession.open(unit_of_work)
        before = session.working_copy.get(("gtfs_stops", "s1"))
        assert before is not None
        after = dict(before)
        after["stop_lat"] = 41.0
        session.apply(
            EditorCommand(EditorCommandKind.MOVE_STOP, ("gtfs_stops", "s1"), before, after)
        )

    with database.connection() as connection:
        payload = connection.execute(
            "SELECT payload, deleted FROM editor_deltas WHERE table_name = 'gtfs_stops'"
        ).fetchone()
        assert payload is not None
        connection.execute("DROP TABLE editor_deltas")
        connection.execute(
            "CREATE TABLE editor_deltas ("
            "entity_id VARCHAR PRIMARY KEY, payload JSON, deleted BOOLEAN)"
        )
        connection.execute("INSERT INTO editor_deltas VALUES (?, ?, ?)", ["s1", *payload])

    with DuckDbUnitOfWork(database) as unit_of_work:
        session = EditorSession.open(unit_of_work)
        assert session.working_copy.get(("gtfs_stops", "s1"))["stop_lat"] == 41.0

    with database.connection() as connection:
        assert connection.execute(
            "SELECT stop_lat FROM gtfs_stops WHERE stop_id = 's1'"
        ).fetchone() == (40.0,)


@pytest.mark.parametrize("operation", ["apply", "apply_batch", "undo", "redo"])
def test_data_operations_invalidate_validation(tmp_path: Path, operation: str, monkeypatch) -> None:
    with DuckDbUnitOfWork(_database(tmp_path)) as uow:
        session = EditorSession.open(uow)
        before = session.working_copy.get(("gtfs_stops", "s1"))
        after = dict(before, stop_lat=41.0)
        command = EditorCommand(EditorCommandKind.MOVE_STOP, ("gtfs_stops", "s1"), before, after)
        if operation in {"undo", "redo"}:
            session.apply(command)
        if operation == "redo":
            session.undo()
        session.validate()
        assert session.validation_current

        def unexpected_validation(*args):
            pytest.fail("Editing must not run full validation")

        with monkeypatch.context() as patch:
            patch.setattr(
                "gtfs_explorer.application.editor_session.WorkingCopyValidator.validate",
                unexpected_validation,
            )
            if operation == "apply_batch":
                session.apply_batch((command,))
            elif operation == "apply":
                session.apply(command)
            else:
                getattr(session, operation)()
        assert not session.validation_current
        assert session.validation_issues == ()
        assert session.validate() == session.validation_issues
        assert session.validation_current
