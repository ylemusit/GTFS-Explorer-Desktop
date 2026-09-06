from __future__ import annotations

import json
import subprocess
from pathlib import Path

from gtfs_explorer.application.queries.map_layers import (
    MAX_RENDERED_STOPS,
    MapLayerPayload,
    MapViewport,
    contrast_halo_color,
    map_layers_for_trip,
    map_layers_for_working_copy_routes,
    readable_foreground_color,
    route_color,
    route_colors,
    sanitize_route_color,
    simplify_for_viewport,
)
from gtfs_explorer.domain.changesets import RouteWorkspaceState, WorkingCopy
from gtfs_explorer.domain.geometry import Coordinate, MapStop, TripShapeGeometry


def _geometry(
    *, color: str | None = "1a2b3c", coordinates: tuple[Coordinate, ...] | None = None
) -> TripShapeGeometry:
    return TripShapeGeometry(
        trip_id="T1",
        shape_id="SH1",
        coordinates=coordinates or (Coordinate(43.0, -5.0), Coordinate(43.1, -5.1)),
        length_meters=100,
        bbox=None,
        stop_distances=(),
        distance_unit="meters",
        length_method="test",
        distance_method="test",
        issues=(),
        stops=(MapStop("S1", "<img src=x onerror=alert(1)>", Coordinate(43.0, -5.0)),),
        route_color=color,
    )


def test_map_layers_emit_wgs84_features_and_sanitize_invalid_colors() -> None:
    payload = map_layers_for_trip(_geometry(color="invalid"))

    shape = payload.shapes["features"][0]  # type: ignore[index]
    stop = payload.stops["features"][0]  # type: ignore[index]
    assert shape["geometry"]["coordinates"] == [[-5.0, 43.0], [-5.1, 43.1]]  # type: ignore[index]
    assert shape["properties"]["color"] == "#2563eb"  # type: ignore[index]
    assert stop["geometry"]["coordinates"] == [-5.0, 43.0]  # type: ignore[index]
    assert stop["properties"]["name"] == "<img src=x onerror=alert(1)>"  # type: ignore[index]
    assert stop["properties"]["endpoint"] == "origin"  # type: ignore[index]
    assert stop["properties"]["popup"] == {}  # type: ignore[index]
    assert sanitize_route_color("#1a2b3c") == "#1A2B3C"


def test_map_layers_keep_stops_and_omit_a_missing_or_short_shape() -> None:
    geometry = _geometry(coordinates=(Coordinate(43.0, -5.0),))
    payload = map_layers_for_trip(geometry)

    assert payload.shapes == {"type": "FeatureCollection", "features": []}
    assert len(payload.stops["features"]) == 1  # type: ignore[arg-type]


def test_route_fallback_color_is_deterministic_and_distinguishes_routes() -> None:
    assert route_color("R1", "invalid") == route_color("R1", "invalid")
    assert route_color("R1", "invalid") != route_color("R2", "invalid")


def test_route_colors_replace_repeated_gtfs_colours_with_eight_distinct_fallbacks() -> None:
    route_values = {f"R{index}": "2244AA" for index in range(8)}

    colors = route_colors(route_values)

    assert len(set(colors.values())) == 8
    assert colors == route_colors(route_values)


def test_route_colors_keep_a_unique_valid_gtfs_colour() -> None:
    colors = route_colors({"R1": "12ab34", "R2": None})

    assert colors["R1"] == "#12AB34"
    assert colors["R2"] != colors["R1"]


def test_route_colors_replace_unique_but_visually_insufficient_gtfs_colours() -> None:
    colors = route_colors({"R1": "FF0000", "R2": "F00000"})

    assert colors["R1"] != colors["R2"]
    assert "#FF0000" not in set(colors.values()) or "#F00000" not in set(colors.values())


