"""Mapa MapLibre con basemap intercambiable y overlay GTFS local."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Mapping
from pathlib import Path, PurePosixPath

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings, QWebEngineUrlRequestInterceptor
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from gtfs_explorer.application.map_editing import MapEditMode
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
    _route_line_width,
    map_layer_bounds,
    simplify_for_viewport,
)
from gtfs_explorer.domain.changesets import RouteWorkspaceState
from gtfs_explorer.infrastructure.maps.loopback import MapPackageServer
from gtfs_explorer.infrastructure.maps.offline_library import OfflineMapLibrary, OfflineMapPackage
from gtfs_explorer.infrastructure.maps.package import MapPackage, load_map_package
from gtfs_explorer.performance_gate import GateTrace, mark
from gtfs_explorer.presentation.desktop.i18n import t
from gtfs_explorer.presentation.map_bridge import (
    MapBridge,
    MapBridgeEvent,
    MapEditGesture,
    MapFitBounds,
)


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

    supports_async_rebuild = True

    def __init__(
        self,
        layers_for_trip: Callable[[str], MapLayerPayload],
        on_stop_selected: Callable[[str], None],
        parent: QWidget | None = None,
        mode: MapMode = MapMode.AUTO,
        provider: OnlineMapProvider | None = DEFAULT_ONLINE_MAP_PROVIDER,
        on_edit_gesture: Callable[[MapEditGesture], None] | None = None,
        performance_trace: GateTrace | None = None,
        on_stop_action: Callable[[str, str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName(t("accessibility.trip_map"))
        self.setAccessibleDescription(t("accessibility.trip_map_description"))
        self._layers_for_trip = layers_for_trip
        self._on_stop_selected = on_stop_selected
        self._on_edit_gesture = on_edit_gesture
        self._on_stop_action = on_stop_action
        self._performance_trace = performance_trace
        self._edit_mode = MapEditMode.NORMAL
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
        self._bridge.edit_event_received.connect(self._edit_event_received)
        self._bridge.event_received.connect(self._ready_event)
        self._payload: MapLayerPayload | None = None
        self._performance_generation: int | None = None
        self._fit_payload = True
        self._reset_selection_on_flush = True
        self._viewport_cache: dict[tuple[float, float, float, float, int], MapLayerPayload] = {}
        self._latest_viewport_request = 0
        self._package_server: MapPackageServer | None = None
        online_origins = () if provider is None else (provider.origin,)
        self._network_policy = MapRequestPolicy(self._mode, online_origins=online_origins)
        self._network_policy.set_active_availability(MapAvailability.UNAVAILABLE)
        self._view = QWebEngineView(self)
        self._view.setObjectName("tripMap")
        self._view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
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
        layout.addWidget(self._view, 1)
        self._attribution = QLabel(t("map.neutral_attribution"), self)
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

    def set_stop_action_handler(self, handler: Callable[[str, str], None] | None) -> None:
        """Conecta las acciones de la Stop Card sin duplicar el modelo del popup."""
        self._on_stop_action = handler

    def set_ui_texts(self) -> None:
        """Actualiza etiquetas del popup sin tocar el payload GTFS."""
        texts = {
            "stopNameUnknown": t("stop.name_unknown"),
            "routeChip": t("stop.route_chip", short_name="").strip(),
            "route": t("stop.route"),
            "origin": t("stop.origin"),
            "intermediate": t("stop.intermediate"),
            "destination": t("stop.destination"),
            "operations": t("stop.operations"),
            "scheduledTime": t("stop.scheduled_time"),
            "arrival": t("stop.arrival"),
            "departure": t("stop.departure"),
            "sequence": t("stop.sequence"),
            "previous": t("stop.previous"),
            "next": t("stop.next"),
            "dwell": t("stop.dwell"),
            "context": t("stop.context"),
            "agency": t("stop.agency"),
            "trip": t("stop.trip"),
            "service": t("stop.service"),
            "headsign": t("stop.headsign"),
            "technical": t("stop.technical"),
            "otherRoutes": t("stop.other_routes"),
            "stopId": t("stop.stop_id"),
            "routeId": t("stop.route_id"),
            "actions": t("stop.actions"),
            "center": t("stop.center"),
            "edit": t("stop.edit"),
            "details": t("stop.details"),
            "notAvailable": t("stop.not_available"),
        }
        if self._bridge.ready:
            self._view.page().runJavaScript(
                f"window.GTFSExplorerLayers.setUiTexts({json.dumps(texts, ensure_ascii=False)});"
            )

    def retranslate_ui(self) -> None:
        """Actualiza accesibilidad, estado del mapa y textos del popup."""
        self.setAccessibleName(t("accessibility.trip_map"))
        self.setAccessibleDescription(t("accessibility.trip_map_description"))
        self._view.setAccessibleName(t("accessibility.map_canvas"))
        self._view.setAccessibleDescription(t("accessibility.map_canvas_description"))
        self._attribution.setAccessibleName(t("accessibility.map_status"))
        self._refresh_policy_status()
        self.set_ui_texts()

    @property
    def map_mode(self) -> MapMode:
        return self._mode

    def set_edit_gesture_handler(self, handler: Callable[[MapEditGesture], None] | None) -> None:
        """Conecta el destino de gestos sin cambiar la firma histórica del widget."""
        self._on_edit_gesture = handler

    @property
    def edit_mode(self) -> MapEditMode:
        return self._edit_mode

    def set_edit_mode(self, mode: MapEditMode | str) -> MapEditMode:
        """Activa un modo cartográfico explícito; NORMAL no permite mutaciones."""
        try:
            normalized = mode if isinstance(mode, MapEditMode) else MapEditMode(str(mode))
        except ValueError:
            normalized = MapEditMode.NORMAL
        self._edit_mode = normalized
        if self._bridge.ready:
            self._view.page().runJavaScript(
                f"window.GTFSExplorerLayers.setEditMode({json.dumps(normalized.value)});"
            )
        return normalized

    def set_vertex_action(self, action: str | None) -> None:
        """Arma una acción geométrica que requiere un clic posterior explícito."""
        if self._bridge.ready:
            self._view.page().runJavaScript(
                f"window.GTFSExplorerLayers.setVertexAction({json.dumps(action)});"
            )

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

    def refresh_host(self) -> None:
        """Recalcula el viewport tras un reparenting del único WebEngine."""
        self.updateGeometry()
        self._view.setGeometry(self.contentsRect())
        self._view.show()
        self._view.update()
        self.update()

        def resize_map() -> None:
            self._view.setGeometry(self.contentsRect())
            if self._bridge.ready:
                self._view.page().runJavaScript(
                    "if (window.GTFSExplorerLayers) window.GTFSExplorerLayers.resize();"
                )

        QTimer.singleShot(0, resize_map)

    def clear(self) -> None:
        empty: dict[str, object] = {"type": "FeatureCollection", "features": []}
        self._performance_generation = None
        self._payload = MapLayerPayload(empty, empty)
        self._selected_stop_id = None
        self._fit_payload = False
        self._reset_selection_on_flush = True
        self._viewport_cache.clear()
        self.set_edit_mode(MapEditMode.NORMAL)
        self._flush()

    def show_trip(self, trip_id: str) -> None:
        self.show_payload(self._layers_for_trip(trip_id))

    def show_payload(
        self,
        payload: MapLayerPayload,
        *,
        fit: bool = True,
        reset_selection: bool = True,
        generation: int | None = None,
    ) -> None:
        """Muestra un overlay ya validado, incluido un conjunto de rutas."""
        self._performance_generation = generation
        mark(
            self._performance_trace,
            "T10_MAPWIDGET_SHOW_PAYLOAD",
            generation=generation,
        )
        self._payload = payload
        if reset_selection:
            self._selected_stop_id = None
        self._fit_payload = fit
        self._reset_selection_on_flush = reset_selection
        self._viewport_cache.clear()
        self._latest_viewport_request = 0
        self._has_map_context = True
        self._reconcile_basemap()
        self._flush()

    def update_route_states(self, states: Mapping[str, RouteWorkspaceState]) -> None:
        """Actualiza propiedades visuales sin reconstruir geometrías ni encuadrar."""
        if not states:
            return
        if self._payload is not None:
            self._payload = _update_payload_route_states(self._payload, states)
            self._viewport_cache.clear()
        if not self._bridge.ready:
            return
        serialized = json.dumps(
            [
                {
                    "route_id": route_id,
                    "visible": state.visible,
                    "active": state.active,
                    "editable": state.editable,
                    "locked": state.locked,
                    "dimmed": state.dimmed,
                }
                for route_id, state in states.items()
            ],
            ensure_ascii=False,
        )
        self._view.page().runJavaScript(
            f"window.GTFSExplorerLayers.updateRouteStates({serialized});"
        )

    def update_route_selection(self, route_id: str | None) -> None:
        """Mueve el énfasis de inspección sin recalcular geometría GTFS."""
        if self._payload is not None:
            self._payload = _update_payload_route_selection(self._payload, route_id)
        if self._bridge.ready:
            self._view.page().runJavaScript(
                "window.GTFSExplorerLayers.updateRouteSelection("
                f"{json.dumps(route_id, ensure_ascii=False)});"
            )

    def fit_bounds(self, bounds: tuple[float, float, float, float] | None) -> None:
        """Encuadra un contexto GTFS sin modificar las capas ni el modo de mapa."""
        if bounds is None:
            return
        try:
            self._bridge.navigate(MapFitBounds(*bounds))
        except ValueError:
            return

    def select_stop(self, stop_id: str) -> None:
        self._selected_stop_id = stop_id
        self._view.page().runJavaScript(
            f"window.GTFSExplorerLayers.selectStop({json.dumps(stop_id)});"
        )

    def center_stop(self, stop_id: str) -> None:
        """Centra la parada usando la geometría ya cargada en MapLibre."""
        self._selected_stop_id = stop_id
        self._view.page().runJavaScript(
            f"window.GTFSExplorerLayers.centerStop({json.dumps(stop_id)});"
        )

    def _flush(self) -> None:
        if self._payload is None or not self._bridge.ready:
            return
        # Antes del primer viewport el presupuesto global evita transferir el
        # viaje completo al proceso WebEngine.
        payload = simplify_for_viewport(self._payload, MapViewport(-180, -90, 180, 90, 0))
        mark(
            self._performance_trace,
            "T8_SERIALIZATION_STARTED",
            generation=self._performance_generation,
        )
        serialized = json.dumps(
            {
                "shapes": payload.shapes,
                "stops": payload.stops,
                "shape_points": payload.shape_points,
            },
            ensure_ascii=False,
        )
        payload_bytes = len(serialized.encode("utf-8"))
        mark(
            self._performance_trace,
            "T8_SERIALIZATION_FINISHED",
            generation=self._performance_generation,
            payload_bytes=payload_bytes,
        )
        mark(
            self._performance_trace,
            "T11_RUNJAVASCRIPT_STARTED",
            generation=self._performance_generation,
            payload_bytes=payload_bytes,
        )
        mark(
            self._performance_trace,
            "T12_MAPLIBRE_SETDATA_STARTED",
            generation=self._performance_generation,
            payload_bytes=payload_bytes,
        )
        self._view.page().runJavaScript(
            "window.GTFSExplorerLayers.replace("
            f"{serialized}, {str(self._fit_payload).lower()}, "
            f"{str(self._reset_selection_on_flush).lower()}, "
            f"{json.dumps(self._performance_generation)});"
        )
        self._fit_payload = False
        self._reset_selection_on_flush = False
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
            action = event.payload.get("action")
            if isinstance(action, str) and self._on_stop_action is not None:
                self._on_stop_action(stop_id, action)
            self._on_stop_selected(stop_id)

    def _edit_event_received(self, gesture: MapEditGesture) -> None:
        if self._on_edit_gesture is not None:
            self._on_edit_gesture(gesture)

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
            {
                "shapes": payload.shapes,
                "stops": payload.stops,
                "shape_points": payload.shape_points,
            },
            ensure_ascii=False,
        )
        self._view.page().runJavaScript(
            f"window.GTFSExplorerLayers.replace({serialized}, false, false);"
        )

    def _ready_event(self, event: MapBridgeEvent) -> None:
        if event.event == "mapReady":
            self._apply_active_basemap()
            self.set_ui_texts()
            self.set_edit_mode(self._edit_mode)
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
                self._attribution.setText(t("map.status_online_unavailable"))
            else:
                self._attribution.setText(t("map.status_unavailable"))
            return
        decision = self._policy_decision()
        if decision.availability is MapAvailability.LOCAL:
            text = t("map.status_offline")
        elif decision.availability is MapAvailability.ONLINE and self._online_provider is not None:
            text = t("map.status_online", provider=self._online_provider.name)
        elif decision.coverage is MapCoverage.OUTSIDE_LOCAL_COVERAGE:
            text = t("map.status_outside_coverage")
        else:
            text = f"{t('map.status_no_map')} · {decision.reason}"
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


def _update_payload_route_states(
    payload: MapLayerPayload,
    states: Mapping[str, RouteWorkspaceState],
) -> MapLayerPayload:
    def update_collection(collection: dict[str, object]) -> dict[str, object]:
        features = collection.get("features")
        if not isinstance(features, list):
            return collection
        updated: list[dict[str, object]] = []
        for feature in features:
            if not isinstance(feature, dict):
                continue
            properties = feature.get("properties")
            route_id = properties.get("route_id") if isinstance(properties, dict) else None
            state = states.get(str(route_id)) if route_id is not None else None
            if state is None:
                updated.append(feature)
                continue
            updated.append(
                {
                    **feature,
                    "properties": {
                        **(properties if isinstance(properties, dict) else {}),
                        "dimmed": state.dimmed,
                        "route_visible": state.visible,
                        "route_active": state.active,
                        "route_editable": state.editable,
                        "route_locked": state.locked,
                        **(
                            {
                                "line_width": _route_line_width(
                                    _shared_route_count(properties.get("shared_route_count")),
                                    active=state.active,
                                )
                            }
                            if isinstance(properties, dict) and "line_width" in properties
                            else {}
                        ),
                    },
                }
            )
        return {**collection, "features": updated}

    return MapLayerPayload(
        update_collection(payload.shapes),
        update_collection(payload.stops),
        update_collection(payload.shape_points or {"type": "FeatureCollection", "features": []}),
    )


def _update_payload_route_selection(
    payload: MapLayerPayload, route_id: str | None
) -> MapLayerPayload:
    """Reetiqueta features existentes; no consulta ni genera geometrías."""

    def update_collection(collection: dict[str, object]) -> dict[str, object]:
        features = collection.get("features")
        if not isinstance(features, list):
            return collection
        return {
            **collection,
            "features": [
                {
                    **feature,
                    "properties": {
                        **(properties if isinstance(properties, dict) else {}),
                        "route_selected": (
                            isinstance(properties, dict)
                            and str(properties.get("route_id")) == route_id
                        ),
                    },
                }
                if isinstance(feature, dict)
                and isinstance((properties := feature.get("properties")), dict)
                else feature
                for feature in features
            ],
        }

    return MapLayerPayload(
        update_collection(payload.shapes),
        update_collection(payload.stops),
        update_collection(payload.shape_points or {"type": "FeatureCollection", "features": []}),
    )


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


def _shared_route_count(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return max(1, value)
    if isinstance(value, str):
        try:
            return max(1, int(value))
        except ValueError:
            pass
    return 1
