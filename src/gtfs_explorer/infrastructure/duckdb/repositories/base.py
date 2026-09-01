"""Repositorios base DuckDB para las operaciones de control ya disponibles."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Sequence
from datetime import date, datetime, timezone

import duckdb

from gtfs_explorer.domain.errors import RepositoryError
from gtfs_explorer.domain.geometry import GeometryIssue, TripShapeGeometry
from gtfs_explorer.domain.operations import (
    Operation,
    OperationStatus,
    OperationType,
    validate_artifact,
    validate_error_code,
    validate_utc_naive,
)
from gtfs_explorer.domain.overview import (
    FeedOverview,
    OverviewFile,
    OverviewMetric,
    ValidationOverview,
)
from gtfs_explorer.domain.ports import FeedSourceFile, PagedResult, PageRequest
from gtfs_explorer.domain.project import (
    FeedMetadata,
    FeedStatus,
    ImportJobMetadata,
    ProjectMetadata,
    ProjectStatus,
)
from gtfs_explorer.domain.raw import RawColumn, RawFilter, RawPage, RawQuery, RawRow, RawSort
from gtfs_explorer.domain.routes import (
    DirectionSummary,
    RouteSummary,
    ServiceSummary,
    TimelineStop,
    TripSummary,
)
from gtfs_explorer.domain.service_calendar import ServicePeriod
from gtfs_explorer.domain.spec import FieldSpec, ScheduleSpec
from gtfs_explorer.domain.stops import ScheduledStopEvent, StopInspection, StopSummary
from gtfs_explorer.domain.subset import CoreStop, CoreSubsetSource, CoreTrip
from gtfs_explorer.domain.validation import (
    ValidationCategory,
    ValidationEntity,
    ValidationIssueFilter,
    ValidationIssueSummary,
    ValidationSeverity,
)
from gtfs_explorer.infrastructure.duckdb.database import (
    DatabaseConnection,
    DatabaseError,
    ProjectDatabase,
)
from gtfs_explorer.infrastructure.geometry import build_trip_shape_geometry
from gtfs_explorer.product import IDENTITY


class DuckDbProjectRepository:
    """Implementa las consultas de control del proyecto en DuckDB."""

    def __init__(self, connection: DatabaseConnection) -> None:
        self._connection = connection

    def schema_version(self) -> int:
        try:
            row = self._connection.execute("SELECT schema_version FROM schema_metadata").fetchone()
        except (DatabaseError, duckdb.Error) as error:
            raise RepositoryError("No se ha podido consultar la versión del proyecto.") from error
        if row is None or not isinstance(row[0], int):
            raise RepositoryError("La versión del proyecto almacenada no es válida.")
        return row[0]

    def metadata(self) -> ProjectMetadata | None:
        row = self._connection.execute(
            "SELECT project_id, name, status FROM projects ORDER BY created_at LIMIT 1"
        ).fetchone()
        return (
            None
            if row is None
            else ProjectMetadata(str(row[0]), str(row[1]), ProjectStatus(row[2]))
        )

    def save_metadata(self, metadata: ProjectMetadata) -> None:
        now = datetime.now(timezone.utc)
        self._connection.execute(
            "INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (project_id) DO UPDATE SET name = excluded.name, "
            "status = excluded.status, "
            "updated_at = excluded.updated_at, schema_version = excluded.schema_version",
            [metadata.project_id, metadata.name, metadata.status, now, now, self.schema_version()],
        )


class DuckDbFeedRepository:
    """Implementa el acceso paginado al inventario staging del feed."""

    def __init__(self, connection: DatabaseConnection) -> None:
        self._connection = connection

    def source_files(self, page: PageRequest) -> PagedResult[FeedSourceFile]:
        try:
            total_row = self._connection.execute(
                "SELECT count(*) FROM stg_source_inventory"
            ).fetchone()
            rows = self._connection.execute(
                "SELECT original_name, canonical_name, content_sha256, size_bytes, "
                "known_to_schedule_spec, loaded_row_count, staging_table_name "
                "FROM stg_source_inventory ORDER BY canonical_name, original_name LIMIT ? OFFSET ?",
                [page.limit, page.offset],
            ).fetchall()
        except (DatabaseError, duckdb.Error) as error:
            raise RepositoryError("No se ha podido consultar el inventario del feed.") from error
        if total_row is None or not isinstance(total_row[0], int):
            raise RepositoryError("El recuento del inventario del feed no es válido.")
        return PagedResult(
            items=tuple(
                FeedSourceFile(
                    original_name=str(row[0]),
                    canonical_name=str(row[1]),
                    content_sha256=str(row[2]),
                    size_bytes=int(row[3]),
                    known_to_schedule_spec=bool(row[4]),
                    loaded_row_count=int(row[5]) if row[5] is not None else None,
                    staging_table_name=str(row[6]) if row[6] is not None else None,
                )
                for row in rows
            ),
            total=total_row[0],
            request=page,
        )

    def latest_metadata(self) -> FeedMetadata | None:
        row = self._connection.execute(
            "SELECT feed_id, project_id, source_name, source_sha256, import_mode, "
            "spec_revision, status "
            "FROM feeds ORDER BY CASE WHEN status = 'IMPORTED' THEN 0 ELSE 1 END, "
            "imported_at DESC LIMIT 1"
        ).fetchone()
        return (
            None
            if row is None
            else FeedMetadata(
                str(row[0]),
                str(row[1]),
                str(row[2]),
                str(row[3]),
                str(row[4]),
                str(row[5]),
                FeedStatus(row[6]),
            )
        )

    def save_metadata(self, metadata: FeedMetadata) -> None:
        self._connection.execute(
            "INSERT INTO feeds VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (feed_id) DO UPDATE SET source_name = excluded.source_name, "
            "source_sha256 = excluded.source_sha256, import_mode = excluded.import_mode, "
            "spec_revision = excluded.spec_revision, status = excluded.status",
            [
                metadata.feed_id,
                metadata.project_id,
                metadata.source_name,
                metadata.manifest_sha256,
                metadata.import_mode,
                metadata.spec_revision,
                IDENTITY.version,
                datetime.now(timezone.utc),
                metadata.status,
            ],
        )


class DuckDbFeedOverviewRepository:
    """Compone el resumen desde datos normalizados e inventario staging."""

    _METRICS = (
        ("Agencias", "gtfs_agency", "agencias"),
        ("Paradas", "gtfs_stops", "paradas"),
        ("Rutas", "gtfs_routes", "rutas"),
        ("Viajes", "gtfs_trips", "viajes"),
        ("Eventos de parada", "gtfs_stop_times", "eventos"),
    )

    def __init__(self, connection: DatabaseConnection) -> None:
        self._connection = connection

    def overview(self) -> FeedOverview:
        try:
            feed = DuckDbFeedRepository(self._connection).latest_metadata()
            metrics: list[OverviewMetric] = []
            for label, table, unit in self._METRICS:
                row = self._connection.execute(f"SELECT count(*) FROM {table}").fetchone()
                if row is None:
                    raise RepositoryError("El recuento normalizado del feed no es válido.")
                metrics.append(OverviewMetric(label, int(row[0]), unit, "datos normalizados"))
            file_rows = self._connection.execute(
                "SELECT canonical_name, known_to_schedule_spec, loaded_row_count "
                "FROM stg_source_inventory ORDER BY canonical_name, original_name"
            ).fetchall()
            validation_row = self._connection.execute(
                "SELECT count(*), coalesce(sum(total_issue_count), 0), "
                "coalesce(string_agg(DISTINCT status, ', ' ORDER BY status), '') "
                "FROM validation_runs" + (" WHERE feed_id = ?" if feed is not None else ""),
                [feed.feed_id] if feed is not None else [],
            ).fetchone()
            period = DuckDbServiceCalendarRepository(self._connection).service_period()
        except (DatabaseError, duckdb.Error, TypeError, IndexError) as error:
            raise RepositoryError("No se ha podido consultar el resumen del feed.") from error
        assert validation_row is not None
        statuses = tuple(filter(None, str(validation_row[2]).split(", ")))
        return FeedOverview(
            feed=feed,
            period=period,
            metrics=tuple(metrics),
            files=tuple(
                OverviewFile(str(row[0]), bool(row[1]), None if row[2] is None else int(row[2]))
                for row in file_rows
            ),
            validation=ValidationOverview(int(validation_row[0]), int(validation_row[1]), statuses),
        )


class DuckDbValidationRepository:
    """Consulta las incidencias almacenadas con filtros y ventana acotada."""

    def __init__(self, connection: DatabaseConnection) -> None:
        self._connection = connection

    def issues(
        self, report_filter: ValidationIssueFilter, page: PageRequest
    ) -> PagedResult[ValidationIssueSummary]:
        conditions: list[str] = []
        parameters: list[object] = []
        _validation_conditions(report_filter, conditions, parameters)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        try:
            total_row = self._connection.execute(
                "SELECT count(*) FROM validation_issues i "
                "JOIN validation_runs r ON r.batch_id = i.batch_id" + where,
                parameters,
            ).fetchone()
            rows = self._connection.execute(
                "SELECT i.batch_id, i.position, i.rule_code, i.validator, i.severity, i.category, "
                "i.file_name, i.row_number, i.field_name, i.entity_type, i.entity_id, "
                "i.message_key, i.message_parameters, i.help_id, i.occurrence_count "
                "FROM validation_issues i JOIN validation_runs r ON r.batch_id = i.batch_id"
                + where
                + " ORDER BY i.batch_id DESC, i.position LIMIT ? OFFSET ?",
                [*parameters, page.limit, page.offset],
            ).fetchall()
        except (DatabaseError, duckdb.Error, ValueError) as error:
            raise RepositoryError(
                "No se han podido consultar las incidencias de validación."
            ) from error
        if total_row is None or not isinstance(total_row[0], int):
            raise RepositoryError("El recuento de incidencias no es válido.")
        return PagedResult(
            tuple(_validation_issue_summary(row) for row in rows), total_row[0], page
        )

    def files(self, report_filter: ValidationIssueFilter) -> tuple[str, ...]:
        """Consulta el catálogo de archivos sin materializar las incidencias."""
        conditions = ["i.file_name IS NOT NULL", "i.file_name <> ''"]
        parameters: list[object] = []
        if report_filter.feed_id is not None:
            conditions.append("r.feed_id = ?")
            parameters.append(report_filter.feed_id)
        try:
            rows = self._connection.execute(
                "SELECT DISTINCT i.file_name FROM validation_issues i "
                "JOIN validation_runs r ON r.batch_id = i.batch_id WHERE "
                + " AND ".join(conditions)
                + " ORDER BY lower(i.file_name), i.file_name",
                parameters,
            ).fetchall()
        except (DatabaseError, duckdb.Error, ValueError) as error:
            raise RepositoryError("No se han podido consultar los archivos validados.") from error
        return tuple(str(row[0]) for row in rows if row[0] is not None)


class DuckDbImportJobRepository:
    def __init__(self, connection: DatabaseConnection) -> None:
        self._connection = connection

    def save_metadata(self, metadata: ImportJobMetadata) -> None:
        self._connection.execute(
            "INSERT INTO import_jobs (job_id, feed_id, state, phase, progress, error_code) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (job_id) DO UPDATE SET state = excluded.state, "
            "phase = excluded.phase, progress = excluded.progress, "
            "error_code = excluded.error_code",
            [
                metadata.job_id,
                metadata.feed_id,
                metadata.state,
                metadata.phase,
                metadata.progress,
                metadata.error_code,
            ],
        )

    def recover_interrupted(self) -> tuple[str, ...]:
        """Marca como fallidos los trabajos que no llegaron a un estado terminal."""
        rows = self._connection.execute(
            "SELECT job_id FROM import_jobs WHERE state IN ('PENDING', 'RUNNING', 'CANCELLING') "
            "ORDER BY job_id"
        ).fetchall()
        job_ids = tuple(str(row[0]) for row in rows)
        if job_ids:
            self._connection.execute(
                "UPDATE import_jobs SET state = 'FAILED', phase = 'CLEANUP', progress = 0, "
                "error_code = 'INTERRUPTED_RECOVERY' "
                "WHERE state IN ('PENDING', 'RUNNING', 'CANCELLING')"
            )
        return job_ids


class DuckDbOperationRepository:
    """Ledger canónico de operaciones, aislado de los pipelines productivos."""

    def __init__(self, connection: DatabaseConnection) -> None:
        self._connection = connection

    def start(
        self,
        operation_id: str,
        project_id: str,
        operation_type: OperationType,
        started_at: datetime,
    ) -> None:
        validate_utc_naive(started_at)
        self._connection.execute(
            "INSERT INTO operations (operation_id, project_id, operation_type, status, started_at) "
            "VALUES (?, ?, ?, 'RUNNING', ?)",
            [operation_id, project_id, operation_type, started_at],
        )

    def finish(
        self,
        operation_id: str,
        status: OperationStatus,
        finished_at: datetime,
        error_code: str | None = None,
    ) -> None:
        if status is OperationStatus.RUNNING:
            raise ValueError("Una operación no puede finalizar en RUNNING.")
        validate_utc_naive(finished_at)
        validate_error_code(status, error_code)
        row = self._connection.execute(
            "SELECT status, started_at FROM operations WHERE operation_id = ?", [operation_id]
        ).fetchone()
        if row is None:
            raise ValueError("La operación no existe.")
        if str(row[0]) != OperationStatus.RUNNING:
            raise ValueError("Una operación terminal no puede volver a finalizarse.")
        if not isinstance(row[1], datetime) or finished_at < row[1]:
            raise ValueError("La finalización no puede preceder al inicio.")
        self._connection.execute(
            "UPDATE operations SET status = ?, finished_at = ?, error_code = ? "
            "WHERE operation_id = ? AND status = 'RUNNING'",
            [status, finished_at, error_code, operation_id],
        )

    def attach_import_detail(self, operation_id: str, feed_id: str, job_id: str) -> None:
        self._attach(
            operation_id,
            OperationType.IMPORT,
            "operation_import_details",
            ["operation_id", "feed_id", "job_id"],
            [operation_id, feed_id, job_id],
        )

    def attach_validation_detail(
        self, operation_id: str, feed_id: str, validation_batch_id: str | None = None
    ) -> None:
        self._attach(
            operation_id,
            OperationType.VALIDATION,
            "operation_validation_details",
            ["operation_id", "feed_id", "validation_batch_id"],
            [operation_id, feed_id, validation_batch_id],
        )

    def attach_export_detail(
        self,
        operation_id: str,
        feed_id: str,
        export_format: str,
        artifact_name: str | None = None,
        artifact_sha256: str | None = None,
        artifact_size_bytes: int | None = None,
    ) -> None:
        normalized_name, normalized_hash = validate_artifact(
            artifact_name, artifact_sha256, artifact_size_bytes
        )
        self._attach(
            operation_id,
            OperationType.EXPORT,
            "operation_export_details",
            [
                "operation_id",
                "feed_id",
                "export_format",
                "artifact_name",
                "artifact_sha256",
                "artifact_size_bytes",
            ],
            [
                operation_id,
                feed_id,
                export_format,
                normalized_name,
                normalized_hash,
                artifact_size_bytes,
            ],
        )

    def update_export_detail(
        self,
        operation_id: str,
        artifact_name: str,
        artifact_sha256: str,
        artifact_size_bytes: int,
    ) -> None:
        normalized_name, normalized_hash = validate_artifact(
            artifact_name, artifact_sha256, artifact_size_bytes
        )
        assert normalized_name is not None and normalized_hash is not None
        row = self._connection.execute(
            "SELECT operation_type FROM operations WHERE operation_id = ?", [operation_id]
        ).fetchone()
        if row is None:
            raise ValueError("La operación no existe.")
        if str(row[0]) != OperationType.EXPORT:
            raise ValueError("El detalle no es compatible con el tipo de operación.")
        existing = self._connection.execute(
            "SELECT count(*) FROM operation_export_details WHERE operation_id = ?", [operation_id]
        ).fetchone()
        if existing is None or existing[0] != 1:
            raise ValueError("La operación no tiene un detalle de exportación.")
        self._connection.execute(
            "UPDATE operation_export_details SET artifact_name = ?, "
            "artifact_sha256 = ?, artifact_size_bytes = ? WHERE operation_id = ?",
            [normalized_name, normalized_hash, artifact_size_bytes, operation_id],
        )

    def list_operations(
        self,
        project_id: str,
        page: PageRequest,
        operation_type: OperationType | None = None,
        status: OperationStatus | None = None,
    ) -> PagedResult[Operation]:
        conditions = ["o.project_id = ?"]
        parameters: list[object] = [project_id]
        if operation_type is not None:
            conditions.append("o.operation_type = ?")
            parameters.append(operation_type)
        if status is not None:
            conditions.append("o.status = ?")
            parameters.append(status)
        where = " WHERE " + " AND ".join(conditions)
        total = self._connection.execute(
            "SELECT count(*) FROM operations o" + where, parameters
        ).fetchone()
        rows = self._connection.execute(
            "SELECT o.operation_id, o.project_id, o.operation_type, o.status, o.started_at, "
            "o.finished_at, o.error_code, coalesce(i.feed_id, v.feed_id, e.feed_id), "
            "coalesce(fi.source_name, fv.source_name, fe.source_name), i.job_id, "
            "coalesce(v.validation_batch_id, ivr.batch_id), "
            "CASE WHEN coalesce(vr.status, ivr.status) IN ('VALID', 'INVALID', 'CANCELLED') "
            "THEN coalesce(vr.status, ivr.status) END, "
            "CASE WHEN coalesce(vr.status, ivr.status) IN ('VALID', 'INVALID', 'CANCELLED') "
            "THEN coalesce(vr.total_issue_count, ivr.total_issue_count) END, e.export_format, "
            "e.artifact_name, e.artifact_sha256, e.artifact_size_bytes FROM operations o "
            "LEFT JOIN operation_import_details i ON i.operation_id = o.operation_id "
            "LEFT JOIN feeds fi ON fi.feed_id = i.feed_id "
            "LEFT JOIN operation_validation_details v ON v.operation_id = o.operation_id "
            "LEFT JOIN feeds fv ON fv.feed_id = v.feed_id "
            "LEFT JOIN validation_runs vr ON vr.batch_id = v.validation_batch_id "
            "LEFT JOIN validation_runs ivr ON ivr.batch_id = i.job_id || ':structure' "
            "AND ivr.feed_id = i.feed_id "
            "LEFT JOIN operation_export_details e ON e.operation_id = o.operation_id "
            "LEFT JOIN feeds fe ON fe.feed_id = e.feed_id"
            + where
            + " ORDER BY o.started_at DESC, o.operation_id DESC LIMIT ? OFFSET ?",
            [*parameters, page.limit, page.offset],
        ).fetchall()
        if total is None or not isinstance(total[0], int):
            raise RepositoryError("El recuento de operaciones no es válido.")
        return PagedResult(tuple(self._operation(row) for row in rows), total[0], page)

    def _attach(
        self,
        operation_id: str,
        expected_type: OperationType,
        table: str,
        columns: list[str],
        values: list[object],
    ) -> None:
        row = self._connection.execute(
            "SELECT operation_type FROM operations WHERE operation_id = ?", [operation_id]
        ).fetchone()
        if row is None:
            raise ValueError("La operación no existe.")
        if str(row[0]) != expected_type:
            raise ValueError("El detalle no es compatible con el tipo de operación.")
        existing = self._connection.execute(
            f"SELECT count(*) FROM {table} WHERE operation_id = ?", [operation_id]
        ).fetchone()
        if existing is None or existing[0] != 0:
            raise ValueError("Una operación ya tiene un detalle de ese tipo.")
        unique_column = {
            "operation_import_details": "job_id",
            "operation_validation_details": "validation_batch_id",
        }.get(table)
        if unique_column is not None and values[-1] is not None:
            linked = self._connection.execute(
                f"SELECT count(*) FROM {table} WHERE {unique_column} = ?", [values[-1]]
            ).fetchone()
            if linked is None or linked[0] != 0:
                raise ValueError("La referencia ya está asociada a otra operación.")
        statement = (
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})"
        )
        self._connection.execute(statement, values)

    @staticmethod
    def _operation(row: tuple[object, ...]) -> Operation:
        started_at, finished_at = row[4], row[5]
        if not isinstance(started_at, datetime) or (
            finished_at is not None and not isinstance(finished_at, datetime)
        ):
            raise RepositoryError("Los timestamps de operaciones no son válidos.")
        return Operation(
            str(row[0]),
            str(row[1]),
            OperationType(str(row[2])),
            OperationStatus(str(row[3])),
            started_at,
            finished_at,
            None if row[6] is None else str(row[6]),
            None if row[7] is None else str(row[7]),
            None if row[9] is None else str(row[9]),
            None if row[10] is None else str(row[10]),
            None if row[11] is None else str(row[11]),
            None if row[12] is None else _int_value(row[12]),
            None if row[13] is None else str(row[13]),
            None if row[14] is None else str(row[14]),
            None if row[15] is None else str(row[15]),
            None if row[16] is None else _int_value(row[16]),
            None if row[8] is None else str(row[8]),
        )


class DuckDbServiceCalendarRepository:
    """Resuelve calendario y excepciones con consultas acotadas a DuckDB."""

    _WEEKDAY_COLUMNS = (
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    )

    def __init__(self, connection: DatabaseConnection) -> None:
        self._connection = connection

    def service_ids_on(self, service_date: date) -> tuple[str, ...]:
        weekday_column = self._WEEKDAY_COLUMNS[service_date.weekday()]
        try:
            rows = self._connection.execute(
                "WITH weekly AS ("
                "SELECT DISTINCT service_id FROM gtfs_calendar "
                f"WHERE {weekday_column} = 1 AND start_date <= ? AND end_date >= ? "
                "AND service_id IS NOT NULL"
                "), additions AS ("
                "SELECT DISTINCT service_id FROM gtfs_calendar_dates "
                "WHERE date = ? AND exception_type = 1 AND service_id IS NOT NULL"
                "), removals AS ("
                "SELECT DISTINCT service_id FROM gtfs_calendar_dates "
                "WHERE date = ? AND exception_type = 2 AND service_id IS NOT NULL"
                ") SELECT service_id FROM ("
                "SELECT service_id FROM weekly UNION SELECT service_id FROM additions"
                ") "
                "WHERE service_id NOT IN (SELECT service_id FROM removals) ORDER BY service_id",
                [service_date, service_date, service_date, service_date],
            ).fetchall()
        except (DatabaseError, duckdb.Error) as error:
            message = "No se ha podido consultar el calendario de servicios."
            raise RepositoryError(message) from error
        return tuple(str(row[0]) for row in rows)

    def service_period(self) -> ServicePeriod | None:
        try:
            row = self._connection.execute(
                "SELECT min(service_date), max(service_date) FROM ("
                "SELECT start_date AS service_date FROM gtfs_calendar "
                "WHERE start_date IS NOT NULL AND end_date IS NOT NULL AND start_date <= end_date "
                "UNION ALL SELECT end_date FROM gtfs_calendar "
                "WHERE start_date IS NOT NULL AND end_date IS NOT NULL AND start_date <= end_date "
                "UNION ALL SELECT date FROM gtfs_calendar_dates WHERE date IS NOT NULL"
                ")"
            ).fetchone()
        except (DatabaseError, duckdb.Error) as error:
            raise RepositoryError("No se ha podido consultar el periodo de servicios.") from error
        if row is None or row[0] is None or row[1] is None:
            return None
        if not isinstance(row[0], date) or not isinstance(row[1], date):
            raise RepositoryError("El periodo de servicios almacenado no es válido.")
        return ServicePeriod(row[0], row[1])


class DuckDbRouteExplorerRepository:
    """Consultas parametrizadas de la cadena ruta, servicio, dirección y viaje."""

    def __init__(self, connection: DatabaseConnection) -> None:
        self._connection = connection

    def routes(self, page: PageRequest) -> PagedResult[RouteSummary]:
        total, rows = self._page(
            "SELECT count(*) FROM gtfs_routes",
            "SELECT route_id, agency_id, route_short_name, route_long_name, route_type "
            "FROM gtfs_routes "
            "ORDER BY agency_id NULLS LAST, route_sort_order NULLS LAST, route_id, source_row "
            "LIMIT ? OFFSET ?",
            [],
            page,
            "las rutas",
        )
        return PagedResult(
            items=tuple(
                RouteSummary(
                    route_id=str(row[0]),
                    agency_id=str(row[1]) if row[1] is not None else None,
                    short_name=str(row[2]) if row[2] is not None else None,
                    long_name=str(row[3]) if row[3] is not None else None,
                    route_type=_optional_int(row[4]),
                )
                for row in rows
            ),
            total=total,
            request=page,
        )

    def services_for_route(self, route_id: str, page: PageRequest) -> PagedResult[ServiceSummary]:
        total, rows = self._page(
            "SELECT count(DISTINCT service_id) FROM gtfs_trips "
            "WHERE route_id = ? AND service_id IS NOT NULL",
            "SELECT service_id, count(*) FROM gtfs_trips "
            "WHERE route_id = ? AND service_id IS NOT NULL "
            "GROUP BY service_id ORDER BY service_id LIMIT ? OFFSET ?",
            [route_id],
            page,
            "los servicios de la ruta",
        )
        return PagedResult(
            items=tuple(ServiceSummary(str(row[0]), _int_value(row[1])) for row in rows),
            total=total,
            request=page,
        )

    def directions_for_route_service(
        self, route_id: str, service_id: str, page: PageRequest
    ) -> PagedResult[DirectionSummary]:
        total, rows = self._page(
            "SELECT count(*) FROM (SELECT direction_id FROM gtfs_trips "
            "WHERE route_id = ? AND service_id = ? GROUP BY direction_id)",
            "SELECT direction_id, count(*) FROM gtfs_trips "
            "WHERE route_id = ? AND service_id = ? "
            "GROUP BY direction_id "
            "ORDER BY direction_id IS NULL, direction_id LIMIT ? OFFSET ?",
            [route_id, service_id],
            page,
            "las direcciones de la ruta y servicio",
        )
        return PagedResult(
            items=tuple(
                DirectionSummary(_optional_int(row[0]), _int_value(row[1])) for row in rows
            ),
            total=total,
            request=page,
        )

    def trips_for_route_service_direction(
        self, route_id: str, service_id: str, direction_id: int | None, page: PageRequest
    ) -> PagedResult[TripSummary]:
        filters: Sequence[object] = [route_id, service_id, direction_id]
        total, rows = self._page(
            "SELECT count(*) FROM gtfs_trips "
            "WHERE route_id = ? AND service_id = ? AND direction_id IS NOT DISTINCT FROM ?",
            "SELECT trip_id, route_id, service_id, direction_id, trip_headsign, trip_short_name, "
            "shape_id FROM gtfs_trips "
            "WHERE route_id = ? AND service_id = ? AND direction_id IS NOT DISTINCT FROM ? "
            "ORDER BY trip_id, source_row LIMIT ? OFFSET ?",
            filters,
            page,
            "los viajes de la ruta, servicio y dirección",
        )
        return PagedResult(
            items=tuple(
                TripSummary(
                    trip_id=str(row[0]),
                    route_id=str(row[1]),
                    service_id=str(row[2]),
                    direction_id=_optional_int(row[3]),
                    headsign=str(row[4]) if row[4] is not None else None,
                    short_name=str(row[5]) if row[5] is not None else None,
                    shape_id=str(row[6]) if row[6] is not None else None,
                )
                for row in rows
            ),
            total=total,
            request=page,
        )

    def trip_timeline(self, trip_id: str, page: PageRequest) -> PagedResult[TimelineStop]:
        total, rows = self._page(
            "SELECT count(*) FROM gtfs_stop_times WHERE trip_id = ?",
            "SELECT stop_sequence, stop_id, "
            "(SELECT stop_name FROM gtfs_stops "
            "WHERE stop_id = gtfs_stop_times.stop_id ORDER BY source_row LIMIT 1), "
            "arrival_time_lexeme, arrival_service_seconds, departure_time_lexeme, "
            "departure_service_seconds FROM gtfs_stop_times WHERE trip_id = ? "
            "ORDER BY stop_sequence NULLS LAST, source_row LIMIT ? OFFSET ?",
            [trip_id],
            page,
            "el timeline del viaje",
        )
        return PagedResult(
            items=tuple(
                TimelineStop(
                    stop_sequence=_optional_int(row[0]),
                    stop_id=str(row[1]) if row[1] is not None else None,
                    stop_name=str(row[2]) if row[2] is not None else None,
                    arrival_time=str(row[3]) if row[3] is not None else None,
                    arrival_service_seconds=_optional_int(row[4]),
                    departure_time=str(row[5]) if row[5] is not None else None,
                    departure_service_seconds=_optional_int(row[6]),
                )
                for row in rows
            ),
            total=total,
            request=page,
        )

    def _page(
        self,
        total_query: str,
        items_query: str,
        parameters: Sequence[object],
        page: PageRequest,
        subject: str,
    ) -> tuple[int, list[tuple[object, ...]]]:
        try:
            total_row = self._connection.execute(total_query, parameters).fetchone()
            rows = self._connection.execute(
                items_query, [*parameters, page.limit, page.offset]
            ).fetchall()
        except (DatabaseError, duckdb.Error) as error:
            raise RepositoryError(f"No se han podido consultar {subject}.") from error
        if total_row is None or not isinstance(total_row[0], int):
            raise RepositoryError(f"El recuento de {subject} no es válido.")
        return total_row[0], rows


class DuckDbStopInspectorRepository:
    """Consulta una parada con un número fijo de operaciones, nunca por cada fila."""

    _WEEKDAY_COLUMNS = DuckDbServiceCalendarRepository._WEEKDAY_COLUMNS

    def __init__(self, connection: DatabaseConnection) -> None:
        self._connection = connection

    def inspect_stop(
        self, stop_id: str, service_date: date | None, page: PageRequest
    ) -> StopInspection:
        stop = self._stop(stop_id)
        routes = self._routes(stop_id, page)
        services = self._services(stop_id, page)
        events = self._scheduled_events(stop_id, service_date, page)
        return StopInspection(stop, service_date, routes, services, events)

    def _stop(self, stop_id: str) -> StopSummary | None:
        try:
            row = self._connection.execute(
                "SELECT stop_id, stop_name, parent_station FROM gtfs_stops "
                "WHERE stop_id = ? ORDER BY source_row LIMIT 1",
                [stop_id],
            ).fetchone()
        except (DatabaseError, duckdb.Error) as error:
            raise RepositoryError("No se ha podido consultar la parada.") from error
        return (
            None
            if row is None
            else StopSummary(
                str(row[0]),
                str(row[1]) if row[1] is not None else None,
                str(row[2]) if row[2] is not None else None,
            )
        )

    def _routes(self, stop_id: str, page: PageRequest) -> PagedResult[RouteSummary]:
        total, rows = self._page(
            "SELECT count(*) FROM ("
            "SELECT r.route_id FROM gtfs_stop_times st JOIN gtfs_trips t ON t.trip_id = st.trip_id "
            "JOIN gtfs_routes r ON r.route_id = t.route_id "
            f"WHERE st.stop_id IN ({self._scope_sql()}) GROUP BY r.route_id"
            ")",
            "SELECT r.route_id, any_value(r.agency_id), any_value(r.route_short_name), "
            "any_value(r.route_long_name), any_value(r.route_type) "
            "FROM gtfs_stop_times st JOIN gtfs_trips t ON t.trip_id = st.trip_id "
            "JOIN gtfs_routes r ON r.route_id = t.route_id "
            f"WHERE st.stop_id IN ({self._scope_sql()}) GROUP BY r.route_id "
            "ORDER BY any_value(r.agency_id) NULLS LAST, any_value(r.route_sort_order) NULLS LAST, "
            "r.route_id LIMIT ? OFFSET ?",
            [stop_id, stop_id],
            page,
            "las rutas de la parada",
        )
        return PagedResult(
            tuple(
                RouteSummary(
                    str(row[0]),
                    str(row[1]) if row[1] is not None else None,
                    str(row[2]) if row[2] is not None else None,
                    str(row[3]) if row[3] is not None else None,
                    _optional_int(row[4]),
                )
                for row in rows
            ),
            total,
            page,
        )

    def _services(self, stop_id: str, page: PageRequest) -> PagedResult[ServiceSummary]:
        total, rows = self._page(
            "SELECT count(*) FROM (SELECT t.service_id FROM gtfs_stop_times st "
            "JOIN gtfs_trips t ON t.trip_id = st.trip_id "
            f"WHERE st.stop_id IN ({self._scope_sql()}) AND t.service_id IS NOT NULL "
            "GROUP BY t.service_id)",
            "SELECT t.service_id, count(*) FROM gtfs_stop_times st "
            "JOIN gtfs_trips t ON t.trip_id = st.trip_id "
            f"WHERE st.stop_id IN ({self._scope_sql()}) AND t.service_id IS NOT NULL "
            "GROUP BY t.service_id ORDER BY t.service_id LIMIT ? OFFSET ?",
            [stop_id, stop_id],
            page,
            "los servicios de la parada",
        )
        return PagedResult(
            tuple(ServiceSummary(str(row[0]), _int_value(row[1])) for row in rows), total, page
        )

    def _scheduled_events(
        self, stop_id: str, service_date: date | None, page: PageRequest
    ) -> PagedResult[ScheduledStopEvent]:
        active_sql, active_parameters = self._active_services_sql(service_date)
        filters = [stop_id, stop_id, *active_parameters]
        prefix = f"WITH scoped_stops AS ({self._scope_sql()}), {active_sql} "
        where = "st.stop_id IN (SELECT stop_id FROM scoped_stops)"
        if service_date is not None:
            where += " AND t.service_id IN (SELECT service_id FROM active_services)"
        total, rows = self._page(
            prefix
            + "SELECT count(*) FROM gtfs_stop_times st JOIN gtfs_trips t ON t.trip_id = st.trip_id "
            + "JOIN gtfs_routes r ON r.route_id = t.route_id WHERE "
            + where,
            prefix
            + "SELECT t.trip_id, r.route_id, r.agency_id, r.route_short_name, r.route_long_name, "
            "r.route_type, t.service_id, st.stop_id, own_stop.stop_name, st.stop_sequence, "
            "st.arrival_time_lexeme, st.arrival_service_seconds, st.departure_time_lexeme, "
            "st.departure_service_seconds FROM gtfs_stop_times st "
            "JOIN gtfs_trips t ON t.trip_id = st.trip_id "
            "JOIN gtfs_routes r ON r.route_id = t.route_id "
            "LEFT JOIN gtfs_stops own_stop ON own_stop.stop_id = st.stop_id WHERE "
            + where
            + " ORDER BY coalesce(st.departure_service_seconds, "
            "st.arrival_service_seconds) NULLS LAST, "
            "t.trip_id, st.stop_sequence NULLS LAST, st.source_row LIMIT ? OFFSET ?",
            filters,
            page,
            "los eventos programados de la parada",
        )
        return PagedResult(
            tuple(
                ScheduledStopEvent(
                    trip_id=str(row[0]),
                    route=RouteSummary(
                        str(row[1]),
                        str(row[2]) if row[2] is not None else None,
                        str(row[3]) if row[3] is not None else None,
                        str(row[4]) if row[4] is not None else None,
                        _optional_int(row[5]),
                    ),
                    service_id=str(row[6]),
                    stop_id=str(row[7]),
                    stop_name=str(row[8]) if row[8] is not None else None,
                    stop_sequence=_optional_int(row[9]),
                    arrival_time=str(row[10]) if row[10] is not None else None,
                    arrival_service_seconds=_optional_int(row[11]),
                    departure_time=str(row[12]) if row[12] is not None else None,
                    departure_service_seconds=_optional_int(row[13]),
                )
                for row in rows
            ),
            total,
            page,
        )

    def _active_services_sql(self, service_date: date | None) -> tuple[str, list[object]]:
        if service_date is None:
            return "active_services AS (SELECT service_id FROM gtfs_trips WHERE FALSE)", []
        weekday = self._WEEKDAY_COLUMNS[service_date.weekday()]
        return (
            "active_services AS ("
            "WITH weekly AS (SELECT DISTINCT service_id FROM gtfs_calendar "
            f"WHERE {weekday} = 1 AND start_date <= ? AND end_date >= ?), "
            "additions AS (SELECT DISTINCT service_id FROM gtfs_calendar_dates "
            "WHERE date = ? AND exception_type = 1), "
            "removals AS (SELECT DISTINCT service_id FROM gtfs_calendar_dates "
            "WHERE date = ? AND exception_type = 2) "
            "SELECT service_id FROM (SELECT service_id FROM weekly "
            "UNION SELECT service_id FROM additions) "
            "WHERE service_id NOT IN (SELECT service_id FROM removals))",
            [service_date, service_date, service_date, service_date],
        )

    @staticmethod
    def _scope_sql() -> str:
        return "SELECT ? AS stop_id UNION SELECT stop_id FROM gtfs_stops WHERE parent_station = ?"

    def _page(
        self,
        total_query: str,
        items_query: str,
        parameters: Sequence[object],
        page: PageRequest,
        subject: str,
    ) -> tuple[int, list[tuple[object, ...]]]:
        try:
            total_row = self._connection.execute(total_query, parameters).fetchone()
            rows = self._connection.execute(
                items_query, [*parameters, page.limit, page.offset]
            ).fetchall()
        except (DatabaseError, duckdb.Error) as error:
            raise RepositoryError(f"No se han podido consultar {subject}.") from error
        if total_row is None or not isinstance(total_row[0], int):
            raise RepositoryError(f"El recuento de {subject} no es válido.")
        return total_row[0], rows


class DuckDbRawInspectorRepository:
    """Inspecciona staging mediante identificadores permitidos por el manifiesto."""

    def __init__(self, connection: DatabaseConnection, schedule_spec: ScheduleSpec) -> None:
        self._connection = connection
        self._spec = schedule_spec

    def query(self, request: RawQuery) -> RawPage:
        fields = self._fields(request)
        offset = self._offset(request)
        selected = ", ".join(_quote_identifier(column) for column in request.columns)
        where, parameters = self._where(request.filters, fields)
        ordering = self._ordering(request.sort, fields)
        table = _quote_identifier(_staging_table_name(request.filename))
        try:
            rows = self._connection.execute(
                f"SELECT source_row, {selected} FROM {table}{where} "
                f"ORDER BY {ordering} LIMIT ? OFFSET ?",
                [*parameters, request.page_size + 1, offset],
            ).fetchall()
        except (DatabaseError, duckdb.Error) as error:
            raise RepositoryError("No se ha podido consultar el staging raw.") from error

        has_next = len(rows) > request.page_size
        page_rows = rows[: request.page_size]
        next_token = _encode_page_token(request, offset + len(page_rows)) if has_next else None
        return RawPage(
            filename=request.filename,
            columns=tuple(
                RawColumn(column, fields[column].value_type) for column in request.columns
            ),
            rows=tuple(
                RawRow(
                    source_row=_int_value(row[0]),
                    values=tuple(str(value) if value is not None else None for value in row[1:]),
                )
                for row in page_rows
            ),
            next_page_token=next_token,
        )

    def _fields(self, request: RawQuery) -> dict[str, FieldSpec]:
        file_spec = self._spec.files.get(request.filename)
        if file_spec is None:
            raise ValueError("El archivo raw no figura en el manifiesto GTFS.")
        fields = file_spec.fields
        requested = [
            *request.columns,
            *(item.column for item in request.filters),
            *(item.column for item in request.sort),
        ]
        if any(column not in fields for column in requested):
            raise ValueError("La columna raw no figura en el manifiesto GTFS.")
        return fields

    def _offset(self, request: RawQuery) -> int:
        if request.page_token is None:
            return 0
        try:
            encoded = request.page_token.encode("ascii")
            padding = b"=" * (-len(encoded) % 4)
            payload = json.loads(base64.urlsafe_b64decode(encoded + padding))
            if (
                not isinstance(payload, dict)
                or set(payload) != {"offset", "signature"}
                or not isinstance(payload["offset"], int)
                or payload["offset"] < 0
                or payload["signature"] != _query_signature(request)
            ):
                raise ValueError
            return payload["offset"]
        except (UnicodeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("El token de página raw no es válido para esta consulta.") from error

    def _where(
        self, filters: tuple[RawFilter, ...], fields: dict[str, FieldSpec]
    ) -> tuple[str, list[object]]:
        clauses: list[str] = []
        parameters: list[object] = []
        operators = {"equals": "=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
        for filter_ in filters:
            identifier = _quote_identifier(filter_.column)
            if filter_.operator == "contains":
                clauses.append(f"contains({identifier}, ?)")
                parameters.append(filter_.value)
                continue
            operator = operators.get(filter_.operator)
            if operator is None:
                raise ValueError("El operador de filtro raw no es válido.")
            expression, value = _typed_expression(identifier, fields[filter_.column], filter_.value)
            clauses.append(f"{expression} {operator} ?")
            parameters.append(value)
        return (" WHERE " + " AND ".join(clauses) if clauses else "", parameters)

    def _ordering(self, sort: tuple[RawSort, ...], fields: dict[str, FieldSpec]) -> str:
        parts: list[str] = []
        for item in sort:
            if item.direction not in {"asc", "desc"}:
                raise ValueError("La dirección de ordenación raw no es válida.")
            expression, _ = _typed_expression(
                _quote_identifier(item.column), fields[item.column], None
            )
            parts.append(f"{expression} {item.direction.upper()} NULLS LAST")
        parts.append("source_row ASC")
        return ", ".join(parts)


class DuckDbGeometryRepository:
    """Recupera los datos asociados al viaje antes de calcular métricas geográficas."""

    def __init__(self, connection: DatabaseConnection) -> None:
        self._connection = connection

    def trip_shape(self, trip_id: str) -> TripShapeGeometry:
        try:
            trip = self._connection.execute(
                "SELECT t.shape_id, r.route_id, r.route_color, r.route_text_color "
                "FROM gtfs_trips t "
                "LEFT JOIN LATERAL (SELECT route_id, route_color, route_text_color "
                "FROM gtfs_routes "
                "WHERE route_id = t.route_id ORDER BY source_row LIMIT 1) r ON TRUE "
                "WHERE t.trip_id = ? ORDER BY t.source_row LIMIT 1",
                [trip_id],
            ).fetchone()
            if trip is None:
                return self._missing_trip(trip_id)
            shape_id = str(trip[0]) if trip[0] is not None else None
            shape_rows = self._shape_rows(shape_id)
            stop_rows = self._stop_rows(trip_id)
            map_stops = self._map_stops(trip_id)
        except (DatabaseError, duckdb.Error) as error:
            raise RepositoryError("No se ha podido consultar la geometría del viaje.") from error
        return build_trip_shape_geometry(
            trip_id,
            shape_id,
            shape_rows,
            stop_rows,
            map_stops=map_stops,
            route_color=str(trip[2]) if trip[2] is not None else None,
            route_text_color=str(trip[3]) if trip[3] is not None else None,
            route_id=str(trip[1]) if trip[1] is not None else None,
        )

    def _shape_rows(self, shape_id: str | None) -> list[tuple[object, object, object]]:
        if shape_id is None:
            return []
        return self._connection.execute(
            "SELECT source_row, shape_pt_lat, shape_pt_lon FROM gtfs_shapes WHERE shape_id = ? "
            "ORDER BY shape_pt_sequence NULLS LAST, source_row",
            [shape_id],
        ).fetchall()

    def _stop_rows(self, trip_id: str) -> list[tuple[object, object, object]]:
        return self._connection.execute(
            "SELECT st.stop_id, stop.stop_lat, stop.stop_lon FROM gtfs_stop_times st "
            "LEFT JOIN LATERAL (SELECT stop_lat, stop_lon FROM gtfs_stops "
            "WHERE stop_id = st.stop_id ORDER BY source_row LIMIT 1) stop ON TRUE "
            "WHERE st.trip_id = ? ORDER BY st.stop_sequence NULLS LAST, st.source_row",
            [trip_id],
        ).fetchall()

    def _map_stops(self, trip_id: str) -> list[tuple[object, ...]]:
        return self._connection.execute(
            "SELECT st.stop_id, stop.stop_name, stop.stop_lat, stop.stop_lon, st.stop_sequence "
            "FROM gtfs_stop_times st "
            "LEFT JOIN LATERAL (SELECT stop_name, stop_lat, stop_lon FROM gtfs_stops "
            "WHERE stop_id = st.stop_id ORDER BY source_row LIMIT 1) stop ON TRUE "
            "WHERE st.trip_id = ? ORDER BY st.stop_sequence NULLS LAST, st.source_row",
            [trip_id],
        ).fetchall()

    @staticmethod
    def _missing_trip(trip_id: str) -> TripShapeGeometry:
        return TripShapeGeometry(
            trip_id=trip_id,
            shape_id=None,
            coordinates=(),
            length_meters=None,
            bbox=None,
            stop_distances=(),
            distance_unit="meters",
            length_method="haversine_spherical_geodesic",
            distance_method="local_azimuthal_equidistant_projection",
            issues=(GeometryIssue("TRIP_NOT_FOUND", "El viaje no existe.", trip_id),),
        )


class DuckDbCoreSubsetRepository:
    """Carga las relaciones core completas para el algoritmo puro Mini-GTFS."""

    def __init__(self, connection: DatabaseConnection) -> None:
        self._connection = connection

    def core_subset_source(self) -> CoreSubsetSource:
        try:
            route_agencies = tuple(
                (str(row[0]), str(row[1]) if row[1] is not None else None)
                for row in self._connection.execute(
                    "SELECT route_id, agency_id FROM gtfs_routes "
                    "WHERE route_id IS NOT NULL ORDER BY route_id, source_row"
                ).fetchall()
            )
            trips = tuple(
                CoreTrip(str(row[0]), str(row[1]), str(row[2]))
                for row in self._connection.execute(
                    "SELECT trip_id, route_id, service_id FROM gtfs_trips "
                    "WHERE trip_id IS NOT NULL AND route_id IS NOT NULL AND service_id IS NOT NULL "
                    "ORDER BY trip_id, source_row"
                ).fetchall()
            )
            stop_times = tuple(
                (str(row[0]), str(row[1]))
                for row in self._connection.execute(
                    "SELECT trip_id, stop_id FROM gtfs_stop_times "
                    "WHERE trip_id IS NOT NULL AND stop_id IS NOT NULL "
                    "ORDER BY trip_id, stop_sequence NULLS LAST, source_row"
                ).fetchall()
            )
            stops = tuple(
                CoreStop(str(row[0]), str(row[1]) if row[1] is not None else None)
                for row in self._connection.execute(
                    "SELECT stop_id, parent_station FROM gtfs_stops "
                    "WHERE stop_id IS NOT NULL ORDER BY stop_id, source_row"
                ).fetchall()
            )
            calendar_ids = frozenset(
                str(row[0])
                for row in self._connection.execute(
                    "SELECT DISTINCT service_id FROM gtfs_calendar WHERE service_id IS NOT NULL"
                ).fetchall()
            )
            calendar_date_ids = frozenset(
                str(row[0])
                for row in self._connection.execute(
                    "SELECT DISTINCT service_id FROM gtfs_calendar_dates "
                    "WHERE service_id IS NOT NULL"
                ).fetchall()
            )
            agency_ids = frozenset(
                str(row[0])
                for row in self._connection.execute(
                    "SELECT DISTINCT agency_id FROM gtfs_agency WHERE agency_id IS NOT NULL"
                ).fetchall()
            )
        except (DatabaseError, duckdb.Error) as error:
            raise RepositoryError("No se ha podido cargar el cierre core Mini-GTFS.") from error
        return CoreSubsetSource(
            route_agencies,
            trips,
            stop_times,
            stops,
            calendar_ids,
            calendar_date_ids,
            agency_ids,
        )


def _optional_int(value: object) -> int | None:
    return None if value is None else _int_value(value)


def _int_value(value: object) -> int:
    if isinstance(value, int):
        return value
    raise RepositoryError("Un valor numérico almacenado no es válido.")


def _staging_table_name(filename: str) -> str:
    return "stg_" + filename.removesuffix(".txt").casefold()


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _typed_expression(
    identifier: str, field: FieldSpec, value: str | None
) -> tuple[str, object | None]:
    """Devuelve una expresión segura y el valor tipado que puede compararse con ella."""
    value_type = field.value_type.casefold()
    if "date" in value_type:
        return f"try_strptime({identifier}, '%Y%m%d')", _parse_date_value(value)
    if "time" in value_type:
        expression = (
            f"try_cast(split_part({identifier}, ':', 1) AS BIGINT) * 3600 + "
            f"try_cast(split_part({identifier}, ':', 2) AS BIGINT) * 60 + "
            f"try_cast(split_part({identifier}, ':', 3) AS BIGINT)"
        )
        return expression, _parse_time_value(value)
    if any(token in value_type for token in ("integer", "enum")):
        return f"try_cast({identifier} AS BIGINT)", _parse_integer_value(value)
    if any(token in value_type for token in ("float", "latitude", "longitude", "currency amount")):
        return f"try_cast({identifier} AS DOUBLE)", _parse_float_value(value)
    return identifier, value


def _parse_date_value(value: str | None) -> date | None:
    if value is None or len(value) != 8 or not value.isdecimal():
        raise ValueError("El valor de fecha raw debe tener formato YYYYMMDD.")
    try:
        return date.fromisoformat(f"{value[:4]}-{value[4:6]}-{value[6:]}")
    except ValueError as error:
        raise ValueError("El valor de fecha raw no es válido.") from error


def _parse_time_value(value: str | None) -> int | None:
    if value is None:
        return None
    parts = value.split(":")
    if len(parts) != 3 or any(not part.isdecimal() for part in parts):
        raise ValueError("El valor de hora raw debe tener formato HH:MM:SS.")
    hours, minutes, seconds = (int(part) for part in parts)
    if minutes > 59 or seconds > 59:
        raise ValueError("El valor de hora raw no es válido.")
    return hours * 3600 + minutes * 60 + seconds


def _parse_integer_value(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as error:
        raise ValueError("El valor entero raw no es válido.") from error


def _parse_float_value(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError as error:
        raise ValueError("El valor decimal raw no es válido.") from error


def _query_signature(request: RawQuery) -> str:
    payload = {
        "filename": request.filename,
        "columns": request.columns,
        "filters": [(item.column, item.operator, item.value) for item in request.filters],
        "sort": [(item.column, item.direction) for item in request.sort],
        "page_size": request.page_size,
    }
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _encode_page_token(request: RawQuery, offset: int) -> str:
    payload = json.dumps(
        {"offset": offset, "signature": _query_signature(request)}, separators=(",", ":")
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _validation_in_condition(
    column: str,
    values: frozenset[ValidationSeverity] | frozenset[ValidationCategory] | None,
    conditions: list[str],
    parameters: list[object],
) -> None:
    if values is None:
        return
    if not values:
        conditions.append("FALSE")
        return
    ordered = sorted(value.value for value in values)
    conditions.append(f"{column} IN ({','.join('?' for _ in ordered)})")
    parameters.extend(ordered)


def _validation_conditions(
    report_filter: ValidationIssueFilter,
    conditions: list[str],
    parameters: list[object],
) -> None:
    """Construye predicados de validación con parámetros, nunca SQL de la UI."""
    _validation_in_condition("i.severity", report_filter.severities, conditions, parameters)
    _validation_in_condition("i.category", report_filter.categories, conditions, parameters)
    if report_filter.file_name is not None:
        conditions.append("i.file_name = ?")
        parameters.append(report_filter.file_name)
    if report_filter.feed_id is not None:
        conditions.append("r.feed_id = ?")
        parameters.append(report_filter.feed_id)
    search_text = (report_filter.search_text or "").strip().lower()
    if search_text:
        conditions.append(
            "(contains(lower(coalesce(i.rule_code, '')), ?) "
            "OR contains(lower(coalesce(i.message_key, '')), ?) "
            "OR contains(lower(coalesce(i.field_name, '')), ?) "
            "OR contains(lower(coalesce(i.file_name, '')), ?))"
        )
        parameters.extend([search_text] * 4)


def _validation_issue_summary(row: tuple[object, ...]) -> ValidationIssueSummary:
    parameters = json.loads(str(row[12]))
    if not isinstance(parameters, dict):
        raise ValueError("Los parámetros de la incidencia no son un objeto JSON.")
    entity = (
        ValidationEntity(str(row[9]), str(row[10]))
        if row[9] is not None and row[10] is not None
        else None
    )
    return ValidationIssueSummary(
        str(row[0]),
        _validation_integer(row[1]),
        str(row[2]),
        str(row[3]),
        ValidationSeverity(str(row[4])),
        ValidationCategory(str(row[5])),
        None if row[6] is None else str(row[6]),
        None if row[7] is None else _validation_integer(row[7]),
        None if row[8] is None else str(row[8]),
        entity,
        str(row[11]),
        parameters,
        str(row[13]),
        _validation_integer(row[14]),
    )


def _validation_integer(value: object) -> int:
    if not isinstance(value, int):
        raise ValueError("El valor numérico de la incidencia no es válido.")
    return value


class DuckDbUnitOfWork:
    """Abre una transacción DuckDB y expone puertos sin filtrar SQL a la aplicación."""

    def __init__(
        self, database: ProjectDatabase, schedule_spec: ScheduleSpec | None = None
    ) -> None:
        connection: DatabaseConnection | None = None
        try:
            connection = database.connect()
            connection.execute("BEGIN TRANSACTION")
        except (DatabaseError, duckdb.Error) as error:
            if connection is not None:
                connection.close()
            raise RepositoryError(
                "No se ha podido abrir la unidad de trabajo del proyecto."
            ) from error
        assert connection is not None
        self._connection = connection
        self.projects = DuckDbProjectRepository(self._connection)
        self.feeds = DuckDbFeedRepository(self._connection)
        self.overview = DuckDbFeedOverviewRepository(self._connection)
        self.validation = DuckDbValidationRepository(self._connection)
        self.import_jobs = DuckDbImportJobRepository(self._connection)
        self.operations = DuckDbOperationRepository(self._connection)
        self.service_calendar = DuckDbServiceCalendarRepository(self._connection)
        self.route_explorer = DuckDbRouteExplorerRepository(self._connection)
        self.stop_inspector = DuckDbStopInspectorRepository(self._connection)
        self.raw = (
            DuckDbRawInspectorRepository(self._connection, schedule_spec)
            if schedule_spec is not None
            else None
        )
        self.geometry = DuckDbGeometryRepository(self._connection)
        self.core_subset = DuckDbCoreSubsetRepository(self._connection)
        self._finished = False

    def __enter__(self) -> "DuckDbUnitOfWork":
        return self

    def __exit__(self, exception_type: object, exception: object, traceback: object) -> None:
        if exception_type is None:
            self.commit()
        else:
            self.rollback()
        self._connection.close()

    def commit(self) -> None:
        self._finish("COMMIT")

    def rollback(self) -> None:
        self._finish("ROLLBACK")

    def _finish(self, statement: str) -> None:
        if self._finished:
            return
        try:
            self._connection.execute(statement)
        except DatabaseError as error:
            raise RepositoryError(
                "No se ha podido cerrar la unidad de trabajo del proyecto."
            ) from error
        self._finished = True