def test_shared_corridor_uses_render_offsets_without_mutating_gtfs_coordinates() -> None:
    entities: dict[tuple[str, str], dict[str, object]] = {
        ("gtfs_agency", "A1"): {"agency_id": "A1", "agency_name": "Operador"},
        ("gtfs_stops", "S1"): {
            "stop_id": "S1",
            "stop_name": "Centro",
            "stop_lat": 40.0,
            "stop_lon": -3.0,
        },
    }
    for index in range(4):
        route_id, trip_id, shape_id = f"R{index}", f"T{index}", f"SH{index}"
        entities[("gtfs_routes", route_id)] = {"route_id": route_id, "agency_id": "A1"}
        entities[("gtfs_trips", trip_id)] = {
            "trip_id": trip_id,
            "route_id": route_id,
            "shape_id": shape_id,
        }
        entities[("gtfs_stop_times", f"{trip_id}-1")] = {
            "trip_id": trip_id,
            "stop_id": "S1",
            "stop_sequence": 1,
            "arrival_time_lexeme": "24:01:00",
            "departure_time_lexeme": "24:01:30",
        }
        entities[("gtfs_shapes", f"{shape_id}-1")] = {
            "shape_id": shape_id,
            "shape_pt_lat": 40.0,
            "shape_pt_lon": -3.0,
            "shape_pt_sequence": 1,
        }
        entities[("gtfs_shapes", f"{shape_id}-2")] = {
            "shape_id": shape_id,
            "shape_pt_lat": 40.01,
            "shape_pt_lon": -3.0,
            "shape_pt_sequence": 2,
        }
    working_copy = WorkingCopy(entities)
    for index in range(4):
        working_copy.set_route_workspace_state(RouteWorkspaceState(f"R{index}", visible=True))
    before = working_copy.get(("gtfs_shapes", "SH0-1"))

    payload = map_layers_for_working_copy_routes(working_copy, {f"R{index}" for index in range(4)})
    features = payload.shapes["features"]
    assert len(features) == 4
    assert {feature["properties"]["shared_route_count"] for feature in features} == {4}
    assert {feature["properties"]["lane_offset"] for feature in features} == {
        -12.0,
        -4.0,
        4.0,
        12.0,
    }
    assert {feature["properties"]["line_width"] for feature in features} == {2.5}
    assert all(
        feature["properties"]["halo_color"] in {"#111827", "#FFFFFF"} for feature in features
    )
    popup = payload.stops["features"][0]["properties"]["popup"]
    assert popup["route_id"] == "R0"
    assert popup["arrival_time"] == "24:01:00"
    assert popup["agency"] == "Operador"
    assert working_copy.get(("gtfs_shapes", "SH0-1")) == before


def test_route_halo_uses_contrast_and_crossing_lines_survive_viewport_simplification() -> None:
    assert contrast_halo_color("FFFF00") == "#111827"
    assert contrast_halo_color("101010") == "#FFFFFF"
    assert readable_foreground_color("FFFF00") == "#111827"
    assert readable_foreground_color("101010") == "#FFFFFF"
    payload = MapLayerPayload(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {"type": "LineString", "coordinates": [[-10.0, 0.0], [10.0, 0.0]]},
                }
            ],
        },
        {"type": "FeatureCollection", "features": []},
    )
    result = simplify_for_viewport(payload, MapViewport(-1.0, -1.0, 1.0, 1.0, 20))
    assert len(result.shapes["features"]) == 1


