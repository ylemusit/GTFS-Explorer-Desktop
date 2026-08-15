"""Descriptor JSON verificable; DuckDB sigue siendo la fuente de verdad."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from gtfs_explorer.domain.project import FeedMetadata, ProjectMetadata
from gtfs_explorer.infrastructure.duckdb.repositories import DuckDbUnitOfWork

PROJECT_DESCRIPTOR_VERSION = 1


class ProjectDescriptorError(ValueError):
    """El descriptor no cumple el contrato persistible."""


class ProjectDescriptorMismatchError(ProjectDescriptorError):
    """El descriptor no representa los metadatos autoritativos de DuckDB."""


@dataclass(frozen=True)
class ProjectDescriptor:
    project_id: str
    name: str
    status: str
    feed_id: str | None
    feed_sha256: str | None
    references: dict[str, PurePosixPath]

    @classmethod
    def from_metadata(
        cls, project: ProjectMetadata, feed: FeedMetadata | None, project_directory: Path
    ) -> "ProjectDescriptor":
        return cls(
            project.project_id,
            project.name,
            project.status,
            feed.feed_id if feed else None,
            feed.manifest_sha256 if feed else None,
            {
                "database": _relative(project_directory, project_directory / "data.duckdb"),
                "cache": _relative(project_directory, project_directory / "cache"),
                "reports": _relative(project_directory, project_directory / "reports"),
            },
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "version": PROJECT_DESCRIPTOR_VERSION,
            "project_id": self.project_id,
            "name": self.name,
            "status": self.status,
            "feed": None
            if self.feed_id is None
            else {"feed_id": self.feed_id, "manifest_sha256": self.feed_sha256},
            "references": {key: value.as_posix() for key, value in self.references.items()},
        }


def reconcile_project_descriptor(
    project_directory: Path, unit_of_work: DuckDbUnitOfWork
) -> ProjectDescriptor:
    """Regenera un descriptor ausente o rechaza uno inválido/divergente al reabrir."""
    project = unit_of_work.projects.metadata()
    if project is None:
        raise ProjectDescriptorError("DuckDB no contiene metadatos de proyecto.")
    expected = ProjectDescriptor.from_metadata(
        project, unit_of_work.feeds.latest_metadata(), project_directory
    )
    descriptor_path = project_directory / "project.json"
    if not descriptor_path.exists():
        save_project_descriptor(descriptor_path, expected)
        return expected
    actual = load_project_descriptor(descriptor_path)
    if actual.to_dict() != expected.to_dict():
        raise ProjectDescriptorMismatchError("project.json no coincide con los metadatos DuckDB.")
    return actual


def save_project_descriptor(path: Path, descriptor: ProjectDescriptor) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(descriptor.to_dict(), indent=2) + "\n", encoding="utf-8")


def load_project_descriptor(path: Path) -> ProjectDescriptor:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectDescriptorError("project.json no es JSON válido.") from error
    return _from_payload(payload)


def _from_payload(payload: Any) -> ProjectDescriptor:
    if not isinstance(payload, dict) or set(payload) != {
        "version",
        "project_id",
        "name",
        "status",
        "feed",
        "references",
    }:
        raise ProjectDescriptorError("project.json no cumple el esquema v1.")
    if payload["version"] != PROJECT_DESCRIPTOR_VERSION or not all(
        isinstance(payload[key], str) and payload[key] for key in ("project_id", "name", "status")
    ):
        raise ProjectDescriptorError("project.json contiene metadatos inválidos.")
    feed = payload["feed"]
    if feed is not None and (
        not isinstance(feed, dict)
        or set(feed) != {"feed_id", "manifest_sha256"}
        or not all(isinstance(value, str) and value for value in feed.values())
    ):
        raise ProjectDescriptorError("El feed de project.json no es válido.")
    references = payload["references"]
    if not isinstance(references, dict) or set(references) != {"database", "cache", "reports"}:
        raise ProjectDescriptorError("Las referencias de project.json no son válidas.")
    paths = {key: _relative_path(value) for key, value in references.items()}
    return ProjectDescriptor(
        payload["project_id"],
        payload["name"],
        payload["status"],
        None if feed is None else feed["feed_id"],
        None if feed is None else feed["manifest_sha256"],
        paths,
    )


def _relative(base: Path, path: Path) -> PurePosixPath:
    return PurePosixPath(path.relative_to(base).as_posix())


def _relative_path(value: object) -> PurePosixPath:
    if not isinstance(value, str):
        raise ProjectDescriptorError("Las referencias deben ser rutas relativas.")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ProjectDescriptorError("Las referencias deben permanecer dentro del proyecto.")
    return path
