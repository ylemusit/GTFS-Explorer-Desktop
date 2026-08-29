"""Conexiones DuckDB por proyecto, migraciones y límites de recursos."""

from __future__ import annotations

import re
import shutil
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Sequence

import duckdb

_MIGRATION_NAME = re.compile(r"^(?P<version>[0-9]{3,})_[a-z0-9_]+\.sql$")
_MIGRATIONS_DIRECTORY = Path(__file__).with_name("migrations")


class DatabaseError(RuntimeError):
    """Error controlado al abrir o preparar una base de proyecto."""


class DatabaseCorruptionError(DatabaseError):
    """La ruta no contiene una base DuckDB legible."""


class DatabaseSchemaError(DatabaseError):
    """La base no pertenece al esquema gestionado por esta aplicación."""


class MigrationError(DatabaseError):
    """Una migración no pudo aplicarse y se ha revertido."""


class ConnectionThreadError(DatabaseError):
    """Una conexión se intentó usar desde un thread distinto de su propietario."""


@dataclass(frozen=True)
class DatabaseSettings:
    """Límites aplicados a cada conexión DuckDB del proyecto."""

    memory_limit: str = "50%"
    max_temp_directory_size: str = "1GB"
    threads: int = 1

    def __post_init__(self) -> None:
        if not self.memory_limit or not self.max_temp_directory_size:
            raise ValueError("Los límites de memoria y temporales deben estar definidos.")
        if self.threads < 1:
            raise ValueError("DuckDB debe usar al menos un thread.")


@dataclass(frozen=True)
class _Migration:
    version: int
    path: Path


class DatabaseConnection:
    """Conexión cerrable que rechaza el uso cruzado entre threads."""

    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self._connection = connection
        self._thread_id = threading.get_ident()
        self._closed = False

    def execute(
        self, query: str, parameters: Sequence[object] | None = None
    ) -> duckdb.DuckDBPyConnection:
        """Ejecuta una consulta en el thread que creó la conexión."""
        self._assert_usable()
        if parameters is None:
            return self._connection.execute(query)
        return self._connection.execute(query, parameters)

    def executemany(
        self, query: str, parameters: Sequence[Sequence[object]]
    ) -> duckdb.DuckDBPyConnection:
        """Ejecuta un lote de parámetros en el thread propietario."""
        self._assert_usable()
        return self._connection.executemany(query, parameters)

    def close(self) -> None:
        """Cierra la conexión una única vez desde su thread propietario."""
        self._assert_owner()
        if not self._closed:
            self._connection.close()
            self._closed = True

    def _assert_usable(self) -> None:
        self._assert_owner()
        if self._closed:
            raise DatabaseError("La conexión DuckDB ya está cerrada.")

    def _assert_owner(self) -> None:
        if threading.get_ident() != self._thread_id:
            raise ConnectionThreadError("Una conexión DuckDB no puede compartirse entre threads.")


class ProjectDatabase:
    """Inicializa una base DuckDB por proyecto y abre conexiones independientes."""

    def __init__(
        self,
        database_path: Path,
        temporary_directory: Path,
        *,
        settings: DatabaseSettings | None = None,
        migrations_directory: Path | None = None,
    ) -> None:
        self.database_path = database_path
        self.temporary_directory = temporary_directory
        self.settings = settings or DatabaseSettings()
        self._migrations_directory = migrations_directory or _MIGRATIONS_DIRECTORY

    @property
    def backup_path(self) -> Path:
        """Copia de seguridad más reciente tomada antes de una migración."""
        return self.database_path.with_suffix(self.database_path.suffix + ".pre-migration.bak")

    def validate_compatible(self) -> int:
        """Comprueba una base existente sin migrarla ni crear directorios de trabajo."""
        migrations = _load_migrations(self._migrations_directory)
        connection = self._open_connection()
        try:
            current_version = _current_schema_version(connection)
        finally:
            connection.close()
        if current_version != migrations[-1].version:
            raise DatabaseSchemaError(
                "La versión del esquema DuckDB no es compatible con esta apertura."
            )
        return current_version

    def initialize(self) -> int:
        """Aplica las migraciones pendientes de forma transaccional y devuelve la versión."""
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.temporary_directory.mkdir(parents=True, exist_ok=True)
        existed_before_opening = self.database_path.exists()
        migrations = _load_migrations(self._migrations_directory)

        connection = self._open_connection()
        try:
            current_version = _current_schema_version(connection)
            pending = [migration for migration in migrations if migration.version > current_version]
        finally:
            connection.close()

        if not pending:
            return current_version
        if existed_before_opening:
            shutil.copy2(self.database_path, self.backup_path)

        connection = self._open_connection()
        try:
            _apply_migrations(connection, pending)
            return pending[-1].version
        finally:
            connection.close()

    def connect(self) -> DatabaseConnection:
        """Inicializa la base y entrega una conexión propiedad del thread actual."""
        self.initialize()
        return DatabaseConnection(self._open_connection())

    @contextmanager
    def connection(self) -> Iterator[DatabaseConnection]:
        """Abre y cierra una conexión, incluso cuando la operación falle."""
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    def _open_connection(self) -> duckdb.DuckDBPyConnection:
        try:
            connection = duckdb.connect(str(self.database_path))
            _configure_connection(connection, self.temporary_directory, self.settings)
            return connection
        except duckdb.Error as error:
            if "not a valid duckdb database" in str(error).lower():
                raise DatabaseCorruptionError(
                    "La base DuckDB del proyecto está corrupta."
                ) from error
            raise DatabaseError("No se ha podido abrir la base DuckDB del proyecto.") from error


