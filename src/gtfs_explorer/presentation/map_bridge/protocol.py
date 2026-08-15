"""DTOs y validación del protocolo JSON v1 del mapa.

La página recibe únicamente comandos de cámara y notifica eventos de mapa. No
hay métodos que acepten rutas, SQL o instrucciones de acceso a datos.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Final, Literal

from PySide6.QtCore import QObject, Signal, Slot

PROTOCOL_VERSION: Final = 1
MAX_MESSAGE_BYTES: Final = 16 * 1024
MAX_PENDING_COMMANDS: Final = 32
_EVENT_NAMES: Final = frozenset({"mapReady", "featureClicked", "mapError", "viewportChanged"})


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
class MapBridgeEvent:
    """Evento validado emitido por la página local del mapa."""

    event: Literal["mapReady", "featureClicked", "mapError", "viewportChanged"]
    sequence: int
    payload: dict[str, object]


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


def serialize_navigation(command: MapNavigation) -> str:
    """Serializa el único comando v1 permitido hacia la página del mapa."""
    serialized = json.dumps(
        {
            "version": PROTOCOL_VERSION,
            "type": "command",
            "command": "navigate",
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
    protocol_error = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._ready = False
        self._last_sequence = -1
        self._pending: deque[MapNavigation] = deque(maxlen=MAX_PENDING_COMMANDS)

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def navigate(self, command: MapNavigation) -> DispatchStatus:
        """Encola la navegación hasta recibir `mapReady`, con límite fijo."""
        if self._ready:
            self.command_available.emit(serialize_navigation(command))
            return DispatchStatus.SENT
        if len(self._pending) == MAX_PENDING_COMMANDS:
            self.protocol_error.emit("La cola de navegación del mapa está llena.")
            return DispatchStatus.REJECTED
        self._pending.append(command)
        return DispatchStatus.QUEUED

    @Slot(str)  # type: ignore[arg-type]
    def receive(self, serialized: str) -> None:
        """Punto de entrada WebChannel: rechaza entradas inválidas sin propagar errores."""
        try:
            event = parse_event(serialized)
            self._accept_event(event)
        except BridgeProtocolError as error:
            self.protocol_error.emit(str(error))

    def _accept_event(self, event: MapBridgeEvent) -> None:
        if event.sequence <= self._last_sequence:
            raise BridgeProtocolError("Evento fuera de orden.")
        if event.event == "featureClicked" and not self._ready:
            raise BridgeProtocolError("Evento recibido antes de mapReady.")
        if event.event == "mapReady" and self._ready:
            raise BridgeProtocolError("mapReady duplicado.")
        self._last_sequence = event.sequence
        if event.event == "mapReady":
            self._ready = True
            while self._pending:
                self.command_available.emit(serialize_navigation(self._pending.popleft()))
        self.event_received.emit(event)
