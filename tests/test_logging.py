from __future__ import annotations

import logging
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest

from gtfs_explorer.infrastructure.logging import (
    configure_logging,
    export_diagnostics,
    install_exception_handler,
    preview_diagnostics,
    redact,
    safe_context,
)


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
