# Reproducibilidad del toolchain

## Cierre canónico post-migración

Registro final autorizado, sin reejecución durante el freeze:

```ini
PYTHON_VERSION = 3.12.10
PYTEST_VERSION = 8.3.5
RUFF_VERSION = 0.9.10
MYPY_VERSION = 1.15.0
PYTEST_PASSED = 527
PYTEST_FAILED = 0
PYTEST_SKIPPED = 0
PYTEST_DURATION = 565.53 s
TOOLS_CHECK_EXIT_CODE = 0
RC2_MANUAL_ACCEPTANCE = PASS
TOOLCHAIN_RECONSTRUCTION_FROM_UV_LOCK = PASS
ARTIFACT_STORE_RESOLUTION = PASS
POST_MIGRATION_CANONICAL_GATE = PASS
```

Los bytes originales del gate y sus hashes se preservan, cuando están
disponibles, en `GTFS Explorer Engineering`; este documento no sustituye esa
evidencia por una reejecución.

## POST-RC2 — reconstrucción y gate

Fecha de ejecución: 2026-09-02

### Contrato descubierto

- `pyproject.toml`: Python `>=3.12,<3.13`, dependencias runtime exactas y grupo `dev` con pytest, Ruff y mypy.
- `uv.lock`: lockfile Python oficial, `requires-python = "==3.12.*"`.
- `README.md`: creación/sincronización documentada mediante `uv sync --all-groups`.
- `docs/TESTING.md`: gate canónico `tools/check.ps1`.
- `tools/check.ps1`: orden formato, Ruff, mypy y pytest.
- No se encontraron `requirements*.txt`, `poetry.lock` ni `Pipfile.lock` aplicables.

### Reconstrucción

```ini
TOOLCHAIN_RECONSTRUCTION = PASS
VENV_PATH = .venv
INSTALL_SOURCE = uv.lock mediante uv sync --frozen --all-groups
PYTHON_VERSION = 3.12.10
```

Python 3.12.10 fue verificado antes de crear `.venv`. Como `uv` no estaba
disponible globalmente, se usó un bootstrap temporal aislado de Python 3.12
con `uv 0.12.9`; no se instaló ninguna herramienta global y no se modificaron
manifests ni versiones.

Paquetes de desarrollo verificados desde el lockfile:

```ini
PYTEST_VERSION = 8.3.5
RUFF_VERSION = 0.9.10
MYPY_VERSION = 1.15.0
```

### Gate canónico

Se priorizó `.venv\\Scripts` únicamente en el PATH de la sesión y se ejecutó
una sola vez `pwsh -NoProfile -File .\\tools\\check.ps1`.

```ini
TOOLS_CHECK_EXIT_CODE = 1
RUFF = PASS (format: 230 files; lint: All checks passed)
MYPY = PASS (125 source files)
PYTEST_TOTAL = 526
PYTEST_PASSED = 523
PYTEST_FAILED = 3
PYTEST_SKIPPED = 0
PYTEST_DURATION = 551.52 s (0:09:11.52)
```

Fallos capturados:

1. `tests/test_export_assistant.py::test_completion_dialog_copy_path_action_copies_full_destination`

   ```text
   AssertionError: assert '' == '...\\exports\\mini.zip'
   tests/test_export_assistant.py:287
   ```

   Capa probable: interacción Qt del diálogo/portapapeles en el harness
   offscreen. No se confirma todavía si es producto o entorno de prueba.

2. `tests/test_map_loopback_spike.py::test_webengine_bridge_and_range_contract_are_demonstrated`

   ```text
   tests/test_map_loopback_spike.py:62
   assert evidence["map_loaded"]
   E       assert False
   ```

   Capa probable: temporización/renderizado Qt WebEngine/Chromium en modo
   offscreen; queda como fallo del gate de esta ejecución.

3. `tests/test_p1_33_upgrade.py::test_p1_33_target_artifacts_match_manifest`

   ```text
   FileNotFoundError: [Errno 2] No such file or directory:
   ...\\dist\\P1-32-packaging-20260828\\release-manifest.json
   tests/test_p1_33_upgrade.py:72
   ```

   Capa probable: precondición de fixture/artefactos históricos ausentes en
   el checkout; no es evidencia de un fallo de lógica del producto.

No se ejecutó el fallback `python -m pytest -q`, no se repitió la suite y no se
modificaron producto, tests ni `tools/check.ps1` después de detectar los
fallos.

```ini
REPRODUCIBILITY_GAPS = NONE for dependency lock; gate failures require triage
POST_MIGRATION_GATE = FAIL
PROFESSIONALIZATION_STATUS = GATE_BLOCKED_REAL_TEST_FAILURES
```

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.
