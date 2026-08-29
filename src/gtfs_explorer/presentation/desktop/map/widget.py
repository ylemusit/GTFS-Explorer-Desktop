"""Mapa MapLibre con basemap intercambiable y overlay GTFS local."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings, QWebEngineUrlRequestInterceptor
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from gtfs_explorer.application.map_policy import (
    DEFAULT_ONLINE_MAP_PROVIDER,
    MapAvailability,
    MapCoverage,
    MapMode,
    MapPolicyDecision,
    MapRequestPolicy,
    OnlineMapProvider,
    normalize_map_mode,
    resolve_map_policy,
)
from gtfs_explorer.application.queries.map_layers import (
    MapLayerPayload,
    MapViewport,
    map_layer_bounds,
    simplify_for_viewport,
)
from gtfs_explorer.infrastructure.maps.loopback import MapPackageServer
from gtfs_explorer.infrastructure.maps.offline_library import OfflineMapLibrary, OfflineMapPackage
from gtfs_explorer.infrastructure.maps.package import MapPackage, load_map_package
from gtfs_explorer.presentation.desktop.i18n import t
from gtfs_explorer.presentation.map_bridge import MapBridge, MapBridgeEvent


class MapNetworkInterceptor(QWebEngineUrlRequestInterceptor):
    """Bloquea por defecto cualquier origen que no sea parte del mapa."""

    def __init__(self, policy: MapRequestPolicy) -> None:
        super().__init__()
        self._policy = policy
        self._blocked_requests = 0

    @property
    def blocked_requests(self) -> int:
        """Número de bloqueos, sin conservar las URLs potencialmente sensibles."""
        return self._blocked_requests

    def interceptRequest(self, info: object) -> None:  # noqa: N802 - API Qt
        url = info.requestUrl().toString()  # type: ignore[attr-defined]
        if self._policy.allows(url):
            return
        self._blocked_requests += 1
        info.block(True)  # type: ignore[attr-defined]


class MapWidget(QWidget):
    """Sincroniza un overlay GTFS con un basemap local o remoto."""

    def __init__(
        self,
        layers_for_trip: Callable[[str], MapLayerPayload],
        on_stop_selected: Callable[[str], None],
        parent: QWidget | None = None,
        mode: MapMode = MapMode.AUTO,
        provider: OnlineMapProvider | None = DEFAULT_ONLINE_MAP_PROVIDER,
    ) -> None:
        super().__init__(parent)
        self.setAccessibleName(t("accessibility.trip_map"))
        self.setAccessibleDescription(t("accessibility.trip_map_description"))
        self._layers_for_trip = layers_for_trip
        self._on_stop_selected = on_stop_selected
        self._mode = normalize_map_mode(mode)
        self._online_provider = provider
        self._map_package: MapPackage | None = None
        self._runtime_status: str | None = None
        self._has_map_context = False
        self._active_availability = MapAvailability.UNAVAILABLE
        self._active_package: MapPackage | None = None
        self._basemap_generation = 0
        self._selected_stop_id: str | None = None
        self._bridge = MapBridge()
        self._bridge.event_received.connect(self._event_received)
        self._bridge.event_received.connect(self._ready_event)
        self._payload: MapLayerPayload | None = None
        self._viewport_cache: dict[tuple[float, float, float, float, int], MapLayerPayload] = {}
        self._latest_viewport_request = 0
        self._package_server: MapPackageServer | None = None
        online_origins = () if provider is None else (provider.origin,)
        self._network_policy = MapRequestPolicy(self._mode, online_origins=online_origins)
        self._network_policy.set_active_availability(MapAvailability.UNAVAILABLE)
        self._view = QWebEngineView(self)
        self._view.setObjectName("tripMap")
        self._view.setAccessibleName(t("accessibility.map_canvas"))
        self._view.setAccessibleDescription(t("accessibility.map_canvas_description"))
        self._view.setMinimumHeight(240)
        settings = self._view.settings()
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False
        )
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, False)
        self._network_interceptor = MapNetworkInterceptor(self._network_policy)
        self._view.page().setUrlRequestInterceptor(self._network_interceptor)
        channel = QWebChannel(self._view.page())
        channel.registerObject("mapBridge", self._bridge)
        self._view.page().setWebChannel(channel)
        self._channel = channel
        layout = QVBoxLayout(self)
        layout.addWidget(self._view)
        self._attribution = QLabel("Mapa sin paquete offline: fondo neutro.", self)
        self._attribution.setObjectName("mapAttribution")
        self._attribution.setAccessibleName(t("accessibility.map_status"))
        self._attribution.setTextFormat(Qt.TextFormat.PlainText)
        self._attribution.setWordWrap(True)
        layout.addWidget(self._attribution)
        self._refresh_policy_status()
        assets = _map_assets_directory()
        html = (
            '<!doctype html><html><head><meta charset="utf-8">'
            '<meta name="referrer" content="no-referrer">'
            "<style>html,body,#map{margin:0;width:100%;height:100%;}</style>"
            '<link rel="stylesheet" href="maplibre-gl.css"></head><body><div id="map"></div>'
            '<script src="qrc:///qtwebchannel/qwebchannel.js"></script>'
            '<script src="map_bundle.js"></script>'
            '<script src="map_bridge.js"></script><script src="map_layers.js"></script>'
            "</body></html>"
        )
        self._view.setHtml(html, QUrl(f"{assets.as_uri()}/"))

    @property
    def map_mode(self) -> MapMode:
        return self._mode

    @property
    def availability(self) -> MapAvailability:
        if self._runtime_status is not None:
            return MapAvailability.UNAVAILABLE
        return self._policy_decision().availability

    @property
    def status_text(self) -> str:
        return self._attribution.text()

    @property
    def blocked_external_requests(self) -> int:
        return self._network_interceptor.blocked_requests

    def set_mode(self, mode: MapMode | str) -> str:
        """Cambia la preferencia y el basemap sin tocar el overlay GTFS."""
        self._mode = normalize_map_mode(mode)
        self._network_policy.set_mode(self._mode)
        self._runtime_status = None
        if self._mode is MapMode.ONLINE:
            self._has_map_context = True
        self._reconcile_basemap()
        return self.status_text

    def set_map_package(self, root: Path) -> MapPackage:
        """Carga un paquete previamente validado y mantiene visible su atribución."""
        package = load_map_package(root)
        self._map_package = package
        self._runtime_status = None
        self._has_map_context = True
        self._reconcile_basemap()
        return package

    def set_managed_map(self, library: OfflineMapLibrary, item: OfflineMapPackage) -> None:
        """Activa solo un paquete renderizable ya validado como bundle."""
        if not item.is_renderable:
            raise ValueError("PMTiles válido, pero estilo compatible no disponible.")
        self._map_package = load_map_package(library.package_root(item))
        self._runtime_status = None
        self._has_map_context = True
        self._reconcile_basemap()

    def clear_managed_map(self) -> None:
        """Desactiva el basemap local sin tocar el overlay del proyecto."""
        self._map_package = None
        self._runtime_status = None
        self._reconcile_basemap()

    def closeEvent(self, event: object) -> None:  # noqa: N802 - Qt API
        self._close_package_server()
        super().closeEvent(event)  # type: ignore[arg-type]

    def clear(self) -> None:
        empty: dict[str, object] = {"type": "FeatureCollection", "features": []}
        self._payload = MapLayerPayload(empty, empty)
        self._selected_stop_id = None
        self._viewport_cache.clear()
        self._flush()

    def show_trip(self, trip_id: str) -> None:
        self._payload = self._layers_for_trip(trip_id)
        self._selected_stop_id = None
        self._viewport_cache.clear()
        self._latest_viewport_request = 0
        self._has_map_context = True
        self._reconcile_basemap()
        self._flush()

    def select_stop(self, stop_id: str) -> None:
        self._selected_stop_id = stop_id
        self._view.page().runJavaScript(
            f"window.GTFSExplorerLayers.selectStop({json.dumps(stop_id)});"
        )

    def _flush(self) -> None:
        if self._payload is None or not self._bridge.ready:
            return
        # Antes del primer viewport el presupuesto global evita transferir el
        # viaje completo al proceso WebEngine.
        payload = simplify_for_viewport(self._payload, MapViewport(-180, -90, 180, 90, 0))
        serialized = json.dumps(
            {"shapes": payload.shapes, "stops": payload.stops}, ensure_ascii=False
        )
        self._view.page().runJavaScript(
            f"window.GTFSExplorerLayers.replace({serialized}, true, true);"
        )
        if self._selected_stop_id is not None:
            self._view.page().runJavaScript(
                f"window.GTFSExplorerLayers.selectStop({json.dumps(self._selected_stop_id)});"
            )

    def _event_received(self, event: MapBridgeEvent) -> None:
        if event.event == "mapError":
            request = event.payload.get("request")
            if type(request) is int and request != self._basemap_generation:
                return
            source = event.payload.get("source")
            self._runtime_status = (
                "Online no disponible"
                if source == MapAvailability.ONLINE.value
                else "Mapa no disponible"
            )
            self._activate_neutral()
            self._refresh_policy_status()
            return
        if event.event == "viewportChanged":
            self._viewport_changed(event)
            return
        if event.event != "featureClicked" or event.payload.get("kind") != "stop":
            return
        stop_id = event.payload.get("id")
        if isinstance(stop_id, str):
            self._on_stop_selected(stop_id)

    def _viewport_changed(self, event: MapBridgeEvent) -> None:
        if self._payload is None:
            return
        request = event.payload.get("request")
        values = tuple(event.payload.get(key) for key in ("west", "south", "east", "north", "zoom"))
        if not isinstance(request, int) or not all(
            isinstance(value, (int, float)) for value in values
        ):
            return
        if request < self._latest_viewport_request:
            return
        self._latest_viewport_request = request
        west, south, east, north, zoom = (
            float(value) for value in values if isinstance(value, (int, float))
        )
        key = (round(west, 3), round(south, 3), round(east, 3), round(north, 3), round(zoom))
        payload = self._viewport_cache.get(key)
        if payload is None:
            payload = simplify_for_viewport(
                self._payload, MapViewport(west, south, east, north, zoom)
            )
            if len(self._viewport_cache) >= 32:
                self._viewport_cache.pop(next(iter(self._viewport_cache)))
            self._viewport_cache[key] = payload
        if request != self._latest_viewport_request:
            return
        serialized = json.dumps(
            {"shapes": payload.shapes, "stops": payload.stops}, ensure_ascii=False
        )
        self._view.page().runJavaScript(
            f"window.GTFSExplorerLayers.replace({serialized}, false, false);"
        )

    def _ready_event(self, event: MapBridgeEvent) -> None:
        if event.event == "mapReady":
            self._apply_active_basemap()
            self._flush()

    def _policy_decision(self) -> MapPolicyDecision:
        coverage = self._coverage()
        return resolve_map_policy(
            self._mode,
            local_available=(
                self._has_map_context
                and self._map_package is not None
                and coverage is not MapCoverage.OUTSIDE_LOCAL_COVERAGE
            ),
            online_available=self._has_map_context and self._online_provider is not None,
            coverage=coverage,
            provider_name=None if self._online_provider is None else self._online_provider.name,
        )

    def _refresh_policy_status(self) -> None:
        if self._runtime_status is not None:
            if self._runtime_status == "Online no disponible":
                self._attribution.setText("Mapa · Online no disponible")
            else:
                self._attribution.setText("Mapa · No disponible")
            return
        decision = self._policy_decision()
        if decision.availability is MapAvailability.LOCAL:
            text = "Mapa · Offline · PMTiles"
        elif decision.availability is MapAvailability.ONLINE and self._online_provider is not None:
            text = f"Mapa · Online · {self._online_provider.name}"
        elif decision.coverage is MapCoverage.OUTSIDE_LOCAL_COVERAGE:
            text = "Mapa · Sin cobertura offline"
        else:
            # Conserva el prefijo histórico para el estado inicial sin proyecto.
            text = f"Mapa: no disponible · {decision.reason}"
        if decision.availability is MapAvailability.LOCAL and self._map_package is not None:
            text = f"{text} · {self._map_package.attribution}"
        elif decision.availability is MapAvailability.ONLINE and self._online_provider is not None:
            text = f"{text} · {self._online_provider.attribution}"
        self._attribution.setText(text)

    def _activate_local_package(self, package: MapPackage) -> None:
        self._close_package_server()
        server = MapPackageServer(package)
        server.start()
        self._package_server = server
        self._network_policy.set_local_origin(server.origin)
        self._runtime_status = None
        self._active_availability = MapAvailability.LOCAL
        self._active_package = package
        self._network_policy.set_active_availability(MapAvailability.LOCAL)
        self._basemap_generation += 1
        # El contenido local solo puede alcanzar el loopback después de validar
        # íntegramente el paquete; el interceptor sigue bloqueando Internet.
        self._view.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        self._refresh_policy_status()

        self._apply_active_basemap()

    def _activate_online(self) -> None:
        provider = self._online_provider
        if provider is None:
            self._activate_neutral()
            return
        self._close_package_server()
        self._runtime_status = None
        self._active_availability = MapAvailability.ONLINE
        self._active_package = None
        self._network_policy.set_active_availability(MapAvailability.ONLINE)
        self._basemap_generation += 1
        self._view.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        self._refresh_policy_status()
        self._apply_active_basemap()

    def _activate_neutral(self) -> None:
        self._close_package_server()
        self._active_availability = MapAvailability.UNAVAILABLE
        self._active_package = None
        self._network_policy.set_active_availability(MapAvailability.UNAVAILABLE)
        self._basemap_generation += 1
        self._view.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False
        )
        self._apply_active_basemap()

    def _apply_active_basemap(self) -> None:
        """Aplica solo el basemap; el último payload GTFS queda en la página."""
        if not self._bridge.ready:
            return
        request = self._basemap_generation
        if self._active_availability is MapAvailability.LOCAL:
            package = self._active_package
            server = self._package_server
            if package is None or server is None:
                return
            style_url = server.url_for(PurePosixPath(package.style.relative_to(package.root)))
            pmtiles_url = server.url_for(PurePosixPath(package.basemap.relative_to(package.root)))
            script = (
                "window.GTFSExplorerLayers.setBasemap("
                f"{json.dumps(style_url)}, {json.dumps(pmtiles_url)}, {request})"
                ".catch(() => window.GTFSExplorerMapBridge.mapError("
                f"{{source: 'local', kind: 'style', request: {request}}}));"
            )
        elif self._active_availability is MapAvailability.ONLINE:
            provider = self._online_provider
            if provider is None:
                return
            script = (
                "window.GTFSExplorerLayers.setOnlineBasemap("
                f"{json.dumps(provider.tile_url_template)}, {provider.tile_size}, "
                f"{provider.min_zoom}, {provider.max_zoom}, {request})"
                ".catch(() => window.GTFSExplorerMapBridge.mapError("
                f"{{source: 'online', kind: 'style', request: {request}}}));"
            )
        else:
            script = f"window.GTFSExplorerLayers.clearBasemap({request});"
        self._view.page().runJavaScript(script)

    def _reconcile_basemap(self) -> None:
        if not self._has_map_context:
            self._network_policy.set_active_availability(MapAvailability.UNAVAILABLE)
            self._refresh_policy_status()
            return
        decision = self._policy_decision()
        if decision.availability is MapAvailability.LOCAL and self._map_package is not None:
            if (
                self._active_availability is MapAvailability.LOCAL
                and self._active_package == self._map_package
            ):
                self._refresh_policy_status()
            else:
                self._activate_local_package(self._map_package)
            return
        if decision.availability is MapAvailability.ONLINE and self._online_provider is not None:
            if self._active_availability is MapAvailability.ONLINE:
                self._refresh_policy_status()
            else:
                self._activate_online()
            return
        if self._active_availability is not MapAvailability.UNAVAILABLE:
            self._activate_neutral()
        else:
            self._network_policy.set_active_availability(MapAvailability.UNAVAILABLE)
            self._refresh_policy_status()

    def _coverage(self) -> MapCoverage:
        if self._map_package is None or self._payload is None:
            return MapCoverage.UNKNOWN_COVERAGE
        bounds = map_layer_bounds(self._payload)
        if bounds is None:
            return MapCoverage.UNKNOWN_COVERAGE
        west, south, east, north = bounds
        package_west, package_south, package_east, package_north = self._map_package.bbox
        if (
            package_west <= west <= east <= package_east
            and package_south <= south <= north <= package_north
        ):
            return MapCoverage.LOCAL_COVERAGE
        return MapCoverage.OUTSIDE_LOCAL_COVERAGE

    def _close_package_server(self) -> None:
        server = self._package_server
        self._package_server = None
        self._network_policy.set_local_origin(None)
        if server is not None:
            server.close()


def _map_assets_directory() -> Path:
    """Localiza el bundle del mapa sin depender del directorio de trabajo.

    El portable deja ``web/`` junto al ejecutable; durante el desarrollo se
    usa el árbol del repositorio. Ninguna de las dos rutas se obtiene del cwd.
    """
    packaged = Path(sys.executable).resolve().parent / "web" / "map" / "qt_resources"
    if packaged.is_dir():
        return packaged
    repository = Path(__file__).resolve().parents[5] / "web" / "map" / "qt_resources"
    if repository.is_dir():
        return repository
    raise FileNotFoundError("No se encuentran los recursos locales del mapa.")
