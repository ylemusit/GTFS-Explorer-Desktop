"""Escritura y revalidación previa de un subconjunto GTFS Schedule."""

from __future__ import annotations

import csv
import io
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from gtfs_explorer.application.commands.import_feed import ImportFeed
from gtfs_explorer.domain.exporting import ExportError, ExportManifest
from gtfs_explorer.domain.project import JobState, ProjectMetadata, ProjectStatus
from gtfs_explorer.domain.source import InputSource, InputSourceKind
from gtfs_explorer.domain.spec import ScheduleSpec
from gtfs_explorer.domain.subset import CoreSubset, CoreSubsetSource
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.infrastructure.duckdb.repositories.base import DuckDbCoreSubsetRepository
from gtfs_explorer.infrastructure.exporting.atomic_output import (
    AtomicOutputWriter,
    CancellationCheck,
)


class FormalValidationStatus(StrEnum):
    """Resultado explícito del validador formal opcional de MobilityData."""

    NOT_AVAILABLE = "not_available"
    PASSED = "passed"
    FAILED = "failed"


@dataclass(frozen=True)
class FormalValidationResult:
    status: FormalValidationStatus


@dataclass(frozen=True)
class MiniGtfsTable:
    """Tabla ya cerrada por T055/T056, conservada como lexemas GTFS."""

    filename: str
    headers: tuple[str, ...]
    rows: tuple[tuple[str | None, ...], ...]

    def __post_init__(self) -> None:
        if not self.filename.endswith(".txt") or "/" in self.filename or "\\" in self.filename:
            raise ValueError("Mini-GTFS solo admite archivos .txt en la raíz del ZIP.")
        if (
            not self.headers
            or len(set(self.headers)) != len(self.headers)
            or any(not header for header in self.headers)
        ):
            raise ValueError("Cada tabla Mini-GTFS requiere cabeceras únicas y no vacías.")
        if any(len(row) != len(self.headers) for row in self.rows):
            raise ValueError("Cada fila Mini-GTFS debe coincidir con su cabecera.")


FormalValidator = Callable[[Path], FormalValidationResult]


class MiniGtfsSubsetExporter:
    """Publica solo un ZIP que haya superado una reimportación interna completa."""

    def __init__(
        self,
        specification: ScheduleSpec,
        *,
        writer: AtomicOutputWriter | None = None,
        database_factory: Callable[[Path], ProjectDatabase] | None = None,
        formal_validator: FormalValidator | None = None,
    ) -> None:
        self._specification = specification
        self._writer = writer or AtomicOutputWriter()
        self._database_factory = database_factory or _database_for_revalidation
        self._formal_validator = formal_validator

    def write(
        self,
        destination: Path,
        tables: Iterable[MiniGtfsTable],
        *,
        expected: CoreSubset,
        overwrite: bool = False,
        is_cancelled: CancellationCheck = lambda: False,
    ) -> ExportManifest:
        """Serializa, reimporta y solo entonces publica ZIP y manifiesto lateral.

        ``tables`` debe proceder del cierre core/opcional ya calculado: esta capa no
        inventa ni modifica filas del feed fuente. Las filas se ordenan por sus
        lexemas para que el mismo cierre produzca el mismo contenedor ZIP.
        """
        materialized = tuple(sorted(tables, key=lambda table: table.filename))
        _validate_tables(materialized, self._specification, expected)
        temporary = self._temporary_zip(destination)
        try:
            _raise_if_cancelled(is_cancelled)
            _write_zip(temporary, materialized, is_cancelled)
            self._revalidate(temporary, expected, is_cancelled)
            formal = self._formal(temporary)
            if formal.status is FormalValidationStatus.FAILED:
                raise ExportError("La validación formal Mini-GTFS ha informado errores.")
            _raise_if_cancelled(is_cancelled)
            return self._writer.write(
                destination,
                _file_chunks(temporary, is_cancelled),
                overwrite=overwrite,
                is_cancelled=is_cancelled,
                manifest_metadata={
                    "format": "gtfs_schedule_zip",
                    "internal_revalidation": "passed",
                    "formal_validation": formal.status.value,
                },
            )
        finally:
            _remove(temporary)

    def _revalidate(
        self, archive: Path, expected: CoreSubset, is_cancelled: CancellationCheck
    ) -> None:
        workspace = archive.parent / f".{archive.name}.revalidation-{uuid4().hex}"
        database = self._database_factory(workspace)
        database.initialize()
        try:
            result = ImportFeed(
                database,
                ProjectMetadata("mini-gtfs-revalidation", "Mini-GTFS", ProjectStatus.READY),
                InputSource(archive, InputSourceKind.ARCHIVE),
                self._specification,
                job_id="mini-gtfs-revalidation",
                feed_id="mini-gtfs-revalidation",
            ).execute()
            if result.state is not JobState.READY or result.issue_count:
                raise ExportError(
                    "La reimportación interna Mini-GTFS no ha superado la validación."
                )
            _raise_if_cancelled(is_cancelled)
            with database.connection() as connection:
                actual = DuckDbCoreSubsetRepository(connection).core_subset_source()
            _assert_selection_matches(actual, expected)
        finally:
            _remove_tree(workspace)

    def _formal(self, archive: Path) -> FormalValidationResult:
        if self._formal_validator is None:
            return FormalValidationResult(FormalValidationStatus.NOT_AVAILABLE)
        return self._formal_validator(archive)

    @staticmethod
    def _temporary_zip(destination: Path) -> Path:
        parent = destination.parent.resolve()
        if not parent.is_dir():
            raise ExportError("La carpeta de destino Mini-GTFS no existe.")
        with NamedTemporaryFile(
            prefix=f".{destination.name}.", suffix=".tmp", dir=parent, delete=False
        ) as f:
            return Path(f.name)


