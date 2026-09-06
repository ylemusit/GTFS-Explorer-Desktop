"""Contrato restringido entre la página local del mapa y Qt WebChannel."""

from gtfs_explorer.presentation.map_bridge.protocol import (
    EDIT_PROTOCOL_VERSION,
    MAX_MESSAGE_BYTES,
    MAX_PENDING_COMMANDS,
    PROTOCOL_VERSION,
    MapBridge,
    MapBridgeEvent,
    MapEditGesture,
    MapFitBounds,
    MapNavigation,
    parse_edit_event,
)

__all__ = [
    "MAX_MESSAGE_BYTES",
    "MAX_PENDING_COMMANDS",
    "EDIT_PROTOCOL_VERSION",
    "PROTOCOL_VERSION",
    "MapBridge",
    "MapBridgeEvent",
    "MapEditGesture",
    "MapFitBounds",
    "MapNavigation",
    "parse_edit_event",
]
