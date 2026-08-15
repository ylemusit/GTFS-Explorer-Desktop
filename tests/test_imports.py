"""Pruebas del árbol de paquetes y la dirección de dependencias de T002."""

import ast
from pathlib import Path

import gtfs_explorer.application
import gtfs_explorer.domain
import gtfs_explorer.infrastructure
import gtfs_explorer.presentation


def test_layer_packages_import() -> None:
    assert gtfs_explorer.domain.__name__ == "gtfs_explorer.domain"
    assert gtfs_explorer.application.__name__ == "gtfs_explorer.application"
    assert gtfs_explorer.infrastructure.__name__ == "gtfs_explorer.infrastructure"
    assert gtfs_explorer.presentation.__name__ == "gtfs_explorer.presentation"


def test_domain_has_no_imports_from_outer_layers() -> None:
    domain_root = Path(__file__).parents[1] / "src" / "gtfs_explorer" / "domain"
    forbidden_prefixes = ("PySide6", "duckdb", "shapely", "gtfs_explorer.application")
    imported = []
    for path in domain_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported.extend(
            node.module or node.names[0].name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
    assert not any(name.startswith(forbidden_prefixes) for name in imported)
