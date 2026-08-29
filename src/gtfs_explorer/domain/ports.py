"""Puertos del dominio para fuentes de importación y persistencia."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Generic, Protocol, TypeVar

from .geometry import TripShapeGeometry
from .operations import Operation, OperationStatus, OperationType
from .overview import FeedOverview
from .project import FeedMetadata, ImportJobMetadata, ProjectMetadata
from .raw import RawPage, RawQuery
from .routes import (
    DirectionSummary,
    RouteSummary,
    ServiceSummary,
    TimelineStop,
    TripSummary,
)
from .service_calendar import ServicePeriod
from .source import InputSource, SourceManifest
from .stops import StopInspection
from .subset import CoreSubsetSource
from .validation import ValidationIssueFilter, ValidationIssueSummary


class SourceInventory(Protocol):
    """Obtiene un manifiesto sin interpretar aún archivos de datos."""

    def inventory(self, source: InputSource) -> SourceManifest: ...


Item = TypeVar("Item")


@dataclass(frozen=True)
class PageRequest:
    """Ventana acotada para resultados que la UI puede paginar."""

    offset: int = 0
    limit: int = 100

    def __post_init__(self) -> None:
        if self.offset < 0:
            raise ValueError("El desplazamiento de página no puede ser negativo.")
        if not 1 <= self.limit <= 500:
            raise ValueError("El tamaño de página debe estar entre 1 y 500.")


@dataclass(frozen=True)
class PagedResult(Generic[Item]):
    """Resultado paginado independiente de la base de datos."""

    items: tuple[Item, ...]
    total: int
    request: PageRequest

    @property
    def next_offset(self) -> int | None:
        next_offset = self.request.offset + len(self.items)
        return next_offset if next_offset < self.total else None


@dataclass(frozen=True)
class FeedSourceFile:
    """Archivo del inventario staging asociado al feed actual."""

    original_name: str
    canonical_name: str
    content_sha256: str
    size_bytes: int
    known_to_schedule_spec: bool
    loaded_row_count: int | None
    staging_table_name: str | None


class ProjectRepository(Protocol):
    """Consultas de control del proyecto, sin exponer la base de datos."""

    def schema_version(self) -> int: ...

    def metadata(self) -> ProjectMetadata | None: ...

    def save_metadata(self, metadata: ProjectMetadata) -> None: ...


class FeedRepository(Protocol):
    """Acceso al inventario del feed; las consultas GTFS concretas van aparte."""

    def source_files(self, page: PageRequest) -> PagedResult[FeedSourceFile]: ...

    def latest_metadata(self) -> FeedMetadata | None: ...

    def save_metadata(self, metadata: FeedMetadata) -> None: ...


class FeedOverviewRepository(Protocol):
    """Resumen consultable de los datos importados y su validación."""

    def overview(self) -> FeedOverview: ...


class ValidationRepository(Protocol):
    """Lista incidencias persistidas para la UI sin exponer DuckDB."""

    def issues(
        self, report_filter: ValidationIssueFilter, page: PageRequest
    ) -> PagedResult[ValidationIssueSummary]: ...

    def files(self, report_filter: ValidationIssueFilter) -> tuple[str, ...]: ...


class ImportJobRepository(Protocol):
    def save_metadata(self, metadata: ImportJobMetadata) -> None: ...

    def recover_interrupted(self) -> tuple[str, ...]: ...


class OperationRepository(Protocol):
    def start(
        self,
        operation_id: str,
        project_id: str,
        operation_type: OperationType,
        started_at: datetime,
    ) -> None: ...
    def finish(
        self,
        operation_id: str,
        status: OperationStatus,
        finished_at: datetime,
        error_code: str | None = None,
    ) -> None: ...
    def attach_import_detail(self, operation_id: str, feed_id: str, job_id: str) -> None: ...
    def attach_validation_detail(
        self, operation_id: str, feed_id: str, validation_batch_id: str | None = None
    ) -> None: ...
    def attach_export_detail(
        self,
        operation_id: str,
        feed_id: str,
        export_format: str,
        artifact_name: str | None = None,
        artifact_sha256: str | None = None,
        artifact_size_bytes: int | None = None,
    ) -> None: ...
    def list_operations(
        self,
        project_id: str,
        page: PageRequest,
        operation_type: OperationType | None = None,
        status: OperationStatus | None = None,
    ) -> PagedResult[Operation]: ...


class ServiceCalendarRepository(Protocol):
    """Consulta fechas de servicio GTFS sin acoplarlas a una interfaz."""

    def service_ids_on(self, service_date: date) -> tuple[str, ...]: ...

    def service_period(self) -> ServicePeriod | None: ...


class RouteExplorerRepository(Protocol):
    """Consultas relacionales del feed para el explorador, sin UI ni SQL."""

    def routes(self, page: PageRequest) -> PagedResult[RouteSummary]: ...

    def services_for_route(
        self, route_id: str, page: PageRequest
    ) -> PagedResult[ServiceSummary]: ...

    def directions_for_route_service(
        self, route_id: str, service_id: str, page: PageRequest
    ) -> PagedResult[DirectionSummary]: ...

    def trips_for_route_service_direction(
        self, route_id: str, service_id: str, direction_id: int | None, page: PageRequest
    ) -> PagedResult[TripSummary]: ...

    def trip_timeline(self, trip_id: str, page: PageRequest) -> PagedResult[TimelineStop]: ...


class StopInspectorRepository(Protocol):
    """Reconstruye contexto de parada a partir del horario GTFS importado."""

    def inspect_stop(
        self, stop_id: str, service_date: date | None, page: PageRequest
    ) -> StopInspection: ...


class GeometryRepository(Protocol):
    """Obtiene la geometría y métricas para un viaje y su shape declarado."""

    def trip_shape(self, trip_id: str) -> TripShapeGeometry: ...


class RawInspectorRepository(Protocol):
    """Consulta staging a partir de un contrato estructurado, nunca SQL de la UI."""

    def query(self, request: RawQuery) -> RawPage: ...


class CoreSubsetRepository(Protocol):
    """Lee solo las relaciones core necesarias para calcular Mini-GTFS."""

    def core_subset_source(self) -> CoreSubsetSource: ...


class UnitOfWork(Protocol):
    """Límite transaccional para repositorios de un proyecto."""

    @property
    def projects(self) -> ProjectRepository: ...

    @property
    def feeds(self) -> FeedRepository: ...

    @property
    def overview(self) -> FeedOverviewRepository: ...

    @property
    def validation(self) -> ValidationRepository: ...

    @property
    def import_jobs(self) -> ImportJobRepository: ...

    @property
    def operations(self) -> OperationRepository: ...

    @property
    def service_calendar(self) -> ServiceCalendarRepository: ...

    @property
    def route_explorer(self) -> RouteExplorerRepository: ...

    @property
    def stop_inspector(self) -> StopInspectorRepository: ...

    @property
    def raw(self) -> RawInspectorRepository | None: ...

    @property
    def geometry(self) -> GeometryRepository: ...

    @property
    def core_subset(self) -> CoreSubsetRepository: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...
