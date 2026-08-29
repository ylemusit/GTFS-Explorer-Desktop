"""Catálogo local de tipos de ruta GTFS core y extendidos conocidos."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class RouteTypeKind(StrEnum):
    """Origen semántico del código mostrado para una ruta."""

    CORE = "core"
    EXTENDED = "extended"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RouteTypeInfo:
    """Descripción local de un `route_type` sin sustituir su valor GTFS."""

    code: int
    name: str
    kind: RouteTypeKind


CORE_ROUTE_TYPES: Final[Mapping[int, str]] = {
    0: "Tram, Streetcar, Light rail",
    1: "Subway, Metro",
    2: "Rail",
    3: "Bus",
    4: "Ferry",
    5: "Cable tram",
    6: "Aerial lift",
    7: "Funicular",
    11: "Trolleybus",
    12: "Monorail",
}

# Catálogo estático: no se consulta Internet durante la importación ni desde la UI.
# La lista corresponde a la tabla Extended GTFS Route Types de Google Transit.
EXTENDED_ROUTE_TYPES: Final[Mapping[int, str]] = {
    100: "Railway Service",
    101: "High Speed Rail Service",
    102: "Long Distance Trains",
    103: "Inter Regional Rail Service",
    104: "Car Transport Rail Service",
    105: "Sleeper Rail Service",
    106: "Regional Rail Service",
    107: "Tourist Railway Service",
    108: "Rail Shuttle (Within Complex)",
    109: "Suburban Railway",
    110: "Replacement Rail Service",
    111: "Special Rail Service",
    112: "Lorry Transport Rail Service",
    113: "All Rail Services",
    114: "Cross-Country Rail Service",
    115: "Vehicle Transport Rail Service",
    116: "Rack and Pinion Railway",
    117: "Additional Rail Service",
    200: "Coach Service",
    201: "International Coach Service",
    202: "National Coach Service",
    203: "Shuttle Coach Service",
    204: "Regional Coach Service",
    205: "Special Coach Service",
    206: "Sightseeing Coach Service",
    207: "Tourist Coach Service",
    208: "Commuter Coach Service",
    209: "All Coach Services",
    400: "Urban Railway Service",
    401: "Metro Service",
    402: "Underground Service",
    403: "Urban Railway Service",
    404: "All Urban Railway Services",
    405: "Monorail",
    700: "Bus Service",
    701: "Regional Bus Service",
    702: "Express Bus Service",
    703: "Stopping Bus Service",
    704: "Local Bus Service",
    705: "Night Bus Service",
    706: "Post Bus Service",
    707: "Special Needs Bus",
    708: "Mobility Bus Service",
    709: "Mobility Bus for Registered Disabled",
    710: "Sightseeing Bus",
    711: "Shuttle Bus",
    712: "School Bus",
    713: "School and Public Service Bus",
    714: "Rail Replacement Bus Service",
    715: "Demand and Response Bus Service",
    716: "All Bus Services",
    800: "Trolleybus Service",
    900: "Tram Service",
    901: "City Tram Service",
    902: "Local Tram Service",
    903: "Regional Tram Service",
    904: "Sightseeing Tram Service",
    905: "Shuttle Tram Service",
    906: "All Tram Services",
    1000: "Water Transport Service",
    1100: "Air Service",
    1200: "Ferry Service",
    1300: "Aerial Lift Service",
    1301: "Telecabin Service",
    1302: "Cable Car Service",
    1303: "Elevator Service",
    1304: "Chair Lift Service",
    1305: "Drag Lift Service",
    1306: "Small Telecabin Service",
    1307: "All Telecabin Services",
    1400: "Funicular Service",
    1500: "Taxi Service",
    1501: "Communal Taxi Service",
    1502: "Water Taxi Service",
    1503: "Rail Taxi Service",
    1504: "Bike Taxi Service",
    1505: "Licensed Taxi Service",
    1506: "Private Hire Service Vehicle",
    1507: "All Taxi Services",
    1700: "Miscellaneous Service",
    1702: "Horse-drawn Carriage",
}

_ROUTE_TYPE_INTEGER = re.compile(r"[0-9]+")


def classify_route_type(code: int | None) -> RouteTypeInfo | None:
    """Clasifica un código tipado manteniendo visibles core, extensión o desconocido."""
    if code is None:
        return None
    if code in CORE_ROUTE_TYPES:
        return RouteTypeInfo(code, CORE_ROUTE_TYPES[code], RouteTypeKind.CORE)
    if code in EXTENDED_ROUTE_TYPES:
        return RouteTypeInfo(code, EXTENDED_ROUTE_TYPES[code], RouteTypeKind.EXTENDED)
    return RouteTypeInfo(code, "Unknown route type", RouteTypeKind.UNKNOWN)


def is_known_extended_route_type(value: str) -> bool:
    """Indica si el lexema conserva exactamente un código extendido conocido."""
    if _ROUTE_TYPE_INTEGER.fullmatch(value) is None:
        return False
    code = int(value)
    return str(code) == value and code in EXTENDED_ROUTE_TYPES


def format_route_type(code: int | None) -> str:
    """Genera una etiqueta explicativa que siempre conserva el número GTFS."""
    info = classify_route_type(code)
    if info is None:
        return "route_type: sin declarar"
    if info.kind is RouteTypeKind.CORE:
        return f"route_type {info.code} — {info.name} (GTFS core)"
    if info.kind is RouteTypeKind.EXTENDED:
        return f"route_type {info.code} — {info.name} (Google Transit extended)"
    return f"route_type {info.code} — {info.name}"
