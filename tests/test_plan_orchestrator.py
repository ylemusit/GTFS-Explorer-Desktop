"""Pruebas de recuperación y configuración del orquestador local."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _orchestrator_fixture(tmp_path: Path) -> tuple[Path, Path]:
    fixture_root = tmp_path / "orchestrator-repository"
    relative_files = (
        "tools/plan_orchestrator.ps1",
        "tools/task_result.schema.json",
        "tools/check.ps1",
        "docs/PLAN_MAESTRO_CONSTRUCCION.md",
        "docs/TASK_STATUS.json",
        "docs/TAREAS_PENDIENTES.md",
        "docs/CURRENT_STATE.md",
    )
    for relative_file in relative_files:
        source = REPOSITORY_ROOT / relative_file
        destination = fixture_root / relative_file
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return fixture_root, fixture_root / "tools" / "plan_orchestrator.ps1"


def _run_orchestrator(script: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    pwsh = shutil.which("pwsh")
    assert pwsh is not None, "PowerShell 7 es un requisito del orquestador"
    return subprocess.run(
        [pwsh, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(script), *arguments],
        cwd=script.parents[1],
        text=True,
        capture_output=True,
        check=False,
    )


def _powershell_literal(value: Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _read_state(fixture_root: Path) -> dict[str, object]:
    return json.loads((fixture_root / "docs" / "TASK_STATUS.json").read_text(encoding="utf-8"))


def _write_state(fixture_root: Path, state: dict[str, object]) -> None:
    (fixture_root / "docs" / "TASK_STATUS.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _task(state: dict[str, object], task_id: str) -> dict[str, object]:
    tasks = state["tasks"]
    assert isinstance(tasks, list)
    return next(task for task in tasks if isinstance(task, dict) and task["id"] == task_id)


def test_recover_removes_stale_lock_and_blocks_interrupted_task(tmp_path: Path) -> None:
    fixture_root, script = _orchestrator_fixture(tmp_path)
    state = _read_state(fixture_root)
    interrupted = _task(state, "T013")
    interrupted["status"] = "IN_PROGRESS"
    interrupted["started_at"] = "2026-08-12T03:07:21+02:00"
    _write_state(fixture_root, state)
    lock_path = fixture_root / ".codex-runs" / "orchestrator.lock"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text("pid=2147483647\nstarted_at=2026-08-12T03:07:21+02:00\n", encoding="utf-8")
    historical_run = lock_path.parent / "T001-historical"
    historical_run.mkdir()
    (historical_run / "process.json").write_text(
        json.dumps({"exit_code": 0, "finished_at": "2026-08-12T02:20:08+02:00"}),
        encoding="utf-8",
    )

    result = _run_orchestrator(script, "-Action", "Recover")

    assert result.returncode == 0, result.stderr
    assert not lock_path.exists()
    recovered = _task(_read_state(fixture_root), "T013")
    assert recovered["status"] == "BLOCKED"
    assert "sin resultado verificable" in str(recovered["blocker"])


def test_recover_refuses_to_remove_active_lock(tmp_path: Path) -> None:
    fixture_root, script = _orchestrator_fixture(tmp_path)
    lock_path = fixture_root / ".codex-runs" / "orchestrator.lock"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text(
        f"pid={os.getpid()}\nstarted_at=2026-08-12T03:07:21+02:00\n",
        encoding="utf-8",
    )

    result = _run_orchestrator(script, "-Action", "Recover")

    assert result.returncode != 0
    assert lock_path.exists()
    assert "sigue activo" in result.stderr


def test_configure_changes_executor_explicitly(tmp_path: Path) -> None:
    fixture_root, script = _orchestrator_fixture(tmp_path)
    state = _read_state(fixture_root)
    tasks = state["tasks"]
    assert isinstance(tasks, list)
    for task in tasks:
        if isinstance(task, dict) and task.get("status") == "IN_PROGRESS":
            task["status"] = "READY"
            task["started_at"] = None
    state["executor"] = {"model": "gpt-5.6-luna", "reasoning_effort": "medium"}
    _write_state(fixture_root, state)

    result = _run_orchestrator(
        script,
        "-Action",
        "Configure",
        "-Model",
        "gpt-5.6-terra",
        "-ReasoningEffort",
        "medium",
    )

    assert result.returncode == 0, result.stderr
    state = _read_state(fixture_root)
    assert state["executor"] == {"model": "gpt-5.6-terra", "reasoning_effort": "medium"}


def test_retry_clears_attempt_metadata_but_keeps_history_files(tmp_path: Path) -> None:
    fixture_root, script = _orchestrator_fixture(tmp_path)
    state = _read_state(fixture_root)
    blocked = _task(state, "T013")
    blocked.update(
        {
            "status": "BLOCKED",
            "started_at": "2026-08-12T03:07:21+02:00",
            "completed_at": "2026-08-12T03:08:21+02:00",
            "session_id": "example",
            "summary": "partial",
            "blocker": {"type": "TECHNICAL"},
        }
    )
    _write_state(fixture_root, state)

    result = _run_orchestrator(script, "-Action", "Retry", "-TaskId", "T013")

    assert result.returncode == 0, result.stderr
    retried = _task(_read_state(fixture_root), "T013")
    assert retried["status"] == "READY"
    assert retried["started_at"] is None
    assert retried["completed_at"] is None
    assert retried["session_id"] is None
    assert retried["summary"] is None
    assert retried["blocker"] is None


def test_async_completion_does_not_pollute_the_function_pipeline(tmp_path: Path) -> None:
    _, script = _orchestrator_fixture(tmp_path)
    pwsh = shutil.which("pwsh")
    assert pwsh is not None, "PowerShell 7 es un requisito del orquestador"
    probe = f"""
. {_powershell_literal(script)} -Action Status | Out-Null
$output = @(Complete-TaskWithoutPipelineOutput -Task ([System.Threading.Tasks.Task]::CompletedTask))
if ($output.Count -ne 0) {{
    throw "La espera asíncrona contaminó el pipeline con $($output.Count) valor(es)."
}}
"""

    result = subprocess.run(
        [pwsh, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", probe],
        cwd=script.parents[1],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_task_prompt_retries_acl_only_checks_with_scoped_permissions(tmp_path: Path) -> None:
    _, script = _orchestrator_fixture(tmp_path)

    contents = script.read_text(encoding="utf-8-sig")

    assert "falla únicamente por el sandbox o una ACL" in contents
    assert "reintenta una vez el mismo comando acotado" in contents


def test_next_handles_an_empty_ready_list(tmp_path: Path) -> None:
    fixture_root, script = _orchestrator_fixture(tmp_path)
    state = _read_state(fixture_root)
    tasks = state["tasks"]
    assert isinstance(tasks, list)
    for task in tasks:
        if isinstance(task, dict) and task.get("status") != "DONE":
            task["status"] = "BLOCKED"
            task["blocker"] = {"type": "TEST"}
    _write_state(fixture_root, state)

    result = _run_orchestrator(script, "-Action", "Next")

    assert result.returncode == 0, result.stderr
    assert "No hay tareas READY" in result.stdout
