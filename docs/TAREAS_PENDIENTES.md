# Tareas pendientes y bloqueos

Este documento registra únicamente tareas del plan maestro que no han podido completarse o que requieren una decisión antes de continuar.

Cada entrada debe incluir la tarea, la parte completada, el criterio pendiente, la evidencia del problema, los intentos realizados y la acción necesaria. El orquestador añade las incidencias automáticamente y se detiene; nunca omite una dependencia bloqueada.


## T001 — Fijar plataforma y versiones

- **Fecha:** 2026-08-12T02:01:11.3189505+02:00
- **Estado:** BLOCKED
- **Parte completada:** No determinada.
- **Problema o criterio pendiente:** Cannot bind argument to parameter 'Content' because it is an empty string.
- **Evidencia:** No disponible.
- **Acción necesaria:** Revisar la evidencia y decidir cómo continuar.
- **Dependencias afectadas:** el orquestador no ejecutará tareas que dependan directa o indirectamente de T001.


## T001 — Fijar plataforma y versiones

- **Fecha:** 2026-08-12T02:01:57.4131904+02:00
- **Estado:** BLOCKED
- **Parte completada:** No determinada.
- **Problema o criterio pendiente:** Codex terminó con código 2. Codex no generó el resultado JSON final.
- **Evidencia:** .codex-runs/T001-20260812-020157
- **Acción necesaria:** Revisar la evidencia y decidir cómo continuar.
- **Dependencias afectadas:** el orquestador no ejecutará tareas que dependan directa o indirectamente de T001.


## T001 — Fijar plataforma y versiones

- **Fecha:** 2026-08-12T02:06:14.8978422+02:00
- **Estado:** BLOCKED
- **Parte completada:** Preparación parcial realizada: pyproject.toml y smoke creados. No se pudo instalar uv ni dependencias; el smoke, uv.lock y la decisión documentada no pueden demostrarse en este entorno.
- **Problema o criterio pendiente:** PIP_NO_INDEX=1 bloquea el índice de paquetes y, aun forzando PyPI, no se obtienen candidatos. Sin uv ni dependencias instaladas no pueden ejecutarse las pruebas obligatorias.
- **Evidencia:** .codex-runs/T001-20260812-020237
- **Acción necesaria:** Proporcionar un índice/cache autorizado accesible con uv y ruedas para Python 3.12 Windows x64; después ejecutar uv lock, uv sync y tools/smoke_dependencies.py.
- **Dependencias afectadas:** el orquestador no ejecutará tareas que dependan directa o indirectamente de T001.


## T001 — Fijar plataforma y versiones

- **Fecha:** 2026-08-12T02:11:32.9539255+02:00
- **Estado:** BLOCKED
- **Parte completada:** No se puede completar T001: uv no está instalado y la resolución de dependencias requiere acceso de red ampliado, rechazado por las restricciones de la tarea.
- **Problema o criterio pendiente:** La herramienta uv no está disponible. Instalarla y resolver paquetes necesita acceso de red ampliado y modifica el entorno de usuario; el intento fue rechazado por las restricciones aplicables.
- **Evidencia:** .codex-runs/T001-20260812-021000
- **Acción necesaria:** Proporcionar uv.exe/uv.lock y dependencias instalables localmente, o autorizar explícitamente el acceso requerido en una nueva sesión.
- **Dependencias afectadas:** el orquestador no ejecutará tareas que dependan directa o indirectamente de T001.


## T002 — Crear esqueleto por capas

- **Fecha:** 2026-08-12T02:25:51.4861722+02:00
- **Estado:** BLOCKED
- **Parte completada:** Esqueleto T002 implementado, pero no puede cerrarse porque la instalación editable y pytest están bloqueados por permisos y herramientas ausentes.
- **Problema o criterio pendiente:** El entorno deniega temporales y artefactos de pip con WinError 5; además pytest no está instalado. La ficha exige instalación editable y pruebas ejecutables.
- **Evidencia:** .codex-runs/T002-20260812-022126
- **Acción necesaria:** Ejecutar pip install -e ., pytest tests/test_imports.py tests/test_entrypoint.py -q y el smoke instalado en un Python/venv con permisos de escritura, setuptools y pytest disponibles.
- **Dependencias afectadas:** el orquestador no ejecutará tareas que dependan directa o indirectamente de T002.


