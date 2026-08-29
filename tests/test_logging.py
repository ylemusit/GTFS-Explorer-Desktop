from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest

from gtfs_explorer.infrastructure.logging import (
    capture_application_error,
    configure_logging,
    export_diagnostics,
    install_exception_handler,
    preview_diagnostics,
    redact,
    safe_context,
)
from gtfs_explorer.product import IDENTITY


def test_captured_ui_errors_keep_operation_exception_cause_traceback_and_zip(
    tmp_path: Path,
) -> None:
    logger = configure_logging(tmp_path)
    try:
        try:
            raise KeyError("token=synthetic-secret")
        except KeyError as cause:
            try:
                raise RuntimeError("open failed at C:/Users/yeiso/private/feed.zip") from cause
            except RuntimeError as error:
                capture_application_error(
                    logger,
                    error_code="UI-0003",
                    operation="open_project",
                    exception=error,
                    context={
                        "project_name": "Synthetic project",
                        "project_id": "project-1",
                        "version": "0.1.0",
                        "build_id": "build-test",
                        "app_state": "NO_PROJECT",
                        "source_path": "C:/Users/yeiso/private/feed.zip",
                    },
                )
        handler = logger.handlers[0]
        handler.flush()
        content = (tmp_path / "gtfs-explorer.log").read_text(encoding="utf-8")
        assert "UI-0003" in content
    finally:
        for handler in logger.handlers:
            handler.close()

    assert "open_project" in content
    assert "RuntimeError" in content
    assert "KeyError" in content
    assert "open failed" in content
    assert "Traceback (most recent call last)" in content
    assert "synthetic-secret" not in content
    assert "C:/Users/yeiso/private/feed.zip" not in content
    preview = preview_diagnostics(tmp_path)
    destination = export_diagnostics(preview, tmp_path / "diagnostic.zip")
    with ZipFile(destination) as archive:
        zipped = archive.read("gtfs-explorer.log").decode("utf-8")
    assert "UI-0003" in zipped and "RuntimeError" in zipped


def test_diagnostic_export_has_strong_negative_secret_and_path_assertions(
    tmp_path: Path,
) -> None:
    logger = configure_logging(tmp_path)
    original_path = r"C:\Users\SensitiveUser\Projects\SensitiveProject\feed.zip"
    original_token = "SUPER_SECRET_TOKEN_123"
    try:

        def external_failure() -> None:
            raise OSError(f"external source unavailable: {original_path} token={original_token}")

        def synthetic_open_project() -> None:
            try:
                external_failure()
            except OSError as cause:
                raise RuntimeError(
                    f"open_project failed at {original_path}; url=https://example.invalid/private"
                    f"?token={original_token}",
                    original_path,
                    original_token,
                ) from cause

        try:
            synthetic_open_project()
        except RuntimeError as error:
            capture_application_error(
                logger,
                error_code="UI-4242",
                operation="open_project",
                exception=error,
                context={
                    "project_id": "project-sensitive-01",
                    "project_name": "Proyecto Sintético Operativo",
                    "project_path": original_path,
                    "version": "0.1.0-test",
                    "build_id": "build-regression-002",
                    "app_state": "PROJECT_OPENING",
                    "feed": "route_id=R-SYNTH; stop_name=No exportar",
                    "row": "GTFS row must not be exported",
                },
            )
        logger.handlers[0].flush()
    finally:
        for handler in logger.handlers:
            handler.close()

    preview = preview_diagnostics(tmp_path)
    destination = export_diagnostics(preview, tmp_path / "diagnostic.zip")
    with ZipFile(destination) as archive:
        assert archive.namelist() == ["gtfs-explorer.log"]
        exported = archive.read("gtfs-explorer.log").decode("utf-8")

    assert original_path not in exported
    assert original_token not in exported
    assert "[PATH]" in exported
    assert "[REDACTED]" in exported
    assert "synthetic_open_project" in exported
    assert "external_failure" in exported
    assert "RuntimeError" in exported and "OSError" in exported
    assert "The above exception was the direct cause" in exported


