# ruff: noqa: E501

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from gtfs_explorer.application.map_policy import (
    DEFAULT_ONLINE_MAP_PROVIDER,
    MapAvailability,
    MapCoverage,
    MapMode,
    MapPolicyError,
    MapRequestPolicy,
    OnlineMapProvider,
    resolve_map_policy,
)
from gtfs_explorer.application.queries.map_layers import MapLayerPayload, map_layer_bounds

# Los stubs JavaScript se mantienen legibles como bloques ejecutables.


def _payload() -> MapLayerPayload:
    return MapLayerPayload(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"trip_id": "T1"},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[-5.8, 43.1], [-5.7, 43.2]],
                    },
                }
            ],
        },
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"id": "S1", "name": "Parada"},
                    "geometry": {"type": "Point", "coordinates": [-5.75, 43.15]},
                }
            ],
        },
    )


def test_overlay_bounds_are_pure_and_cover_shape_and_stop_features() -> None:
    payload = _payload()

    assert map_layer_bounds(payload) == (-5.8, 43.1, -5.7, 43.2)
    features = payload.stops["features"]
    assert isinstance(features, list)
    assert isinstance(features[0], dict)
    assert features[0]["properties"] == {"id": "S1", "name": "Parada"}


@pytest.mark.parametrize(
    ("mode", "coverage", "online", "availability"),
    (
        (MapMode.AUTO, MapCoverage.LOCAL_COVERAGE, True, MapAvailability.LOCAL),
        (MapMode.AUTO, MapCoverage.OUTSIDE_LOCAL_COVERAGE, True, MapAvailability.ONLINE),
        (MapMode.OFFLINE, MapCoverage.LOCAL_COVERAGE, True, MapAvailability.LOCAL),
        (MapMode.OFFLINE, MapCoverage.OUTSIDE_LOCAL_COVERAGE, True, MapAvailability.UNAVAILABLE),
        (MapMode.ONLINE, MapCoverage.LOCAL_COVERAGE, True, MapAvailability.ONLINE),
    ),
)
def test_policy_uses_bounds_without_scanning_tiles(
    mode: MapMode,
    coverage: MapCoverage,
    online: bool,
    availability: MapAvailability,
) -> None:
    decision = resolve_map_policy(
        mode,
        local_available=True,
        online_available=online,
        coverage=coverage,
        provider_name=DEFAULT_ONLINE_MAP_PROVIDER.name,
    )

    assert decision.availability is availability
    assert decision.coverage is coverage


def test_default_provider_is_https_interactive_osm_without_credentials() -> None:
    provider = DEFAULT_ONLINE_MAP_PROVIDER

    assert provider.name == "OpenStreetMap Standard"
    assert provider.origin == "https://tile.openstreetmap.org"
    assert provider.tile_url(z=12, x=1, y=2) == "https://tile.openstreetmap.org/12/1/2.png"
    assert "?" not in provider.tile_url_template
    assert "token" not in provider.tile_url_template.casefold()
    assert "key" not in provider.tile_url_template.casefold()


@pytest.mark.parametrize(
    "template",
    (
        "http://tiles.example/{z}/{x}/{y}.png",
        "https://tiles.example/{z}/{x}/{y}.png?token=secret",
    ),
)
def test_online_provider_rejects_non_contract_templates(template: str) -> None:
    with pytest.raises(MapPolicyError):
        OnlineMapProvider("Invalid provider", template, "Attribution")


def test_online_allowlist_is_strict_and_auto_local_does_not_open_remote_tiles() -> None:
    policy = MapRequestPolicy(
        MapMode.AUTO,
        local_origin="http://127.0.0.1:43123",
        online_origins=(DEFAULT_ONLINE_MAP_PROVIDER.origin,),
    )
    policy.set_active_availability(MapAvailability.LOCAL)

    assert policy.allows("http://127.0.0.1:43123/session/style.json")
    assert not policy.allows("https://tile.openstreetmap.org/12/1/2.png")
    assert not policy.allows("https://other.example/12/1/2.png")

    policy.set_active_availability(MapAvailability.ONLINE)
    assert policy.allows("https://tile.openstreetmap.org/12/1/2.png")
    assert not policy.allows("https://tile.openstreetmap.org/12/1/2.png?trip_id=T1")
    assert not policy.allows("https://tile.openstreetmap.org/12/1/2.png#stop_id=S1")