## T002 — Crear esqueleto por capas

- **Fecha:** 2026-08-12T02:32:22.6288530+02:00
- **Estado:** BLOCKED
- **Parte completada:** El esqueleto de T002 ya estaba presente al iniciar la sesión y supera imports, capas, CLI --version y ventana pre-alpha. No se han revertido cambios ajenos ni se han modificado archivos. No puede declararse DONE porque la instalación editable no se ha podido demostrar: pip falla por permisos al crear y limpiar sus build trackers temporales.
- **Problema o criterio pendiente:** El entorno Windows deniega a pip la creación y limpieza de directorios temporales necesarios para la instalación editable, incluso dentro del workspace. El criterio obligatorio no puede demostrarse.
- **Evidencia:** .codex-runs/T002-20260812-022903
- **Acción necesaria:** Corregir los permisos de las carpetas temporales o usar un entorno Python con pip operativo; repetir la instalación editable y el smoke del entrypoint.
- **Dependencias afectadas:** el orquestador no ejecutará tareas que dependan directa o indirectamente de T002.


## T002 — Crear esqueleto por capas

- **Fecha:** 2026-08-12T02:37:52.5473627+02:00
- **Estado:** BLOCKED
- **Parte completada:** La implementación de T002 ya estaba presente en el árbol de trabajo y sus tests pasan, pero no se pudo demostrar una instalación editable reproducible porque pip falla por permisos en el directorio temporal del sistema.
- **Problema o criterio pendiente:** pip no puede crear su directorio temporal bajo C:\Users\yeiso\AppData\Local\Temp.
- **Evidencia:** .codex-runs/T002-20260812-023359
- **Acción necesaria:** Restaurar permisos de escritura para ese directorio o proporcionar un entorno Python con temporales escribibles y repetir la instalación editable.
- **Dependencias afectadas:** el orquestador no ejecutará tareas que dependan directa o indirectamente de T002.


## T004 — Crear fixtures GTFS reproducibles

- **Fecha:** 2026-08-12T02:48:09.1652224+02:00
- **Estado:** BLOCKED
- **Parte completada:** T004 implementada y criterios funcionales demostrados. El comando canónico tools/check.ps1 falla por Acceso denegado al recorrer directorios auxiliares del workspace.
- **Problema o criterio pendiente:** tools/check.ps1 no puede completar Ruff por Acceso denegado en directorios auxiliares del workspace. La carpeta temporal .t004-temp creada durante el diagnóstico tampoco puede eliminarse por ACL.
- **Evidencia:** .codex-runs/T004-20260812-024229
- **Acción necesaria:** Corregir o retirar las ACL de los directorios auxiliares y volver a ejecutar tools/check.ps1.
- **Dependencias afectadas:** el orquestador no ejecutará tareas que dependan directa o indirectamente de T004.


## T013 — Parser tabular fiel

- **Fecha:** 2026-08-12T03:54:05.0293141+02:00
- **Estado:** BLOCKED
- **Parte completada:** No determinada.
- **Problema o criterio pendiente:** El control independiente terminó con código 1: 31 files already formatted
All checks passed!
Success: no issues found in 19 source files
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.3.5, pluggy-1.6.0
rootdir: C:\Users\yeiso\Desktop\Folder\VSCode\Proyectos\GTFS Explorer Desktop
configfile: pyproject.toml
collected 33 items

tests\test_directory_source.py ..                                        [  6%]
tests\test_entrypoint.py .                                               [  9%]
tests\test_fixtures.py .                                                 [ 12%]
tests\test_imports.py ..                                                 [ 18%]
tests\test_paths_and_settings.py ....                                    [ 30%]
tests\test_plan_orchestrator.py ..F...                                   [ 48%]
tests\test_source.py ...                                                 [ 57%]
tests\test_spec.py .                                                     [ 60%]
tests\test_tabular_reader.py ......                                      [ 78%]
tests\test_zip_source.py .......                                         [100%]

