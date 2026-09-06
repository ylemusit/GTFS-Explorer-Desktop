"""Cobertura del ciclo de vida de la ventana independiente del mapa."""

from __future__ import annotations

from PySide6.QtWidgets import QLineEdit, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from gtfs_explorer.presentation.desktop.map.window import MapWindow


def test_map_window_reuses_widget_close_reopen_and_persists_geometry(application) -> None:
    saved: list[tuple[bytes, bool]] = []
    returned: list[bool] = []
    docked: list[bool] = []
    main_window = QWidget()
    host = QWidget()
    QVBoxLayout(host)
    host.show()
    map_widget = QWidget()

    def dock_map() -> None:
        docked.append(True)
        map_widget.setParent(host)
        host.layout().addWidget(map_widget)  # type: ignore[union-attr]

    window = MapWindow(
        map_widget,
        save_geometry=lambda geometry, maximized: saved.append((geometry, maximized)),
        on_return_to_data=lambda: returned.append(main_window.isVisible()),
        on_dock_map=dock_map,
    )

    window.show()
    application.processEvents()
    assert map_widget.parentWidget() is window
    assert window.isVisible()

    first_window = window
    window.show()
    application.processEvents()
    assert window is first_window
    window.close()
    application.processEvents()
    assert not window.isVisible()
    assert map_widget.parentWidget() is not window
    assert map_widget.isVisible()
    assert docked == [True]
    assert returned == []

    window.show()
    application.processEvents()
    assert window.isVisible()
    window.attach_map()
    assert map_widget.parentWidget() is window
    return_to_data = window.findChild(QPushButton, "returnToData")
    assert return_to_data is not None
    main_window.show()
    return_to_data.click()
    application.processEvents()
    assert window.isVisible()
    assert main_window.isVisible()
    assert returned[-1] is True
    dock_button = window.findChild(QPushButton, "dockMap")
    assert dock_button is not None
    dock_button.click()
    application.processEvents()
    assert not window.isVisible()
    assert docked == [True, True]
    assert map_widget.parentWidget() is host
    window.close()
    assert saved and saved[-1][0]
    window.shutdown()
    application.processEvents()


def test_map_window_map_widget_expands_to_available_client_area(application) -> None:
    map_widget = QWidget()
    window = MapWindow(map_widget)
    window.resize(800, 600)
    window.show()
    application.processEvents()

    assert map_widget.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding
    assert map_widget.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Expanding
    assert map_widget.geometry().height() == window.contentsRect().height()
    assert map_widget.geometry().width() == window.contentsRect().width()

    normal_height = map_widget.height()
    window.resize(800, 700)
    application.processEvents()
    assert map_widget.height() > normal_height

    window.showMaximized()
    application.processEvents()
    maximized_height = map_widget.height()
    assert maximized_height >= normal_height

    window.showNormal()
    window.resize(800, 500)
    application.processEvents()
    assert map_widget.height() < maximized_height
    assert map_widget.geometry().bottom() == window.contentsRect().bottom()
    window.shutdown()
    application.processEvents()


def test_map_window_exposes_separate_confirm_and_cancel_callbacks(application) -> None:
    events: list[str] = []
    window = MapWindow(
        QWidget(),
        on_confirm=lambda: events.append("confirm"),
        on_cancel=lambda: events.append("cancel"),
    )

    window.findChild(QPushButton, "mapWindowConfirm").click()  # type: ignore[union-attr]
    window.findChild(QPushButton, "mapWindowCancel").click()  # type: ignore[union-attr]
    application.processEvents()

    assert events == ["confirm", "cancel"]
    window.shutdown()


def test_map_window_shortcuts_keep_text_undo_local(application) -> None:
    events: list[str] = []
    window = MapWindow(
        QWidget(),
        on_undo=lambda: events.append("undo"),
        on_redo=lambda: events.append("redo"),
    )
    line_edit = QLineEdit(window)
    window.show()
    line_edit.show()
    line_edit.setFocus()
    application.processEvents()

    assert window._undo_action.shortcut().toString() == "Ctrl+Z"
    assert window._redo_action.shortcut().toString() == "Ctrl+Y"
    assert window._redo_shift_action.shortcut().toString() == "Ctrl+Shift+Z"
    window._invoke_undo()
    window._invoke_redo()

    assert events == []
    window.shutdown()
