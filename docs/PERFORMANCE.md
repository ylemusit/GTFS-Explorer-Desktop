# Rendimiento medido localmente

Última actualización: 2026-08-27

## T075 — presupuesto visual del mapa

Comando reproducible: ` .venv\Scripts\python.exe tools\benchmark_map_lod.py`.

Medición local en Windows 11 10.0.26200, Python del entorno del proyecto:

| Entrada | Viewport | Salida al WebEngine | Tiempo de preparación |
|---|---:|---:|---:|
| 50.000 paradas, 100.000 puntos de shape | zoom 12 | 2.000 paradas, 1.034 puntos | 68,77 ms |

El presupuesto de renderizado es de 2.000 paradas y 4.000 puntos por shape. Las
paradas se agrupan visualmente en MapLibre y el resultado se cachea para hasta
32 viewports. Esta medición cubre la transformación visual pura; no acredita
todavía importación, WebEngine, RAM ni el objetivo RNF-006 completo, que se
mide en T095.

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.

## P1-21 — rendimiento formal reproducible

La infraestructura está en `src/gtfs_explorer/performance.py`, el ejecutor en
`tools/benchmark.py` y los contratos estructurales en
`tests/test_p1_21_performance.py`. El generador produce feeds ficticios,
deterministas y válidos con semilla 21; no usa ni versiona CTM.

| Perfil | Agencias | Rutas | Paradas | Viajes | `stop_times` | Shapes | Puntos shape | Servicios |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| SMALL | 1 | 10 | 500 | 250 | 5.000 | 10 | 20 | 2 |
| MEDIUM | 2 | 50 | 5.000 | 1.000 | 50.000 | 50 | 100 | 4 |
| LARGE | 4 | 150 | 15.000 | 3.000 | 225.000 | 150 | 300 | 8 |
| XL | 4 | 300 | 30.000 | 7.500 | 600.000 | 300 | 600 | 12 |

La ejecución normal usa un temporal por escenario y no escribe datos de
operadores. El límite es independiente por worker, configurable y devuelve
`TIMEOUT` sin abortar los escenarios siguientes; el valor CLI por defecto es
900 s, no un umbral de aceptación.

Ejemplos reproducibles:

```powershell
.venv\Scripts\python.exe tools\benchmark.py --profile small --scenario export --max-duration 180 --json C:\temp\p1-21-small.json
.venv\Scripts\python.exe tools\benchmark.py --profile medium --scenario import --max-duration 900 --json C:\temp\p1-21-medium-import.json
.venv\Scripts\python.exe tools\benchmark.py --profile large --scenario import --max-duration 300 --json C:\temp\p1-21-large-import.json
```

Los escenarios disponibles son `generate`, `zip`, `workspace`, `import`,
`validation`, `reopen`, `raw`, `relational`, `validation_queries`, `map`,
`csv`, `json`, `geojson`, `mini_gtfs` y `export`. Cada resultado incluye
`scenario_start`, `phase_start`, `phase_end`, `elapsed`, duración, estado,
conteos, tamaños de feed/workspace/salida y throughput basado en las filas
generadas. No se registran filas individuales. El JSON no contiene paths,
usuario, hostname ni secretos; los temporales del worker se eliminan incluso
tras un timeout. La memoria reporta explícitamente `available: false` cuando
la API local de Windows no devuelve contadores.

La instrumentación separa generación, compresión ZIP, workspace, preflight,
staging, normalización core/geometría/opcional, validación, commit, apertura,
consultas RAW/relacionales/validación/mapa y exportadores CSV/JSON/GeoJSON/
Mini-GTFS. Mini-GTFS reutiliza el exportador de producto y mide también su
reimportación interna; no hay un exportador paralelo del harness.

### Baseline P1-21 de esta ejecución

La sesión se ejecutó en Windows 11, Python 3.12.10, DuckDB 1.1.3,
arquitectura AMD64 y 24 CPU lógicas. Son observaciones de esta máquina, no SLA.