@pytest.mark.parametrize(
    "source_root",
    [
        r"C:\Users\SensitiveUser\Projects\SensitiveProject\presentation\desktop",
        "/home/SensitiveUser/Projects/SensitiveProject/presentation/desktop",
    ],
)
def test_diagnostic_zip_traceback_keeps_basenames_and_redacts_paths(
    tmp_path: Path, source_root: str
) -> None:
    logger = configure_logging(tmp_path)
    separator = "\\" if source_root.startswith("C:") else "/"
    execute_path = f"{source_root}{separator}open_project.py"
    window_path = f"{source_root}{separator}main_window.py"
    secret_path = f"{source_root}{separator}project.json"
    secret_literal = repr(secret_path)
    namespace: dict[str, object] = {}
    try:
        exec(
            compile(
                'def execute():\n    raise ValueError("token=synthetic-trace-secret")\n',
                execute_path,
                "exec",
            ),
            namespace,
        )
        exec(
            compile(
                "def _choose_project():\n"
                "    try:\n"
                "        execute()\n"
                "    except ValueError as cause:\n"
                f'        raise RuntimeError("open failed at {secret_literal}", '
                f'{secret_literal}, "token=synthetic-args-secret") from cause\n'
                "_choose_project()\n",
                window_path,
                "exec",
            ),
            namespace,
        )
    except RuntimeError as error:
        capture_application_error(
            logger,
            error_code="UI-0001",
            operation="open_project",
            exception=error,
            context={"version": "0.1.0-test", "app_state": "PROJECT_OPENING"},
        )
    finally:
        logger.handlers[0].flush()
        for handler in logger.handlers:
            handler.close()

    destination = export_diagnostics(preview_diagnostics(tmp_path), tmp_path / "diagnostic.zip")
    with ZipFile(destination) as archive:
        exported = archive.read("gtfs-explorer.log").decode("utf-8")

    assert source_root not in exported
    assert "SensitiveUser" not in exported
    assert "main_window.py" in exported
    assert "open_project.py" in exported
    assert "_choose_project" in exported
    assert "execute" in exported
    assert re.search(r"main_window\.py\", line \d+, in _choose_project", exported)
    assert re.search(r"open_project\.py\", line \d+, in execute", exported)
    assert "synthetic-trace-secret" not in exported
    assert "synthetic-args-secret" not in exported
    assert "[REDACTED]" in exported
    assert "The above exception was the direct cause" in exported
    assert "project.json" not in exported


@pytest.mark.parametrize("operation", ["open_project", "close_project", "ui_operation"])
def test_captured_ui_error_operations_are_stable(tmp_path: Path, operation: str) -> None:
    logger = configure_logging(tmp_path)
    try:
        try:
            raise ValueError("controlled failure")
        except ValueError as error:
            capture_application_error(
                logger,
                error_code="UI-0001",
                operation=operation,
                exception=error,
            )
        logger.handlers[0].flush()
        content = (tmp_path / "gtfs-explorer.log").read_text(encoding="utf-8")
        assert operation in content
        assert "ValueError" in content
        assert "controlled failure" in content
    finally:
        for handler in logger.handlers:
            handler.close()


def test_captured_diagnostic_identity_cannot_be_overridden(tmp_path: Path) -> None:
    logger = configure_logging(tmp_path)
    try:
        capture_application_error(
            logger,
            error_code="UI-IDENTITY",
            operation="identity_check",
            exception=ValueError("controlled failure"),
            context={
                "product": "other-product",
                "version": "other-version",
                "build_id": "other-build",
            },
        )
        logger.handlers[0].flush()
        content = (tmp_path / "gtfs-explorer.log").read_text(encoding="utf-8")
    finally:
        for handler in logger.handlers:
            handler.close()

    assert f"'product': '{IDENTITY.name}'" in content
    assert f"'version': '{IDENTITY.version}'" in content
    assert "other-product" not in content
    assert "other-version" not in content
    assert "other-build" not in content


def test_old_code_only_application_error_is_insufficient() -> None:
    old_record = (
        "APPLICATION_ERROR code=UI-0003 context={'event':'ui_error','error_code':'UI-0003'}"
    )
    assert "traceback=" not in old_record
    assert "exception_type=" not in old_record


def test_successful_operation_does_not_create_application_error(tmp_path: Path) -> None:
    logger = configure_logging(tmp_path)
    try:
        logger.info("operation=close_project result=success")
        logger.handlers[0].flush()
        content = (tmp_path / "gtfs-explorer.log").read_text(encoding="utf-8")
        assert "APPLICATION_ERROR" not in content
        assert "traceback=" not in content
    finally:
        for handler in logger.handlers:
            handler.close()


def test_diagnostics_keep_only_operational_context_and_redact_secrets() -> None:
    assert safe_context({"job_id": "job-1", "source_path": "C:/private/feed.zip", "row": "x"}) == {
        "job_id": "job-1"
    }
    assert redact("token=abc password: hidden") == "[REDACTED] [REDACTED]"


def test_rotates_logs_and_exports_only_previewed_log_files(tmp_path: Path) -> None:
    logger = configure_logging(tmp_path, debug=False)
    handler = logger.handlers[0]
    handler.maxBytes = 32  # type: ignore[attr-defined]
    logger.info("x" * 80)
    logger.info("y" * 80)
    (tmp_path / "feed.zip").write_text("private feed", encoding="utf-8")

    preview = preview_diagnostics(tmp_path)
    assert preview.files
    assert all(path.name.startswith("gtfs-explorer.log") for path in preview.files)
    assert "feed.zip" not in preview.summary()

    destination = export_diagnostics(preview, tmp_path / "diagnostic.zip")
    with ZipFile(destination) as archive:
        assert archive.namelist() == [path.name for path in preview.files]
    handler.close()


def test_unhandled_exception_is_redacted_and_only_keeps_stack_in_debug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = logging.getLogger("test_gtfs_explorer_unhandled")
    logger.handlers.clear()
    logger.propagate = False
    records: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger.addHandler(Capture())
    previous = sys.excepthook
    install_exception_handler(logger, debug=False)
    try:
        error = RuntimeError("token=private-value")
        sys.excepthook(type(error), error, error.__traceback__)
    finally:
        monkeypatch.setattr(sys, "excepthook", previous)

    assert "private-value" not in records[0].getMessage()
    assert records[0].exc_info is False
