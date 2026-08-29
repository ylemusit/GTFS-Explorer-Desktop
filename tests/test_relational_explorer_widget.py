"""Flujos Qt del explorador relacional principal."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from gtfs_explorer.application.queries.timetable import (
    TimetableCell,
    TimetableColumn,
    TimetableExportScope,
    TimetableMatrix,
    TimetablePattern,
    TimetableRow,
)
from gtfs_explorer.domain.ports import PagedResult, PageRequest
from gtfs_explorer.domain.routes import (
    DirectionSummary,
    RouteSummary,
    ServiceSummary,
    TimelineStop,
    TripSummary,
)
from gtfs_explorer.domain.stops import StopInspection, StopSummary
from gtfs_explorer.presentation.desktop.routes.widget import RouteExplorerWidget
from gtfs_explorer.presentation.desktop.timetable.widget import TimetableWidget


def _page(items: tuple[object, ...]) -> PagedResult[object]:
    return PagedResult(items, len(items), PageRequest())


def _matrix(_route: str, _service: str, direction: int | None) -> TimetableMatrix:
    return TimetableMatrix(
        "R1",
        "weekday",
        direction,
        (
            TimetablePattern(
                (TimetableRow(1, "S1", "Central", 1),),
                (TimetableColumn("T1", (TimetableCell("25:05:00", "25:06:00"),)),),
            ),
        ),
        1,
        False,
        TimetableExportScope("R1", "weekday", direction),
    )


def test_relational_selection_resets_and_exposes_ids_and_extended_hours(
    application: QApplication,
) -> None:
    route = RouteSummary("R1", None, "10", None, 715)
    empty_route = RouteSummary("R2", None, None, "Vacía", 3)
    service = ServiceSummary("weekday", 1)
    direction = DirectionSummary(0, 1)
    trip = TripSummary("T1", "R1", "weekday", 0, "Centro", None, None)
    timeline = TimelineStop(1, "S1", "Central", "25:05:00", 90300, "25:06:00", 90360)
    event_inspection = StopInspection(
        StopSummary("S1", "Central", None),
        None,
        _page(()),  # type: ignore[arg-type]
        _page(()),  # type: ignore[arg-type]
        _page(()),  # type: ignore[arg-type]
    )

    def services(route_id: str) -> PagedResult[ServiceSummary]:
        return _page((service,)) if route_id == "R1" else _page(())  # type: ignore[return-value]

    widget = RouteExplorerWidget(
        lambda: _page((route, empty_route)),  # type: ignore[arg-type]
        services,
        lambda *_: _page((direction,)),  # type: ignore[arg-type]
        lambda *_: _page((trip,)),  # type: ignore[arg-type]
        lambda _: _page((timeline,)),  # type: ignore[arg-type]
        lambda _: event_inspection,
        _matrix,
    )

    widget.refresh()

    assert (
        widget._routes.currentText()
        == "10 (R1) · route_type 715 — Demand and Response Bus Service "
        "(Google Transit extended)"
    )
    assert widget._directions.currentText() == "direction_id: 0 (1 viajes)"
    assert widget._trips.currentText() == "Centro (T1)"
    assert widget._timeline._table.item(0, 1).text() == "Central"
    assert widget._timeline._table.item(0, 2).text() == "S1"
    assert widget._timeline._table.item(0, 3).text() == "25:05:00"

    widget._show_stop("S1")
    assert widget._stops._headline.text() == "Parada: Central (S1) — horarios GTFS del feed"

    button = widget.findChild(QPushButton, "")
    assert button is not None
    button.click()
    assert widget._timetable._table.item(0, 0).text() == "Central (S1)"
    assert (
        widget._timetable._table.item(0, 1).text()
        == "arrival_time: 25:05:00 · departure_time: 25:06:00"
    )

    widget._routes.setCurrentIndex(1)
    assert widget._services.count() == 0
    assert widget._directions.count() == 0
    assert widget._trips.count() == 0
    assert widget._timeline._table.rowCount() == 0
    assert not widget._timetable.isVisible()
    widget.deleteLater()
    application.processEvents()


def test_relational_selector_keeps_basic_keyboard_navigation(
    application: QApplication,
) -> None:
    routes = (
        RouteSummary("R1", None, "Centro", None, 3),
        RouteSummary("R2", None, "Norte", None, 3),
    )
    widget = RouteExplorerWidget(
        lambda: _page(routes),  # type: ignore[arg-type]
        lambda _: _page(()),  # type: ignore[arg-type]
        lambda *_: _page(()),  # type: ignore[arg-type]
        lambda *_: _page(()),  # type: ignore[arg-type]
        lambda _: _page(()),  # type: ignore[arg-type]
        lambda _: StopInspection(
            StopSummary("S1", "Central", None), None, _page(()), _page(()), _page(())
        ),
        _matrix,
    )

    widget.refresh()
    selector = widget._routes
    selector.showPopup()
    QTest.keyClick(selector, Qt.Key.Key_Down)
    QTest.keyClick(selector, Qt.Key.Key_Enter)
    assert selector.currentData() == routes[1]
    widget.deleteLater()
    application.processEvents()


def test_timetable_labels_missing_fields_without_inferring_a_time(
    application: QApplication,
) -> None:
    matrix = TimetableMatrix(
        "R1",
        "weekday",
        0,
        (
            TimetablePattern(
                (
                    TimetableRow(1, "S1", "Central", 1),
                    TimetableRow(2, "S2", "Sur", 1),
                ),
                (
                    TimetableColumn(
                        "T1", (TimetableCell(None, "24:01:00"), TimetableCell(None, None))
                    ),
                ),
            ),
        ),
        1,
        False,
        TimetableExportScope("R1", "weekday", 0),
    )
    widget = TimetableWidget(lambda: matrix)

    widget.refresh()

    assert widget._table.horizontalHeaderItem(0).text() == "Parada"
    assert widget._table.item(0, 1).text() == "departure_time: 24:01:00"
    assert widget._table.item(1, 1).text() == "—"
    widget.deleteLater()
    application.processEvents()


def test_relational_selection_clears_map_before_loading_the_next_trip(
    application: QApplication, monkeypatch
) -> None:
    map_events: list[tuple[str, str | None]] = []

    class FakeMap(QWidget):
        def __init__(self, _layers, _stop_selected) -> None:
            super().__init__()
            map_events.append(("created", None))

        def clear(self) -> None:
            map_events.append(("clear", None))

        def show_trip(self, trip_id: str) -> None:
            map_events.append(("show", trip_id))

        def select_stop(self, stop_id: str) -> None:
            map_events.append(("select", stop_id))

    monkeypatch.setattr("gtfs_explorer.presentation.desktop.routes.widget.MapWidget", FakeMap)
    route = RouteSummary("R1", None, "10", None, 1)
    service = ServiceSummary("weekday", 1)
    direction = DirectionSummary(0, 1)
    trip = TripSummary("T1", "R1", "weekday", 0, "Centro", None, None)
    inspection = StopInspection(
        StopSummary("S1", "Central", None), None, _page(()), _page(()), _page(())
    )
    widget = RouteExplorerWidget(
        lambda: _page((route,)),  # type: ignore[arg-type]
        lambda _: _page((service,)),  # type: ignore[arg-type]
        lambda *_: _page((direction,)),  # type: ignore[arg-type]
        lambda *_: _page((trip,)),  # type: ignore[arg-type]
        lambda _: _page(()),  # type: ignore[arg-type]
        lambda _: inspection,
        _matrix,
        lambda _: None,  # type: ignore[arg-type]
    )

    widget.refresh()

    assert ("show", "T1") in map_events
    assert map_events.index(("clear", None)) < map_events.index(("show", "T1"))
    widget.clear()
    assert map_events[-1] == ("clear", None)
    widget.deleteLater()
    application.processEvents()


def test_relational_selectors_search_by_id_label_case_insensitive_and_preserve_data(
    application: QApplication,
) -> None:
    routes = (
        RouteSummary("R-CENTRAL", None, "10", "Centro", 3),
        RouteSummary("R-NORTH", None, "20", "Norte", 3),
    )
    widget = RouteExplorerWidget(
        lambda: _page(routes),  # type: ignore[arg-type]
        lambda _: _page(()),  # type: ignore[arg-type]
        lambda *_: _page(()),  # type: ignore[arg-type]
        lambda *_: _page(()),  # type: ignore[arg-type]
        lambda _: _page(()),  # type: ignore[arg-type]
        lambda _: StopInspection(
            StopSummary("S1", "Central", None), None, _page(()), _page(()), _page(())
        ),
        _matrix,
    )

    widget.refresh()
    selector = widget._routes
    assert selector.isEditable()
    assert selector.insertPolicy() == selector.InsertPolicy.NoInsert

    selector.lineEdit().setText("north")
    application.processEvents()
    assert selector.currentData() is None
    assert [
        selector.completer().completionModel().index(row, 0).data()
        for row in range(selector.completer().completionModel().rowCount())
    ] == ["20 (R-NORTH) · route_type 3 — Bus (GTFS core)"]

    selector.lineEdit().setText("r-central")
    application.processEvents()
    assert selector.completer().completionModel().rowCount() == 1
    selector.completer().setCurrentRow(0)
    selector.completer().activated.emit("10 (R-CENTRAL) · route_type 3 — Bus (GTFS core)")
    assert selector.currentData() == routes[0]
    assert selector.currentData().route_id == "R-CENTRAL"

    widget.clear()
    assert selector.currentText() == ""
    assert selector.completer().completionModel().rowCount() == 0
    widget.deleteLater()
    application.processEvents()


def test_relational_search_handles_empty_single_and_large_datasets(
    application: QApplication,
) -> None:
    routes = tuple(RouteSummary(f"R-{index}", None, str(index), None, 3) for index in range(10_000))
    widget = RouteExplorerWidget(
        lambda: _page(routes),  # type: ignore[arg-type]
        lambda _: _page(()),  # type: ignore[arg-type]
        lambda *_: _page(()),  # type: ignore[arg-type]
        lambda *_: _page(()),  # type: ignore[arg-type]
        lambda _: _page(()),  # type: ignore[arg-type]
        lambda _: StopInspection(
            StopSummary("S1", "Central", None), None, _page(()), _page(()), _page(())
        ),
        _matrix,
    )

    widget.refresh()
    selector = widget._routes
    selector.lineEdit().setText("9999")
    application.processEvents()
    assert selector.completer().completionModel().rowCount() == 1
    assert (
        selector.completer().completionModel().index(0, 0).data()
        == "9999 (R-9999) · route_type 3 — Bus (GTFS core)"
    )

    widget.clear()
    assert selector.count() == 0
    assert selector.currentText() == ""
    widget.deleteLater()
    application.processEvents()

    # A selector with one item remains keyboard/search compatible.
    widget = RouteExplorerWidget(
        lambda: _page((routes[0],)),  # type: ignore[arg-type]
        lambda _: _page(()),  # type: ignore[arg-type]
        lambda *_: _page(()),  # type: ignore[arg-type]
        lambda *_: _page(()),  # type: ignore[arg-type]
        lambda _: _page(()),  # type: ignore[arg-type]
        lambda _: StopInspection(
            StopSummary("S1", "Central", None), None, _page(()), _page(()), _page(())
        ),
        _matrix,
    )
    widget.refresh()
    widget._routes.lineEdit().clear()
    QTest.keyClicks(widget._routes.lineEdit(), "r-0")
    application.processEvents()
    assert widget._routes.completer().completionModel().rowCount() == 1
    widget.deleteLater()
    application.processEvents()