================================== FAILURES ===================================
_________________ test_configure_changes_executor_explicitly __________________

tmp_path = WindowsPath('C:/Users/yeiso/Desktop/Folder/VSCode/Proyectos/GTFS Explorer Desktop/tests/.runtime/pytest/test_configure_changes_executo0')

    def t...
- **Evidencia:** .codex-runs/T013-20260812-035150
- **Acción necesaria:** Revisar la evidencia y decidir cómo continuar.
- **Dependencias afectadas:** el orquestador no ejecutará tareas que dependan directa o indirectamente de T013.


## T014 — Registro versionado de especificación

- **Fecha:** 2026-08-12T23:28:37.7195231+02:00
- **Estado:** BLOCKED
- **Parte completada:** No determinada.
- **Problema o criterio pendiente:** Codex terminó con código 1. stderr: WARNING: failed to clean up stale arg0 temp dirs: Acceso denegado. (os error 5)
WARNING: proceeding, even though we could not create PATH aliases: Acceso denegado. (os error 5) at path "C:\\Users\\yeiso\\.codex\\tmp\\arg0\\codex-arg0UQnhkN"
2026-08-12T21:28:35.596079Z  WARN codex_state::runtime: failed to open state db at C:\Users\yeiso\.codex\state_5.sqlite: failed to open state DB at C:\Users\yeiso\.codex\state_5.sqlite: error returned from database: (code: 8) attempt to write a readonly database
2026-08-12T21:28:35.596118Z  WARN codex_rollout::state_db: failed to initialize state runtime: failed to initialize state runtime at C:\Users\yeiso\.codex: failed to open state DB at C:\Users\yeiso\.codex\state_5.sqlite: error returned from database: (code: 8) attempt to write a readonly database: error returned from database: (code: 8) attempt to write a readonly database: (code: 8) attempt to write a readonly database
Reading additional input from stdin...
Error: failed to initialize in-pr... Codex no generó el resultado JSON final.
- **Evidencia:** .codex-runs/T014-20260812-232835
- **Acción necesaria:** Revisar la evidencia y decidir cómo continuar.
- **Dependencias afectadas:** el orquestador no ejecutará tareas que dependan directa o indirectamente de T014.


## T014 — Registro versionado de especificación

- **Fecha:** 2026-08-12T23:31:32.7721133+02:00
- **Estado:** BLOCKED / RECOVERED
- **Parte completada:** No determinada.
- **Problema o criterio pendiente:** La ejecución anterior terminó sin resultado verificable.
- **Evidencia:** No disponible.
- **Acción necesaria:** Revisar los cambios y artefactos de T014, y después usar Retry explícitamente.
- **Dependencias afectadas:** el orquestador no ejecutará tareas que dependan directa o indirectamente de T014.


## T023 — Persistencia de proyectos y caché

- **Fecha:** 2026-08-13T00:42:25.1152775+02:00
- **Estado:** BLOCKED
- **Parte completada:** Implementada la apertura exclusiva de proyectos y la caché descartable versionada/atómica. La validación final de pytest queda bloqueada por ACL del temporal y un segundo permiso ampliado rechazado por política.
- **Problema o criterio pendiente:** La prueba requerida no puede finalizar por WinError 5 al acceder al temporal de pytest. El reintento ampliado previo se usó antes de corregir el fallo funcional y el nuevo reintento fue rechazado por política.
- **Evidencia:** .codex-runs/T023-20260813-003742
- **Acción necesaria:** Autorizar explícitamente un nuevo pytest local con permisos ampliados después de la corrección, o restaurar una ACL funcional para el temporal de pytest.
- **Dependencias afectadas:** el orquestador no ejecutará tareas que dependan directa o indirectamente de T023.


## T040 — Framework de reglas y problemas