def test_map_javascript_uses_text_content_fit_bounds_and_clicks_without_html_injection() -> None:
    layers_path = (
        Path(__file__).parents[1] / "src/gtfs_explorer/presentation/desktop/map/map_layers.js"
    )
    source = layers_path.read_text(encoding="utf-8")
    result = subprocess.run(
        ["node", "--check", str(layers_path)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "textContent" in source
    assert "innerHTML" not in source
    assert "fitBounds" in source
    assert "maxZoom: 16" in source
    assert "Number.isFinite" in source
    assert "map.resize();" in source
    assert "trackResize: true" in source
    assert '"gtfs-stops-circle"' in source
    assert '"gtfs-route-context"' in source
    assert '"gtfs-stops-cluster"' not in source
    assert '"cluster": true' not in source
    assert '"gtfs-stops-endpoints"' in source
    assert "properties.sequence" in source
    assert 'action: "drag_preview"' not in source
    assert 'map.on("contextmenu"' not in source
    assert 'map.on("dblclick"' not in source
    assert "setVertexAction" in source
    assert "setEditMode" in source
    assert "generationId" in source
    assert "performanceTimings" in source
    assert "final_visible_routes" in source
    assert "Horario programado" in source
    assert "other_routes" in source
    assert "gtfs-explorer-map-bridge-ready" in source
    assert "reportMapReadyWhenBridgeIsAvailable" in source
    assert "mapLoaded = true;" in source


def test_packaged_map_layers_match_the_source_contract() -> None:
    root = Path(__file__).parents[1]

    assert (root / "src/gtfs_explorer/presentation/desktop/map/map_layers.js").read_bytes() == (
        root / "web/map/qt_resources/map_layers.js"
    ).read_bytes()


def test_endpoint_layer_expressions_are_validated_by_maplibre_style_spec() -> None:
    root = Path(__file__).parents[1]
    layers_path = root / "src/gtfs_explorer/presentation/desktop/map/map_layers.js"
    source = layers_path.read_text(encoding="utf-8")
    style_spec_path = (root / "web/map/node_modules/@maplibre/maplibre-gl-style-spec").as_posix()
    harness = f"""
const styleSpec = require({style_spec_path!r});
const handlers = {{}};
class Source {{ constructor(data) {{ this.data = data; }} setData(data) {{ this.data = data; }} }}
class Bounds {{ extend() {{ return this; }} }}
class FakeMap {{
  constructor() {{
    this.sources = {{}}; this.layers = {{}}; this.styleLoaded = true;
    globalThis.testMap = this;
  }}
  on(event, ...args) {{ (handlers[event] ||= []).push(args.at(-1)); }}
  emit(event) {{ for (const handler of handlers[event] || []) handler({{}}); }}
  addSource(id, specification) {{ this.sources[id] = new Source(specification.data); }}
  getSource(id) {{ return this.sources[id]; }}
  addLayer(layer) {{ this.layers[layer.id] = layer; }}
  getLayer(id) {{ return this.layers[id]; }}
  isStyleLoaded() {{ return this.styleLoaded; }}
  resize() {{}} fitBounds() {{}} getCanvas() {{ return {{style: {{}}}}; }}
}}
globalThis.document = {{createElement: () => ({{textContent: ""}})}};
globalThis.fetch = async () => ({{
  ok: true, json: async () => ({{version: 8, sources: {{}}, layers: []}}),
}});
globalThis.window = {{
  GTFSExplorerMap: {{maplibregl: {{
    setWorkerUrl() {{}}, addProtocol() {{}}, Map: FakeMap,
    LngLatBounds: Bounds, Popup: class {{}},
  }}, PMTiles: class {{}}, Protocol: class {{add() {{}}}}}},
  GTFSExplorerMapBridge: {{mapReady: () => true}}, addEventListener: () => {{}},
}};
eval({source!r});
testMap.emit("load");
const layer = testMap.getLayer("gtfs-stops-endpoints");
const filter = styleSpec.featureFilter(layer.filter, "layers.gtfs-stops-endpoints.filter");
const color = styleSpec.createPropertyExpression(
  layer.paint["circle-color"],
  "layers.gtfs-stops-endpoints.paint.circle-color",
  styleSpec.latest.paint_circle["circle-color"],
);
if (!filter || !color.result) throw new Error(JSON.stringify(color.errors || []));
console.log(JSON.stringify({{filter: layer.filter, color: layer.paint["circle-color"]}}));
"""
    result = subprocess.run(
        ["node", "--input-type=commonjs"],
        input=harness,
        check=True,
        capture_output=True,
        text=True,
        cwd=root / "web/map",
    )
    expressions = json.loads(result.stdout)
    assert expressions == {
        "filter": ["in", ["get", "endpoint"], ["literal", ["origin", "destination"]]],
        "color": [
            "match",
            ["get", "endpoint"],
            "origin",
            "#16a34a",
            "destination",
            "#dc2626",
            "#ffffff",
        ],
    }


def test_map_queues_layers_until_the_style_is_really_ready() -> None:
    layers_path = (
        Path(__file__).parents[1] / "src/gtfs_explorer/presentation/desktop/map/map_layers.js"
    )
    source = layers_path.read_text(encoding="utf-8")
    harness = f"""
const handlers = {{}};
let readyCalls = 0;
const listeners = {{}};
class Source {{
  constructor(data) {{ this.data = data; }}
  setData(data) {{ this.data = data; }}
  serialize() {{ return {{data: this.data}}; }}
}}
class Bounds {{
  extend() {{ return this; }}
}}
class FakeMap {{
  constructor() {{
    this.sources = {{}};
    this.layers = {{}};
    this.styleLoaded = false;
    globalThis.testMap = this;
  }}
  on(event, ...args) {{ (handlers[event] ||= []).push(args.at(-1)); }}
  emit(event) {{ for (const handler of handlers[event] || []) handler({{}}); }}
  addSource(id, specification) {{ this.sources[id] = new Source(specification.data); }}
  getSource(id) {{ return this.sources[id]; }}
  addLayer(layer) {{ this.layers[layer.id] = layer; }}
  getLayer(id) {{ return this.layers[id]; }}
  isStyleLoaded() {{ return this.styleLoaded; }}
  resize() {{}}
  fitBounds() {{}}
  getCanvas() {{ return {{style: {{}}}}; }}
  setStyle() {{
    this.sources = {{}};
    this.layers = {{}};
    this.styleLoaded = true;
    this.emit("style.load");
  }}
}}
globalThis.document = {{createElement: () => ({{textContent: ""}})}};
globalThis.fetch = async () => ({{
  ok: true,
  json: async () => ({{version: 8, sources: {{}}, layers: []}}),
}});
globalThis.window = {{
  GTFSExplorerMap: {{maplibregl: {{
    setWorkerUrl() {{}}, addProtocol() {{}}, Map: FakeMap, LngLatBounds: Bounds, Popup: class {{}}
  }}, PMTiles: class {{}}, Protocol: class {{
    constructor() {{ this.tile = () => {{}}; }}
    add() {{}}
  }}}},
  GTFSExplorerMapBridge: {{mapReady: () => {{ readyCalls += 1; return true; }}}},
  addEventListener: (event, handler) => {{ listeners[event] = handler; }},
}};
eval({source!r});
testMap.emit("load");
const payload = {{
  shapes: {{type: "FeatureCollection", features: [{{
    type: "Feature", geometry: {{type: "LineString", coordinates: [[-5.8, 43.1], [-5.9, 43.2]]}}
  }}]}},
  stops: {{type: "FeatureCollection", features: [{{
    type: "Feature", geometry: {{type: "Point", coordinates: [-5.8, 43.1]}}
  }}]}},
}};
const initial = window.GTFSExplorerLayers.replace(payload, true, true);
const beforeIdle = testMap.getSource("gtfs-shapes").data.features.length;
testMap.styleLoaded = true;
testMap.emit("idle");
const afterIdle = testMap.getSource("gtfs-shapes").data.features.length;
window.GTFSExplorerLayers.setBasemap("style.json", "basemap.pmtiles").then(() => {{
  console.log(JSON.stringify({{
    initial,
    beforeIdle,
    afterIdle,
    afterBasemap: testMap.getSource("gtfs-shapes").data.features.length,
    transitLayerRestored: !!testMap.getLayer("gtfs-shapes-line"),
    readyCalls,
  }}));
}});
"""
    result = subprocess.run(
        ["node", "--input-type=commonjs"],
        input=harness,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == {
        "initial": False,
        "beforeIdle": 0,
        "afterIdle": 1,
        "afterBasemap": 1,
        "transitLayerRestored": True,
        "readyCalls": 1,
    }


def test_viewport_lod_filters_stops_and_keeps_a_bounded_visual_payload() -> None:
    stops = [
        {
            "type": "Feature",
            "properties": {"id": f"S{index}"},
            "geometry": {"type": "Point", "coordinates": [-5.0 + index / 100_000, 43.0]},
        }
        for index in range(MAX_RENDERED_STOPS + 100)
    ]
    payload = MapLayerPayload(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[-5.0 + index / 10_000, 43.0] for index in range(8_000)],
                    },
                }
            ],
        },
        {"type": "FeatureCollection", "features": stops},
    )

    result = simplify_for_viewport(payload, MapViewport(-5.0, 42.9, -4.9, 43.1, 12))

    assert len(result.stops["features"]) == MAX_RENDERED_STOPS  # type: ignore[arg-type]
    coordinates = result.shapes["features"][0]["geometry"]["coordinates"]  # type: ignore[index]
    assert len(coordinates) < 8_000
    assert all(-5.0 <= point[0] <= -4.9 for point in coordinates)
