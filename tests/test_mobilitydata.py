from __future__ import annotations

from pathlib import Path

import pytest

from gtfs_explorer.domain.errors import ImportCancelled
from gtfs_explorer.infrastructure.validation.mobilitydata import (
    MobilityDataSidecar,
    MobilityDataStatus,
    MobilityDataValidator,
)


def _sidecar(tmp_path: Path, *, timeout_seconds: float = 1) -> MobilityDataSidecar:
    java = tmp_path / "java.exe"
    jar = tmp_path / "gtfs-validator-v5.0.1-cli.jar"
    java.write_text("stub", encoding="utf-8")
    jar.write_text("stub", encoding="utf-8")
    return MobilityDataSidecar("5.0.1", java, jar, timeout_seconds)


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "feed.zip"
    source.write_bytes(b"fixture")
    return source


def test_absent_sidecar_does_not_break_core(tmp_path: Path) -> None:
    sidecar = MobilityDataSidecar("5.0.1", tmp_path / "missing-java", tmp_path / "missing.jar")
    result = MobilityDataValidator(sidecar).validate(_source(tmp_path), tmp_path / "reports")
    assert result.status is MobilityDataStatus.NOT_AVAILABLE
    assert result.validator_version == "5.0.1"


def test_runs_fixed_argument_vector_and_collects_reports(tmp_path: Path) -> None:
    output = tmp_path / "reports"

    def factory(command: list[str], **kwargs: object) -> _CompletedProcess:
        assert kwargs["shell"] is False
        assert command == [
            str(tmp_path / "java.exe"),
            "-jar",
            str(tmp_path / "gtfs-validator-v5.0.1-cli.jar"),
            "-i",
            str(tmp_path / "feed.zip"),
            "-o",
            str(output),
        ]
        output.mkdir(exist_ok=True)
        (output / "report.json").write_text("{}", encoding="utf-8")
        (output / "report.html").write_text("<html>", encoding="utf-8")
        (output / "system_errors.json").write_text("[]", encoding="utf-8")
        return _CompletedProcess(0)

    result = MobilityDataValidator(_sidecar(tmp_path), process_factory=factory).validate(
        _source(tmp_path), output
    )
    assert result.status is MobilityDataStatus.SUCCEEDED
    assert result.report_json == output / "report.json"
    assert result.report_html == output / "report.html"


def test_nonzero_exit_is_captured_without_raising(tmp_path: Path) -> None:
    result = MobilityDataValidator(
        _sidecar(tmp_path),
        process_factory=lambda *args, **kwargs: _CompletedProcess(3, "", "bad feed"),
    ).validate(_source(tmp_path), tmp_path / "reports")
    assert result.status is MobilityDataStatus.FAILED
    assert result.exit_code == 3
    assert result.stderr == "bad feed"


def test_timeout_terminates_process(tmp_path: Path) -> None:
    process = _RunningProcess()
    result = MobilityDataValidator(
        _sidecar(tmp_path, timeout_seconds=0.001), process_factory=lambda *args, **kwargs: process
    ).validate(_source(tmp_path), tmp_path / "reports")
    assert result.status is MobilityDataStatus.TIMED_OUT
    assert process.terminated


def test_cancellation_terminates_process(tmp_path: Path) -> None:
    process = _RunningProcess()
    validator = MobilityDataValidator(
        _sidecar(tmp_path), process_factory=lambda *args, **kwargs: process
    )
    with pytest.raises(ImportCancelled):
        validator.validate(_source(tmp_path), tmp_path / "reports", is_cancelled=lambda: True)
    assert process.terminated


class _CompletedProcess:
    def __init__(self, returncode: int, stdout: str = "ok", stderr: str = "") -> None:
        self.returncode = returncode

    def poll(self) -> int:
        return self.returncode

    def communicate(self) -> tuple[str, str]:
        return ("ok", "") if self.returncode == 0 else ("", "bad feed")


class _RunningProcess:
    returncode: int | None = None

    def __init__(self) -> None:
        self.terminated = False

    def poll(self) -> None:
        return None

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def wait(self, timeout: float) -> int:
        return -15

    def kill(self) -> None:
        self.returncode = -9

    def communicate(self) -> tuple[str, str]:
        return "", ""
