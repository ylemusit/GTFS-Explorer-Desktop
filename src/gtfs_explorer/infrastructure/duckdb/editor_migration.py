"""Migración reversible del almacenamiento de edición de 0.1.0 a 0.2.0."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from gtfs_explorer.infrastructure.duckdb.database import ProjectDatabase
from gtfs_explorer.infrastructure.duckdb.repositories import DuckDbUnitOfWork
from gtfs_explorer.infrastructure.duckdb.repositories.editor import DuckDbEditorRepository


class EditorMigrationError(RuntimeError):
    """La migración del borrador no pudo completarse y se ha revertido."""


@dataclass(frozen=True)
class EditorMigrationResult:
    """Resultado observable de preparar el almacenamiento de edición."""

    migrated: bool
    backup_path: Path | None = None


_EDITOR_STORAGE_TABLES = frozenset(
    {
        "editor_schema",
        "editor_state",
        "editor_history",
        "editor_deltas",
        "editor_route_state",
        "editor_revisions",
        "editor_revision_deltas",
    }
)
_EDITOR_SCHEMA_VERSION = 2


def migrate_editor_database(database: ProjectDatabase) -> EditorMigrationResult:
    """Crea o completa el almacenamiento 0.2.0 sin mutar el GTFS original.

    La copia se toma antes de abrir la transacción de DDL. DuckDB revierte la
    transacción si falla la preparación; el backup dedicado cubre además un
    corte o una implementación de DDL que no pueda revertirse completamente.
    """
    if _editor_storage_is_ready(database):
        return EditorMigrationResult(False)

    backup_path = database.database_path.with_suffix(
        database.database_path.suffix + ".editor-pre-migration.bak"
    )
    try:
        shutil.copy2(database.database_path, backup_path)
        with DuckDbUnitOfWork(database) as unit_of_work:
            DuckDbEditorRepository(unit_of_work.connection).create_or_recover()
    except Exception as error:
        try:
            shutil.copy2(backup_path, database.database_path)
        except OSError as restore_error:
            raise EditorMigrationError(
                "La migración del editor falló y tampoco se pudo restaurar el backup."
            ) from restore_error
        raise EditorMigrationError(
            "La migración del editor falló y el proyecto se ha restaurado."
        ) from error
    return EditorMigrationResult(True, backup_path)


def _editor_storage_is_ready(database: ProjectDatabase) -> bool:
    with database.connection() as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
        }
        if not _EDITOR_STORAGE_TABLES <= tables:
            return False
        revision_columns = {
            str(row[0])
            for row in connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'main' AND table_name = 'editor_revisions'"
            ).fetchall()
        }
        schema_row = connection.execute(
            "SELECT schema_version FROM editor_schema WHERE schema_id = 1"
        ).fetchone()
    return (
        "entities_json" not in revision_columns
        and "delta_reference" in revision_columns
        and "delta_count" in revision_columns
        and schema_row is not None
        and int(schema_row[0]) == _EDITOR_SCHEMA_VERSION
    )
