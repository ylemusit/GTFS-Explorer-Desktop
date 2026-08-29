"""Creación segura de un proyecto local antes de su primera importación."""

from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from gtfs_explorer.application.commands.open_project import OpenedProject, OpenProject
from gtfs_explorer.domain.project import ProjectMetadata, ProjectStatus
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.infrastructure.duckdb.repositories import DuckDbUnitOfWork
from gtfs_explorer.infrastructure.filesystem.project_descriptor import (
    ProjectDescriptor,
    save_project_descriptor,
)


class ProjectCreateError(RuntimeError):
    """La carpeta elegida no permite crear un proyecto sin sobrescribir datos."""


class CreateProject:
    """Inicializa DuckDB y su descriptor en una carpeta vacía y abre el proyecto."""

    def __init__(self, project_directory: Path, *, name: str | None = None) -> None:
        self._project_directory = project_directory
        self._name = name

    def execute(self) -> OpenedProject:
        directory = self._project_directory.resolve()
        if not directory.is_dir():
            raise ProjectCreateError("Seleccione una carpeta existente para el proyecto.")
        if any(directory.iterdir()):
            raise ProjectCreateError("La carpeta del nuevo proyecto debe estar vacía.")

        name = (self._name or directory.name).strip()
        if not name:
            raise ProjectCreateError("El proyecto debe tener un nombre.")
        metadata = ProjectMetadata(str(uuid4()), name, ProjectStatus.READY)
        database = ProjectDatabase(
            directory / "data.duckdb",
            directory / "temp",
            settings=DatabaseSettings(memory_limit="512MB"),
        )
        try:
            with DuckDbUnitOfWork(database) as unit_of_work:
                unit_of_work.projects.save_metadata(metadata)
            save_project_descriptor(
                directory / "project.json",
                ProjectDescriptor.from_metadata(metadata, None, directory),
            )
            return OpenProject(directory).execute()
        except Exception as error:
            # El directorio elegido por el usuario se conserva; solo se retiran
            # artefactos creados por esta tentativa fallida.
            for path in (
                directory / "project.json",
                directory / "data.duckdb",
                directory / "data.duckdb.pre-migration.bak",
            ):
                path.unlink(missing_ok=True)
            for transient in (directory / "temp", directory / "cache"):
                if transient.is_dir():
                    shutil.rmtree(transient)
            raise ProjectCreateError("No se ha podido crear el proyecto local.") from error
