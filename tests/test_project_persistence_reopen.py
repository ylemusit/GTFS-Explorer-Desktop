"""Regresión P0-003: persistencia al cerrar y reabrir un proyecto."""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from dataclasses import asdict, is_dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any

import pytest

from gtfs_explorer.application.commands.create_project import CreateProject
from gtfs_explorer.application.commands.import_feed import ImportFeed
from gtfs_explorer.application.commands.open_project import OpenProject
from gtfs_explorer.domain.ports import PageRequest
from gtfs_explorer.domain.project import JobState, ProjectMetadata, ProjectStatus
from gtfs_explorer.domain.source import InputSource, InputSourceKind
from gtfs_explorer.domain.spec import load_schedule_spec
from gtfs_explorer.infrastructure.duckdb.repositories import DuckDbUnitOfWork
from gtfs_explorer.infrastructure.filesystem.project_descriptor import (
    ProjectDescriptor,
    save_project_descriptor,
)

SPEC_PATH = Path("schemas/gtfs_schedule/2026-04-27/spec.json")
FIXTURE_DIRECTORY = Path("tests/fixtures/specs")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date,)):
        return value.isoformat()
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _write_fixture(source: Path, fixture_name: str) -> None:
    fixture = json.loads((FIXTURE_DIRECTORY / f"{fixture_name}.json").read_text(encoding="utf-8"))
    source.mkdir()
    for filename, table in fixture["tables"].items():
        with (source / filename).open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=table["headers"], lineterminator="\n")
            writer.writeheader()
            writer.writerows(table["rows"])


def _synchronise_descriptor(project: Path) -> None:
    with OpenProject(project).execute() as opened:
        with DuckDbUnitOfWork(opened.database) as unit_of_work:
            metadata = unit_of_work.projects.metadata()
            feed = unit_of_work.feeds.latest_metadata()
            assert metadata is not None
            descriptor = ProjectDescriptor.from_metadata(metadata, feed, project)
    save_project_descriptor(project / "project.json", descriptor)


def _snapshot(project: Path) -> dict[str, Any]:
    descriptor = json.loads((project / "project.json").read_text(encoding="utf-8"))
    with OpenProject(project).execute() as opened:
        with DuckDbUnitOfWork(opened.database) as unit_of_work:
            metadata = unit_of_work.projects.metadata()
            feed = unit_of_work.feeds.latest_metadata()
            overview = unit_of_work.overview.overview()
            routes = unit_of_work.route_explorer.routes(PageRequest(limit=500))
            with opened.database.connection() as connection:
                job_row = connection.execute(
                    "SELECT state FROM import_jobs ORDER BY started_at DESC LIMIT 1"
                ).fetchone()
            assert metadata is not None
            assert feed is not None
            assert job_row is not None
            snapshot = {
                "project": metadata,
                "feed": feed,
                "project_status": metadata.status,
                "feed_status": feed.status,
                "job_state": job_row[0],
                "validation_status": overview.validation.statuses,
                "issue_count": overview.validation.total_issue_count,
                "inventory": overview.files,
                "metrics": overview.metrics,
                "service_period": overview.period,
                # Es una consulta funcional de tablas normalizadas, no una
                # comprobación de que el fichero DuckDB exista solamente.
                "normalised_routes": routes,
            }
    snapshot["descriptor"] = descriptor
    return _jsonable(snapshot)


def _import_fixture(project: Path, source: Path, fixture_name: str) -> None:
    project.mkdir()
    opened = CreateProject(project, name=f"P0-003 {fixture_name}").execute()
    try:
        metadata = ProjectMetadata(
            opened.descriptor.project_id,
            opened.descriptor.name,
            ProjectStatus(opened.descriptor.status),
        )
        result = ImportFeed(
            opened.database,
            metadata,
            InputSource(source, InputSourceKind.DIRECTORY),
            load_schedule_spec(SPEC_PATH),
        ).execute()
        assert result.state in {JobState.READY, JobState.INVALID}
    finally:
        opened.close()
    # Es la sincronización que realiza MainWindow._import_finished después del
    # comando real de aplicación; no se usa como flujo alternativo de importación.
    _synchronise_descriptor(project)


