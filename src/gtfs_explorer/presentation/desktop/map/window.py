"""Ventana independiente para la visualización cartográfica."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QAction, QCloseEvent, QGuiApplication, QKeySequence, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QWidget,
)

from gtfs_explorer.presentation.desktop.i18n import t


class MapWindow(QWidget):
    """Contenedor top-level de un único ``MapWidget`` reutilizable."""

    def __init__(
        self,
        map_widget: QWidget,
        *,
        geometry: bytes | None = None,
        maximized: bool = False,
        save_geometry: Callable[[bytes, bool], bool] | None = None,
        on_return_to_data: Callable[[], None] | None = None,
        on_dock_map: Callable[[], None] | None = None,
        on_mode_changed: Callable[[str], None] | None = None,
        on_vertex_action: Callable[[str], None] | None = None,
        on_confirm: Callable[[], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
        on_undo: Callable[[], None] | None = None,
        on_redo: Callable[[], None] | None = None,
        on_fit: Callable[[], None] | None = None,
        on_finish: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setObjectName("mapWindow")
        self.setWindowTitle(t("map.title"))
        self.setAccessibleName(t("map.window_accessible"))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self._save_geometry = save_geometry
        self._on_return_to_data = on_return_to_data
        self._on_dock_map = on_dock_map
        self._on_mode_changed = on_mode_changed
        self._on_vertex_action = on_vertex_action
        self._on_confirm = on_confirm
        self._on_cancel = on_cancel
        self._on_undo = on_undo
        self._on_redo = on_redo
        self._on_fit = on_fit
        self._on_finish = on_finish
        self._context_values: tuple[str, str, int, int] | None = None
        self._selected_context: tuple[str, str] | None = None
        self._context_mode: str | None = None
        self._shutting_down = False
        self._restored = False
        self._initial_geometry = geometry
        self._initial_maximized = maximized
        self._map_widget = map_widget
        map_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        actions = QHBoxLayout()
        actions.setContentsMargins(8, 8, 8, 4)
        self._editor_context = QLabel(self)
        self._editor_context.setObjectName("mapWindowEditorContext")
        self._editor_context.setAccessibleName(t("map.context_accessible"))
        self._editor_context.setWordWrap(True)
        self._editor_context.hide()
        actions.addWidget(self._editor_context, 1)
        self._mode_selector = QComboBox(self)
        self._mode_selector.setObjectName("mapWindowMode")
        self._mode_selector.setAccessibleName(t("map.mode_accessible"))
        for mode, label_key in (
            ("NORMAL", "map.mode_normal_label"),
            ("EDIT_ROUTE", "map.mode_edit_route_label"),
            ("SELECT_SEGMENT", "map.mode_select_segment_label"),
            ("REDRAW_SEGMENT", "map.mode_redraw_segment_label"),
        ):
            self._mode_selector.addItem(t(label_key), mode)
        self._mode_selector.currentIndexChanged.connect(self._mode_changed)
        self._mode_label = QLabel(t("map.mode_label"), self)
        actions.addWidget(self._mode_label)
        actions.addWidget(self._mode_selector)
        self._toolbar_buttons: dict[str, QPushButton] = {}
        self._add_toolbar_button(actions, "editRoute", t("map.edit_shape"), self._select_edit_route)
        self._add_toolbar_button(
            actions, "selectSegment", t("map.select_segment"), self._select_segment
        )
        self._add_toolbar_button(
            actions, "addVertex", t("map.add_vertex"), lambda: self._vertex("add")
        )
        self._add_toolbar_button(
            actions, "moveVertex", t("map.move_vertex"), self._select_edit_route
        )
        self._add_toolbar_button(
            actions, "deleteVertex", t("map.delete_vertex"), lambda: self._vertex("delete")
        )
        self._add_toolbar_button(actions, "confirm", t("map.confirm"), self._invoke_confirm)
        self._add_toolbar_button(actions, "cancel", t("map.cancel"), self._invoke_cancel)
        self._add_toolbar_button(actions, "undo", t("map.undo"), self._invoke_undo)
        self._add_toolbar_button(actions, "redo", t("map.redo"), self._invoke_redo)
        self._add_toolbar_button(actions, "fit", t("map.fit"), self._invoke_fit)
        self._add_toolbar_button(actions, "finish", t("map.finish"), self._invoke_finish)
        self._toolbar_buttons["finish"].setVisible(on_finish is not None)
        return_to_data = QPushButton(t("map.return_to_data"), self)
        self._return_to_data_button = return_to_data
        return_to_data.setObjectName("returnToData")
        return_to_data.setAccessibleName(t("map.return_to_data_accessible"))
        return_to_data.setToolTip(t("map.return_to_data_tooltip"))
        return_to_data.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        return_to_data.clicked.connect(self._return_to_data)
        actions.addWidget(return_to_data)
        dock_map = QPushButton(t("map.dock"), self)
        self._dock_map_button = dock_map
        dock_map.setObjectName("dockMap")
        dock_map.setAccessibleName(t("map.dock_accessible"))
        dock_map.setToolTip(t("map.dock_tooltip"))
        dock_map.clicked.connect(self.dock_map)
        actions.addWidget(dock_map)
        actions.addStretch()
        self._layout.addLayout(
            actions, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        # La barra queda superpuesta en la parte superior; el mapa conserva
        # toda el área cliente y no pierde altura útil al desacoplarse.
        self._layout.addWidget(map_widget, 0, 0)
        self.resize(960, 640)
        self._undo_action = QAction(t("map.undo"), self)
        self._undo_action.setShortcut(QKeySequence("Ctrl+Z"))
        self._undo_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self._undo_action.triggered.connect(self._invoke_undo)
        self.addAction(self._undo_action)
        self._redo_action = QAction(t("map.redo"), self)
        self._redo_action.setShortcut(QKeySequence("Ctrl+Y"))
        self._redo_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self._redo_action.triggered.connect(self._invoke_redo)
        self.addAction(self._redo_action)
        self._redo_shift_action = QAction(t("map.redo"), self)
        self._redo_shift_action.setShortcut(QKeySequence("Ctrl+Shift+Z"))
        self._redo_shift_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self._redo_shift_action.triggered.connect(self._invoke_redo)
        self.addAction(self._redo_shift_action)
        self.set_history_state(False, False)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - API Qt
        super().showEvent(event)
        if self._restored:
            return
        self._restored = True
        restored = bool(self._initial_geometry) and self.restoreGeometry(
            QByteArray(self._initial_geometry or b"")
        )
        if not restored or not self._is_visible_on_a_screen():
            self.resize(960, 640)
            screen = self.screen() or QGuiApplication.primaryScreen()
            if screen is not None:
                self.move(screen.availableGeometry().center() - self.rect().center())
        if self._initial_maximized:
            self.showMaximized()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - API Qt
        if self._save_geometry is not None:
            self._save_geometry(bytes(self.saveGeometry().data()), self.isMaximized())
        if self._shutting_down:
            event.accept()
            return
        self._layout.removeWidget(self._map_widget)
        if self._on_dock_map is not None:
            self._on_dock_map()
        event.accept()

    def dock_map(self) -> None:
        """Solicita el mismo cierre que usa la X para acoplar el mapa."""
        self.close()

    def attach_map(self) -> None:
        """Vuelve a alojar el mapa en esta ventana para un nuevo desacople."""
        if self._map_widget.parentWidget() is not self:
            self._layout.addWidget(self._map_widget, 0, 0)
        self._map_widget.show()
        self._layout.activate()
        refresh_host = getattr(self._map_widget, "refresh_host", None)
        if callable(refresh_host):
            refresh_host()

    def shutdown(self) -> None:
        """Cierra el widget cartográfico y el top-level al salir de la app."""
        if self._save_geometry is not None:
            self._save_geometry(bytes(self.saveGeometry().data()), self.isMaximized())
        self._shutting_down = True
        self._map_widget.close()
        self._map_widget.deleteLater()
        self.close()
        self.deleteLater()

    def set_editor_context(
        self,
        route_id: str,
        mode: str,
        route_label: str | None = None,
        ordinal: int | None = None,
        total: int | None = None,
        *,
        selected_route_id: str | None = None,
        selected_route_label: str | None = None,
    ) -> None:
        """Expone el contexto de la sesión sin crear un segundo mapa o sesión."""
        self.setWindowTitle(t("editor.open_cartographic_editor"))
        safe_ordinal = ordinal or 1
        safe_total = total or 1
        self._context_values = (route_id, route_label or route_id, safe_ordinal, safe_total)
        self._selected_context = (
            (selected_route_id, selected_route_label or selected_route_id)
            if selected_route_id is not None
            else None
        )
        self._context_mode = mode
        self._update_context_text()
        self._editor_context.show()
        index = self._mode_selector.findData(mode)
        if index >= 0:
            self._mode_selector.blockSignals(True)
            self._mode_selector.setCurrentIndex(index)
            self._mode_selector.blockSignals(False)

    def set_editor_callbacks(
        self,
        *,
        on_mode_changed: Callable[[str], None] | None = None,
        on_vertex_action: Callable[[str], None] | None = None,
        on_confirm: Callable[[], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
        on_undo: Callable[[], None] | None = None,
        on_redo: Callable[[], None] | None = None,
        on_fit: Callable[[], None] | None = None,
        on_finish: Callable[[], None] | None = None,
    ) -> None:
        self._on_mode_changed = on_mode_changed
        self._on_vertex_action = on_vertex_action
        self._on_confirm = on_confirm
        self._on_cancel = on_cancel
        self._on_undo = on_undo
        self._on_redo = on_redo
        self._on_fit = on_fit
        self._on_finish = on_finish
        finish_button = self._toolbar_buttons.get("finish")
        if finish_button is not None:
            finish_button.setVisible(on_finish is not None)
        self._undo_action.setText(t("map.undo"))
        self._redo_action.setText(t("map.redo"))
        self._redo_shift_action.setText(t("map.redo"))
        self._update_context_text()

    def _update_context_text(self) -> None:
        if self._context_values is None or self._context_mode is None:
            return
        route_id, label, ordinal, total = self._context_values
        selected_id, selected_label = self._selected_context or (route_id, label)
        self._editor_context.setText(
            t(
                "map.route_context",
                selected_label=selected_label,
                selected_route_id=selected_id,
                active_label=label,
                active_route_id=route_id,
                ordinal=ordinal,
                total=total,
                mode=self._context_mode,
            )
        )

    def set_history_state(self, undo_available: bool, redo_available: bool) -> None:
        """Sincroniza botones y shortcuts con el historial compartido."""
        self._undo_action.setEnabled(undo_available)
        self._redo_action.setEnabled(redo_available)
        self._redo_shift_action.setEnabled(redo_available)
        for key, enabled in (("undo", undo_available), ("redo", redo_available)):
            button = self._toolbar_buttons.get(key)
            if button is not None:
                button.setEnabled(enabled)

    def _add_toolbar_button(
        self, layout: QHBoxLayout, key: str, label: str, callback: Callable[[], None]
    ) -> None:
        button = QPushButton(label, self)
        button.setObjectName(f"mapWindow{key[0].upper()}{key[1:]}")
        button.setAccessibleName(label)
        button.clicked.connect(callback)
        layout.addWidget(button)
        self._toolbar_buttons[key] = button

    def _mode_changed(self, _index: int) -> None:
        if self._on_mode_changed is not None:
            self._on_mode_changed(str(self._mode_selector.currentData()))

    def _select_edit_route(self) -> None:
        self._mode_selector.setCurrentIndex(self._mode_selector.findData("EDIT_ROUTE"))

    def _select_segment(self) -> None:
        self._mode_selector.setCurrentIndex(self._mode_selector.findData("SELECT_SEGMENT"))

    def _vertex(self, action: str) -> None:
        self._mode_selector.setCurrentIndex(self._mode_selector.findData("REDRAW_SEGMENT"))
        if self._on_vertex_action is not None:
            self._on_vertex_action(action)

    def _invoke_confirm(self) -> None:
        if self._on_confirm is not None:
            self._on_confirm()

    def _invoke_cancel(self) -> None:
        if self._on_cancel is not None:
            self._on_cancel()

    def _invoke_undo(self) -> None:
        if self._focused_text_editor():
            return
        if self._on_undo is not None:
            self._on_undo()

    def _invoke_redo(self) -> None:
        if self._focused_text_editor():
            return
        if self._on_redo is not None:
            self._on_redo()

    @staticmethod
    def _focused_text_editor() -> bool:
        focused = QApplication.focusWidget()
        return isinstance(focused, (QLineEdit, QTextEdit, QPlainTextEdit))

    def _invoke_fit(self) -> None:
        if self._on_fit is not None:
            self._on_fit()

    def _invoke_finish(self) -> None:
        if self._on_finish is not None:
            self._on_finish()

    def retranslate_ui(self) -> None:
        """Actualiza controles visibles conservando ventana, mapa y contexto."""
        self.setWindowTitle(t("editor.open_cartographic_editor"))
        self._mode_label.setText(t("map.mode_label"))
        for index, key in enumerate(
            (
                "map.mode_normal_label",
                "map.mode_edit_route_label",
                "map.mode_select_segment_label",
                "map.mode_redraw_segment_label",
            )
        ):
            if index < self._mode_selector.count():
                self._mode_selector.setItemText(index, t(key))
        self._return_to_data_button.setText(t("map.return_to_data"))
        self._dock_map_button.setText(t("map.dock"))
        for key, message in (
            ("editRoute", t("map.edit_shape")),
            ("selectSegment", t("map.select_segment")),
            ("addVertex", t("map.add_vertex")),
            ("moveVertex", t("map.move_vertex")),
            ("deleteVertex", t("map.delete_vertex")),
            ("confirm", t("map.confirm")),
            ("cancel", t("map.cancel")),
            ("undo", t("map.undo")),
            ("redo", t("map.redo")),
            ("fit", t("map.fit")),
            ("finish", t("map.finish")),
        ):
            button = self._toolbar_buttons.get(key)
            if button is not None:
                button.setText(message)
                button.setAccessibleName(message)
        self._undo_action.setText(t("map.undo"))
        self._redo_action.setText(t("map.redo"))
        self._redo_shift_action.setText(t("map.redo"))
        self._update_context_text()

    def _return_to_data(self) -> None:
        if self._on_return_to_data is not None:
            self._on_return_to_data()

    def _is_visible_on_a_screen(self) -> bool:
        return any(
            screen.availableGeometry().intersects(self.frameGeometry())
            for screen in QGuiApplication.screens()
        )