def _configure_connection(
    connection: duckdb.DuckDBPyConnection,
    temporary_directory: Path,
    settings: DatabaseSettings,
) -> None:
    connection.execute(f"SET temp_directory = {_sql_string(str(temporary_directory.resolve()))}")
    connection.execute(f"SET memory_limit = {_sql_string(settings.memory_limit)}")
    connection.execute(
        f"SET max_temp_directory_size = {_sql_string(settings.max_temp_directory_size)}"
    )
    connection.execute("SET threads = ?", [settings.threads])


def _current_schema_version(connection: duckdb.DuckDBPyConnection) -> int:
    tables = connection.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()
    table_names = {str(row[0]) for row in tables}
    if "schema_migrations" not in table_names:
        if table_names:
            raise DatabaseSchemaError("La base no contiene el control de migraciones esperado.")
        return 0
    if "schema_metadata" not in table_names:
        raise DatabaseSchemaError("La base no contiene la versión de esquema esperada.")
    rows = connection.execute("SELECT schema_version FROM schema_metadata").fetchall()
    if len(rows) != 1 or not isinstance(rows[0][0], int):
        raise DatabaseSchemaError("La versión de esquema almacenada no es válida.")
    migration_version = connection.execute(
        "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
    ).fetchone()
    if migration_version is None or rows[0][0] != migration_version[0]:
        raise DatabaseSchemaError(
            "El historial de migraciones no coincide con la versión del esquema."
        )
    return rows[0][0]


def _apply_migrations(connection: duckdb.DuckDBPyConnection, migrations: list[_Migration]) -> None:
    try:
        connection.execute("BEGIN TRANSACTION")
        for migration in migrations:
            connection.execute(migration.path.read_text(encoding="utf-8"))
            now = datetime.now(timezone.utc)
            connection.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                [migration.version, now],
            )
            metadata_columns = {
                str(row[0])
                for row in connection.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'main' AND table_name = 'schema_metadata'"
                ).fetchall()
            }
            if "updated_at" in metadata_columns:
                connection.execute(
                    "UPDATE schema_metadata SET schema_version = ?, updated_at = ?",
                    [migration.version, now],
                )
            else:
                connection.execute(
                    "UPDATE schema_metadata SET schema_version = ?", [migration.version]
                )
        connection.execute("COMMIT")
    except (OSError, duckdb.Error) as error:
        try:
            connection.execute("ROLLBACK")
        except duckdb.Error:
            pass
        raise MigrationError("La migración DuckDB ha fallado y se ha revertido.") from error


def _load_migrations(directory: Path) -> list[_Migration]:
    migrations: list[_Migration] = []
    for path in sorted(directory.glob("*.sql")):
        match = _MIGRATION_NAME.fullmatch(path.name)
        if match is None:
            raise MigrationError(f"Nombre de migración inválido: {path.name}")
        migrations.append(_Migration(version=int(match["version"]), path=path))
    if not migrations:
        raise MigrationError("No hay migraciones DuckDB disponibles.")
    versions = [migration.version for migration in migrations]
    if len(versions) != len(set(versions)):
        raise MigrationError("Las versiones de migración DuckDB deben ser únicas.")
    return migrations


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
