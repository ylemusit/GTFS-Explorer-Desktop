"""Regresiones de exclusividad y ciclo de vida del workspace P1-19."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from gtfs_explorer.application.commands.create_project import CreateProject
from gtfs_explorer.application.commands.open_project import (
    OpenProject,
    ProjectWriterLock,
    ProjectWriterLockedError,
    WriterLockState,
)


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    opened = CreateProject(project).execute()
    opened.close()
    return project


def _child_environment() -> dict[str, str]:
    environment = os.environ.copy()
    source_root = str(Path("src").resolve())
    environment["PYTHONPATH"] = os.pathsep.join(
        item for item in (source_root, environment.get("PYTHONPATH", "")) if item
    )
    return environment


def test_lock_metadata_is_minimal_and_release_is_idempotent(tmp_path: Path) -> None:
    project = _project(tmp_path)
    lock = ProjectWriterLock(project)

    lock.acquire()
    payload = lock.metadata
    lock.release()
    lock.release()

    assert payload is not None
    assert set(payload) == {"lock_version", "pid", "created_at"}
    assert payload["pid"] == os.getpid()
    assert not (project / ".writer.lock").exists()


def test_stale_sentinel_is_reused_without_touching_duckdb(tmp_path: Path) -> None:
    project = _project(tmp_path)
    database_before = (project / "data.duckdb").read_bytes()
    (project / ".writer.lock").write_text("{not-json", encoding="utf-8")

    lock = ProjectWriterLock(project)
    lock.acquire()
    try:
        assert lock.state is WriterLockState.INVALID
    finally:
        lock.release()

    assert (project / "data.duckdb").read_bytes() == database_before


def test_valid_stale_sentinel_is_classified_stale(tmp_path: Path) -> None:
    project = _project(tmp_path)
    stale = ProjectWriterLock(project)
    stale.acquire()
    metadata = stale.metadata
    stale.release()
    assert metadata is not None
    (project / ".writer.lock").write_text(json.dumps(metadata), encoding="utf-8")

    reused = ProjectWriterLock(project)
    reused.acquire()
    try:
        assert reused.state is WriterLockState.STALE
    finally:
        reused.release()


def test_second_subprocess_writer_is_rejected_and_lock_is_released_after_exit(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    holder_code = """
from pathlib import Path
import sys
from gtfs_explorer.application.commands.open_project import OpenProject
opened = OpenProject(Path(sys.argv[1])).execute()
print('READY', flush=True)
input()
opened.close()
"""
    holder = subprocess.Popen(
        [sys.executable, "-c", holder_code, str(project)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_child_environment(),
        cwd=Path.cwd(),
    )
    assert holder.stdout is not None
    assert holder.stdout.readline().strip() == "READY"
    try:
        with pytest.raises(ProjectWriterLockedError, match="en uso"):
            OpenProject(project).execute()
    finally:
        holder.kill()
        holder.wait(timeout=10)

    for _ in range(20):
        try:
            with OpenProject(project).execute() as reopened:
                assert reopened.directory == project.resolve()
            break
        except ProjectWriterLockedError:
            time.sleep(0.1)
    else:
        pytest.fail("El lock del proceso terminado no se liberó")


def test_acquisition_race_has_one_winner(tmp_path: Path) -> None:
    """La carrera real Windows no deja escapar PermissionError del bootstrap."""
    for iteration in range(20):
        iteration_root = tmp_path / str(iteration)
        iteration_root.mkdir()
        project = _project(iteration_root)
        results: list[str] = []
        opened = []
        failures: list[BaseException] = []
        barrier = threading.Barrier(2)

        def attempt() -> None:
            barrier.wait()
            try:
                current = OpenProject(project).execute()
                opened.append(current)
                results.append("won")
            except ProjectWriterLockedError:
                results.append("blocked")
            except BaseException as error:
                failures.append(error)

        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        for current in opened:
            current.close()

        assert not failures
        assert sorted(results) == ["blocked", "won"]


def test_permission_error_without_active_writer_is_not_normalized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    lock = ProjectWriterLock(project)
    original_open = Path.open

    def deny_lock_open(path: Path, mode: str = "r", *args: object, **kwargs: object) -> Any:
        if path == project / ".writer.lock" and mode == "a+b":
            raise PermissionError("denegado por ACL")
        return original_open(path)

    monkeypatch.setattr(Path, "open", deny_lock_open)

    with pytest.raises(PermissionError, match="ACL"):
        lock.acquire()
