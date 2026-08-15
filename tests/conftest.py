"""Infraestructura compartida para las pruebas Qt."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def application() -> QApplication:
    """Mantiene una sola QApplication durante toda la suite."""
    return QApplication.instance() or QApplication([])