def _database_for_revalidation(workspace: Path) -> ProjectDatabase:
    return ProjectDatabase(
        workspace / "project.duckdb",
        workspace / "temporary",
        settings=DatabaseSettings(memory_limit="128MB", max_temp_directory_size="128MB", threads=1),
    )


def _validate_tables(
    tables: tuple[MiniGtfsTable, ...], specification: ScheduleSpec, expected: CoreSubset
) -> None:
    names = [table.filename for table in tables]
    if len(names) != len(set(names)):
        raise ValueError("Un Mini-GTFS no puede contener tablas duplicadas.")
    if any(name not in specification.files for name in names):
        raise ValueError("Mini-GTFS contiene un archivo que no figura en el registro GTFS.")
    by_name = {table.filename: table for table in tables}
    required = {"agency.txt", "routes.txt", "trips.txt", "stops.txt", "stop_times.txt"}
    if expected.calendar_service_ids:
        required.add("calendar.txt")
    if expected.calendar_date_service_ids:
        required.add("calendar_dates.txt")
    if missing := required - by_name.keys():
        raise ValueError(
            f"Mini-GTFS no contiene las tablas core requeridas: {', '.join(sorted(missing))}."
        )
    empty = {name for name in required if not by_name[name].rows}
    if empty:
        raise ValueError(
            f"Mini-GTFS no puede publicar tablas core vacías: {', '.join(sorted(empty))}."
        )
    for table in tables:
        unknown_headers = set(table.headers) - specification.files[table.filename].fields.keys()
        if unknown_headers:
            headers = ", ".join(sorted(unknown_headers))
            raise ValueError(f"Cabeceras no registradas en {table.filename}: {headers}.")