- **Fecha:** 2026-08-13T01:30:23.0954971+02:00
- **Estado:** BLOCKED
- **Parte completada:** No determinada.
- **Problema o criterio pendiente:** Codex terminó con código 1. stderr: WARNING: failed to clean up stale arg0 temp dirs: Acceso denegado. (os error 5)
WARNING: proceeding, even though we could not create PATH aliases: Acceso denegado. (os error 5) at path "C:\\Users\\yeiso\\.codex\\tmp\\arg0\\codex-arg0FHXekC"
2026-08-12T23:30:20.960351Z  WARN codex_state::runtime: failed to open state db at C:\Users\yeiso\.codex\state_5.sqlite: failed to open state DB at C:\Users\yeiso\.codex\state_5.sqlite: error returned from database: (code: 8) attempt to write a readonly database
2026-08-12T23:30:20.960379Z  WARN codex_rollout::state_db: failed to initialize state runtime: failed to initialize state runtime at C:\Users\yeiso\.codex: failed to open state DB at C:\Users\yeiso\.codex\state_5.sqlite: error returned from database: (code: 8) attempt to write a readonly database: error returned from database: (code: 8) attempt to write a readonly database: (code: 8) attempt to write a readonly database
Reading additional input from stdin...
Error: failed to initialize in-pr... Codex no generó el resultado JSON final.
- **Evidencia:** .codex-runs/T040-20260813-013020
- **Acción necesaria:** Revisar la evidencia y decidir cómo continuar.
- **Dependencias afectadas:** el orquestador no ejecutará tareas que dependan directa o indirectamente de T040.


## T052 — Exportador JSON

- **Fecha:** 2026-08-13T02:21:39.7961935+02:00
- **Estado:** BLOCKED
- **Parte completada:** No determinada.
- **Problema o criterio pendiente:** Codex terminó con código 1. stderr: WARNING: failed to clean up stale arg0 temp dirs: Acceso denegado. (os error 5)
WARNING: proceeding, even though we could not create PATH aliases: Acceso denegado. (os error 5) at path "C:\\Users\\yeiso\\.codex\\tmp\\arg0\\codex-arg0YMb7VN"
2026-08-13T00:21:37.657744Z  WARN codex_state::runtime: failed to open state db at C:\Users\yeiso\.codex\state_5.sqlite: failed to open state DB at C:\Users\yeiso\.codex\state_5.sqlite: error returned from database: (code: 8) attempt to write a readonly database
2026-08-13T00:21:37.657778Z  WARN codex_rollout::state_db: failed to initialize state runtime: failed to initialize state runtime at C:\Users\yeiso\.codex: failed to open state DB at C:\Users\yeiso\.codex\state_5.sqlite: error returned from database: (code: 8) attempt to write a readonly database: error returned from database: (code: 8) attempt to write a readonly database: (code: 8) attempt to write a readonly database
Reading additional input from stdin...
Error: failed to initialize in-pr... Codex no generó el resultado JSON final.
- **Evidencia:** .codex-runs/T052-20260813-022137
- **Acción necesaria:** Revisar la evidencia y decidir cómo continuar.
- **Dependencias afectadas:** el orquestador no ejecutará tareas que dependan directa o indirectamente de T052.


## T057 — Escritor y revalidación Mini-GTFS

- **Fecha:** 2026-08-13T03:09:53.3815139+02:00
- **Estado:** BLOCKED
- **Parte completada:** No determinada.
- **Problema o criterio pendiente:** Codex terminó con código 1. stderr: WARNING: failed to clean up stale arg0 temp dirs: Acceso denegado. (os error 5)
WARNING: proceeding, even though we could not create PATH aliases: Acceso denegado. (os error 5) at path "C:\\Users\\yeiso\\.codex\\tmp\\arg0\\codex-arg0K1FFOz"
2026-08-13T01:09:51.250097Z  WARN codex_state::runtime: failed to open state db at C:\Users\yeiso\.codex\state_5.sqlite: failed to open state DB at C:\Users\yeiso\.codex\state_5.sqlite: error returned from database: (code: 8) attempt to write a readonly database
2026-08-13T01:09:51.250138Z  WARN codex_rollout::state_db: failed to initialize state runtime: failed to initialize state runtime at C:\Users\yeiso\.codex: failed to open state DB at C:\Users\yeiso\.codex\state_5.sqlite: error returned from database: (code: 8) attempt to write a readonly database: error returned from database: (code: 8) attempt to write a readonly database: (code: 8) attempt to write a readonly database
Reading additional input from stdin...
Error: failed to initialize in-pr... Codex no generó el resultado JSON final.
- **Evidencia:** .codex-runs/T057-20260813-030951
- **Acción necesaria:** Revisar la evidencia y decidir cómo continuar.
- **Dependencias afectadas:** el orquestador no ejecutará tareas que dependan directa o indirectamente de T057.


