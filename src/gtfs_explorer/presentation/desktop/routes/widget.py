"""Controles encadenados ruta, servicio, direction_id y viaje."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from gtfs_explorer.application.map_policy import MapMode
from gtfs_explorer.application.queries.map_layers import MapLayerPayload
from gtfs_explorer.application.queries.timetable import TimetableMatrix
from gtfs_explorer.domain.ports import PagedResult
from gtfs_explorer.domain.route_types import format_route_type
from gtfs_explorer.domain.routes import (
    DirectionSummary,
    RouteSummary,
    ServiceSummary,
    TimelineStop,
    TripSummary,
)
from gtfs_explorer.domain.stops import StopInspection
from gtfs_explorer.infrastructure.maps.offline_library import OfflineMapLibrary, OfflineMapPackage
from gtfs_explorer.presentation.desktop.i18n import t
from gtfs_explorer.presentation.desktop.map.widget import MapWidget
from gtfs_explorer.presentation.desktop.map.window import MapWindow
from gtfs_explorer.presentation.desktop.stops.widget import StopInspectorWidget
from gtfs_explorer.presentation.desktop.timetable.widget import TimetableWidget
from gtfs_explorer.presentation.desktop.trips.widget import TripTimelineWidget


class RouteExplorerWidget(QWidget):
    """Mantiene una única selección relacional y reinicia descendientes de forma determinista."""

    def __init__(
        self,
        routes: Callable[[], PagedResult[RouteSummary]],
        services: Callable[[str], PagedResult[ServiceSummary]],
        directions: Callable[[str, str], PagedResult[DirectionSummary]],
        trips: Callable[[str, str, int | None], PagedResult[TripSummary]],
        timeline: Callable[[str], PagedResult[TimelineStop]],
        inspect_stop: Callable[[str], StopInspection],
        matrix: Callable[[str, str, int | None], TimetableMatrix],
        map_layers_for_trip: Callable[[str], MapLayerPayload] | None = None,
        splitter_state: bytes | None = None,
        save_splitter_state: Callable[[bytes], bool] | None = None,
        parent: QWidget | None = None,
        feed_bounds: Callable[[], tuple[float, float, float, float] | None] | None = None,
        route_bounds: Callable[[str], tuple[float, float, float, float] | None] | None = None,
        map_window_geometry: bytes | None = None,
        map_window_maximized: bool = False,
        save_map_window_geometry: Callable[[bytes, bool], bool] | None = None,
        on_return_to_data: Callable[[], None] | None = None,
        on_dock_to_explore: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._routes_query, self._services_query, self._directions_query = (
            routes,
            services,
            directions,
        )
        self._trips_query, self._matrix_query = trips, matrix
        self._feed_bounds, self._route_bounds = feed_bounds, route_bounds
        self._saved_splitter_state = splitter_state
        self._save_splitter_state = save_splitter_state
        self._map_window_geometry = map_window_geometry
        self._map_window_maximized = map_window_maximized
        self._save_map_window_geometry = save_map_window_geometry
        self._on_return_to_data = on_return_to_data
        self._on_dock_to_explore = on_dock_to_explore
        self._map_window: MapWindow | None = None
        self._splitter_restored = False
        layout = QVBoxLayout(self)
        filters = QGroupBox(t("routes.filters"))
        form = QFormLayout(filters)
        self._routes = QComboBox()
        _make_searchable(self._routes)
        self._routes.setObjectName("routeSelector")
        self._routes.setAccessibleName(t("routes.route_selector"))
        self._services = QComboBox()
        _make_searchable(self._services)
        self._services.setObjectName("serviceSelector")
        self._services.setAccessibleName(t("routes.service_selector"))
        self._directions = QComboBox()
        _make_searchable(self._directions)
        self._directions.setObjectName("directionSelector")
        self._directions.setAccessibleName(t("routes.direction_selector"))
        self._trips = QComboBox()
        _make_searchable(self._trips)
        self._trips.setObjectName("tripSelector")
        self._trips.setAccessibleName(t("routes.trip_selector"))
        for label_text, selector in (
            (t("routes.route"), self._routes),
            (t("routes.service"), self._services),
            (t("routes.direction"), self._directions),
            (t("routes.trip"), self._trips),
        ):
            label = QLabel(label_text)
            label.setBuddy(selector)
            form.addRow(label, selector)
        matrix_button = QPushButton(t("routes.matrix"))
        matrix_button.setAccessibleName(t("routes.matrix"))
        matrix_button.setAccessibleDescription(t("routes.matrix_description"))
        matrix_button.setToolTip(t("routes.matrix_description"))
        matrix_button.clicked.connect(self._show_matrix)
        form.addRow(matrix_button)
        layout.addWidget(filters)
        self._layout_actions = QWidget(self)
        actions_layout = QHBoxLayout(self._layout_actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        open_map = QPushButton("Abrir en ventana", self._layout_actions)
        open_map.setObjectName("openMapWindow")
        open_map.setAccessibleName("Abrir en ventana")
        open_map.setToolTip("Abre el mapa en una ventana independiente.")
        open_map.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        open_map.clicked.connect(self.open_map)
        actions_layout.addWidget(open_map)
        actions_layout.addStretch()
        layout.addWidget(self._layout_actions)
        details = QHBoxLayout()
        self._timeline = TripTimelineWidget(timeline, self._show_stop)
        self._stops = StopInspectorWidget(inspect_stop)
        details.addWidget(self._timeline)
        details.addWidget(self._stops)
        details_widget = QWidget(self)
        details_widget.setLayout(details)
        self._map = MapWidget(map_layers_for_trip, self._show_stop) if map_layers_for_trip else None
        self._workspace_splitter: QSplitter | None
        if self._map is not None:
            # QSplitter no hereda el mínimo del QWebEngineView anidado; conserva
            # explícitamente el mínimo funcional auditado del mapa.
            self._map.setMinimumHeight(240)
            details_widget.setMinimumHeight(180)
            self._workspace_splitter = QSplitter(Qt.Orientation.Vertical, self)
            self._workspace_splitter.setObjectName("exploreWorkspaceSplitter")
            self._workspace_splitter.setAccessibleName("Área redimensionable de datos y mapa")
            self._workspace_splitter.addWidget(details_widget)
            self._map_host: QWidget | None = QWidget(self)
            self._map_host.setObjectName("embeddedMapHost")
            self._map_host.setMinimumHeight(240)
            self._map_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            map_layout = QVBoxLayout(self._map_host)
            map_layout.setContentsMargins(0, 0, 0, 0)
            map_layout.addWidget(self._map, 1)
            self._workspace_splitter.addWidget(self._map_host)
            self._workspace_splitter.setStretchFactor(0, 1)
            self._workspace_splitter.setStretchFactor(1, 1)
            self._workspace_splitter.setChildrenCollapsible(False)
            self._workspace_splitter.setCollapsible(0, False)
            self._workspace_splitter.setCollapsible(1, False)
            self._workspace_splitter.splitterMoved.connect(self._splitter_moved)
            layout.addWidget(self._workspace_splitter, 1)
        else:
            self._workspace_splitter = None
            self._map_host = None
            layout.addWidget(details_widget, 1)
        self._timetable = TimetableWidget(self._selected_matrix)
        self._timetable.hide()
        if self._map is not None:
            self._map.clear()
        layout.addWidget(self._timetable)
        self._routes.currentIndexChanged.connect(self._route_changed)
        self._services.currentIndexChanged.connect(self._service_changed)
        self._directions.currentIndexChanged.connect(self._direction_changed)
        self._trips.currentIndexChanged.connect(self._trip_changed)
        self.setTabOrder(self._routes, self._services)
        self.setTabOrder(self._services, self._directions)
        self.setTabOrder(self._directions, self._trips)
        self.setTabOrder(self._trips, matrix_button)

    def showEvent(self, event: object) -> None:  # noqa: N802 - nombre impuesto por Qt
        super().showEvent(event)  # type: ignore[arg-type]
        if not self._splitter_restored:
            self._splitter_restored = True
            QTimer.singleShot(0, self._restore_or_balance)

    def save_layout_state(self) -> None:
        """Guarda explícitamente el estado actual, por ejemplo al cerrar la ventana."""
        self._persist_splitter_state()

    def open_map(self) -> None:
        """Muestra el único mapa actual y lo trae al frente."""
        if self._map is None:
            return
        if self._map_window is None:
            self._map_window = MapWindow(
                self._map,
                geometry=self._map_window_geometry,
                maximized=self._map_window_maximized,
                save_geometry=self._save_map_window_geometry,
                on_return_to_data=self._on_return_to_data,
                on_dock_map=self._dock_map,
            )
        else:
            self._map_window.attach_map()
        self._map_window.show()
        if self._map_window.isMinimized():
            self._map_window.showNormal()
        self._map_window.raise_()
        self._map_window.activateWindow()

    def close_map_window(self) -> None:
        if self._map_window is not None:
            self._map_window.shutdown()
            self._map_window = None

    def _dock_map(self) -> None:
        if self._map is None or self._map_host is None:
            return
        host_layout = cast(QVBoxLayout, self._map_host.layout())
        if host_layout is None:
            return
        current_parent = self._map.parentWidget()
        current_layout = current_parent.layout() if current_parent is not None else None
        if current_layout is not None:
            current_layout.removeWidget(self._map)
        self._map.setParent(self._map_host)
        host_layout.addWidget(self._map, 1)
        self._map.show()
        host_layout.activate()
        self._map.resize(self._map_host.contentsRect().size())
        self._map_host.updateGeometry()
        if self._map_window is not None:
            self._map_window.hide()
        if self._on_dock_to_explore is not None:
            self._on_dock_to_explore()
        elif self._on_return_to_data is not None:
            self._on_return_to_data()

    def _restore_or_balance(self) -> None:
        splitter = self._workspace_splitter
        if splitter is None:
            return
        restored = False
        if self._saved_splitter_state:
            try:
                restored = splitter.restoreState(QByteArray(self._saved_splitter_state))
            except (TypeError, ValueError):
                restored = False
        if not restored or not self._has_functional_sizes():
            self._set_balanced_splitter()
        self._ensure_functional_sizes()

    def _set_balanced_splitter(self) -> None:
        splitter = self._workspace_splitter
        if splitter is None:
            return
        total = sum(splitter.sizes())
        details_min, map_min = self._splitter_minimums()
        if total <= 0:
            total = max(details_min + map_min, self.height())
        first = max(details_min, (total + 1) // 2)
        second = max(map_min, total - first)
        splitter.setSizes([first, second])

    def _splitter_minimums(self) -> tuple[int, int]:
        splitter = self._workspace_splitter
        if splitter is None:
            return (0, 0)
        return (splitter.widget(0).minimumHeight(), splitter.widget(1).minimumHeight())

    def _has_functional_sizes(self) -> bool:
        splitter = self._workspace_splitter
        if splitter is None:
            return True
        sizes = splitter.sizes()
        details_min, map_min = self._splitter_minimums()
        return len(sizes) == 2 and sizes[0] >= details_min and sizes[1] >= map_min

    def _ensure_functional_sizes(self) -> None:
        if self._workspace_splitter is not None and not self._has_functional_sizes():
            self._set_balanced_splitter()

    def _splitter_moved(self, _position: int, _index: int) -> None:
        self._ensure_functional_sizes()
        self._persist_splitter_state()

    def _persist_splitter_state(self) -> None:
        if self._workspace_splitter is not None and self._save_splitter_state is not None:
            state = cast(bytes, self._workspace_splitter.saveState().data())
            self._save_splitter_state(state)

    def refresh(self) -> None:
        self.clear()
        fit_bounds = getattr(self._map, "fit_bounds", None)
        if callable(fit_bounds) and self._feed_bounds is not None:
            fit_bounds(self._feed_bounds())
        self._routes.blockSignals(True)
        for route in self._routes_query().items:
            name = route.short_name or route.long_name or "Sin nombre"
            self._routes.addItem(
                f"{name} ({route.route_id}) · {format_route_type(route.route_type)}", route
            )
        self._routes.blockSignals(False)
        if self._routes.count():
            self._routes.setCurrentIndex(0)
            self._route_changed()

    def clear(self) -> None:
        for selector in (self._routes, self._services, self._directions, self._trips):
            selector.blockSignals(True)
            selector.clear()
            selector.blockSignals(False)
        self._timeline.clear()
        self._stops.clear()
        self._clear_map()
        self._timetable.clear()
        self._timetable.hide()

    def set_map_package(self, root: Path) -> str:
        """Selecciona un mapa local; el error de validación se propaga a la UI."""
        if self._map is None:
            raise RuntimeError("El mapa no está disponible.")
        return self._map.set_map_package(root).attribution

    def set_managed_map(self, library: OfflineMapLibrary, package: OfflineMapPackage) -> None:
        if self._map is None:
            raise RuntimeError("El mapa no está disponible.")
        self._map.set_managed_map(library, package)

    def clear_managed_map(self) -> None:
        if self._map is not None:
            self._map.clear_managed_map()

    def set_map_mode(self, mode: MapMode | str) -> str:
        """Aplica una preferencia global de mapa y devuelve su estado visible."""
        if self._map is None:
            raise RuntimeError("El mapa no está disponible.")
        return self._map.set_mode(mode)

    @property
    def map_status(self) -> str:
        """Expone el estado cartográfico sin filtrar datos del proyecto."""
        if self._map is None:
            return "Mapa: no disponible · el explorador no incluye mapa."
        status = getattr(self._map, "status_text", None)
        return status if isinstance(status, str) else "Mapa: no disponible · estado no disponible."

    def _route_changed(self) -> None:
        self._reset(self._services, self._directions, self._trips)
        self._timeline.clear()
        self._stops.clear()
        self._clear_map()
        self._timetable.hide()
        route = self._routes.currentData()
        if not isinstance(route, RouteSummary):
            return
        fit_bounds = getattr(self._map, "fit_bounds", None)
        if callable(fit_bounds) and self._route_bounds is not None:
            fit_bounds(self._route_bounds(route.route_id))
        for service in self._services_query(route.route_id).items:
            self._services.addItem(f"{service.service_id} ({service.trip_count} viajes)", service)
        if self._services.count():
            self._services.setCurrentIndex(0)
            self._service_changed()

    def _service_changed(self) -> None:
        self._reset(self._directions, self._trips)
        self._timeline.clear()
        self._stops.clear()
        self._clear_map()
        self._timetable.hide()
        route, service = self._routes.currentData(), self._services.currentData()
        if not isinstance(route, RouteSummary) or not isinstance(service, ServiceSummary):
            return
        for direction in self._directions_query(route.route_id, service.service_id).items:
            label = (
                "sin declarar" if direction.direction_id is None else str(direction.direction_id)
            )
            self._directions.addItem(
                f"direction_id: {label} ({direction.trip_count} viajes)", direction
            )
        if self._directions.count():
            self._directions.setCurrentIndex(0)
            self._direction_changed()

    def _direction_changed(self) -> None:
        self._reset(self._trips)
        self._timeline.clear()
        self._stops.clear()
        self._clear_map()
        self._timetable.hide()
        route, service, direction = self._selection()
        if route is None or service is None or direction is None:
            return
        for trip in self._trips_query(
            route.route_id, service.service_id, direction.direction_id
        ).items:
            name = trip.headsign or trip.short_name or "Sin nombre"
            self._trips.addItem(f"{name} ({trip.trip_id})", trip)
        if self._trips.count():
            self._trips.setCurrentIndex(0)
            self._trip_changed()

    def _trip_changed(self) -> None:
        trip = self._trips.currentData()
        self._timeline.clear()
        self._stops.clear()
        self._clear_map()
        if isinstance(trip, TripSummary):
            self._timeline.show_trip(trip)
            if self._map is not None:
                self._map.show_trip(trip.trip_id)

    def _show_stop(self, stop_id: str) -> None:
        self._stops.show_stop(stop_id)
        self._timeline.select_stop(stop_id)
        if self._map is not None:
            self._map.select_stop(stop_id)

    def _clear_map(self) -> None:
        if self._map is not None:
            self._map.clear()

    def _show_matrix(self) -> None:
        self._timetable.show()
        self._timetable.refresh()

    def _selected_matrix(self) -> TimetableMatrix | None:
        route, service, direction = self._selection()
        return (
            None
            if route is None or service is None or direction is None
            else self._matrix_query(route.route_id, service.service_id, direction.direction_id)
        )

    def _selection(
        self,
    ) -> tuple[RouteSummary | None, ServiceSummary | None, DirectionSummary | None]:
        route, service, direction = (
            self._routes.currentData(),
            self._services.currentData(),
            self._directions.currentData(),
        )
        return (
            route if isinstance(route, RouteSummary) else None,
            service if isinstance(service, ServiceSummary) else None,
            direction if isinstance(direction, DirectionSummary) else None,
        )

    @staticmethod
    def _reset(*selectors: QComboBox) -> None:
        for selector in selectors:
            selector.blockSignals(True)
            selector.clear()
            selector.blockSignals(False)


def _make_searchable(selector: QComboBox) -> None:
    """Configura un selector editable con filtrado incremental por texto visible."""
    selector.setEditable(True)
    selector.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    selector.setCompleter(QCompleter(selector.model(), selector))
    completer = selector.completer()
    assert completer is not None
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    completer.setFilterMode(Qt.MatchFlag.MatchContains)
    completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    line_edit = selector.lineEdit()
    assert line_edit is not None
    line_edit.textChanged.connect(completer.setCompletionPrefix)

    editing = False

    def invalidate_stale_selection(text: str) -> None:
        nonlocal editing
        if editing or selector.currentIndex() < 0:
            return
        if selector.itemText(selector.currentIndex()) == text:
            return
        editing = True
        selector.setCurrentIndex(-1)
        line_edit.setText(text)
        completer.setCompletionPrefix(text)
        editing = False

    line_edit.textChanged.connect(invalidate_stale_selection)

    def accept_completion(text: str) -> None:
        index = selector.findText(text, Qt.MatchFlag.MatchExactly)
        if index >= 0:
            selector.setCurrentIndex(index)

    completer.activated.connect(accept_completion)
