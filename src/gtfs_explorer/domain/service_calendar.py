"""Reglas puras para resolver servicios GTFS por fecha de servicio."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal


@dataclass(frozen=True)
class ServicePeriod:
    """Periodo inclusivo durante el que el feed declara alguna fecha de servicio."""

    start_date: date
    end_date: date

    def __post_init__(self) -> None:
        if self.start_date > self.end_date:
            raise ValueError("El inicio del periodo de servicio no puede ser posterior a su fin.")


@dataclass(frozen=True)
class CalendarRule:
    """Regla semanal inclusiva de una fila de ``calendar.txt``."""

    service_id: str
    weekdays: tuple[bool, bool, bool, bool, bool, bool, bool]
    period: ServicePeriod

    def operates_on(self, service_date: date) -> bool:
        return (
            self.period.start_date <= service_date <= self.period.end_date
            and self.weekdays[service_date.weekday()]
        )


@dataclass(frozen=True)
class CalendarException:
    """Excepción de alta o baja de una fecha de ``calendar_dates.txt``."""

    service_id: str
    service_date: date
    exception_type: Literal[1, 2]


class ServiceCalendar:
    """Resuelve el calendario GTFS sin depender de UI ni de zonas horarias."""

    def __init__(
        self,
        rules: tuple[CalendarRule, ...] = (),
        exceptions: tuple[CalendarException, ...] = (),
    ) -> None:
        self._rules = rules
        self._exceptions = exceptions

    def service_ids_on(self, service_date: date) -> tuple[str, ...]:
        """Devuelve los servicios activos, aplicando add/remove sobre la regla semanal."""
        active = {rule.service_id for rule in self._rules if rule.operates_on(service_date)}
        for exception in self._exceptions:
            if exception.service_date != service_date:
                continue
            if exception.exception_type == 1:
                active.add(exception.service_id)
            else:
                active.discard(exception.service_id)
        return tuple(sorted(active))

    def period(self) -> ServicePeriod | None:
        """Devuelve el límite global declarado o ``None`` cuando no hay fechas válidas."""
        boundaries = [
            boundary
            for rule in self._rules
            for boundary in (rule.period.start_date, rule.period.end_date)
        ] + [exception.service_date for exception in self._exceptions]
        if not boundaries:
            return None
        return ServicePeriod(min(boundaries), max(boundaries))
