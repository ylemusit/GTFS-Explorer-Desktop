"""Ventana independiente para la visualización cartográfica."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QCloseEvent, QGuiApplication, QShowEvent
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QPushButton, QSizePolicy, QWidget


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
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setObjectName("mapWindow")
        self.setWindowTitle("Mapa")
        self.setAccessibleName("Ventana independiente del mapa")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self._save_geometry = save_geometry
        self._on_return_to_data = on_return_to_data
        self._on_dock_map = on_dock_map
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
        return_to_data = QPushButton("Volver a datos", self)
        return_to_data.setObjectName("returnToData")
        return_to_data.setAccessibleName("Volver a datos")
        return_to_data.setToolTip("Muestra la ventana principal con los datos de Explorar.")
        return_to_data.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        return_to_data.clicked.connect(self._return_to_data)
        actions.addWidget(return_to_data)
        dock_map = QPushButton("Acoplar mapa", self)
        dock_map.setObjectName("dockMap")
        dock_map.setAccessibleName("Acoplar mapa")
        dock_map.setToolTip("Devuelve el mapa a la pantalla Explorar.")
        dock_map.clicked.connect(self.dock_map)
        actions.addWidget(dock_map)
        actions.addStretch()
        self._layout.addWidget(map_widget, 0, 0)
        self._layout.addLayout(
            actions, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        self.resize(960, 640)

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

    def shutdown(self) -> None:
        """Cierra el widget cartográfico y el top-level al salir de la app."""
        if self._save_geometry is not None:
            self._save_geometry(bytes(self.saveGeometry().data()), self.isMaximized())
        self._shutting_down = True
        self._map_widget.close()
        self._map_widget.deleteLater()
        self.close()

    def _return_to_data(self) -> None:
        if self._on_return_to_data is not None:
            self._on_return_to_data()

    def _is_visible_on_a_screen(self) -> bool:
        return any(
            screen.availableGeometry().intersects(self.frameGeometry())
            for screen in QGuiApplication.screens()
        )
