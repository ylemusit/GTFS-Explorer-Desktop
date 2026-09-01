"""Identidad visual de la aplicación para Qt y las distribuciones Windows."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QGuiApplication, QIcon

from gtfs_explorer.infrastructure.filesystem.paths import application_resource_path

ICON_RELATIVE_PATH = Path("gtfs_explorer") / "resources" / "gtfs_explorer.ico"


def application_icon_path() -> Path:
    """Resuelve el ICO desde el standalone o desde el paquete fuente."""
    packaged = application_resource_path(ICON_RELATIVE_PATH.as_posix())
    if packaged.is_file():
        return packaged
    source = Path(__file__).resolve().parents[2] / "resources" / "gtfs_explorer.ico"
    if source.is_file():
        return source
    raise FileNotFoundError(f"No se encontró el icono de producto: {ICON_RELATIVE_PATH}")


def configure_application_icon(application: QGuiApplication) -> QIcon:
    """Configura y devuelve el icono común de QApplication y sus ventanas."""
    icon = QIcon(str(application_icon_path()))
    if icon.isNull():
        raise RuntimeError("El icono de producto no pudo cargarse en Qt.")
    application.setWindowIcon(icon)
    return icon