def _child_snapshot(project: Path) -> dict[str, Any]:
    code = """
import json
from dataclasses import asdict, is_dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from gtfs_explorer.application.commands.open_project import OpenProject
from gtfs_explorer.domain.ports import PageRequest
from gtfs_explorer.infrastructure.duckdb.repositories import DuckDbUnitOfWork

def convert(value):
    if isinstance(value, Enum): return value.value
    if isinstance(value, date): return value.isoformat()
    if is_dataclass(value): return convert(asdict(value))
    if isinstance(value, dict): return {str(k): convert(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)): return [convert(v) for v in value]
    return value

project = Path(__import__('sys').argv[1])
with OpenProject(project).execute() as opened:
    with DuckDbUnitOfWork(opened.database) as uow:
        metadata = uow.projects.metadata()
        feed = uow.feeds.latest_metadata()
        overview = uow.overview.overview()
        routes = uow.route_explorer.routes(PageRequest(limit=500))
        with opened.database.connection() as connection:
            row = connection.execute(
                'SELECT state FROM import_jobs ORDER BY started_at DESC LIMIT 1'
            ).fetchone()
        assert metadata is not None and feed is not None and row is not None
        result = {'project': metadata, 'feed': feed, 'project_status': metadata.status,
                  'feed_status': feed.status, 'job_state': row[0],
                  'validation_status': overview.validation.statuses,
                  'issue_count': overview.validation.total_issue_count,
                  'inventory': overview.files, 'metrics': overview.metrics,
                  'service_period': overview.period, 'normalised_routes': routes}
result['descriptor'] = json.loads((project / 'project.json').read_text(encoding='utf-8'))
print(json.dumps(convert(result), sort_keys=True))
"""
    environment = os.environ.copy()
    source_root = str(Path("src").resolve())
    environment["PYTHONPATH"] = os.pathsep.join(
        item for item in (source_root, environment.get("PYTHONPATH", "")) if item
    )
    completed = subprocess.run(
        [sys.executable, "-c", code, str(project.resolve())],
        check=True,
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
        env=environment,
    )
    return json.loads(completed.stdout)


def test_valid_project_close_reopen_is_lossless_and_repeated(tmp_path: Path) -> None:
    project = tmp_path / "valid-project"
    source = tmp_path / "valid-source"
    _write_fixture(source, "valid_full")
    _import_fixture(project, source, "valid_full")

    before = _snapshot(project)
    assert before["feed_status"] == "IMPORTED"
    assert before["validation_status"] == ["VALID"]
    assert isinstance(before["issue_count"], int)

    # open -> close -> open -> close -> open: cada apertura consulta lo mismo.
    for _ in range(3):
        assert _snapshot(project) == before

    assert _child_snapshot(project) == before
    assert not (project / ".writer.lock").exists()

    descriptor = json.loads((project / "project.json").read_text(encoding="utf-8"))
    assert descriptor == before["descriptor"]
    assert set(descriptor) == {"version", "project_id", "name", "status", "feed", "references"}
    assert "validation" not in descriptor
    assert "statistics" not in descriptor


def test_invalid_project_close_reopen_remains_imported_invalid_and_queryable(
    tmp_path: Path,
) -> None:
    project = tmp_path / "invalid-project"
    source = tmp_path / "invalid-source"
    _write_fixture(source, "invalid_core")
    _import_fixture(project, source, "invalid_core")

    before = _snapshot(project)
    assert before["feed_status"] == "IMPORTED"
    assert before["validation_status"] == ["INVALID"]
    assert before["issue_count"] > 0
    assert before["job_state"] == "INVALID"
    assert before["normalised_routes"]

    for _ in range(3):
        current = _snapshot(project)
        assert current == before
        assert current["feed_status"] == "IMPORTED"
        assert current["job_state"] != "FAILED"
        assert current["validation_status"] == ["INVALID"]


@pytest.mark.integration
def test_valid_project_reopens_in_a_new_python_process(tmp_path: Path) -> None:
    project = tmp_path / "process-project"
    source = tmp_path / "process-source"
    _write_fixture(source, "valid_full")
    _import_fixture(project, source, "valid_full")

    before = _snapshot(project)
    assert _child_snapshot(project) == before
