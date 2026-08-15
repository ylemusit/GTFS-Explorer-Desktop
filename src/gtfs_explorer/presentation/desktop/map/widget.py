"""Mapa MapLibre sin basemap para un único viaje seleccionado."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from PySide6.QtCore import QUrl
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from gtfs_explorer.application.queries.map_layers import (
    MapLayerPayload,
    MapViewport,
    simplify_for_viewport,
)
from gtfs_explorer.infrastructure.maps.loopback import MapPackageServer
from gtfs_explorer.infrastructure.maps.package import MapPackage, load_map_package
from gtfs_explorer.presentation.map_bridge import MapBridge, MapBridgeEvent


class MapWidget(QWidget):
    """Carga únicamente recursos locales y sincroniza clicks de parada con Qt."""

    def __init__(
        self,
        layers_for_trip: Callable[[str], MapLayerPayload],
        on_stop_selected: Callable[[str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._layers_for_trip = layers_for_trip
        self._on_stop_selected = on_stop_selected
        self._bridge = MapBridge()
        self._bridge.event_received.connect(self._event_received)
        self._bridge.event_received.connect(self._ready_event)
        self._payload: MapLayerPayload | None = None
        self._viewport_cache: dict[tuple[float, float, float, float, int], MapLayerPayload] = {}
        self._latest_viewport_request = 0
        self._package_server: MapPackageServer | None = None
        self._view = QWebEngineView(self)
        self._view.setObjectName("tripMap")
        self._view.setMinimumHeight(240)
        settings = self._view.settings()
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False
        )
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, False)
        channel = QWebChannel(self._view.page())
        channel.registerObject("mapBridge", self._bridge)
        self._view.page().setWebChannel(channel)
        self._channel = channel
        layout = QVBoxLayout(self)
        layout.addWidget(self._view)
        self._attribution = QLabel("Mapa sin paquete offline: fondo neutro.", self)
        self._attribution.setObjectName("mapAttribution")
        self._attribution.setWordWrap(True)
        layout.addWidget(self._attribution)
        assets = _map_assets_directory()
        html = (
            '<!doctype html><html><head><meta charset="utf-8">'
            "<style>html,body,#map{margin:0;width:100%;height:100%;}</style>"
            '<link rel="stylesheet" href="maplibre-gl.css"></head><body><div id="map"></div>'
            '<script src="qrc:///qtwebchannel/qwebchannel.js"></script>'
            '<script src="map_bundle.js"></script>'
            '<script src="map_bridge.js"></script><script src="map_layers.js"></script>'
            "</body></html>"
        )
        self._view.setHtml(html, QUrl(f"{assets.as_uri()}/"))

    def set_map_package(self, root: Path) -> MapPackage:
        """Carga un paquete previamente validado y mantiene visible su atribución."""
        package = load_map_package(root)
        if self._package_server is not None:
            self._package_server.close()
        server = MapPackageServer(package)
        server.start()
        self._package_server = server
        self._attribution.setText(package.attribution)
        # El contenido local solo puede alcanzar el loopback después de validar
        # íntegramente el paquete; el estilo nunca puede introducir URL remotas.
        self._view.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        style_url = server.url_for(PurePosixPath(package.style.relative_to(package.root)))
        pmtiles_url = server.url_for(PurePosixPath(package.basemap.relative_to(package.root)))
        self._view.page().runJavaScript(
            "window.GTFSExplorerLayers.setBasemap("
            f"{json.dumps(style_url)}, {json.dumps(pmtiles_url)})"
            ".catch((error) => window.GTFSExplorerMapBridge.mapError("
            "{message: String(error)}));"
        )
        return package

    def closeEvent(self, event: object) -> None:  # noqa: N802 - Qt API
        if self._package_server is not None:
            self._package_server.close()
            self._package_server = None
        super().closeEvent(event)  # type: ignore[arg-type]

    def clear(self) -> None:
        empty: dict[str, object] = {"type": "FeatureCollection", "features": []}
        self._payload = MapLayerPayload(empty, empty)
        self._viewport_cache.clear()
        self._flush()

    def show_trip(self, trip_id: str) -> None:
        self._payload = self._layers_for_trip(trip_id)
        self._viewport_cache.clear()
        self._latest_viewport_request = 0
        self._flush()

    def select_stop(self, stop_id: str) -> None:
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

    def _event_received(self, event: MapBridgeEvent) -> None:
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
            self._flush()


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
