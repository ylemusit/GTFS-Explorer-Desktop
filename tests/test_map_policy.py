from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from PySide6.QtCore import QUrl

from gtfs_explorer.application.map_policy import (
    MapAvailability,
    MapMode,
    MapPolicyError,
    MapRequestPolicy,
    build_external_tile_url,
    resolve_map_policy,
)
from gtfs_explorer.presentation.desktop.map.widget import MapNetworkInterceptor


@pytest.mark.parametrize(
    ("mode", "local", "online", "availability"),
    (
        (MapMode.AUTO, True, True, MapAvailability.LOCAL),
        (MapMode.AUTO, False, False, MapAvailability.UNAVAILABLE),
        (MapMode.OFFLINE, True, True, MapAvailability.LOCAL),
        (MapMode.OFFLINE, False, True, MapAvailability.UNAVAILABLE),
        (MapMode.ONLINE, False, True, MapAvailability.ONLINE),
    ),
)
def test_map_modes_resolve_with_local_priority_and_without_network_probe(
    mode: MapMode,
    local: bool,
    online: bool,
    availability: MapAvailability,
) -> None:
    decision = resolve_map_policy(mode, local_available=local, online_available=online)

    assert decision.availability is availability
    assert decision.source_label in {"local/offline", "online", "no disponible"}


def test_auto_without_local_or_configured_provider_is_unavailable() -> None:
    decision = resolve_map_policy(MapMode.AUTO, local_available=False)

    assert decision.availability is MapAvailability.UNAVAILABLE
    assert "No hay paquete local" in decision.reason
    assert decision.status_text.startswith("Mapa: no disponible")


def test_offline_request_policy_allows_only_local_resources_and_loopback() -> None:
    policy = MapRequestPolicy(MapMode.OFFLINE, local_origin="http://127.0.0.1:43123")

    assert policy.allows("file:///C:/map/map_layers.js")
    assert policy.allows("qrc:///qtwebchannel/qwebchannel.js")
    assert policy.allows("http://127.0.0.1:43123/session/basemap.pmtiles")
    assert not policy.allows("http://127.0.0.1:43124/session/basemap.pmtiles")
    assert not policy.allows("https://tiles.example/12/1/2.pbf")
    assert not policy.allows("https://tiles.example/12/1/2.pbf?route_id=R1")


def test_online_policy_allows_only_an_explicit_origin_without_fallback() -> None:
    policy = MapRequestPolicy(MapMode.ONLINE, online_origins=("https://tiles.example/",))

    assert policy.allows("https://tiles.example/12/1/2.pbf")
    assert not policy.allows("https://other.example/12/1/2.pbf")
    assert not policy.allows("https://tiles.example/12/1/2.pbf?token=secret")


@dataclass
class _RequestInfo:
    url: str
    blocked: bool = False

    def requestUrl(self) -> QUrl:  # noqa: N802 - API Qt
        return QUrl(self.url)

    def block(self, value: bool) -> None:
        self.blocked = value


def test_offline_interceptor_blocks_external_requests_without_retaining_urls() -> None:
    policy = MapRequestPolicy(MapMode.OFFLINE, local_origin="http://127.0.0.1:43123")
    interceptor = MapNetworkInterceptor(policy)
    info = _RequestInfo("https://tiles.example/12/1/2.pbf?trip_id=T1")

    interceptor.interceptRequest(info)

    assert info.blocked
    assert interceptor.blocked_requests == 1
    assert not hasattr(interceptor, "blocked_urls")


def test_external_tile_url_contains_only_xyz_and_rejects_context_or_credentials() -> None:
    url = build_external_tile_url("https://tiles.example/{z}/{x}/{y}.pbf", z=12, x=1, y=2)

    assert url == "https://tiles.example/12/1/2.pbf"
    assert all(value not in url for value in ("route_id", "trip_id", "stop_id", "workspace"))
    assert "token" not in url.casefold()
    assert "key" not in url.casefold()

    invalid_templates = (
        "https://tiles.example/{z}/{x}/{y}.pbf?api_key=secret",
        "https://tiles.example/{z}/{x}/{y}/{route_id}.pbf",
        "https://tiles.example/token/{z}/{x}/{y}.pbf",
        "https://tiles.example/{z}/{x}/{y}.pbf#workspace",
    )
    for template in invalid_templates:
        with pytest.raises(MapPolicyError):
            build_external_tile_url(template, z=12, x=1, y=2)


def test_map_policy_labels_the_three_visible_states() -> None:
    assert resolve_map_policy(MapMode.OFFLINE, local_available=True).source_label == "local/offline"
    assert (
        resolve_map_policy(
            MapMode.ONLINE, local_available=False, online_available=True
        ).source_label
        == "online"
    )
    assert (
        resolve_map_policy(MapMode.OFFLINE, local_available=False).source_label == "no disponible"
    )


def test_runtime_map_assets_have_neutral_fallback_and_no_remote_provider_or_tracking() -> None:
    root = Path(__file__).parents[1]
    layers = (root / "src/gtfs_explorer/presentation/desktop/map/map_layers.js").read_text(
        encoding="utf-8"
    )
    app = (root / "web/map/src/app.js").read_text(encoding="utf-8")

    assert "clearBasemap" in layers
    assert "neutralStyle" in layers
    assert "http://" not in layers and "https://" not in layers
    assert "http://" not in app and "https://" not in app
    assert "analytics" not in f"{layers}\n{app}".casefold()
    assert "telemetry" not in f"{layers}\n{app}".casefold()
