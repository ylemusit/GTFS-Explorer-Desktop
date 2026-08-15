# Rendimiento medido localmente

Última actualización: 2026-08-14

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
