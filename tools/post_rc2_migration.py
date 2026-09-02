#!/usr/bin/env python3
"""Controlador reversible para la migracion post-RC2.

No borra ni reconstruye artefactos. Genera el snapshot previo y ejecuta
movimientos de directorios ya clasificados, registrando cada operacion en un
ledger JSONL despues de verificar hash y tamano en destino.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

PRODUCT = Path(__file__).resolve().parents[1]
PARENT = PRODUCT.parent
ENGINEERING = PARENT / "GTFS Explorer Engineering"
ARTIFACTS = PARENT / "GTFS Explorer Artifacts"
MANIFESTS = ARTIFACTS / "manifests"
LEDGER = MANIFESTS / "MIGRATION_LEDGER.jsonl"
SECURITY_SUFFIXES = {".pfx", ".p12", ".key", ".pem"}
SKIP_PARTS = {".git", "__pycache__"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return path.relative_to(PRODUCT).as_posix()


def is_security_material(path: Path) -> bool:
    return path.suffix.lower() in SECURITY_SUFFIXES


def classify(path: Path) -> str:
    value = rel(path)
    if is_security_material(path):
        return "SECURITY_MATERIAL"
    if value.startswith("dist/rc/P1-34C-20260829/"):
        return "RC1_CANONICAL"
    if "rc2" in value.lower():
        return "RC2_RELEASE_OR_EVIDENCE"
    if value.startswith("dist/"):
        return "RELEASE_OR_EVIDENCE"
    if value.startswith(".venv/"):
        return "GENERATED_RUNTIME"
    if value.startswith((".mypy_cache/", ".pytest_cache/", ".ruff_cache/")):
        return "GENERATED_CACHE"
    if value.startswith((".tmp/", ".codex-runs/", ".task-", ".t004-temp/")):
        return "RUN_EVIDENCE_OR_TEMPORARY"
    return "PRODUCT_SOURCE_OR_DOCUMENTATION"


def files(root: Path) -> Iterable[Path]:
    for current, dirs, names in os.walk(root):
        dirs[:] = [item for item in dirs if item not in SKIP_PARTS]
        for name in names:
            yield Path(current) / name


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=PRODUCT, text=True).strip()


def prepare_destinations() -> None:
    for folder in (
        ENGINEERING / "engineering" / "adr",
        ENGINEERING / "engineering" / "releases",
        ENGINEERING / "engineering" / "current",
        ARTIFACTS / "releases" / "0.1.0-rc1",
        ARTIFACTS / "releases" / "0.1.0-rc2",
        ARTIFACTS / "acceptance-builds",
        ARTIFACTS / "superseded",
        ARTIFACTS / "evidence" / "packaging",
        ARTIFACTS / "evidence" / "windows",
        ARTIFACTS / "evidence" / "webengine",
        ARTIFACTS / "evidence" / "ctm",
        ARTIFACTS / "evidence" / "performance",
        ARTIFACTS / "evidence" / "upgrades",
        ARTIFACTS / "generated-runtime",
        ARTIFACTS / "security-restricted",
        MANIFESTS,
    ):
        folder.mkdir(parents=True, exist_ok=True)
    for repository in (ENGINEERING, ARTIFACTS):
        if not (repository / ".git").exists():
            subprocess.run(["git", "init"], cwd=repository, check=True, capture_output=True)
    if not LEDGER.exists():
        LEDGER.touch()


def snapshot() -> None:
    prepare_destinations()
    entries: list[dict[str, object]] = []
    counts: Counter[str] = Counter()
    total_bytes = 0
    for file_path in files(PRODUCT):
        item_class = classify(file_path)
        size = file_path.stat().st_size
        entry: dict[str, object] = {
            "original_path": rel(file_path),
            "sha256": None if item_class == "SECURITY_MATERIAL" else sha256(file_path),
            "bytes": size,
            "classification": item_class,
        }
        entries.append(entry)
        counts[item_class] += 1
        total_bytes += size
    manifest = MANIFESTS / "PRE_MIGRATION_MANIFEST.jsonl"
    if manifest.exists():
        raise SystemExit(f"Snapshot already exists: {manifest}")
    with manifest.open("x", encoding="utf-8", newline="\n") as output:
        for entry in entries:
            output.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    metadata = {
        "created_at": utc_now(),
        "snapshot_branch": git("branch", "--show-current"),
        "head": git("rev-parse", "HEAD"),
        "tags": {
            "v0.1.0-rc1": git("rev-parse", "v0.1.0-rc1^{}"),
            "v0.1.0-rc2": git("rev-parse", "v0.1.0-rc2^{}"),
        },
        "worktree": git("worktree", "list", "--porcelain"),
        "file_count": len(entries),
        "total_bytes": total_bytes,
        "classification_counts": dict(sorted(counts.items())),
        "security_material_policy": "Excluded SHA-256 by policy; existence and bytes only.",
        "scope": "Working tree excluding .git and Python __pycache__ directories.",
    }
    (MANIFESTS / "PRE_MIGRATION_SNAPSHOT.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


def ledger(entry: dict[str, object]) -> None:
    with LEDGER.open("a", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def move_tree(source_relative: str, destination: Path, classification: str, rationale: str) -> None:
    source = PRODUCT / source_relative
    if not source.exists():
        raise SystemExit(f"Missing source: {source}")
    if destination.exists():
        raise SystemExit(f"Destination exists: {destination}")
    source_files = list(files(source)) if source.is_dir() else [source]
    before = []
    for item in source_files:
        relative = item.relative_to(PRODUCT).as_posix()
        before.append(
            (relative, item.stat().st_size, None if is_security_material(item) else sha256(item))
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    verified = []
    for original, size, digest in before:
        item = destination / Path(original).relative_to(source_relative)
        if not item.exists() or item.stat().st_size != size:
            raise SystemExit(f"Size verification failed after move: {original}")
        if digest is not None and sha256(item) != digest:
            raise SystemExit(f"Hash verification failed after move: {original}")
        verified.append((original, item, size, digest))
    for original, item, size, digest in verified:
        ledger(
            {
                "original_path": original,
                "target_path": str(item.relative_to(PARENT)).replace("\\", "/"),
                "sha256": digest,
                "bytes": size,
                "classification": classification,
                "status": "MOVED_VERIFIED",
                "superseded_by": None,
                "rationale": rationale,
                "copied_at": utc_now(),
                "verified_by": "tools/post_rc2_migration.py sha256+bytes",
            }
        )


def migrate_known_generated() -> None:
    prepare_destinations()
    moves = (
        (
            ".venv",
            ARTIFACTS / "generated-runtime" / "python-venv",
            "GENERATED_RUNTIME",
            "Entorno generado; no es fuente de producto.",
        ),
        (
            ".mypy_cache",
            ARTIFACTS / "generated-runtime" / "mypy-cache",
            "GENERATED_CACHE",
            "Cache de análisis generada.",
        ),
        (
            ".pytest_cache",
            ARTIFACTS / "generated-runtime" / "pytest-cache",
            "GENERATED_CACHE",
            "Cache de pruebas generada.",
        ),
        (
            ".ruff_cache",
            ARTIFACTS / "generated-runtime" / "ruff-cache",
            "GENERATED_CACHE",
            "Cache de formato generada.",
        ),
        (
            ".tmp",
            ARTIFACTS / "evidence" / "packaging" / "temporary-workspace",
            "RUN_EVIDENCE_OR_TEMPORARY",
            "Workspace temporal de packaging/smoke.",
        ),
        (
            ".codex-runs",
            ARTIFACTS / "evidence" / "packaging" / "codex-runs",
            "RUN_EVIDENCE_OR_TEMPORARY",
            "Evidencia de ejecuciones locales.",
        ),
        (
            ".t004-temp",
            ARTIFACTS / "evidence" / "packaging" / "t004-temp",
            "RUN_EVIDENCE_OR_TEMPORARY",
            "Temporal de tarea histórica.",
        ),
        (
            ".task-t013-pytest",
            ARTIFACTS / "evidence" / "packaging" / "task-t013-pytest",
            "RUN_EVIDENCE_OR_TEMPORARY",
            "Evidencia pytest histórica.",
        ),
        (
            ".task-t057-final",
            ARTIFACTS / "evidence" / "packaging" / "task-t057-final",
            "RUN_EVIDENCE_OR_TEMPORARY",
            "Evidencia pytest histórica.",
        ),
        (
            ".task-t057-pytest",
            ARTIFACTS / "evidence" / "packaging" / "task-t057-pytest",
            "RUN_EVIDENCE_OR_TEMPORARY",
            "Evidencia pytest histórica.",
        ),
        (
            ".task-t061-pytest",
            ARTIFACTS / "evidence" / "packaging" / "task-t061-pytest",
            "RUN_EVIDENCE_OR_TEMPORARY",
            "Evidencia pytest histórica.",
        ),
        (
            ".task-t062-pytest",
            ARTIFACTS / "evidence" / "packaging" / "task-t062-pytest",
            "RUN_EVIDENCE_OR_TEMPORARY",
            "Evidencia pytest histórica.",
        ),
        (
            ".task-t063-pytest",
            ARTIFACTS / "evidence" / "packaging" / "task-t063-pytest",
            "RUN_EVIDENCE_OR_TEMPORARY",
            "Evidencia pytest histórica.",
        ),
        (
            ".task-t064-pytest",
            ARTIFACTS / "evidence" / "packaging" / "task-t064-pytest",
            "RUN_EVIDENCE_OR_TEMPORARY",
            "Evidencia pytest histórica.",
        ),
        (
            ".task-t090-manual-3",
            ARTIFACTS / "evidence" / "packaging" / "task-t090-manual-3",
            "RUN_EVIDENCE_OR_TEMPORARY",
            "Evidencia pytest histórica.",
        ),
        (
            ".task-t090-pytest-2",
            ARTIFACTS / "evidence" / "packaging" / "task-t090-pytest-2",
            "RUN_EVIDENCE_OR_TEMPORARY",
            "Evidencia pytest histórica.",
        ),
    )
    for source, destination, item_class, rationale in moves:
        if (PRODUCT / source).exists():
            move_tree(source, destination, item_class, rationale)


def migrate_dist() -> None:
    prepare_destinations()
    # El PFX se extrae primero: queda fuera de cualquier manifest versionable.
    pfx = PRODUCT / "dist/Certificados/Yeison-Development-Code-Signing.pfx"
    if pfx.exists():
        move_tree(
            "dist/Certificados/Yeison-Development-Code-Signing.pfx",
            ARTIFACTS / "security-restricted" / "Yeison-Development-Code-Signing.pfx",
            "SECURITY_MATERIAL",
            "Material de firma separado de repositorios y manifests publicables.",
        )
    moves = (
        (
            "dist/rc/P1-34C-20260829",
            ARTIFACTS / "releases/0.1.0-rc1/P1-34C-20260829",
            "RC1_CANONICAL",
            "Conjunto RC1 canónico declarado por el usuario.",
        ),
        (
            "dist/GTFS-Explorer-0.1.0-rc1",
            ARTIFACTS / "superseded/GTFS-Explorer-0.1.0-rc1",
            "SUPERSEDED_RC1_EVIDENCE",
            "Conjunto RC1 no canónico; sólo evidencia.",
        ),
        (
            "dist/rc/0.1.0-rc1",
            ARTIFACTS / "superseded/rc-0.1.0-rc1",
            "SUPERSEDED_RC1_EVIDENCE",
            "Conjunto RC1 no canónico; sólo evidencia.",
        ),
        (
            "dist/GTFS-Explorer-0.1.0-rc2",
            ARTIFACTS / "releases/0.1.0-rc2/GTFS-Explorer-0.1.0-rc2",
            "RC2_RELEASE",
            "Artefactos asociados al tag RC2 inmutable.",
        ),
        (
            "dist/ctm-harness-regression",
            ARTIFACTS / "evidence/ctm/ctm-harness-regression",
            "CTM_EVIDENCE",
            "Evidencia técnica CTM, distinta de aceptación manual.",
        ),
    )
    for source, destination, item_class, rationale in moves:
        if (PRODUCT / source).exists():
            move_tree(source, destination, item_class, rationale)
    for folder in sorted((PRODUCT / "dist").iterdir() if (PRODUCT / "dist").exists() else []):
        if folder.name == "Certificados":
            destination = ARTIFACTS / "evidence/packaging/certificados-publicos"
            item_class = "PUBLIC_CERTIFICATE_EVIDENCE"
        elif folder.is_dir():
            destination = ARTIFACTS / "acceptance-builds" / folder.name
            item_class = "ACCEPTANCE_BUILD_OR_EVIDENCE"
        elif "rc2" in folder.name.lower():
            destination = ARTIFACTS / "releases/0.1.0-rc2/final-files" / folder.name
            item_class = "RC2_RELEASE"
        else:
            destination = ARTIFACTS / "superseded/direct-dist-files" / folder.name
            item_class = "SUPERSEDED_OR_EVIDENCE"
        move_tree(
            folder.relative_to(PRODUCT).as_posix(),
            destination,
            item_class,
            "Reclasificación post-RC2; sin reconstruir artefactos.",
        )


def migrate_test_runtime() -> None:
    prepare_destinations()
    if (PRODUCT / "tests/.runtime").exists():
        move_tree(
            "tests/.runtime",
            ARTIFACTS / "evidence/packaging/post-migration-test-runtime",
            "POST_MIGRATION_GENERATED_RUNTIME",
            "Salida generada por el gate post-migración; fuera de la fuente.",
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=("snapshot", "migrate-known-generated", "migrate-dist", "migrate-test-runtime"),
    )
    args = parser.parse_args()
    if args.command == "snapshot":
        snapshot()
    elif args.command == "migrate-known-generated":
        migrate_known_generated()
    elif args.command == "migrate-dist":
        migrate_dist()
    elif args.command == "migrate-test-runtime":
        migrate_test_runtime()
    return 0


if __name__ == "__main__":
    sys.exit(main())
