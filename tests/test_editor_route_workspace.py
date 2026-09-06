from __future__ import annotations

from typing import Any

from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QMessageBox, QWidget

from gtfs_explorer.application.queries.map_layers import map_layers_for_working_copy_routes
from gtfs_explorer.domain.changesets import RouteWorkspaceState, WorkingCopy
from gtfs_explorer.presentation.desktop.editor.widget import EditorWidget, _MapRebuildSignals


def _working_copy(route_count: int = 4) -> WorkingCopy:
    entities: dict[tuple[str, str], dict[str, Any]] = {
        ("gtfs_agency", "A1"): {
            "agency_id": "A1",
            "agency_name": "Operador local",
        },
    }
    for index in range(1, route_count + 1):
        route_id = f"R{index}"
        trip_id = f"T{index}"
        shape_id = f"SH{index}"
        entities[("gtfs_routes", route_id)] = {
            "route_id": route_id,
            "agency_id": "A1",
            "route_short_name": str(index),
            "route_long_name": f"Ruta {index}",
            "route_color": f"00{index:02d}0{index}",
            "route_sort_order": index,
        }
        entities[("gtfs_trips", trip_id)] = {
            "trip_id": trip_id,
            "route_id": route_id,
            "service_id": "WEEK",
            "shape_id": shape_id,
        }
        for position in (1, 2):
            stop_id = f"S{index}-{position}"
            entities[("gtfs_stops", stop_id)] = {
                "stop_id": stop_id,
                "stop_name": f"Parada {stop_id}",
                "stop_lat": 40.0 + index / 100 + position / 1000,
                "stop_lon": -3.0 - index / 100 - position / 1000,
            }
            entities[("gtfs_stop_times", f"{trip_id}-{position}")] = {
                "trip_id": trip_id,
                "stop_id": stop_id,
                "stop_sequence": position,
                "arrival_time_lexeme": f"08:0{position}:00",
                "departure_time_lexeme": f"08:0{position}:30",
            }
        entities[("gtfs_shapes", f"{shape_id}-1")] = {
            "shape_id": shape_id,
            "shape_pt_lat": 40.0 + index / 100,
            "shape_pt_lon": -3.0 - index / 100,
            "shape_pt_sequence": 1,
        }
        entities[("gtfs_shapes", f"{shape_id}-2")] = {
            "shape_id": shape_id,
            "shape_pt_lat": 40.01 + index / 100,
            "shape_pt_lon": -3.01 - index / 100,
            "shape_pt_sequence": 2,
        }
    return WorkingCopy(entities)


class _Session:
    def __init__(self, working_copy: WorkingCopy) -> None:
        self.working_copy = working_copy
        self.validation_issues: tuple[object, ...] = ()

    def can_edit_route(self, route_id: str) -> bool:
        return self.working_copy.can_edit_route(route_id)

    def set_route_workspace_state(self, state: RouteWorkspaceState) -> None:
        self.working_copy.set_route_workspace_state(state)


class _Map(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.payload = None
        self.show_calls = 0
        self.state_updates = []
        self.selection_updates = []
        self.host_refreshes = 0

    def show_payload(self, payload: object, **_kwargs: object) -> None:
        self.payload = payload
        self.show_calls += 1

    def update_route_states(self, states: object) -> None:
        self.state_updates.append(states)

    def update_route_selection(self, route_id: str) -> None:
        self.selection_updates.append(route_id)

    def refresh_host(self) -> None:
        self.host_refreshes += 1


def test_mass_visibility_guard_has_no_modal_up_to_forty_routes(application, monkeypatch) -> None:
    widget = EditorWidget(lambda: None)
    asked = False

    def unexpected_question(*_args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        nonlocal asked
        asked = True
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "question", unexpected_question)
    assert widget._confirm_mass_visibility(20) is True
    assert widget._confirm_mass_visibility(21) is True
    assert widget._confirm_mass_visibility(40) is True
    assert asked is False
    widget.deleteLater()


def test_mass_visibility_guard_confirms_dynamic_count_and_can_cancel(
    application, monkeypatch
) -> None:
    widget = EditorWidget(lambda: None)
    captured: dict[str, str] = {}

    def cancel_question(
        _parent: QWidget, title: str, text: str, *_args: object
    ) -> QMessageBox.StandardButton:
        captured.update(title=title, text=text)
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "question", cancel_question)
    assert widget._confirm_mass_visibility(79) is False
    assert "79" in captured["text"]
    assert "memoria" in captured["text"].casefold()
    widget.deleteLater()


