"""Pruebas focales de servicios, agencias y atribuciones."""

from typing import Any

from gtfs_explorer.application.operator_editing import OperatorEditor
from gtfs_explorer.application.service_editing import ServiceEditor, parse_service_date
from gtfs_explorer.domain.changesets import WorkingCopy


class _Session:
    def __init__(self, working_copy: WorkingCopy) -> None:
        self.working_copy = working_copy

    def preview_impact(self, command: Any) -> Any:
        return self.working_copy.analyze_impact(command)

    def prepare_command(self, command: Any, impact: Any, **kwargs: Any) -> Any:
        return self.working_copy.prepare_command(command, impact, **kwargs)

    def apply(self, command: Any, *, impact: Any) -> Any:
        return self.working_copy.apply_with_impact(command, impact)


def _session() -> _Session:
    return _Session(
        WorkingCopy(
            {
                ("gtfs_agency", "A1"): {"agency_id": "A1", "agency_name": "Operador"},
                ("gtfs_agency", "A2"): {"agency_id": "A2", "agency_name": "Otro"},
                ("gtfs_routes", "R1"): {"route_id": "R1", "agency_id": "A1"},
                ("gtfs_trips", "T1"): {
                    "trip_id": "T1",
                    "route_id": "R1",
                    "service_id": "W1",
                },
                ("gtfs_calendar", "W1"): {
                    "service_id": "W1",
                    "start_date": parse_service_date("20260101"),
                    "end_date": parse_service_date("20261231"),
                },
                ("gtfs_calendar_dates", "1"): {
                    "service_id": "W1",
                    "date": parse_service_date("20260106"),
                    "exception_type": 2,
                },
                ("gtfs_attributions", "AT1"): {
                    "attribution_id": "AT1",
                    "agency_id": "A1",
                },
            }
        )
    )


def test_service_editor_exposes_calendar_exceptions_and_requires_delete_resolution() -> None:
    session = _session()
    editor = ServiceEditor(session)  # type: ignore[arg-type]
    summary = editor.services()[0]
    assert summary.service_id == "W1"
    assert summary.calendar_date_keys == (("gtfs_calendar_dates", "1"),)
    proposal = editor.propose_delete("W1")
    assert "delete_trips_and_calendar" in proposal.impact.resolution_options


def test_operator_editor_assigns_route_with_explicit_impact() -> None:
    session = _session()
    editor = OperatorEditor(session)  # type: ignore[arg-type]
    proposal = editor.propose_route_assignment(("gtfs_routes", "R1"), "A2")
    editor.apply(proposal)
    assert session.working_copy.get(("gtfs_routes", "R1"))["agency_id"] == "A2"
    assert editor.operators()[1].route_ids == ("R1",)
