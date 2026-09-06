"""Casos de uso para agencias, asignación de rutas y atribuciones GTFS."""

from __future__ import annotations

from dataclasses import dataclass

from gtfs_explorer.application.editor_session import EditorSession
from gtfs_explorer.domain.changesets import EditorCommand, EditorCommandKind, ImpactAnalysis


@dataclass(frozen=True)
class OperatorSummary:
    agency_id: str
    route_ids: tuple[str, ...]
    attribution_ids: tuple[str, ...]


@dataclass(frozen=True)
class OperatorEditProposal:
    command: EditorCommand
    impact: ImpactAnalysis


class OperatorEditor:
    """Edita operadores y atribuciones, sin convertirlos en cuentas de aplicación."""

    def __init__(self, session: EditorSession) -> None:
        self._session = session

    def operators(self) -> tuple[OperatorSummary, ...]:
        entities = self._session.working_copy.entities
        agency_ids = sorted(
            str(payload["agency_id"])
            for key, payload in entities.items()
            if key[0] == "gtfs_agency" and payload.get("agency_id") is not None
        )
        return tuple(
            OperatorSummary(
                agency_id,
                tuple(
                    sorted(
                        str(payload["route_id"])
                        for key, payload in entities.items()
                        if key[0] == "gtfs_routes"
                        and payload.get("agency_id") == agency_id
                        and payload.get("route_id") is not None
                    )
                ),
                tuple(
                    sorted(
                        str(payload["attribution_id"])
                        for key, payload in entities.items()
                        if key[0] == "gtfs_attributions"
                        and payload.get("agency_id") == agency_id
                        and payload.get("attribution_id") is not None
                    )
                ),
            )
            for agency_id in agency_ids
        )

    def propose_agency_update(
        self, entity_key: tuple[str, str], field: str, value: object
    ) -> OperatorEditProposal:
        if entity_key[0] != "gtfs_agency":
            raise ValueError("La entidad no es una agencia GTFS.")
        self._ensure_routes_editable(entity_key)
        return self._proposal(entity_key, field, value, EditorCommandKind.UPDATE_AGENCY)

    def propose_agency_add(self, agency_id: str, **fields: object) -> OperatorEditProposal:
        if not agency_id:
            raise ValueError("Una agencia necesita un agency_id.")
        key = ("gtfs_agency", agency_id)
        if self._session.working_copy.get(key) is not None:
            raise ValueError(f"La agencia {agency_id!r} ya existe en el borrador.")
        payload: dict[str, object] = {
            "source_filename": "editor",
            "source_row": len(self._session.working_copy.entities) + 1,
            "raw_values": {},
            "agency_id": agency_id,
            **fields,
        }
        command = EditorCommand(EditorCommandKind.UPDATE_AGENCY, key, None, payload)
        return OperatorEditProposal(command, self._session.preview_impact(command))

    def propose_route_assignment(
        self, entity_key: tuple[str, str], agency_id: str | None
    ) -> OperatorEditProposal:
        if entity_key[0] != "gtfs_routes":
            raise ValueError("La entidad no es una ruta GTFS.")
        self._ensure_routes_editable(entity_key)
        return self._proposal(entity_key, "agency_id", agency_id, EditorCommandKind.UPDATE_ROUTE)

    def propose_attribution_update(
        self, entity_key: tuple[str, str], field: str, value: object
    ) -> OperatorEditProposal:
        if entity_key[0] != "gtfs_attributions":
            raise ValueError("La entidad no es una atribución GTFS.")
        self._ensure_routes_editable(entity_key)
        return self._proposal(entity_key, field, value, EditorCommandKind.UPDATE_ATTRIBUTION)

    def propose_attribution_add(
        self, attribution_id: str, **fields: object
    ) -> OperatorEditProposal:
        if not attribution_id:
            raise ValueError("Una atribución necesita un attribution_id.")
        key = ("gtfs_attributions", attribution_id)
        if self._session.working_copy.get(key) is not None:
            raise ValueError(f"La atribución {attribution_id!r} ya existe en el borrador.")
        payload: dict[str, object] = {
            "source_filename": "editor",
            "source_row": len(self._session.working_copy.entities) + 1,
            "raw_values": {},
            "attribution_id": attribution_id,
            **fields,
        }
        command = EditorCommand(EditorCommandKind.UPDATE_ATTRIBUTION, key, None, payload)
        return OperatorEditProposal(command, self._session.preview_impact(command))

    def propose_agency_delete(self, entity_key: tuple[str, str]) -> OperatorEditProposal:
        if entity_key[0] != "gtfs_agency":
            raise ValueError("La entidad no es una agencia GTFS.")
        before = self._session.working_copy.get(entity_key)
        if before is None:
            raise ValueError("La agencia no existe en el borrador.")
        self._ensure_routes_editable(entity_key)
        command = EditorCommand(EditorCommandKind.UPDATE_AGENCY, entity_key, before, None)
        return OperatorEditProposal(command, self._session.preview_impact(command))

    def apply(self, proposal: OperatorEditProposal) -> EditorCommand:
        return self._session.apply(proposal.command, impact=proposal.impact)

    def _proposal(
        self,
        entity_key: tuple[str, str],
        field: str,
        value: object,
        kind: EditorCommandKind,
    ) -> OperatorEditProposal:
        before = self._session.working_copy.get(entity_key)
        if before is None:
            raise ValueError("La entidad de operador no existe en el borrador.")
        after = dict(before)
        after[field] = value
        command = EditorCommand(kind, entity_key, before, after)
        return OperatorEditProposal(command, self._session.preview_impact(command))

    def _ensure_routes_editable(self, entity_key: tuple[str, str]) -> None:
        can_edit = getattr(self._session, "can_edit_route", None)
        if not callable(can_edit):
            return
        route_ids = self._session.working_copy.route_ids_for_entity(entity_key)
        if any(not can_edit(route_id) for route_id in route_ids):
            raise ValueError(
                "La entidad afecta a una ruta no autorizada: activa, editable y desbloqueada."
            )
