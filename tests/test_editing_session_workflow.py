from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication

from gtfs_explorer.application.editor_session import EditorSession, EditSession
from gtfs_explorer.application.queries.map_layers import map_layers_for_working_copy_routes
from gtfs_explorer.domain.changesets import (
    EditorCommand,
    EditorCommandKind,
    RouteWorkspaceState,
    WorkingCopy,
)
from gtfs_explorer.infrastructure.duckdb.repositories.editor import DuckDbEditorRepository
from gtfs_explorer.presentation.desktop.editor.widget import RouteEditSelectionDialog


class _UnitOfWork:
    connection = object()


def _working_copy() -> WorkingCopy:
    entities: dict[tuple[str, str], dict[str, Any]] = {}
    for route_number in range(1, 5):
        route_id = f"R{route_number}"
        entities[("gtfs_routes", route_id)] = {
            "route_id": route_id,
            "route_short_name": str(route_number),
            "route_long_name": f"Ruta {route_number}",
            "route_sort_order": route_number,
        }
        entities[("gtfs_trips", f"T{route_number}")] = {
            "trip_id": f"T{route_number}",
            "route_id": route_id,
            "shape_id": f"SH{route_number}",
            "service_id": "WEEK",
        }
        for sequence, (latitude, longitude) in enumerate(((40.0, -3.0), (40.1, -3.1)), start=1):
            entities[("gtfs_shapes", f"SH{route_number}-{sequence}")] = {
                "shape_id": f"SH{route_number}",
                "shape_pt_lat": latitude,
                "shape_pt_lon": longitude,
                "shape_pt_sequence": sequence,
            }
    return WorkingCopy(entities)


def test_edit_session_enforces_one_to_three_routes_and_restores_temporary_roles(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        DuckDbEditorRepository,
        "__init__",
        lambda self, connection: setattr(self, "_connection", connection),
    )
    monkeypatch.setattr(
        DuckDbEditorRepository,
        "persist_route_workspace_states",
        lambda _repository, _states: None,
    )
    working_copy = _working_copy()
    session = EditorSession(_UnitOfWork(), working_copy)  # type: ignore[arg-type]

    assert EditSession.create(("R1", "R2", "R3"), active_route_id="R2").ordinal("R3") == 3
    with pytest.raises(ValueError, match="entre 1 y 3"):
        EditSession.create(("R1", "R2", "R3", "R4"))

    editing = session.start_editing(("R1", "R2", "R3"), active_route_id="R2")
    assert editing.loaded_route_ids == ("R1", "R2", "R3")
    assert editing.active_route_id == "R2"
    assert session.working_copy.route_state("R2").can_edit
    assert session.working_copy.route_state("R1").locked
    assert not session.editing_dirty
    with pytest.raises(ValueError, match="Ya hay una sesión"):
        session.start_editing(("R1",))

    generation = working_copy.geometric_generation
    switched = session.activate_editing_route("R3")
    assert switched.active_route_id == "R3"
    assert session.working_copy.route_state("R3").can_edit
    assert session.working_copy.route_state("R2").locked
    assert working_copy.geometric_generation == generation

    session.finish_editing()
    assert session.editing_session is None
    assert not working_copy.dirty
    assert all(
        not state.locked and not state.active for state in working_copy.route_states.values()
    )


def test_active_route_switch_reuses_geometry_and_only_changes_visual_width() -> None:
    working_copy = _working_copy()
    working_copy.set_route_workspace_state(
        RouteWorkspaceState("R1", visible=True, active=True, editable=True)
    )
    working_copy.set_route_workspace_state(RouteWorkspaceState("R2", visible=True, locked=True))
    before = map_layers_for_working_copy_routes(working_copy, {"R1", "R2"})
    before_features = {
        feature["properties"]["route_id"]: feature for feature in before.shapes["features"]
    }
    generation = working_copy.geometric_generation

    working_copy.set_route_workspace_state(
        replace(working_copy.route_state("R1"), active=False, editable=False, locked=True)
    )
    working_copy.set_route_workspace_state(
        replace(working_copy.route_state("R2"), active=True, editable=True, locked=False)
    )
    after = map_layers_for_working_copy_routes(working_copy, {"R1", "R2"})
    after_features = {
        feature["properties"]["route_id"]: feature for feature in after.shapes["features"]
    }

    assert working_copy.geometric_generation == generation
    assert before_features["R1"]["geometry"] == after_features["R1"]["geometry"]
    assert before_features["R2"]["geometry"] == after_features["R2"]["geometry"]
    assert (
        before_features["R1"]["properties"]["line_width"]
        > before_features["R2"]["properties"]["line_width"]
    )
    assert (
        after_features["R2"]["properties"]["line_width"]
        > after_features["R1"]["properties"]["line_width"]
    )


def test_editor_session_history_is_shared_by_undo_and_redo(monkeypatch) -> None:
    monkeypatch.setattr(
        DuckDbEditorRepository,
        "__init__",
        lambda self, connection: setattr(self, "_connection", connection),
    )
    monkeypatch.setattr(DuckDbEditorRepository, "persist", lambda _repository, _working_copy: None)
    working_copy = _working_copy()
    session = EditorSession(_UnitOfWork(), working_copy)  # type: ignore[arg-type]
    key = ("gtfs_routes", "R1")
    before = working_copy.get(key)
    assert before is not None
    after = {**before, "route_long_name": "Ruta modificada"}

    command = EditorCommand(EditorCommandKind.UPDATE_ROUTE, key, before, after)
    session.apply(command, impact=session.preview_impact(command))
    assert working_copy.get(key)["route_long_name"] == "Ruta modificada"
    assert working_copy.changeset.undo_available
    session.undo()
    assert working_copy.get(key)["route_long_name"] == before.get("route_long_name")
    assert working_copy.changeset.redo_available
    session.redo()
    assert working_copy.get(key)["route_long_name"] == "Ruta modificada"


def test_route_selection_dialog_exposes_active_route_and_caps_context(
    application: QApplication,
) -> None:
    dialog = RouteEditSelectionDialog(
        {route_id: f"Ruta {route_id}" for route_id in ("R1", "R2", "R3", "R4")}
    )
    dialog.set_selected_route_ids(("R1", "R2", "R3", "R4"))
    dialog.set_active_route_id("R2")

    assert dialog.selected_route_ids == ("R1", "R2", "R3")
    assert dialog.active_route_id == "R2"
    dialog.deleteLater()
    application.processEvents()