| Fase de `import` completo | SMALL | MEDIUM |
|---|---:|---:|
| Generación | 0,007 s | 0,055 s |
| Workspace | 0,105 s | 0,209 s |
| `PREFLIGHT` | 0,014 s | 0,021 s |
| `STAGING` | 17,524 s | 173,906 s |
| `NORMALIZING` | 21,491 s | 217,085 s |
| `VALIDATING` | 32,272 s | 67,649 s |
| `COMMITTING` | 0,074 s | 0,106 s |
| Tiempo total del escenario | 71,892 s | 459,612 s |
| Estado / incidencias | `READY` / 0 | `READY` / 0 |

La validación desacoplada terminó `VALID_WITH_WARNINGS` en 72,558 s para
SMALL (4.868 incidencias, 0 omitidas) y en 476,508 s para MEDIUM (49.228
incidencias, 0 omitidas). El throughput MEDIUM observado fue 315,740 filas/s
en staging, 246,592 filas/s en normalización core y 804,102 filas/s en
validación; el workspace llegó a 20.983.808 bytes.

Las consultas de producto fueron cortas después de la preparación:

| Escenario | SMALL | MEDIUM |
|---|---:|---:|
| RAW, 5 iteraciones | 0,192 s | 0,176 s |
| Explorador relacional, 5 iteraciones | 0,221 s | 0,235 s |
| `ValidationQueries`, 5 iteraciones | 0,243 s | 0,214 s |
| Mapa, 3 iteraciones | 0,131 s | `TIMEOUT` a 180 s durante normalización |
| Reapertura real (`OpenProject`), 3 ciclos | 0,358 s (mediana 0,120 s) | 0,361 s (mediana 0,118 s) |

Los exportadores SMALL terminaron `PASS`: CSV 128 bytes, JSON 213.400 bytes,
GeoJSON 100.869 bytes y Mini-GTFS 8.893 bytes. La reimportación interna
Mini-GTFS tardó 15,793 s y verificó el cierre de 1 agencia, 1 ruta, 25 viajes,
500 paradas y 2 servicios. El escenario conjunto de exportación también pasó.
Los cinco escenarios de exportación MEDIUM (`csv`, `json`, `geojson`,
`mini_gtfs` y `export`) devolvieron `TIMEOUT` aislado a 180 s tras cerrar
staging (151--154 s) y comenzar `setup.normalizing.core`; no se atribuye un
fallo a ningún exportador.

LARGE pasó generación (0,240 s), compresión ZIP (0,128 s; 1.474.674 bytes) y
workspace (0,086 s). Su importación se detuvo como `TIMEOUT` a 300,012 s con
`STAGING` activo, sin marcar `FAILED` ni ejecutar una GUI. Esto es consistente
con el escalado lineal observado; no se modificaron las dimensiones para
ocultar el coste.

### Diagnóstico y clasificación

Las clases del resultado son `BENCHMARK_GENERATOR` para generación,
`BENCHMARK_HARNESS` para ZIP/workspace, `PRODUCT_IMPORT` para importación,
`PRODUCT_VALIDATION` para validación, `PRODUCT_QUERY` para RAW/relacional/
validación/mapa/reapertura y `PRODUCT_EXPORT` para CSV/JSON/GeoJSON/Mini-GTFS.

El cuello MEDIUM no está en generación, preflight, consultas ni commit: está
en las inserciones de DuckDB durante staging y normalización. `StagingLoader`
ya usa lotes de 1.000 mediante `executemany`; un experimento controlado de
5.000 filas y 16 columnas con DuckDB 1.1.3 midió 29,284 s con cinco lotes
`executemany` frente a 26,850 s con sentencias multi-fila, por lo que la
segunda vía no es una corrección suficiente. Cambiar temporalmente de 1 a 4
threads tampoco mejoró el caso (27,400 s frente a 29,516 s). No se observa N²
en las consultas.

