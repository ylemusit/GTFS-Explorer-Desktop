"""Smoke del entrypoint de T002."""

import subprocess
import sys


def test_entrypoint_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "gtfs_explorer", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "0.1.0"


def test_entrypoint_runtime_smoke() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "gtfs_explorer", "--runtime-smoke"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
