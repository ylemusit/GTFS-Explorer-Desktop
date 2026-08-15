"""Genera fixtures GTFS ficticios y reproducibles para las pruebas locales."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

FIXED_ZIP_TIMESTAMP = (2020, 1, 1, 0, 0, 0)


def _csv_bytes(specification: dict[str, Any]) -> bytes:
    rows = specification["rows"]
    fieldnames = list(rows[0]) if rows else specification["headers"]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _read_specifications(specifications_directory: Path) -> list[dict[str, Any]]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(specifications_directory.glob("*.json"))
    ]


def _write_zip(destination: Path, files: dict[str, bytes]) -> None:
    with ZipFile(destination, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for filename, contents in sorted(files.items()):
            metadata = ZipInfo(filename, FIXED_ZIP_TIMESTAMP)
            metadata.compress_type = ZIP_DEFLATED
            metadata.external_attr = 0o100644 << 16
            archive.writestr(metadata, contents)


def build_fixtures(specifications_directory: Path, output_directory: Path) -> list[Path]:
    """Construye ZIPs y manifiestos de los JSON de especificación indicados."""
    output_directory.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []
    for specification in _read_specifications(specifications_directory):
        fixture_id = specification["fixture_id"]
        files = {filename: _csv_bytes(table) for filename, table in specification["tables"].items()}
        zip_path = output_directory / f"{fixture_id}.zip"
        _write_zip(zip_path, files)
        manifest = {
            "fixture_id": fixture_id,
            "description": specification["description"],
            "fictitious": True,
            "files": [
                {"name": name, "sha256": hashlib.sha256(contents).hexdigest()}
                for name, contents in sorted(files.items())
            ],
            "zip_sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest(),
        }
        manifest_path = output_directory / f"{fixture_id}.manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        generated.extend((zip_path, manifest_path))
    return generated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent / "generated",
        help="Directorio de salida (por defecto, tests/fixtures/generated).",
    )
    arguments = parser.parse_args()
    build_fixtures(Path(__file__).parent / "specs", arguments.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
