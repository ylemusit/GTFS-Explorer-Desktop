"""Casos de uso para matriz de horarios y operaciones explícitas de secuencia."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from gtfs_explorer.application.editor_session import EditorSession
from gtfs_explorer.domain.changesets import (
    EditorCommand,
    EditorCommandKind,
    EntityChange,
    ImpactAnalysis,
)


@dataclass(frozen=True)
class ScheduleMatrixRow:
    """Fila de una matriz de horarios, ya ordenada por viaje y secuencia."""

    entity_key: tuple[str, str]
    trip_id: str
    stop_id: str | None
    stop_sequence: int | None
    arrival_time: str | None
    departure_time: str | None


@dataclass(frozen=True)
class ScheduleEditProposal:
    command: EditorCommand
    impact: ImpactAnalysis


@dataclass(frozen=True)
class InterpolatedCell:
    """Valor sugerido, todavía no aplicado, para una celda sin horario."""

    entity_key: tuple[str, str]
    field: str
    lexeme: str


@dataclass(frozen=True)
class StopInsertionProposal:
    """Inserción explícita de parada y ``stop_time`` como una unidad."""

    command: EditorCommand
    impact: ImpactAnalysis
    stop_key: tuple[str, str]
    stop_time_key: tuple[str, str]


class ScheduleEditor:
    """Matriz sin SQL que propone comandos sobre ``gtfs_stop_times``."""

    def __init__(self, session: EditorSession) -> None:
        self._session = session

    def matrix(self, trip_id: str) -> tuple[ScheduleMatrixRow, ...]:
        rows = list(self._session.working_copy.entity_index.stop_times_by_trip.get(trip_id, ()))
        rows.sort(key=lambda item: _sequence(item[1].get("stop_sequence")))
        return tuple(
            ScheduleMatrixRow(
                key,
                str(payload.get("trip_id") or trip_id),
                _text(payload.get("stop_id")),
                _integer(payload.get("stop_sequence")),
                _text(payload.get("arrival_time_lexeme")),
                _text(payload.get("departure_time_lexeme")),
            )
            for key, payload in rows
        )

    def apply(self, proposal: ScheduleEditProposal) -> EditorCommand:
        return self._session.apply(proposal.command, impact=proposal.impact)

    def propose_trip_update(
        self, entity_key: tuple[str, str], field: str, value: object
    ) -> ScheduleEditProposal:
        if entity_key[0] != "gtfs_trips":
            raise ValueError("La entidad no es un viaje GTFS.")
        before = self._session.working_copy.get(entity_key)
        if before is None:
            raise ValueError("El viaje ya no existe en el borrador.")
        self._ensure_trip_editable(before)
        after = dict(before)
        after[field] = value
        command = EditorCommand(EditorCommandKind.UPDATE_TRIP, entity_key, before, after)
        return ScheduleEditProposal(command, self._session.preview_impact(command))

    def propose_time_update(
        self, entity_key: tuple[str, str], field: str, lexeme: str
    ) -> ScheduleEditProposal:
        if field not in {"arrival_time_lexeme", "departure_time_lexeme"}:
            raise ValueError("La matriz solo admite columnas de llegada y salida.")
        _parse_time(lexeme)
        before = self._session.working_copy.get(entity_key)
        if before is None:
            raise ValueError("La fila de horarios ya no existe en el borrador.")
        trip = self._session.working_copy.entity_index.trips_by_id.get(
            str(before.get("trip_id") or "")
        )
        if trip is not None:
            self._ensure_trip_editable(trip)
        after = dict(before)
        after[field] = lexeme
        command = EditorCommand(EditorCommandKind.UPDATE_STOP_TIME, entity_key, before, after)
        return ScheduleEditProposal(command, self._session.preview_impact(command))

    def propose_add_stop_to_trip(
        self,
        trip_id: str,
        *,
        stop_id: str,
        stop_name: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        arrival_time: str | None = None,
        departure_time: str | None = None,
    ) -> StopInsertionProposal:
        """Añade una parada y su horario sin interpolar ninguna otra celda."""
        trip_key, trip = self._trip(trip_id)
        self._ensure_trip_editable(trip)
        if stop_id in self._session.working_copy.entity_index.stops_by_id:
            raise ValueError(f"La parada {stop_id!r} ya existe en el borrador.")
        if arrival_time is not None:
            _parse_time(arrival_time)
        if departure_time is not None:
            _parse_time(departure_time)
        entities = self._session.working_copy.entity_index
        stop_key = ("gtfs_stops", stop_id)
        source_rows = [
            value
            for _key, payload in entities.by_table.get("gtfs_stops", ())
            if isinstance((value := payload.get("source_row")), int) and not isinstance(value, bool)
        ]
        stop_time_key = ("gtfs_stop_times", f"draft-{uuid4().hex}")
        stop_payload: dict[str, object] = {
            "source_filename": "editor",
            "source_row": max(source_rows, default=0) + 1,
            "raw_values": {},
            "stop_id": stop_id,
            "stop_name": stop_name,
            "stop_lat": latitude,
            "stop_lon": longitude,
        }
        existing = list(self.matrix(trip_id))
        sequence = (len(existing) + 1) * 10
        stop_time_payload: dict[str, object] = {
            "source_filename": "editor",
            "source_row": entities.entity_count + 1,
            "raw_values": {},
            "trip_id": trip_id,
            "stop_id": stop_id,
            "stop_sequence": sequence,
            "arrival_time_lexeme": arrival_time,
            "departure_time_lexeme": departure_time,
        }
        command = EditorCommand(
            EditorCommandKind.ADD_STOP,
            stop_key,
            None,
            stop_payload,
            changes=(EntityChange(stop_time_key, None, stop_time_payload),),
            metadata={"trip_id": trip_id, "schedule_insert": True},
        )
        return StopInsertionProposal(
            command,
            self._session.preview_impact(command),
            stop_key,
            stop_time_key,
        )

    def apply_stop_insertion(self, proposal: StopInsertionProposal) -> EditorCommand:
        return self._session.apply(proposal.command, impact=proposal.impact)

    def interpolation_preview(self, trip_id: str, field: str) -> tuple[InterpolatedCell, ...]:
        if field not in {"arrival_time_lexeme", "departure_time_lexeme"}:
            raise ValueError("La interpolación solo admite llegada o salida.")
        rows = list(self.matrix(trip_id))
        suggestions: list[InterpolatedCell] = []
        for index, row in enumerate(rows):
            if getattr(row, "arrival_time" if field.startswith("arrival") else "departure_time"):
                continue
            previous = next(
                (value for value in reversed(rows[:index]) if _row_time(value, field) is not None),
                None,
            )
            following = next(
                (value for value in rows[index + 1 :] if _row_time(value, field) is not None),
                None,
            )
            if previous is None or following is None:
                continue
            before_seconds = _parse_time(_row_time(previous, field) or "")
            after_seconds = _parse_time(_row_time(following, field) or "")
            gap = rows.index(following) - rows.index(previous)
            offset = index - rows.index(previous)
            seconds = before_seconds + round((after_seconds - before_seconds) * offset / gap)
            suggestions.append(InterpolatedCell(row.entity_key, field, _format_time(seconds)))
        return tuple(suggestions)

    def apply_interpolation(
        self, cells: tuple[InterpolatedCell, ...], *, accepted: bool
    ) -> EditorCommand | None:
        if not accepted:
            raise ValueError("La interpolación requiere aceptación explícita.")
        if not cells:
            return None
        primary = cells[0]
        before = self._session.working_copy.get(primary.entity_key)
        if before is None:
            raise ValueError("La celda de interpolación ya no existe en el borrador.")
        after = dict(before)
        after[primary.field] = primary.lexeme
        changes = []
        for cell in cells[1:]:
            current = self._session.working_copy.get(cell.entity_key)
            if current is None:
                raise ValueError("Una celda de interpolación ya no existe en el borrador.")
            updated = dict(current)
            updated[cell.field] = cell.lexeme
            changes.append(EntityChange(cell.entity_key, current, updated))
        command = EditorCommand(
            EditorCommandKind.UPDATE_STOP_TIME,
            primary.entity_key,
            before,
            after,
            changes=tuple(changes),
            metadata={"interpolation": "accepted_explicitly", "cell_count": len(cells)},
        )
        return command

    def _trip(self, trip_id: str) -> tuple[tuple[str, str], dict[str, object]]:
        for key, payload in self._session.working_copy.entity_index.by_table.get("gtfs_trips", ()):
            if payload.get("trip_id") == trip_id:
                return key, payload
        raise ValueError(f"El viaje {trip_id!r} no existe en el borrador.")

    def _ensure_trip_editable(self, trip: dict[str, object]) -> None:
        route_id = trip.get("route_id")
        can_edit = getattr(self._session, "can_edit_route", None)
        if route_id is not None and callable(can_edit) and not can_edit(str(route_id)):
            raise ValueError("La ruta del viaje no está activa, editable y desbloqueada.")

    def propose_reorder(
        self, trip_id: str, entity_key: tuple[str, str], new_index: int
    ) -> ScheduleEditProposal:
        matrix = list(self.matrix(trip_id))
        if not 0 <= new_index < len(matrix):
            raise ValueError("La nueva posición queda fuera de la matriz del viaje.")
        positions = {row.entity_key: index for index, row in enumerate(matrix)}
        if entity_key not in positions:
            raise ValueError("La fila no pertenece al viaje indicado.")
        _trip_key, trip = self._trip(trip_id)
        self._ensure_trip_editable(trip)
        row = matrix.pop(positions[entity_key])
        matrix.insert(new_index, row)
        sequence_values = _new_sequences(matrix)
        before = self._session.working_copy.get(entity_key)
        if before is None:
            raise ValueError("La fila de horarios ya no existe en el borrador.")
        after = dict(before)
        after["stop_sequence"] = sequence_values[entity_key]
        changes = tuple(
            EntityChange(
                other.entity_key,
                self._session.working_copy.get(other.entity_key),
                _with_sequence(
                    self._session.working_copy.get(other.entity_key),
                    sequence_values[other.entity_key],
                ),
            )
            for other in matrix
            if other.entity_key != entity_key
        )
        command = EditorCommand(
            EditorCommandKind.REORDER_STOP,
            entity_key,
            before,
            after,
            changes=changes,
            metadata={"trip_id": trip_id, "matrix_reorder": True},
        )
        return ScheduleEditProposal(command, self._session.preview_impact(command))


def _new_sequences(rows: list[ScheduleMatrixRow]) -> dict[tuple[str, str], int]:
    """Usa múltiplos de diez para facilitar inserciones futuras sin renumerar todo."""
    return {row.entity_key: (index + 1) * 10 for index, row in enumerate(rows)}


def _with_sequence(payload: dict[str, object] | None, sequence: int) -> dict[str, object]:
    if payload is None:
        raise ValueError("La fila de horarios ya no existe en el borrador.")
    result = dict(payload)
    result["stop_sequence"] = sequence
    return result


def _sequence(value: object) -> tuple[int, int | str]:
    if isinstance(value, int):
        return (0, value)
    return (1, "" if value is None else str(value))


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _text(value: object) -> str | None:
    return None if value is None else str(value)


def _row_time(row: ScheduleMatrixRow, field: str) -> str | None:
    return row.arrival_time if field.startswith("arrival") else row.departure_time


def _parse_time(value: str) -> int:
    parts = value.split(":")
    if len(parts) != 3 or any(not part.isdecimal() for part in parts):
        raise ValueError("La hora GTFS debe tener formato HH:MM:SS.")
    hours, minutes, seconds = (int(part) for part in parts)
    if minutes > 59 or seconds > 59:
        raise ValueError("La hora GTFS debe tener minutos y segundos válidos.")
    return hours * 3600 + minutes * 60 + seconds


def _format_time(value: int) -> str:
    hours, remainder = divmod(value, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
