"""Casos de uso para servicios, calendario y excepciones GTFS."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import uuid4

from gtfs_explorer.application.editor_session import EditorSession
from gtfs_explorer.domain.changesets import EditorCommand, EditorCommandKind, ImpactAnalysis


@dataclass(frozen=True)
class ServiceSummary:
    service_id: str
    calendar_keys: tuple[tuple[str, str], ...]
    calendar_date_keys: tuple[tuple[str, str], ...]
    trip_ids: tuple[str, ...]


@dataclass(frozen=True)
class ServiceEditProposal:
    command: EditorCommand
    impact: ImpactAnalysis


class ServiceEditor:
    """Gestiona servicios sin convertir calendario en un campo libre de SQL."""

    def __init__(self, session: EditorSession) -> None:
        self._session = session

    def services(self) -> tuple[ServiceSummary, ...]:
        entities = self._session.working_copy.entities
        service_ids = {
            str(payload["service_id"])
            for key, payload in entities.items()
            if key[0] in {"gtfs_calendar", "gtfs_calendar_dates"}
            and payload.get("service_id") is not None
        }
        return tuple(
            ServiceSummary(
                service_id,
                tuple(
                    key
                    for key, payload in sorted(entities.items())
                    if key[0] == "gtfs_calendar" and payload.get("service_id") == service_id
                ),
                tuple(
                    key
                    for key, payload in sorted(entities.items())
                    if key[0] == "gtfs_calendar_dates" and payload.get("service_id") == service_id
                ),
                tuple(
                    sorted(
                        str(payload["trip_id"])
                        for key, payload in entities.items()
                        if key[0] == "gtfs_trips"
                        and payload.get("service_id") == service_id
                        and payload.get("trip_id") is not None
                    )
                ),
            )
            for service_id in sorted(service_ids)
        )

    def propose_calendar_update(
        self, entity_key: tuple[str, str], field: str, value: object
    ) -> ServiceEditProposal:
        if field not in {
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
            "start_date_lexeme",
            "end_date_lexeme",
        }:
            raise ValueError("El editor de servicios no admite ese campo de calendario.")
        before = self._session.working_copy.get(entity_key)
        if before is None:
            raise ValueError("La entidad de calendario no existe en el borrador.")
        self._ensure_service_editable(str(before.get("service_id")))
        return self._proposal(entity_key, field, value)

    def propose_exception_update(
        self, entity_key: tuple[str, str], *, date_lexeme: str, exception_type: int
    ) -> ServiceEditProposal:
        before = self._session.working_copy.get(entity_key)
        if before is None or entity_key[0] != "gtfs_calendar_dates":
            raise ValueError("La excepción de servicio no existe en el borrador.")
        self._ensure_service_editable(str(before.get("service_id")))
        after = dict(before)
        after["date_lexeme"] = date_lexeme
        after["exception_type"] = exception_type
        return self._proposal_for_payload(entity_key, before, after)

    def propose_service_add(self, service_id: str, **fields: object) -> ServiceEditProposal:
        if not service_id:
            raise ValueError("Un servicio necesita un service_id.")
        if any(item.service_id == service_id for item in self.services()):
            raise ValueError(f"El servicio {service_id!r} ya existe en el borrador.")
        key = ("gtfs_calendar", service_id)
        payload: dict[str, object] = {
            "source_filename": "editor",
            "source_row": len(self._session.working_copy.entities) + 1,
            "raw_values": {},
            "service_id": service_id,
            **fields,
        }
        return self._proposal_for_new(key, payload)

    def propose_exception_add(
        self, service_id: str, *, date_lexeme: str, exception_type: int
    ) -> ServiceEditProposal:
        parse_service_date(date_lexeme)
        if exception_type not in {1, 2}:
            raise ValueError("exception_type debe ser 1 o 2.")
        if not any(item.service_id == service_id for item in self.services()):
            raise ValueError("La excepción necesita un servicio existente.")
        key = ("gtfs_calendar_dates", f"draft-{uuid4().hex}")
        payload: dict[str, object] = {
            "source_filename": "editor",
            "source_row": len(self._session.working_copy.entities) + 1,
            "raw_values": {},
            "service_id": service_id,
            "date_lexeme": date_lexeme,
            "date": parse_service_date(date_lexeme),
            "exception_type": exception_type,
        }
        return self._proposal_for_new(key, payload)

    def propose_delete(self, service_id: str) -> ServiceEditProposal:
        summary = next((item for item in self.services() if item.service_id == service_id), None)
        if summary is None:
            raise ValueError("El servicio no existe en el borrador.")
        self._ensure_service_editable(service_id)
        key = summary.calendar_keys[0] if summary.calendar_keys else summary.calendar_date_keys[0]
        before = self._session.working_copy.get(key)
        if before is None:
            raise ValueError("La entidad de servicio no existe en el borrador.")
        command = EditorCommand(EditorCommandKind.UPDATE_SERVICE, key, before, None)
        return ServiceEditProposal(command, self._session.preview_impact(command))

    def prepare_delete(
        self,
        proposal: ServiceEditProposal,
        *,
        resolution: str,
        replacement_id: str | None = None,
    ) -> EditorCommand:
        return self._session.prepare_command(
            proposal.command,
            proposal.impact,
            resolution=resolution,
            replacement_id=replacement_id,
        )

    def apply(self, proposal: ServiceEditProposal) -> EditorCommand:
        return self._session.apply(proposal.command, impact=proposal.impact)

    def _proposal(
        self, entity_key: tuple[str, str], field: str, value: object
    ) -> ServiceEditProposal:
        before = self._session.working_copy.get(entity_key)
        if before is None:
            raise ValueError("La entidad de servicio no existe en el borrador.")
        after = dict(before)
        after[field] = value
        return self._proposal_for_payload(entity_key, before, after)

    def _proposal_for_payload(
        self,
        entity_key: tuple[str, str],
        before: dict[str, object],
        after: dict[str, object],
    ) -> ServiceEditProposal:
        command = EditorCommand(EditorCommandKind.UPDATE_SERVICE, entity_key, before, after)
        return ServiceEditProposal(command, self._session.preview_impact(command))

    def _proposal_for_new(
        self, entity_key: tuple[str, str], after: dict[str, object]
    ) -> ServiceEditProposal:
        command = EditorCommand(EditorCommandKind.UPDATE_SERVICE, entity_key, None, after)
        return ServiceEditProposal(command, self._session.preview_impact(command))

    def _ensure_service_editable(self, service_id: str) -> None:
        can_edit = getattr(self._session, "can_edit_route", None)
        if not callable(can_edit):
            return
        route_ids = {
            str(payload.get("route_id"))
            for key, payload in self._session.working_copy.entities.items()
            if key[0] == "gtfs_trips"
            and payload.get("service_id") == service_id
            and payload.get("route_id") is not None
        }
        if any(not can_edit(route_id) for route_id in route_ids):
            raise ValueError(
                "El servicio se usa en una ruta no autorizada; no se modifica de forma global."
            )


def parse_service_date(value: str) -> date:
    if len(value) != 8 or not value.isdecimal():
        raise ValueError("La fecha de servicio debe tener formato YYYYMMDD.")
    try:
        return date.fromisoformat(f"{value[:4]}-{value[4:6]}-{value[6:]}")
    except ValueError as error:
        raise ValueError("La fecha de servicio no es válida.") from error