## T064 — Rutas, viajes, paradas y horarios

- **Fecha:** 2026-08-13T03:46:29.6978671+02:00
- **Estado:** BLOCKED
- **Parte completada:** No determinada.
- **Problema o criterio pendiente:** Codex terminó con código 1. stderr: WARNING: failed to clean up stale arg0 temp dirs: Acceso denegado. (os error 5)
WARNING: proceeding, even though we could not create PATH aliases: Acceso denegado. (os error 5) at path "C:\\Users\\yeiso\\.codex\\tmp\\arg0\\codex-arg0pHuv90"
2026-08-13T01:46:27.569062Z  WARN codex_state::runtime: failed to open state db at C:\Users\yeiso\.codex\state_5.sqlite: failed to open state DB at C:\Users\yeiso\.codex\state_5.sqlite: error returned from database: (code: 8) attempt to write a readonly database
2026-08-13T01:46:27.569103Z  WARN codex_rollout::state_db: failed to initialize state runtime: failed to initialize state runtime at C:\Users\yeiso\.codex: failed to open state DB at C:\Users\yeiso\.codex\state_5.sqlite: error returned from database: (code: 8) attempt to write a readonly database: error returned from database: (code: 8) attempt to write a readonly database: (code: 8) attempt to write a readonly database
Reading additional input from stdin...
Error: failed to initialize in-pr... Codex no generó el resultado JSON final.
- **Evidencia:** .codex-runs/T064-20260813-034627
- **Acción necesaria:** Revisar la evidencia y decidir cómo continuar.
- **Dependencias afectadas:** el orquestador no ejecutará tareas que dependan directa o indirectamente de T064.


## T064 — Rutas, viajes, paradas y horarios

- **Fecha:** 2026-08-13T03:53:00.6348947+02:00
- **Estado:** BLOCKED
- **Parte completada:** No determinada.
- **Problema o criterio pendiente:** El control independiente terminó con código -1073741819: 136 files already formatted
All checks passed!
Success: no issues found in 90 source files
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.3.5, pluggy-1.6.0
rootdir: C:\Users\yeiso\Desktop\Folder\VSCode\Proyectos\GTFS Explorer Desktop
configfile: pyproject.toml
collected 148 items

tests\test_atomic_output.py ....                                         [  2%]
tests\test_best_practices_and_validation_report.py ..                    [  4%]
tests\test_core_normalizer.py ...                                        [  6%]
tests\test_csv_exporter.py ...                                           [  8%]
tests\test_directory_source.py ..                                        [  9%]
tests\test_duckdb_database.py .....                                      [ 12%]
tests\test_duckdb_repositories.py .....                                  [ 16%]
tests\test_entrypoint.py .                                               [ 16%]
tests\test_feed_overview.py .                                            [ 17%]
tests\test_field_reference_validation.py ..                              [ 18%]
tests\test_fixtures.py .                                                 [ 19%]
tests\test_geojson_exporter.py ...                                       [ 21%]
tests\test_geometry_queries.py ...                                       [ 23%]
tests\test_geometry_validation.py ...                                    [ 25%]
t...
- **Evidencia:** .codex-runs/T064-20260813-034649
- **Acción necesaria:** Revisar la evidencia y decidir cómo continuar.
- **Dependencias afectadas:** el orquestador no ejecutará tareas que dependan directa o indirectamente de T064.