def test_runtime_javascript_keeps_overlay_selection_and_camera_across_basemap_changes() -> None:
    root = Path(__file__).parents[1]
    source = (root / "src/gtfs_explorer/presentation/desktop/map/map_layers.js").read_text(
        encoding="utf-8"
    )
    harness = f"""
const handlers = {{}};
const listeners = {{}};
let errors = [];
class Source {{
  constructor(data) {{ this.data = data; }}
  setData(data) {{ this.data = data; }}
  serialize() {{ return {{data: this.data}}; }}
}}
class Bounds {{ extend() {{ return this; }} }}
class FakeMap {{
  constructor() {{
    this.sources = {{}}; this.layers = {{}}; this.styleLoaded = false;
    this.camera = {{center: [10, 20], zoom: 7, bearing: 11, pitch: 12}};
    this.fitCalls = 0; this.deferNextStyle = false;
    globalThis.testMap = this;
  }}
  on(event, ...args) {{ (handlers[event] ||= []).push(args.at(-1)); }}
  emit(event, payload = {{}}) {{ for (const handler of handlers[event] || []) handler(payload); }}
  addSource(id, specification) {{ this.sources[id] = new Source(specification.data); }}
  getSource(id) {{ return this.sources[id]; }}
  addLayer(layer) {{ this.layers[layer.id] = layer; }}
  getLayer(id) {{ return this.layers[id]; }}
  isStyleLoaded() {{ return this.styleLoaded; }}
  resize() {{}}
  fitBounds() {{ this.fitCalls += 1; }}
  getCenter() {{ return {{lng: this.camera.center[0], lat: this.camera.center[1]}}; }}
  getZoom() {{ return this.camera.zoom; }}
  getBearing() {{ return this.camera.bearing; }}
  getPitch() {{ return this.camera.pitch; }}
  jumpTo(value) {{ this.camera = {{...this.camera, ...value}}; }}
  getCanvas() {{ return {{style: {{}}}}; }}
  setStyle(style) {{
    this.style = style; this.sources = {{}}; this.layers = {{}};
    this.styleLoaded = !this.deferNextStyle;
    if (this.styleLoaded) this.emit("style.load");
  }}
}}
globalThis.document = {{createElement: () => ({{textContent: ""}})}};
globalThis.fetch = async () => ({{ok: true, json: async () => ({{version: 8, sources: {{}}, layers: []}})}});
globalThis.window = {{
  GTFSExplorerMap: {{maplibregl: {{
    setWorkerUrl() {{}}, addProtocol() {{}}, Map: FakeMap,
    LngLatBounds: Bounds, Popup: class {{}}
  }}, PMTiles: class {{}}, Protocol: class {{
    constructor() {{ this.tile = () => {{}}; }} add() {{}}
  }}}},
  GTFSExplorerMapBridge: {{
    mapReady: () => true,
    featureClicked: () => true,
    viewportChanged: () => true,
    mapError: (payload) => errors.push(payload),
  }},
  addEventListener: (event, handler) => {{ listeners[event] = handler; }},
}};
eval({source!r});
testMap.emit("load");
const payload = {{
  shapes: {{type: "FeatureCollection", features: [{{type: "Feature", properties: {{trip_id: "T1"}}, geometry: {{type: "LineString", coordinates: [[10, 20], [11, 21]]}}}}]}},
  stops: {{type: "FeatureCollection", features: [{{type: "Feature", properties: {{id: "S1", name: "Nombre"}}, geometry: {{type: "Point", coordinates: [10, 20]}}}}]}},
}};
window.GTFSExplorerLayers.replace(payload, false, true);
window.GTFSExplorerLayers.selectStop("S1");
const before = JSON.stringify({{camera: testMap.camera, overlay: testMap.getSource("gtfs-stops").data}});
testMap.deferNextStyle = true;
const onlineChange = window.GTFSExplorerLayers.setOnlineBasemap("https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", 256, 0, 19, 1);
window.GTFSExplorerLayers.replace(payload, true, false);
testMap.styleLoaded = true;
testMap.emit("style.load");
testMap.deferNextStyle = false;
onlineChange
  .then(() => window.GTFSExplorerLayers.setBasemap("style.json", "basemap.pmtiles", 2))
  .then(() => window.GTFSExplorerLayers.clearBasemap(3))
  .then(() => console.log(JSON.stringify({{
    before: JSON.parse(before),
    camera: testMap.camera,
    overlay: testMap.getSource("gtfs-stops").data,
    fitCalls: testMap.fitCalls,
    styleSources: testMap.style.sources,
    errors,
  }})));
"""
    result = subprocess.run(
        ["node", "--input-type=commonjs", "--eval", harness],
        check=True,
        capture_output=True,
        text=True,
    )
    evidence = json.loads(result.stdout)

    assert evidence["before"]["camera"] == evidence["camera"]
    assert evidence["overlay"]["features"][0]["properties"]["selected"]
    assert evidence["overlay"]["features"][0]["properties"]["id"] == "S1"
    assert evidence["fitCalls"] == 1
    assert evidence["styleSources"] == {}
    assert evidence["errors"] == []


