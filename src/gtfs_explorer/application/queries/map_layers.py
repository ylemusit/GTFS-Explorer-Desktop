"""Adaptador de geometría de viaje a capas GeoJSON locales."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Collection, Mapping
from dataclasses import dataclass, replace
from hashlib import sha256
from math import atan2, cos, hypot, isfinite, radians
from typing import cast

from gtfs_explorer.domain.changesets import (
    RouteWorkspaceState,
    WorkingCopy,
    WorkingCopyEntityIndex,
)
from gtfs_explorer.domain.geometry import Coordinate, MapStop, TripShapeGeometry
from gtfs_explorer.domain.stops import StopCard
from gtfs_explorer.performance_gate import count_current, current_generation, mark_current

_FALLBACK_COLOR = "#2563eb"
_ROUTE_FALLBACK_PALETTE = (
    "#2563EB",  # blue
    "#DC2626",  # red
    "#16A34A",  # green
    "#D97706",  # amber
    "#7C3AED",  # violet
    "#0891B2",  # cyan
    "#C026D3",  # fuchsia
    "#4D7C0F",  # lime
    "#EA580C",  # orange
    "#BE123C",  # rose
    "#0F766E",  # teal
    "#4338CA",  # indigo
)
MAX_RENDERED_STOPS = 2_000
MAX_RENDERED_SHAPE_POINTS = 4_000
SHARED_CORRIDOR_TOLERANCE_METERS = 35.0
SHARED_CORRIDOR_LANE_SPACING_PX = 8.0
MIN_ROUTE_LINE_WIDTH_PX = 2.5
MAX_ROUTE_LINE_WIDTH_PX = 7.5
_ROUTE_CACHE_LIMIT = 128
_VISIBLE_SET_CACHE_LIMIT = 8

# Las consultas son puras respecto de la working copy. Estos LRU se mantienen
# deliberadamente pequeños: guardan geometría ya preparada, no snapshots GTFS.
_ROUTE_GEOMETRY_CACHE: OrderedDict[tuple[int, int, str], MapLayerPayload] = OrderedDict()
_VISIBLE_SET_CACHE: OrderedDict[tuple[int, int, tuple[str, ...]], MapLayerPayload] = OrderedDict()


@dataclass(frozen=True)
class MapLayerPayload:
    """Colecciones RFC 7946 listas para una página local, sin SQL ni HTML."""

    shapes: dict[str, object]
    stops: dict[str, object]
    shape_points: dict[str, object] | None = None


@dataclass(frozen=True)
class MapViewport:
    """Ventana WGS84 solicitada por el mapa; sus límites siempre son finitos."""

    west: float
    south: float
    east: float
    north: float
    zoom: float


def sanitize_route_color(value: str | None) -> str:
    """Normaliza el color GTFS RGB o usa un valor de contraste seguro."""
    if not isinstance(value, str):
        return _FALLBACK_COLOR
    normalized = value.strip().removeprefix("#")
    if len(normalized) != 6 or any(
        character not in "0123456789abcdefABCDEF" for character in normalized
    ):
        return _FALLBACK_COLOR
    return f"#{normalized.upper()}"


def contrast_halo_color(value: str | None) -> str:
    """Elige un halo blanco/negro mediante luminancia relativa perceptual."""
    color = sanitize_route_color(value)
    channels = [int(color[offset : offset + 2], 16) / 255 for offset in (1, 3, 5)]
    linear = [
        channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    luminance = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    return "#111827" if luminance >= 0.42 else "#FFFFFF"


def readable_foreground_color(value: str | None) -> str:
    """Devuelve texto oscuro o blanco con el mayor contraste sobre la ruta."""
    color = sanitize_route_color(value)
    channels = [int(color[offset : offset + 2], 16) / 255 for offset in (1, 3, 5)]
    linear = [
        channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    luminance = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    contrast_black = (luminance + 0.05) / 0.05
    contrast_white = 1.05 / (luminance + 0.05)
    return "#111827" if contrast_black >= contrast_white else "#FFFFFF"


def route_color(route_id: str, value: str | None) -> str:
    """Color estable: primero el color GTFS y después un fallback por route_id."""
    if isinstance(value, str):
        normalized = value.strip().removeprefix("#")
        if len(normalized) == 6 and all(c in "0123456789abcdefABCDEF" for c in normalized):
            return f"#{normalized.upper()}"
    digest = sha256(route_id.encode("utf-8")).hexdigest()[:6].upper()
    return f"#{digest}"


def route_colors(route_values: Mapping[str, str | None]) -> dict[str, str]:
    """Resuelve colores de ruta estables y distinguibles para una working copy.

    Un ``route_color`` GTFS válido se conserva cuando identifica de forma única
    una ruta. Los colores GTFS repetidos pierden esa identidad dentro del
    conjunto y pasan, igual que los ausentes o inválidos, a una paleta amplia.
    La asignación se ordena por hash de ``route_id``: no depende del orden de
    consulta ni de la selección actual y se mantiene al refrescar o reabrir.
    """
    normalized = {route_id: _valid_route_color(value) for route_id, value in route_values.items()}
    counts: dict[str, int] = {}
    for color in normalized.values():
        if color is not None:
            counts[color] = counts.get(color, 0) + 1
    result: dict[str, str] = {}
    for route_id in sorted(
        route_values,
        key=lambda item: (sha256(item.encode("utf-8")).hexdigest(), item),
    ):
        color = normalized[route_id]
        if color is not None and counts[color] == 1 and _is_distinguishable(color, result.values()):
            result[route_id] = color
    used = set(result.values())
    fallback_ids = sorted(
        (route_id for route_id in route_values if route_id not in result),
        key=lambda route_id: (sha256(route_id.encode("utf-8")).hexdigest(), route_id),
    )
    for route_id in fallback_ids:
        start = int(sha256(route_id.encode("utf-8")).hexdigest()[:8], 16) % len(
            _ROUTE_FALLBACK_PALETTE
        )
        color = next(
            (
                _ROUTE_FALLBACK_PALETTE[(start + offset) % len(_ROUTE_FALLBACK_PALETTE)]
                for offset in range(len(_ROUTE_FALLBACK_PALETTE))
                if (
                    _ROUTE_FALLBACK_PALETTE[(start + offset) % len(_ROUTE_FALLBACK_PALETTE)]
                    not in used
                    and _is_distinguishable(
                        _ROUTE_FALLBACK_PALETTE[(start + offset) % len(_ROUTE_FALLBACK_PALETTE)],
                        result.values(),
                    )
                )
            ),
            route_color(route_id, None),
        )
        result[route_id] = color
        used.add(color)
    return result


def _valid_route_color(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().removeprefix("#")
    if len(normalized) != 6 or any(c not in "0123456789abcdefABCDEF" for c in normalized):
        return None
    return f"#{normalized.upper()}"


def _is_distinguishable(candidate: str, existing: Collection[str]) -> bool:
    """Evita conservar tonos GTFS válidos pero prácticamente indistinguibles."""
    red, green, blue = (int(candidate[position : position + 2], 16) for position in (1, 3, 5))
    return all(
        abs(red - int(color[1:3], 16))
        + abs(green - int(color[3:5], 16))
        + abs(blue - int(color[5:7], 16))
        >= 96
        for color in existing
    )


def map_layers_for_trip(
    geometry: TripShapeGeometry, popup_by_stop: dict[str, dict[str, object]] | None = None
) -> MapLayerPayload:
    """Construye capas sin fabricar una línea cuando el shape está ausente."""
    color = sanitize_route_color(geometry.route_color)
    shape_features: list[dict[str, object]] = []
    if len(geometry.coordinates) >= 2:
        shape_features.append(
            {
                "type": "Feature",
                "properties": {
                    "trip_id": geometry.trip_id,
                    "route_id": geometry.route_id,
                    "shape_id": geometry.shape_id,
                    "color": color,
                    "halo_color": contrast_halo_color(color),
                    "line_width": MAX_ROUTE_LINE_WIDTH_PX,
                    "lane_offset": 0.0,
                    "shared_route_count": 1,
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [point.longitude, point.latitude] for point in geometry.coordinates
                    ],
                },
            }
        )
    valid_stops = tuple(geometry.stops)
    stop_features: list[dict[str, object]] = [
        {
            "type": "Feature",
            "properties": {
                "id": stop.stop_id,
                "route_id": geometry.route_id,
                "name": stop.name or "Sin nombre",
                "sequence": stop.stop_sequence,
                "endpoint": (
                    "origin"
                    if index == 0
                    else "destination"
                    if index == len(valid_stops) - 1
                    else None
                ),
                "color": color,
                "popup": (popup_by_stop or {}).get(stop.stop_id, {}),
            },
            "geometry": {
                "type": "Point",
                "coordinates": [stop.coordinate.longitude, stop.coordinate.latitude],
            },
        }
        for index, stop in enumerate(valid_stops)
    ]
    return MapLayerPayload(_collection(shape_features), _collection(stop_features))


def map_layers_for_working_copy(
    working_copy: WorkingCopy,
    trip_id: str,
    popup_by_stop: dict[str, dict[str, object]] | None = None,
    index: WorkingCopyEntityIndex | None = None,
    include_shape_points: bool = False,
    segment: tuple[str, str] | None = None,
) -> MapLayerPayload:
    """Construye el overlay desde la revisión editable, nunca desde ``gtfs_*``.

    La consulta conserva el contrato visual de ``map_layers_for_trip`` y solo
    usa entidades relacionadas con el viaje solicitado. Las filas inválidas se
    omiten del dibujo y quedan para el motor de validación del borrador.
    """
    entity_index = index or working_copy.entity_index
    trip = entity_index.trips_by_id.get(trip_id)
    if trip is None:
        return MapLayerPayload(_collection([]), _collection([]), _collection([]))
    route_id = _text(trip.get("route_id"))
    route_state = working_copy.route_state(route_id or "")
    if not route_state.visible:
        return MapLayerPayload(_collection([]), _collection([]), _collection([]))
    route = entity_index.routes_by_id.get(route_id or "", {})
    stops_by_id = entity_index.stops_by_id
    stop_times = [payload for _key, payload in entity_index.stop_times_by_trip.get(trip_id, ())]
    stop_times.sort(key=lambda payload: _sequence(payload.get("stop_sequence")))
    stops: list[MapStop] = []
    for stop_time in stop_times:
        stop_id = _text(stop_time.get("stop_id"))
        stop = stops_by_id.get(stop_id or "")
        if stop is None:
            continue
        coordinate = _coordinate(stop.get("stop_lat"), stop.get("stop_lon"))
        if coordinate is None or stop_id is None:
            continue
        stops.append(
            MapStop(
                stop_id,
                _text(stop.get("stop_name")),
                coordinate,
                _integer(stop_time.get("stop_sequence")),
            )
        )
    shape_id = _text(trip.get("shape_id"))
    shape_points = [payload for _key, payload in entity_index.shapes_by_id.get(shape_id or "", ())]
    shape_points.sort(key=lambda payload: _sequence(payload.get("shape_pt_sequence")))
    coordinates = tuple(
        coordinate
        for payload in shape_points
        if (coordinate := _coordinate(payload.get("shape_pt_lat"), payload.get("shape_pt_lon")))
        is not None
    )
    geometry = TripShapeGeometry(
        trip_id=trip_id,
        shape_id=shape_id,
        coordinates=coordinates,
        length_meters=None,
        bbox=None,
        stop_distances=(),
        distance_unit="meters",
        length_method="working_revision",
        distance_method="not_calculated",
        issues=(),
        stops=tuple(stops),
        route_color=_text(route.get("route_color")),
        route_text_color=_text(route.get("route_text_color")),
        route_id=route_id,
    )
    payload = map_layers_for_trip(geometry, popup_by_stop)
    shapes = _decorate_features(payload.shapes, route_state)
    decorated_stops = _decorate_features(payload.stops, route_state)
    vertex_features: list[dict[str, object]] = []
    if include_shape_points and route_state.active and route_state.editable:
        point_rows = list(entity_index.shapes_by_id.get(shape_id or "", ()))
        selected_keys = _segment_keys(point_rows, segment)
        for key, point in point_rows:
            if selected_keys is not None and key[1] not in selected_keys:
                continue
            coordinate = _coordinate(point.get("shape_pt_lat"), point.get("shape_pt_lon"))
            if coordinate is None:
                continue
            vertex_features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "id": str(key[1]),
                        "shape_id": shape_id,
                        "route_id": route_id,
                        "color": route_color(route_id or "", _text(route.get("route_color"))),
                        "sequence": point.get("shape_pt_sequence"),
                        "position": len(vertex_features),
                        "dimmed": route_state.dimmed,
                    },
                    "geometry": {
                        "type": "Point",
                        "coordinates": [coordinate.longitude, coordinate.latitude],
                    },
                }
            )
    return MapLayerPayload(shapes, decorated_stops, _collection(vertex_features))


def map_layers_for_working_copy_routes(
    working_copy: WorkingCopy,
    route_ids: Collection[str],
    index: WorkingCopyEntityIndex | None = None,
    *,
    include_shape_points: bool = False,
    segment: tuple[str, str] | None = None,
    preview_route_id: str | None = None,
    session_route_ids: Collection[str] | None = None,
    popup_by_stop: Mapping[str, Mapping[str, object]] | None = None,
    _building_route_cache: bool = False,
) -> MapLayerPayload:
    """Construye un overlay simultáneo por rutas desde la working copy.

    Se representa una geometría por ``route_id``/``shape_id`` y un patrón de
    paradas por ruta. Esto evita multiplicar la misma línea por cada viaje y
    deja en las propiedades del feature el estado route-centric que consume
    MapLibre: visible, activa, editable, bloqueada y atenuada.
    """
    selected = {str(route_id) for route_id in route_ids if str(route_id)}
    session_routes = {str(route_id) for route_id in (session_route_ids or ()) if str(route_id)}
    if not selected:
        empty_generation = current_generation()
        mark_current("T4_BASE_GEOMETRY_FINISHED", generation=empty_generation)
        mark_current("T6_STOPS_POPUPS_FINISHED", generation=empty_generation)
        mark_current("T5_SHARED_CORRIDORS_FINISHED", generation=empty_generation)
        mark_current("T7_PAYLOAD_BUILT", generation=empty_generation)
        return MapLayerPayload(_collection([]), _collection([]), _collection([]))

    entity_index = index or working_copy.entity_index
    generation = getattr(working_copy, "geometric_generation", 0)
    trace_generation = current_generation()
    if trace_generation is None:
        trace_generation = generation
    set_key = (id(working_copy), generation, tuple(sorted(selected)))
    # El preview de una ruta oculta es efímero y no debe contaminar las cachés
    # de combinaciones visibles persistentes.
    if (
        not _building_route_cache
        and not include_shape_points
        and segment is None
        and preview_route_id is None
        and not session_routes
    ):
        cached_set = _VISIBLE_SET_CACHE.get(set_key)
        if cached_set is not None:
            count_current("visible_set_cache_hits")
            _VISIBLE_SET_CACHE.move_to_end(set_key)
            cached_payload = _refresh_payload_states(cached_set, working_copy)
            mark_current("T4_BASE_GEOMETRY_FINISHED", generation=trace_generation)
            mark_current("T6_STOPS_POPUPS_FINISHED", generation=trace_generation)
            mark_current("T5_SHARED_CORRIDORS_FINISHED", generation=trace_generation)
            mark_current("T7_PAYLOAD_BUILT", generation=trace_generation)
            return cached_payload
        count_current("visible_set_cache_misses")

    # Para conjuntos de varias rutas, cada componente se obtiene de la caché
    # individual. La única fase que permanece conjunta es la de corredores,
    # que necesita comparar segmentos de rutas distintas.
    if (
        not _building_route_cache
        and len(selected) > 1
        and not include_shape_points
        and preview_route_id is None
        and not session_routes
    ):
        cached_shape_records: list[dict[str, object]] = []
        cached_stop_features: list[dict[str, object]] = []
        for route_id in sorted(selected):
            route_key = (id(working_copy), generation, route_id)
            route_payload = _ROUTE_GEOMETRY_CACHE.get(route_key)
            if route_payload is None:
                count_current("route_geometry_cache_misses")
                route_payload = map_layers_for_working_copy_routes(
                    working_copy,
                    {route_id},
                    entity_index,
                    popup_by_stop=popup_by_stop,
                    _building_route_cache=True,
                )
                _ROUTE_GEOMETRY_CACHE[route_key] = route_payload
                _ROUTE_GEOMETRY_CACHE.move_to_end(route_key)
                while len(_ROUTE_GEOMETRY_CACHE) > _ROUTE_CACHE_LIMIT:
                    _ROUTE_GEOMETRY_CACHE.popitem(last=False)
            else:
                count_current("route_geometry_cache_hits")
                _ROUTE_GEOMETRY_CACHE.move_to_end(route_key)
            route_payload = _refresh_payload_states(route_payload, working_copy)
            for feature in _features(route_payload.shapes):
                properties = feature.get("properties")
                geometry = feature.get("geometry")
                if isinstance(properties, dict) and isinstance(geometry, dict):
                    coordinates = geometry.get("coordinates")
                    if isinstance(coordinates, list):
                        cached_shape_records.append(
                            {
                                "route_id": route_id,
                                "shape_id": properties.get("shape_id"),
                                "trip_id": properties.get("trip_id"),
                                "color": properties.get("color"),
                                "halo_color": properties.get("halo_color"),
                                "coordinates": coordinates,
                                "state": working_copy.route_state(route_id),
                            }
                        )
            cached_stop_features.extend(_features(route_payload.stops))
        mark_current("T5_SHARED_CORRIDORS_FINISHED", generation=trace_generation)
        result = MapLayerPayload(
            _collection(_shared_corridor_features(cached_shape_records)),
            _collection(cached_stop_features),
            _collection([]),
        )
        _VISIBLE_SET_CACHE[set_key] = result
        _VISIBLE_SET_CACHE.move_to_end(set_key)
        while len(_VISIBLE_SET_CACHE) > _VISIBLE_SET_CACHE_LIMIT:
            _VISIBLE_SET_CACHE.popitem(last=False)
        mark_current("T7_PAYLOAD_BUILT", generation=trace_generation)
        return result
    routes = {
        route_id: entity_index.routes_by_id[route_id]
        for route_id in selected
        if route_id in entity_index.routes_by_id
    }
    colors = route_colors(
        {
            route_id: _text(payload.get("route_color"))
            for route_id, payload in entity_index.routes_by_id.items()
        }
    )
    trips_by_route = {
        route_id: list(entity_index.trips_by_route.get(route_id, ())) for route_id in selected
    }
    stops_by_id = entity_index.stops_by_id
    shapes_by_id = entity_index.shapes_by_id

    shape_records: list[dict[str, object]] = []
    stop_features: list[dict[str, object]] = []
    shape_point_features: list[dict[str, object]] = []
    for route_id in sorted(selected):
        persisted_state = working_copy.route_state(route_id)
        # Una EditSession es un contexto cartográfico explícito: sus rutas se
        # muestran aunque la preferencia Visible previa fuese falsa. No se
        # persiste ni se altera el estado global; solo el payload usa este
        # estado efectivo transitorio.
        session_visible = route_id in session_routes
        state = replace(persisted_state, visible=True) if session_visible else persisted_state
        is_preview = route_id == preview_route_id and not session_visible and not state.visible
        if not state.visible and not is_preview:
            continue
        route = routes.get(route_id, {})
        color = colors.get(route_id, route_color(route_id, _text(route.get("route_color"))))
        trips = sorted(
            (payload for _key, payload in trips_by_route.get(route_id, [])),
            key=lambda payload: (
                _sequence(payload.get("trip_id")),
                _sequence(payload.get("shape_id")),
            ),
        )
        shape_ids = {
            str(trip.get("shape_id")) for trip in trips if trip.get("shape_id") is not None
        }
        for shape_id in sorted(shape_ids):
            point_rows = shapes_by_id.get(shape_id, ())
            coordinates = [
                [coordinate[1], coordinate[0]]
                for _key, point in point_rows
                if (
                    coordinate := _valid_coordinate_pair(
                        point.get("shape_pt_lat"), point.get("shape_pt_lon")
                    )
                )
            ]
            if len(coordinates) >= 2:
                shape_records.append(
                    {
                        "route_id": route_id,
                        "shape_id": shape_id,
                        "trip_id": str(trips[0].get("trip_id")) if trips else None,
                        "color": color,
                        "halo_color": contrast_halo_color(color),
                        "line_width": _route_line_width(1, active=state.active),
                        "route_selected": route_id == preview_route_id,
                        "route_preview": is_preview,
                        "coordinates": coordinates,
                        "state": state,
                    }
                )
            if include_shape_points and state.active and state.editable:
                selected_keys = _segment_keys(point_rows, segment)
                for position, (key, point) in enumerate(point_rows):
                    if selected_keys is not None and key[1] not in selected_keys:
                        continue
                    coordinate = _valid_coordinate_pair(
                        point.get("shape_pt_lat"), point.get("shape_pt_lon")
                    )
                    if coordinate is None:
                        continue
                    shape_point_features.append(
                        {
                            "type": "Feature",
                            "properties": {
                                "id": str(key[1]),
                                "route_id": route_id,
                                "shape_id": shape_id,
                                "sequence": point.get("shape_pt_sequence"),
                                "position": position,
                                "color": color,
                                **_workspace_properties(
                                    state,
                                    selected=route_id == preview_route_id,
                                    preview=is_preview,
                                ),
                            },
                            "geometry": {
                                "type": "Point",
                                "coordinates": [coordinate[1], coordinate[0]],
                            },
                        }
                    )

        # El primer viaje ordenado es el patrón visual de referencia de la ruta.
        trip = trips[0] if trips else None
        if trip is None or trip.get("trip_id") is None:
            continue
        trip_id = str(trip["trip_id"])
        route_popups = stop_popup_data_for_working_copy(working_copy, trip_id, entity_index)
        stop_times = list(entity_index.stop_times_by_trip.get(trip_id, ()))
        stop_times.sort(key=lambda item: _sequence(item[1].get("stop_sequence")))
        for stop_index, (key, stop_time) in enumerate(stop_times):
            stop_id = _text(stop_time.get("stop_id"))
            stop = stops_by_id.get(stop_id or "")
            if stop is None or stop_id is None:
                continue
            coordinate = _valid_coordinate_pair(stop.get("stop_lat"), stop.get("stop_lon"))
            if coordinate is None:
                continue
            stop_features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "id": stop_id,
                        "route_id": route_id,
                        "trip_id": trip_id,
                        "name": _text(stop.get("stop_name")) or "Sin nombre",
                        "sequence": stop_time.get("stop_sequence"),
                        "endpoint": (
                            "origin"
                            if stop_index == 0
                            else "destination"
                            if stop_index == len(stop_times) - 1
                            else None
                        ),
                        "popup": dict((popup_by_stop or route_popups).get(stop_id, {})),
                        "color": color,
                        **_workspace_properties(
                            state,
                            selected=route_id == preview_route_id,
                            preview=is_preview,
                        ),
                    },
                    "geometry": {
                        "type": "Point",
                        "coordinates": [coordinate[1], coordinate[0]],
                    },
                }
            )

    mark_current("T4_BASE_GEOMETRY_FINISHED", generation=trace_generation)
    mark_current("T6_STOPS_POPUPS_FINISHED", generation=trace_generation)
    shape_features = _shared_corridor_features(shape_records)
    mark_current("T5_SHARED_CORRIDORS_FINISHED", generation=trace_generation)
    result = MapLayerPayload(
        _collection(shape_features),
        _collection(stop_features),
        _collection(shape_point_features),
    )
    mark_current("T7_PAYLOAD_BUILT", generation=trace_generation)
    if _building_route_cache and len(selected) == 1 and not include_shape_points:
        return result
    return result


def stop_popup_data_for_working_copy(
    working_copy: WorkingCopy,
    trip_id: str,
    index: WorkingCopyEntityIndex | None = None,
) -> dict[str, dict[str, object]]:
    """Datos de parada compartidos por Explorar y el editor cartográfico."""
    entity_index = index or working_copy.entity_index
    trip = entity_index.trips_by_id.get(trip_id)
    if trip is None:
        return {}
    route_id = _text(trip.get("route_id")) or ""
    route = entity_index.routes_by_id.get(route_id, {})
    agency_id = _text(route.get("agency_id")) or ""
    agency = entity_index.agencies_by_id.get(agency_id)
    if agency is None and len(entity_index.agencies_by_id) == 1:
        agency = next(iter(entity_index.agencies_by_id.values()))
        agency_id = _text(agency.get("agency_id")) or agency_id
    agency_name = _text(agency.get("agency_name")) if agency else ""
    stop_times = list(entity_index.stop_times_by_trip.get(trip_id, ()))
    stop_times.sort(key=lambda item: _sequence(item[1].get("stop_sequence")))
    result: dict[str, dict[str, object]] = {}
    for position, (_key, stop_time) in enumerate(stop_times):
        stop_id = _text(stop_time.get("stop_id"))
        if stop_id is None:
            continue
        previous = stop_times[position - 1][1] if position else None
        following = stop_times[position + 1][1] if position + 1 < len(stop_times) else None
        arrival_seconds = stop_time.get("arrival_service_seconds")
        departure_seconds = stop_time.get("departure_service_seconds")
        dwell_seconds = (
            int(departure_seconds) - int(arrival_seconds)
            if isinstance(arrival_seconds, int)
            and not isinstance(arrival_seconds, bool)
            and isinstance(departure_seconds, int)
            and not isinstance(departure_seconds, bool)
            else None
        )
        previous_stop_id = _text(previous.get("stop_id")) if previous else None
        next_stop_id = _text(following.get("stop_id")) if following else None
        previous_stop_name = (
            _text(entity_index.stops_by_id.get(previous_stop_id or "", {}).get("stop_name"))
            if previous_stop_id
            else None
        )
        next_stop_name = (
            _text(entity_index.stops_by_id.get(next_stop_id or "", {}).get("stop_name"))
            if next_stop_id
            else None
        )
        card = StopCard(
            stop_id=stop_id,
            name=(
                _text(entity_index.stops_by_id.get(stop_id, {}).get("stop_name"))
                or _text(stop_time.get("stop_name"))
                or ""
            ),
            route_id=route_id,
            route_short_name=_text(route.get("route_short_name")) or "",
            route_long_name=_text(route.get("route_long_name")) or "",
            route_color=route_color(route_id, _text(route.get("route_color"))),
            endpoint=(
                "origin"
                if position == 0
                else "destination"
                if position == len(stop_times) - 1
                else "intermediate"
            ),
            arrival=_text(stop_time.get("arrival_time_lexeme")) or "",
            departure=_text(stop_time.get("departure_time_lexeme")) or "",
            sequence=_integer(stop_time.get("stop_sequence")),
            previous_stop=previous_stop_id,
            next_stop=next_stop_id,
            previous_stop_name=previous_stop_name,
            next_stop_name=next_stop_name,
            dwell_seconds=dwell_seconds,
            agency=agency_name or agency_id,
            agency_id=agency_id,
            trip_id=trip_id,
            service_id=_text(trip.get("service_id")) or "",
            headsign=_text(trip.get("trip_headsign")) or "",
        )
        payload = card.to_payload()
        result[stop_id] = payload
    # El editor no necesita una segunda consulta: añade un contexto compacto de
    # otras rutas que comparten la parada, igual que el popup de Explorar.
    for stop_id, popup in result.items():
        seen: set[str] = set()
        for _other_key, other_stop_time in entity_index.stop_times_by_stop.get(stop_id, ()):
            other_trip_id = _text(other_stop_time.get("trip_id"))
            other_trip = entity_index.trips_by_id.get(other_trip_id or "")
            other_route_id = _text(other_trip.get("route_id")) if other_trip else None
            if not other_route_id or other_route_id == route_id or other_route_id in seen:
                continue
            other_route = entity_index.routes_by_id.get(other_route_id, {})
            other_agency_id = _text(other_route.get("agency_id")) or ""
            other_agency = entity_index.agencies_by_id.get(other_agency_id, {})
            other_label = (
                " · ".join(
                    value
                    for value in (
                        _text(other_route.get("route_short_name")),
                        _text(other_route.get("route_long_name")),
                    )
                    if value
                )
                or other_route_id
            )
            other_routes = popup["other_routes"]
            if isinstance(other_routes, list):
                other_routes.append(
                    {
                        "route_id": other_route_id,
                        "route": other_label,
                        "agency": _text(other_agency.get("agency_name")) or other_agency_id,
                        "times": [
                            value
                            for value in (
                                _text(other_stop_time.get("departure_time_lexeme")),
                                _text(other_stop_time.get("arrival_time_lexeme")),
                            )
                            if value
                        ][:3],
                    }
                )
            seen.add(other_route_id)
    return result


def map_layer_bounds(payload: MapLayerPayload) -> tuple[float, float, float, float] | None:
    """Calcula la envolvente del overlay sin tocar su geometría ni el feed.

    La envolvente se usa únicamente para decidir si un paquete PMTiles puede
    cubrir el viaje completo. No se inspeccionan teselas ni se envía el overlay
    a ningún proveedor remoto.
    """
    coordinates: list[tuple[float, float]] = []
    for collection in (payload.shapes, payload.stops):
        for feature in _features(collection):
            geometry = feature.get("geometry")
            if not isinstance(geometry, dict):
                continue
            geometry_type = geometry.get("type")
            values = geometry.get("coordinates")
            points = values if geometry_type == "LineString" else [values]
            if not isinstance(points, list):
                continue
            for point in points:
                if not isinstance(point, list) or len(point) < 2:
                    continue
                longitude, latitude = point[0], point[1]
                if (
                    isinstance(longitude, (int, float))
                    and not isinstance(longitude, bool)
                    and isinstance(latitude, (int, float))
                    and not isinstance(latitude, bool)
                    and isfinite(float(longitude))
                    and isfinite(float(latitude))
                ):
                    coordinates.append((float(longitude), float(latitude)))
    if not coordinates:
        return None
    longitudes, latitudes = zip(*coordinates)
    return min(longitudes), min(latitudes), max(longitudes), max(latitudes)


def simplify_for_viewport(payload: MapLayerPayload, viewport: MapViewport) -> MapLayerPayload:
    """Reduce una capa al viewport sin modificar la geometría fuente.

    El límite es deliberadamente visual: la selección detallada sigue usando el
    viaje y la parada originales en las consultas Qt. La llamada es pura para
    poder cachear el resultado por viewport y descartarlo si queda obsoleto.
    """
    if not _valid_viewport(viewport):
        return MapLayerPayload(_collection([]), _collection([]))
    tolerance = max(0.000_002, 0.06 / (2 ** max(viewport.zoom, 0.0)))
    shapes: list[dict[str, object]] = []
    for feature in _features(payload.shapes):
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
            continue
        coordinates = _line_coordinates(geometry.get("coordinates"))
        visible = _visible_line(coordinates, viewport)
        if len(visible) < 2:
            continue
        visible = _evenly_sample(visible, MAX_RENDERED_SHAPE_POINTS)
        reduced = _douglas_peucker(visible, tolerance)
        if len(reduced) > MAX_RENDERED_SHAPE_POINTS:
            reduced = _evenly_sample(reduced, MAX_RENDERED_SHAPE_POINTS)
        shapes.append({**feature, "geometry": {**geometry, "coordinates": reduced}})
    stops = [
        feature
        for feature in _features(payload.stops)
        if _point_in_viewport(_point_coordinates(feature), viewport)
    ][:MAX_RENDERED_STOPS]
    shape_points = [
        feature
        for feature in _features(payload.shape_points or _collection([]))
        if _point_in_viewport(_point_coordinates(feature), viewport)
    ]
    shape_points = _evenly_sample_features(shape_points, MAX_RENDERED_SHAPE_POINTS)
    return MapLayerPayload(_collection(shapes), _collection(stops), _collection(shape_points))


def _features(collection: dict[str, object]) -> list[dict[str, object]]:
    features = collection.get("features")
    if not isinstance(features, list):
        return []
    return [feature for feature in features if isinstance(feature, dict)]


def _line_coordinates(value: object) -> list[list[float]]:
    if not isinstance(value, list):
        return []
    return [
        point
        for point in value
        if isinstance(point, list)
        and len(point) >= 2
        and all(isinstance(item, (int, float)) for item in point[:2])
    ]


def _point_coordinates(feature: dict[str, object]) -> list[float] | None:
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") != "Point":
        return None
    coordinates = geometry.get("coordinates")
    return coordinates if isinstance(coordinates, list) and len(coordinates) >= 2 else None


def _valid_viewport(viewport: MapViewport) -> bool:
    return (
        -180 <= viewport.west <= 180
        and -180 <= viewport.east <= 180
        and -90 <= viewport.south <= 90
        and -90 <= viewport.north <= 90
        and viewport.west <= viewport.east
        and viewport.south <= viewport.north
        and viewport.zoom >= 0
    )


def _point_in_viewport(point: list[float] | None, viewport: MapViewport) -> bool:
    return (
        point is not None
        and isinstance(point[0], (int, float))
        and isinstance(point[1], (int, float))
        and viewport.west <= point[0] <= viewport.east
        and viewport.south <= point[1] <= viewport.north
    )


def _visible_line(points: list[list[float]], viewport: MapViewport) -> list[list[float]]:
    visible = [point for point in points if _point_in_viewport(point, viewport)]
    if len(visible) >= 2:
        return visible
    # No descartes una ruta porque el viewport solo contiene un vértice (o
    # cruza la ventana entre dos vértices). La geometría sigue siendo visual:
    # MapLibre ya recorta la línea al canvas y conserva la identidad del shape.
    if points and _line_bounds_intersect(points, viewport):
        return points
    return []


def _line_bounds_intersect(points: list[list[float]], viewport: MapViewport) -> bool:
    longitudes = [point[0] for point in points]
    latitudes = [point[1] for point in points]
    return not (
        max(longitudes) < viewport.west
        or min(longitudes) > viewport.east
        or max(latitudes) < viewport.south
        or min(latitudes) > viewport.north
    )


def _route_line_width(shared_route_count: int, *, active: bool = False) -> float:
    """Ancho legible por ruta; la activa conserva una jerarquía visible."""
    count = max(1, shared_route_count)
    width = max(MIN_ROUTE_LINE_WIDTH_PX, min(6.0, 5.5 / count + 0.8))
    if active:
        width = min(MAX_ROUTE_LINE_WIDTH_PX, width + 1.2)
    return width


def _shared_corridor_features(records: list[dict[str, object]]) -> list[dict[str, object]]:
    """Divide únicamente los tramos compartidos y asigna carriles en píxeles.

    La comparación usa punto medio, longitud y rumbo en una proyección local
    equirectangular. Es tolerante a pequeñas diferencias de shape y nunca
    escribe en ``shape_pt_lat``/``shape_pt_lon``.
    """
    segments: list[dict[str, object]] = []
    for record_index, record in enumerate(records):
        coordinates = record["coordinates"]
        if not isinstance(coordinates, list):
            continue
        for segment_index in range(len(coordinates) - 1):
            first, second = coordinates[segment_index], coordinates[segment_index + 1]
            if not isinstance(first, list) or not isinstance(second, list):
                continue
            segments.append(
                {
                    "record_index": record_index,
                    "segment_index": segment_index,
                    "first": first,
                    "second": second,
                    "midpoint": [(first[0] + second[0]) / 2, (first[1] + second[1]) / 2],
                    "length": _segment_length_meters(first, second),
                    "bearing": _segment_bearing(first, second),
                }
            )
    # Índice uniforme en metros. Solo se comparan candidatos cuyo punto medio
    # puede estar dentro de la tolerancia; evita el producto cartesiano de
    # segmentos y conserva la misma decisión final de _segments_match().
    buckets: dict[tuple[int, int], list[dict[str, object]]] = {}
    bucket_size = SHARED_CORRIDOR_TOLERANCE_METERS
    for segment in segments:
        midpoint = cast(list[float], segment["midpoint"])
        latitude = float(midpoint[1])
        x = int((float(midpoint[0]) * 111_320 * cos(radians(latitude))) / bucket_size)
        y = int((latitude * 110_540) / bucket_size)
        segment["bucket"] = (x, y)
        buckets.setdefault((x, y), []).append(segment)

    # Las componentes conectadas conservan la unión transitiva del algoritmo
    # anterior, pero no recorren todos los grupos existentes por cada segmento.
    # La búsqueda de aristas sigue acotada a las celdas vecinas del bucket.
    parents = list(range(len(segments)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(first: int, second: int) -> None:
        first_root, second_root = find(first), find(second)
        if first_root != second_root:
            parents[second_root] = first_root

    segment_indexes = {id(segment): index for index, segment in enumerate(segments)}
    for candidate_index, candidate in enumerate(segments):
        bucket = cast(tuple[int, int], candidate["bucket"])
        nearby = (
            item
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for item in buckets.get((bucket[0] + dx, bucket[1] + dy), ())
            if segment_indexes[id(item)] < candidate_index
            and item["record_index"] != candidate["record_index"]
        )
        for existing in nearby:
            existing_index = segment_indexes[id(existing)]
            if _segments_match(candidate, existing):
                union(candidate_index, existing_index)

    grouped: dict[int, list[dict[str, object]]] = {}
    for index, segment in enumerate(segments):
        grouped.setdefault(find(index), []).append(segment)
    groups = [grouped[root] for root in sorted(grouped)]

    segment_info: dict[tuple[int, int], tuple[int, int, float]] = {}
    corridor_number = 0
    for group in groups:
        route_ids = sorted(
            {str(records[cast(int, item["record_index"])]["route_id"]) for item in group}
        )
        if len(route_ids) < 2:
            continue
        route_positions = {route_id: index for index, route_id in enumerate(route_ids)}
        count = len(route_ids)
        for item in group:
            record_index = cast(int, item["record_index"])
            route_id = str(records[record_index]["route_id"])
            lane = (route_positions[route_id] - (count - 1) / 2) * SHARED_CORRIDOR_LANE_SPACING_PX
            segment_info[(record_index, cast(int, item["segment_index"]))] = (
                corridor_number,
                count,
                lane,
            )
        corridor_number += 1

    features: list[dict[str, object]] = []
    for record_index, record in enumerate(records):
        coordinates = record["coordinates"]
        if not isinstance(coordinates, list):
            continue
        runs: list[tuple[list[list[float]], int, int, float]] = []
        for segment_index in range(len(coordinates) - 1):
            info = segment_info.get((record_index, segment_index), (-1, 1, 0.0))
            corridor, count, lane = info
            if runs and runs[-1][1:] == (corridor, count, lane):
                runs[-1][0].append(coordinates[segment_index + 1])
            else:
                runs.append(
                    (
                        [coordinates[segment_index], coordinates[segment_index + 1]],
                        corridor,
                        count,
                        lane,
                    )
                )
        for run_coordinates, corridor, count, lane in runs:
            properties = {
                "route_id": record["route_id"],
                "shape_id": record["shape_id"],
                "trip_id": record["trip_id"],
                "color": record["color"],
                "halo_color": record["halo_color"],
                "line_width": _route_line_width(
                    count,
                    active=cast(RouteWorkspaceState, record["state"]).active,
                ),
                "lane_offset": lane,
                "shared_route_count": count,
                "shared_corridor_id": corridor if corridor >= 0 else None,
                **_workspace_properties(
                    cast(RouteWorkspaceState, record["state"]),
                    selected=bool(record.get("route_selected")),
                    preview=bool(record.get("route_preview")),
                ),
            }
            features.append(
                {
                    "type": "Feature",
                    "properties": properties,
                    "geometry": {"type": "LineString", "coordinates": run_coordinates},
                }
            )
    return features


def _segment_length_meters(first: list[float], second: list[float]) -> float:
    latitude = radians((first[1] + second[1]) / 2)
    return hypot((second[0] - first[0]) * 111_320 * cos(latitude), (second[1] - first[1]) * 110_540)


def _segment_bearing(first: list[float], second: list[float]) -> float:
    latitude = radians((first[1] + second[1]) / 2)
    return atan2((second[0] - first[0]) * cos(latitude), second[1] - first[1])


def _segments_match(first: dict[str, object], second: dict[str, object]) -> bool:
    midpoint_a, midpoint_b = first["midpoint"], second["midpoint"]
    if not isinstance(midpoint_a, list) or not isinstance(midpoint_b, list):
        return False
    distance = hypot(
        (midpoint_a[0] - midpoint_b[0])
        * 111_320
        * cos(radians((midpoint_a[1] + midpoint_b[1]) / 2)),
        (midpoint_a[1] - midpoint_b[1]) * 110_540,
    )
    if distance > SHARED_CORRIDOR_TOLERANCE_METERS:
        return False
    if (
        abs(float(cast(float, first["length"])) - float(cast(float, second["length"])))
        > SHARED_CORRIDOR_TOLERANCE_METERS * 2
    ):
        return False
    bearing_delta = abs(
        float(cast(float, first["bearing"])) - float(cast(float, second["bearing"]))
    )
    bearing_delta = min(bearing_delta, 3.141592653589793 - bearing_delta)
    return bearing_delta <= radians(20)


def _evenly_sample(points: list[list[float]], limit: int) -> list[list[float]]:
    if len(points) <= limit:
        return points
    step = (len(points) - 1) / (limit - 1)
    return [points[round(index * step)] for index in range(limit)]


def _evenly_sample_features(
    features: list[dict[str, object]], limit: int
) -> list[dict[str, object]]:
    if len(features) <= limit:
        return features
    if limit <= 1:
        return features[:1]
    step = (len(features) - 1) / (limit - 1)
    return [features[round(index * step)] for index in range(limit)]


def _douglas_peucker(points: list[list[float]], tolerance: float) -> list[list[float]]:
    if len(points) <= 2:
        return points
    # Iterativo: una geometría dentada no puede agotar la pila de Python.
    keep = {0, len(points) - 1}
    pending = [(0, len(points) - 1)]
    while pending:
        first, last = pending.pop()
        start, end = points[first], points[last]
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = hypot(dx, dy)
        maximum, index = 0.0, None
        for candidate in range(first + 1, last):
            point = points[candidate]
            distance = (
                abs(dy * point[0] - dx * point[1] + end[0] * start[1] - end[1] * start[0]) / length
                if length
                else hypot(point[0] - start[0], point[1] - start[1])
            )
            if distance > maximum:
                maximum, index = distance, candidate
        if index is not None and maximum > tolerance:
            keep.add(index)
            pending.extend(((first, index), (index, last)))
    return [points[index] for index in sorted(keep)]


def _collection(features: list[dict[str, object]]) -> dict[str, object]:
    return {"type": "FeatureCollection", "features": features}


def _decorate_features(
    collection: dict[str, object], state: RouteWorkspaceState
) -> dict[str, object]:
    features = _features(collection)
    dimmed = state.dimmed
    decorated: list[dict[str, object]] = []
    for feature in features:
        raw_properties = feature.get("properties")
        properties: dict[str, object] = (
            dict(raw_properties) if isinstance(raw_properties, dict) else {}
        )
        decorated.append(
            {
                **feature,
                "properties": {
                    **properties,
                    "dimmed": dimmed,
                    "route_visible": state.visible,
                    "route_active": state.active,
                    "route_editable": state.editable,
                    "route_locked": state.locked,
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "features": decorated,
    }


def _refresh_payload_states(payload: MapLayerPayload, working_copy: WorkingCopy) -> MapLayerPayload:
    """Reaplica solo estados de workspace sobre una entrada geométrica cacheada."""

    def refresh(collection: dict[str, object]) -> dict[str, object]:
        refreshed: list[dict[str, object]] = []
        for feature in _features(collection):
            properties = feature.get("properties")
            route_id = properties.get("route_id") if isinstance(properties, dict) else None
            state = working_copy.route_state(str(route_id)) if route_id is not None else None
            if state is None:
                refreshed.append(feature)
                continue
            refreshed_properties = feature.get("properties")
            if isinstance(refreshed_properties, dict) and "line_width" in refreshed_properties:
                try:
                    shared_route_count = int(refreshed_properties.get("shared_route_count", 1))
                except (TypeError, ValueError):
                    shared_route_count = 1
                feature = {
                    **feature,
                    "properties": {
                        **refreshed_properties,
                        "line_width": _route_line_width(
                            shared_route_count,
                            active=state.active,
                        ),
                    },
                }
            refreshed.extend(_features(_decorate_features(_collection([feature]), state)))
        return _collection(refreshed)

    return MapLayerPayload(
        refresh(payload.shapes),
        refresh(payload.stops),
        refresh(payload.shape_points) if payload.shape_points is not None else None,
    )


def _text(value: object) -> str | None:
    return None if value is None else str(value)


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _coordinate(latitude: object, longitude: object) -> Coordinate | None:
    if not (
        isinstance(latitude, (int, float))
        and not isinstance(latitude, bool)
        and isinstance(longitude, (int, float))
        and not isinstance(longitude, bool)
        and isfinite(float(latitude))
        and isfinite(float(longitude))
        and -90 <= float(latitude) <= 90
        and -180 <= float(longitude) <= 180
    ):
        return None
    return Coordinate(float(latitude), float(longitude))


def _valid_coordinate_pair(latitude: object, longitude: object) -> tuple[float, float] | None:
    coordinate = _coordinate(latitude, longitude)
    return None if coordinate is None else (coordinate.latitude, coordinate.longitude)


def _workspace_properties(
    state: RouteWorkspaceState, *, selected: bool = False, preview: bool = False
) -> dict[str, bool]:
    return {
        "dimmed": state.dimmed,
        "route_visible": state.visible,
        "route_active": state.active,
        "route_editable": state.editable,
        "route_locked": state.locked,
        "route_selected": selected,
        "route_preview": preview,
    }


def _segment_keys(
    point_rows: Collection[tuple[tuple[str, str], dict[str, object]]],
    segment: tuple[str, str] | None,
) -> set[str] | None:
    if segment is None:
        return None
    ordered = list(point_rows)
    ordered.sort(key=lambda item: _sequence(item[1].get("shape_pt_sequence")))
    positions = {key[1]: position for position, (key, _payload) in enumerate(ordered)}
    first, second = (positions.get(str(value)) for value in segment)
    if first is None or second is None:
        return set()
    low, high = sorted((first, second))
    return {key[1] for key, _payload in ordered[low : high + 1]}


def _sequence(value: object) -> tuple[int, int | str]:
    if isinstance(value, int) and not isinstance(value, bool):
        return 0, value
    return 1, "" if value is None else str(value)