## T066 — Asistente de exportación

- **Fecha:** 2026-08-13T04:14:09.3202329+02:00
- **Estado:** BLOCKED
- **Parte completada:** No determinada.
- **Problema o criterio pendiente:** Codex terminó con código 1. stderr: WARNING: failed to clean up stale arg0 temp dirs: Acceso denegado. (os error 5)
WARNING: proceeding, even though we could not create PATH aliases: Acceso denegado. (os error 5) at path "C:\\Users\\yeiso\\.codex\\tmp\\arg0\\codex-arg0dp9PXp"
2026-08-13T02:14:07.174864Z  WARN codex_state::runtime: failed to open state db at C:\Users\yeiso\.codex\state_5.sqlite: failed to open state DB at C:\Users\yeiso\.codex\state_5.sqlite: error returned from database: (code: 8) attempt to write a readonly database
2026-08-13T02:14:07.174898Z  WARN codex_rollout::state_db: failed to initialize state runtime: failed to initialize state runtime at C:\Users\yeiso\.codex: failed to open state DB at C:\Users\yeiso\.codex\state_5.sqlite: error returned from database: (code: 8) attempt to write a readonly database: error returned from database: (code: 8) attempt to write a readonly database: (code: 8) attempt to write a readonly database
Reading additional input from stdin...
Error: failed to initialize in-pr... Codex no generó el resultado JSON final.
- **Evidencia:** .codex-runs/T066-20260813-041407
- **Acción necesaria:** Revisar la evidencia y decidir cómo continuar.
- **Dependencias afectadas:** el orquestador no ejecutará tareas que dependan directa o indirectamente de T066.


## T066 — Asistente de exportación

- **Fecha:** 2026-08-13T04:24:58.4730117+02:00
- **Estado:** BLOCKED / RECOVERED
- **Parte completada:** No determinada.
- **Problema o criterio pendiente:** La ejecución anterior terminó sin resultado verificable.
- **Evidencia:** No disponible.
- **Acción necesaria:** Revisar los cambios y artefactos de T066, y después usar Retry explícitamente.
- **Dependencias afectadas:** el orquestador no ejecutará tareas que dependan directa o indirectamente de T066.


## T066 — Asistente de exportación

- **Fecha:** 2026-08-13T17:08:40.4392092+02:00
- **Estado:** BLOCKED
- **Parte completada:** No determinada.
- **Problema o criterio pendiente:** Codex terminó con código 1. stderr: WARNING: failed to clean up stale arg0 temp dirs: Acceso denegado. (os error 5)
WARNING: proceeding, even though we could not create PATH aliases: Acceso denegado. (os error 5) at path "C:\\Users\\yeiso\\.codex\\tmp\\arg0\\codex-arg0BsaOYt"
2026-08-13T15:08:38.308966Z  WARN codex_state::runtime: failed to open state db at C:\Users\yeiso\.codex\state_5.sqlite: failed to open state DB at C:\Users\yeiso\.codex\state_5.sqlite: error returned from database: (code: 8) attempt to write a readonly database
2026-08-13T15:08:38.309024Z  WARN codex_rollout::state_db: failed to initialize state runtime: failed to initialize state runtime at C:\Users\yeiso\.codex: failed to open state DB at C:\Users\yeiso\.codex\state_5.sqlite: error returned from database: (code: 8) attempt to write a readonly database: error returned from database: (code: 8) attempt to write a readonly database: (code: 8) attempt to write a readonly database
Reading additional input from stdin...
Error: failed to initialize in-pr... Codex no generó el resultado JSON final.
- **Evidencia:** .codex-runs/T066-20260813-170838
- **Acción necesaria:** Revisar la evidencia y decidir cómo continuar.
- **Dependencias afectadas:** el orquestador no ejecutará tareas que dependan directa o indirectamente de T066.


## T071 — Pipeline de recursos web

