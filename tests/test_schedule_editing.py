"""Pruebas focales de matriz de horarios y reordenación explícita."""

from typing import Any

from gtfs_explorer.application.schedule_editing import ScheduleEditor
from gtfs_explorer.domain.changesets import WorkingCopy


class _Session:
    def __init__(self, working_copy: WorkingCopy) -> None:
        self.working_copy = working_copy

    def preview_impact(self, command: Any) -> Any:
        return self.working_copy.analyze_impact(command)

    def apply(self, command: Any, *, impact: Any) -> Any:
        return self.working_copy.apply_with_impact(command, impact)


def _editor() -> tuple[WorkingCopy, ScheduleEditor]:
    working_copy = WorkingCopy(
        {
            ("gtfs_trips", "T1"): {
                "trip_id": "T1",
                "route_id": "R1",
                "service_id": "W1",
                "shape_id": "SH1",
            },
            ("gtfs_stop_times", "1"): {
                "trip_id": "T1",
                "stop_id": "S1",
                "stop_sequence": 10,
                "arrival_time_lexeme": "24:00:00",
                "departure_time_lexeme": "24:01:00",
                "arrival_service_seconds": 86400,
                "departure_service_seconds": 86460,
            },
            ("gtfs_stop_times", "2"): {
                "trip_id": "T1",
                "stop_id": "S2",
                "stop_sequence": 20,
                "arrival_time_lexeme": "25:00:00",
                "departure_time_lexeme": "25:01:00",
                "arrival_service_seconds": 90000,
                "departure_service_seconds": 90060,
            },
        }
    )
    return working_copy, ScheduleEditor(_Session(working_copy))  # type: ignore[arg-type]


def test_schedule_matrix_preserves_extended_hours_and_updates_only_explicit_cell() -> None:
    working_copy, editor = _editor()
    rows = editor.matrix("T1")
    assert [row.arrival_time for row in rows] == ["24:00:00", "25:00:00"]

    proposal = editor.propose_time_update(
        ("gtfs_stop_times", "1"), "departure_time_lexeme", "25:02:00"
    )
    editor.apply(proposal)
    payload = working_copy.get(("gtfs_stop_times", "1"))
    assert payload["departure_service_seconds"] == 90120
    assert payload["arrival_time_lexeme"] == "24:00:00"


def test_schedule_reorder_is_a_compound_command_without_time_recalculation() -> None:
    working_copy, editor = _editor()
    proposal = editor.propose_reorder("T1", ("gtfs_stop_times", "2"), 0)
    editor.apply(proposal)

    first = working_copy.get(("gtfs_stop_times", "2"))
    second = working_copy.get(("gtfs_stop_times", "1"))
    assert first["stop_sequence"] == 10
    assert second["stop_sequence"] == 20
    assert first["arrival_time_lexeme"] == "25:00:00"
    assert second["arrival_time_lexeme"] == "24:00:00"
    working_copy.undo()
    assert working_copy.get(("gtfs_stop_times", "1"))["stop_sequence"] == 10