def test_route_workspace_starts_with_one_visible_route_and_updates_incrementally(
    application, monkeypatch
) -> None:
    working_copy = _working_copy()
    working_copy.set_route_workspace_state(
        RouteWorkspaceState("R1", visible=True, active=True, editable=True)
    )
    working_copy.set_route_workspace_state(RouteWorkspaceState("R4", locked=True))
    session = _Session(working_copy)
    map_widget = _Map()

    widget = EditorWidget(
        lambda: session,  # type: ignore[arg-type]
        map_widget=map_widget,
        map_layers_for_routes=lambda route_ids, **kwargs: map_layers_for_working_copy_routes(
            working_copy, route_ids, **kwargs
        ),
    )

    assert widget._route_list.rowCount() == 4
    assert [widget._editor_tabs.tabText(index) for index in range(widget._editor_tabs.count())] == [
        "Rutas y mapa",
        "Recorrido",
        "Paradas",
        "Horarios",
        "Servicios y operador",
        "Cambios / historial",
        "Avanzado",
    ]
    assert widget._route_list.item(0, 2).text() == "R1"
    assert "route_id: R1" in widget._route_properties.text()
    assert "agency/operator: Operador local (A1)" in widget._route_properties.text()
    assert widget._schedule_trip.count() == 1
    assert widget._schedule_table.rowCount() == 2
    assert widget._geometry_context.text()
    assert widget._stops_context.rowCount() == 2
    assert "Operador local" in widget._services_context.text()
    assert "Cambios de esta ruta: 0" in widget._history_context.text()
    assert map_widget.payload is not None
    features = map_widget.payload.shapes["features"]  # type: ignore[union-attr]
    assert len(features) == 1
    assert map_widget.payload.shape_points["features"] == []  # type: ignore[union-attr,index]
    assert {feature["properties"]["route_id"] for feature in features} == {"R1"}
    properties = {feature["properties"]["route_id"]: feature["properties"] for feature in features}
    assert properties["R1"]["route_active"] is True
    assert properties["R1"]["route_editable"] is True

    segment_payload = map_layers_for_working_copy_routes(
        working_copy, frozenset({"R1"}), include_shape_points=True, segment=("SH1-1", "SH1-2")
    )
    assert len(segment_payload.shape_points["features"]) == 2  # type: ignore[index]

    def fail_refresh() -> None:
        raise AssertionError("Un toggle de workspace no debe reconstruir el editor completo")

    monkeypatch.setattr(widget, "refresh", fail_refresh)
    initial_map_calls = map_widget.show_calls
    widget._route_state_toggled("R2", "visible", True)
    assert map_widget.show_calls == initial_map_calls + 1
    assert {
        feature["properties"]["route_id"]
        for feature in map_widget.payload.shapes["features"]  # type: ignore[union-attr]
    } == {"R1", "R2"}

    widget._route_state_toggled("R1", "dimmed", True)
    assert map_widget.show_calls == initial_map_calls + 1
    assert len(map_widget.state_updates) == 1

    # Active cambia estilos/selección de las filas ya dibujadas; no regenera
    # shapes, paradas ni corredores compartidos.
    widget._route_state_toggled("R2", "active", True)
    assert map_widget.show_calls == initial_map_calls + 1
    assert len(map_widget.state_updates) == 2
    assert session.working_copy.route_state("R1").active is False
    assert session.working_copy.route_state("R2").active is True

    selection = widget._route_list.selectionModel()
    selection.select(
        widget._route_list.model().index(1, 0),
        QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
    )
    widget._route_selection_changed()
    assert widget._selected_route_ids == frozenset({"R1", "R2"})
    assert not widget._advanced_toggle.isChecked()
    widget._edit_selected_shape()
    assert widget._advanced_toggle.isChecked()

    widget._route_list.selectRow(3)
    widget._route_selection_changed()
    assert "route_id: R4" in widget._route_properties.text()
    assert "LOCKED" not in widget._route_context_status.text()
    assert "Bloqueada" in widget._route_context_status.text()
    assert not session.can_edit_route("R4")
    assert not widget._entity_is_editable(("gtfs_routes", "R4"))
    assert not widget._edit_shape_button.isEnabled()
    preview_properties = {
        feature["properties"]["route_id"]: feature["properties"]
        for feature in map_widget.payload.shapes["features"]  # type: ignore[union-attr]
    }
    assert preview_properties["R4"]["route_preview"] is True
    assert session.working_copy.route_state("R4").visible is False
    widget.deleteLater()


def test_hidden_selected_route_is_a_temporary_preview_without_persisting_visibility() -> None:
    working_copy = _working_copy()
    working_copy.set_route_workspace_state(RouteWorkspaceState("R1", visible=True))

    payload = map_layers_for_working_copy_routes(working_copy, {"R1", "R2"}, preview_route_id="R2")

    properties = {
        feature["properties"]["route_id"]: feature["properties"]
        for feature in payload.shapes["features"]
    }
    assert set(properties) == {"R1", "R2"}
    assert properties["R2"]["route_selected"] is True
    assert properties["R2"]["route_preview"] is True
    assert working_copy.route_state("R2").visible is False


