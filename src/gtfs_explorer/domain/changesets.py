"""Modelo de borrador no destructivo para el editor visual 0.2.0.

Este módulo no conoce DuckDB ni Qt. El original se copia al crear el borrador y
solo la working copy puede cambiar. Los comandos guardan payloads JSON para
que el historial sea portable y auditable.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping, Sequence, cast
from uuid import uuid4


class EditorCommandKind(StrEnum):
    ADD_STOP = "ADD_STOP"
    DELETE_STOP = "DELETE_STOP"
    MOVE_STOP = "MOVE_STOP"
    UPDATE_STOP = "UPDATE_STOP"
    REORDER_STOP = "REORDER_STOP"
    DELETE_ROUTE = "DELETE_ROUTE"
    UPDATE_SHAPE = "UPDATE_SHAPE"
    ADD_SHAPE_POINT = "ADD_SHAPE_POINT"
    MOVE_SHAPE_POINT = "MOVE_SHAPE_POINT"
    DELETE_SHAPE_POINT = "DELETE_SHAPE_POINT"
    UPDATE_ROUTE = "UPDATE_ROUTE"
    UPDATE_TRIP = "UPDATE_TRIP"
    UPDATE_STOP_TIME = "UPDATE_STOP_TIME"
    UPDATE_SERVICE = "UPDATE_SERVICE"
    UPDATE_AGENCY = "UPDATE_AGENCY"
    UPDATE_ATTRIBUTION = "UPDATE_ATTRIBUTION"


Payload = dict[str, Any]
EntityKey = tuple[str, str]


_STRUCTURAL_COMMANDS = frozenset(
    {
        EditorCommandKind.ADD_STOP,
        EditorCommandKind.DELETE_STOP,
        EditorCommandKind.REORDER_STOP,
        EditorCommandKind.DELETE_ROUTE,
        EditorCommandKind.UPDATE_SHAPE,
        EditorCommandKind.ADD_SHAPE_POINT,
        EditorCommandKind.MOVE_SHAPE_POINT,
        EditorCommandKind.DELETE_SHAPE_POINT,
        EditorCommandKind.UPDATE_ROUTE,
        EditorCommandKind.UPDATE_TRIP,
        EditorCommandKind.UPDATE_STOP_TIME,
        EditorCommandKind.UPDATE_SERVICE,
        EditorCommandKind.UPDATE_AGENCY,
        EditorCommandKind.UPDATE_ATTRIBUTION,
    }
)


class ImpactConfirmationRequired(ValueError):
    """La operación estructural necesita una previsualización confirmada."""


class ImpactResolutionRequired(ValueError):
    """La operación tiene referencias que deben resolverse explícitamente."""


@dataclass(frozen=True)
class RouteWorkspaceState:
    """Permisos de presentación y edición de una ruta dentro del borrador."""

    route_id: str
    visible: bool = False
    active: bool = False
    editable: bool = False
    locked: bool = False
    dimmed: bool = False

    @property
    def can_edit(self) -> bool:
        return self.active and self.editable and not self.locked


@dataclass(frozen=True)
class EntityChange:
    """Cambio explícito de una entidad secundaria dentro de un comando compuesto."""

    entity_key: EntityKey
    before: Payload | None
    after: Payload | None

    def __post_init__(self) -> None:
        if not self.entity_key[0] or not self.entity_key[1]:
            raise ValueError("Una entidad secundaria debe tener tabla e identificador.")
        if self.before is None and self.after is None:
            raise ValueError("Un cambio secundario debe tener al menos un estado.")


@dataclass(frozen=True)
class ImpactAnalysis:
    """Previsualización reproducible de relaciones afectadas por un comando."""

    command_kind: EditorCommandKind
    entity_key: EntityKey
    affected_entities: tuple[EntityKey, ...]
    affected_tables: tuple[str, ...]
    relationships: tuple[str, ...]
    required_entity_changes: tuple[EntityKey, ...] = ()
    resolution_options: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    fingerprint: str = ""

    @property
    def requires_confirmation(self) -> bool:
        return bool(
            self.command_kind in _STRUCTURAL_COMMANDS
            or self.required_entity_changes
            or self.blockers
        )

    @property
    def requires_resolution(self) -> bool:
        return bool(self.required_entity_changes or self.blockers)

    def with_fingerprint(
        self, *, before: Payload | None, after: Payload | None
    ) -> "ImpactAnalysis":
        payload = {
            "command_kind": self.command_kind.value,
            "entity_key": list(self.entity_key),
            "before": _json_prepare(before),
            "after": _json_prepare(after),
            "affected_entities": [list(key) for key in self.affected_entities],
            "affected_tables": list(self.affected_tables),
            "relationships": list(self.relationships),
            "required_entity_changes": [list(key) for key in self.required_entity_changes],
            "resolution_options": list(self.resolution_options),
            "blockers": list(self.blockers),
        }
        fingerprint = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
        return replace(self, fingerprint=fingerprint)

    def as_payload(self) -> dict[str, Any]:
        return {
            "command_kind": self.command_kind.value,
            "entity_key": list(self.entity_key),
            "affected_entities": [list(key) for key in self.affected_entities],
            "affected_tables": list(self.affected_tables),
            "relationships": list(self.relationships),
            "required_entity_changes": [list(key) for key in self.required_entity_changes],
            "resolution_options": list(self.resolution_options),
            "blockers": list(self.blockers),
            "fingerprint": self.fingerprint,
        }

    def approve(self, command: "EditorCommand") -> "EditorCommand":
        """Adjunta el impacto confirmado al comando, sin cambiar sus datos."""
        if command.entity_key != self.entity_key or command.kind != self.command_kind:
            raise ValueError("El impacto no corresponde al comando solicitado.")
        return replace(
            command,
            affected_entities=tuple(
                key for key in self.affected_entities if key != command.entity_key
            ),
            impact=self.as_payload(),
        )


@dataclass(frozen=True)
class EditorCommand:
    """Una mutación reversible sobre una entidad del borrador."""

    kind: EditorCommandKind
    entity_key: EntityKey
    before: Payload | None
    after: Payload | None
    affected_entities: tuple[EntityKey, ...] = ()
    changes: tuple[EntityChange, ...] = ()
    impact: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    command_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    sequence: int = 0
    inverse_of: str | None = None

    def __post_init__(self) -> None:
        if not self.entity_key[0] or not self.entity_key[1]:
            raise ValueError("Una entidad debe tener tabla e identificador.")
        if self.before is None and self.after is None:
            raise ValueError("Un comando debe tener al menos un estado.")

    @property
    def entity_keys(self) -> tuple[EntityKey, ...]:
        result: list[EntityKey] = [self.entity_key, *self.affected_entities]
        result.extend(change.entity_key for change in self.changes)
        return tuple(dict.fromkeys(result))

    def payload(self, *, forward: bool) -> Payload | None:
        value = self.after if forward else self.before
        return copy.deepcopy(value) if value is not None else None

    def precondition_hash(self) -> str:
        value = _canonical_json(self.before)
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def approved_impact_fingerprint(self) -> str | None:
        if self.impact is None:
            return None
        value = self.impact.get("fingerprint")
        return str(value) if value is not None else None


@dataclass(frozen=True)
class HistoryEvent:
    action: str
    command_id: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


EntityRows = tuple[tuple[EntityKey, Payload], ...]


@dataclass
class WorkingCopyEntityIndex:
    """Índices de solo lectura para las consultas frecuentes del editor.

    Las cargas apuntan a la working copy y no se exponen a operaciones mutantes.
    Se reconstruyen tras un cambio GTFS, pero un cambio de estado visual de ruta
    no los invalida porque no modifica ninguna entidad.
    """

    by_table: dict[str, EntityRows]
    routes_by_id: dict[str, Payload]
    agencies_by_id: dict[str, Payload]
    trips_by_id: dict[str, Payload]
    trips_by_route: dict[str, EntityRows]
    stop_times_by_trip: dict[str, EntityRows]
    stop_times_by_stop: dict[str, EntityRows]
    stops_by_id: dict[str, Payload]
    shapes_by_id: dict[str, EntityRows]
    route_ids_by_entity: dict[EntityKey, frozenset[str]]
    entity_count: int

    @classmethod
    def build(cls, entities: Mapping[EntityKey, Payload]) -> "WorkingCopyEntityIndex":
        grouped: dict[str, list[tuple[EntityKey, Payload]]] = {}
        routes_by_id: dict[str, Payload] = {}
        agencies_by_id: dict[str, Payload] = {}
        trips_by_id: dict[str, Payload] = {}
        stops_by_id: dict[str, Payload] = {}
        trips_by_route: dict[str, list[tuple[EntityKey, Payload]]] = {}
        stop_times_by_trip: dict[str, list[tuple[EntityKey, Payload]]] = {}
        stop_times_by_stop: dict[str, list[tuple[EntityKey, Payload]]] = {}
        shapes_by_id: dict[str, list[tuple[EntityKey, Payload]]] = {}

        for key, payload in entities.items():
            table_name = key[0]
            grouped.setdefault(table_name, []).append((key, payload))
            if table_name == "gtfs_routes" and payload.get("route_id") is not None:
                routes_by_id[str(payload["route_id"])] = payload
            elif table_name == "gtfs_agency" and payload.get("agency_id") is not None:
                agencies_by_id[str(payload["agency_id"])] = payload
            elif table_name == "gtfs_trips" and payload.get("trip_id") is not None:
                trip_id = str(payload["trip_id"])
                trips_by_id[trip_id] = payload
                route_id = payload.get("route_id")
                if route_id is not None:
                    trips_by_route.setdefault(str(route_id), []).append((key, payload))
            elif table_name == "gtfs_stop_times":
                trip_id_value = payload.get("trip_id")
                if trip_id_value is not None:
                    stop_times_by_trip.setdefault(str(trip_id_value), []).append((key, payload))
                stop_id_value = payload.get("stop_id")
                if stop_id_value is not None:
                    stop_times_by_stop.setdefault(str(stop_id_value), []).append((key, payload))
            elif table_name == "gtfs_stops" and payload.get("stop_id") is not None:
                stops_by_id[str(payload["stop_id"])] = payload
            elif table_name == "gtfs_shapes" and payload.get("shape_id") is not None:
                shapes_by_id.setdefault(str(payload["shape_id"]), []).append((key, payload))

        route_ids_by_agency: dict[str, set[str]] = {}
        route_ids_by_service: dict[str, set[str]] = {}
        route_ids_by_shape: dict[str, set[str]] = {}
        route_ids_by_stop: dict[str, set[str]] = {}
        for route in routes_by_id.values():
            route_id = route.get("route_id")
            if route_id is None:
                continue
            agency_id = route.get("agency_id")
            if agency_id is not None:
                route_ids_by_agency.setdefault(str(agency_id), set()).add(str(route_id))
        for trip in trips_by_id.values():
            route_id = trip.get("route_id")
            if route_id is None:
                continue
            route_id = str(route_id)
            service_id = trip.get("service_id")
            if service_id is not None:
                route_ids_by_service.setdefault(str(service_id), set()).add(route_id)
            shape_id = trip.get("shape_id")
            if shape_id is not None:
                route_ids_by_shape.setdefault(str(shape_id), set()).add(route_id)

        def _route_id_for_trip(trip_id_value: object) -> str | None:
            if trip_id_value is None:
                return None
            trip = trips_by_id.get(str(trip_id_value))
            route_id = trip.get("route_id") if trip is not None else None
            return str(route_id) if route_id is not None else None

        route_ids_by_entity: dict[EntityKey, frozenset[str]] = {
            key: frozenset() for key in entities
        }
        for key, payload in grouped.get("gtfs_routes", ()):
            route_id = payload.get("route_id")
            if route_id is not None:
                route_ids_by_entity[key] = frozenset((str(route_id),))
        for key, payload in grouped.get("gtfs_trips", ()):
            route_id = payload.get("route_id")
            if route_id is not None:
                route_ids_by_entity[key] = frozenset((str(route_id),))
        for key, payload in grouped.get("gtfs_stop_times", ()):
            route_id = _route_id_for_trip(payload.get("trip_id"))
            if route_id is not None:
                route_ids_by_entity[key] = frozenset((route_id,))
                stop_id = payload.get("stop_id")
                if stop_id is not None:
                    route_ids_by_stop.setdefault(str(stop_id), set()).add(route_id)
        for key, payload in grouped.get("gtfs_stops", ()):
            stop_id = payload.get("stop_id")
            if stop_id is not None:
                route_ids_by_entity[key] = frozenset(route_ids_by_stop.get(str(stop_id), ()))
        for key, payload in grouped.get("gtfs_shapes", ()):
            shape_id = payload.get("shape_id")
            if shape_id is not None:
                route_ids_by_entity[key] = frozenset(route_ids_by_shape.get(str(shape_id), ()))
        for key, payload in grouped.get("gtfs_transfers", ()):
            route_ids = {
                str(payload[field_name])
                for field_name in ("from_route_id", "to_route_id")
                if payload.get(field_name) is not None
            }
            for field_name in ("from_trip_id", "to_trip_id"):
                route_id = _route_id_for_trip(payload.get(field_name))
                if route_id is not None:
                    route_ids.add(route_id)
            route_ids_by_entity[key] = frozenset(route_ids)
        for key, payload in grouped.get("gtfs_attributions", ()):
            route_ids = {str(payload["route_id"])} if payload.get("route_id") is not None else set()
            route_id = _route_id_for_trip(payload.get("trip_id"))
            if route_id is not None:
                route_ids.add(route_id)
            route_ids_by_entity[key] = frozenset(route_ids)
        for key, payload in grouped.get("gtfs_agency", ()):
            agency_id = payload.get("agency_id")
            if agency_id is not None:
                route_ids_by_entity[key] = frozenset(route_ids_by_agency.get(str(agency_id), ()))
        for table_name in ("gtfs_calendar", "gtfs_calendar_dates"):
            for key, payload in grouped.get(table_name, ()):
                service_id = payload.get("service_id")
                if service_id is not None:
                    route_ids_by_entity[key] = frozenset(
                        route_ids_by_service.get(str(service_id), ())
                    )

        return cls(
            by_table={name: tuple(rows) for name, rows in grouped.items()},
            routes_by_id=routes_by_id,
            agencies_by_id=agencies_by_id,
            trips_by_id=trips_by_id,
            trips_by_route={name: tuple(rows) for name, rows in trips_by_route.items()},
            stop_times_by_trip={name: tuple(rows) for name, rows in stop_times_by_trip.items()},
            stop_times_by_stop={name: tuple(rows) for name, rows in stop_times_by_stop.items()},
            stops_by_id=stops_by_id,
            shapes_by_id={name: tuple(rows) for name, rows in shapes_by_id.items()},
            route_ids_by_entity=route_ids_by_entity,
            entity_count=len(entities),
        )


class ChangeSet:
    """Historial lineal con ramas redo descartables pero auditables."""

    def __init__(
        self, *, changeset_id: str | None = None, base_revision_id: str = "original"
    ) -> None:
        self.changeset_id = changeset_id or str(uuid4())
        self.base_revision_id = base_revision_id
        self.commands: list[EditorCommand] = []
        self.history: list[HistoryEvent] = []
        self._cursor = 0

    @property
    def undo_available(self) -> bool:
        return self._cursor > 0

    @property
    def redo_available(self) -> bool:
        return self._cursor < len(self.commands)

    @property
    def active_commands(self) -> tuple[EditorCommand, ...]:
        return tuple(self.commands[: self._cursor])

    def append(self, command: EditorCommand) -> EditorCommand:
        if self.redo_available:
            self.commands = self.commands[: self._cursor]
        command = replace(command, sequence=len(self.commands) + 1)
        self.commands.append(command)
        self._cursor += 1
        self.history.append(HistoryEvent("APPLY", command.command_id))
        return command

    def undo(self) -> EditorCommand:
        if not self.undo_available:
            raise ValueError("No hay cambios que deshacer.")
        self._cursor -= 1
        command = self.commands[self._cursor]
        self.history.append(HistoryEvent("UNDO", command.command_id))
        return command

    def redo(self) -> EditorCommand:
        if not self.redo_available:
            raise ValueError("No hay cambios que rehacer.")
        command = self.commands[self._cursor]
        self._cursor += 1
        self.history.append(HistoryEvent("REDO", command.command_id))
        return command


class WorkingCopy:
    """Original inmutable, revisión de trabajo y estado de borrador en memoria."""

    def __init__(
        self,
        original: Mapping[EntityKey, Mapping[str, Any]],
        *,
        base_revision_id: str = "original",
        base_entities: Mapping[EntityKey, Mapping[str, Any]] | None = None,
        clone_original: bool = True,
    ) -> None:
        self._original: dict[EntityKey, Payload] = (
            _clone_entities(original)
            if clone_original
            else cast(dict[EntityKey, Payload], dict(original))
        )
        self._base: dict[EntityKey, Payload] = (
            # La base inicial comparte las cargas ya clonadas del original;
            # los comandos sustituyen payloads y nunca mutan uno in situ.
            dict(self._original) if base_entities is None else _clone_entities(base_entities)
        )
        # Las entidades solo se sustituyen por payloads copiados al aplicar un
        # comando; compartir inicialmente las cargas reduce una copia profunda
        # completa al abrir feeds grandes sin relajar la frontera de lectura.
        self._working: dict[EntityKey, Payload] = dict(self._base)
        self._entity_index: WorkingCopyEntityIndex | None = None
        self._geometric_generation = 0
        self.changeset = ChangeSet(base_revision_id=base_revision_id)
        self._route_states: dict[str, RouteWorkspaceState] = {
            str(payload["route_id"]): RouteWorkspaceState(str(payload["route_id"]))
            for key, payload in self._base.items()
            if key[0] == "gtfs_routes" and payload.get("route_id") is not None
        }
        self._base_route_states = copy.deepcopy(self._route_states)

    @property
    def original(self) -> dict[EntityKey, Payload]:
        """Devuelve exclusivamente el snapshot importado, nunca la working copy."""
        return copy.deepcopy(self._original)

    @property
    def base_entities(self) -> dict[EntityKey, Payload]:
        """Devuelve la última revisión confirmada que sirve de base al borrador."""
        return copy.deepcopy(self._base)

    @property
    def base_revision_id(self) -> str:
        return self.changeset.base_revision_id

    @property
    def geometric_generation(self) -> int:
        """Generación de datos cartográficos; los estados visuales no la cambian."""
        return self._geometric_generation

    @property
    def entities(self) -> dict[EntityKey, Payload]:
        return copy.deepcopy(self._working)

    @property
    def entity_count(self) -> int:
        """Número de entidades sin materializar una copia profunda."""
        return len(self._working)

    @property
    def entity_index(self) -> WorkingCopyEntityIndex:
        """Índices de lectura reutilizables durante la sesión del editor."""
        if self._entity_index is None:
            self._entity_index = WorkingCopyEntityIndex.build(self._working)
        return self._entity_index

    @property
    def dirty(self) -> bool:
        return self.data_draft_dirty or self.workspace_dirty

    @property
    def data_draft_dirty(self) -> bool:
        """Cambios GTFS no confirmados que impiden exportar la revisión."""
        return self._working != self._base

    @property
    def workspace_dirty(self) -> bool:
        """Preferencias visuales persistibles, sin efecto en el GTFS exportado."""
        return any(
            self._route_states.get(route_id) != state
            for route_id, state in self._base_route_states.items()
        ) or any(route_id not in self._base_route_states for route_id in self._route_states)

    @property
    def route_states(self) -> dict[str, RouteWorkspaceState]:
        return copy.deepcopy(self._route_states)

    def route_state(self, route_id: str) -> RouteWorkspaceState:
        return self._route_states.get(route_id, RouteWorkspaceState(route_id))

    def set_route_workspace_state(self, state: RouteWorkspaceState) -> None:
        """Actualiza la autorización sin convertir visibilidad en permiso de edición."""
        if not state.route_id:
            raise ValueError("Una ruta debe tener identificador.")
        if state.active:
            for route_id, current in tuple(self._route_states.items()):
                if route_id != state.route_id and current.active:
                    self._route_states[route_id] = replace(current, active=False)
        self._route_states[state.route_id] = state

    def can_edit_route(self, route_id: str) -> bool:
        return self.route_state(route_id).can_edit

    def route_ids_for_entity(self, entity_key: EntityKey) -> frozenset[str]:
        """Devuelve las rutas afectadas por una entidad del borrador.

        La presentación utiliza esta consulta para aplicar el mismo guard de
        ruta activa/bloqueada a campos, mapa y operaciones compuestas. Una
        entidad compartida no se reduce a una ruta arbitraria: el llamador
        debe hacer explícito el contexto antes de mutarla.
        """
        if entity_key not in self._working:
            return frozenset()
        return self.entity_index.route_ids_by_entity.get(entity_key, frozenset())

    def get(self, entity_key: EntityKey) -> Payload | None:
        value = self._working.get(entity_key)
        return copy.deepcopy(value) if value is not None else None

    def apply(self, command: EditorCommand) -> EditorCommand:
        return self._apply(command, impact=None, enforce_impact=True)

    def apply_with_impact(self, command: EditorCommand, impact: ImpactAnalysis) -> EditorCommand:
        """Aplica una operación después de confirmar su análisis de impacto."""
        return self._apply(command, impact=impact, enforce_impact=True)

    def apply_batch(
        self,
        commands: Sequence[EditorCommand],
        impacts: Sequence[ImpactAnalysis] | None = None,
    ) -> tuple[EditorCommand, ...]:
        """Aplica varios comandos como una única operación reversible en memoria.

        La persistencia se realiza por la sesión solo después de que todos los
        comandos hayan superado sus precondiciones. Si uno falla, se restaura
        exactamente el estado previo, incluido el cursor y el historial.
        """
        if impacts is not None and len(impacts) != len(commands):
            raise ValueError("El lote de impactos no coincide con el lote de comandos.")
        working_before = _clone_entities(self._working)
        route_states_before = copy.deepcopy(self._route_states)
        commands_before = list(self.changeset.commands)
        history_before = list(self.changeset.history)
        cursor_before = self.changeset._cursor
        try:
            applied: list[EditorCommand] = []
            for index, command in enumerate(commands):
                if impacts is None:
                    applied.append(self.apply(command))
                else:
                    applied.append(self.apply_with_impact(command, impacts[index]))
            return tuple(applied)
        except BaseException:
            self._working = working_before
            self._entity_index = None
            self._route_states = route_states_before
            self.changeset.commands = commands_before
            self.changeset.history = history_before
            self.changeset._cursor = cursor_before
            raise

    def analyze_impact(self, command: EditorCommand) -> ImpactAnalysis:
        """Calcula dependencias sobre el estado efectivo sin modificarlo."""
        command = _normalize_command(command)
        if command.kind in {
            EditorCommandKind.MOVE_STOP,
            EditorCommandKind.MOVE_SHAPE_POINT,
            EditorCommandKind.ADD_SHAPE_POINT,
            EditorCommandKind.DELETE_SHAPE_POINT,
        }:
            return self._analyze_local_map_impact(command)
        table, value = command.entity_key
        target = self.get(command.entity_key)
        if target is None:
            target = command.before
        if target is None:
            target = command.after
        if target is None:
            raise ValueError("No existe la entidad objetivo para analizar el impacto.")

        affected: set[EntityKey] = {command.entity_key}
        required: set[EntityKey] = set()
        relationships: set[str] = set()
        blockers: set[str] = set()
        options: set[str] = set()

        def add_rows(
            table_name: str, field: str, field_value: object, relation: str
        ) -> list[EntityKey]:
            if field_value is None:
                return []
            rows = [
                key
                for key, payload in self._working.items()
                if key[0] == table_name and payload.get(field) == field_value
            ]
            if rows:
                relationships.add(relation)
                affected.update(rows)
            return rows

        seen_trips: set[object] = set()
        seen_routes: set[object] = set()
        seen_services: set[object] = set()
        seen_shapes: set[object] = set()
        seen_agencies: set[object] = set()

        def include_trip_graph(trip_ids: Sequence[object]) -> None:
            for trip_id in trip_ids:
                if trip_id is None or trip_id in seen_trips:
                    continue
                seen_trips.add(trip_id)
                trip_rows = add_rows(
                    "gtfs_trips", "trip_id", trip_id, "trip -> route/service/shape"
                )
                for trip_key in trip_rows:
                    trip = self._working[trip_key]
                    route_id = trip.get("route_id")
                    service_id = trip.get("service_id")
                    shape_id = trip.get("shape_id")
                    add_rows("gtfs_stop_times", "trip_id", trip_id, "trip -> stop_times")
                    add_rows("gtfs_frequencies", "trip_id", trip_id, "trip -> frequencies")
                    add_rows("gtfs_transfers", "from_trip_id", trip_id, "trip -> transfers")
                    add_rows("gtfs_transfers", "to_trip_id", trip_id, "trip -> transfers")
                    add_rows("gtfs_attributions", "trip_id", trip_id, "trip -> attributions")
                    include_route(route_id)
                    include_service(service_id)
                    include_shape(shape_id)

        def include_route(route_id: object) -> None:
            if route_id is None or route_id in seen_routes:
                return
            seen_routes.add(route_id)
            route_rows = add_rows("gtfs_routes", "route_id", route_id, "route -> trips")
            add_rows("gtfs_transfers", "from_route_id", route_id, "route -> transfers")
            add_rows("gtfs_transfers", "to_route_id", route_id, "route -> transfers")
            add_rows("gtfs_attributions", "route_id", route_id, "route -> attributions")
            for route_key in route_rows:
                agency_id = self._working[route_key].get("agency_id")
                include_agency(agency_id)
            trip_ids = [
                payload.get("trip_id")
                for key, payload in self._working.items()
                if key[0] == "gtfs_trips" and payload.get("route_id") == route_id
            ]
            include_trip_graph(trip_ids)

        def include_service(service_id: object) -> None:
            if service_id is None or service_id in seen_services:
                return
            seen_services.add(service_id)
            add_rows("gtfs_calendar", "service_id", service_id, "service -> calendar")
            add_rows("gtfs_calendar_dates", "service_id", service_id, "service -> calendar_dates")
            trip_rows = add_rows("gtfs_trips", "service_id", service_id, "service -> trips")
            include_trip_graph([self._working[key].get("trip_id") for key in trip_rows])

        def include_shape(shape_id: object) -> None:
            if shape_id is None or shape_id in seen_shapes:
                return
            seen_shapes.add(shape_id)
            add_rows("gtfs_shapes", "shape_id", shape_id, "shape -> geometry")
            trip_rows = add_rows("gtfs_trips", "shape_id", shape_id, "shape -> trips")
            include_trip_graph([self._working[key].get("trip_id") for key in trip_rows])

        def include_agency(agency_id: object) -> None:
            if agency_id is None or agency_id in seen_agencies:
                return
            seen_agencies.add(agency_id)
            add_rows("gtfs_agency", "agency_id", agency_id, "agency -> routes")
            add_rows("gtfs_attributions", "agency_id", agency_id, "agency -> attributions")

        before = command.before or {}
        after = command.after or {}
        if table == "gtfs_stops":
            stop_id = before.get("stop_id") or after.get("stop_id") or value
            stop_times = add_rows("gtfs_stop_times", "stop_id", stop_id, "stop -> stop_times")
            add_rows("gtfs_transfers", "from_stop_id", stop_id, "stop -> transfers")
            transfer_rows = add_rows("gtfs_transfers", "to_stop_id", stop_id, "stop -> transfers")
            transfer_rows.extend(
                key
                for key, payload in self._working.items()
                if key[0] == "gtfs_transfers"
                and (payload.get("from_stop_id") == stop_id or payload.get("to_stop_id") == stop_id)
                and key not in transfer_rows
            )
            trip_ids = [self._working[key].get("trip_id") for key in stop_times]
            include_trip_graph(trip_ids)
            if command.after is None and (stop_times or transfer_rows):
                required.update(stop_times)
                required.update(transfer_rows)
                options.update({"delete_stop_times", "reassign_stop_times", "cancel"})
            if before.get("stop_id") != after.get("stop_id") and after.get("stop_id"):
                references = {
                    *stop_times,
                    *transfer_rows,
                }
                required.update(references)
                if references:
                    options.add("update_stop_references")
            if command.kind is EditorCommandKind.ADD_STOP:
                trip_id = command.metadata.get("trip_id")
                if trip_id is not None:
                    include_trip_graph([trip_id])
                    relationships.add("new stop -> selected trip")
                    options.update(
                        {"introduce_stop_times", "preview_interpolation", "leave_unresolved"}
                    )
                else:
                    relationships.add("new standalone stop")
        elif table == "gtfs_routes":
            route_id = before.get("route_id") or after.get("route_id") or value
            include_route(route_id)
            include_agency(before.get("agency_id"))
            include_agency(after.get("agency_id"))
            if command.after is None:
                route_trips = {
                    key
                    for key, payload in self._working.items()
                    if key[0] == "gtfs_trips" and payload.get("route_id") == route_id
                }
                required.update(route_trips)
                required.update(
                    key
                    for key, payload in self._working.items()
                    if key[0] in {"gtfs_transfers", "gtfs_attributions"}
                    and (
                        payload.get("route_id") == route_id
                        or payload.get("from_route_id") == route_id
                        or payload.get("to_route_id") == route_id
                    )
                )
                if required:
                    options.update({"delete_trips_and_stop_times", "reassign_trips", "cancel"})
            if before.get("route_id") != after.get("route_id"):
                references = {
                    key
                    for key, payload in self._working.items()
                    if key[0] in {"gtfs_trips", "gtfs_transfers", "gtfs_attributions"}
                    and route_id
                    in {
                        payload.get("route_id"),
                        payload.get("from_route_id"),
                        payload.get("to_route_id"),
                    }
                }
                required.update(references)
                if references:
                    options.add("update_route_references")
        elif table == "gtfs_trips":
            trip_id = before.get("trip_id") or after.get("trip_id") or value
            include_trip_graph([trip_id])
            include_route(before.get("route_id"))
            include_route(after.get("route_id"))
            include_service(before.get("service_id"))
            include_service(after.get("service_id"))
            include_shape(before.get("shape_id"))
            include_shape(after.get("shape_id"))
            if before.get("trip_id") != after.get("trip_id"):
                references = {
                    key
                    for key, payload in self._working.items()
                    if key[0]
                    in {
                        "gtfs_stop_times",
                        "gtfs_frequencies",
                        "gtfs_transfers",
                        "gtfs_attributions",
                    }
                    and trip_id
                    in {
                        payload.get("trip_id"),
                        payload.get("from_trip_id"),
                        payload.get("to_trip_id"),
                    }
                }
                required.update(references)
                if references:
                    options.add("update_trip_references")
        elif table in {"gtfs_calendar", "gtfs_calendar_dates"}:
            service_id = before.get("service_id") or after.get("service_id") or value
            include_service(service_id)
            include_service(before.get("service_id"))
            include_service(after.get("service_id"))
            if before.get("service_id") != after.get("service_id"):
                references = {
                    key
                    for key, payload in self._working.items()
                    if key[0] in {"gtfs_trips", "gtfs_calendar", "gtfs_calendar_dates"}
                    and payload.get("service_id") == service_id
                }
                required.update(references)
                if references:
                    options.add("update_service_references")
            if command.after is None:
                service_references = {
                    key
                    for key, payload in self._working.items()
                    if key[0] == "gtfs_trips" and payload.get("service_id") == service_id
                }
                required.update(service_references)
                if service_references:
                    options.update({"delete_trips_and_calendar", "reassign_trips", "cancel"})
                required.update(
                    key
                    for key, payload in self._working.items()
                    if key[0] in {"gtfs_calendar", "gtfs_calendar_dates"}
                    and payload.get("service_id") == service_id
                )
        elif table == "gtfs_shapes":
            shape_id = before.get("shape_id") or after.get("shape_id") or value
            include_shape(shape_id)
            include_shape(before.get("shape_id"))
            include_shape(after.get("shape_id"))
            if before.get("shape_id") != after.get("shape_id"):
                references = {
                    key
                    for key, payload in self._working.items()
                    if key[0] == "gtfs_trips" and payload.get("shape_id") == shape_id
                }
                required.update(references)
                if references:
                    options.add("update_shape_references")
        elif table == "gtfs_agency":
            agency_id = before.get("agency_id") or after.get("agency_id") or value
            include_agency(agency_id)
            include_agency(before.get("agency_id"))
            include_agency(after.get("agency_id"))
            if before.get("agency_id") != after.get("agency_id"):
                references = {
                    key
                    for key, payload in self._working.items()
                    if key[0] in {"gtfs_routes", "gtfs_attributions"}
                    and payload.get("agency_id") == agency_id
                }
                required.update(references)
                if references:
                    options.add("update_agency_references")
            if command.after is None:
                agency_references = {
                    key
                    for key, payload in self._working.items()
                    if key[0] in {"gtfs_routes", "gtfs_attributions"}
                    and payload.get("agency_id") == agency_id
                }
                required.update(agency_references)
                if agency_references:
                    options.update({"reassign_routes_and_attributions", "cancel"})
        elif table == "gtfs_stop_times":
            trip_id = before.get("trip_id") or after.get("trip_id")
            stop_id = before.get("stop_id") or after.get("stop_id")
            include_trip_graph([trip_id])
            add_rows("gtfs_stops", "stop_id", stop_id, "stop_time -> stop")
            if before.get("trip_id") != after.get("trip_id"):
                references = {
                    key
                    for key, payload in self._working.items()
                    if key[0] == "gtfs_stop_times" and payload.get("trip_id") == trip_id
                }
                required.update(references)
                if references:
                    options.add("update_stop_time_references")
            if command.kind is EditorCommandKind.REORDER_STOP:
                trip_id = command.metadata.get("trip_id") or before.get("trip_id")
                if trip_id is None:
                    blockers.add("reorder_stop_requires_selected_trip")
                else:
                    stop_times = add_rows(
                        "gtfs_stop_times", "trip_id", trip_id, "reorder -> trip stop_times"
                    )
                    affected.update(stop_times)
                    include_trip_graph([trip_id])
        elif table == "gtfs_attributions":
            include_agency(before.get("agency_id") or after.get("agency_id"))
            include_route(before.get("route_id") or after.get("route_id"))
            include_trip_graph([before.get("trip_id") or after.get("trip_id")])
        elif table in {"gtfs_frequencies", "gtfs_transfers"}:
            include_trip_graph(
                [before.get("trip_id"), before.get("from_trip_id"), before.get("to_trip_id")]
            )
            include_route(before.get("from_route_id") or before.get("to_route_id"))
            add_rows("gtfs_stops", "stop_id", before.get("from_stop_id"), "dependency -> stop")
            add_rows("gtfs_stops", "stop_id", before.get("to_stop_id"), "dependency -> stop")

        required.discard(command.entity_key)
        analysis = ImpactAnalysis(
            command.kind,
            command.entity_key,
            tuple(sorted(affected)),
            tuple(sorted({key[0] for key in affected})),
            tuple(sorted(relationships)),
            tuple(sorted(required)),
            tuple(sorted(options)),
            tuple(sorted(blockers)),
        )
        return analysis.with_fingerprint(before=command.before, after=command.after)

    def _analyze_local_map_impact(self, command: EditorCommand) -> ImpactAnalysis:
        """Analiza una edición cartográfica con índices, sin clonar ni escanear todo."""
        index = self.entity_index
        before = command.before or {}
        after = command.after or {}
        direct = tuple(
            dict.fromkeys((command.entity_key, *(change.entity_key for change in command.changes)))
        )
        route_ids: set[str] = set()
        relationships: list[str] = []
        if command.kind is EditorCommandKind.MOVE_STOP:
            route_ids.update(index.route_ids_by_entity.get(command.entity_key, frozenset()))
            relationships.append(f"stop -> {len(route_ids)} ruta(s) consultada(s)")
        else:
            shape_id = str(
                before.get("shape_id")
                or after.get("shape_id")
                or command.metadata.get("shape_id")
                or ""
            )
            for key, _payload in index.shapes_by_id.get(shape_id, ()):
                route_ids.update(index.route_ids_by_entity.get(key, frozenset()))
            trip_count = sum(len(index.trips_by_route.get(route_id, ())) for route_id in route_ids)
            relationships.extend(
                (
                    "shape -> geometry",
                    f"shape reutilizado por {trip_count} viaje(s)",
                    f"{len(route_ids)} ruta(s) consultada(s)",
                )
            )
        affected_tables = tuple(sorted({key[0] for key in direct}))
        analysis = ImpactAnalysis(
            command.kind,
            command.entity_key,
            direct,
            affected_tables,
            tuple(relationships),
            (),
            (),
            (),
        )
        return analysis.with_fingerprint(before=command.before, after=command.after)

    def prepare_command(
        self,
        command: EditorCommand,
        impact: ImpactAnalysis,
        *,
        resolution: str | None = None,
        replacement_id: str | None = None,
    ) -> EditorCommand:
        """Prepara un comando compuesto tras una elección explícita de resolución."""
        command = _normalize_command(command)
        if resolution is None:
            return impact.approve(command)
        if resolution not in impact.resolution_options:
            raise ValueError("La resolución elegida no pertenece al análisis de impacto.")
        required_keys = set(impact.required_entity_changes)
        if resolution in {"delete_trips_and_stop_times", "delete_trips_and_calendar"}:
            required_keys.update(
                key
                for key in impact.affected_entities
                if key[0]
                in {
                    "gtfs_trips",
                    "gtfs_stop_times",
                    "gtfs_frequencies",
                    "gtfs_transfers",
                    "gtfs_attributions",
                }
            )
        changes: list[EntityChange] = []
        for key in sorted(required_keys):
            payload = self.get(key)
            if payload is None:
                continue
            after = None
            if resolution.startswith("reassign_") or resolution.startswith("update_"):
                if replacement_id is None:
                    raise ValueError("La resolución requiere un identificador de reasignación.")
                after = _reassigned_payload(payload, command, resolution, replacement_id)
                if after is None:
                    raise ValueError("No se ha podido determinar la referencia a resolver.")
            changes.append(EntityChange(key, payload, after))
        approved = impact.approve(command)
        metadata = dict(approved.metadata)
        metadata["impact_resolution"] = resolution
        return replace(approved, changes=tuple(changes), metadata=metadata)

    def _apply(
        self,
        command: EditorCommand,
        *,
        impact: ImpactAnalysis | None,
        enforce_impact: bool,
    ) -> EditorCommand:
        command = _normalize_command(command)
        analysis = self.analyze_impact(command) if enforce_impact else None
        if analysis is not None and analysis.requires_confirmation:
            supplied = impact or _impact_from_payload(command.impact)
            if supplied is None or supplied.fingerprint != analysis.fingerprint:
                raise ImpactConfirmationRequired(
                    "La operación estructural requiere previsualizar y confirmar su impacto."
                )
            missing = set(analysis.required_entity_changes) - {
                change.entity_key for change in command.changes
            }
            if missing:
                raise ImpactResolutionRequired(
                    "La operación tiene dependencias sin resolver: "
                    + ", ".join(f"{table}:{entity}" for table, entity in sorted(missing))
                )
            selected_resolution = command.metadata.get("impact_resolution")
            if (
                analysis.resolution_options
                and selected_resolution not in analysis.resolution_options
            ):
                raise ImpactResolutionRequired(
                    "La operación requiere elegir una resolución explícita: "
                    + ", ".join(analysis.resolution_options)
                )
            command = impact.approve(command) if impact is not None else command
        elif impact is not None:
            if impact.fingerprint != (analysis.fingerprint if analysis else impact.fingerprint):
                raise ImpactConfirmationRequired(
                    "El impacto confirmado no coincide con el borrador."
                )
            command = impact.approve(command)

        self._assert_preconditions(command, forward=True)
        candidate = _clone_entities(self._working)
        _apply_state_to(candidate, command, forward=True)
        _validate_changed_references(self._working, candidate, command)
        self._sync_route_state(command, forward=True)
        self._working = candidate
        self._entity_index = None
        self._advance_geometric_generation(command)
        return self.changeset.append(command)

    def _assert_preconditions(self, command: EditorCommand, *, forward: bool) -> None:
        expected = command.before if forward else command.after
        keys = ((command.entity_key, expected),) + tuple(
            (change.entity_key, change.before if forward else change.after)
            for change in command.changes
        )
        for key, value in keys:
            if self.get(key) != value:
                raise ValueError("La precondición del comando no coincide con el borrador actual.")

    def _apply_state(self, command: EditorCommand, *, forward: bool) -> None:
        self._set(command.entity_key, command.after if forward else command.before)
        for change in command.changes:
            self._set(change.entity_key, change.after if forward else change.before)
        self._sync_route_state(command, forward=forward)

    def _sync_route_state(self, command: EditorCommand, *, forward: bool) -> None:
        if (
            command.entity_key[0] != "gtfs_routes"
            or command.before is None
            or command.after is None
        ):
            return
        old_value = command.before.get("route_id")
        new_value = command.after.get("route_id")
        if old_value is None or new_value is None:
            return
        old_id, new_id = str(old_value), str(new_value)
        if old_id == new_id:
            return
        source_id, target_id = (old_id, new_id) if forward else (new_id, old_id)
        state = self._route_states.pop(source_id, RouteWorkspaceState(source_id))
        self._route_states[target_id] = replace(state, route_id=target_id)

    def undo(self) -> EditorCommand:
        command = self.changeset.undo()
        try:
            self._assert_preconditions(command, forward=False)
            self._apply_state(command, forward=False)
        except BaseException:
            self.changeset._cursor += 1
            if self.changeset.history and self.changeset.history[-1].action == "UNDO":
                self.changeset.history.pop()
            raise
        self._advance_geometric_generation(command)
        return command

    def redo(self) -> EditorCommand:
        command = self.changeset.redo()
        try:
            self._assert_preconditions(command, forward=True)
            self._apply_state(command, forward=True)
        except BaseException:
            self.changeset._cursor -= 1
            if self.changeset.history and self.changeset.history[-1].action == "REDO":
                self.changeset.history.pop()
            raise ValueError("No se puede rehacer: el borrador ya no coincide con el comando.")
        self._advance_geometric_generation(command)
        return command

    def discard(self) -> None:
        # _base es inmutable por contrato: los comandos sustituyen payloads y
        # nunca mutan sus diccionarios. Restaurar referencias evita duplicar
        # el feed completo al volver a una revisión limpia.
        self._working = dict(self._base)
        self._entity_index = None
        self._route_states = copy.deepcopy(self._base_route_states)
        self.changeset = ChangeSet(base_revision_id=self.changeset.base_revision_id)
        self._advance_geometric_generation(None)

    def promote_revision(self, revision_id: str) -> None:
        """Publica la working copy como nueva base y abre un ChangeSet vacío."""
        if not revision_id or revision_id == "draft":
            raise ValueError("Una revisión confirmada necesita un identificador válido.")
        self._base = _clone_entities(self._working)
        self._entity_index = None
        self._base_route_states = copy.deepcopy(self._route_states)
        self.changeset = ChangeSet(base_revision_id=revision_id)
        self._advance_geometric_generation(None)

    def _accept_route_workspace_state(self) -> None:
        """Marca como persistido el estado de workspace recuperado de DuckDB."""
        self._base_route_states = copy.deepcopy(self._route_states)

    def _set(self, entity_key: EntityKey, value: Payload | None) -> None:
        self._entity_index = None
        if value is None:
            self._working.pop(entity_key, None)
        else:
            self._working[entity_key] = copy.deepcopy(value)

    def _advance_geometric_generation(self, command: EditorCommand | None) -> None:
        if command is None or any(
            key[0] in {"gtfs_routes", "gtfs_trips", "gtfs_stops", "gtfs_stop_times", "gtfs_shapes"}
            for key in (command.entity_key, *(change.entity_key for change in command.changes))
        ):
            self._geometric_generation += 1


class WorkingCopyStore:
    """Persistencia JSON atómica del borrador y su historial."""

    def save(self, working_copy: WorkingCopy, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 2,
            "original": _json_prepare(_encode_entities(working_copy._original)),
            "base": _json_prepare(_encode_entities(working_copy._base)),
            "working": _json_prepare(_encode_entities(working_copy._working)),
            "changeset": {
                "changeset_id": working_copy.changeset.changeset_id,
                "base_revision_id": working_copy.changeset.base_revision_id,
                "cursor": working_copy.changeset._cursor,
                "commands": [
                    _command_to_json(command) for command in working_copy.changeset.commands
                ],
                "history": _json_prepare(
                    [asdict(event) for event in working_copy.changeset.history]
                ),
            },
            "route_workspace": [asdict(state) for state in working_copy._route_states.values()],
            "base_route_workspace": [
                asdict(state) for state in working_copy._base_route_states.values()
            ],
        }
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
        except BaseException:
            Path(temporary_name).unlink(missing_ok=True)
            raise

    def load(self, path: Path) -> WorkingCopy:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("version") not in {1, 2}:
            raise ValueError("Versión de borrador no compatible.")
        changeset_payload = payload["changeset"]
        result = WorkingCopy(
            _decode_entities(payload["original"]),
            base_revision_id=changeset_payload["base_revision_id"],
            base_entities=_decode_entities(payload.get("base", payload["original"])),
        )
        result._working = _decode_entities(payload["working"])
        result._entity_index = None
        result.changeset = ChangeSet(
            changeset_id=changeset_payload["changeset_id"],
            base_revision_id=changeset_payload["base_revision_id"],
        )
        result.changeset.commands = [
            _command_from_json(item) for item in changeset_payload["commands"]
        ]
        result.changeset.history = [HistoryEvent(**item) for item in changeset_payload["history"]]
        result.changeset._cursor = int(changeset_payload["cursor"])
        result._route_states = {
            str(item["route_id"]): RouteWorkspaceState(**item)
            for item in payload.get("route_workspace", ())
        }
        result._base_route_states = {
            str(item["route_id"]): RouteWorkspaceState(**item)
            for item in payload.get("base_route_workspace", payload.get("route_workspace", ()))
        }
        return result


def _clone_entities(entities: Mapping[EntityKey, Mapping[str, Any]]) -> dict[EntityKey, Payload]:
    result: dict[EntityKey, Payload] = {}
    for key, value in entities.items():
        result[key] = copy.deepcopy(dict(value))
    return result


def _encode_entities(entities: Mapping[EntityKey, Payload]) -> list[dict[str, Any]]:
    return [
        {"table": key[0], "id": key[1], "payload": value} for key, value in sorted(entities.items())
    ]


def _decode_entities(items: list[dict[str, Any]]) -> dict[EntityKey, Payload]:
    result: dict[EntityKey, Payload] = {}
    for item in items:
        key: EntityKey = (str(item["table"]), str(item["id"]))
        result[key] = _json_restore(dict(item["payload"]))
    return result


def _command_to_json(command: EditorCommand) -> dict[str, Any]:
    value = {
        "kind": command.kind.value,
        "entity_key": list(command.entity_key),
        "before": _json_prepare(command.before),
        "after": _json_prepare(command.after),
        "affected_entities": [list(key) for key in command.affected_entities],
        "changes": [
            {
                "entity_key": list(change.entity_key),
                "before": _json_prepare(change.before),
                "after": _json_prepare(change.after),
            }
            for change in command.changes
        ],
        "impact": _json_prepare(command.impact),
        "metadata": _json_prepare(command.metadata),
        "command_id": command.command_id,
        "created_at": command.created_at,
        "sequence": command.sequence,
        "inverse_of": command.inverse_of,
    }
    return value


def _command_from_json(value: Mapping[str, Any]) -> EditorCommand:
    entity_key = value["entity_key"]
    affected_entities = value["affected_entities"]
    return EditorCommand(
        kind=EditorCommandKind(value["kind"]),
        entity_key=(str(entity_key[0]), str(entity_key[1])),
        before=_json_restore(value["before"]),
        after=_json_restore(value["after"]),
        affected_entities=tuple((str(key[0]), str(key[1])) for key in affected_entities),
        changes=tuple(
            EntityChange(
                (str(item["entity_key"][0]), str(item["entity_key"][1])),
                _json_restore(item["before"]),
                _json_restore(item["after"]),
            )
            for item in value.get("changes", ())
        ),
        impact=_json_restore(value.get("impact")),
        metadata=_json_restore(value.get("metadata", {})),
        command_id=value["command_id"],
        created_at=value["created_at"],
        sequence=int(value["sequence"]),
        inverse_of=value.get("inverse_of"),
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _json_prepare(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _json_prepare(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return {"__gtfs_type__": "datetime", "value": value.isoformat()}
    from datetime import date

    if isinstance(value, date):
        return {"__gtfs_type__": "date", "value": value.isoformat()}
    if isinstance(value, Mapping):
        return {str(key): _json_prepare(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_prepare(item) for item in value]
    raise TypeError(f"Valor no serializable en el borrador: {type(value).__name__}")


def _json_restore(value: Any) -> Any:
    if isinstance(value, list):
        return [_json_restore(item) for item in value]
    if isinstance(value, dict):
        marker = value.get("__gtfs_type__")
        if marker == "date":
            from datetime import date

            return date.fromisoformat(str(value["value"]))
        if marker == "datetime":
            return datetime.fromisoformat(str(value["value"]))
        return {key: _json_restore(item) for key, item in value.items()}
    return value


def _normalize_command(command: EditorCommand) -> EditorCommand:
    """Mantiene lexemas GTFS y valores calculados en una única operación."""
    after = _normalize_payload(command.entity_key[0], command.after)
    changes = tuple(
        replace(change, after=_normalize_payload(change.entity_key[0], change.after))
        for change in command.changes
    )
    if after == command.after and changes == command.changes:
        return command
    return replace(command, after=after, changes=changes)


def _normalize_payload(table_name: str, payload: Payload | None) -> Payload | None:
    if payload is None:
        return None
    result = copy.deepcopy(payload)
    pairs: tuple[tuple[str, str], ...] = ()
    if table_name == "gtfs_stop_times":
        pairs = (
            ("arrival_time_lexeme", "arrival_service_seconds"),
            ("departure_time_lexeme", "departure_service_seconds"),
            ("start_pickup_drop_off_window_lexeme", "start_pickup_drop_off_window_service_seconds"),
            ("end_pickup_drop_off_window_lexeme", "end_pickup_drop_off_window_service_seconds"),
        )
    elif table_name == "gtfs_calendar":
        pairs = (("start_date_lexeme", "start_date"), ("end_date_lexeme", "end_date"))
    elif table_name == "gtfs_calendar_dates":
        pairs = (("date_lexeme", "date"),)
    elif table_name in {"gtfs_frequencies", "gtfs_feed_info"}:
        pairs = (
            ("start_time_lexeme", "start_time_service_seconds"),
            ("end_time_lexeme", "end_time_service_seconds"),
            ("feed_start_date_lexeme", "feed_start_date"),
            ("feed_end_date_lexeme", "feed_end_date"),
        )
    for lexeme_field, typed_field in pairs:
        lexeme = result.get(lexeme_field)
        if lexeme is None or lexeme == "":
            continue
        if "time" in lexeme_field or "window" in lexeme_field:
            result[typed_field] = _parse_gtfs_time(lexeme)
        else:
            result[typed_field] = _parse_gtfs_date(lexeme)
    return result


def _parse_gtfs_time(value: object) -> int:
    if not isinstance(value, str):
        raise ValueError("El lexema horario debe ser texto.")
    parts = value.split(":")
    if len(parts) != 3 or any(not part.isdecimal() for part in parts):
        raise ValueError("La hora GTFS debe tener formato HH:MM:SS válido.")
    hours, minutes, seconds = (int(part) for part in parts)
    if minutes > 59 or seconds > 59:
        raise ValueError("La hora GTFS debe tener minutos y segundos válidos.")
    return hours * 3600 + minutes * 60 + seconds


def _parse_gtfs_date(value: object) -> date:
    if not isinstance(value, str) or len(value) != 8 or not value.isdecimal():
        raise ValueError("La fecha GTFS debe tener formato YYYYMMDD válido.")
    try:
        return date.fromisoformat(f"{value[:4]}-{value[4:6]}-{value[6:]}")
    except ValueError as error:
        raise ValueError("La fecha GTFS no es válida.") from error


def _apply_state_to(
    entities: dict[EntityKey, Payload], command: EditorCommand, *, forward: bool
) -> None:
    value = command.after if forward else command.before
    if value is None:
        entities.pop(command.entity_key, None)
    else:
        entities[command.entity_key] = copy.deepcopy(value)
    for change in command.changes:
        value = change.after if forward else change.before
        if value is None:
            entities.pop(change.entity_key, None)
        else:
            entities[change.entity_key] = copy.deepcopy(value)


def _validate_changed_references(
    previous: Mapping[EntityKey, Payload],
    current: Mapping[EntityKey, Payload],
    command: EditorCommand,
) -> None:
    """Evita introducir huérfanos nuevos, sin revalidar silenciosamente el original."""
    touched: dict[EntityKey, tuple[Payload | None, Payload | None]] = {
        command.entity_key: (command.before, command.after)
    }
    touched.update((change.entity_key, (change.before, change.after)) for change in command.changes)
    for key, (before, after) in touched.items():
        if after is not None:
            _validate_changed_row(previous.get(key), current, key, after)
        if before is not None and after is None:
            identity_field = _ENTITY_IDENTITY_FIELDS.get(key[0])
            deleted_value = before.get(identity_field) if identity_field else None
            if deleted_value is not None:
                for source_table, fields in _REFERENCE_FIELDS.items():
                    for field, target_table in fields.items():
                        if target_table != key[0] or _reference_exists(
                            current, target_table, field, deleted_value
                        ):
                            continue
                        _raise_orphan_references(
                            current, key[0], deleted_value, source_table, field
                        )


def _validate_changed_row(
    before: Payload | None,
    current: Mapping[EntityKey, Payload],
    key: EntityKey,
    after: Payload,
) -> None:
    _validate_unique_identity(current, key, before, after)
    for field_name, target_table in _REFERENCE_FIELDS.get(key[0], {}).items():
        value = after.get(field_name)
        if value is None:
            continue
        if before is not None and before.get(field_name) == value:
            continue
        if not _reference_exists(current, target_table, field_name, value):
            raise ValueError(
                f"La referencia {key[0]}.{field_name}={value!r} no existe en el borrador."
            )


def _validate_unique_identity(
    current: Mapping[EntityKey, Payload],
    key: EntityKey,
    before: Payload | None,
    after: Payload,
) -> None:
    identity_field = _ENTITY_IDENTITY_FIELDS.get(key[0])
    if identity_field is not None:
        identity = after.get(identity_field)
        identity_changed = before is None or before.get(identity_field) != identity
        if (
            identity_changed
            and identity is not None
            and any(
                other_key != key
                and other_key[0] == key[0]
                and other_payload.get(identity_field) == identity
                for other_key, other_payload in current.items()
            )
        ):
            raise ValueError(f"El identificador {key[0]}.{identity_field}={identity!r} ya existe.")
    if key[0] == "gtfs_calendar_dates":
        service_id, date_value = after.get("service_id"), after.get("date")
        identity_changed = before is None or (
            before.get("service_id") != service_id or before.get("date") != date_value
        )
        if (
            identity_changed
            and service_id is not None
            and date_value is not None
            and any(
                other_key != key
                and other_key[0] == key[0]
                and other_payload.get("service_id") == service_id
                and other_payload.get("date") == date_value
                for other_key, other_payload in current.items()
            )
        ):
            raise ValueError("No puede haber dos excepciones para el mismo servicio y fecha.")
    if key[0] == "gtfs_stop_times":
        trip_id, sequence = after.get("trip_id"), after.get("stop_sequence")
        identity_changed = before is None or (
            before.get("trip_id") != trip_id or before.get("stop_sequence") != sequence
        )
        if (
            identity_changed
            and trip_id is not None
            and sequence is not None
            and any(
                other_key != key
                and other_key[0] == key[0]
                and other_payload.get("trip_id") == trip_id
                and other_payload.get("stop_sequence") == sequence
                for other_key, other_payload in current.items()
            )
        ):
            raise ValueError("No puede haber dos paradas con la misma secuencia en un viaje.")


def _reference_exists(
    entities: Mapping[EntityKey, Payload], target_table: str, field: str, value: object
) -> bool:
    target_field = {
        "gtfs_agency": "agency_id",
        "gtfs_stops": "stop_id",
        "gtfs_routes": "route_id",
        "gtfs_trips": "trip_id",
        "gtfs_shapes": "shape_id",
        "gtfs_calendar": "service_id",
        "gtfs_calendar_dates": "service_id",
    }.get(target_table)
    if target_field is None:
        return True
    if target_table in {"gtfs_calendar", "gtfs_calendar_dates"}:
        return any(
            key[0] in {"gtfs_calendar", "gtfs_calendar_dates"}
            and payload.get("service_id") == value
            for key, payload in entities.items()
        )
    return any(
        key[0] == target_table and payload.get(target_field) == value
        for key, payload in entities.items()
    )


def _raise_orphan_references(
    entities: Mapping[EntityKey, Payload],
    deleted_table: str,
    value: object,
    source_table: str,
    field: str,
) -> None:
    for key, payload in entities.items():
        reference_fields = _REFERENCE_FIELDS.get(key[0], {})
        if any(
            reference_field == field
            and target_table == deleted_table
            and payload.get(reference_field) == value
            for reference_field, target_table in reference_fields.items()
        ):
            raise ValueError(
                f"No se puede eliminar {deleted_table}={value!r}: "
                f"queda {key[0]}.{field} sin resolver."
            )


_REFERENCE_FIELDS: dict[str, dict[str, str]] = {
    "gtfs_routes": {"agency_id": "gtfs_agency"},
    "gtfs_trips": {
        "route_id": "gtfs_routes",
        "service_id": "gtfs_calendar",
        "shape_id": "gtfs_shapes",
    },
    "gtfs_stop_times": {"trip_id": "gtfs_trips", "stop_id": "gtfs_stops"},
    "gtfs_frequencies": {"trip_id": "gtfs_trips"},
    "gtfs_transfers": {
        "from_stop_id": "gtfs_stops",
        "to_stop_id": "gtfs_stops",
        "from_route_id": "gtfs_routes",
        "to_route_id": "gtfs_routes",
        "from_trip_id": "gtfs_trips",
        "to_trip_id": "gtfs_trips",
    },
    "gtfs_attributions": {
        "agency_id": "gtfs_agency",
        "route_id": "gtfs_routes",
        "trip_id": "gtfs_trips",
    },
}

_ENTITY_IDENTITY_FIELDS = {
    "gtfs_agency": "agency_id",
    "gtfs_stops": "stop_id",
    "gtfs_routes": "route_id",
    "gtfs_trips": "trip_id",
    "gtfs_calendar": "service_id",
    "gtfs_attributions": "attribution_id",
}


def _impact_from_payload(value: dict[str, Any] | None) -> ImpactAnalysis | None:
    if value is None:
        return None
    try:
        return ImpactAnalysis(
            command_kind=EditorCommandKind(str(value["command_kind"])),
            entity_key=(str(value["entity_key"][0]), str(value["entity_key"][1])),
            affected_entities=tuple(
                (str(key[0]), str(key[1])) for key in value["affected_entities"]
            ),
            affected_tables=tuple(str(item) for item in value["affected_tables"]),
            relationships=tuple(str(item) for item in value["relationships"]),
            required_entity_changes=tuple(
                (str(key[0]), str(key[1])) for key in value.get("required_entity_changes", ())
            ),
            resolution_options=tuple(str(item) for item in value.get("resolution_options", ())),
            blockers=tuple(str(item) for item in value.get("blockers", ())),
            fingerprint=str(value["fingerprint"]),
        )
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise ImpactConfirmationRequired(
            "El impacto persistido del comando no es válido."
        ) from error


def _reassigned_payload(
    payload: Payload,
    command: EditorCommand,
    resolution: str,
    replacement_id: str,
) -> Payload | None:
    before = command.before or {}
    field_groups: tuple[tuple[str, ...], ...]
    if "agency" in resolution or resolution.startswith("reassign_routes"):
        field_groups = (("agency_id",),)
    elif "stop_time" in resolution:
        field_groups = (("trip_id", "from_trip_id", "to_trip_id"),)
    elif "stop" in resolution:
        field_groups = (("stop_id", "from_stop_id", "to_stop_id"),)
    elif "route" in resolution or resolution == "reassign_trips":
        field_groups = (("route_id", "from_route_id", "to_route_id"),)
    elif "service" in resolution:
        field_groups = (("service_id",),)
    elif "trip" in resolution:
        field_groups = (("trip_id", "from_trip_id", "to_trip_id"),)
    else:
        return None
    old_values = {
        field: before.get(field)
        for group in field_groups
        for field in group
        if before.get(field) is not None
    }
    updated = copy.deepcopy(payload)
    changed = False
    for field_name, old_value in old_values.items():
        if field_name in updated and updated[field_name] == old_value:
            updated[field_name] = replacement_id
            changed = True
    return updated if changed else None
