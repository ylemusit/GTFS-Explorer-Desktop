"""Adaptador opcional y aislado para el validador GTFS de MobilityData."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from gtfs_explorer.domain.errors import ImportCancelled


class MobilityDataStatus(StrEnum):
    NOT_AVAILABLE = "NOT_AVAILABLE"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class MobilityDataSidecar:
    """Dependencias locales fijadas por una distribución ampliada, nunca descargadas."""

    validator_version: str
    java_executable: Path
    cli_jar: Path
    timeout_seconds: float = 300.0

    def __post_init__(self) -> None:
        if not self.validator_version:
            raise ValueError("La versión de MobilityData debe estar fijada.")
        if self.timeout_seconds <= 0:
            raise ValueError("El timeout del validador debe ser positivo.")

    def is_available(self) -> bool:
        return self.java_executable.is_file() and self.cli_jar.is_file()


@dataclass(frozen=True)
class MobilityDataResult:
    status: MobilityDataStatus
    validator_version: str
    report_json: Path | None = None
    report_html: Path | None = None
    system_errors_json: Path | None = None
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""


ProcessFactory = Callable[..., subprocess.Popen[str]]


class MobilityDataValidator:
    """Ejecuta la CLI sin shell y conserva sus informes fuera del validador interno."""

    def __init__(
        self, sidecar: MobilityDataSidecar, *, process_factory: ProcessFactory | None = None
    ) -> None:
        self._sidecar = sidecar
        self._process_factory = process_factory or subprocess.Popen

    def validate(
        self,
        source: Path,
        output_directory: Path,
        *,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> MobilityDataResult:
        if not source.is_file():
            raise ValueError("La fuente para MobilityData debe ser un archivo GTFS existente.")
        if not self._sidecar.is_available():
            return MobilityDataResult(
                MobilityDataStatus.NOT_AVAILABLE, self._sidecar.validator_version
            )

        output_directory.mkdir(parents=True, exist_ok=True)
        command = [
            str(self._sidecar.java_executable),
            "-jar",
            str(self._sidecar.cli_jar),
            "-i",
            str(source),
            "-o",
            str(output_directory),
        ]
        process = self._process_factory(
            command,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        started = time.monotonic()
        check_cancelled = is_cancelled or (lambda: False)
        while process.poll() is None:
            if check_cancelled():
                _terminate(process)
                stdout, stderr = process.communicate()
                raise ImportCancelled("La validación opcional de MobilityData se ha cancelado.")
            if time.monotonic() - started >= self._sidecar.timeout_seconds:
                _terminate(process)
                stdout, stderr = process.communicate()
                return self._result(
                    MobilityDataStatus.TIMED_OUT, output_directory, None, stdout, stderr
                )
            time.sleep(0.02)
        stdout, stderr = process.communicate()
        status = (
            MobilityDataStatus.SUCCEEDED if process.returncode == 0 else MobilityDataStatus.FAILED
        )
        return self._result(status, output_directory, process.returncode, stdout, stderr)

    def _result(
        self,
        status: MobilityDataStatus,
        output_directory: Path,
        exit_code: int | None,
        stdout: str,
        stderr: str,
    ) -> MobilityDataResult:
        return MobilityDataResult(
            status=status,
            validator_version=self._sidecar.validator_version,
            report_json=_existing_file(output_directory / "report.json"),
            report_html=_existing_file(output_directory / "report.html"),
            system_errors_json=_existing_file(output_directory / "system_errors.json"),
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
        )


def _existing_file(path: Path) -> Path | None:
    return path if path.is_file() else None


def _terminate(process: subprocess.Popen[str]) -> None:
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