- **Fecha:** 2026-08-13T18:24:20.4070562+02:00
- **Estado:** BLOCKED
- **Parte completada:** No determinada.
- **Problema o criterio pendiente:** El control independiente terminó con código 1: Would reformat: tools\build_map_assets.py
1 file would be reformatted, 148 files already formatted
- **Evidencia:** .codex-runs/T071-20260813-181616
- **Acción necesaria:** Revisar la evidencia y decidir cómo continuar.
- **Dependencias afectadas:** el orquestador no ejecutará tareas que dependan directa o indirectamente de T071.


## T071 — Pipeline de recursos web

- **Fecha:** 2026-08-13T18:27:42.6899606+02:00
- **Estado:** BLOCKED
- **Parte completada:** No determinada.
- **Problema o criterio pendiente:** El control independiente terminó con código 1: 149 files already formatted
tools\build_map_assets.py:3:1: I001 [*] Import block is un-sorted or un-formatted
   |
 1 |   """Construye recursos web del mapa de forma bloqueada y verificable."""
 2 |
 3 | / from __future__ import annotations
 4 | |
 5 | | import argparse
 6 | | import hashlib
 7 | | import json
 8 | | import re
 9 | | import shutil
10 | | import subprocess
11 | | from pathlib import Path
   | |________________________^ I001
   |
   = help: Organize imports

Found 1 error.
[*] 1 fixable with the `--fix` option.
- **Evidencia:** .codex-runs/T071-20260813-182500
- **Acción necesaria:** Revisar la evidencia y decidir cómo continuar.
- **Dependencias afectadas:** el orquestador no ejecutará tareas que dependan directa o indirectamente de T071.


## T072 — Bridge tipado del mapa

- **Fecha:** 2026-08-13T18:44:43.7633930+02:00
- **Estado:** BLOCKED
- **Parte completada:** No determinada.
- **Problema o criterio pendiente:** El control independiente terminó con código 1: Would reformat: tests\test_map_bridge.py
1 file would be reformatted, 156 files already formatted
- **Evidencia:** .codex-runs/T072-20260813-183917
- **Acción necesaria:** Revisar la evidencia y decidir cómo continuar.
- **Dependencias afectadas:** el orquestador no ejecutará tareas que dependan directa o indirectamente de T072.


## T073 — Shapes y paradas interactivos

- **Fecha:** 2026-08-13T18:54:19.4429429+02:00
- **Estado:** BLOCKED
- **Parte completada:** No determinada.
- **Problema o criterio pendiente:** Codex terminó con código 1. stderr: WARNING: failed to clean up stale arg0 temp dirs: Acceso denegado. (os error 5)
WARNING: proceeding, even though we could not create PATH aliases: Acceso denegado. (os error 5) at path "C:\\Users\\yeiso\\.codex\\tmp\\arg0\\codex-arg0md34pM"
2026-08-13T16:54:17.321250Z  WARN codex_state::runtime: failed to open state db at C:\Users\yeiso\.codex\state_5.sqlite: failed to open state DB at C:\Users\yeiso\.codex\state_5.sqlite: error returned from database: (code: 8) attempt to write a readonly database
2026-08-13T16:54:17.321435Z  WARN codex_rollout::state_db: failed to initialize state runtime: failed to initialize state runtime at C:\Users\yeiso\.codex: failed to open state DB at C:\Users\yeiso\.codex\state_5.sqlite: error returned from database: (code: 8) attempt to write a readonly database: error returned from database: (code: 8) attempt to write a readonly database: (code: 8) attempt to write a readonly database
Reading additional input from stdin...
Error: failed to initialize in-pr... Codex no generó el resultado JSON final.
- **Evidencia:** .codex-runs/T073-20260813-185417
- **Acción necesaria:** Revisar la evidencia y decidir cómo continuar.
- **Dependencias afectadas:** el orquestador no ejecutará tareas que dependan directa o indirectamente de T073.


## T073 — Shapes y paradas interactivos