El perfil dirigido cProfile de SMALL registró 5.783 filas de staging en
`_staging_row` y solo decenas de llamadas del wrapper de base; el tiempo está
en la llamada C de DuckDB. En core se observaron 5.786 llamadas a
`DatabaseConnection.execute`, coherentes con el bucle de inserción por fila,
pero la agrupación experimental no redujo el tiempo SMALL (21,32 s frente a
aproximadamente 20,09 s). El perfil completo queda afectado por la sobrecarga
de importación interna del runtime, así que las duraciones acreditadas son las
de `perf_counter` por fase, no las del profiler.

### P1-22 — comparación SMALL tras instrumentación

La instrumentación de progreso granular mantiene el pipeline de importación y
no añade una pasada de lectura. En la misma máquina, el benchmark SMALL
posterior terminó `READY` en `75,572 s`, frente a los `71,892 s` de la baseline
P1-21 (diferencia observada del 5,1 % en una ejecución que coincidió con otras
validaciones). No se considera una degradación material reproducible; el
hallazgo de rendimiento LARGE continúa separado y no se optimiza en P1-22.

La medición UI no cambia la clasificación funcional: staging comunica basename
y filas acumuladas en eventos estrangulados, mientras las fases sin total real
son indeterminadas.

Conclusión P1-21: baseline reproducible y clasificada, sin defecto funcional
ni optimización de producto justificada por esta evidencia. El coste lineal
pesado de DuckDB 1.1.3 queda como hallazgo P1-22; P1-22 no se inicia en esta
tarea. No se ejecutó suspensión del PC, apagado de pantallas ni GUI durante
las pruebas.

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.

## T095 — flujo completo y límite publicado

El ejecutable reproducible es `tools/benchmark_feed.py`. Genera un GTFS
ficticio y determinista, no emplea datos de operadores y borra el workspace
temporal al finalizar:

```powershell
.venv\Scripts\python.exe tools\benchmark_feed.py --profile small --output .tmp\t095-small.json
.venv\Scripts\python.exe tools\benchmark_feed.py --profile medium --output .tmp\t095-medium.json
.venv\Scripts\python.exe tools\benchmark_feed.py --profile rnf-006 --output .tmp\t095-rnf-006.json
```

Los tres perfiles cubren, respectivamente, pequeño (200 viajes, 500 paradas,
4.000 `stop_times`), medio (10.000/10.000/500.000) y el objetivo original
RNF-006 (100.000/50.000/5.000.000). Cada ejecución registra versión de Python
y DuckDB, plataforma, dataset, importación con validación, consulta de 500
filas, exportación JSON, preparación de capas de mapa, pico RSS, disco y
cancelación cooperativa.

### Resultado comprobado

Se ejecutó el perfil pequeño el 2026-08-14 en Windows 11 10.0.26200, Python
3.12.10 y DuckDB 1.1.3, equipo ASUS con 31,15 GiB de RAM. Con el límite de
DuckDB fijado explícitamente en 1 GiB y un único thread, los resultados fueron:

| Operación | Resultado |
|---|---:|
| Generar fixture | 0,006 s |
| Importar y validar | 38,019 s |
| Consulta paginada de 500 filas | 0,001 s |
| Exportación JSON | 0,335 s (1.000.166 bytes) |
| Preparar mapa | 0,002 s (500 paradas; 2 puntos de shape tras simplificación) |
| Cancelar al iniciar staging | 0,293 s; estado `CANCELLED` |
| Pico RSS del proceso | 71.835.648 bytes (68,5 MiB) |
| Workspace temporal | 17.527.681 bytes |

El feed sintético deliberadamente no incluye geometrías, por lo que termina
`INVALID`; esto no invalida la medida de las fases, pero impide usarla como
prueba de un feed válido listo para publicación.

### Límite vigente

El único límite de flujo completo comprobado es el perfil pequeño anterior.
RNF-006 **no está acreditado**: los perfiles medio y RNF-006 son reproducibles,
pero deben ejecutarse y conservar sus JSON antes de elevar ese límite. En
consecuencia, no se promete todavía soporte de 5 millones de `stop_times`,
100.000 viajes, 50.000 paradas ni 2 GiB comprimidos. La UI mantiene paginación,
presupuestos de mapa y cancelación; los límites de seguridad configurados no se
relajan con esta medición.
