"""Contrato restringido entre la página local del mapa y Qt WebChannel."""

from gtfs_explorer.presentation.map_bridge.protocol import (
    MAX_MESSAGE_BYTES,
    MAX_PENDING_COMMANDS,
    PROTOCOL_VERSION,
    MapBridge,
    MapBridgeEvent,
    MapFitBounds,
    MapNavigation,
)

__all__ = [
    "MAX_MESSAGE_BYTES",
    "MAX_PENDING_COMMANDS",
    "PROTOCOL_VERSION",
    "MapBridge",
    "MapBridgeEvent",
    "MapFitBounds",
    "MapNavigation",
]
