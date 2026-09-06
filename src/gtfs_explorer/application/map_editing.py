"""Casos de uso que convierten gestos del mapa en comandos del editor."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import uuid4

from gtfs_explorer.application.editor_session import EditorSession
from gtfs_explorer.domain.changesets import (
    EditorCommand,
    EditorCommandKind,
    EntityChange,
    ImpactAnalysis,
)
from gtfs_explorer.presentation.map_bridge import MapEditGesture


class MapEditError(ValueError):
    """El gesto no puede convertirse en una edición segura del borrador."""


class MapEditMode(StrEnum):
    """Modos explícitos del editor cartográfico."""

    NORMAL = "NORMAL"
    EDIT_ROUTE = "EDIT_ROUTE"
    SELECT_SEGMENT = "SELECT_SEGMENT"
    REDRAW_SEGMENT = "REDRAW_SEGMENT"


@dataclass(frozen=True)
class MapEditProposal:
    """Comando y previsualización que la UI debe confirmar antes de aplicar."""

    command: EditorCommand
    impact: ImpactAnalysis


class MapEditController:
    """Controlador sin SQL: el mapa solo propone, la sesión aplica."""

    def __init__(self, session: EditorSession, mode: MapEditMode | None = None) -> None:
        self._session = session
        self._mode = mode

    def propose(self, gesture: MapEditGesture) -> MapEditProposal:
        if gesture.action in {"select", "drag_start", "drag_preview"}:
            raise MapEditError("El gesto visual todavía no es una operación confirmable.")
        if self._mode is MapEditMode.NORMAL:
            raise MapEditError("El mapa está en NORMAL: entra en un modo de edición explícito.")
        if gesture.entity_type == "shape_vertex" and self._mode not in {
            None,
            MapEditMode.EDIT_ROUTE,
            MapEditMode.REDRAW_SEGMENT,
        }:
            raise MapEditError(
                "La geometría solo puede modificarse en un modo de recorrido explícito."
            )
        if gesture.entity_type == "shape_vertex" and gesture.action in {
            "add_vertex",
        }:
            if self._mode is not MapEditMode.REDRAW_SEGMENT:
                raise MapEditError("Añadir vértices requiere REDRAW_SEGMENT.")
            command = self._add_shape_point(gesture)
            return MapEditProposal(command, self._session.preview_impact(command))
        key, before = self._target(gesture)
        self._check_route_permission(gesture, before)
        if gesture.entity_type == "stop" and gesture.action == "drag_end":
            command = self._move_stop(key, before, gesture)
        elif gesture.entity_type == "shape_vertex" and gesture.action in {
            "drag_end",
            "move_vertex",
        }:
            command = self._move_shape_point(key, before, gesture)
        elif gesture.entity_type == "shape_vertex" and gesture.action == "delete_vertex":
            command = EditorCommand(EditorCommandKind.DELETE_SHAPE_POINT, key, before, None)
        elif gesture.entity_type == "shape_vertex" and gesture.action == "reorder_vertex":
            command = self._reorder_shape_point(key, before, gesture)
        else:
            raise MapEditError("El gesto de mapa no tiene un comando 0.2.0 implementado.")
        return MapEditProposal(command, self._session.preview_impact(command))

    def _add_shape_point(self, gesture: MapEditGesture) -> EditorCommand:
        if gesture.longitude is None or gesture.latitude is None:
            raise MapEditError("Añadir un vértice requiere una coordenada WGS84 completa.")
        points = list(
            self._session.working_copy.entity_index.shapes_by_id.get(gesture.entity_id, ())
        )
        if not points:
            raise MapEditError(f"El shape {gesture.entity_id!r} no existe en el borrador.")
        points.sort(key=lambda item: _sequence(item[1].get("shape_pt_sequence")))
        position = len(points) if gesture.position is None else gesture.position
        if not 0 <= position <= len(points):
            raise MapEditError("La posición del nuevo vértice queda fuera de la geometría.")
        self._check_route_permission(gesture, points[0][1])
        new_sequence = _intermediate_sequence(points, position)
        source_rows = [
            int(payload["source_row"])
            for _key, payload in points
            if isinstance(payload.get("source_row"), int)
        ]
        new_key = ("gtfs_shapes", f"draft-{uuid4().hex}")
        new_payload = {
            "source_filename": "editor",
            "source_row": (max(source_rows) + 1) if source_rows else 1,
            "raw_values": {},
            "shape_id": gesture.entity_id,
            "shape_pt_lat": gesture.latitude,
            "shape_pt_lon": gesture.longitude,
            "shape_pt_sequence": new_sequence,
        }
        return EditorCommand(
            EditorCommandKind.ADD_SHAPE_POINT,
            new_key,
            None,
            new_payload,
            changes=(),
            metadata={"shape_id": gesture.entity_id, "geometry_edit": "insert_vertex"},
        )

    def _reorder_shape_point(
        self,
        key: tuple[str, str],
        before: dict[str, object],
        gesture: MapEditGesture,
    ) -> EditorCommand:
        if gesture.position is None:
            raise MapEditError("Reordenar un vértice requiere una posición explícita.")
        shape_id = before.get("shape_id")
        points = list(self._session.working_copy.entity_index.shapes_by_id.get(str(shape_id), ()))
        points.sort(key=lambda item: _sequence(item[1].get("shape_pt_sequence")))
        positions = {candidate: index for index, (candidate, _payload) in enumerate(points)}
        if key not in positions or not 0 <= gesture.position < len(points):
            raise MapEditError("La posición del vértice queda fuera de la geometría.")
        self._check_route_permission(gesture, before)
        item = points.pop(positions[key])
        points.insert(gesture.position, item)
        changes = tuple(
            EntityChange(
                candidate,
                self._session.working_copy.get(candidate),
                _with_sequence(self._session.working_copy.get(candidate), (index + 1) * 10),
            )
            for index, (candidate, _payload) in enumerate(points)
            if self._session.working_copy.get(candidate) is not None
        )
        updated = _with_sequence(before, (gesture.position + 1) * 10)
        changes = tuple(change for change in changes if change.entity_key != key)
        return EditorCommand(
            EditorCommandKind.MOVE_SHAPE_POINT,
            key,
            before,
            updated,
            changes=changes,
            metadata={"shape_id": str(shape_id), "geometry_edit": "reorder_vertex"},
        )

    def apply(self, proposal: MapEditProposal) -> EditorCommand:
        """Aplica la propuesta después de que la UI haya confirmado su impacto."""
        return self._session.apply(proposal.command, impact=proposal.impact)

    def _target(self, gesture: MapEditGesture) -> tuple[tuple[str, str], dict[str, object]]:
        table = "gtfs_stops" if gesture.entity_type == "stop" else "gtfs_shapes"
        key = (table, gesture.entity_id)
        index = self._session.working_copy.entity_index
        exact = index.by_table.get(table, ())
        exact_payload = next((payload for candidate, payload in exact if candidate == key), None)
        if exact_payload is not None:
            payload = self._session.working_copy.get(key) or exact_payload
            self._check_expected_shape(gesture, payload)
            return key, payload
        identity = "stop_id" if table == "gtfs_stops" else "source_row"
        for candidate, payload in exact:
            value = payload.get(identity)
            if str(value) == gesture.entity_id:
                resolved = self._session.working_copy.get(candidate) or payload
                self._check_expected_shape(gesture, resolved)
                return candidate, resolved
        raise MapEditError(f"La entidad de mapa {gesture.entity_id!r} no existe en el borrador.")

    @staticmethod
    def _check_expected_shape(gesture: MapEditGesture, payload: dict[str, object]) -> None:
        if (
            gesture.entity_type == "shape_vertex"
            and gesture.shape_id is not None
            and payload.get("shape_id") != gesture.shape_id
        ):
            raise MapEditError("El vértice no pertenece al shape seleccionado.")

    def _check_route_permission(self, gesture: MapEditGesture, payload: dict[str, object]) -> None:
        route_ids = self._route_ids(gesture.entity_type, payload)
        if gesture.route_id is not None:
            if gesture.route_id not in route_ids:
                raise MapEditError("La entidad no pertenece a la ruta indicada.")
        if len(route_ids) != 1:
            raise MapEditError(
                "La edición de mapa requiere una única ruta activa como contexto explícito."
            )
        route_id = next(iter(route_ids))
        if not self._session.can_edit_route(route_id):
            raise MapEditError(
                "La ruta no está autorizada: debe estar activa, editable y desbloqueada."
            )

    def _route_ids(self, entity_type: str, payload: dict[str, object]) -> set[str]:
        index = self._session.working_copy.entity_index
        if entity_type == "shape_vertex":
            shape_id = str(payload.get("shape_id") or "")
            return set().union(
                *(
                    index.route_ids_by_entity.get(key, frozenset())
                    for key, _payload in index.shapes_by_id.get(shape_id, ())
                )
            )
        stop_id = payload.get("stop_id")
        return set().union(
            *(
                self._session.working_copy.entity_index.route_ids_by_entity.get(key, frozenset())
                for key, stop_time in self._session.working_copy.entity_index.by_table.get(
                    "gtfs_stop_times", ()
                )
                if stop_time.get("stop_id") == stop_id
            )
        )

    @staticmethod
    def _move_stop(
        key: tuple[str, str], before: dict[str, object], gesture: MapEditGesture
    ) -> EditorCommand:
        if gesture.longitude is None or gesture.latitude is None:
            raise MapEditError("Mover una parada requiere una coordenada WGS84 completa.")
        after = dict(before)
        after["stop_lon"] = gesture.longitude
        after["stop_lat"] = gesture.latitude
        return EditorCommand(EditorCommandKind.MOVE_STOP, key, before, after)

    @staticmethod
    def _move_shape_point(
        key: tuple[str, str], before: dict[str, object], gesture: MapEditGesture
    ) -> EditorCommand:
        if gesture.longitude is None or gesture.latitude is None:
            raise MapEditError("Mover un vértice requiere una coordenada WGS84 completa.")
        after = dict(before)
        after["shape_pt_lon"] = gesture.longitude
        after["shape_pt_lat"] = gesture.latitude
        return EditorCommand(EditorCommandKind.MOVE_SHAPE_POINT, key, before, after)


def _sequence(value: object) -> tuple[int, int | str]:
    if isinstance(value, int) and not isinstance(value, bool):
        return (0, value)
    return (1, "" if value is None else str(value))


def _with_sequence(payload: dict[str, object] | None, value: int) -> dict[str, object]:
    if payload is None:
        raise MapEditError("El vértice ya no existe en el borrador.")
    result = dict(payload)
    result["shape_pt_sequence"] = value
    return result


def _intermediate_sequence(
    points: list[tuple[tuple[str, str], dict[str, object]]], position: int
) -> int:
    """Obtiene una secuencia local sin reescribir las filas vecinas."""
    previous = points[position - 1][1].get("shape_pt_sequence") if position else None
    following = points[position][1].get("shape_pt_sequence") if position < len(points) else None
    previous_int = (
        previous if isinstance(previous, int) and not isinstance(previous, bool) else None
    )
    following_int = (
        following if isinstance(following, int) and not isinstance(following, bool) else None
    )
    if previous_int is not None and following_int is not None:
        if following_int - previous_int <= 1:
            raise MapEditError(
                "No hay hueco de secuencia para añadir el vértice. "
                "Solicita la acción explícita de renumerar el shape."
            )
        return previous_int + (following_int - previous_int) // 2
    if previous_int is not None:
        return previous_int + 10
    if following_int is not None:
        return following_int - 10
    return 10
