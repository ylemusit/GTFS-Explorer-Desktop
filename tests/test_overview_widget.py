"""Presentación separada de importación y validación en la página Proyecto."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gtfs_explorer.domain.overview import FeedOverview, OverviewMetric, ValidationOverview
from gtfs_explorer.domain.project import FeedMetadata, FeedStatus
from gtfs_explorer.presentation.desktop.overview.widget import FeedOverviewWidget


def _overview(status: FeedStatus, validation: tuple[str, ...], issues: int = 0) -> FeedOverview:
    feed = FeedMetadata("feed", "project", "feed.zip", "a" * 64, "ARCHIVE", "2026-04-27", status)
    return FeedOverview(
        feed,
        None,
        (OverviewMetric("Paradas", 4, "paradas", "datos normalizados"),),
        (),
        ValidationOverview(len(validation), issues, validation),
    )


def test_overview_states_are_explicit_and_not_collapsed(application: QApplication) -> None:
    widget = FeedOverviewWidget(lambda: None)

    widget.show_overview(_overview(FeedStatus.IMPORTED, ("VALID",)))
    assert widget._feed_import_status.text() == "Completada"
    assert widget._feed_validation_status.text() == "VALID"
    assert widget._feed_issue_count.text() == "0"

    widget.show_overview(_overview(FeedStatus.IMPORTED, ("INVALID",), 3))
    assert widget._feed_import_status.text() == "Completada"
    assert widget._feed_validation_status.text() == "INVALID"
    assert widget._feed_issue_count.text() == "3"

    widget.show_overview(_overview(FeedStatus.CANCELLED, (), 0))
    assert widget._feed_import_status.text() == "Cancelada"
    assert widget._feed_validation_status.text() == "Sin ejecutar"
    assert widget._feed_issue_count.text() == "No disponible"
    assert "no disponibles" in widget._metrics_note.text().lower()

    widget.show_overview(_overview(FeedStatus.FAILED, ("INVALID",), 3))
    assert widget._feed_import_status.text() == "Fallida"
    assert widget._feed_validation_status.text() == "No disponible"
    assert widget._feed_validation_status.text() != "INVALID"

    widget.clear()
    assert widget._feed_import_status.text() == "Sin feed importado"
    assert widget._feed_validation_status.text() == "Sin ejecutar"
    widget.deleteLater()
    application.processEvents()
