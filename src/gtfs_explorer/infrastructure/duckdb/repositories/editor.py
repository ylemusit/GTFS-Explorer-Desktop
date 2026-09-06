"""Persistencia transaccional del borrador visual sobre el feed original."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from gtfs_explorer.domain.changesets import (
    EditorCommand,
    EntityKey,
    HistoryEvent,
    RouteWorkspaceState,
    WorkingCopy,
    _command_from_json,
    _command_to_json,
    _json_prepare,
    _json_restore,
)
from gtfs_explorer.infrastructure.duckdb.database import DatabaseConnection

_EDITOR_SCHEMA_VERSION = 2
_WORKSPACE_STATE_VERSION = 1
_REVISION_DELTA_TABLE = "editor_revision_deltas"

_EDITOR_TABLES = (
    "gtfs_agency",
    "gtfs_stops",
    "gtfs_routes",
    "gtfs_trips",
    "gtfs_stop_times",
    "gtfs_calendar",
    "gtfs_calendar_dates",
    "gtfs_shapes",
    "gtfs_frequencies",
    "gtfs_transfers",
    "gtfs_feed_info",
    "gtfs_attributions",
)

# Las tablas sin una clave GTFS propia usan source_row como identidad de edición.
# No es un ID publicado: es la identidad estable de la fila original dentro del feed.
_ENTITY_COLUMNS = {
    "gtfs_agency": "agency_id",
    "gtfs_stops": "stop_id",
    "gtfs_routes": "route_id",
    "gtfs_trips": "trip_id",
    "gtfs_calendar": "service_id",
    "gtfs_attributions": "attribution_id",
}


class DuckDbEditorRepository:
    """Carga el original y guarda únicamente deltas con clave tabla+entidad."""

    def __init__(self, connection: DatabaseConnection) -> None:
        self._connection = connection
        self._ensure_schema()

    def create_or_recover(self) -> WorkingCopy:
        original = self._load_original_entities()
        state = self._connection.execute(
            "SELECT changeset_id, base_revision_id, cursor, commands_json, working_revision_id, "
            "workspace_state_version "
            "FROM editor_state WHERE state_id = 1"
        ).fetchone()
        base_revision_id = (
            str(state[4] or state[1])
            if state is not None and (state[4] or state[1])
            else "original"
        )
        base_entities = (
            original
            if base_revision_id == "original"
            else self._load_revision_entities(base_revision_id)
        )
        if base_revision_id == "original":
            # El cargador acaba de crear este snapshot y no lo comparte con
            # ningún llamador; evita una segunda copia profunda de todo el feed.
            working = WorkingCopy(original, clone_original=False)
        else:
            working = WorkingCopy(
                original,
                base_revision_id=base_revision_id,
                base_entities=base_entities,
            )

        commands: list[EditorCommand] = []
        cursor = 0
        if state:
            raw_commands = _json_restore(json.loads(str(state[3])))
            if not isinstance(raw_commands, list):
                raise ValueError("El historial persistido del editor no es una lista.")
            commands = [_command_from_json(item) for item in raw_commands]
            cursor = int(state[2])
            if cursor < 0 or cursor > len(commands):
                raise ValueError("El cursor persistido del editor no es válido.")
            for command in commands[:cursor]:
                working._assert_preconditions(command, forward=True)
                working._apply_state(command, forward=True)
            working.changeset.changeset_id = str(state[0])

        working.changeset.commands = commands
        working.changeset._cursor = cursor
        history = self._connection.execute(
            "SELECT action, command_id, created_at FROM editor_history ORDER BY rowid"
        ).fetchall()
        working.changeset.history = [
            HistoryEvent(str(action), str(command_id), str(created_at))
            for action, command_id, created_at in history
        ]

        delta_rows = self._connection.execute(
            "SELECT table_name, entity_id, payload, deleted FROM editor_deltas "
            "ORDER BY table_name, entity_id"
        ).fetchall()
        for table_name, entity_id, payload, deleted in delta_rows:
            key = (str(table_name), str(entity_id))
            value = None if bool(deleted) else _json_restore(json.loads(str(payload)))
            # El materializado es un cache recuperable, no otra fuente de verdad.
            # Comparar solo las filas delta evita copiar el feed completo al abrir.
            if working.get(key) != value:
                raise ValueError("El borrador persistido no coincide con su historial de comandos.")
        route_state_rows = self._connection.execute(
            "SELECT route_id, visible, active, editable, locked, dimmed "
            "FROM editor_route_state ORDER BY route_id"
        ).fetchall()
        for route_id, visible, active, editable, locked, dimmed in route_state_rows:
            working._route_states[str(route_id)] = RouteWorkspaceState(
                str(route_id),
                bool(visible),
                bool(active),
                bool(editable),
                bool(locked),
                bool(dimmed),
            )
        workspace_version = int(state[5] or 0) if state is not None else 0
        if workspace_version < _WORKSPACE_STATE_VERSION:
            self._migrate_legacy_route_workspace(working, had_persisted_rows=bool(route_state_rows))
            working._accept_route_workspace_state()
            self._connection.execute(
                "UPDATE editor_state SET workspace_state_version = ? WHERE state_id = 1",
                [_WORKSPACE_STATE_VERSION],
            )
        working._accept_route_workspace_state()
        return working

    def _migrate_legacy_route_workspace(
        self, working: WorkingCopy, *, had_persisted_rows: bool
    ) -> None:
        """Normaliza una única vez el estado antiguo que hacía visibles todas las rutas."""
        route_ids = sorted(working.entity_index.routes_by_id)
        states = working._route_states
        if not route_ids:
            return
        meaningful = any(
            state.locked or state.dimmed or state.editable for state in states.values()
        )
        visible_count = sum(
            states.get(route_id, RouteWorkspaceState(route_id)).visible for route_id in route_ids
        )
        active_ids = [
            route_id
            for route_id in route_ids
            if states.get(route_id, RouteWorkspaceState(route_id)).active
        ]
        uniform_legacy = (
            not meaningful
            and len(active_ids) <= 1
            and (not had_persisted_rows or visible_count >= max(1, len(route_ids) - 1))
        )
        if not uniform_legacy:
            return
        selected = active_ids[0] if active_ids else route_ids[0]
        for route_id in route_ids:
            current = states.get(route_id, RouteWorkspaceState(route_id))
            states[route_id] = replace(
                current,
                visible=route_id == selected,
                active=route_id == selected and current.active,
            )
        # El estado se escribe aquí, dentro del UOW que abrió el proyecto, para
        # que la migración sea visible y no vuelva a ejecutarse en el siguiente arranque.
        self.persist_route_workspace_states(tuple(states.values()))

    def persist(self, working: WorkingCopy) -> None:
        """Actualiza el materializado y el historial dentro de la transacción del UOW."""
        original = working.base_entities
        current = working.entities
        deltas: list[tuple[str, str, str | None, bool]] = []
        for key in sorted(set(original) | set(current)):
            original_value = original.get(key)
            current_value = current.get(key)
            if original_value == current_value:
                continue
            table_name, entity_id = key
            if current_value is None:
                deltas.append((table_name, entity_id, None, True))
            else:
                deltas.append((table_name, entity_id, _json_dumps(current_value), False))

        # DuckDB puede conservar índices de una fila borrada hasta el commit.
        # Reemplazar la tabla materializada evita la secuencia DELETE+INSERT de la
        # misma clave cuando undo y redo ocurren dentro del mismo UOW.
        self._connection.execute("DROP TABLE IF EXISTS editor_deltas_next")
        self._connection.execute(
            "CREATE TABLE editor_deltas_next ("
            "table_name VARCHAR NOT NULL, entity_id VARCHAR NOT NULL, payload JSON, "
            "deleted BOOLEAN NOT NULL, PRIMARY KEY (table_name, entity_id))"
        )
        if deltas:
            self._connection.executemany(
                "INSERT INTO editor_deltas_next (table_name, entity_id, payload, deleted) "
                "VALUES (?, ?, ?, ?)",
                deltas,
            )
        self._connection.execute("DROP TABLE editor_deltas")
        self._connection.execute("ALTER TABLE editor_deltas_next RENAME TO editor_deltas")

        commands = [_command_to_json(command) for command in working.changeset.commands]
        self._connection.execute("DELETE FROM editor_history")
        for event in working.changeset.history:
            self._connection.execute(
                "INSERT INTO editor_history VALUES (?, ?, ?)",
                [event.action, event.command_id, event.created_at],
            )
        self._connection.execute(
            "UPDATE editor_state SET changeset_id = ?, base_revision_id = ?, cursor = ?, "
            "commands_json = ?, working_revision_id = ?, workspace_state_version = ? "
            "WHERE state_id = 1",
            [
                working.changeset.changeset_id,
                working.changeset.base_revision_id,
                working.changeset._cursor,
                _json_dumps(commands),
                working.base_revision_id,
                _WORKSPACE_STATE_VERSION,
            ],
        )
        self._connection.execute("DROP TABLE IF EXISTS editor_route_state_next")
        self._connection.execute(
            "CREATE TABLE editor_route_state_next ("
            "route_id VARCHAR PRIMARY KEY, visible BOOLEAN NOT NULL, active BOOLEAN NOT NULL, "
            "editable BOOLEAN NOT NULL, locked BOOLEAN NOT NULL, dimmed BOOLEAN NOT NULL)"
        )
        states = [
            (
                state.route_id,
                state.visible,
                state.active,
                state.editable,
                state.locked,
                state.dimmed,
            )
            for state in sorted(working.route_states.values(), key=lambda item: item.route_id)
        ]
        if states:
            self._connection.executemany(
                "INSERT INTO editor_route_state_next VALUES (?, ?, ?, ?, ?, ?)", states
            )
        self._connection.execute("DROP TABLE editor_route_state")
        self._connection.execute("ALTER TABLE editor_route_state_next RENAME TO editor_route_state")

    def persist_route_workspace_states(self, states: tuple[RouteWorkspaceState, ...]) -> None:
        """Persiste únicamente estados visuales de ruta mediante UPSERT.

        Esta ruta no toca la working copy ni las tablas de deltas, historial o
        estado del ChangeSet. El llamador incluye también las rutas que hayan
        perdido el flag ``active`` cuando la activación es exclusiva.
        """
        if not states:
            return
        self._connection.executemany(
            "INSERT INTO editor_route_state "
            "(route_id, visible, active, editable, locked, dimmed) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (route_id) DO UPDATE SET "
            "visible = excluded.visible, active = excluded.active, "
            "editable = excluded.editable, locked = excluded.locked, dimmed = excluded.dimmed",
            [
                (
                    state.route_id,
                    state.visible,
                    state.active,
                    state.editable,
                    state.locked,
                    state.dimmed,
                )
                for state in states
            ],
        )

    def discard_working_revision(self, working: WorkingCopy) -> None:
        """Descarta el borrador sin materializar ni comparar sus entidades.

        El objetivo del discard es conocido: cero deltas e historial, con la
        metadata y el workspace de la base ya representados por ``working``.
        """
        self._connection.execute("DELETE FROM editor_deltas")
        self._connection.execute("DELETE FROM editor_history")
        self._connection.execute(
            "UPDATE editor_state SET changeset_id = ?, base_revision_id = ?, cursor = 0, "
            "commands_json = ?, working_revision_id = ?, workspace_state_version = ? "
            "WHERE state_id = 1",
            [
                working.changeset.changeset_id,
                working.changeset.base_revision_id,
                _json_dumps([]),
                working.base_revision_id,
                _WORKSPACE_STATE_VERSION,
            ],
        )
        states = tuple(sorted(working.route_states.values(), key=lambda item: item.route_id))
        self.persist_route_workspace_states(states)

    def publish_revision(self, working: WorkingCopy, *, revision_id: str) -> None:
        """Persiste metadatos y deltas inmutables, y reinicia el borrador sobre ellos."""
        if not revision_id or revision_id == "draft":
            raise ValueError("Una revisión confirmada necesita un identificador válido.")
        if self._connection.execute(
            "SELECT 1 FROM editor_revisions WHERE revision_id = ?", [revision_id]
        ).fetchone():
            raise ValueError(f"La revisión ya existe: {revision_id}.")
        impact = [
            command.impact
            for command in working.changeset.active_commands
            if command.impact is not None
        ]
        deltas = _calculate_deltas(working.base_entities, working.entities)
        self._connection.execute(
            "INSERT INTO editor_revisions "
            "(revision_id, parent_revision_id, changeset_id, created_at, impact_json, "
            "delta_reference, delta_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                revision_id,
                working.base_revision_id,
                working.changeset.changeset_id,
                datetime.now(timezone.utc).isoformat(),
                _json_dumps(impact),
                revision_id,
                len(deltas),
            ],
        )
        if deltas:
            self._connection.executemany(
                f"INSERT INTO {_REVISION_DELTA_TABLE} "
                "(revision_id, table_name, entity_id, payload, deleted) VALUES (?, ?, ?, ?, ?)",
                [(revision_id, *delta) for delta in deltas],
            )
        working.promote_revision(revision_id)
        self.persist(working)

    def revisions(self) -> tuple[tuple[str, str | None, str], ...]:
        """Devuelve el historial de revisiones confirmadas, más reciente primero."""
        rows = self._connection.execute(
            "SELECT revision_id, parent_revision_id, created_at "
            "FROM editor_revisions ORDER BY created_at DESC, revision_id DESC"
        ).fetchall()
        return tuple(
            (
                str(row[0]),
                None if row[1] is None else str(row[1]),
                str(row[2]),
            )
            for row in rows
        )

    def _load_revision_entities(self, revision_id: str) -> dict[EntityKey, dict[str, Any]]:
        if revision_id == "original":
            return self._load_original_entities()
        chain: list[str] = []
        seen: set[str] = set()
        current = revision_id
        while current != "original":
            if current in seen:
                raise ValueError("La cadena de revisiones contiene un ciclo.")
            seen.add(current)
            row = self._connection.execute(
                "SELECT parent_revision_id FROM editor_revisions WHERE revision_id = ?", [current]
            ).fetchone()
            if row is None:
                raise ValueError(f"No existe la revisión base del borrador: {revision_id}.")
            chain.append(current)
            current = str(row[0]) if row[0] else "original"

        entities = self._load_original_entities()
        for chain_revision_id in reversed(chain):
            rows = self._connection.execute(
                f"SELECT table_name, entity_id, payload, deleted FROM {_REVISION_DELTA_TABLE} "
                "WHERE revision_id = ? ORDER BY table_name, entity_id",
                [chain_revision_id],
            ).fetchall()
            for table_name, entity_id, payload, deleted in rows:
                key = (str(table_name), str(entity_id))
                value = None if bool(deleted) else _json_restore(json.loads(str(payload)))
                if value is not None and not isinstance(value, dict):
                    raise ValueError("El delta de revisión no contiene una entidad válida.")
                if value is None:
                    entities.pop(key, None)
                else:
                    entities[key] = value
        return entities

    def _load_original_entities(self) -> dict[EntityKey, dict[str, Any]]:
        result: dict[EntityKey, dict[str, Any]] = {}
        available = {
            str(row[0])
            for row in self._connection.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
        }
        for table_name in _EDITOR_TABLES:
            if table_name not in available:
                continue
            columns = [
                str(row[0])
                for row in self._connection.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'main' AND table_name = ? ORDER BY ordinal_position",
                    [table_name],
                ).fetchall()
            ]
            for row in self._connection.execute(f"SELECT * FROM {table_name}").fetchall():
                payload = dict(zip(columns, row, strict=True))
                entity_id = _entity_id(table_name, payload)
                result[(table_name, entity_id)] = payload
        return result

    def _ensure_schema(self) -> None:
        legacy_revision_columns = self._table_columns("editor_revisions")
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS editor_schema ("
            "schema_id INTEGER PRIMARY KEY, schema_version INTEGER NOT NULL, "
            "updated_at TIMESTAMP NOT NULL)"
        )
        schema_row = self._connection.execute(
            "SELECT schema_version FROM editor_schema WHERE schema_id = 1"
        ).fetchone()
        if schema_row is not None and int(schema_row[0]) > _EDITOR_SCHEMA_VERSION:
            raise ValueError("La versión del almacenamiento editorial no es compatible.")
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS editor_state ("
            "state_id INTEGER PRIMARY KEY, changeset_id VARCHAR NOT NULL, "
            "base_revision_id VARCHAR NOT NULL, cursor INTEGER NOT NULL, "
            "commands_json JSON NOT NULL, working_revision_id VARCHAR NOT NULL DEFAULT 'original', "
            "workspace_state_version INTEGER NOT NULL DEFAULT 0)"
        )
        self._connection.execute(
            "ALTER TABLE editor_state ADD COLUMN IF NOT EXISTS working_revision_id VARCHAR"
        )
        self._connection.execute(
            "ALTER TABLE editor_state ADD COLUMN IF NOT EXISTS workspace_state_version INTEGER"
        )
        self._connection.execute(
            "UPDATE editor_state SET working_revision_id = 'original' "
            "WHERE working_revision_id IS NULL"
        )
        self._connection.execute(
            "UPDATE editor_state SET workspace_state_version = 0 "
            "WHERE workspace_state_version IS NULL"
        )
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS editor_history ("
            "action VARCHAR NOT NULL, command_id VARCHAR NOT NULL, created_at VARCHAR NOT NULL)"
        )
        self._connection.execute(
            "INSERT INTO editor_state "
            "(state_id, changeset_id, base_revision_id, cursor, commands_json, "
            "working_revision_id, workspace_state_version) "
            "VALUES (1, 'original', 'original', 0, '[]', 'original', 0) "
            "ON CONFLICT (state_id) DO NOTHING"
        )
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS editor_route_state ("
            "route_id VARCHAR PRIMARY KEY, visible BOOLEAN NOT NULL, active BOOLEAN NOT NULL, "
            "editable BOOLEAN NOT NULL, locked BOOLEAN NOT NULL, dimmed BOOLEAN NOT NULL)"
        )

        self._connection.execute(
            f"CREATE TABLE IF NOT EXISTS {_REVISION_DELTA_TABLE} ("
            "revision_id VARCHAR NOT NULL, table_name VARCHAR NOT NULL, "
            "entity_id VARCHAR NOT NULL, "
            "payload JSON, deleted BOOLEAN NOT NULL, "
            "PRIMARY KEY (revision_id, table_name, entity_id))"
        )

        if "entities_json" in legacy_revision_columns:
            self._migrate_legacy_revision_table()
        else:
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS editor_revisions ("
                "revision_id VARCHAR PRIMARY KEY, parent_revision_id VARCHAR, "
                "changeset_id VARCHAR NOT NULL, created_at VARCHAR NOT NULL, "
                "impact_json JSON NOT NULL, delta_reference VARCHAR NOT NULL, "
                "delta_count INTEGER NOT NULL DEFAULT 0)"
            )

        revision_columns = self._table_columns("editor_revisions")
        if "delta_reference" not in revision_columns:
            self._connection.execute(
                "ALTER TABLE editor_revisions ADD COLUMN delta_reference VARCHAR"
            )
            self._connection.execute(
                "UPDATE editor_revisions SET delta_reference = revision_id "
                "WHERE delta_reference IS NULL"
            )
        if "delta_count" not in revision_columns:
            self._connection.execute("ALTER TABLE editor_revisions ADD COLUMN delta_count INTEGER")
            self._connection.execute(
                "UPDATE editor_revisions SET delta_count = ("
                f"SELECT count(*) FROM {_REVISION_DELTA_TABLE} d "
                "WHERE d.revision_id = editor_revisions.revision_id) "
                "WHERE delta_count IS NULL"
            )

        columns = {
            str(row[0])
            for row in self._connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'main' AND table_name = 'editor_deltas'"
            ).fetchall()
        }
        if not columns:
            self._create_delta_table()
        elif "table_name" not in columns:
            # Migración local del primer slice: cada delta antiguo era una parada.
            self._connection.execute(
                "CREATE TABLE editor_deltas_v2 ("
                "table_name VARCHAR NOT NULL, entity_id VARCHAR NOT NULL, payload JSON, "
                "deleted BOOLEAN NOT NULL, PRIMARY KEY (table_name, entity_id))"
            )
            self._connection.execute(
                "INSERT INTO editor_deltas_v2 (table_name, entity_id, payload, deleted) "
                "SELECT 'gtfs_stops', entity_id, payload, deleted FROM editor_deltas"
            )
            self._connection.execute("DROP TABLE editor_deltas")
            self._connection.execute("ALTER TABLE editor_deltas_v2 RENAME TO editor_deltas")

        self._connection.execute(
            "INSERT INTO editor_schema (schema_id, schema_version, updated_at) VALUES (1, ?, ?) "
            "ON CONFLICT (schema_id) DO UPDATE SET schema_version = excluded.schema_version, "
            "updated_at = excluded.updated_at",
            [_EDITOR_SCHEMA_VERSION, datetime.now(timezone.utc)],
        )

    def _migrate_legacy_revision_table(self) -> None:
        """Convierte revisiones experimentales con snapshot a filas de delta.

        ``working-0`` era solo una copia del original; se elimina sin leer su
        JSON. El resto de revisiones se transforma dentro de DuckDB mediante
        ``UNNEST(json_extract(...))`` y conserva el contenido por entidad, nunca el documento
        monolítico. Las filas que faltan frente al padre se registran como
        eliminaciones para mantener la semántica de la revisión completa.
        """
        self._connection.execute("ALTER TABLE editor_revisions RENAME TO editor_revisions_legacy")
        self._connection.execute(
            "CREATE TABLE editor_revisions ("
            "revision_id VARCHAR PRIMARY KEY, parent_revision_id VARCHAR, "
            "changeset_id VARCHAR NOT NULL, created_at VARCHAR NOT NULL, "
            "impact_json JSON NOT NULL, delta_reference VARCHAR NOT NULL, "
            "delta_count INTEGER NOT NULL DEFAULT 0)"
        )
        legacy_rows = self._connection.execute(
            "SELECT revision_id, parent_revision_id, changeset_id, created_at, impact_json "
            "FROM editor_revisions_legacy ORDER BY created_at, revision_id"
        ).fetchall()
        legacy_ids = {str(row[0]) for row in legacy_rows}
        for row in legacy_rows:
            revision_id = str(row[0])
            if revision_id == "working-0" and row[1] is None:
                continue
            parent = str(row[1]) if row[1] else "original"
            if parent == "working-0" or parent not in legacy_ids:
                parent = "original"
            self._copy_legacy_snapshot(revision_id, parent, parent in legacy_ids)
            delta_count = self._connection.execute(
                f"SELECT count(*) FROM {_REVISION_DELTA_TABLE} WHERE revision_id = ?",
                [revision_id],
            ).fetchone()
            assert delta_count is not None
            self._connection.execute(
                "INSERT INTO editor_revisions "
                "(revision_id, parent_revision_id, changeset_id, created_at, impact_json, "
                "delta_reference, delta_count) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    revision_id,
                    parent,
                    str(row[2]),
                    str(row[3]),
                    str(row[4]),
                    revision_id,
                    int(delta_count[0]),
                ],
            )

        self._connection.execute(
            "UPDATE editor_state SET base_revision_id = CASE base_revision_id "
            "WHEN 'working-0' THEN 'original' ELSE base_revision_id END, "
            "working_revision_id = CASE working_revision_id "
            "WHEN 'working-0' THEN 'original' ELSE working_revision_id END "
            "WHERE state_id = 1"
        )
        self._connection.execute("DROP TABLE editor_revisions_legacy")

    def _copy_legacy_snapshot(
        self, revision_id: str, parent_revision_id: str, parent_is_legacy: bool
    ) -> None:
        self._connection.execute(
            f"INSERT INTO {_REVISION_DELTA_TABLE} "
            "(revision_id, table_name, entity_id, payload, deleted) "
            "SELECT ?, json_extract_string(item.value, '$.table'), "
            "json_extract_string(item.value, '$.id'), json_extract(item.value, '$.payload'), FALSE "
            "FROM editor_revisions_legacy legacy, "
            "UNNEST(json_extract(legacy.entities_json, '$[*]')) AS item(value) "
            "WHERE legacy.revision_id = ?",
            [revision_id, revision_id],
        )
        if parent_is_legacy:
            self._connection.execute(
                f"INSERT INTO {_REVISION_DELTA_TABLE} "
                "(revision_id, table_name, entity_id, payload, deleted) "
                "SELECT ?, json_extract_string(parent_item.value, '$.table'), "
                "json_extract_string(parent_item.value, '$.id'), NULL, TRUE "
                "FROM editor_revisions_legacy parent_revision, "
                "UNNEST(json_extract(parent_revision.entities_json, '$[*]')) "
                "AS parent_item(value) "
                "WHERE parent_revision.revision_id = ? AND NOT EXISTS ("
                "SELECT 1 FROM editor_revisions_legacy current_revision, "
                "UNNEST(json_extract(current_revision.entities_json, '$[*]')) "
                "AS current_item(value) "
                "WHERE current_revision.revision_id = ? "
                "AND json_extract_string(current_item.value, '$.table') = "
                "json_extract_string(parent_item.value, '$.table') "
                "AND json_extract_string(current_item.value, '$.id') = "
                "json_extract_string(parent_item.value, '$.id'))",
                [revision_id, parent_revision_id, revision_id],
            )
        else:
            for table_name in _EDITOR_TABLES:
                key_expression = _legacy_entity_key_expression(table_name)
                self._connection.execute(
                    f"INSERT INTO {_REVISION_DELTA_TABLE} "
                    "(revision_id, table_name, entity_id, payload, deleted) "
                    f"SELECT ?, '{table_name}', CAST({key_expression} AS VARCHAR), NULL, TRUE "
                    f"FROM {table_name} original_row WHERE {key_expression} IS NOT NULL "
                    "AND NOT EXISTS (SELECT 1 FROM "
                    f"{_REVISION_DELTA_TABLE} existing WHERE existing.revision_id = ? "
                    "AND existing.table_name = ? "
                    "AND existing.entity_id = CAST(" + key_expression + " AS VARCHAR))",
                    [revision_id, revision_id, table_name],
                )

    def _table_columns(self, table_name: str) -> set[str]:
        return {
            str(row[0])
            for row in self._connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'main' AND table_name = ?",
                [table_name],
            ).fetchall()
        }

    def _create_delta_table(self) -> None:
        self._connection.execute(
            "CREATE TABLE editor_deltas ("
            "table_name VARCHAR NOT NULL, entity_id VARCHAR NOT NULL, payload JSON, "
            "deleted BOOLEAN NOT NULL, PRIMARY KEY (table_name, entity_id))"
        )


def _calculate_deltas(
    base: dict[EntityKey, dict[str, Any]], current: dict[EntityKey, dict[str, Any]]
) -> list[tuple[str, str, str | None, bool]]:
    deltas: list[tuple[str, str, str | None, bool]] = []
    for key in sorted(set(base) | set(current)):
        base_value = base.get(key)
        current_value = current.get(key)
        if base_value == current_value:
            continue
        table_name, entity_id = key
        if current_value is None:
            deltas.append((table_name, entity_id, None, True))
        else:
            deltas.append((table_name, entity_id, _json_dumps(current_value), False))
    return deltas


def _legacy_entity_key_expression(table_name: str) -> str:
    column = _ENTITY_COLUMNS.get(table_name)
    if column is None:
        return "original_row.source_row"
    return (
        f"COALESCE(CAST(original_row.{column} AS VARCHAR), "
        "CAST(original_row.source_row AS VARCHAR))"
    )


def _entity_id(table_name: str, payload: dict[str, Any]) -> str:
    # Las excepciones de calendario son una relación service_id+date y, por
    # tanto, service_id no identifica una fila. source_row es estable dentro
    # del archivo fuente y evita perder excepciones al materializar el feed.
    if table_name == "gtfs_calendar_dates":
        source_row = payload.get("source_row")
        if source_row is not None:
            return str(source_row)
    column = _ENTITY_COLUMNS.get(table_name)
    value = payload.get(column) if column is not None else None
    if value is None or value == "":
        value = payload.get("source_row")
    if value is None or value == "":
        raise ValueError(f"La fila de {table_name} no tiene identidad de edición.")
    return str(value)


def _json_dumps(value: Any) -> str:
    return json.dumps(
        _json_prepare(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
