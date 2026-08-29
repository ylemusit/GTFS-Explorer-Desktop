"""Regresiones contractuales de accesibilidad y teclado para P1-29."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from gtfs_explorer.application.map_policy import MapMode
from gtfs_explorer.application.ui_state import UiAction
from gtfs_explorer.domain.ports import PagedResult, PageRequest
from gtfs_explorer.presentation.desktop.about import AboutDialog
from gtfs_explorer.presentation.desktop.exporter.widget import ExportAssistantWidget
from gtfs_explorer.presentation.desktop.main_window import MainWindow
from gtfs_explorer.presentation.desktop.routes.widget import RouteExplorerWidget
from gtfs_explorer.presentation.desktop.startup_intro import StartupIntroDialog
from gtfs_explorer.presentation.desktop.validation.widget import ValidationWidget


@pytest.fixture(autouse=True)
def _replace_web_map(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeMap(QLabel):
        def __init__(self, _layers: object, _stop_selected: object) -> None:
            super().__init__()
            self.mode = MapMode.AUTO
            self.status_text = "Mapa: no disponible · sin paquete local."

        def clear(self) -> None:
            pass

        def set_mode(self, mode: MapMode) -> str:
            self.mode = mode
            self.status_text = f"Mapa: {mode.value}."
            return self.status_text

    monkeypatch.setattr("gtfs_explorer.presentation.desktop.routes.widget.MapWidget", FakeMap)


def test_main_controls_have_safe_state_and_accessible_metadata(application: QApplication) -> None:
    window = MainWindow()

    assert not window._actions[UiAction.IMPORT_FEED].isEnabled()
    assert window._navigation.accessibleName() == "Navegación"
    assert window._map_mode_combo.accessibleName() == "Modo de mapa:"
    assert window._offline_maps.accessibleName() == "Mapas offline"
    assert window._offline_maps.focusPolicy() != Qt.FocusPolicy.NoFocus

    window.close()
    window.deleteLater()
    application.processEvents()


def test_forms_associate_labels_and_compact_actions(application: QApplication) -> None:
    routes = RouteExplorerWidget(
        lambda: PagedResult((), 0, PageRequest()),
        lambda _route: PagedResult((), 0, PageRequest()),
        lambda _route, _service: PagedResult((), 0, PageRequest()),
        lambda _route, _service, _direction: PagedResult((), 0, PageRequest()),
        lambda _trip: PagedResult((), 0, PageRequest()),
        lambda _stop: None,
        lambda _route, _service, _direction: None,
    )
    route_label = next(label for label in routes.findChildren(QLabel) if label.text() == "Ruta:")
    assert route_label.buddy() is routes._routes

    exporter = ExportAssistantWidget()
    format_label = next(
        label for label in exporter.findChildren(QLabel) if label.text() == "Formato:"
    )
    assert format_label.buddy() is exporter._format
    assert exporter._export.accessibleName() == "Iniciar exportación"
    assert exporter._cancel.accessibleName() == "Cancelar exportación"

    routes.deleteLater()
    exporter.deleteLater()
    application.processEvents()


def test_validation_keyboard_contract_and_disabled_pagination(application: QApplication) -> None:
    widget = ValidationWidget(
        lambda _filter, page: PagedResult((), 0, page),
    )

    widget._search.setFocus()
    QTest.keyClick(widget._search, Qt.Key.Key_Return)
    assert widget._table.accessibleName() == "Incidencias de validación"
    assert widget._previous.accessibleName() == "Página anterior"
    assert not widget._previous.isEnabled()
    assert not widget._next.isEnabled()

    widget.deleteLater()
    application.processEvents()


def test_dialog_enter_and_escape_remain_native(application: QApplication) -> None:
    intro = StartupIntroDialog()
    intro.show()
    QTest.keyClick(intro, Qt.Key.Key_Return)
    assert intro.result() != 0
    intro.close()
    intro.deleteLater()
    application.processEvents()

    about = AboutDialog()
    about.show()
    about.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    )
    assert not about.isVisible()

    about.deleteLater()
    application.processEvents()