- **Fecha:** 2026-08-13T20:48:56.7483126+02:00
- **Estado:** BLOCKED
- **Parte completada:** No determinada.
- **Problema o criterio pendiente:** El control independiente terminó con código -1073741819: 163 files already formatted
All checks passed!
Success: no issues found in 101 source files
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.3.5, pluggy-1.6.0
rootdir: C:\Users\yeiso\Desktop\Folder\VSCode\Proyectos\GTFS Explorer Desktop
configfile: pyproject.toml
collected 171 items

tests\test_atomic_output.py ....                                         [  2%]
tests\test_best_practices_and_validation_report.py ..                    [  3%]
tests\test_core_normalizer.py ...                                        [  5%]
tests\test_csv_exporter.py ...                                           [  7%]
tests\test_directory_source.py ..                                        [  8%]
tests\test_duckdb_database.py .....                                      [ 11%]
tests\test_duckdb_repositories.py .....                                  [ 14%]
tests\test_entrypoint.py .                                               [ 14%]
tests\test_export_assistant.py .....                                     [ 17%]
tests\test_feed_overview.py .                                            [ 18%]
tests\test_field_reference_validation.py ..                              [ 19%]
tests\test_fixtures.py .                                                 [ 19%]
tests\test_geojson_exporter.py ...                                       [ 21%]
tests\test_geometry_queries.py ...                                       [ 23%]
...
- **Evidencia:** .codex-runs/T073-20260813-203852
- **Acción necesaria:** Revisar la evidencia y decidir cómo continuar.
- **Dependencias afectadas:** el orquestador no ejecutará tareas que dependan directa o indirectamente de T073.

<!-- ORCHESTRATOR_ENTRIES -->

## T094 — Matriz de smoke en Windows limpio

- **Fecha:** 2026-08-15
- **Estado:** DONE
- **Parte completada:** El responsable confirmó P01, P02, I01 e I02 con los artefactos fijados. El recorrido cubrió portable e instalador offline, importación, validación, consultas, mapa PMTiles con rutas/paradas, exportaciones JSON/CSV, ayuda local, rutas especiales y conservación del workspace tras desinstalar.
- **Problema o criterio pendiente:** ninguno para T094. I03 se registra como skip justificado porque 0.1.0 es la primera versión instalable y no existe un setup N-1 verificable; será obligatorio en la siguiente versión.
- **Evidencia:** `tests/packaging/evidence/T094-2026-08-13/`, `tests/packaging/evidence/T094-2026-08-14/` y `tests/packaging/SMOKE_MATRIX.md`.
- **Acción necesaria:** continuar con T096.
- **Dependencias afectadas:** T096 queda desbloqueada.

## T070 — Spike vinculante Qt WebEngine/MapLibre/PMTiles

- **Fecha:** 2026-08-13
- **Estado:** DONE / NO_GO
- **Parte completada:** Prototipo aislado de esquema local y CSP disponible en `spikes/map_webengine/`.
- **Problema o criterio pendiente:** `QWebEngineUrlRequestJob` no puede responder con HTTP 206 Partial Content y el bridge QWebChannel no quedó demostrado con los recursos del entorno.
- **Evidencia:** `spikes/map_webengine/README.md` y DEC-015.
- **Acción necesaria:** Tomar una nueva decisión técnica antes de evaluar un loopback estrictamente local en un spike independiente.
- **Dependencias afectadas:** T071--T075 no pueden continuar.

## T070 — Desbloqueo mediante loopback local protegido

- **Fecha:** 2026-08-13T18:06:48+02:00
- **Estado:** DONE / GO (supera el NO_GO anterior)
- **Parte completada:** MapLibre/PMTiles real, QWebChannel bidireccional, rangos HTTP y standalone Windows demostrados.
- **Resolución:** DEC-016 acepta un servidor efímero limitado a `127.0.0.1`, con token/puerto aleatorios, validación `Host`, allowlist, CSP y cierre ligado a la vista.
- **Evidencia:** `spikes/map_webengine/loopback_spike.py`, `tests/test_map_loopback_spike.py` y build local `.tmp/t070-loopback-nuitka/loopback_spike.dist/`.
- **Resultado:** T071 queda READY; el bloqueo transitivo de T071--T075 queda resuelto.

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.
