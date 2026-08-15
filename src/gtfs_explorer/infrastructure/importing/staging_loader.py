"""Carga fiel y transaccional del origen GTFS en tablas de staging DuckDB."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from gtfs_explorer.domain.errors import ImportCancelled
from gtfs_explorer.domain.source import SourceManifest
from gtfs_explorer.domain.spec import ScheduleSpec
from gtfs_explorer.infrastructure.duckdb.database import DatabaseConnection, ProjectDatabase
from gtfs_explorer.infrastructure.importing.tabular_reader import TabularReader


@dataclass(frozen=True)
class StagingLoadResult:
    """Recuentos de las tablas conocidas que se han cargado en staging."""

    row_counts: dict[str, int]
    unknown_files: tuple[str, ...]


class StagingLoader:
    """Carga archivos inventariados sin interpretar ni normalizar sus valores."""

    def __init__(self, reader: TabularReader | None = None, batch_size: int = 1_000) -> None:
        if batch_size < 1:
            raise ValueError("El tamaño de lote debe ser mayor que cero.")
        self._reader = reader or TabularReader()
        self._batch_size = batch_size

    def load(
        self,
        database: ProjectDatabase,
        source_directory: Path,
        manifest: SourceManifest,
        schedule_spec: ScheduleSpec,
        *,
        is_cancelled: Callable[[], bool] = lambda: False,
    ) -> StagingLoadResult:
        """Sustituye el staging en una sola transacción o lo revierte íntegramente."""
        source_root = source_directory.resolve()
        row_counts: dict[str, int] = {}
        unknown_files: list[str] = []
        with database.connection() as connection:
            connection.execute("BEGIN TRANSACTION")
            try:
                self._reset_staging(connection, schedule_spec)
                for entry in manifest.entries:
                    self._raise_if_cancelled(is_cancelled)
                    filename = entry.original_name
                    file_spec = schedule_spec.files.get(filename)
                    table_name = _staging_table_name(filename) if file_spec is not None else None
                    connection.execute(
                        "INSERT INTO stg_source_inventory "
                        "(original_name, canonical_name, content_sha256, size_bytes, "
                        "known_to_schedule_spec, loaded_row_count, staging_table_name) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        [
                            filename,
                            entry.canonical_name,
                            entry.content_sha256,
                            entry.size_bytes,
                            file_spec is not None,
                            None,
                            table_name,
                        ],
                    )
                    if file_spec is None:
                        unknown_files.append(filename)
                        continue
                    assert table_name is not None
                    source_path = _source_path(source_root, filename)
                    count = self._load_file(
                        connection,
                        source_path,
                        filename,
                        tuple(file_spec.fields),
                        table_name,
                        is_cancelled,
                    )
                    connection.execute(
                        "UPDATE stg_source_inventory SET loaded_row_count = ? "
                        "WHERE original_name = ?",
                        [count, filename],
                    )
                    row_counts[filename] = count
                self._raise_if_cancelled(is_cancelled)
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
        return StagingLoadResult(row_counts, tuple(unknown_files))

    def _reset_staging(self, connection: DatabaseConnection, schedule_spec: ScheduleSpec) -> None:
        for filename in schedule_spec.files:
            connection.execute(
                f"DROP TABLE IF EXISTS {_quote_identifier(_staging_table_name(filename))}"
            )
        # DuckDB no permite reutilizar en la misma transacción una clave única eliminada.
        # Recrear el inventario conserva la sustitución atómica del staging completo.
        connection.execute("DROP TABLE stg_source_inventory")
        connection.execute(
            "CREATE TABLE stg_source_inventory ("
            "original_name VARCHAR PRIMARY KEY, "
            "canonical_name VARCHAR NOT NULL, "
            "content_sha256 VARCHAR NOT NULL, "
            "size_bytes BIGINT NOT NULL CHECK (size_bytes >= 0), "
            "known_to_schedule_spec BOOLEAN NOT NULL, "
            "loaded_row_count BIGINT, "
            "staging_table_name VARCHAR)"
        )

    def _load_file(
        self,
        connection: DatabaseConnection,
        source_path: Path,
        filename: str,
        expected_columns: tuple[str, ...],
        table_name: str,
        is_cancelled: Callable[[], bool],
    ) -> int:
        self._create_staging_table(connection, table_name, expected_columns)
        count = 0
        for batch in self._reader.iter_gtfs_batches(source_path, self._batch_size):
            self._raise_if_cancelled(is_cancelled)
            positions = _column_positions(batch.header, expected_columns)
            values = [
                _staging_row(
                    row.number, filename, batch.header, row.values, positions, expected_columns
                )
                for row in batch.rows
            ]
            self._raise_if_cancelled(is_cancelled)
            if values:
                placeholders = ", ".join("?" for _ in values[0])
                connection.executemany(
                    f"INSERT INTO {_quote_identifier(table_name)} VALUES ({placeholders})", values
                )
                count += len(values)
        return count

    @staticmethod
    def _create_staging_table(
        connection: DatabaseConnection, table_name: str, expected_columns: tuple[str, ...]
    ) -> None:
        column_definitions = [
            "source_row BIGINT NOT NULL",
            "source_filename VARCHAR NOT NULL",
            *(_quote_identifier(column) + " VARCHAR" for column in expected_columns),
            "extra_columns JSON NOT NULL",
        ]
        connection.execute(
            f"CREATE TABLE {_quote_identifier(table_name)} ({', '.join(column_definitions)})"
        )

    @staticmethod
    def _raise_if_cancelled(is_cancelled: Callable[[], bool]) -> None:
        if is_cancelled():
            raise ImportCancelled("Carga de staging cancelada.")


def _source_path(source_root: Path, filename: str) -> Path:
    path = (source_root / filename).resolve()
    if path.parent != source_root:
        raise ValueError("El archivo inventariado no pertenece al directorio fuente.")
    return path


def _staging_table_name(filename: str) -> str:
    return "stg_" + filename.removesuffix(".txt").casefold()


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _column_positions(
    header: tuple[str, ...], expected_columns: tuple[str, ...]
) -> dict[str, int | None]:
    positions: dict[str, int | None] = {}
    used: set[int] = set()
    for column in expected_columns:
        position = next(
            (
                index
                for index, header_column in enumerate(header)
                if header_column == column and index not in used
            ),
            None,
        )
        positions[column] = position
        if position is not None:
            used.add(position)
    return positions


def _staging_row(
    source_row: int,
    filename: str,
    header: tuple[str, ...],
    values: tuple[str, ...],
    positions: dict[str, int | None],
    expected_columns: tuple[str, ...],
) -> tuple[object, ...]:
    used_positions = {position for position in positions.values() if position is not None}
    extras = [
        {"column": column, "value": values[index] if index < len(values) else None}
        for index, column in enumerate(header)
        if index not in used_positions
    ]
    extras.extend({"column": None, "value": value} for value in values[len(header) :])
    return (
        source_row,
        filename,
        *(
            values[position] if position is not None and position < len(values) else None
            for position in positions.values()
        ),
        json.dumps(extras, ensure_ascii=False),
    )
