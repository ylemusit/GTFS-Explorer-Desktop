"""Lector CSV estricto GTFS y compatible sin pérdida silenciosa de lexemas."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from gtfs_explorer.domain.errors import TabularReadError


@dataclass(frozen=True)
class TabularRow:
    number: int
    values: tuple[str, ...]


@dataclass(frozen=True)
class TabularData:
    header: tuple[str, ...]
    rows: tuple[TabularRow, ...]


@dataclass(frozen=True)
class TabularBatch:
    """Un lote de filas que conserva la cabecera y las filas físicas."""

    header: tuple[str, ...]
    rows: tuple[TabularRow, ...]


@dataclass(frozen=True)
class CompatibleTabularFormat:
    """Formato propuesto para un CSV que el usuario debe confirmar antes de leer."""

    encoding: str
    delimiter: str


class TabularReader:
    def __init__(self, maximum_field_size: int = 1024 * 1024) -> None:
        self._maximum_field_size = maximum_field_size

    def read_gtfs(self, path: Path) -> TabularData:
        return self._read(path.read_bytes(), encoding="utf-8-sig", delimiter=",", strict=True)

    def iter_gtfs_batches(self, path: Path, batch_size: int) -> Iterator[TabularBatch]:
        """Lee un GTFS estricto por lotes, sin materializar todas sus filas en Python."""
        if batch_size < 1:
            raise ValueError("El tamaño de lote debe ser mayor que cero.")
        previous_limit = csv.field_size_limit(self._maximum_field_size)
        try:
            with (
                path.open("rb") as raw_file,
                io.TextIOWrapper(raw_file, encoding="utf-8-sig", newline="") as text_file,
            ):
                reader = csv.reader(text_file, delimiter=",", strict=True)
                try:
                    header = tuple(next(reader))
                except StopIteration as error:
                    raise TabularReadError("archivo tabular vacío", 1) from error
                if not header or any(not value for value in header):
                    raise TabularReadError("cabecera ausente o vacía", reader.line_num or 1)
                batch: list[TabularRow] = []
                for values in reader:
                    batch.append(TabularRow(reader.line_num, tuple(values)))
                    if len(batch) == batch_size:
                        yield TabularBatch(header, tuple(batch))
                        batch = []
                if batch:
                    yield TabularBatch(header, tuple(batch))
        except UnicodeDecodeError as error:
            raise TabularReadError("codificación inválida", 1) from error
        except csv.Error as error:
            raise TabularReadError(str(error), reader.line_num or 1) from error
        finally:
            csv.field_size_limit(previous_limit)

    def detect_compatible(self, path: Path) -> CompatibleTabularFormat:
        """Propone, sin leer el archivo, un formato UTF-8 que debe confirmarse después."""
        contents = path.read_bytes()
        encoding = "utf-8-sig" if contents.startswith(b"\xef\xbb\xbf") else "utf-8"
        try:
            text = contents.decode(encoding)
        except UnicodeDecodeError as error:
            row_number = contents[: error.start].count(b"\n") + 1
            raise TabularReadError("codificación compatible no detectada", row_number) from error
        try:
            dialect = csv.Sniffer().sniff(text, delimiters=",;\t|")
        except csv.Error:
            delimiter = ","
        else:
            delimiter = dialect.delimiter
        return CompatibleTabularFormat(encoding=encoding, delimiter=delimiter)

    def read_compatible(
        self, path: Path, *, encoding: str, delimiter: str, confirmed: bool
    ) -> TabularData:
        if not confirmed:
            raise TabularReadError(
                "El modo compatible requiere confirmación explícita de encoding y delimitador.",
                1,
            )
        return self._read(path.read_bytes(), encoding=encoding, delimiter=delimiter, strict=False)

    def _read(self, contents: bytes, *, encoding: str, delimiter: str, strict: bool) -> TabularData:
        try:
            text = contents.decode(encoding)
        except UnicodeDecodeError as error:
            row_number = contents[: error.start].count(b"\n") + 1
            raise TabularReadError("codificación inválida", row_number) from error
        previous_limit = csv.field_size_limit(self._maximum_field_size)
        try:
            reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=strict)
            try:
                header = tuple(next(reader))
            except StopIteration as error:
                raise TabularReadError("archivo tabular vacío", 1) from error
            if not header or any(not value for value in header):
                raise TabularReadError("cabecera ausente o vacía", reader.line_num or 1)
            rows = tuple(TabularRow(reader.line_num, tuple(values)) for values in reader)
        except csv.Error as error:
            raise TabularReadError(str(error), reader.line_num or 1) from error
        finally:
            csv.field_size_limit(previous_limit)
        return TabularData(header, rows)
