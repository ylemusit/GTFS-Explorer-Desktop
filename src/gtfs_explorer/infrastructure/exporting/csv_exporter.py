"""Exportación CSV UTF-8 fiel o segura para hojas de cálculo."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from gtfs_explorer.domain.exporting import ExportManifest
from gtfs_explorer.infrastructure.exporting.atomic_output import (
    AtomicOutputWriter,
    CancellationCheck,
)


class CsvExportMode(StrEnum):
    """El modo fiel conserva valores; el seguro evita fórmulas al abrir en Excel."""

    FAITHFUL = "faithful"
    SPREADSHEET_SAFE = "spreadsheet-safe"


@dataclass(frozen=True)
class CsvExportOptions:
    """Opciones explícitas y reproducibles; el delimitador GTFS es siempre coma."""

    mode: CsvExportMode = CsvExportMode.FAITHFUL
    include_utf8_bom: bool = False


class CsvExporter:
    """Publica CSV atómico sin materializar todas las filas en memoria."""

    def __init__(self, writer: AtomicOutputWriter | None = None) -> None:
        self._writer = writer or AtomicOutputWriter()

    def write(
        self,
        destination: Path,
        *,
        headers: Sequence[str],
        rows: Iterable[Sequence[str | None]],
        options: CsvExportOptions = CsvExportOptions(),
        overwrite: bool = False,
        is_cancelled: CancellationCheck = lambda: False,
    ) -> ExportManifest:
        """Exporta una tabla ya filtrada con modo explícito en nombre y manifiesto."""
        _validate_headers(headers)
        _validate_destination_name(destination, options.mode)
        return self._writer.write(
            destination,
            self._chunks(headers, rows, options, is_cancelled),
            overwrite=overwrite,
            is_cancelled=is_cancelled,
            manifest_metadata={
                "csv_delimiter": ",",
                "encoding": "utf-8",
                "formula_neutralization": options.mode is CsvExportMode.SPREADSHEET_SAFE,
                "mode": options.mode.value,
                "utf8_bom": options.include_utf8_bom,
            },
        )

    @staticmethod
    def _chunks(
        headers: Sequence[str],
        rows: Iterable[Sequence[str | None]],
        options: CsvExportOptions,
        is_cancelled: CancellationCheck,
    ) -> Iterator[bytes]:
        if options.include_utf8_bom:
            yield b"\xef\xbb\xbf"
        yield _csv_line(headers)
        expected_columns = len(headers)
        for row in rows:
            if is_cancelled():
                from gtfs_explorer.domain.exporting import ExportCancelled

                raise ExportCancelled("La exportación CSV se ha cancelado.")
            if len(row) != expected_columns:
                raise ValueError(
                    "Cada fila CSV debe tener exactamente las columnas de la cabecera."
                )
            values = (_value_for_mode(value, options.mode) for value in row)
            yield _csv_line(values)


def _validate_headers(headers: Sequence[str]) -> None:
    if not headers or any(not header for header in headers) or len(set(headers)) != len(headers):
        raise ValueError("La exportación CSV requiere cabeceras únicas y no vacías.")


def _validate_destination_name(destination: Path, mode: CsvExportMode) -> None:
    suffix = f"-{mode.value}.csv"
    if not destination.name.casefold().endswith(suffix):
        raise ValueError(f"El nombre CSV debe terminar en '{suffix}' para mostrar el modo elegido.")


def _csv_line(values: Iterable[str]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, delimiter=",", lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(values)
    return buffer.getvalue().encode("utf-8")


def _value_for_mode(value: str | None, mode: CsvExportMode) -> str:
    text = "" if value is None else value
    if mode is CsvExportMode.SPREADSHEET_SAFE and text[:1] in {"=", "+", "-", "@"}:
        return "'" + text
    return text
