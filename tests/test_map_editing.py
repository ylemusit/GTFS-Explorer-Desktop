"""Pruebas focales del adaptador de gestos de mapa a ChangeSets."""

from typing import Any

import pytest

from gtfs_explorer.application.map_editing import MapEditController, MapEditError, MapEditMode
from gtfs_explorer.domain.changesets import RouteWorkspaceState, WorkingCopy
from gtfs_explorer.presentation.map_bridge import MapEditGesture


class _Session:
    def __init__(self, working_copy: WorkingCopy) -> None:
        self.working_copy = working_copy

    def can_edit_route(self, route_id: str) -> bool:
        return self.working_copy.can_edit_route(route_id)

    def preview_impact(self, command: Any) -> Any:
        return self.working_copy.analyze_impact(command)

    def apply(self, command: Any, *, impact: Any) -> Any:
        return self.working_copy.apply_with_impact(command, impact)


def _copy() -> WorkingCopy:
    return WorkingCopy(
        {
            ("gtfs_routes", "R1"): {"route_id": "R1"},
            ("gtfs_routes", "R2"): {"route_id": "R2"},
            ("gtfs_trips", "T1"): {
                "trip_id": "T1",
                "route_id": "R1",
                "service_id": "W1",
                "shape_id": "SH1",
            },
            ("gtfs_stop_times", "1"): {"trip_id": "T1", "stop_id": "S1"},
            ("gtfs_stops", "S1"): {"stop_id": "S1", "stop_lat": 40.0, "stop_lon": -3.0},
            ("gtfs_shapes", "1"): {
                "shape_id": "SH1",
                "shape_pt_lat": 40.0,
                "shape_pt_lon": -3.0,
                "shape_pt_sequence": 1,
            },
        }
    )


def test_map_gesture_becomes_explicit_reversible_stop_command() -> None:
    working_copy = _copy()
    working_copy.set_route_workspace_state(RouteWorkspaceState("R1", active=True, editable=True))
    controller = MapEditController(_Session(working_copy))  # type: ignore[arg-type]
    proposal = controller.propose(MapEditGesture("drag_end", "stop", "S1", 0, "R1", -3.1, 40.1))

    controller.apply(proposal)
    assert working_copy.get(("gtfs_stops", "S1"))["stop_lon"] == -3.1
    working_copy.undo()
    assert working_copy.get(("gtfs_stops", "S1"))["stop_lon"] == -3.0


def test_proposal_does_not_mutate_working_copy_until_it_is_confirmed() -> None:
    working_copy = _copy()
    working_copy.set_route_workspace_state(RouteWorkspaceState("R1", active=True, editable=True))
    controller = MapEditController(_Session(working_copy))  # type: ignore[arg-type]

    controller.propose(MapEditGesture("drag_end", "stop", "S1", 0, "R1", -3.1, 40.1))

    assert working_copy.get(("gtfs_stops", "S1"))["stop_lon"] == -3.0
    assert working_copy.changeset.active_commands == ()


def test_shared_shape_cannot_be_edited_from_one_route_context() -> None:
    working_copy = _copy()
    working_copy._working[("gtfs_trips", "T2")] = {
        "trip_id": "T2",
        "route_id": "R2",
        "service_id": "W1",
        "shape_id": "SH1",
    }
    working_copy._entity_index = None
    working_copy.set_route_workspace_state(RouteWorkspaceState("R1", active=True, editable=True))
    controller = MapEditController(_Session(working_copy), mode=MapEditMode.EDIT_ROUTE)  # type: ignore[arg-type]

    with pytest.raises(MapEditError, match="única ruta activa"):
        controller.propose(
            MapEditGesture("drag_end", "shape_vertex", "1", 0, "R1", -3.1, 40.1, shape_id="SH1")
        )


def test_map_gesture_requires_single_authorized_route() -> None:
    working_copy = _copy()
    controller = MapEditController(_Session(working_copy))  # type: ignore[arg-type]
    gesture = MapEditGesture("drag_end", "stop", "S1", 0, "R1", -3.1, 40.1)
    with pytest.raises(MapEditError, match="autorizada"):
        controller.propose(gesture)

    working_copy.set_route_workspace_state(RouteWorkspaceState("R1", active=True, editable=True))
    proposal = controller.propose(gesture)
    assert proposal.command.kind.value == "MOVE_STOP"


def test_normal_mode_rejects_every_mutating_map_gesture() -> None:
    working_copy = _copy()
    working_copy.set_route_workspace_state(RouteWorkspaceState("R1", active=True, editable=True))
    controller = MapEditController(_Session(working_copy), mode=MapEditMode.NORMAL)
    gesture = MapEditGesture("drag_end", "stop", "S1", 0, "R1", -3.1, 40.1)
    with pytest.raises(MapEditError, match="NORMAL"):
        controller.propose(gesture)


def test_insert_vertex_with_sequence_gap_changes_one_direct_row_without_renumbering() -> None:
    working_copy = _copy()
    working_copy.set_route_workspace_state(RouteWorkspaceState("R1", active=True, editable=True))
    working_copy._working[("gtfs_shapes", "1")]["shape_pt_sequence"] = 10
    working_copy._working[("gtfs_shapes", "2")] = {
        "shape_id": "SH1",
        "shape_pt_lat": 40.1,
        "shape_pt_lon": -3.1,
        "shape_pt_sequence": 20,
    }
    working_copy._entity_index = None
    controller = MapEditController(_Session(working_copy), mode=MapEditMode.REDRAW_SEGMENT)
    proposal = controller.propose(
        MapEditGesture("add_vertex", "shape_vertex", "SH1", 0, "R1", -3.05, 40.05, 1)
    )
    assert proposal.command.after is not None
    assert proposal.command.after["shape_pt_sequence"] == 15
    assert proposal.command.changes == ()


def test_insert_vertex_without_sequence_gap_requires_explicit_renumbering() -> None:
    working_copy = _copy()
    working_copy.set_route_workspace_state(RouteWorkspaceState("R1", active=True, editable=True))
    working_copy._working[("gtfs_shapes", "2")] = {
        "shape_id": "SH1",
        "shape_pt_lat": 40.1,
        "shape_pt_lon": -3.1,
        "shape_pt_sequence": 2,
    }
    working_copy._entity_index = None
    controller = MapEditController(_Session(working_copy), mode=MapEditMode.REDRAW_SEGMENT)
    with pytest.raises(MapEditError, match="renumerar"):
        controller.propose(
            MapEditGesture("add_vertex", "shape_vertex", "SH1", 0, "R1", -3.05, 40.05, 1)
        )
