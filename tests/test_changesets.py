"""Contrato del borrador no destructivo del editor visual."""

from pathlib import Path

import pytest

from gtfs_explorer.domain.changesets import (
    EditorCommand,
    EditorCommandKind,
    WorkingCopy,
    WorkingCopyStore,
)


def _stop(name: str = "Centro", lat: float = 40.0) -> dict[str, object]:
    return {"stop_id": "s1", "stop_name": name, "stop_lat": lat, "stop_lon": -3.0}


def _move(before: dict[str, object], after: dict[str, object]) -> EditorCommand:
    return EditorCommand(EditorCommandKind.MOVE_STOP, ("stops", "s1"), before, after)


def test_original_is_immutable_and_dirty_tracks_working_copy() -> None:
    original = {("stops", "s1"): _stop()}
    working = WorkingCopy(original)

    command = _move(_stop(), _stop(lat=41.0))
    working.apply(command)
    returned_original = working.original
    returned_original[("stops", "s1")]["stop_lat"] = 99.0

    assert original[("stops", "s1")]["stop_lat"] == 40.0
    assert working.original[("stops", "s1")]["stop_lat"] == 40.0
    assert working.dirty is True

    working.discard()
    assert working.entities == original
    assert working.dirty is False


def test_apply_rejects_stale_precondition() -> None:
    working = WorkingCopy({("stops", "s1"): _stop()})
    working.apply(_move(_stop(), _stop(lat=41.0)))

    with pytest.raises(ValueError, match="precondición"):
        working.apply(_move(_stop(), _stop(lat=42.0)))


def test_undo_redo_and_new_edit_invalidate_redo_branch() -> None:
    working = WorkingCopy({("stops", "s1"): _stop()})
    working.apply(_move(_stop(), _stop(lat=41.0)))
    working.apply(_move(_stop(lat=41.0), _stop(lat=42.0)))

    working.undo()
    assert working.get(("stops", "s1"))["stop_lat"] == 41.0
    working.redo()
    assert working.get(("stops", "s1"))["stop_lat"] == 42.0
    working.undo()
    working.apply(_move(_stop(lat=41.0), _stop(lat=43.0)))

    assert working.changeset.redo_available is False
    assert [event.action for event in working.changeset.history] == [
        "APPLY",
        "APPLY",
        "UNDO",
        "REDO",
        "UNDO",
        "APPLY",
    ]


def test_save_and_load_preserve_state_and_history(tmp_path: Path) -> None:
    working = WorkingCopy({("stops", "s1"): _stop()})
    working.apply(_move(_stop(), _stop(lat=41.0)))
    path = tmp_path / "draft.json"

    WorkingCopyStore().save(working, path)
    restored = WorkingCopyStore().load(path)

    assert restored.entities == working.entities
    assert restored.original == working.original
    assert restored.dirty is True
    assert restored.changeset.commands[0].kind is EditorCommandKind.MOVE_STOP
    restored.undo()
    assert restored.dirty is False