def test_preview_is_removed_when_selection_moves_to_an_already_visible_route(application) -> None:
    working_copy = _working_copy()
    working_copy.set_route_workspace_state(RouteWorkspaceState("R1", visible=True))
    map_widget = _Map()
    widget = EditorWidget(
        lambda: _Session(working_copy),  # type: ignore[arg-type]
        map_widget=map_widget,
        map_layers_for_routes=lambda route_ids, **kwargs: map_layers_for_working_copy_routes(
            working_copy, route_ids, **kwargs
        ),
    )

    widget._route_list.selectRow(1)
    widget._route_selection_changed()
    previewed_routes = {
        feature["properties"]["route_id"] for feature in map_widget.payload.shapes["features"]
    }
    assert previewed_routes == {
        "R1",
        "R2",
    }
    widget._route_list.selectRow(0)
    widget._route_selection_changed()
    rendered_routes = {
        feature["properties"]["route_id"] for feature in map_widget.payload.shapes["features"]
    }
    assert rendered_routes == {"R1"}
    widget.deleteLater()


def test_stale_map_rebuild_result_is_rejected_after_selection_invalidation(application) -> None:
    working_copy = _working_copy()
    map_widget = _Map()
    widget = EditorWidget(lambda: _Session(working_copy), map_widget=map_widget)
    widget._map_rebuild_token = 3
    before = map_widget.show_calls
    widget._map_rebuild_finished(2, object())
    assert map_widget.show_calls == before
    widget.deleteLater()


def test_map_rebuild_signal_holders_are_released_for_stale_and_failed_workers(application) -> None:
    working_copy = _working_copy()
    widget = EditorWidget(lambda: _Session(working_copy), map_widget=_Map())
    widget._map_rebuild_token = 500
    signals = tuple(_MapRebuildSignals() for _ in range(300))
    widget._map_rebuild_signals.update(signals)

    for index, signal in enumerate(signals):
        if index % 2:
            widget._map_rebuild_failed(index, "controlled failure", signal)
        else:
            widget._map_rebuild_finished(index, object(), signal)

    assert not widget._map_rebuild_signals
    widget.deleteLater()


def test_edit_session_routes_render_without_changing_persisted_visibility() -> None:
    working_copy = _working_copy(route_count=3)
    payload = map_layers_for_working_copy_routes(
        working_copy,
        {"R1", "R2", "R3"},
        session_route_ids={"R1", "R2", "R3"},
    )

    properties = {
        feature["properties"]["route_id"]: feature["properties"]
        for feature in payload.shapes["features"]
    }
    assert set(properties) == {"R1", "R2", "R3"}
    assert all(properties[route_id]["route_visible"] for route_id in properties)
    assert all(not working_copy.route_state(route_id).visible for route_id in properties)


def test_editor_opens_the_existing_map_in_a_cartographic_window(application) -> None:
    working_copy = _working_copy()
    working_copy.set_route_workspace_state(
        RouteWorkspaceState("R1", visible=True, active=True, editable=True)
    )
    map_widget = _Map()
    widget = EditorWidget(
        lambda: _Session(working_copy),  # type: ignore[arg-type]
        map_widget=map_widget,
        map_layers_for_routes=lambda route_ids, **kwargs: map_layers_for_working_copy_routes(
            working_copy, route_ids, **kwargs
        ),
    )

    action = widget.findChild(QWidget, "openEditorMapWindow")
    assert action is not None and action.isEnabled()
    widget._open_map_window()
    application.processEvents()

    assert widget._map_window is not None
    assert map_widget.parentWidget() is widget._map_window
    assert widget._map_window.findChild(QWidget, "mapWindowConfirm") is not None
    assert widget._map_window.findChild(QWidget, "mapWindowCancel") is not None
    assert widget._map_window.findChild(QWidget, "mapWindowSelectSegment") is not None
    assert (
        "Ruta activa: R1" in widget._map_window.findChild(QWidget, "mapWindowEditorContext").text()
    )  # type: ignore[union-attr]
    map_window = widget._map_window
    for _ in range(5):
        map_window.close()
        application.processEvents()
        assert map_widget.parentWidget() is widget.map_host
        widget._open_map_window()
        application.processEvents()
        assert widget._map_window is map_window
        assert map_widget.parentWidget() is map_window
    map_window.close()
    application.processEvents()
    assert map_widget.parentWidget() is widget.map_host
    widget.close_map_window()
    widget.deleteLater()


def test_route_workspace_reparents_the_same_map_widget(application) -> None:
    working_copy = _working_copy()
    working_copy.set_route_workspace_state(
        RouteWorkspaceState("R1", visible=True, active=True, editable=True)
    )
    map_widget = _Map()
    widget = EditorWidget(
        lambda: _Session(working_copy),  # type: ignore[arg-type]
        map_widget=map_widget,
        map_layers_for_routes=lambda route_ids, **kwargs: map_layers_for_working_copy_routes(
            working_copy, route_ids, **kwargs
        ),
    )

    widget._dock_map()
    assert map_widget.parentWidget() is widget.map_host
    widget._editor_tabs.setCurrentWidget(widget._geometry_page)
    application.processEvents()
    assert map_widget.parentWidget() is widget._geometry_map_host
    assert map_widget.host_refreshes >= 1
    widget._editor_tabs.setCurrentIndex(0)
    application.processEvents()
    assert map_widget.parentWidget() is widget.map_host
    widget.deleteLater()
