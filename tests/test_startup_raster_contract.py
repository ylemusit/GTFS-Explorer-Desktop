from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from gtfs_explorer.presentation.desktop.icon import application_icon_path
from gtfs_explorer.presentation.desktop.startup_intro import (
    CLOSE_RECT,
    COPYRIGHT_RECT,
    MINIMIZE_RECT,
    START_BUTTON_RECT,
    TITLEBAR_DRAG_RECT,
    TITLEBAR_ICON_RECT,
    TITLEBAR_RECT,
    TITLEBAR_TEXT_RECT,
    VERSION_RECT,
    WelcomeDialog,
)
from gtfs_explorer.product import IDENTITY


def test_welcome_uses_master_raster_and_normalized_dynamic_regions(application) -> None:
    dialog = WelcomeDialog()

    assert dialog.master_image.size().width() == 1077
    assert dialog.master_image.size().height() == 947
    assert application_icon_path().is_file()
    for region in (
        TITLEBAR_RECT,
        START_BUTTON_RECT,
        VERSION_RECT,
        COPYRIGHT_RECT,
        TITLEBAR_ICON_RECT,
        TITLEBAR_TEXT_RECT,
        MINIMIZE_RECT,
        CLOSE_RECT,
        TITLEBAR_DRAG_RECT,
    ):
        assert all(0.0 <= value <= 1.0 for value in region)

    assert dialog.title_label.text() == f"Bienvenido a {IDENTITY.name}"
    assert dialog.version_label.text() == "Versión 0.2.1"
    assert dialog.title_icon.accessibleName() == IDENTITY.name
    assert dialog.minimize_button.accessibleName() == "Minimize"
    assert dialog.close_button.accessibleName() == "Close"
    assert dialog.start_button.accessibleName()

    dialog.close()
    dialog.deleteLater()
    application.processEvents()


def test_welcome_close_and_escape_are_safe(application) -> None:
    dialog = WelcomeDialog()
    dialog.show()
    dialog.close_button.click()
    assert dialog.result() == 0

    dialog = WelcomeDialog()
    dialog.show()
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    assert dialog.result() == 0
    dialog.deleteLater()
    application.processEvents()
