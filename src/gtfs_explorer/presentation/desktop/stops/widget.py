"""Inspector de una parada y sus eventos programados."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gtfs_explorer.application.queries.map_layers import route_color
from gtfs_explorer.domain.stops import ScheduledStopEvent, StopCard, StopInspection
from gtfs_explorer.presentation.desktop.i18n import t


class StopInspectorWidget(QWidget):
    """Muestra contexto de parada; los eventos no se presentan como tiempo real."""

    def __init__(
        self,
        inspect_stop: Callable[[str], StopInspection],
        parent: QWidget | None = None,
        *,
        on_center: Callable[[str], None] | None = None,
        on_edit: Callable[[str], None] | None = None,
        on_details: Callable[[str], None] | None = None,
        can_edit: Callable[[str], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self._inspect_stop = inspect_stop
        self._on_center = on_center
        self._on_edit = on_edit
        self._on_details = on_details
        self._can_edit = can_edit
        self._current_stop_id: str | None = None
        self._current_inspection: StopInspection | None = None
        self._current_events: tuple[ScheduledStopEvent, ...] = ()
        layout = QVBoxLayout(self)
        self._headline = QLabel(t("stop.card_description"))
        self._headline.setObjectName("stopInspectorHeadline")
        self._headline.setWordWrap(True)
        layout.addWidget(self._headline)
        self._card_route = QLabel()
        self._card_route.setObjectName("stopCardRoute")
        self._card_route.setWordWrap(True)
        layout.addWidget(self._card_route)
        self._card_hierarchy = QLabel()
        self._card_hierarchy.setObjectName("stopCardHierarchy")
        self._card_hierarchy.setWordWrap(True)
        layout.addWidget(self._card_hierarchy)
        self._card_operations = QLabel()
        self._card_operations.setObjectName("stopCardOperations")
        self._card_operations.setWordWrap(True)
        layout.addWidget(self._card_operations)
        self._card_context = QLabel()
        self._card_context.setObjectName("stopCardContext")
        self._card_context.setWordWrap(True)
        layout.addWidget(self._card_context)
        self._card_technical = QLabel()
        self._card_technical.setObjectName("stopCardTechnical")
        self._card_technical.setWordWrap(True)
        layout.addWidget(self._card_technical)
        action_layout = QHBoxLayout()
        self._center_button = QPushButton(t("stop.center"))
        self._center_button.setObjectName("centerStop")
        self._edit_button = QPushButton(t("stop.edit"))
        self._edit_button.setObjectName("editStop")
        self._details_button = QPushButton(t("stop.details"))
        self._details_button.setObjectName("stopMoreDetails")
        self._close_button = QPushButton(t("identity.about_close"))
        self._close_button.setObjectName("closeStopInspector")
        action_layout.addWidget(self._center_button)
        action_layout.addWidget(self._edit_button)
        action_layout.addWidget(self._details_button)
        action_layout.addWidget(self._close_button)
        action_layout.addStretch()
        self._center_button.clicked.connect(lambda: self._emit_action(self._on_center))
        self._edit_button.clicked.connect(lambda: self._emit_action(self._on_edit))
        self._details_button.clicked.connect(lambda: self._emit_action(self._on_details))
        self._close_button.clicked.connect(self.hide)
        layout.addLayout(action_layout)
        self._events = QTableWidget(0, 5)
        self._events.setObjectName("stopScheduledEvents")
        self._events.setHorizontalHeaderLabels(
            (
                t("routes.route"),
                t("routes.route_id"),
                t("stop.trip"),
                f"{t('stop.arrival')} GTFS (arrival_time)",
                f"{t('stop.departure')} GTFS (departure_time)",
            )
        )
        self._events.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._events.setAccessibleName(t("stop.events_accessible"))
        layout.addWidget(self._events)

    def clear(self) -> None:
        self._current_stop_id = None
        self._current_inspection = None
        self._current_events = ()
        self._headline.setText(t("stop.card_description"))
        for label in (
            self._card_route,
            self._card_hierarchy,
            self._card_operations,
            self._card_context,
            self._card_technical,
        ):
            label.clear()
        for button in (self._center_button, self._edit_button, self._details_button):
            button.setEnabled(False)
        self._edit_button.setVisible(False)
        self._events.setRowCount(0)

    def show_stop(self, stop_id: str) -> None:
        self.show()
        inspection = self._inspect_stop(stop_id)
        if inspection.stop is None:
            self._current_inspection = inspection
            self._current_events = ()
            self._headline.setText(t("stop.not_found", stop_id=stop_id))
            self._events.setRowCount(0)
            return
        self._current_stop_id = stop_id
        self._current_inspection = inspection
        events = inspection.scheduled_events.items
        self._current_events = events
        name = inspection.stop.name or t("stop.name_unknown")
        self._headline.setText(t("stop.card_title", name=name, stop_id=inspection.stop.stop_id))
        self._show_card(inspection, events)
        self._center_button.setEnabled(True)
        self._details_button.setEnabled(True)
        editable = self._on_edit is not None and (
            self._can_edit(stop_id) if self._can_edit is not None else False
        )
        self._edit_button.setVisible(editable)
        self._edit_button.setEnabled(editable)
        self._events.setRowCount(len(events))
        for row, event in enumerate(events):
            route_name = event.route.short_name or event.route.long_name or t("routes.name_unknown")
            for column, value in enumerate(
                (
                    route_name,
                    event.route.route_id,
                    event.trip_id,
                    event.arrival_time or t("stop.not_available"),
                    event.departure_time or t("stop.not_available"),
                )
            ):
                self._events.setItem(row, column, QTableWidgetItem(value))
        self._events.resizeColumnsToContents()

    def retranslate_ui(self) -> None:
        """Actualiza acciones y cabeceras; el contenido de feed se conserva."""
        self._center_button.setText(t("stop.center"))
        self._edit_button.setText(t("stop.edit"))
        self._details_button.setText(t("stop.details"))
        self._close_button.setText(t("identity.about_close"))
        self._events.setHorizontalHeaderLabels(
            (
                t("routes.route"),
                t("routes.route_id"),
                t("stop.trip"),
                f"{t('stop.arrival')} GTFS (arrival_time)",
                f"{t('stop.departure')} GTFS (departure_time)",
            )
        )
        self._events.setAccessibleName(t("stop.events_accessible"))
        if self._current_inspection is not None and self._current_inspection.stop is not None:
            self._show_card(self._current_inspection, self._current_events)

    def _show_card(
        self, inspection: StopInspection, events: tuple[ScheduledStopEvent, ...]
    ) -> None:
        stop = inspection.stop
        if stop is None:
            return
        event = events[0] if events else None
        if event is None:
            self._card_route.clear()
            self._card_hierarchy.setText(t("stop.no_events"))
            self._card_operations.clear()
            self._card_context.clear()
            self._card_technical.setText(f"{t('stop.stop_id')}: {stop.stop_id}")
            return
        route = event.route
        card = StopCard(
            stop_id=stop.stop_id,
            name=stop.name,
            route_id=route.route_id,
            route_short_name=route.short_name,
            route_long_name=route.long_name,
            route_color=route_color(route.route_id, route.route_color),
            endpoint="intermediate",
            arrival=event.arrival_time,
            departure=event.departure_time,
            sequence=event.stop_sequence,
            dwell_seconds=(
                event.departure_service_seconds - event.arrival_service_seconds
                if event.arrival_service_seconds is not None
                and event.departure_service_seconds is not None
                else None
            ),
            agency_id=route.agency_id,
            trip_id=event.trip_id,
            service_id=event.service_id,
        )
        self._card_route.setText(
            f"{t('stop.route_chip', short_name=card.route_short_name or card.route_id or '')} · "
            f"{card.route_long_name or t('stop.not_available')}"
        )
        self._card_route.setStyleSheet(
            "padding: 4px 8px; border-radius: 8px; color: white; "
            f"background-color: {card.route_color or '#2563eb'};"
        )
        endpoint = {
            "origin": t("stop.origin"),
            "destination": t("stop.destination"),
            "intermediate": t("stop.intermediate"),
        }.get(card.endpoint or "intermediate", t("stop.intermediate"))
        self._card_hierarchy.setText(f"{endpoint} · {card.route_short_name or card.route_id}")
        previous = (
            getattr(event, "previous_stop_name", None)
            or getattr(event, "previous_stop", None)
            or t("stop.not_available")
        )
        following = (
            getattr(event, "next_stop_name", None)
            or getattr(event, "next_stop", None)
            or t("stop.not_available")
        )
        dwell = (
            f"{t('stop.dwell')}: {card.dwell_seconds}s"
            if card.dwell_seconds is not None
            else f"{t('stop.dwell')}: {t('stop.not_available')}"
        )
        arrival = card.arrival or t("stop.not_available")
        departure = card.departure or t("stop.not_available")
        sequence = card.sequence if card.sequence is not None else t("stop.not_available")
        self._card_operations.setText(
            f"{t('stop.operations')}: {t('stop.arrival')} {arrival} · "
            f"{t('stop.departure')} {departure} · "
            f"{t('stop.sequence')} {sequence} · "
            f"{t('stop.previous')} {previous} · {t('stop.next')} {following} · {dwell}"
        )
        self._card_context.setText(
            f"{t('stop.context')}: "
            f"{t('stop.route')} {card.route_label or t('stop.not_available')} · "
            f"{t('stop.agency')} {card.agency or card.agency_id or t('stop.not_available')} · "
            f"{t('stop.trip')} {card.trip_id or t('stop.not_available')} · "
            f"{t('stop.service')} {card.service_id or t('stop.not_available')}"
        )
        self._card_technical.setText(
            f"{t('stop.technical')}: {t('stop.stop_id')} {card.stop_id} · "
            f"{t('stop.trip_id')} {card.trip_id or t('stop.not_available')} · "
            f"{t('stop.route_id')} {card.route_id or t('stop.not_available')} · "
            f"{t('stop.service_id')} {card.service_id or t('stop.not_available')}"
        )

    def _emit_action(self, callback: Callable[[str], None] | None) -> None:
        if self._current_stop_id is not None and callback is not None:
            callback(self._current_stop_id)