def _write_zip(
    destination: Path, tables: tuple[MiniGtfsTable, ...], is_cancelled: CancellationCheck
) -> None:
    try:
        with ZipFile(destination, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
            for table in tables:
                _raise_if_cancelled(is_cancelled)
                info = ZipInfo(table.filename, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                archive.writestr(info, _csv_bytes(table, is_cancelled), compress_type=ZIP_DEFLATED)
    except OSError as error:
        raise ExportError("No se ha podido preparar el ZIP Mini-GTFS.") from error


def _csv_bytes(table: MiniGtfsTable, is_cancelled: CancellationCheck) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(table.headers)
    for row in _ordered_rows(table):
        _raise_if_cancelled(is_cancelled)
        writer.writerow("" if value is None else value for value in row)
    return output.getvalue().encode("utf-8")


def _ordered_rows(table: MiniGtfsTable) -> tuple[tuple[str | None, ...], ...]:
    """Ordena determinísticamente sin perder la secuencia de entidades GTFS."""
    indexed = tuple(enumerate(table.rows))
    positions = {header: index for index, header in enumerate(table.headers)}

    if table.filename == "stop_times.txt":
        return tuple(
            row
            for _, row in sorted(
                indexed,
                key=lambda item: (
                    _field_text(item[1], positions, "trip_id"),
                    _numeric_key(_field_text(item[1], positions, "stop_sequence")),
                    item[0],
                ),
            )
        )
    if table.filename == "shapes.txt":
        return tuple(
            row
            for _, row in sorted(
                indexed,
                key=lambda item: (
                    _field_text(item[1], positions, "shape_id"),
                    _numeric_key(_field_text(item[1], positions, "shape_pt_sequence")),
                    item[0],
                ),
            )
        )
    if table.filename == "frequencies.txt":
        return tuple(
            row
            for _, row in sorted(
                indexed,
                key=lambda item: (
                    _field_text(item[1], positions, "trip_id"),
                    _time_key(_field_text(item[1], positions, "start_time")),
                    item[0],
                ),
            )
        )
    if table.filename == "calendar_dates.txt":
        return tuple(
            row
            for _, row in sorted(
                indexed,
                key=lambda item: (
                    _field_text(item[1], positions, "service_id"),
                    _field_text(item[1], positions, "date"),
                    _numeric_key(_field_text(item[1], positions, "exception_type")),
                    item[0],
                ),
            )
        )
    return tuple(
        row
        for _, row in sorted(
            indexed,
            key=lambda item: (tuple(_text(value) for value in item[1]), item[0]),
        )
    )


def _field_text(row: tuple[str | None, ...], positions: dict[str, int], field_name: str) -> str:
    index = positions.get(field_name)
    return "" if index is None else _text(row[index])


def _text(value: str | None) -> str:
    return "" if value is None else value


def _numeric_key(value: str) -> tuple[int, int | str]:
    try:
        return (0, int(value))
    except ValueError:
        return (1, value)


def _time_key(value: str) -> tuple[int, int | str]:
    parts = value.split(":")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        hours, minutes, seconds = (int(part) for part in parts)
        return (0, hours * 3600 + minutes * 60 + seconds)
    return (1, value)


def _assert_selection_matches(source: CoreSubsetSource, expected: CoreSubset) -> None:
    if not (
        {route_id for route_id, _ in source.route_agencies} == expected.route_ids
        and {trip.trip_id for trip in source.trips} == expected.trip_ids
        and {stop.stop_id for stop in source.stops} == expected.stop_ids
        and source.calendar_service_ids == expected.calendar_service_ids
        and source.calendar_date_service_ids == expected.calendar_date_service_ids
        and source.agency_ids == expected.agency_ids
    ):
        raise ExportError("La reimportación Mini-GTFS no coincide con el cierre seleccionado.")


def _file_chunks(path: Path, is_cancelled: CancellationCheck) -> Iterable[bytes]:
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            _raise_if_cancelled(is_cancelled)
            yield chunk


def _raise_if_cancelled(is_cancelled: CancellationCheck) -> None:
    if is_cancelled():
        from gtfs_explorer.domain.exporting import ExportCancelled

        raise ExportCancelled("La exportación Mini-GTFS se ha cancelado.")


def _remove(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _remove_tree(path: Path) -> None:
    if not path.exists():
        return
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_file():
            child.unlink()
        else:
            child.rmdir()
    path.rmdir()
