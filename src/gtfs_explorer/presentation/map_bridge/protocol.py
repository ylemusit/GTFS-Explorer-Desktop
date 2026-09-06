"""DTOs y validación del protocolo JSON v1 del mapa.

La página recibe únicamente comandos de cámara y notifica eventos de mapa. No
hay métodos que acepten rutas, SQL o instrucciones de acceso a datos.
"""

from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Final, Literal

from PySide6.QtCore import QObject, Signal, Slot

PROTOCOL_VERSION: Final = 1
EDIT_PROTOCOL_VERSION: Final = 2
MAX_MESSAGE_BYTES: Final = 16 * 1024
MAX_PENDING_COMMANDS: Final = 32
_EVENT_NAMES: Final = frozenset(
    {"mapReady", "featureClicked", "mapError", "viewportChanged", "performanceTimings"}
)
_EDIT_ACTIONS: Final = frozenset(
    {
        "select",
        "drag_start",
        "drag_preview",
        "drag_end",
        "add_vertex",
        "insert_vertex",
        "move_vertex",
        "delete_vertex",
        "reorder_vertex",
        "reorder_stop",
    }
)
_EDIT_ENTITY_TYPES: Final = frozenset({"stop", "shape_vertex", "shape_segment"})


class BridgeProtocolError(ValueError):
    """El mensaje no cumple el contrato público del bridge."""


class DispatchStatus(str, Enum):
    SENT = "sent"
    QUEUED = "queued"
    REJECTED = "rejected"


@dataclass(frozen=True)
class MapNavigation:
    """Comando de cámara; las coordenadas son WGS84 longitud/latitud."""

    longitude: float
    latitude: float
    zoom: float

    def __post_init__(self) -> None:
        if not (-180.0 <= self.longitude <= 180.0):
            raise BridgeProtocolError("La longitud debe estar entre -180 y 180.")
        if not (-90.0 <= self.latitude <= 90.0):
            raise BridgeProtocolError("La latitud debe estar entre -90 y 90.")
        if not (0.0 <= self.zoom <= 24.0):
            raise BridgeProtocolError("El zoom debe estar entre 0 y 24.")


@dataclass(frozen=True)
class MapFitBounds:
    """Extensión WGS84 que debe encuadrar MapLibre."""

    west: float
    south: float
    east: float
    north: float

    def __post_init__(self) -> None:
        if not (-180 <= self.west <= self.east <= 180 and -90 <= self.south <= self.north <= 90):
            raise BridgeProtocolError("Los límites geográficos no son válidos.")


@dataclass(frozen=True)
class MapBridgeEvent:
    """Evento validado emitido por la página local del mapa."""

    event: Literal[
        "mapReady", "featureClicked", "mapError", "viewportChanged", "performanceTimings"
    ]
    sequence: int
    payload: dict[str, object]


@dataclass(frozen=True)
class MapEditGesture:
    """Gesto declarativo v2; nunca contiene SQL, rutas ni instrucciones ejecutables."""

    action: str
    entity_type: str
    entity_id: str
    sequence: int
    route_id: str | None = None
    longitude: float | None = None
    latitude: float | None = None
    position: int | None = None
    shape_id: str | None = None
    anchor_id: str | None = None