@pytest.mark.parametrize("failure", ("dns", "http", "tile", "timeout", "style", "source"))
def test_runtime_javascript_reports_map_failure_without_exposing_request_details(
    failure: str,
) -> None:
    root = Path(__file__).parents[1]
    source = (root / "src/gtfs_explorer/presentation/desktop/map/map_layers.js").read_text(
        encoding="utf-8"
    )
    harness = f"""
const handlers = {{}}; let errors = [];
class Source {{ constructor(data) {{ this.data = data; }} setData(data) {{ this.data = data; }} serialize() {{ return {{data: this.data}}; }} }}
class FakeMap {{
  constructor() {{ this.sources = {{}}; this.layers = {{}}; this.styleLoaded = false; globalThis.testMap = this; }}
  on(event, ...args) {{ (handlers[event] ||= []).push(args.at(-1)); }}
  emit(event, value = {{}}) {{ for (const handler of handlers[event] || []) handler(value); }}
  addSource(id, specification) {{ this.sources[id] = new Source(specification.data); }}
  getSource(id) {{ return this.sources[id]; }}
  addLayer(layer) {{ this.layers[layer.id] = layer; }}
  getLayer(id) {{ return this.layers[id]; }}
  isStyleLoaded() {{ return this.styleLoaded; }}
  setStyle() {{ this.styleLoaded = true; this.emit("style.load"); }}
  resize() {{}} getCanvas() {{ return {{style: {{}}}}; }}
}}
globalThis.document = {{createElement: () => ({{textContent: ""}})}};
globalThis.window = {{
  GTFSExplorerMap: {{maplibregl: {{setWorkerUrl() {{}}, addProtocol() {{}}, Map: FakeMap, LngLatBounds: class {{}}, Popup: class {{}}}}, PMTiles: class {{}}, Protocol: class {{add() {{}}}}}},
  GTFSExplorerMapBridge: {{mapReady: () => true, featureClicked: () => true, viewportChanged: () => true, mapError: (value) => errors.push(value)}},
  addEventListener: () => {{}},
}};
eval({source!r});
"""
    harness += f"""\ntestMap.emit("load");
window.GTFSExplorerLayers.setOnlineBasemap("https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", 256, 0, 19, 9);
testMap.emit("error", {{error: {{message: "secret-url-with-trip_id-{failure}"}}}});
testMap.emit("error", {{}});
console.log(JSON.stringify(errors));\n"""
    result = subprocess.run(
        ["node", "--input-type=commonjs", "--eval", harness],
        check=True,
        capture_output=True,
        text=True,
    )
    errors = json.loads(result.stdout)

    assert len(errors) == 1
    assert errors[0] == {"source": "online", "kind": "map", "request": 9}
    assert "secret-url" not in json.dumps(errors)
