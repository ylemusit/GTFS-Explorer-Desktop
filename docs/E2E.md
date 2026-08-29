# P1-23 — Matriz operativa E2E

Esta suite prueba recorridos de usuario sobre la arquitectura productiva del
proyecto: `MainWindow`, `ImportJobAdapter`/`QThread`, `ImportFeed`, DuckDB
file-backed, consultas de exploración, exportadores, historial, recuperación y
política de mapas. No duplica las pruebas unitarias de reglas o repositorios.

## Ejecución

Desde la raíz del repositorio:

```powershell
.venv\Scripts\python.exe -m pytest -m e2e tests\test_e2e_journeys.py
```

La suite usa únicamente fixtures ficticios locales, `tmp_path` por caso, una
biblioteca PMTiles temporal y conexiones DuckDB en archivos temporales. No
descarga feeds ni hace llamadas de red externas. El único proceso hijo es el
escenario de lock real.

## Matriz

| ID | Recorrido real | Contrato crítico comprobado | Resultado |
|---|---|---|---|
| E2E-01 | Crear proyecto → importar → progreso → validar → explorar ruta/viaje/paradas → RAW → exportar → cerrar/reabrir | `READY`, resumen de validación sin errores bloqueantes, horas `24:10:00`, `source_row`, manifest privado, historial y estado durable | PASS |
| E2E-02 | Importar feed defectuoso → abrir validación → detalle → ir a RAW → exportar | Feed `INVALID` pero importación `COMPLETED`; error trazable a `stop_times.txt`/`MISSING_STOP`; el feed sigue inspeccionable y exportable | PASS |
| E2E-03 | Primera importación → cancelar en staging → continuar con otro intento | `CANCELLED`, proyecto utilizable, sin filas GTFS parciales, operación cancelada y siguiente importación `READY` | PASS |
| E2E-04 | Importar feed A → cancelar reimportación de B → cerrar/reabrir | El feed A permanece como último feed importado; no se publican datos de B; ledger y vistas siguen coherentes | PASS |
| E2E-05 | Exportar desde UI JSON, CSV, GeoJSON y Mini-GTFS → reimportar Mini-GTFS | Artefactos reales, manifest SHA-256, nombres sin rutas, cuatro operaciones `COMPLETED` y Mini-GTFS reimportable `READY` sin incidencias | PASS |
| E2E-06 | Cambiar proyecto A → B | Se limpian rutas, validación, RAW y contexto dependiente del feed anterior; no se mezclan identidades | PASS |
| E2E-07 | Importar → exportar → cerrar → reabrir | Se reconstruyen overview, explorador, validación, RAW e historial desde el workspace durable | PASS |
| E2E-08 | Abrir el mismo workspace en dos procesos reales | El segundo escritor recibe conflicto de lock; al terminar el primer proceso el lock queda liberado y el workspace vuelve a abrirse | PASS |
| E2E-09 | Recuperar descriptor inválido/ausente y abrir DB corrupta | Recovery seguro, informe sin rutas privadas/traceback, descriptor reconstruido y DB original preservada ante corrupción no recuperable | PASS |
| E2E-10 | Importar PMTiles local → seleccionar modo offline → consultar viaje con mapa | Paquete raster local renderizable, overlay GTFS conservado, origen `127.0.0.1` permitido y tesela remota bloqueada sin query con datos del feed | PASS |
| E2E-11 | Fallo técnico controlado de importación | Estado `FAILED`, operación fallida y UI sin presentar el error como `READY` | PASS |

La suite contiene 11 tests `pytest.mark.e2e` y pasó `11 passed` en 49,15 s en
el entorno de desarrollo del 2026-08-27.

## Límites y aislamiento

- El WebEngine visual se sustituye en esta suite por un doble funcional
  controlado: se conserva la consulta real de capas, el payload del overlay,
  el modo, el paquete y la selección de parada, pero no se hacen asserts de
  píxeles. El render offscreen/WebGL tiene un smoke separado; esta decisión
  evita convertir una limitación gráfica del runner en un falso fallo de
  negocio.
- E2E-10 sí ejecuta la política e interceptor productivos de red; el doble solo
  sustituye el render para mantener el test determinista y offline.
- Las barreras de progreso tienen timeout máximo de 10 s, las importaciones de
  15 s y el proceso de lock de 5 s. Cada caso libera barreras, cierra la
  ventana y cierra sus conexiones/procesos temporales.
- Los manifests se revisan para que no incluyan la ruta del proyecto, el perfil
  de usuario, traceback ni secretos. No se imprimen rutas absolutas en la UI.

## Clasificación

- `BLOCKER`: ninguno detectado en esta matriz.
- `IMPORTANTE-PERO-NO-BLOQUEANTE`: el smoke visual WebEngine offscreen sigue
  separado; la UI puede mostrar `VALID_WITH_WARNINGS` cuando el fixture tiene
  advertencias de calidad, aunque el job sea `READY` y no haya errores
  bloqueantes.
- `BACKLOG`: prueba visual pixel-based en Windows con renderer disponible y
  optimización del staging LARGE. No se amplía P1-23 a portable, NSIS ni
  packaging.

---

Propietario y autor: Yeison Arbey Carrillo Lemus.  
Todos los derechos reservados.
