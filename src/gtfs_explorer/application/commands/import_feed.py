"""Orquesta una importación GTFS completa sin depender de la interfaz Qt."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from gtfs_explorer.application.jobs.import_job import (
    CancelToken,
    ImportPhase,
    ImportProgress,
    ProgressMode,
)
from gtfs_explorer.domain.errors import ImportCancelled
from gtfs_explorer.domain.operations import OperationStatus, OperationType, utc_now_naive
from gtfs_explorer.domain.project import (
    FeedMetadata,
    FeedStatus,
    ImportJobMetadata,
    JobState,
    ProjectMetadata,
)
from gtfs_explorer.domain.source import InputSource, InputSourceKind, SourceManifest
from gtfs_explorer.domain.spec import ScheduleSpec
from gtfs_explorer.domain.validation import ValidationRuleRegistry, ValidationSeverity
from gtfs_explorer.infrastructure.duckdb.database import ProjectDatabase
from gtfs_explorer.infrastructure.duckdb.repositories import DuckDbUnitOfWork
from gtfs_explorer.infrastructure.importing.directory_source import DirectorySource
from gtfs_explorer.infrastructure.importing.normalizers.core import CoreNormalizer
from gtfs_explorer.infrastructure.importing.normalizers.geometry import GeometryNormalizer
from gtfs_explorer.infrastructure.importing.normalizers.optional import OptionalNormalizer
from gtfs_explorer.infrastructure.importing.staging_loader import StagingLoader
from gtfs_explorer.infrastructure.importing.zip_source import ZipSource
from gtfs_explorer.infrastructure.validation.best_practices import BestPracticeValidationRule
from gtfs_explorer.infrastructure.validation.engine import ValidationEngine
from gtfs_explorer.infrastructure.validation.fields import FieldValidationRule
from gtfs_explorer.infrastructure.validation.geometry import GeometryValidationRule
from gtfs_explorer.infrastructure.validation.references import ReferenceValidationRule
from gtfs_explorer.infrastructure.validation.structure import StructureValidationRule
from gtfs_explorer.infrastructure.validation.timetable import TimetableValidationRule

_WORK_PHASES = (
    ImportPhase.PREFLIGHT,
    ImportPhase.STAGING,
    ImportPhase.NORMALIZING,
    ImportPhase.VALIDATING,
    ImportPhase.COMMITTING,
)


@dataclass(frozen=True)
class ImportFeedResult:
    job_id: str
    feed_id: str
    state: JobState
    issue_count: int


class ImportFeed:
    """Compone los pasos ya validados en un trabajo rastreable y recuperable."""

    def __init__(
        self,
        database: ProjectDatabase,
        project: ProjectMetadata,
        source: InputSource,
        specification: ScheduleSpec,
        *,
        job_id: str | None = None,
        feed_id: str | None = None,
        on_progress: Callable[[ImportProgress], None] | None = None,
        has_free_space: Callable[[int], bool] | None = None,
    ) -> None:
        self._database = database
        self._project = project
        self._source = source
        self._specification = specification
        self._job_id = job_id or str(uuid4())
        self._feed_id = feed_id or str(uuid4())
        self._on_progress = on_progress or (lambda progress: None)
        self._has_free_space = has_free_space or self._default_has_free_space
        self._manifest: SourceManifest | None = None
        self._operation_started = False
        self._staging_counts: dict[str, int] = {}

    def execute(self, cancel_token: CancelToken | None = None) -> ImportFeedResult:
        """Ejecuta una vez el feed y deja siempre un estado terminal persistido."""
        token = cancel_token or CancelToken()
        manifest: SourceManifest | None = None
        extracted_directory: Path | None = None
        issue_count = 0
        self._save(JobState.RUNNING, ImportPhase.PREFLIGHT, 0.0)
        try:
            self._start(ImportPhase.PREFLIGHT, token)
            manifest, source_directory, extracted_directory = self._preflight(token)
            self._manifest = manifest

            self._start(ImportPhase.STAGING, token)
            StagingLoader().load(
                self._database,
                source_directory,
                manifest,
                self._specification,
                is_cancelled=token.is_cancelled,
                on_progress=self._staging_progress,
            )

            self._start(ImportPhase.NORMALIZING, token)
            self._detail(ImportPhase.NORMALIZING, "core")
            core = CoreNormalizer().normalize(
                self._database, self._specification, is_cancelled=token.is_cancelled
            )
            self._detail(ImportPhase.NORMALIZING, "shapes")
            geometry = GeometryNormalizer().normalize(
                self._database, self._specification, is_cancelled=token.is_cancelled
            )
            self._detail(ImportPhase.NORMALIZING, "opcionales")
            optional = OptionalNormalizer().normalize(
                self._database, self._specification, is_cancelled=token.is_cancelled
            )
            issue_count = core.issue_count + geometry.issue_count + optional.issue_count
            self._raise_if_cancelled(token)

            self._start(ImportPhase.VALIDATING, token)
            registry = ValidationRuleRegistry()
            registry.register(
                StructureValidationRule(manifest, source_directory, self._specification)
            )
            with self._database.connection() as connection:
                registry.register(FieldValidationRule(connection, self._specification))
                registry.register(ReferenceValidationRule(connection, self._specification))
                registry.register(TimetableValidationRule(connection))
                registry.register(GeometryValidationRule(connection))
                registry.register(BestPracticeValidationRule(connection))
                ValidationEngine(registry).execute(
                    connection,
                    feed_id=self._feed_id,
                    batch_id=f"{self._job_id}:structure",
                    is_cancelled=token.is_cancelled,
                    on_progress=lambda rule: self._detail(ImportPhase.VALIDATING, rule),
                )
            issue_count = self._error_count()
            if issue_count:
                self._save(JobState.INVALID, ImportPhase.VALIDATING, 4 / len(_WORK_PHASES))
                return ImportFeedResult(self._job_id, self._feed_id, JobState.INVALID, issue_count)

            self._start(ImportPhase.COMMITTING, token)
            self._save(JobState.READY, ImportPhase.COMMITTING, 1.0)
            return ImportFeedResult(self._job_id, self._feed_id, JobState.READY, 0)
        except ImportCancelled:
            self._save(JobState.CANCELLED, ImportPhase.CLEANUP, 0.0, "CANCELLED")
            return ImportFeedResult(self._job_id, self._feed_id, JobState.CANCELLED, issue_count)
        except Exception as error:
            self._save(JobState.FAILED, ImportPhase.CLEANUP, 0.0, type(error).__name__)
            return ImportFeedResult(self._job_id, self._feed_id, JobState.FAILED, issue_count)
        finally:
            if extracted_directory is not None:
                self._cleanup(extracted_directory)

    def _preflight(self, token: CancelToken) -> tuple[SourceManifest, Path, Path | None]:
        if self._source.kind is InputSourceKind.ARCHIVE:
            extracted = self._database.temporary_directory / f"import-{self._job_id}"
            self._cleanup(extracted)
            manifest = ZipSource().extract(
                self._source,
                extracted,
                has_free_space=self._has_free_space,
                is_cancelled=token.is_cancelled,
            )
            return manifest, extracted, extracted
        manifest = DirectorySource().inventory(self._source)
        source_directory = (
            self._source.path.parent
            if self._source.kind is InputSourceKind.FILE
            else self._source.path
        )
        return manifest, source_directory, None

    def _start(self, phase: ImportPhase, token: CancelToken) -> None:
        completed = _WORK_PHASES.index(phase)
        self._save(JobState.RUNNING, phase, completed / len(_WORK_PHASES))
        self._on_progress(
            ImportProgress(
                phase,
                completed,
                len(_WORK_PHASES),
                mode=ProgressMode.INDETERMINATE,
            )
        )
        self._raise_if_cancelled(token)

    def _detail(self, phase: ImportPhase, detail: str) -> None:
        completed = _WORK_PHASES.index(phase)
        self._on_progress(ImportProgress(phase, completed, len(_WORK_PHASES), detail=detail))

    def _staging_progress(self, filename: str, count: int) -> None:
        self._staging_counts[filename] = count
        self._on_progress(
            ImportProgress(
                ImportPhase.STAGING,
                _WORK_PHASES.index(ImportPhase.STAGING),
                len(_WORK_PHASES),
                detail=filename,
                completed=count,
                unit="filas",
                mode=ProgressMode.INDETERMINATE,
            )
        )

    def _save(
        self, state: JobState, phase: ImportPhase, progress: float, error_code: str | None = None
    ) -> None:
        manifest_hash = self._manifest.manifest_sha256 if self._manifest else "0" * 64
        operation_started = False
        with DuckDbUnitOfWork(self._database) as unit_of_work:
            unit_of_work.projects.save_metadata(self._project)
            unit_of_work.feeds.save_metadata(
                FeedMetadata(
                    self._feed_id,
                    self._project.project_id,
                    self._source.path.name,
                    manifest_hash,
                    self._source.kind.value,
                    self._specification.revision,
                    FeedStatus.IMPORTED
                    if state in {JobState.READY, JobState.INVALID}
                    else FeedStatus.CANCELLED
                    if state is JobState.CANCELLED
                    else FeedStatus.FAILED,
                )
            )
            unit_of_work.import_jobs.save_metadata(
                ImportJobMetadata(self._job_id, self._feed_id, state, phase, progress, error_code)
            )
            if state is JobState.RUNNING and not self._operation_started:
                unit_of_work.operations.start(
                    self._job_id,
                    self._project.project_id,
                    OperationType.IMPORT,
                    utc_now_naive(),
                )
                unit_of_work.operations.attach_import_detail(
                    self._job_id, self._feed_id, self._job_id
                )
                operation_started = True
            elif state is not JobState.RUNNING:
                unit_of_work.operations.finish(
                    self._job_id,
                    {
                        JobState.READY: OperationStatus.COMPLETED,
                        JobState.INVALID: OperationStatus.COMPLETED,
                        JobState.CANCELLED: OperationStatus.CANCELLED,
                        JobState.FAILED: OperationStatus.FAILED,
                    }[state],
                    utc_now_naive(),
                    error_code.upper()
                    if error_code is not None and state in {JobState.CANCELLED, JobState.FAILED}
                    else None,
                )
        if operation_started:
            self._operation_started = True

    def _error_count(self) -> int:
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT (SELECT count(*) FROM normalization_issues WHERE severity = 'ERROR') + "
                "(SELECT count(*) FROM validation_issues WHERE severity IN (?, ?))",
                [ValidationSeverity.ERROR, ValidationSeverity.FATAL],
            ).fetchone()
        assert row is not None
        return int(row[0])

    @staticmethod
    def _raise_if_cancelled(token: CancelToken) -> None:
        if token.is_cancelled():
            raise ImportCancelled("Importación cancelada.")

    def _cleanup(self, directory: Path) -> None:
        temporary_root = self._database.temporary_directory.resolve()
        target = directory.resolve()
        if target.parent != temporary_root:
            raise ValueError(
                "La limpieza de importación debe permanecer en el temporal del proyecto."
            )
        if target.exists():
            shutil.rmtree(target)

    def _default_has_free_space(self, required_bytes: int) -> bool:
        return shutil.disk_usage(self._database.temporary_directory).free >= required_bytes
