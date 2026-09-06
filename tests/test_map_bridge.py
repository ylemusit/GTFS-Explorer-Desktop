from __future__ import annotations

import json
import subprocess
from pathlib import Path

from gtfs_explorer.presentation.map_bridge.protocol import (
    EDIT_PROTOCOL_VERSION,
    MAX_MESSAGE_BYTES,
    MAX_PENDING_COMMANDS,
    DispatchStatus,
    MapBridge,
    MapFitBounds,
    MapNavigation,
    parse_edit_event,
    serialize_navigation,
)


def _event(name: str, sequence: int, payload: dict[str, object] | None = None) -> str:
    return json.dumps(
        {
            "version": 1,
            "type": "event",
            "event": name,
            "sequence": sequence,
            "payload": payload or {},
        }
    )


def _edit_event(sequence: int, payload: dict[str, object]) -> str:
    return json.dumps(
        {
            "version": EDIT_PROTOCOL_VERSION,
            "type": "event",
            "event": "editGesture",
            "sequence": sequence,
            "payload": payload,
        }
    )


def test_invalid_messages_are_rejected_without_crashing() -> None:
    bridge = MapBridge()
    errors: list[str] = []
    bridge.protocol_error.connect(errors.append)

    bridge.receive("not json")
    bridge.receive(_event("unknown", 0))
    bridge.receive("x" * (MAX_MESSAGE_BYTES + 1))

    assert len(errors) == 3
    assert not bridge.ready


def test_navigation_is_queued_until_ready_with_a_fixed_limit() -> None:
    bridge = MapBridge()
    commands: list[str] = []
    bridge.command_available.connect(commands.append)
    navigation = MapNavigation(-3.7, 40.4, 12.0)

    assert bridge.navigate(navigation) is DispatchStatus.QUEUED
    bridge.receive(_event("mapReady", 4))

    assert bridge.ready
    assert bridge.pending_count == 0
    assert json.loads(commands.pop()) == json.loads(serialize_navigation(navigation))

    limited = MapBridge()
    for _ in range(MAX_PENDING_COMMANDS):
        limited.navigate(navigation)
    assert limited.navigate(navigation) is DispatchStatus.REJECTED


def test_fit_bounds_is_serialized_and_queued_until_ready() -> None:
    bridge = MapBridge()
    commands: list[str] = []
    bridge.command_available.connect(commands.append)
    bounds = MapFitBounds(-6.0, 36.0, -5.0, 37.0)

    assert bridge.navigate(bounds) is DispatchStatus.QUEUED
    bridge.receive(_event("mapReady", 1))

    command = json.loads(commands[0])
    assert command["command"] == "fitBounds"
    assert command["payload"] == {"west": -6.0, "south": 36.0, "east": -5.0, "north": 37.0}


def test_events_out_of_order_or_before_readiness_are_rejected() -> None:
    bridge = MapBridge()
    errors: list[str] = []
    received: list[object] = []
    bridge.protocol_error.connect(errors.append)
    bridge.event_received.connect(received.append)

    bridge.receive(_event("featureClicked", 0, {"id": "S1"}))
    bridge.receive(_event("mapReady", 1))
    bridge.receive(_event("mapReady", 2))
    bridge.receive(_event("featureClicked", 1, {"id": "S1"}))

    assert len(received) == 1
    assert len(errors) == 3


def test_viewport_event_is_available_only_after_map_ready() -> None:
    bridge = MapBridge()
    received: list[object] = []
    bridge.event_received.connect(received.append)

    bridge.receive(_event("mapReady", 1))
    bridge.receive(_event("viewportChanged", 2, {"request": 1, "west": -5.0}))

    assert [event.event for event in received] == ["mapReady", "viewportChanged"]


def test_performance_timings_are_a_bounded_bridge_event_after_map_ready() -> None:
    bridge = MapBridge()
    received: list[object] = []
    errors: list[str] = []
    bridge.event_received.connect(received.append)
    bridge.protocol_error.connect(errors.append)

    bridge.receive(_event("performanceTimings", 0, {"generation_id": 4, "idle_final": 12.5}))
    bridge.receive(_event("mapReady", 1))
    bridge.receive(_event("performanceTimings", 2, {"generation_id": 4, "idle_final": 12.5}))

    assert len(errors) == 1
    assert [event.event for event in received] == ["mapReady", "performanceTimings"]


