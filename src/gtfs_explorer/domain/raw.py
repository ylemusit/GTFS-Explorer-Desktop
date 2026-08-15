"""Contrato seguro para inspeccionar filas de staging sin exponer SQL."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FilterOperator = Literal["contains", "equals", "gt", "gte", "lt", "lte"]
SortDirection = Literal["asc", "desc"]


@dataclass(frozen=True)
class RawFilter:
    """Predicado estructurado sobre una columna declarada en el manifiesto GTFS."""

    column: str
    operator: FilterOperator
    value: str


@dataclass(frozen=True)
class RawSort:
    """Orden estructurado, sin fragmentos SQL aportados por la UI."""

    column: str
    direction: SortDirection = "asc"


@dataclass(frozen=True)
class RawQuery:
    """Consulta limitada de un archivo GTFS conocido presente en staging."""

    filename: str
    columns: tuple[str, ...]
    filters: tuple[RawFilter, ...] = ()
    sort: tuple[RawSort, ...] = ()
    page_size: int = 100
    page_token: str | None = None

    def __post_init__(self) -> None:
        if (
            not self.columns
            or len(self.columns) > 32
            or len(set(self.columns)) != len(self.columns)
        ):
            raise ValueError("La consulta raw debe solicitar entre una y 32 columnas distintas.")
        if len(self.filters) > 8:
            raise ValueError("La consulta raw admite como máximo ocho filtros.")
        if len(self.sort) > 4:
            raise ValueError("La consulta raw admite como máximo cuatro ordenaciones.")
        if not 1 <= self.page_size <= 500:
            raise ValueError("El tamaño de página raw debe estar entre 1 y 500.")


@dataclass(frozen=True)
class RawColumn:
    name: str
    value_type: str


@dataclass(frozen=True)
class RawRow:
    source_row: int
    values: tuple[str | None, ...]


@dataclass(frozen=True)
class RawPage:
    """Respuesta acotada que la UI puede continuar con ``next_page_token``."""

    filename: str
    columns: tuple[RawColumn, ...]
    rows: tuple[RawRow, ...]
    next_page_token: str | None
