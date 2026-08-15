"""Datos de resumen del feed para la pantalla de proyecto."""

from __future__ import annotations

from dataclasses import dataclass

from .project import FeedMetadata
from .service_calendar import ServicePeriod


@dataclass(frozen=True)
class OverviewMetric:
    """Recuento normalizado, con unidad y origen visibles para la UI."""

    label: str
    value: int
    unit: str
    source: str


@dataclass(frozen=True)
class OverviewFile:
    """Archivo inventariado; ``row_count=None`` significa que no se cargó."""

    name: str
    known_to_schedule_spec: bool
    row_count: int | None


@dataclass(frozen=True)
class ValidationOverview:
    """Estado agregado de las ejecuciones de validación registradas."""

    run_count: int
    total_issue_count: int
    statuses: tuple[str, ...]


@dataclass(frozen=True)
class FeedOverview:
    """Consulta de lectura del feed abierto, sin semántica de tiempo real."""

    feed: FeedMetadata | None
    period: ServicePeriod | None
    metrics: tuple[OverviewMetric, ...]
    files: tuple[OverviewFile, ...]
    validation: ValidationOverview
