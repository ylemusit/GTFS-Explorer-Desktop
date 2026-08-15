"""Smoke técnico de las dependencias fijadas en T001.

Ejecutar con el Python del entorno bloqueado por uv. No forma parte de la UI.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path


def _version(module: object) -> str:
    return str(getattr(module, "__version__", "unknown"))


def main() -> int:
    # Permite ejecutar el smoke en una sesión sin display sin cambiar el
    # comportamiento normal de Windows cuando QT_QPA_PLATFORM ya está fijado.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    import duckdb
    import shapely
    from PySide6.QtCore import QCoreApplication, QLibraryInfo, QTimer, qVersion
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication

    pointer_bits = 8 * __import__("struct").calcsize("P")
    if pointer_bits != 64:
        raise RuntimeError(f"Se requiere Python x64; se detectó {pointer_bits} bits")

    database_fd, database_name = tempfile.mkstemp(
        prefix="gtfs-t001-",
        suffix=".duckdb",
        dir=Path.cwd(),
    )
    os.close(database_fd)
    database_path = Path(database_name)
    database_path.unlink()
    try:
        connection = duckdb.connect(str(database_path))
        try:
            connection.execute("CREATE TABLE smoke (distance DOUBLE)")
            connection.execute("INSERT INTO smoke VALUES (42.0)")
            result = connection.execute("SELECT distance FROM smoke").fetchone()
            if result != (42.0,):
                raise RuntimeError(f"Consulta DuckDB inesperada: {result!r}")
        finally:
            connection.close()
    finally:
        database_path.unlink(missing_ok=True)

    from shapely.geometry import Point

    distance = Point(0, 0).distance(Point(3, 4))
    if distance != 5.0:
        raise RuntimeError(f"Distancia Shapely inesperada: {distance!r}")

    application = QApplication.instance() or QApplication(sys.argv)
    view = QWebEngineView()
    view.show()
    application.processEvents()
    view.close()
    view.deleteLater()
    # Deja que el proceso renderer de Qt WebEngine complete su inicialización
    # antes de terminar el proceso principal en Windows.
    QTimer.singleShot(1000, application.quit)
    application.exec()
    if QCoreApplication.instance() is not None:
        QCoreApplication.processEvents()

    nuitka = subprocess.run(
        [sys.executable, "-m", "nuitka", "--version"],
        check=True,
        capture_output=True,
        text=True,
    )

    print(
        json.dumps(
            {
                "python": platform.python_version(),
                "python_implementation": platform.python_implementation(),
                "architecture_bits": pointer_bits,
                "platform": platform.platform(),
                "qt": qVersion(),
                "qt_location": QLibraryInfo.path(QLibraryInfo.LibraryPath.PrefixPath),
                "duckdb": _version(duckdb),
                "shapely": _version(shapely),
                "nuitka": nuitka.stdout.strip(),
                "checks": {
                    "imports_x64": True,
                    "qwebengineview_open_close": True,
                    "duckdb_create_query": True,
                    "shapely_distance": distance,
                    "nuitka_environment": True,
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