def _message_size(value: str) -> None:
    if len(value.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise BridgeProtocolError(f"El mensaje excede {MAX_MESSAGE_BYTES} bytes.")


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BridgeProtocolError(f"{name} debe ser un objeto JSON.")
    return value


def _integer(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise BridgeProtocolError(f"{name} debe ser un entero no negativo.")
    return value


def parse_event(serialized: str) -> MapBridgeEvent:
    """Deserializa un evento v1 sin aceptar campos operativos implícitos."""
    if not isinstance(serialized, str):
        raise BridgeProtocolError("El mensaje debe ser texto JSON.")
    _message_size(serialized)
    try:
        raw = _object(json.loads(serialized), "El mensaje")
    except json.JSONDecodeError as error:
        raise BridgeProtocolError("El mensaje no es JSON válido.") from error
    if raw.get("version") != PROTOCOL_VERSION or raw.get("type") != "event":
        raise BridgeProtocolError("Versión o tipo de mensaje no admitido.")
    event = raw.get("event")
    if event not in _EVENT_NAMES:
        raise BridgeProtocolError("Evento no admitido.")
    payload = _object(raw.get("payload"), "payload")
    return MapBridgeEvent(event, _integer(raw.get("sequence"), "sequence"), payload)


def parse_edit_event(serialized: str) -> MapEditGesture:
    """Valida un gesto v2 acotado antes de entregarlo al caso de uso."""
    if not isinstance(serialized, str):
        raise BridgeProtocolError("El mensaje debe ser texto JSON.")
    _message_size(serialized)
    try:
        raw = _object(json.loads(serialized), "El mensaje")
    except json.JSONDecodeError as error:
        raise BridgeProtocolError("El mensaje no es JSON válido.") from error
    if raw.get("version") != EDIT_PROTOCOL_VERSION or raw.get("type") != "event":
        raise BridgeProtocolError("Versión o tipo de gesto no admitido.")
    if raw.get("event") != "editGesture":
        raise BridgeProtocolError("Evento de edición no admitido.")
    payload = _object(raw.get("payload"), "payload")
    allowed = {
        "action",
        "entity_type",
        "entity_id",
        "route_id",
        "longitude",
        "latitude",
        "position",
        "shape_id",
        "anchor_id",
    }
    if set(payload) - allowed:
        raise BridgeProtocolError("El gesto contiene campos operativos no admitidos.")
    action = payload.get("action")
    entity_type = payload.get("entity_type")
    entity_id = payload.get("entity_id")
    if action not in _EDIT_ACTIONS or entity_type not in _EDIT_ENTITY_TYPES:
        raise BridgeProtocolError("El gesto o tipo de entidad no está permitido.")
    if not isinstance(entity_id, str) or not entity_id or len(entity_id) > 256:
        raise BridgeProtocolError("El identificador de entidad no es válido.")
    route_id = payload.get("route_id")
    if route_id is not None and (
        not isinstance(route_id, str) or not route_id or len(route_id) > 256
    ):
        raise BridgeProtocolError("El identificador de ruta no es válido.")
    longitude, latitude = payload.get("longitude"), payload.get("latitude")
    position = payload.get("position")
    shape_id = payload.get("shape_id")
    anchor_id = payload.get("anchor_id")
    if position is not None and (
        not isinstance(position, int) or isinstance(position, bool) or position < 0
    ):
        raise BridgeProtocolError("La posición del gesto no es un entero no negativo.")
    for identifier, name in ((shape_id, "shape_id"), (anchor_id, "anchor_id")):
        if identifier is not None and (
            not isinstance(identifier, str) or not identifier or len(identifier) > 256
        ):
            raise BridgeProtocolError(f"El identificador {name} no es válido.")
    if (longitude is None) != (latitude is None):
        raise BridgeProtocolError("La coordenada del gesto debe incluir longitud y latitud.")
    if longitude is not None:
        if not isinstance(longitude, (int, float)) or isinstance(longitude, bool):
            raise BridgeProtocolError("La longitud del gesto no es numérica.")
        if not isinstance(latitude, (int, float)) or isinstance(latitude, bool):
            raise BridgeProtocolError("La latitud del gesto no es numérica.")
        if (
            not _finite_number(longitude)
            or not _finite_number(latitude)
            or not -180.0 <= float(longitude) <= 180.0
            or not -90.0 <= float(latitude) <= 90.0
        ):
            raise BridgeProtocolError("La coordenada del gesto queda fuera de WGS84.")
    return MapEditGesture(
        str(action),
        str(entity_type),
        entity_id,
        _integer(raw.get("sequence"), "sequence"),
        route_id,
        None if longitude is None else float(longitude),
        None if latitude is None else float(latitude),
        position,
        shape_id,
        anchor_id,
    )


def _finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def serialize_navigation(command: MapNavigation | MapFitBounds) -> str:
    """Serializa el único comando v1 permitido hacia la página del mapa."""
    serialized = json.dumps(
        {
            "version": PROTOCOL_VERSION,
            "type": "command",
            "command": "navigate" if isinstance(command, MapNavigation) else "fitBounds",
            "payload": asdict(command),
        },
        separators=(",", ":"),
        allow_nan=False,
    )
    _message_size(serialized)
    return serialized


class MapBridge(QObject):
    """Endpoint Qt sin privilegios para el WebChannel del mapa local."""

    command_available = Signal(str)
    event_received = Signal(object)
    edit_event_received = Signal(object)
    protocol_error = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._ready = False
        self._last_sequence = -1
        self._last_edit_sequence = -1
        self._pending: deque[MapNavigation | MapFitBounds] = deque(maxlen=MAX_PENDING_COMMANDS)

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def navigate(self, command: MapNavigation | MapFitBounds) -> DispatchStatus:
        """Encola la navegación hasta recibir `mapReady`, con límite fijo."""
        if self._ready:
            self.command_available.emit(serialize_navigation(command))
            return DispatchStatus.SENT
        if len(self._pending) == MAX_PENDING_COMMANDS:
            self.protocol_error.emit("La cola de navegación del mapa está llena.")
            return DispatchStatus.REJECTED
        self._pending.append(command)
        return DispatchStatus.QUEUED

    @Slot(str)
    def receive(self, serialized: str) -> None:
        """Punto de entrada WebChannel: rechaza entradas inválidas sin propagar errores."""
        try:
            event = parse_event(serialized)
            self._accept_event(event)
        except BridgeProtocolError as error:
            self.protocol_error.emit(str(error))

    @Slot(str)
    def receive_v2(self, serialized: str) -> None:
        """Punto de entrada separado para gestos de edición declarativos v2."""
        try:
            gesture = parse_edit_event(serialized)
            if not self._ready:
                raise BridgeProtocolError("Gesto recibido antes de mapReady.")
            if gesture.sequence <= self._last_edit_sequence:
                raise BridgeProtocolError("Gesto de edición fuera de orden.")
            self._last_edit_sequence = gesture.sequence
            self.edit_event_received.emit(gesture)
        except BridgeProtocolError as error:
            self.protocol_error.emit(str(error))

    def _accept_event(self, event: MapBridgeEvent) -> None:
        if event.sequence <= self._last_sequence:
            raise BridgeProtocolError("Evento fuera de orden.")
        if (
            event.event in {"featureClicked", "viewportChanged", "performanceTimings"}
            and not self._ready
        ):
            raise BridgeProtocolError("Evento recibido antes de mapReady.")
        if event.event == "mapReady" and self._ready:
            raise BridgeProtocolError("mapReady duplicado.")
        self._last_sequence = event.sequence
        if event.event == "mapReady":
            self._ready = True
            while self._pending:
                self.command_available.emit(serialize_navigation(self._pending.popleft()))
        self.event_received.emit(event)
