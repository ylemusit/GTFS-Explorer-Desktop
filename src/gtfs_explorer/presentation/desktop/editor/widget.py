"""Panel de edición genérico conectado a un ``EditorSession`` real."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import date, datetime
from typing import Any
from uuid import uuid4

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from gtfs_explorer.application.editor_session import (
    MAX_EDITING_ROUTES,
    EditorSession,
    EditSession,
    RevisionConfirmationError,
)
from gtfs_explorer.application.map_editing import MapEditMode
from gtfs_explorer.application.queries.map_layers import (
    MapLayerPayload,
    readable_foreground_color,
    route_colors,
)
from gtfs_explorer.domain.changesets import (
    EditorCommand,
    EditorCommandKind,
    EntityChange,
    WorkingCopyEntityIndex,
)
from gtfs_explorer.performance_gate import GateTrace, mark, trace_scope
from gtfs_explorer.presentation.desktop.i18n import t
from gtfs_explorer.presentation.desktop.map.window import MapWindow
from gtfs_explorer.presentation.map_bridge import MapEditGesture

_TABLES: tuple[tuple[str, str], ...] = (
    ("gtfs_routes", "Rutas"),
    ("gtfs_trips", "Viajes"),
    ("gtfs_stops", "Paradas"),
    ("gtfs_stop_times", "Horarios de parada"),
    ("gtfs_shapes", "Shapes"),
    ("gtfs_calendar", "Servicios / calendario"),
    ("gtfs_calendar_dates", "Excepciones de servicio"),
    ("gtfs_agency", "Agencias"),
    ("gtfs_attributions", "Atribuciones"),
)
_TABLE_LABEL_KEYS = {
    "gtfs_routes": "editor.table_routes",
    "gtfs_trips": "editor.table_trips",
    "gtfs_stops": "editor.table_stops",
    "gtfs_stop_times": "editor.table_stop_times",
    "gtfs_shapes": "editor.table_shapes",
    "gtfs_calendar": "editor.table_calendar",
    "gtfs_calendar_dates": "editor.table_calendar_dates",
    "gtfs_agency": "editor.table_agency",
    "gtfs_attributions": "editor.table_attributions",
}
_EDITABLE_FIELDS = {"source_filename", "source_row", "raw_values"}
_COMMAND_KINDS = {
    "gtfs_routes": EditorCommandKind.UPDATE_ROUTE,
    "gtfs_trips": EditorCommandKind.UPDATE_TRIP,
    "gtfs_stops": EditorCommandKind.UPDATE_STOP,
    "gtfs_stop_times": EditorCommandKind.UPDATE_STOP_TIME,
    "gtfs_shapes": EditorCommandKind.UPDATE_SHAPE,
    "gtfs_calendar": EditorCommandKind.UPDATE_SERVICE,
    "gtfs_calendar_dates": EditorCommandKind.UPDATE_SERVICE,
    "gtfs_agency": EditorCommandKind.UPDATE_AGENCY,
    "gtfs_attributions": EditorCommandKind.UPDATE_ATTRIBUTION,
}


class _MapRebuildSignals(QObject):
    finished = Signal(int, object)
    failed = Signal(int, str)


class _MapRebuildJob(QRunnable):
    def __init__(
        self,
        token: int,
        query: Callable[[], MapLayerPayload],
        trace: GateTrace | None,
    ) -> None:
        super().__init__()
        self.token = token
        self.query = query
        self.trace = trace
        self.signals = _MapRebuildSignals()

    def run(self) -> None:
        try:
            with trace_scope(self.trace, generation=self.token):
                mark(self.trace, "T3_INPUTS_READY", generation=self.token)
                self.signals.finished.emit(self.token, self.query())
        except (RuntimeError, TypeError, ValueError) as error:
            self.signals.failed.emit(self.token, str(error))


class RouteEditSelectionDialog(QDialog):
    """Selector accesible de una a tres rutas para abrir una sesión."""

    def __init__(
        self,
        routes: Mapping[str, str] | list[tuple[str, str]] | tuple[tuple[str, str], ...],
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("routeEditSelectionDialog")
        self.setWindowTitle(t("editor.select_routes_title"))
        layout = QVBoxLayout(self)
        title = QLabel(t("editor.select_routes_title"), self)
        title.setStyleSheet("font-weight: bold;")
        title.setWordWrap(True)
        layout.addWidget(title)
        explanation = QLabel(t("editor.select_routes_explanation"), self)
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        active_layout = QHBoxLayout()
        active_label = QLabel(t("editor.active_route_selector"), self)
        self._active_selector = QComboBox(self)
        self._active_selector.setObjectName("editingActiveRouteSelector")
        self._active_selector.setAccessibleName(t("editor.active_route_selector"))
        active_label.setBuddy(self._active_selector)
        active_layout.addWidget(active_label)
        active_layout.addWidget(self._active_selector, 1)
        layout.addLayout(active_layout)
        self._routes = QListWidget(self)
        self._routes.setObjectName("editingRouteSelector")
        self._routes.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._routes.setAccessibleName(t("editor.select_routes_title"))
        route_items = tuple(routes.items() if isinstance(routes, Mapping) else routes)
        self._route_options = tuple((str(route_id), str(label)) for route_id, label in route_items)
        for route_id, label in route_items:
            item = QListWidgetItem(str(label), self._routes)
            item.setData(Qt.ItemDataRole.UserRole, str(route_id))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setToolTip(f"route_id: {route_id}")
        self._routes.itemChanged.connect(self._selection_changed)
        layout.addWidget(self._routes, 1)
        self._selection_status = QLabel(self)
        self._selection_status.setObjectName("editingRouteSelectionStatus")
        self._selection_status.setWordWrap(True)
        layout.addWidget(self._selection_status)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._accept_selection)
        buttons.rejected.connect(self.reject)
        self._ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if self._ok_button is not None:
            self._ok_button.setText(t("editor.open_cartographic_editor"))
        layout.addWidget(buttons)
        self._selection_changed()
        self.resize(520, 420)

    @property
    def selected_route_ids(self) -> tuple[str, ...]:
        return tuple(
            str(item.data(Qt.ItemDataRole.UserRole))
            for index in range(self._routes.count())
            if (item := self._routes.item(index)) is not None
            and item.checkState() == Qt.CheckState.Checked
        )

    @property
    def active_route_id(self) -> str | None:
        value = self._active_selector.currentData()
        return str(value) if isinstance(value, str) else None

    def set_selected_route_ids(self, route_ids: list[str] | tuple[str, ...]) -> None:
        selected = set(route_ids)
        self._routes.blockSignals(True)
        for index in range(self._routes.count()):
            item = self._routes.item(index)
            if item is not None:
                route_id = str(item.data(Qt.ItemDataRole.UserRole))
                item.setCheckState(
                    Qt.CheckState.Checked if route_id in selected else Qt.CheckState.Unchecked
                )
        self._routes.blockSignals(False)
        self._selection_changed()

    def set_active_route_id(self, route_id: str | None) -> None:
        if route_id is None:
            return
        index = self._active_selector.findData(route_id)
        if index >= 0:
            self._active_selector.setCurrentIndex(index)

    def _selection_changed(self, *_args: object) -> None:
        selected = self.selected_route_ids
        if len(selected) > MAX_EDITING_ROUTES:
            self._routes.blockSignals(True)
            for index in range(self._routes.count() - 1, -1, -1):
                item = self._routes.item(index)
                if item is not None and item.checkState() == Qt.CheckState.Checked:
                    item.setCheckState(Qt.CheckState.Unchecked)
                    break
            self._routes.blockSignals(False)
            selected = self.selected_route_ids
            self._selection_status.setText(
                t("editor.select_routes_maximum", maximum=MAX_EDITING_ROUTES)
            )
        else:
            self._selection_status.setText(
                t(
                    "editor.select_routes_count",
                    count=len(selected),
                    maximum=MAX_EDITING_ROUTES,
                )
            )
        self._active_selector.blockSignals(True)
        current_active = self.active_route_id
        self._active_selector.clear()
        selected_ids = set(selected)
        for route_id, label in self._route_options:
            if route_id in selected_ids:
                self._active_selector.addItem(label, route_id)
        if current_active in selected_ids:
            self._active_selector.setCurrentIndex(self._active_selector.findData(current_active))
        elif self._active_selector.count():
            self._active_selector.setCurrentIndex(0)
        self._active_selector.setEnabled(bool(selected))
        self._active_selector.blockSignals(False)
        if self._ok_button is not None:
            self._ok_button.setEnabled(bool(selected))

    def _accept_selection(self) -> None:
        if not self.selected_route_ids:
            self._selection_status.setText(t("editor.select_routes_minimum"))
            return
        if len(self.selected_route_ids) > MAX_EDITING_ROUTES:
            self._selection_status.setText(
                t("editor.select_routes_maximum", maximum=MAX_EDITING_ROUTES)
            )
            return
        if self.active_route_id not in self.selected_route_ids:
            self._selection_status.setText(t("editor.select_routes_minimum"))
            return
        self.accept()


class EditorWidget(QWidget):
    """Editor de campos con impacto visible y operaciones reversibles."""

    history_state_changed = Signal(bool, bool)

    def __init__(
        self,
        session_provider: Callable[[], EditorSession | None],
        *,
        map_widget: QWidget | None = None,
        map_layers_for_routes: Callable[..., MapLayerPayload] | None = None,
        performance_trace: GateTrace | None = None,
        on_finish_editing: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._session_provider = session_provider
        self._map_widget = map_widget
        self._map_layers_for_routes = map_layers_for_routes
        self._performance_trace = performance_trace
        self._on_finish_editing = on_finish_editing
        self._on_confirm_map_operation: Callable[[], None] | None = None
        self._on_cancel_map_operation: Callable[[], None] | None = None
        self._keys: list[tuple[str, str]] = []
        self._payloads: dict[tuple[str, str], dict[str, Any]] = {}
        self._selected_route_id: str | None = None
        self._selected_route_ids: frozenset[str] = frozenset()
        self._route_rows: dict[str, int] = {}
        self._selection_signature: tuple[str | None, frozenset[str]] | None = None
        self._map_rendered = False
        # El preview no forma parte del estado persistido de ruta. Se conserva
        # únicamente para retirarlo al cambiar de inspección.
        self._map_preview_route_id: str | None = None
        self._map_active_route_id: str | None = None
        self._map_edit_mode = MapEditMode.NORMAL
        self._map_window: MapWindow | None = None
        self._segment_selection: tuple[str, str] | None = None
        self._segment_selection_shape: str | None = None
        self._map_rebuild_token = 0
        self._map_rebuild_timer = QTimer(self)
        self._map_rebuild_timer.setSingleShot(True)
        self._map_rebuild_timer.setInterval(30)
        self._map_rebuild_timer.timeout.connect(self._start_pending_map_rebuild)
        self._pending_map_rebuild: tuple[int, bool, bool] | None = None
        self._map_rebuild_signals: set[_MapRebuildSignals] = set()
        self._active_route_buttons = QButtonGroup(self)
        self._active_route_buttons.setExclusive(True)

        layout = QVBoxLayout(self)
        self._title = QLabel(t("editor.title"))
        title = self._title
        title.setObjectName("editorTitle")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)
        self._status = QLabel(t("editor.no_project"))
        self._status.setObjectName("editorStatus")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        route_workspace = QSplitter(Qt.Orientation.Horizontal, self)
        route_workspace.setObjectName("editorRouteWorkspace")
        route_workspace.setAccessibleName(t("editor.route_workspace"))

        route_panel = QGroupBox(t("editor.routes_panel"), route_workspace)
        self._route_panel = route_panel
        route_panel_layout = QVBoxLayout(route_panel)
        route_hint = QLabel(
            t("editor.routes_hint"),
            route_panel,
        )
        self._route_hint = route_hint
        route_hint.setWordWrap(True)
        route_panel_layout.addWidget(route_hint)
        self._route_search = QLineEdit(route_panel)
        self._route_search.setObjectName("editorRouteSearch")
        self._route_search.setAccessibleName(t("editor.route_search"))
        self._route_search.setPlaceholderText(t("editor.route_search_placeholder"))
        route_panel_layout.addWidget(self._route_search)
        bulk_controls = QHBoxLayout()
        self._bulk_label = QLabel(t("editor.bulk_states"), route_panel)
        bulk_controls.addWidget(self._bulk_label)
        self._bulk_visible_button = QPushButton(t("editor.bulk_visible"), route_panel)
        self._bulk_visible_button.setObjectName("selectAllVisibleRoutes")
        self._bulk_visible_button.setToolTip(t("editor.bulk_visible_tooltip"))
        self._bulk_locked_button = QPushButton(t("editor.bulk_locked"), route_panel)
        self._bulk_locked_button.setObjectName("selectAllLockedRoutes")
        self._bulk_locked_button.setToolTip(t("editor.bulk_locked_tooltip"))
        self._bulk_dimmed_button = QPushButton(t("editor.bulk_dimmed"), route_panel)
        self._bulk_dimmed_button.setObjectName("selectAllDimmedRoutes")
        self._bulk_dimmed_button.setToolTip(t("editor.bulk_dimmed_tooltip"))
        for button in (
            self._bulk_visible_button,
            self._bulk_locked_button,
            self._bulk_dimmed_button,
        ):
            bulk_controls.addWidget(button)
        bulk_controls.addStretch()
        route_panel_layout.addLayout(bulk_controls)
        self._route_list = QTableWidget(0, 9, route_panel)
        self._route_list.setObjectName("editorRouteList")
        self._route_list.setAccessibleName(t("editor.route_list_accessible"))
        self._route_list.setHorizontalHeaderLabels(
            (
                t("routes.visible"),
                t("editor.route_name_header"),
                t("editor.route_id_header"),
                t("editor.agency_operator_header"),
                t("routes.active"),
                t("routes.editable"),
                t("routes.locked"),
                t("routes.dimmed"),
                t("routes.status"),
            )
        )
        self._route_list.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._route_list.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self._route_list.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._route_list.setMinimumHeight(220)
        self._route_list.verticalHeader().setVisible(False)
        self._route_list.horizontalHeader().setStretchLastSection(True)
        self._route_list.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._route_list.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        for column, width in ((0, 58), (2, 110), (4, 58), (5, 62), (6, 58), (7, 58)):
            self._route_list.setColumnWidth(column, width)
        for technical_column in (0, 4, 5, 6, 7):
            self._route_list.setColumnHidden(technical_column, True)
        route_panel_layout.addWidget(self._route_list, 1)
        self._route_selection_status = QLabel(t("editor.no_route_selected"), route_panel)
        self._route_selection_status.setObjectName("editorRouteSelectionStatus")
        self._route_selection_status.setWordWrap(True)
        route_panel_layout.addWidget(self._route_selection_status)
        route_workspace.addWidget(route_panel)

        route_context = QWidget(route_workspace)
        route_context_layout = QVBoxLayout(route_context)
        editing_group = QGroupBox(t("editor.editing_routes"), route_context)
        self._editing_group = editing_group
        editing_layout = QVBoxLayout(editing_group)
        self._editing_header = QLabel(editing_group)
        self._editing_header.setObjectName("editingRouteHeader")
        self._editing_header.setWordWrap(True)
        self._editing_header.setStyleSheet("font-weight: bold;")
        editing_layout.addWidget(self._editing_header)
        self._editing_routes = QTableWidget(0, 3, editing_group)
        self._editing_routes.setObjectName("editingSessionRoutes")
        self._editing_routes.setHorizontalHeaderLabels(
            ("#", t("routes.route"), t("editor.role_header"))
        )
        self._editing_routes.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._editing_routes.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._editing_routes.setMinimumHeight(78)
        editing_layout.addWidget(self._editing_routes)
        route_context_layout.addWidget(editing_group)

        context_group = QGroupBox(t("editor.route_context"), route_context)
        self._context_group = context_group
        context_layout = QVBoxLayout(context_group)
        self._route_properties = QLabel(t("editor.route_properties_placeholder"))
        self._route_properties.setObjectName("editorRouteProperties")
        self._route_properties.setAccessibleName(t("editor.properties"))
        self._route_properties.setWordWrap(True)
        context_layout.addWidget(self._route_properties)
        self._route_context_status = QLabel("", context_group)
        self._route_context_status.setObjectName("editorRouteContextStatus")
        self._route_context_status.setWordWrap(True)
        context_layout.addWidget(self._route_context_status)
        route_context_layout.addWidget(context_group)

        route_actions = QGroupBox(t("editor.route_actions_group"), route_context)
        self._route_actions_group = route_actions
        route_actions_layout = QGridLayout(route_actions)
        self._activate_route_button = QPushButton(t("editor.start_editing"))
        self._activate_route_button.setObjectName("startEditing")
        self._start_editing_button = self._activate_route_button
        self._activate_route_button.setToolTip(t("editor.start_editing_tooltip"))
        self._finish_editing_button = QPushButton(t("editor.finish_editing"))
        self._finish_editing_button.setObjectName("finishEditing")
        self._edit_shape_button = QPushButton(t("routes.edit_shape"))
        self._edit_shape_button.setObjectName("editRouteShape")
        self._redraw_segment_button = QPushButton(t("routes.redraw_segment"))
        self._redraw_segment_button.setObjectName("redrawRouteSegment")
        self._redraw_segment_button.setToolTip(t("editor.redraw_segment_tooltip"))
        self._open_map_window_button = QPushButton(t("editor.open_cartographic_editor"))
        self._open_map_window_button.setObjectName("openEditorMapWindow")
        self._open_map_window_button.setAccessibleName(t("editor.open_cartographic_editor"))
        self._open_map_window_button.setToolTip(t("editor.open_cartographic_editor_tooltip"))
        self._edit_stop_button = QPushButton(t("routes.edit_stops"))
        self._edit_stop_button.setObjectName("editRouteStops")
        self._edit_schedule_button = QPushButton(t("routes.edit_schedule"))
        self._edit_schedule_button.setObjectName("editRouteSchedule")
        self._edit_service_button = QPushButton(t("routes.edit_services"))
        self._edit_service_button.setObjectName("editRouteServices")
        self._edit_operator_button = QPushButton(t("routes.edit_operator"))
        self._edit_operator_button.setObjectName("editRouteOperator")
        self._properties_button = QPushButton(t("editor.properties"))
        self._properties_button.setObjectName("showRouteProperties")
        self._reorder_stop_button = QPushButton(t("routes.reorder_stops"))
        self._reorder_stop_button.setObjectName("reorderRouteStops")
        self._reorder_stop_button.setToolTip(t("editor.reorder_stops_tooltip"))
        self._add_segment_vertex_button = QPushButton(t("map.add_vertex"))
        self._add_segment_vertex_button.setObjectName("addSegmentVertex")
        self._add_segment_vertex_button.setToolTip(t("editor.add_vertex_tooltip"))
        self._delete_segment_vertex_button = QPushButton(t("map.delete_vertex"))
        self._delete_segment_vertex_button.setObjectName("deleteSegmentVertex")
        self._delete_segment_vertex_button.setToolTip(t("editor.delete_vertex_tooltip"))
        for index, button in enumerate(
            (
                self._activate_route_button,
                self._finish_editing_button,
                self._open_map_window_button,
                self._edit_shape_button,
                self._redraw_segment_button,
                self._edit_stop_button,
                self._edit_schedule_button,
                self._edit_service_button,
                self._edit_operator_button,
                self._properties_button,
                self._reorder_stop_button,
                self._add_segment_vertex_button,
                self._delete_segment_vertex_button,
            )
        ):
            route_actions_layout.addWidget(button, index // 2, index % 2)
            button.setMinimumHeight(32)
            button.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Preferred,
            )
        route_actions_layout.setColumnStretch(0, 1)
        route_actions_layout.setColumnStretch(1, 1)
        route_context_layout.addWidget(route_actions)

        map_group = QGroupBox(t("editor.map_group"), route_context)
        self._map_group = map_group
        map_layout = QVBoxLayout(map_group)
        self._map_legend = QLabel(
            t("editor.map_legend"),
            map_group,
        )
        self._map_legend.setObjectName("editorMapLegend")
        self._map_legend.setWordWrap(True)
        map_layout.addWidget(self._map_legend)
        self._map_mode_status = QLabel(t("map.mode_normal"))
        self._map_mode_status.setObjectName("editorMapModeStatus")
        self._map_mode_status.setWordWrap(True)
        map_layout.addWidget(self._map_mode_status)
        self._cancel_map_edit_button = QPushButton(t("editor.map_cancel"), map_group)
        self._cancel_map_edit_button.setObjectName("cancelMapEdit")
        self._cancel_map_edit_button.setVisible(False)
        self._cancel_map_edit_button.clicked.connect(self._cancel_map_edit)
        map_layout.addWidget(self._cancel_map_edit_button)
        self._map_host = QWidget(map_group)
        self._map_host.setObjectName("editorMapHost")
        self._map_host.setMinimumHeight(240)
        self._map_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._map_host.setLayout(QVBoxLayout())
        self._map_host.layout().setContentsMargins(0, 0, 0, 0)  # type: ignore[union-attr]
        map_layout.addWidget(self._map_host, 1)
        route_context_layout.addWidget(map_group, 1)
        route_workspace.addWidget(route_context)
        route_workspace.setStretchFactor(0, 1)
        route_workspace.setStretchFactor(1, 2)
        route_workspace.setMinimumHeight(420)

        upper_workspace = QWidget(self)
        upper_layout = QVBoxLayout(upper_workspace)
        upper_layout.setContentsMargins(0, 0, 0, 0)
        upper_layout.addWidget(route_workspace, 1)
        upper_workspace.setMinimumHeight(420)

        lower_workspace = QWidget(self)
        lower_layout = QVBoxLayout(lower_workspace)
        lower_layout.setContentsMargins(0, 0, 0, 0)

        form_group = QGroupBox(t("editor.advanced_draft"))
        self._form_group = form_group
        form = QFormLayout(form_group)
        self._table_selector = QComboBox()
        self._table_selector.setObjectName("editorTableSelector")
        self._table_selector.setAccessibleName(t("editor.table_accessible"))
        for table_name, _label in _TABLES:
            self._table_selector.addItem(
                t(_TABLE_LABEL_KEYS.get(table_name, "editor.table")), table_name
            )
        self._entity_selector = QComboBox()
        self._entity_selector.setObjectName("editorEntitySelector")
        self._entity_selector.setAccessibleName(t("editor.entity_accessible"))
        self._field_selector = QComboBox()
        self._field_selector.setObjectName("editorFieldSelector")
        self._field_selector.setAccessibleName(t("editor.field_accessible"))
        self._value = QLineEdit()
        self._value.setObjectName("editorValue")
        self._value.setAccessibleName(t("editor.value_accessible"))
        self._table_form_label = QLabel(t("editor.table"), form_group)
        self._entity_form_label = QLabel(t("editor.entity"), form_group)
        self._field_form_label = QLabel(t("editor.field"), form_group)
        self._value_form_label = QLabel(t("editor.value"), form_group)
        form.addRow(self._table_form_label, self._table_selector)
        form.addRow(self._entity_form_label, self._entity_selector)
        form.addRow(self._field_form_label, self._field_selector)
        form.addRow(self._value_form_label, self._value)
        self._advanced_toggle = QCheckBox(t("editor.advanced_toggle"))
        self._advanced_toggle.setObjectName("advancedEditorToggle")
        self._advanced_toggle.setAccessibleName(t("editor.advanced_toggle"))
        form_group.setVisible(False)
        self._advanced_toggle.toggled.connect(form_group.setVisible)
        lower_layout.addWidget(self._advanced_toggle)
        lower_layout.addWidget(form_group)

        schedule_group = QGroupBox(t("editor.schedule_matrix"))
        self._schedule_group = schedule_group
        schedule_layout = QVBoxLayout(schedule_group)
        schedule_controls = QHBoxLayout()
        self._schedule_trip = QComboBox()
        self._schedule_trip.setObjectName("editorScheduleTrip")
        self._schedule_trip.setAccessibleName(t("editor.schedule_trip_accessible"))
        self._schedule_trip_label = QLabel(t("editor.schedule_trip"), schedule_group)
        schedule_controls.addWidget(self._schedule_trip_label)
        schedule_controls.addWidget(self._schedule_trip, 1)
        self._interpolation_field = QComboBox()
        self._interpolation_field.addItem(t("stop.arrival"), "arrival_time_lexeme")
        self._interpolation_field.addItem(t("stop.departure"), "departure_time_lexeme")
        self._interpolation_field.setAccessibleName(t("editor.interpolation_field"))
        schedule_controls.addWidget(self._interpolation_field)
        self._interpolation_button = QPushButton(t("editor.interpolation_preview"))
        self._interpolation_button.setObjectName("previewScheduleInterpolation")
        schedule_controls.addWidget(self._interpolation_button)
        self._schedule_scope = QComboBox()
        self._schedule_scope.setObjectName("schedulePropagationScope")
        self._schedule_scope.addItems(
            (
                t("editor.schedule_scope_single"),
                t("editor.schedule_scope_following"),
                t("editor.schedule_scope_trip"),
                t("editor.schedule_scope_selected"),
            )
        )
        self._schedule_scope.setToolTip(t("editor.schedule_scope_tooltip"))
        self._schedule_scope.setEnabled(False)
        schedule_controls.addWidget(self._schedule_scope)
        self._reschedule_button = QPushButton(t("editor.reschedule_following"))
        self._reschedule_button.setObjectName("rescheduleFollowing")
        self._reschedule_button.setEnabled(False)
        schedule_controls.addWidget(self._reschedule_button)
        self._recalculate_button = QPushButton(t("editor.recalculate_schedule"))
        self._recalculate_button.setObjectName("recalculateSchedule")
        self._recalculate_button.setEnabled(False)
        schedule_controls.addWidget(self._recalculate_button)
        schedule_layout.addLayout(schedule_controls)
        self._schedule_table = QTableWidget(0, 4)
        self._schedule_table.setObjectName("editorScheduleMatrix")
        self._schedule_table.setHorizontalHeaderLabels(
            (
                t("stop.name"),
                t("stop.sequence"),
                t("editor.arrival_gtfs"),
                t("editor.departure_gtfs"),
            )
        )
        self._schedule_table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.EditKeyPressed
        )
        self._schedule_table.setAccessibleName(t("editor.schedule_matrix_accessible"))
        schedule_layout.addWidget(self._schedule_table)
        lower_layout.addWidget(schedule_group, 1)

        workspace_group = QGroupBox(t("editor.workspace_state"))
        self._workspace_group = workspace_group
        workspace_layout = QHBoxLayout(workspace_group)
        self._visible = QCheckBox(t("routes.visible"))
        self._active = QCheckBox(t("routes.active"))
        self._editable = QCheckBox(t("routes.editable"))
        self._locked = QCheckBox(t("routes.locked"))
        self._dimmed = QCheckBox(t("routes.dimmed"))
        for checkbox in (
            self._visible,
            self._active,
            self._editable,
            self._locked,
            self._dimmed,
        ):
            workspace_layout.addWidget(checkbox)
        workspace_layout.addStretch()
        self._workspace_apply = QPushButton(t("editor.save_route_state"))
        self._workspace_apply.setObjectName("saveRouteWorkspaceState")
        workspace_layout.addWidget(self._workspace_apply)
        workspace_group.setVisible(False)
        lower_layout.addWidget(workspace_group)

        actions = QHBoxLayout()
        self._apply_button = QPushButton(t("editor.apply"))
        self._apply_button.setObjectName("applyEditorChange")
        self._apply_button.setToolTip(t("editor.apply_tooltip"))
        self._refresh_button = QPushButton(t("editor.refresh"))
        self._refresh_button.setObjectName("refreshEditor")
        self._undo_button = QPushButton(t("editor.undo"))
        self._undo_button.setObjectName("undoEditorChange")
        self._redo_button = QPushButton(t("editor.redo"))
        self._redo_button.setObjectName("redoEditorChange")
        self._discard_button = QPushButton(t("editor.discard"))
        self._discard_button.setObjectName("discardEditorChanges")
        self._validate_button = QPushButton(t("editor.validate"))
        self._validate_button.setObjectName("validateEditorDraft")
        self._delete_button = QPushButton(t("editor.delete_entity"))
        self._delete_button.setObjectName("deleteEditorEntity")
        self._delete_button.setToolTip(t("editor.delete_entity_tooltip"))
        self._add_stop_button = QPushButton(t("editor.add_stop"))
        self._add_stop_button.setObjectName("addEditorStop")
        self._add_stop_button.setToolTip(t("editor.add_stop_tooltip"))
        self._reorder_shape_button = QPushButton(t("editor.reorder_shape"))
        self._reorder_shape_button.setObjectName("reorderEditorShapePoint")
        self._reorder_shape_button.setToolTip(t("editor.reorder_shape_tooltip"))
        self._confirm_button = QPushButton(t("editor.confirm_revision"))
        self._confirm_button.setObjectName("confirmEditorRevision")
        self._confirm_button.setToolTip(t("editor.confirm_revision_tooltip"))
        for button in (
            self._apply_button,
            self._refresh_button,
            self._undo_button,
            self._redo_button,
            self._discard_button,
            self._validate_button,
            self._delete_button,
            self._add_stop_button,
            self._reorder_shape_button,
            self._confirm_button,
        ):
            actions.addWidget(button)
        actions.addStretch()
        lower_layout.addLayout(actions)

        self._history = QTableWidget(0, 4)
        self._history.setObjectName("editorHistory")
        self._history.setHorizontalHeaderLabels(t("editor.history_headers").split("|"))
        self._history.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._history.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._history.setAccessibleName(t("editor.history_accessible"))
        lower_layout.addWidget(self._history, 1)

        # El editor se organiza por intención de trabajo. Los mismos widgets
        # siguen conectados a EditorSession; solo cambia su lugar de acceso.
        for widget in (
            self._advanced_toggle,
            form_group,
            schedule_group,
            workspace_group,
            self._history,
        ):
            lower_layout.removeWidget(widget)
        for button in (
            self._edit_shape_button,
            self._redraw_segment_button,
            self._add_segment_vertex_button,
            self._delete_segment_vertex_button,
            self._edit_stop_button,
            self._reorder_stop_button,
            self._add_stop_button,
            self._edit_service_button,
            self._edit_operator_button,
            self._properties_button,
            self._finish_editing_button,
        ):
            route_actions_layout.removeWidget(button)
        lower_layout.removeItem(actions)

        editor_tabs = QTabWidget(self)
        editor_tabs.setObjectName("editorWorkspaces")
        editor_tabs.setAccessibleName(t("editor.workspaces_accessible"))
        self._editor_tabs = editor_tabs
        self._workspace_hints: list[tuple[QLabel, str]] = []

        def workspace_page(
            title: str, description: str, description_key: str
        ) -> tuple[QWidget, QVBoxLayout]:
            page = QWidget(editor_tabs)
            page_layout = QVBoxLayout(page)
            hint = QLabel(description, page)
            hint.setWordWrap(True)
            page_layout.addWidget(hint)
            self._workspace_hints.append((hint, description_key))
            editor_tabs.addTab(page, title)
            return page, page_layout

        route_page, route_page_layout = workspace_page(
            t("editor.workspace_routes"),
            t("editor.workspace_routes_description"),
            "editor.workspace_routes_description",
        )
        route_page_layout.addWidget(upper_workspace, 1)

        properties_page, properties_layout = workspace_page(
            t("editor.properties"),
            t("editor.workspace_properties_description"),
            "editor.workspace_properties_description",
        )
        self._properties_page = properties_page
        properties_group = QGroupBox(t("editor.properties_user_fields"), properties_page)
        self._properties_group = properties_group
        properties_group_layout = QVBoxLayout(properties_group)
        self._properties_user = QLabel(t("editor.select_route_properties"), properties_group)
        self._properties_user.setObjectName("editorPropertiesUser")
        self._properties_user.setWordWrap(True)
        properties_group_layout.addWidget(self._properties_user)
        properties_layout.addWidget(properties_group)
        technical_group = QGroupBox(t("editor.properties_technical"), properties_page)
        self._technical_group = technical_group
        technical_layout = QVBoxLayout(technical_group)
        self._properties_technical = QLabel(technical_group)
        self._properties_technical.setObjectName("editorPropertiesTechnical")
        self._properties_technical.setWordWrap(True)
        technical_layout.addWidget(self._properties_technical)
        properties_layout.addWidget(technical_group)
        properties_layout.addStretch()

        geometry_page, geometry_layout = workspace_page(
            t("editor.workspace_shape"),
            t("editor.workspace_shape_description"),
            "editor.workspace_shape_description",
        )
        self._geometry_page = geometry_page
        self._geometry_map_host = QWidget(geometry_page)
        self._geometry_map_host.setObjectName("editorRouteWorkspaceMapHost")
        self._geometry_map_host.setMinimumHeight(300)
        self._geometry_map_host.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        geometry_map_layout = QVBoxLayout(self._geometry_map_host)
        geometry_map_layout.setContentsMargins(0, 0, 0, 0)
        geometry_layout.addWidget(self._geometry_map_host, 1)
        geometry_hint = QLabel(t("editor.geometry_hint"))
        self._geometry_hint = geometry_hint
        geometry_layout.addWidget(geometry_hint)
        self._geometry_context = QLabel(geometry_page)
        self._geometry_context.setObjectName("editorRouteGeometryContext")
        self._geometry_context.setWordWrap(True)
        geometry_layout.addWidget(self._geometry_context)
        for button in (
            self._edit_shape_button,
            self._redraw_segment_button,
            self._add_segment_vertex_button,
            self._delete_segment_vertex_button,
        ):
            geometry_layout.addWidget(button)
        geometry_layout.addStretch()

        stops_page, stops_layout = workspace_page(
            t("editor.workspace_stops"),
            t("editor.workspace_stops_description"),
            "editor.workspace_stops_description",
        )
        self._stops_page = stops_page
        self._stops_context = QTableWidget(0, 5, stops_page)
        self._stops_context.setObjectName("editorRouteStopsContext")
        self._stops_context.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._stops_context.setHorizontalHeaderLabels(t("editor.stops_headers").split("|"))
        stops_layout.addWidget(self._stops_context, 1)
        for button in (self._edit_stop_button, self._reorder_stop_button, self._add_stop_button):
            stops_layout.addWidget(button)
        stops_layout.addStretch()

        schedule_page, schedule_layout = workspace_page(
            t("editor.workspace_schedule"),
            t("editor.workspace_schedule_description"),
            "editor.workspace_schedule_description",
        )
        self._schedule_page = schedule_page
        schedule_layout.addWidget(schedule_group, 1)

        service_page, service_layout = workspace_page(
            t("editor.workspace_services"),
            t("editor.workspace_services_description"),
            "editor.workspace_services_description",
        )
        self._service_page = service_page
        self._services_context = QLabel(service_page)
        self._services_context.setObjectName("editorRouteServicesContext")
        self._services_context.setWordWrap(True)
        service_layout.addWidget(self._services_context)
        for button in (self._edit_service_button, self._edit_operator_button):
            service_layout.addWidget(button)
        services_hint = QLabel(t("editor.services_hint"))
        self._services_hint = services_hint
        service_layout.addWidget(services_hint)
        service_layout.addStretch()

        changes_page, changes_layout = workspace_page(
            t("editor.workspace_history"),
            t("editor.workspace_history_description"),
            "editor.workspace_history_description",
        )
        self._changes_page = changes_page
        self._history_context = QLabel(changes_page)
        self._history_context.setObjectName("editorRouteHistoryContext")
        self._history_context.setWordWrap(True)
        changes_layout.addWidget(self._history_context)
        changes_layout.addLayout(actions)
        changes_layout.addWidget(self._history, 1)

        advanced_page, advanced_layout = workspace_page(
            t("editor.workspace_advanced"),
            t("editor.workspace_advanced_description"),
            "editor.workspace_advanced_description",
        )
        self._advanced_page = advanced_page
        advanced_layout.addWidget(self._advanced_toggle)
        advanced_layout.addWidget(form_group)
        advanced_layout.addWidget(workspace_group)
        workspace_group.setVisible(True)
        advanced_layout.addStretch()

        # Rutas y mapa conserva solo las acciones de contexto; recorrido,
        # paradas, horarios y cambios ya no compiten por el mismo espacio.
        route_actions_layout.addWidget(self._activate_route_button, 0, 0)
        route_actions_layout.addWidget(self._open_map_window_button, 0, 1)
        route_actions_layout.addWidget(self._properties_button, 1, 0)
        route_actions_layout.addWidget(self._finish_editing_button, 1, 1)
        route_actions_layout.setRowStretch(2, 1)

        workspace_splitter = QSplitter(Qt.Orientation.Vertical, self)
        workspace_splitter.setObjectName("editorWorkspaceSplitter")
        workspace_splitter.setAccessibleName(t("editor.workspace_splitter_accessible"))
        workspace_splitter.addWidget(editor_tabs)
        workspace_splitter.setStretchFactor(0, 1)
        workspace_splitter.setStretchFactor(1, 0)
        workspace_splitter.setChildrenCollapsible(False)
        workspace_splitter.setCollapsible(0, False)
        workspace_splitter.setCollapsible(1, False)
        workspace_splitter.setSizes([760, 0])
        self._editor_workspace_splitter = workspace_splitter
        layout.addWidget(workspace_splitter, 1)

        self._table_selector.currentIndexChanged.connect(self._table_changed)
        self._entity_selector.currentIndexChanged.connect(self._entity_changed)
        self._field_selector.currentIndexChanged.connect(self._field_changed)
        self._schedule_trip.currentIndexChanged.connect(self._schedule_trip_changed)
        self._schedule_table.itemChanged.connect(self._schedule_item_changed)
        self._interpolation_button.clicked.connect(self._preview_interpolation)
        self._apply_button.clicked.connect(self._apply_change)
        self._refresh_button.clicked.connect(self.refresh)
        self._undo_button.clicked.connect(self._undo)
        self._redo_button.clicked.connect(self._redo)
        self._discard_button.clicked.connect(self._discard)
        self._validate_button.clicked.connect(self._validate)
        self._delete_button.clicked.connect(self._delete)
        self._add_stop_button.clicked.connect(self._add_stop)
        self._reorder_shape_button.clicked.connect(self._reorder_shape_point)
        self._confirm_button.clicked.connect(self._confirm_revision)
        self._workspace_apply.clicked.connect(self._save_workspace_state)
        self._route_search.textChanged.connect(self._filter_routes)
        self._bulk_visible_button.clicked.connect(lambda: self._bulk_route_state("visible"))
        self._bulk_locked_button.clicked.connect(lambda: self._bulk_route_state("locked"))
        self._bulk_dimmed_button.clicked.connect(lambda: self._bulk_route_state("dimmed"))
        self._route_list.itemSelectionChanged.connect(self._route_selection_changed)
        self._editor_tabs.currentChanged.connect(self._workspace_changed)
        self._activate_route_button.clicked.connect(self._start_editing)
        self._finish_editing_button.clicked.connect(self._finish_editing)
        self._open_map_window_button.clicked.connect(self._open_map_window)
        self._edit_shape_button.clicked.connect(self._edit_selected_shape)
        self._redraw_segment_button.clicked.connect(self._redraw_selected_segment)
        self._edit_stop_button.clicked.connect(self._edit_selected_stops)
        self._edit_schedule_button.clicked.connect(self._edit_selected_schedule)
        self._edit_service_button.clicked.connect(self._edit_selected_services)
        self._edit_operator_button.clicked.connect(self._edit_selected_operator)
        self._properties_button.clicked.connect(self._show_selected_properties)
        self._reorder_stop_button.clicked.connect(self._reorder_selected_stop)
        self._add_segment_vertex_button.clicked.connect(self._arm_add_segment_vertex)
        self._delete_segment_vertex_button.clicked.connect(self._arm_delete_segment_vertex)
        initial_session = self._session_provider()
        self._legacy_properties_tab = bool(
            initial_session is not None and not hasattr(initial_session, "start_editing")
        )
        if self._legacy_properties_tab:
            self._editor_tabs.removeTab(self._editor_tabs.indexOf(self._properties_page))
            # Los dobles de prueba de la primera iteración no exponen aún el
            # contrato de sesión; conserva su etiqueta histórica únicamente
            # para no romper integraciones antiguas.
            self._editor_tabs.setTabText(5, t("editor.workspace_history_legacy"))
        self.refresh()

    @property
    def map_host(self) -> QWidget:
        """Host del mapa existente cuando Editar está activa."""
        return self._map_host

    def close_map_window(self) -> None:
        """Cierra la ventana auxiliar al cerrar el proyecto o la aplicación."""
        if self._map_window is not None:
            self._map_window.shutdown()
            self._map_window = None

    def dock_map_window(self) -> None:
        """Acopla el mismo mapa sin destruir el WebEngine compartido."""
        if self._map_window is None:
            return
        self._map_window.dock_map()
        self._map_window = None

    def focus_stop(self, stop_id: str) -> None:
        """Lleva una acción de Stop Card al espacio de Paradas del editor."""
        self._editor_tabs.setCurrentWidget(self._stops_page)
        self._status.setText(t("editor.stop_selected", stop_id=stop_id))

    def set_map_operation_callbacks(
        self,
        *,
        on_confirm: Callable[[], None] | None,
        on_cancel: Callable[[], None] | None,
    ) -> None:
        """Conecta Confirmar/Cancelar del mapa a la propuesta geométrica pendiente."""
        self._on_confirm_map_operation = on_confirm
        self._on_cancel_map_operation = on_cancel

    def _open_map_window(self) -> None:
        """Desacopla el MapWidget ya existente sin crear otro WebEngine."""
        if self._map_widget is None or self._selected_route_id is None:
            return
        if self._map_window is None:
            self._map_window = MapWindow(
                self._map_widget,
                on_dock_map=self._dock_map,
                on_mode_changed=self._map_window_mode_changed,
                on_vertex_action=self._map_window_vertex_action,
                on_confirm=self._confirm_map_operation,
                on_cancel=self._cancel_map_edit,
                on_undo=self._undo,
                on_redo=self._redo,
                on_fit=self._fit_active_route,
                on_finish=self._finish_editing,
            )
        else:
            self._map_window.attach_map()
            self._map_window.set_editor_callbacks(
                on_mode_changed=self._map_window_mode_changed,
                on_vertex_action=self._map_window_vertex_action,
                on_confirm=self._confirm_map_operation,
                on_cancel=self._cancel_map_edit,
                on_undo=self._undo,
                on_redo=self._redo,
                on_fit=self._fit_active_route,
                on_finish=self._finish_editing,
            )
        editing = getattr(self._session_provider(), "editing_session", None)
        active_route_id = self._active_route_id() or self._selected_route_id
        route_label = _route_display_label(
            self._route_payload(active_route_id), active_route_id or ""
        )
        route_ordinal = (
            editing.ordinal(active_route_id)
            if isinstance(editing, EditSession) and active_route_id in editing.route_ids
            else 1
        )
        route_total = editing.total_routes if isinstance(editing, EditSession) else 1
        self._map_window.set_editor_context(
            active_route_id or self._selected_route_id,
            self._map_edit_mode.value,
            route_label,
            route_ordinal,
            route_total,
            selected_route_id=self._selected_route_id,
            selected_route_label=_route_display_label(
                self._route_payload(self._selected_route_id), self._selected_route_id or ""
            ),
        )
        session = self._session_provider()
        if session is not None:
            self._map_window.set_history_state(
                session.working_copy.changeset.undo_available,
                session.working_copy.changeset.redo_available,
            )
        self._map_window.show()
        if self._map_window.isMinimized():
            self._map_window.showNormal()
        self._map_window.raise_()
        self._map_window.activateWindow()

    def _map_window_mode_changed(self, mode: str) -> None:
        try:
            self._set_map_edit_mode(MapEditMode(mode))
        except ValueError:
            self._set_map_edit_mode(MapEditMode.NORMAL)

    def _map_window_vertex_action(self, action: str) -> None:
        if self._map_edit_mode is not MapEditMode.REDRAW_SEGMENT:
            self._set_map_edit_mode(MapEditMode.REDRAW_SEGMENT)
        set_action = getattr(self._map_widget, "set_vertex_action", None)
        if callable(set_action):
            set_action(action)
        self._status.setText(
            t("editor.add_vertex_ready") if action == "add" else t("editor.delete_vertex_ready")
        )

    def _fit_active_route(self) -> None:
        self._render_route_map(fit=True, reset_selection=False)
        self._status.setText(t("editor.map_fitted"))

    def _dock_map(self) -> None:
        if self._map_widget is None:
            return
        host = self._map_host_for_workspace()
        host_layout = host.layout()
        if host_layout is None:
            return
        parent = self._map_widget.parentWidget()
        parent_layout = parent.layout() if parent is not None else None
        if parent_layout is not None:
            parent_layout.removeWidget(self._map_widget)
        self._map_widget.setParent(host)
        host_layout.addWidget(self._map_widget)
        self._map_widget.show()
        host_layout.activate()
        host.updateGeometry()
        self._refresh_rehosted_map()

    def _map_host_for_workspace(self) -> QWidget:
        return (
            self._geometry_map_host
            if self._editor_tabs.currentWidget() is self._geometry_page
            else self._map_host
        )

    def _workspace_changed(self, _index: int) -> None:
        """Realojar el único WebEngine entre Rutas y Recorrido de forma segura."""
        if self._map_widget is None or self._map_window is not None:
            return
        host = self._map_host_for_workspace()
        if self._map_widget.parentWidget() is host:
            return
        parent = self._map_widget.parentWidget()
        parent_layout = parent.layout() if parent is not None else None
        if parent_layout is not None:
            parent_layout.removeWidget(self._map_widget)
        layout = host.layout()
        if layout is None:
            return
        self._map_widget.setParent(host)
        layout.addWidget(self._map_widget)
        self._map_widget.show()
        layout.activate()
        host.updateGeometry()
        self._refresh_rehosted_map()

    def _refresh_rehosted_map(self) -> None:
        """Hace utilizable el WebEngine justo después de cambiar de host."""
        refresh_host = getattr(self._map_widget, "refresh_host", None)
        if callable(refresh_host):
            refresh_host()

    def refresh(self) -> None:
        session = self._session_provider()
        if session is None:
            self._status.setText(t("editor.no_project"))
            self._keys.clear()
            self._payloads.clear()
            self._selected_route_id = None
            self._selected_route_ids = frozenset()
            self._route_rows.clear()
            self._selection_signature = None
            self._map_rendered = False
            self._map_preview_route_id = None
            self._map_active_route_id = None
            self._segment_selection = None
            self._segment_selection_shape = None
            self._set_map_edit_mode(MapEditMode.NORMAL, render=False)
            self._route_search.clear()
            self._route_list.setRowCount(0)
            self._route_selection_status.setText(t("editor.no_route_selected"))
            self._route_properties.setText(t("editor.select_route_properties"))
            self._properties_user.setText(t("editor.select_route_properties"))
            self._properties_technical.clear()
            self._route_context_status.clear()
            self._editing_header.clear()
            self._editing_routes.setRowCount(0)
            self._editing_group.setVisible(False)
            self._entity_selector.clear()
            self._field_selector.clear()
            self._history.setRowCount(0)
            self._set_buttons_enabled(False)
            self._schedule_trip.clear()
            self._schedule_table.setRowCount(0)
            self.history_state_changed.emit(False, False)
            return

        entity_index = session.working_copy.entity_index
        self._status.setText(
            t(
                "editor.draft_status",
                state=t("editor.draft_dirty")
                if session.working_copy.dirty
                else t("editor.draft_clean"),
                count=entity_index.entity_count,
                issues=len(session.validation_issues),
            )
        )
        self._set_buttons_enabled(True)
        self._refresh_route_workspace(session)
        self._render_editing_session(session)
        self._render_history(session)
        self._undo_button.setEnabled(session.working_copy.changeset.undo_available)
        self._redo_button.setEnabled(session.working_copy.changeset.redo_available)
        self._discard_button.setEnabled(session.working_copy.dirty)
        self._confirm_button.setEnabled(True)
        self._set_map_edit_mode(self._map_edit_mode, render=False)
        self.history_state_changed.emit(
            session.working_copy.changeset.undo_available,
            session.working_copy.changeset.redo_available,
        )
        if self._map_window is not None:
            self._map_window.set_history_state(
                session.working_copy.changeset.undo_available,
                session.working_copy.changeset.redo_available,
            )

    def closeEvent(self, event: object) -> None:  # noqa: N802 - Qt API
        """Invalida trabajos cartográficos que aún puedan terminar en segundo plano."""
        self._map_rebuild_token += 1
        self._pending_map_rebuild = None
        self._map_rebuild_timer.stop()
        super().closeEvent(event)  # type: ignore[arg-type]

    def clear(self) -> None:
        self._invalidate_pending_map_rebuild()
        self._map_preview_route_id = None
        clear_map = getattr(self._map_widget, "clear", None)
        if callable(clear_map):
            clear_map()
        self.refresh()

    def retranslate_ui(self) -> None:
        """Actualiza la superficie del editor sin reconstruir el mapa ni el feed."""
        self._title.setText(t("editor.title"))
        self._route_panel.setTitle(t("editor.routes_panel"))
        self._route_hint.setText(t("editor.routes_hint"))
        self._route_search.setAccessibleName(t("editor.route_search"))
        self._route_search.setPlaceholderText(t("editor.route_search_placeholder"))
        self._bulk_label.setText(t("editor.bulk_states"))
        for button, label_key, tooltip_key in (
            (self._bulk_visible_button, "editor.bulk_visible", "editor.bulk_visible_tooltip"),
            (self._bulk_locked_button, "editor.bulk_locked", "editor.bulk_locked_tooltip"),
            (self._bulk_dimmed_button, "editor.bulk_dimmed", "editor.bulk_dimmed_tooltip"),
        ):
            button.setText(t(label_key))
            button.setToolTip(t(tooltip_key))
        self._route_list.setHorizontalHeaderLabels(
            (
                t("routes.visible"),
                t("editor.route_name_header"),
                t("editor.route_id_header"),
                t("editor.agency_operator_header"),
                t("routes.active"),
                t("routes.editable"),
                t("routes.locked"),
                t("routes.dimmed"),
                t("routes.status"),
            )
        )
        self._route_list.setAccessibleName(t("editor.route_list_accessible"))
        self._update_route_selection_status()
        for route_id, row in self._route_rows.items():
            for column, field in (
                (0, "visible"),
                (4, "active"),
                (5, "editable"),
                (6, "locked"),
                (7, "dimmed"),
            ):
                checkbox = self._route_list.cellWidget(row, column)
                if isinstance(checkbox, (QCheckBox, QRadioButton)):
                    self._set_route_state_accessibility(checkbox, field, route_id)
        self._editing_group.setTitle(t("editor.editing_routes"))
        self._editing_routes.setHorizontalHeaderLabels(
            ("#", t("routes.route"), t("editor.role_header"))
        )
        self._context_group.setTitle(t("editor.route_context"))
        self._properties_group.setTitle(t("editor.properties_user_fields"))
        self._technical_group.setTitle(t("editor.properties_technical"))
        for hint, description_key in self._workspace_hints:
            hint.setText(t(description_key))
        self._geometry_hint.setText(t("editor.geometry_hint"))
        self._services_hint.setText(t("editor.services_hint"))
        self._stops_context.setHorizontalHeaderLabels(t("editor.stops_headers").split("|"))
        self._route_properties.setAccessibleName(t("editor.properties"))
        self._route_actions_group.setTitle(t("editor.route_actions_group"))
        self._map_group.setTitle(t("editor.map_group"))
        self._map_legend.setText(t("editor.map_legend"))
        self._cancel_map_edit_button.setText(t("editor.map_cancel"))
        self._form_group.setTitle(t("editor.advanced_draft"))
        for label, key in (
            (self._table_form_label, "editor.table"),
            (self._entity_form_label, "editor.entity"),
            (self._field_form_label, "editor.field"),
            (self._value_form_label, "editor.value"),
        ):
            label.setText(t(key))
        self._advanced_toggle.setText(t("editor.advanced_toggle"))
        self._advanced_toggle.setAccessibleName(t("editor.advanced_toggle"))
        for index, (table_name, _label) in enumerate(_TABLES):
            if index < self._table_selector.count():
                self._table_selector.setItemText(
                    index, t(_TABLE_LABEL_KEYS.get(table_name, "editor.table"))
                )
        self._schedule_group.setTitle(t("editor.schedule_matrix"))
        self._schedule_trip_label.setText(t("editor.schedule_trip"))
        self._schedule_trip.setAccessibleName(t("editor.schedule_trip_accessible"))
        self._interpolation_field.setItemText(0, t("stop.arrival"))
        self._interpolation_field.setItemText(1, t("stop.departure"))
        self._interpolation_field.setAccessibleName(t("editor.interpolation_field"))
        self._interpolation_button.setText(t("editor.interpolation_preview"))
        for index, key in enumerate(
            (
                "editor.schedule_scope_single",
                "editor.schedule_scope_following",
                "editor.schedule_scope_trip",
                "editor.schedule_scope_selected",
            )
        ):
            if index < self._schedule_scope.count():
                self._schedule_scope.setItemText(index, t(key))
        self._schedule_scope.setToolTip(t("editor.schedule_scope_tooltip"))
        self._reschedule_button.setText(t("editor.reschedule_following"))
        self._recalculate_button.setText(t("editor.recalculate_schedule"))
        self._schedule_table.setHorizontalHeaderLabels(
            (
                t("stop.name"),
                t("stop.sequence"),
                t("editor.arrival_gtfs"),
                t("editor.departure_gtfs"),
            )
        )
        self._schedule_table.setAccessibleName(t("editor.schedule_matrix_accessible"))
        self._workspace_group.setTitle(t("editor.workspace_state"))
        for checkbox, key in (
            (self._visible, "routes.visible"),
            (self._active, "routes.active"),
            (self._editable, "routes.editable"),
            (self._locked, "routes.locked"),
            (self._dimmed, "routes.dimmed"),
        ):
            checkbox.setText(t(key))
        self._workspace_apply.setText(t("editor.save_route_state"))
        button_translations: tuple[tuple[QPushButton, str, str | None], ...] = (
            (self._apply_button, "editor.apply", "editor.apply_tooltip"),
            (self._refresh_button, "editor.refresh", None),
            (self._undo_button, "editor.undo", "editor.undo_tooltip"),
            (self._redo_button, "editor.redo", "editor.redo_tooltip"),
            (self._discard_button, "editor.discard", None),
            (self._validate_button, "editor.validate", None),
            (self._delete_button, "editor.delete_entity", "editor.delete_entity_tooltip"),
            (self._add_stop_button, "editor.add_stop", "editor.add_stop_tooltip"),
            (self._reorder_shape_button, "editor.reorder_shape", "editor.reorder_shape_tooltip"),
            (self._confirm_button, "editor.confirm_revision", "editor.confirm_revision_tooltip"),
        )
        for action_button, action_key, action_tooltip_key in button_translations:
            action_button.setText(t(action_key))
            if action_tooltip_key is not None:
                action_button.setToolTip(t(action_tooltip_key))
        self._history.setHorizontalHeaderLabels(t("editor.history_headers").split("|"))
        self._history.setAccessibleName(t("editor.history_accessible"))
        self._editor_tabs.setAccessibleName(t("editor.workspaces_accessible"))
        self._route_selection_status.setText(
            t("editor.no_route_selected")
            if not self._selected_route_ids
            else t(
                "editor.route_selected",
                count=len(self._selected_route_ids),
                visible=len(self._visible_route_ids()),
            )
        )
        self._activate_route_button.setText(t("editor.start_editing"))
        self._activate_route_button.setToolTip(t("editor.start_editing_tooltip"))
        self._finish_editing_button.setText(t("editor.finish_editing"))
        self._open_map_window_button.setText(t("editor.open_cartographic_editor"))
        self._properties_button.setText(t("editor.properties"))
        self._edit_stop_button.setText(t("routes.edit_stops"))
        self._edit_schedule_button.setText(t("routes.edit_schedule"))
        self._edit_service_button.setText(t("routes.edit_services"))
        self._edit_operator_button.setText(t("routes.edit_operator"))
        self._edit_shape_button.setText(t("routes.edit_shape"))
        self._redraw_segment_button.setText(t("routes.redraw_segment"))
        self._reorder_stop_button.setText(t("routes.reorder_stops"))
        self._undo_button.setText(t("editor.undo"))
        self._redo_button.setText(t("editor.redo"))
        self._undo_button.setToolTip(t("editor.undo_tooltip"))
        self._redo_button.setToolTip(t("editor.redo_tooltip"))
        names: tuple[str, ...]
        if self._editor_tabs.count() == 8:
            names = (
                t("editor.workspace_routes"),
                t("editor.properties"),
                t("editor.workspace_shape"),
                t("editor.workspace_stops"),
                t("editor.workspace_schedule"),
                t("editor.workspace_services"),
                t("editor.workspace_history"),
                t("editor.workspace_advanced"),
            )
        else:
            names = (
                t("editor.workspace_routes"),
                t("editor.workspace_shape"),
                t("editor.workspace_stops"),
                t("editor.workspace_schedule"),
                t("editor.workspace_services"),
                t("editor.workspace_history"),
                t("editor.workspace_advanced"),
            )
        for index, name in enumerate(names):
            self._editor_tabs.setTabText(index, name)
        if self._legacy_properties_tab:
            # Compatibilidad con dobles de prueba del contrato pre-0.2.0.
            self._editor_tabs.setTabText(5, t("editor.workspace_history_legacy"))
        session = self._session_provider()
        if session is not None:
            for route_id, row in self._route_rows.items():
                status_item = self._route_list.item(row, 8)
                if status_item is not None:
                    status_item.setText(
                        self._route_state_label_for_route(
                            route_id, session.working_copy.route_state(route_id)
                        )
                    )
            self._render_editing_session(session)
            self._render_route_context()
        if self._map_window is not None:
            self._map_window.retranslate_ui()

    def _refresh_route_workspace(self, session: EditorSession) -> None:
        entity_index = session.working_copy.entity_index
        route_rows = list(entity_index.by_table.get("gtfs_routes", ()))
        route_rows.sort(
            key=lambda item: (
                _sort_value(item[1].get("route_sort_order")),
                str(item[1].get("route_id") or item[0][1]),
                _sort_value(item[1].get("source_row")),
            )
        )
        editing = getattr(session, "editing_session", None)
        if isinstance(editing, EditSession):
            loaded = set(editing.route_ids)
            route_rows = [
                item for item in route_rows if str(item[1].get("route_id") or item[0][1]) in loaded
            ]
        previous_route_id = self._selected_route_id
        route_ids = [str(payload.get("route_id") or key[1]) for key, payload in route_rows]
        if route_ids and not any(
            session.working_copy.route_state(route_id).visible for route_id in route_ids
        ):
            initial_route_id = previous_route_id if previous_route_id in route_ids else route_ids[0]
            initial_state = session.working_copy.route_state(initial_route_id)
            session.set_route_workspace_state(replace(initial_state, visible=True))
        colors = route_colors(
            {
                str(payload.get("route_id") or key[1]): _display_value(payload.get("route_color"))
                for key, payload in route_rows
            }
        )
        self._route_rows.clear()
        for button in self._active_route_buttons.buttons():
            self._active_route_buttons.removeButton(button)
        self._route_list.blockSignals(True)
        self._route_list.setRowCount(len(route_rows))
        for row, (key, payload) in enumerate(route_rows):
            route_id = str(payload.get("route_id") or key[1])
            self._route_rows[route_id] = row
            state = session.working_copy.route_state(route_id)
            operator = self._operator_for_route(entity_index.agencies_by_id, payload)
            short_name = _display_value(payload.get("route_short_name")) or t("routes.name_unknown")
            long_name = _display_value(payload.get("route_long_name"))
            route_label = short_name if not long_name else f"{short_name}\n{long_name}"
            values = (
                "",
                route_label,
                route_id,
                operator,
                "",
                "",
                "",
                "",
                self._route_state_label_for_route(route_id, state),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, route_id)
                item.setToolTip(f"route_id: {route_id}")
                if column == 1:
                    item.setBackground(QColor(colors[route_id]))
                    item.setForeground(QColor(readable_foreground_color(colors[route_id])))
                if state.dimmed:
                    item.setForeground(Qt.GlobalColor.gray)
                self._route_list.setItem(row, column, item)
            self._route_list.setCellWidget(
                row, 0, self._route_state_checkbox(route_id, "visible", state.visible)
            )
            self._route_list.setCellWidget(
                row, 4, self._route_state_checkbox(route_id, "active", state.active)
            )
            self._route_list.setCellWidget(
                row, 5, self._route_state_checkbox(route_id, "editable", state.editable)
            )
            self._route_list.setCellWidget(
                row, 6, self._route_state_checkbox(route_id, "locked", state.locked)
            )
            self._route_list.setCellWidget(
                row, 7, self._route_state_checkbox(route_id, "dimmed", state.dimmed)
            )
        guided_session = isinstance(editing, EditSession)
        for column in (4, 5, 6, 7):
            self._route_list.setColumnHidden(column, guided_session)
        for button in (
            self._bulk_visible_button,
            self._bulk_locked_button,
            self._bulk_dimmed_button,
        ):
            button.setVisible(not guided_session)
        self._route_list.resizeRowsToContents()

        target_row = self._route_rows.get(previous_route_id or "")
        # La fila inspeccionada y la ruta editable son conceptos distintos.
        # Al refrescar una sesión no debemos devolver la selección a la activa:
        # eso impedía comparar una referencia sin perder su contexto.
        if isinstance(editing, EditSession) and previous_route_id not in self._route_rows:
            target_row = self._route_rows.get(editing.active_route_id)
        if target_row is None and route_rows:
            target_row = 0
        if target_row is not None:
            self._route_list.selectRow(target_row)
        self._route_list.blockSignals(False)
        self._route_selection_changed(force=True)

    def _render_editing_session(self, session: EditorSession) -> None:
        editing = getattr(session, "editing_session", None)
        if not isinstance(editing, EditSession):
            self._editing_group.setVisible(False)
            self._editing_header.clear()
            self._editing_routes.setRowCount(0)
            self._render_properties(session)
            return
        self._editing_group.setVisible(True)
        active_route = self._route_payload(editing.active_route_id) or {}
        short_name = _display_value(active_route.get("route_short_name")) or editing.active_route_id
        long_name = _display_value(active_route.get("route_long_name")) or t("stop.not_available")
        self._editing_header.setText(
            t(
                "editor.editing_route_header",
                short_name=short_name,
                long_name=long_name,
                ordinal=editing.ordinal(editing.active_route_id),
                total=editing.total_routes,
            )
        )
        self._editing_routes.setRowCount(len(editing.route_ids))
        for row, route_id in enumerate(editing.route_ids):
            route = self._route_payload(route_id) or {}
            route_short = _display_value(route.get("route_short_name")) or route_id
            route_long = _display_value(route.get("route_long_name"))
            route_label = route_short if not route_long else f"{route_short} · {route_long}"
            status = (
                t("editor.editing")
                if route_id == editing.active_route_id
                else t("editor.reference")
            )
            values = (
                f"{editing.ordinal(route_id)} / {editing.total_routes}",
                route_label,
                status,
            )
            for column, value in enumerate(values):
                self._editing_routes.setItem(row, column, QTableWidgetItem(value))
            if route_id != editing.active_route_id:
                action = QPushButton(t("editor.make_active"), self._editing_routes)
                action.setObjectName(f"makeActive_{_safe_object_name(route_id)}")
                action.clicked.connect(
                    lambda _checked=False, selected_route=route_id: self._make_route_active(
                        selected_route
                    )
                )
                self._editing_routes.setCellWidget(row, 2, action)
            else:
                self._editing_routes.removeCellWidget(row, 2)
        self._editing_routes.resizeColumnsToContents()
        self._render_properties(session)

    def _render_properties(self, session: EditorSession) -> None:
        # Propiedades siempre describe la ruta inspeccionada. La activa solo
        # determina qué acciones pueden modificar el borrador.
        route_id = self._selected_route_id
        route = self._route_payload(route_id)
        if route is None or route_id is None:
            self._properties_user.setText(t("editor.select_route_properties"))
            self._properties_technical.clear()
            return
        entity_index = session.working_copy.entity_index
        operator = self._operator_for_route(entity_index.agencies_by_id, route)
        short_name = _display_value(route.get("route_short_name")) or t("stop.not_available")
        long_name = _display_value(route.get("route_long_name")) or t("stop.not_available")
        route_type = _display_value(route.get("route_type")) or t("stop.not_available")
        self._properties_user.setText(
            t(
                "editor.properties_user_values",
                short_name=short_name,
                long_name=long_name,
                operator=operator,
                route_type=route_type,
            )
        )
        self._properties_technical.setText(
            t(
                "editor.properties_technical_values",
                route_id=route_id,
                agency_id=_display_value(route.get("agency_id")) or t("stop.not_available"),
            )
        )

    def _route_state_checkbox(
        self, route_id: str, field: str, checked: bool
    ) -> QCheckBox | QRadioButton:
        checkbox: QCheckBox | QRadioButton = QRadioButton() if field == "active" else QCheckBox()
        checkbox.setObjectName(f"routeState_{field}_{_safe_object_name(route_id)}")
        self._set_route_state_accessibility(checkbox, field, route_id)
        checkbox.setChecked(checked)
        checkbox.toggled.connect(
            lambda value, selected_route=route_id, state_field=field: self._route_state_toggled(
                selected_route, state_field, value
            )
        )
        if field == "active":
            self._active_route_buttons.addButton(checkbox)
        return checkbox

    def _set_route_state_accessibility(
        self, checkbox: QCheckBox | QRadioButton, field: str, route_id: str
    ) -> None:
        label_key = {
            "visible": "routes.visible",
            "active": "routes.active",
            "editable": "routes.editable",
            "locked": "routes.locked",
            "dimmed": "routes.dimmed",
        }[field]
        label = t(label_key)
        checkbox.setAccessibleName(f"{label} · {route_id}")
        checkbox.setToolTip(f"{label}: {route_id}")

    def _route_state_toggled(self, route_id: str, field: str, value: bool) -> None:
        session = self._session_provider()
        if session is None or field not in {"visible", "active", "editable", "locked", "dimmed"}:
            return
        editing = getattr(session, "editing_session", None)
        if isinstance(editing, EditSession):
            if field == "active" and value:
                self._make_route_active(route_id)
            elif field != "visible":
                self._status.setText(t("editor.reference_locked"))
            return
        # Active tiene semántica de radio: el botón antiguo se desmarca como
        # efecto de seleccionar otro, pero no debe provocar una segunda
        # persistencia ni una segunda reconstrucción del mapa.
        if field == "active" and not value:
            return
        before_states = session.working_copy.route_states
        state = session.working_copy.route_state(route_id)
        if field == "visible":
            updated = replace(state, visible=value)
        elif field == "active":
            updated = replace(state, active=value)
        elif field == "editable":
            updated = replace(state, editable=value)
        elif field == "locked":
            updated = replace(state, locked=value)
        else:
            updated = replace(state, dimmed=value)
        try:
            session.set_route_workspace_state(updated)
        except (TypeError, ValueError) as error:
            self._status.setText(t("editor.route_state_save_error", route_id=route_id, error=error))
            return
        after_states = session.working_copy.route_states
        self._apply_route_state_view(
            before_states,
            after_states,
            # Active solo cambia propiedades de estilo/selección. La geometría
            # ya está en el payload actual y no debe reconstruirse.
            geometry_changed=field == "visible",
            fit=False,
        )

    def _apply_route_state_view(
        self,
        before_states: Mapping[str, object],
        after_states: Mapping[str, object],
        *,
        geometry_changed: bool,
        fit: bool,
    ) -> None:
        changed_route_ids = frozenset(
            candidate
            for candidate in set(before_states) | set(after_states)
            if before_states.get(candidate) != after_states.get(candidate)
        )
        for changed_route_id in changed_route_ids:
            self._update_route_state_row(changed_route_id, after_states.get(changed_route_id))
        self._update_route_selection_status()
        self._render_route_context()
        if geometry_changed:
            self._render_route_map(fit=fit, reset_selection=False)
        else:
            self._update_route_state_map(after_states, changed_route_ids)

    def _bulk_route_state(self, field: str) -> None:
        """Aplica un estado booleano en una sola transacción visual del mapa."""
        if field not in {"visible", "locked", "dimmed"}:
            return
        session = self._session_provider()
        if session is None or not self._route_rows:
            return
        route_ids = tuple(
            route_id
            for route_id, row in self._route_rows.items()
            if not self._route_list.isRowHidden(row)
        )
        if not route_ids:
            return
        before_states = session.working_copy.route_states
        enabled = all(getattr(before_states[route_id], field, False) for route_id in route_ids)
        target = not enabled
        if field == "visible" and target and not self._confirm_mass_visibility(len(route_ids)):
            return
        updates = []
        for route_id in route_ids:
            state = before_states[route_id]
            if field == "visible":
                updated = replace(state, visible=target)
            elif field == "locked":
                updated = replace(state, locked=target)
            else:
                updated = replace(state, dimmed=target)
            updates.append(updated)
        set_states = getattr(session, "set_route_workspace_states", None)
        if callable(set_states):
            set_states(tuple(updates))
        else:
            for updated in updates:
                session.set_route_workspace_state(updated)
        after_states = session.working_copy.route_states
        changed = frozenset(
            route_id
            for route_id in route_ids
            if before_states.get(route_id) != after_states.get(route_id)
        )
        for route_id in changed:
            self._update_route_state_row(route_id, after_states[route_id])
        self._update_route_selection_status()
        self._render_route_context()
        if field == "visible":
            self._render_route_map(fit=False, reset_selection=False)
        else:
            self._update_route_state_map(after_states, changed)
        state_labels = {
            "visible": "routes.visible",
            "locked": "routes.locked",
            "dimmed": "routes.dimmed",
        }
        self._status.setText(
            t(
                "editor.bulk_state_updated",
                state=t(state_labels[field]),
                count=len(changed),
            )
        )
        if field == "visible" and target and 20 < len(route_ids) <= 40:
            self._status.setText(t("editor.visibility_many_routes_notice", count=len(route_ids)))

    def _confirm_mass_visibility(self, count: int) -> bool:
        """Protege solo el rebuild explícito de más de cuarenta rutas."""
        if count <= 40:
            return True
        answer = QMessageBox.question(
            self,
            t("editor.visibility_many_routes_title"),
            t("editor.visibility_many_routes_question", count=count),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _update_route_state_row(self, route_id: str, state: object | None) -> None:
        row = self._route_rows.get(route_id)
        if row is None or state is None:
            return
        state_columns = (
            (0, "visible"),
            (4, "active"),
            (5, "editable"),
            (6, "locked"),
            (7, "dimmed"),
        )
        for column, field in state_columns:
            checkbox = self._route_list.cellWidget(row, column)
            if isinstance(checkbox, (QCheckBox, QRadioButton)):
                checkbox.blockSignals(True)
                checkbox.setChecked(bool(getattr(state, field, False)))
                checkbox.blockSignals(False)
        status_item = self._route_list.item(row, 8)
        if status_item is not None:
            status_item.setText(self._route_state_label_for_route(route_id, state))
        for column in range(1, 9):
            item = self._route_list.item(row, column)
            if item is not None:
                item.setForeground(
                    Qt.GlobalColor.gray if getattr(state, "dimmed", False) else Qt.GlobalColor.black
                )

    def _update_route_selection_status(self) -> None:
        if self._selected_route_ids:
            self._route_selection_status.setText(
                t(
                    "editor.route_selected",
                    count=len(self._selected_route_ids),
                    visible=len(self._visible_route_ids()),
                )
            )
        else:
            self._route_selection_status.setText(t("editor.no_route_selected"))

    def _route_state_label_for_route(self, route_id: str, state: object) -> str:
        session = self._session_provider()
        editing = getattr(session, "editing_session", None) if session is not None else None
        if isinstance(editing, EditSession) and route_id in editing.route_ids:
            return (
                t("editor.editing")
                if route_id == editing.active_route_id
                else t("editor.reference")
            )
        return _route_state_label(state)

    def _filter_routes(self, text: str) -> None:
        needle = text.strip().casefold()
        for row in range(self._route_list.rowCount()):
            values = []
            for column in (1, 2, 3, 8):
                item = self._route_list.item(row, column)
                if item is not None:
                    values.append(item.text())
            haystack = " ".join(values).casefold()
            self._route_list.setRowHidden(row, bool(needle) and needle not in haystack)

    def _route_selection_changed(self, *, force: bool = False) -> None:
        selected_rows = {index.row() for index in self._route_list.selectionModel().selectedRows()}
        route_ids = frozenset(
            route_id for route_id, row in self._route_rows.items() if row in selected_rows
        )
        current_row = self._route_list.currentRow()
        current_item = self._route_list.item(current_row, 2) if current_row >= 0 else None
        current_route_id = (
            str(current_item.data(Qt.ItemDataRole.UserRole))
            if current_item is not None and current_item.data(Qt.ItemDataRole.UserRole) is not None
            else None
        )
        if current_route_id not in self._route_rows:
            current_route_id = next(iter(route_ids), None)
        self._selected_route_id = current_route_id
        self._selected_route_ids = route_ids or (
            frozenset({current_route_id}) if current_route_id is not None else frozenset()
        )
        signature = (self._selected_route_id, self._selected_route_ids)
        if not force and signature == self._selection_signature:
            return
        self._selection_signature = signature
        self._update_route_selection_status()
        self._render_route_context()
        session = self._session_provider()
        if session is not None:
            self._render_history(session)
        self._table_changed(self._table_selector.currentIndex())
        self._refresh_schedule_trips()
        self._sync_selected_route_on_map()

    def _sync_selected_route_on_map(self) -> None:
        """Destaca la ruta inspeccionada sin alterar la ruta editable.

        Cuando ya está en el mapa, MapLibre actualiza únicamente propiedades
        de los features existentes. Una ruta oculta necesita un preview
        temporal, que sí requiere añadir su geometría al payload, pero nunca
        persiste ``Visible``.
        """
        route_id = self._selected_route_id
        session = self._session_provider()
        if route_id is None or session is None:
            if self._map_preview_route_id is not None:
                self._render_route_map(fit=False, reset_selection=False)
            return
        state = session.working_copy.route_state(route_id)
        if self._map_window is not None:
            editing = getattr(session, "editing_session", None)
            active_route_id = self._active_route_id() or route_id
            self._map_window.set_editor_context(
                active_route_id,
                self._map_edit_mode.value,
                _route_display_label(self._route_payload(active_route_id), active_route_id),
                (
                    editing.ordinal(active_route_id)
                    if isinstance(editing, EditSession) and active_route_id in editing.route_ids
                    else 1
                ),
                editing.total_routes if isinstance(editing, EditSession) else 1,
                selected_route_id=route_id,
                selected_route_label=_route_display_label(self._route_payload(route_id), route_id),
            )
        update_selection = getattr(self._map_widget, "update_route_selection", None)
        # Un cambio preview A -> ruta visible B necesita reemplazar el payload;
        # actualizar solo la selección dejaba A dibujada como ruta fantasma.
        if self._map_preview_route_id is not None and self._map_preview_route_id != route_id:
            self._render_route_map(fit=False, reset_selection=False)
            return
        if self._map_rendered and state.visible and callable(update_selection):
            self._invalidate_pending_map_rebuild()
            update_selection(route_id)
            return
        self._render_route_map(fit=not self._map_rendered, reset_selection=False)

    def _invalidate_pending_map_rebuild(self) -> None:
        """Impide que una consulta previa restaure un preview ya descartado."""
        if self._pending_map_rebuild is not None:
            self._map_rebuild_token += 1
            self._pending_map_rebuild = None
            self._map_rebuild_timer.stop()

    def _visible_route_ids(self) -> frozenset[str]:
        session = self._session_provider()
        if session is None:
            return frozenset()
        editing = getattr(session, "editing_session", None)
        if isinstance(editing, EditSession):
            return frozenset(editing.route_ids)
        return frozenset(
            route_id
            for route_id in self._route_rows
            if session.working_copy.route_state(route_id).visible
        )

    def _active_route_id(self) -> str | None:
        session = self._session_provider()
        if session is None:
            return None
        editing = getattr(session, "editing_session", None)
        if isinstance(editing, EditSession):
            return editing.active_route_id
        for route_id in self._route_rows:
            if session.working_copy.route_state(route_id).active:
                return route_id
        return None

    @staticmethod
    def _operator_for_route(agencies: dict[str, dict[str, Any]], route: dict[str, Any]) -> str:
        agency_id = _display_value(route.get("agency_id"))
        agency = agencies.get(agency_id)
        if agency is None and len(agencies) == 1:
            agency = next(iter(agencies.values()))
            agency_id = _display_value(agency.get("agency_id"))
        if agency is None:
            return agency_id or t("editor.operator_unknown")
        name = _display_value(agency.get("agency_name")) or t("editor.agency_name_unknown")
        return f"{name} ({agency_id})" if agency_id else name

    def _route_payload(self, route_id: str | None) -> dict[str, Any] | None:
        session = self._session_provider()
        if session is None or route_id is None:
            return None
        return session.working_copy.entity_index.routes_by_id.get(route_id)

    def _render_route_context(self) -> None:
        session = self._session_provider()
        route_id = self._selected_route_id
        route = self._route_payload(route_id)
        has_route = session is not None and route_id is not None and route is not None
        for button in (
            self._activate_route_button,
            self._finish_editing_button,
            self._open_map_window_button,
            self._properties_button,
            self._edit_shape_button,
            self._redraw_segment_button,
            self._edit_stop_button,
            self._edit_schedule_button,
            self._edit_service_button,
            self._edit_operator_button,
            self._reorder_stop_button,
        ):
            button.setEnabled(bool(has_route))
        if not has_route or session is None or route is None or route_id is None:
            self._route_properties.setText(t("editor.select_route_properties"))
            self._route_context_status.clear()
            self._render_properties(session) if session is not None else None
            return
        entity_index = session.working_copy.entity_index
        trips = [payload for _key, payload in entity_index.trips_by_route.get(route_id, ())]
        trip_ids = {str(payload.get("trip_id")) for payload in trips if payload.get("trip_id")}
        service_ids = {
            str(payload.get("service_id"))
            for payload in trips
            if payload.get("service_id") is not None
        }
        stop_ids = {
            str(payload.get("stop_id"))
            for trip_id in trip_ids
            for _key, payload in entity_index.stop_times_by_trip.get(trip_id, ())
            if payload.get("stop_id") is not None
        }
        shape_ids = {
            str(payload.get("shape_id")) for payload in trips if payload.get("shape_id") is not None
        }
        attributions = [
            payload
            for _key, payload in entity_index.by_table.get("gtfs_attributions", ())
            if (str(payload.get("route_id")) == route_id or payload.get("route_id") in (None, ""))
        ]
        state = session.working_copy.route_state(route_id)
        short_name = _display_value(route.get("route_short_name")) or t("routes.name_unknown")
        long_name = _display_value(route.get("route_long_name")) or t("routes.long_name_unknown")
        operator = self._operator_for_route(entity_index.agencies_by_id, route)
        self._route_properties.setText(
            t(
                "editor.route_context_properties",
                short_name=short_name,
                long_name=long_name,
                route_id=route_id,
                operator=operator,
                services=len(service_ids),
                trips=len(trips),
                stops=len(stop_ids),
                shapes=len(shape_ids),
                attributions=len(attributions),
            )
        )
        self._render_properties(session)
        self._render_route_workspaces(
            session, route_id, trips, service_ids, shape_ids, attributions
        )
        if state.locked:
            context_status = t("editor.route_locked")
        elif state.can_edit:
            context_status = t("editor.route_editable")
        elif state.active:
            context_status = t("editor.route_active_not_editable")
        else:
            context_status = t("editor.route_reference")
        self._route_context_status.setText(context_status)
        editing = getattr(session, "editing_session", None)
        self._activate_route_button.setEnabled(
            not state.locked and not isinstance(editing, EditSession)
        )
        self._finish_editing_button.setEnabled(isinstance(editing, EditSession))
        can_mutate = state.can_edit
        for button in (
            self._edit_shape_button,
            self._redraw_segment_button,
            self._edit_stop_button,
            self._edit_schedule_button,
            self._edit_service_button,
            self._edit_operator_button,
            self._reorder_stop_button,
        ):
            button.setEnabled(can_mutate)

    def _render_route_workspaces(
        self,
        session: EditorSession,
        route_id: str,
        trips: list[dict[str, Any]],
        service_ids: set[str],
        shape_ids: set[str],
        attributions: list[dict[str, Any]],
    ) -> None:
        """Materializa los datos del contexto ya indexado, sin escanear GTFS."""
        index = session.working_copy.entity_index
        shape_summary = ", ".join(sorted(shape_ids)) or t("stop.not_available")
        self._geometry_context.setText(
            t("editor.geometry_context", route_id=route_id, shapes=shape_summary, trips=len(trips))
        )
        trip = trips[0] if trips else None
        trip_id = str(trip.get("trip_id")) if trip and trip.get("trip_id") else None
        rows = list(index.stop_times_by_trip.get(trip_id or "", ()))
        rows.sort(key=lambda item: _sequence(item[1].get("stop_sequence")))
        self._stops_context.setRowCount(len(rows))
        for row_index, (_key, stop_time) in enumerate(rows):
            stop_id = _display_value(stop_time.get("stop_id"))
            stop = index.stops_by_id.get(stop_id, {})
            endpoint = (
                t("stop.origin")
                if row_index == 0
                else t("stop.destination")
                if row_index == len(rows) - 1
                else t("stop.intermediate")
            )
            values = (
                _display_value(stop_time.get("stop_sequence")),
                _display_value(stop.get("stop_name")) or t("stop.name_unknown"),
                stop_id,
                endpoint,
                f"{_display_value(stop_time.get('arrival_time_lexeme'))} · "
                f"{_display_value(stop_time.get('departure_time_lexeme'))}",
            )
            for column, value in enumerate(values):
                self._stops_context.setItem(row_index, column, QTableWidgetItem(value))
        route = self._route_payload(route_id) or {}
        agency_id = _display_value(route.get("agency_id"))
        agency = index.agencies_by_id.get(agency_id, {})
        agency_name = _display_value(agency.get("agency_name")) or self._operator_for_route(
            index.agencies_by_id, route
        )
        self._services_context.setText(
            t(
                "editor.services_context",
                agency=agency_name,
                agency_id=agency_id or t("stop.not_available"),
                services=", ".join(sorted(service_ids)) or t("stop.not_available"),
                attributions=len(attributions),
            )
        )

    def _render_route_map(self, *, fit: bool = False, reset_selection: bool = False) -> None:
        if self._map_widget is None:
            return
        if self._map_layers_for_routes is None:
            return
        route_ids, preview_route_id = self._map_route_context()
        mark(self._performance_trace, "T0_REQUEST_RECEIVED", generation=self._map_rebuild_token + 1)
        if getattr(self._map_widget, "supports_async_rebuild", False):
            self._map_rebuild_token += 1
            self._pending_map_rebuild = (self._map_rebuild_token, fit, reset_selection)
            self._map_rebuild_timer.start()
            self._status.setText(t("editor.routes_map_refreshing"))
            return
        self._render_route_map_sync(
            route_ids,
            preview_route_id=preview_route_id,
            fit=fit,
            reset_selection=reset_selection,
        )

    def _start_pending_map_rebuild(self) -> None:
        pending = self._pending_map_rebuild
        builder = self._map_layers_for_routes
        if pending is None or builder is None:
            return
        mark(self._performance_trace, "T1_DEBOUNCE_COMPLETED", generation=pending[0])
        token, fit, reset_selection = pending
        self._pending_map_rebuild = None
        route_ids, preview_route_id = self._map_route_context()
        include_shape_points = self._map_edit_mode in {
            MapEditMode.EDIT_ROUTE,
            MapEditMode.SELECT_SEGMENT,
            MapEditMode.REDRAW_SEGMENT,
        }

        def query() -> MapLayerPayload:
            mark(self._performance_trace, "T2_WORKER_STARTED", generation=token)
            return builder(
                route_ids,
                include_shape_points=include_shape_points,
                segment=self._segment_selection,
                preview_route_id=preview_route_id,
                session_route_ids=self._session_route_ids(),
            )

        job = _MapRebuildJob(token, query, self._performance_trace)
        job.signals.finished.connect(
            lambda finished_token, payload, signals=job.signals: self._map_rebuild_finished(
                finished_token, payload, signals
            )
        )
        job.signals.failed.connect(
            lambda failed_token, message, signals=job.signals: self._map_rebuild_failed(
                failed_token, message, signals
            )
        )
        self._map_rebuild_signals.add(job.signals)
        QThreadPool.globalInstance().start(job)

    def _map_rebuild_finished(
        self, token: int, payload: object, signals: _MapRebuildSignals | None = None
    ) -> None:
        mark(self._performance_trace, "T9_RESULT_RECEIVED_GUI", generation=token)
        if signals is not None:
            self._map_rebuild_signals.discard(signals)
        if token != self._map_rebuild_token:
            if self._performance_trace is not None:
                self._performance_trace.count("stale_results_discarded")
            mark(self._performance_trace, "T9_STALE_RESULT_DISCARDED", generation=token)
            return
        self._render_map_payload(payload, fit=False, reset_selection=False, generation=token)
        self._status.setText(t("editor.routes_map_updated"))

    def _map_rebuild_failed(
        self, token: int, message: str, signals: _MapRebuildSignals | None = None
    ) -> None:
        if signals is not None:
            self._map_rebuild_signals.discard(signals)
        if token == self._map_rebuild_token:
            self._route_context_status.setText(t("editor.routes_map_error", message=message))

    def _render_route_map_sync(
        self,
        route_ids: frozenset[str],
        *,
        preview_route_id: str | None,
        fit: bool,
        reset_selection: bool,
    ) -> None:
        builder = self._map_layers_for_routes
        if builder is None:
            return
        try:
            try:
                payload = builder(
                    route_ids,
                    include_shape_points=self._map_edit_mode
                    in {
                        MapEditMode.EDIT_ROUTE,
                        MapEditMode.SELECT_SEGMENT,
                        MapEditMode.REDRAW_SEGMENT,
                    },
                    segment=self._segment_selection,
                    preview_route_id=preview_route_id,
                    session_route_ids=self._session_route_ids(),
                )
            except TypeError:
                payload = builder(route_ids)
        except (RuntimeError, TypeError, ValueError) as error:
            self._route_context_status.setText(t("editor.routes_map_error_short", error=error))
            return
        self._render_map_payload(payload, fit=fit, reset_selection=reset_selection)

    def _map_route_context(self) -> tuple[frozenset[str], str | None]:
        """Devuelve el contexto cartográfico y el preview no persistente."""
        visible = self._visible_route_ids()
        route_id = self._selected_route_id
        session = self._session_provider()
        if route_id is None or session is None or route_id in visible:
            return visible, None
        return visible | frozenset({route_id}), route_id

    def _session_route_ids(self) -> frozenset[str]:
        session = self._session_provider()
        editing = getattr(session, "editing_session", None) if session is not None else None
        return frozenset(editing.route_ids) if isinstance(editing, EditSession) else frozenset()

    def _render_map_payload(
        self,
        payload: object,
        *,
        fit: bool,
        reset_selection: bool,
        generation: int | None = None,
    ) -> None:
        show_payload = getattr(self._map_widget, "show_payload", None)
        if callable(show_payload):
            mark(
                self._performance_trace,
                "T10_MAPWIDGET_SHOW_PAYLOAD",
                generation=generation,
            )
            set_mode = getattr(self._map_widget, "set_edit_mode", None)
            if callable(set_mode):
                set_mode(self._map_edit_mode)
            try:
                show_payload(
                    payload,
                    fit=fit,
                    reset_selection=reset_selection,
                    generation=generation,
                )
            except TypeError:
                # Compatibilidad con dobles de prueba y hosts de mapa previos.
                show_payload(payload)
            self._map_rendered = True
            self._map_preview_route_id = self._map_route_context()[1]
            session = self._session_provider()
            self._map_active_route_id = next(
                (
                    candidate
                    for candidate in self._route_rows
                    if session is not None and session.working_copy.route_state(candidate).active
                ),
                None,
            )

    def _update_route_state_map(
        self,
        states: Mapping[str, object],
        route_ids: frozenset[str],
    ) -> None:
        if self._map_widget is None or not self._map_rendered:
            return
        update_states = getattr(self._map_widget, "update_route_states", None)
        if not callable(update_states):
            return
        session_route_ids = self._session_route_ids()
        visible_states = {
            route_id: states[route_id]
            for route_id in route_ids
            if route_id in states
            and (getattr(states[route_id], "visible", False) or route_id in session_route_ids)
        }
        if visible_states:
            update_states(visible_states)

    def _make_route_active(self, route_id: str) -> None:
        session = self._session_provider()
        editing = getattr(session, "editing_session", None) if session is not None else None
        if session is None or not isinstance(editing, EditSession):
            return
        before_states = session.working_copy.route_states
        try:
            activate = getattr(session, "activate_editing_route")
            activate(route_id)
        except (AttributeError, TypeError, ValueError) as error:
            self._status.setText(str(error))
            return
        after_states = session.working_copy.route_states
        self._selected_route_id = route_id
        self._selected_route_ids = frozenset(editing.route_ids)
        self._apply_route_state_view(
            before_states,
            after_states,
            geometry_changed=False,
            fit=False,
        )
        self._render_editing_session(session)
        if self._map_window is not None:
            self._map_window.set_editor_context(
                route_id,
                self._map_edit_mode.value,
                _route_display_label(self._route_payload(route_id), route_id),
                editing.ordinal(route_id),
                editing.total_routes,
                selected_route_id=self._selected_route_id,
                selected_route_label=_route_display_label(
                    self._route_payload(self._selected_route_id), self._selected_route_id or ""
                ),
            )

    def _start_editing(self) -> None:
        session = self._session_provider()
        route_id = self._selected_route_id
        if session is None or route_id is None:
            return
        route_labels: dict[str, str] = {}
        for candidate, row in self._route_rows.items():
            route = self._route_payload(candidate) or {}
            route_labels[candidate] = _route_display_label(route, candidate)
        dialog = RouteEditSelectionDialog(route_labels, parent=self)
        selected = tuple(
            route_id for route_id in self._route_rows if route_id in self._selected_route_ids
        )
        if selected and len(selected) <= MAX_EDITING_ROUTES:
            dialog.set_selected_route_ids(selected)
            dialog.set_active_route_id(route_id if route_id in selected else selected[0])
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected_routes = dialog.selected_route_ids
        try:
            start = getattr(session, "start_editing")
            start(
                selected_routes,
                active_route_id=dialog.active_route_id,
            )
        except AttributeError:
            # Compatibilidad con dobles antiguos: mantienen la semántica
            # existente, pero la aplicación real siempre usa EditSession.
            state = session.working_copy.route_state(route_id)
            if state.locked:
                self._route_context_status.setText(t("editor.route_locked"))
                return
            before_states = session.working_copy.route_states
            session.set_route_workspace_state(
                replace(state, active=True, editable=True, visible=True, locked=False)
            )
            after_states = session.working_copy.route_states
            self._apply_route_state_view(
                before_states,
                after_states,
                geometry_changed=False,
                fit=False,
            )
        except (TypeError, ValueError) as error:
            self._route_context_status.setText(str(error))
            return
        self.refresh()
        self._open_map_window()

    def _activate_selected_route(self) -> None:
        """Alias histórico para integraciones que invocaban el botón antiguo."""
        self._start_editing()

    def _finish_editing(self) -> None:
        if self._on_finish_editing is not None:
            self._on_finish_editing()
            return
        session = self._session_provider()
        finish = getattr(session, "finish_editing", None) if session is not None else None
        if session is None or not callable(finish):
            return
        editing_dirty = getattr(session, "editing_dirty", None)
        if editing_dirty is None:
            editing_dirty = session.dirty
        if not editing_dirty:
            finish()
            self.refresh()
            return
        dialog = QMessageBox(self)
        dialog.setWindowTitle(t("editor.finish_changes_title"))
        dialog.setText(t("editor.finish_changes_message"))
        dialog.addButton(t("editor.preserve_draft"), QMessageBox.ButtonRole.AcceptRole)
        discard = dialog.addButton(
            t("editor.discard_session_changes"), QMessageBox.ButtonRole.DestructiveRole
        )
        cancel = dialog.addButton(t("editor.cancel_finish"), QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        clicked = dialog.clickedButton()
        if clicked is cancel:
            return
        finish(discard_session_changes=clicked is discard)
        self.close_map_window()
        self.refresh()

    def _focus_advanced_table(self, table_name: str, message: str) -> None:
        if self._selected_route_id is None:
            return
        self._advanced_toggle.setChecked(True)
        index = self._table_selector.findData(table_name)
        if index >= 0:
            self._table_selector.setCurrentIndex(index)
        self._status.setText(message)

    def _edit_selected_shape(self) -> None:
        self._editor_tabs.setCurrentWidget(self._geometry_page)
        self._segment_selection = None
        self._segment_selection_shape = None
        self._set_map_edit_mode(MapEditMode.EDIT_ROUTE)
        self._focus_advanced_table(
            "gtfs_shapes",
            t("editor.edit_shape_hint"),
        )

    def _redraw_selected_segment(self) -> None:
        self._editor_tabs.setCurrentWidget(self._geometry_page)
        self._segment_selection = None
        self._segment_selection_shape = None
        self._set_map_edit_mode(MapEditMode.SELECT_SEGMENT)
        self._focus_advanced_table(
            "gtfs_shapes",
            t("editor.redraw_segment_hint"),
        )

    def _set_map_edit_mode(self, mode: MapEditMode, *, render: bool = True) -> None:
        self._map_edit_mode = mode
        labels = {
            MapEditMode.NORMAL: t("map.mode_normal"),
            MapEditMode.EDIT_ROUTE: t("map.mode_edit_route"),
            MapEditMode.SELECT_SEGMENT: t("map.mode_select_segment"),
            MapEditMode.REDRAW_SEGMENT: t("map.mode_redraw_segment"),
        }
        self._map_mode_status.setText(labels[mode])
        if self._map_window is not None and self._selected_route_id is not None:
            editing = getattr(self._session_provider(), "editing_session", None)
            active_route_id = self._active_route_id() or self._selected_route_id
            self._map_window.set_editor_context(
                active_route_id,
                mode.value,
                _route_display_label(self._route_payload(active_route_id), active_route_id),
                editing.ordinal(active_route_id)
                if isinstance(editing, EditSession) and active_route_id in editing.route_ids
                else 1,
                editing.total_routes if isinstance(editing, EditSession) else 1,
                selected_route_id=self._selected_route_id,
                selected_route_label=_route_display_label(
                    self._route_payload(self._selected_route_id), self._selected_route_id or ""
                ),
            )
        self._cancel_map_edit_button.setVisible(mode is not MapEditMode.NORMAL)
        segment_mode = mode is MapEditMode.REDRAW_SEGMENT
        self._add_segment_vertex_button.setVisible(segment_mode)
        self._delete_segment_vertex_button.setVisible(segment_mode)
        set_mode = getattr(self._map_widget, "set_edit_mode", None)
        if callable(set_mode):
            set_mode(mode)
        if render and self._map_rendered:
            self._render_route_map()

    def _cancel_map_edit(self) -> None:
        if self._on_cancel_map_operation is not None:
            self._on_cancel_map_operation()
        self._segment_selection = None
        self._set_map_edit_mode(MapEditMode.NORMAL)
        self._status.setText(t("editor.map_cancelled"))

    def _confirm_map_operation(self) -> None:
        if self._on_confirm_map_operation is not None:
            self._on_confirm_map_operation()

    def _arm_add_segment_vertex(self) -> None:
        if self._map_edit_mode is not MapEditMode.REDRAW_SEGMENT:
            return
        set_action = getattr(self._map_widget, "set_vertex_action", None)
        if callable(set_action):
            set_action("add")
        self._status.setText(t("editor.add_vertex_point_ready"))

    def _arm_delete_segment_vertex(self) -> None:
        if self._map_edit_mode is not MapEditMode.REDRAW_SEGMENT:
            return
        set_action = getattr(self._map_widget, "set_vertex_action", None)
        if callable(set_action):
            set_action("delete")
        self._status.setText(t("editor.delete_vertex_handle_ready"))

    def handle_map_gesture(self, gesture: MapEditGesture) -> bool:
        """Consume selecciones cartográficas sin convertirlas en comandos."""
        if gesture.action != "select" or self._map_edit_mode is not MapEditMode.SELECT_SEGMENT:
            return False
        shape_id = gesture.shape_id
        if not shape_id:
            self._status.setText(t("editor.shape_missing"))
            return True
        selected_id = gesture.entity_id
        if self._segment_selection is None:
            self._segment_selection = (selected_id, selected_id)
            self._segment_selection_shape = shape_id
            self._status.setText(t("editor.segment_start_selected"))
            return True
        if self._segment_selection_shape != shape_id:
            self._status.setText(t("editor.segment_rejected"))
            return True
        self._segment_selection = (self._segment_selection[0], selected_id)
        self._set_map_edit_mode(MapEditMode.REDRAW_SEGMENT)
        self._status.setText(t("editor.segment_selected"))
        return True

    def _edit_selected_stops(self) -> None:
        self._editor_tabs.setCurrentWidget(self._stops_page)
        self._focus_advanced_table(
            "gtfs_stops",
            t("editor.edit_stops_hint"),
        )
        self._schedule_table.setFocus()

    def _reorder_selected_stop(self) -> None:
        session = self._session_provider()
        trip_id = self._schedule_trip.currentData()
        row_index = self._schedule_table.currentRow()
        row_item = self._schedule_table.item(row_index, 0) if row_index >= 0 else None
        entity_key = row_item.data(Qt.ItemDataRole.UserRole) if row_item is not None else None
        if session is None or not isinstance(trip_id, str) or not isinstance(entity_key, tuple):
            self._status.setText(t("editor.reorder_stop_select"))
            return
        if self._selected_route_id is not None and not session.can_edit_route(
            self._selected_route_id
        ):
            self._status.setText(t("editor.route_not_authorized"))
            return
        from gtfs_explorer.application.schedule_editing import ScheduleEditor

        editor = ScheduleEditor(session)
        matrix = editor.matrix(trip_id)
        current_index = next(
            (index for index, item in enumerate(matrix) if item.entity_key == entity_key),
            None,
        )
        if current_index is None:
            self._status.setText(t("editor.stop_not_in_trip"))
            return
        position, accepted = QInputDialog.getInt(
            self,
            t("editor.reorder_stop_title"),
            t("editor.position_range", maximum=len(matrix)),
            current_index + 1,
            1,
            max(1, len(matrix)),
        )
        if not accepted or position == current_index + 1:
            return
        try:
            proposal = editor.propose_reorder(trip_id, entity_key, position - 1)
            if not self._confirm_impact(proposal.impact):
                return
            editor.apply(proposal)
        except (TypeError, ValueError) as error:
            self._status.setText(t("editor.reorder_stop_error", error=error))
            return
        self._status.setText(t("editor.reorder_stop_done", trip_id=trip_id))
        self.refresh()

    def _edit_selected_schedule(self) -> None:
        self._editor_tabs.setCurrentWidget(self._schedule_page)
        active_route = self._active_route_id()
        if active_route is not None:
            self._selected_route_id = active_route
            self._refresh_schedule_trips()
        self._status.setText(t("editor.schedule_loaded"))
        if self._schedule_trip.count():
            self._schedule_trip.setFocus()

    def _edit_selected_services(self) -> None:
        self._editor_tabs.setCurrentWidget(self._service_page)
        self._focus_advanced_table(
            "gtfs_calendar",
            t("editor.edit_services_hint"),
        )

    def _edit_selected_operator(self) -> None:
        self._editor_tabs.setCurrentWidget(self._service_page)
        self._focus_advanced_table(
            "gtfs_agency",
            t("editor.edit_operator_hint"),
        )

    def _show_selected_properties(self) -> None:
        self._editor_tabs.setCurrentWidget(self._properties_page)
        active_route = self._active_route_id()
        if active_route is not None:
            self._selected_route_id = active_route
        session = self._session_provider()
        if session is not None:
            self._render_properties(session)
        self._properties_user.setFocus()
        self._status.setText(t("editor.properties_loaded"))

    def _refresh_schedule_trips(self) -> None:
        session = self._session_provider()
        if session is None:
            return
        selected = self._schedule_trip.currentData()
        selected_route_id = self._selected_route_id
        entity_index = session.working_copy.entity_index
        trip_candidates = (
            entity_index.by_table.get("gtfs_trips", ())
            if selected_route_id is None
            else entity_index.trips_by_route.get(selected_route_id, ())
        )
        trip_rows = sorted(
            (
                str(payload.get("trip_id")),
                str(payload.get("route_id") or ""),
            )
            for _key, payload in trip_candidates
            if payload.get("trip_id") is not None
        )
        self._schedule_trip.blockSignals(True)
        self._schedule_trip.clear()
        for trip_id, route_id in trip_rows:
            self._schedule_trip.addItem(f"{trip_id}{f' · {route_id}' if route_id else ''}", trip_id)
        if selected is not None:
            index = self._schedule_trip.findData(selected)
            if index >= 0:
                self._schedule_trip.setCurrentIndex(index)
        if self._schedule_trip.count() and self._schedule_trip.currentIndex() < 0:
            self._schedule_trip.setCurrentIndex(0)
        self._schedule_trip.blockSignals(False)
        self._render_schedule_matrix()

    def _schedule_trip_changed(self, _index: int) -> None:
        self._render_schedule_matrix()

    def _render_schedule_matrix(self) -> None:
        session = self._session_provider()
        trip_id = self._schedule_trip.currentData()
        if session is None or trip_id is None:
            self._schedule_table.setRowCount(0)
            return
        from gtfs_explorer.application.schedule_editing import ScheduleEditor

        rows = ScheduleEditor(session).matrix(str(trip_id))
        self._schedule_table.blockSignals(True)
        self._schedule_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = (
                row.stop_id or "",
                "" if row.stop_sequence is None else str(row.stop_sequence),
                row.arrival_time or "",
                row.departure_time or "",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, row.entity_key)
                if column < 2:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._schedule_table.setItem(row_index, column, item)
        self._schedule_table.blockSignals(False)

    def _schedule_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() not in {2, 3}:
            return
        session = self._session_provider()
        trip_id = self._schedule_trip.currentData()
        key = item.data(Qt.ItemDataRole.UserRole)
        if session is None or trip_id is None or not isinstance(key, tuple):
            return
        from gtfs_explorer.application.schedule_editing import ScheduleEditor

        field = "arrival_time_lexeme" if item.column() == 2 else "departure_time_lexeme"
        try:
            proposal = ScheduleEditor(session).propose_time_update(key, field, item.text())
            session.apply(proposal.command, impact=proposal.impact)
        except (TypeError, ValueError) as error:
            self._status.setText(t("editor.schedule_update_error", error=error))
        self.refresh()

    def _preview_interpolation(self) -> None:
        session = self._session_provider()
        trip_id = self._schedule_trip.currentData()
        field = self._interpolation_field.currentData()
        if session is None or trip_id is None or not isinstance(field, str):
            return
        from gtfs_explorer.application.schedule_editing import ScheduleEditor

        editor = ScheduleEditor(session)
        try:
            cells = editor.interpolation_preview(str(trip_id), field)
        except ValueError as error:
            self._status.setText(t("editor.interpolation_error", error=error))
            return
        if not cells:
            self._status.setText(t("editor.no_events_between_anchors"))
            return
        details = "\n".join(f"{cell.entity_key[1]} → {cell.lexeme}" for cell in cells)
        confirmation = QMessageBox.question(
            self,
            t("editor.interpolation_title"),
            t("editor.interpolation_question", details=details),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return
        try:
            command = editor.apply_interpolation(cells, accepted=True)
            if command is not None:
                session.apply(command, impact=session.preview_impact(command))
        except (TypeError, ValueError) as error:
            self._status.setText(t("editor.interpolation_apply_error", error=error))
        self.refresh()

    def _table_changed(self, _index: int) -> None:
        session = self._session_provider()
        if session is None:
            return
        table_name = str(self._table_selector.currentData())
        route_id = self._selected_route_id
        route_scoped_tables = {
            "gtfs_routes",
            "gtfs_trips",
            "gtfs_stops",
            "gtfs_stop_times",
            "gtfs_shapes",
            "gtfs_calendar",
            "gtfs_calendar_dates",
            "gtfs_agency",
            "gtfs_attributions",
        }
        entity_index = session.working_copy.entity_index
        self._payloads = {
            key: payload
            for key, payload in entity_index.by_table.get(table_name, ())
            if (
                route_id is None
                or table_name not in route_scoped_tables
                or route_id in entity_index.route_ids_by_entity.get(key, frozenset())
            )
        }
        self._keys = sorted(self._payloads)
        self._entity_selector.blockSignals(True)
        self._entity_selector.clear()
        for key in self._keys:
            self._entity_selector.addItem(key[1], key)
        self._entity_selector.blockSignals(False)
        self._entity_changed(self._entity_selector.currentIndex())

    def _entity_changed(self, _index: int) -> None:
        self._field_selector.blockSignals(True)
        self._field_selector.clear()
        key = self._current_key()
        if key is not None:
            for field_name in sorted(
                field for field in self._payloads[key] if field not in _EDITABLE_FIELDS
            ):
                self._field_selector.addItem(field_name, field_name)
        self._field_selector.blockSignals(False)
        self._field_changed(self._field_selector.currentIndex())
        self._load_workspace_state()
        self._update_delete_button()

    def _field_changed(self, _index: int) -> None:
        key = self._current_key()
        field_name = self._current_field()
        if key is None or field_name is None:
            self._value.clear()
            self._value.setEnabled(False)
            return
        self._value.setEnabled(True)
        self._value.setText(_display_value(self._payloads[key].get(field_name)))

    def _apply_change(self) -> None:
        session = self._session_provider()
        key = self._current_key()
        field_name = self._current_field()
        if session is None or key is None or field_name is None:
            return
        if not self._entity_is_editable(key):
            return
        before = session.working_copy.get(key)
        if before is None:
            self._status.setText(t("editor.entity_missing"))
            return
        after = dict(before)
        try:
            after[field_name] = _parse_value(self._value.text(), before.get(field_name))
            command = EditorCommand(_COMMAND_KINDS[key[0]], key, before, after)
            impact = session.preview_impact(command)
            resolved_command, impact = self._resolve_impact(session, command, impact)
            if resolved_command is None:
                return
            command = resolved_command
            if not self._confirm_impact(impact):
                return
            session.apply(command, impact=impact)
        except (TypeError, ValueError) as error:
            self._status.setText(t("editor.change_error", error=error))
            return
        self.refresh()

    def _delete(self) -> None:
        session = self._session_provider()
        key = self._current_key()
        if session is None or key is None or key[0] not in _DELETE_KINDS:
            return
        before = session.working_copy.get(key)
        if before is None:
            self._status.setText(t("editor.entity_missing"))
            return
        if not self._entity_is_editable(key):
            return
        command_kind = _DELETE_KINDS[key[0]]
        command = EditorCommand(command_kind, key, before, None)
        try:
            impact = session.preview_impact(command)
            resolved_command, impact = self._resolve_impact(session, command, impact)
            if resolved_command is None:
                return
            command = resolved_command
            if not self._confirm_impact(impact, title=t("editor.delete_title")):
                return
            session.apply(command, impact=impact)
        except (TypeError, ValueError) as error:
            self._status.setText(t("editor.delete_error", error=error))
            return
        self.refresh()

    def _add_stop(self) -> None:
        session = self._session_provider()
        route_id = self._selected_route_id
        trip_id = self._schedule_trip.currentData()
        if session is None or route_id is None or not isinstance(trip_id, str):
            self._status.setText(t("editor.add_stop_route_prompt"))
            return
        trip = session.working_copy.entity_index.trips_by_id.get(trip_id)
        if trip is None or str(trip.get("route_id") or "") != route_id:
            self._status.setText(t("editor.trip_not_active_route"))
            return
        if not session.can_edit_route(route_id):
            self._status.setText(t("editor.route_not_authorized_change"))
            return
        name, accepted = QInputDialog.getText(
            self, t("editor.add_stop_title"), t("editor.add_stop_name_prompt")
        )
        if not accepted:
            return
        latitude, accepted = QInputDialog.getDouble(
            self, t("editor.add_stop_title"), t("editor.add_stop_latitude"), 0.0, -90.0, 90.0, 8
        )
        if not accepted:
            return
        longitude, accepted = QInputDialog.getDouble(
            self, t("editor.add_stop_title"), t("editor.add_stop_longitude"), 0.0, -180.0, 180.0, 8
        )
        if not accepted:
            return
        arrival_time, accepted = QInputDialog.getText(
            self, t("editor.add_stop_title"), t("editor.add_stop_arrival")
        )
        if not accepted:
            return
        departure_time, accepted = QInputDialog.getText(
            self, t("editor.add_stop_title"), t("editor.add_stop_departure")
        )
        if not accepted:
            return
        stop_id = _new_draft_stop_id(session.working_copy.entity_index)
        from gtfs_explorer.application.schedule_editing import ScheduleEditor

        editor = ScheduleEditor(session)
        try:
            proposal = editor.propose_add_stop_to_trip(
                trip_id,
                stop_id=stop_id,
                stop_name=name.strip() or None,
                latitude=latitude,
                longitude=longitude,
                arrival_time=arrival_time.strip() or None,
                departure_time=departure_time.strip() or None,
            )
            if not self._confirm_impact(proposal.impact):
                return
            editor.apply_stop_insertion(proposal)
        except (TypeError, ValueError) as error:
            self._status.setText(t("editor.add_stop_error", error=error))
            return
        self.refresh()
        self._status.setText(t("editor.stop_added", trip_id=trip_id, stop_id=stop_id))

    def _reorder_shape_point(self) -> None:
        session = self._session_provider()
        key = self._current_key()
        if session is None or key is None or key[0] != "gtfs_shapes":
            return
        if not self._entity_is_editable(key):
            return
        before = session.working_copy.get(key)
        if before is None:
            return
        shape_id = before.get("shape_id")
        points = list(session.working_copy.entity_index.shapes_by_id.get(str(shape_id), ()))
        points.sort(key=lambda item: _sequence(item[1].get("shape_pt_sequence")))
        current = next(
            (index for index, (candidate, _payload) in enumerate(points) if candidate == key), None
        )
        if current is None:
            return
        position, accepted = QInputDialog.getInt(
            self,
            t("editor.reorder_shape_title"),
            t("editor.position_range", maximum=len(points)),
            current + 1,
            1,
            max(1, len(points)),
        )
        if not accepted or position == current + 1:
            return
        selected = points.pop(current)
        points.insert(position - 1, selected)
        changes = tuple(
            _entity_sequence_change(session, candidate, payload, (index + 1) * 10)
            for index, (candidate, payload) in enumerate(points)
        )
        primary = next(change for change in changes if change.entity_key == key)
        command = EditorCommand(
            EditorCommandKind.MOVE_SHAPE_POINT,
            key,
            primary.before,
            primary.after,
            changes=tuple(change for change in changes if change.entity_key != key),
            metadata={"shape_id": str(shape_id), "geometry_edit": "reorder_vertex"},
        )
        try:
            impact = session.preview_impact(command)
            resolved_command, impact = self._resolve_impact(session, command, impact)
            if resolved_command is None:
                return
            command = resolved_command
            session.apply(command, impact=impact)
        except (TypeError, ValueError) as error:
            self._status.setText(t("editor.reorder_shape_error", error=error))
            return
        self.refresh()

    def _validate(self) -> None:
        session = self._session_provider()
        if session is None:
            return
        issues = session.validate()
        session.validation_issues = issues
        if issues:
            self._status.setText(t("editor.validation_issues", count=len(issues)))
        else:
            self._status.setText(t("editor.validation_clean"))

    def _confirm_revision(self) -> None:
        session = self._session_provider()
        if session is None:
            return
        try:
            revision_id = session.confirm_revision()
        except (RevisionConfirmationError, ValueError) as error:
            QMessageBox.warning(self, t("editor.confirm_revision_error_title"), str(error))
            self.refresh()
            return
        self._status.setText(t("editor.revision_confirmed", revision_id=revision_id))
        self.refresh()

    def _show_impact(self, impact: Any, *, requires_resolution: bool) -> None:
        if requires_resolution:
            message = t(
                "editor.impact_requires_resolution",
                summary=_impact_summary(impact),
                required_count=len(impact.required_entity_changes),
                options=", ".join(impact.resolution_options) or t("editor.impact_no_options"),
            )
            QMessageBox.information(self, t("editor.impact_preview_title"), message)

    def _resolve_impact(
        self, session: EditorSession, command: EditorCommand, impact: Any
    ) -> tuple[EditorCommand | None, Any]:
        if not impact.requires_resolution and not impact.resolution_options:
            return command, impact
        self._show_impact(impact, requires_resolution=True)
        options = tuple(str(option) for option in impact.resolution_options)
        if not options:
            return None, impact
        option, accepted = QInputDialog.getItem(
            self,
            t("editor.resolve_impact_title"),
            t("editor.resolve_impact_prompt"),
            list(options),
            0,
            False,
        )
        if not accepted:
            return None, impact
        replacement: str | None = None
        if option.startswith("reassign_") or option.startswith("update_"):
            replacement, accepted = QInputDialog.getText(
                self,
                t("editor.resolve_impact_title"),
                t("editor.resolve_impact_id"),
                text="",
            )
            if not accepted or not replacement.strip():
                return None, impact
            replacement = replacement.strip()
        try:
            return session.prepare_command(
                command,
                impact,
                resolution=option,
                replacement_id=replacement,
            ), impact
        except (TypeError, ValueError) as error:
            self._status.setText(t("editor.resolution_prepare_error", error=error))
            return None, impact

    def _confirm_impact(self, impact: Any, *, title: str | None = None) -> bool:
        if not impact.requires_confirmation:
            return True
        confirmation = QMessageBox.question(
            self,
            title or t("editor.confirm_operation_title"),
            t("editor.apply_command_question", summary=_impact_summary(impact)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return confirmation == QMessageBox.StandardButton.Yes

    def _undo(self) -> None:
        session = self._session_provider()
        if session is None:
            return
        try:
            session.undo()
        except ValueError as error:
            self._status.setText(str(error))
        self.refresh()

    def _load_workspace_state(self) -> None:
        session = self._session_provider()
        key = self._current_key()
        if session is None or key is None or key[0] != "gtfs_routes":
            for checkbox in (
                self._visible,
                self._active,
                self._editable,
                self._locked,
                self._dimmed,
            ):
                checkbox.setEnabled(False)
            self._workspace_apply.setEnabled(False)
            return
        route_id = str(self._payloads[key].get("route_id") or key[1])
        state = session.working_copy.route_state(route_id)
        values = (state.visible, state.active, state.editable, state.locked, state.dimmed)
        for checkbox, value in zip(
            (
                self._visible,
                self._active,
                self._editable,
                self._locked,
                self._dimmed,
            ),
            values,
        ):
            checkbox.setEnabled(True)
            checkbox.setChecked(value)
        self._workspace_apply.setEnabled(True)

    def _save_workspace_state(self) -> None:
        session = self._session_provider()
        key = self._current_key()
        if session is None or key is None or key[0] != "gtfs_routes":
            return
        from gtfs_explorer.domain.changesets import RouteWorkspaceState

        route_id = str(self._payloads[key].get("route_id") or key[1])
        before_states = session.working_copy.route_states
        session.set_route_workspace_state(
            RouteWorkspaceState(
                route_id,
                self._visible.isChecked(),
                self._active.isChecked(),
                self._editable.isChecked(),
                self._locked.isChecked(),
                self._dimmed.isChecked(),
            )
        )
        after_states = session.working_copy.route_states
        self._apply_route_state_view(
            before_states,
            after_states,
            geometry_changed=(
                before_states != after_states
                and any(
                    before_states.get(route_id) != after_states.get(route_id)
                    and (
                        getattr(after_states.get(route_id), "visible", False)
                        != getattr(before_states.get(route_id), "visible", False)
                    )
                    for route_id in set(before_states) | set(after_states)
                )
            ),
            fit=False,
        )

    def _redo(self) -> None:
        session = self._session_provider()
        if session is None:
            return
        try:
            session.redo()
        except ValueError as error:
            self._status.setText(str(error))
        self.refresh()

    def _discard(self) -> None:
        session = self._session_provider()
        if session is None or not session.working_copy.dirty:
            return
        confirmation = QMessageBox.question(
            self,
            t("editor.discard_title"),
            t("editor.discard_message"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation == QMessageBox.StandardButton.Yes:
            session.discard()
            self.refresh()

    def _render_history(self, session: EditorSession) -> None:
        route_id = self._selected_route_id
        commands = {
            command.command_id: command for command in session.working_copy.changeset.commands
        }
        events = tuple(
            event
            for event in session.working_copy.changeset.history
            if route_id is None
            or (
                (command := commands.get(event.command_id)) is not None
                and any(
                    route_id in session.working_copy.route_ids_for_entity(key)
                    for key in command.entity_keys
                )
            )
        )
        self._history_context.setText(
            t(
                "editor.history_context",
                route_id=route_id or t("stop.not_available"),
                state=(
                    t("editor.draft_dirty")
                    if session.working_copy.dirty
                    else t("editor.draft_clean")
                ),
                count=len(events),
            )
        )
        self._history.setRowCount(len(events))
        for row, event in enumerate(events):
            command = commands.get(event.command_id)
            values = (
                event.action,
                event.command_id[:8],
                str(command.sequence if command is not None else "—"),
                str(len(command.entity_keys) if command is not None else 0),
            )
            for column, value in enumerate(values):
                self._history.setItem(row, column, QTableWidgetItem(value))

    def _current_key(self) -> tuple[str, str] | None:
        key = self._entity_selector.currentData()
        return key if isinstance(key, tuple) and len(key) == 2 else None

    def _current_field(self) -> str | None:
        value = self._field_selector.currentData()
        return str(value) if value is not None else None

    def _set_buttons_enabled(self, enabled: bool) -> None:
        self._apply_button.setEnabled(enabled)
        self._refresh_button.setEnabled(enabled)
        self._validate_button.setEnabled(enabled)
        self._confirm_button.setEnabled(enabled)
        self._table_selector.setEnabled(enabled)
        self._entity_selector.setEnabled(enabled)
        self._field_selector.setEnabled(enabled)
        self._update_delete_button()
        self._add_stop_button.setEnabled(enabled)
        self._reorder_shape_button.setEnabled(False)
        if not enabled:
            for button in (
                self._activate_route_button,
                self._finish_editing_button,
                self._edit_shape_button,
                self._redraw_segment_button,
                self._edit_stop_button,
                self._edit_schedule_button,
                self._edit_service_button,
                self._edit_operator_button,
                self._properties_button,
                self._reorder_stop_button,
            ):
                button.setEnabled(False)

    def _update_delete_button(self) -> None:
        session = self._session_provider()
        route_id = self._selected_route_id
        route_can_mutate = session is not None and (
            route_id is None or session.can_edit_route(route_id)
        )
        self._delete_button.setEnabled(
            self._table_selector.isEnabled()
            and str(self._table_selector.currentData()) in _DELETE_KINDS
            and self._current_key() is not None
            and route_can_mutate
        )
        self._add_stop_button.setEnabled(self._table_selector.isEnabled() and route_can_mutate)
        self._reorder_shape_button.setEnabled(
            self._table_selector.isEnabled()
            and str(self._table_selector.currentData()) == "gtfs_shapes"
            and self._current_key() is not None
            and route_can_mutate
        )

    def _entity_is_editable(self, key: tuple[str, str]) -> bool:
        session = self._session_provider()
        if session is None:
            return False
        route_ids = session.working_copy.route_ids_for_entity(key)
        if len(route_ids) > 1 and key[0] in {
            "gtfs_stops",
            "gtfs_shapes",
            "gtfs_trips",
            "gtfs_stop_times",
        }:
            self._status.setText(t("editor.entity_multiple_routes"))
            return False
        if route_ids and any(not session.can_edit_route(route_id) for route_id in route_ids):
            self._status.setText(t("editor.entity_route_not_authorized"))
            return False
        return True


def _display_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _sort_value(value: object) -> tuple[int, int | str]:
    if isinstance(value, int) and not isinstance(value, bool):
        return (0, value)
    return (1, "" if value is None else str(value))


def _safe_object_name(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value)


def _route_display_label(route: Mapping[str, Any] | None, route_id: str) -> str:
    if route is None:
        return route_id
    short_name = _display_value(route.get("route_short_name")) or route_id
    long_name = _display_value(route.get("route_long_name"))
    return short_name if not long_name else f"{short_name} · {long_name}"


def _new_draft_stop_id(index: WorkingCopyEntityIndex) -> str:
    existing = set(index.stops_by_id)
    while True:
        candidate = f"draft-stop-{uuid4().hex[:12]}"
        if candidate not in existing:
            return candidate


def _route_state_label(state: object) -> str:
    if not hasattr(state, "visible"):
        return "Sin estado"
    if getattr(state, "locked", False):
        return t("routes.locked")
    if getattr(state, "active", False) and getattr(state, "editable", False):
        return f"{t('routes.active')} · {t('routes.editable')}"
    if getattr(state, "active", False):
        return t("routes.active")
    if getattr(state, "dimmed", False):
        return t("routes.dimmed")
    if getattr(state, "visible", False):
        return t("editor.reference")
    return t("routes.hidden")


def _impact_summary(impact: Any) -> str:
    direct = [impact.entity_key, *(change.entity_key for change in getattr(impact, "changes", ()))]
    direct_labels = ", ".join(f"{table}/{entity}" for table, entity in direct[:4]) or t(
        "editor.impact_one_entity"
    )
    dependency_count = max(0, len(impact.affected_entities) - len(set(direct)))
    relationships = ", ".join(impact.relationships) or t("editor.impact_no_dependencies")
    return t(
        "editor.impact_summary",
        direct_count=len(set(direct)),
        direct_labels=direct_labels,
        dependency_count=dependency_count,
        tables=", ".join(impact.affected_tables) or t("editor.impact_none"),
        relationships=relationships,
    )


def _parse_value(raw: str, current: object) -> object:
    value = raw.strip()
    if value == "":
        return None
    if isinstance(current, bool):
        if value.casefold() in {"1", "true", "sí", "si"}:
            return True
        if value.casefold() in {"0", "false", "no"}:
            return False
        raise ValueError(t("editor.boolean_value_error"))
    if isinstance(current, int) and not isinstance(current, bool):
        return int(value)
    if isinstance(current, float):
        return float(value)
    if isinstance(current, date) and not isinstance(current, datetime):
        return date.fromisoformat(value)
    return value


def _sequence(value: object) -> tuple[int, int | str]:
    if isinstance(value, int) and not isinstance(value, bool):
        return (0, value)
    return (1, "" if value is None else str(value))


def _entity_sequence_change(
    session: EditorSession,
    key: tuple[str, str],
    _payload: dict[str, Any],
    sequence: int,
) -> EntityChange:
    before = session.working_copy.get(key)
    if before is None:
        raise ValueError(t("editor.vertex_missing"))
    after = dict(before)
    after["shape_pt_sequence"] = sequence
    return EntityChange(key, before, after)


_DELETE_KINDS = {
    "gtfs_stops": EditorCommandKind.DELETE_STOP,
    "gtfs_routes": EditorCommandKind.DELETE_ROUTE,
    "gtfs_shapes": EditorCommandKind.DELETE_SHAPE_POINT,
    "gtfs_calendar": EditorCommandKind.UPDATE_SERVICE,
    "gtfs_calendar_dates": EditorCommandKind.UPDATE_SERVICE,
    "gtfs_agency": EditorCommandKind.UPDATE_AGENCY,
    "gtfs_attributions": EditorCommandKind.UPDATE_ATTRIBUTION,
}
