"""Creación del proyecto que precede al primer feed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gtfs_explorer.application.commands.create_project import CreateProject, ProjectCreateError


@pytest.mark.integration
def test_create_project_initializes_descriptor_and_reopens(tmp_path: Path) -> None:
    directory = tmp_path / "Proyecto Ágil"
    directory.mkdir()

    opened = CreateProject(directory).execute()
    try:
        assert opened.descriptor.name == "Proyecto Ágil"
        assert opened.descriptor.status == "READY"
        assert (directory / "data.duckdb").is_file()
        payload = json.loads((directory / "project.json").read_text(encoding="utf-8"))
        assert payload["project_id"] == opened.descriptor.project_id
        assert payload["references"]["database"] == "data.duckdb"
    finally:
        opened.close()


@pytest.mark.integration
def test_create_project_rejects_non_empty_directory_without_overwrite(tmp_path: Path) -> None:
    directory = tmp_path / "existing"
    directory.mkdir()
    sentinel = directory / "keep.txt"
    sentinel.write_text("preservar", encoding="utf-8")

    with pytest.raises(ProjectCreateError, match="vacía"):
        CreateProject(directory).execute()

    assert sentinel.read_text(encoding="utf-8") == "preservar"