def test_v2_edit_gesture_is_declarative_bounded_and_ordered() -> None:
    gesture = parse_edit_event(
        _edit_event(
            0,
            {
                "action": "drag_end",
                "entity_type": "stop",
                "entity_id": "S1",
                "route_id": "R1",
                "longitude": -3.7,
                "latitude": 40.4,
            },
        )
    )
    assert gesture.entity_id == "S1"
    assert gesture.longitude == -3.7

    bridge = MapBridge()
    received: list[object] = []
    errors: list[str] = []
    bridge.edit_event_received.connect(received.append)
    bridge.protocol_error.connect(errors.append)
    bridge.receive(_event("mapReady", 0))
    select = {"action": "select", "entity_type": "stop", "entity_id": "S1"}
    bridge.receive_v2(_edit_event(0, select))
    bridge.receive_v2(_edit_event(0, select))
    bridge.receive_v2(
        _edit_event(
            1,
            {
                "action": "drag_end",
                "entity_type": "stop",
                "entity_id": "S1",
                "longitude": 500,
                "latitude": 40,
            },
        )
    )
    assert len(received) == 1
    assert len(errors) == 2


def test_javascript_contract_has_one_channel_and_same_limits() -> None:
    bridge_path = (
        Path(__file__).parents[1] / "src/gtfs_explorer/presentation/map_bridge/map_bridge.js"
    )
    source = bridge_path.read_text(encoding="utf-8")

    assert source.count("new QWebChannel(") == 1
    assert "const VERSION = 1;" in source
    assert "const EDIT_VERSION = 2;" in source
    assert "const MAX_MESSAGE_BYTES = 16 * 1024;" in source
    assert "const MAX_PENDING_COMMANDS = 32;" in source
    assert '["navigate", "fitBounds"].includes(command.command)' in source
    assert "bridge.command_available.connect(dispatchCommand);" in source
    assert 'new Event("gtfs-explorer-map-bridge-ready")' in source
    assert "editGesture" in source
    assert "performanceTimings" in source
    assert "filesystem" in source and "SQL" in source

    harness = f"""
const received = [];
const dispatched = [];
let created = 0;
let commandHandler = null;
globalThis.window = {{dispatchEvent: (event) => dispatched.push(event)}};
globalThis.CustomEvent = class {{
  constructor(type, init) {{ this.type = type; this.detail = init.detail; }}
}};
globalThis.qt = {{webChannelTransport: {{}}}};
globalThis.QWebChannel = function (_, callback) {{
  created += 1;
  callback({{objects: {{mapBridge: {{
    receive: (message) => received.push(JSON.parse(message)),
    command_available: {{connect: (handler) => {{ commandHandler = handler; }}}},
  }}}}}});
}};
eval({source!r});
const api = window.GTFSExplorerMapBridge;
if (api.featureClicked({{id: "S1"}}) !== false || !api.mapReady()) process.exit(2);
api.featureClicked({{id: "S1"}});
commandHandler(JSON.stringify({{
  version: 1, type: "command", command: "navigate",
  payload: {{longitude: 0, latitude: 0, zoom: 1}},
}}));
console.log(JSON.stringify({{created, received, dispatched}}));
"""
    result = subprocess.run(
        ["node", "--input-type=commonjs", "--eval", harness],
        check=True,
        capture_output=True,
        text=True,
    )
    evidence = json.loads(result.stdout)
    assert evidence["created"] == 1
    assert [event["event"] for event in evidence["received"]] == ["mapReady", "featureClicked"]
    assert len(evidence["dispatched"]) == 2
    assert evidence["dispatched"][1]["type"] == "gtfs-explorer-map-command"


def test_qt_webchannel_signal_name_matches_javascript_and_packaged_resource() -> None:
    bridge_path = (
        Path(__file__).parents[1] / "src/gtfs_explorer/presentation/map_bridge/map_bridge.js"
    )
    packaged_path = Path(__file__).parents[1] / "web/map/qt_resources/map_bridge.js"
    meta_object = MapBridge.staticMetaObject
    method_names = {
        bytes(meta_object.method(index).name()).decode("ascii")
        for index in range(meta_object.methodOffset(), meta_object.methodCount())
    }

    assert "command_available" in method_names
    assert "receive_v2" in method_names
    assert bridge_path.read_bytes() == packaged_path.read_bytes()
