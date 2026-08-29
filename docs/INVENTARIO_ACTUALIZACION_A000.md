# Inventario de trabajo local para la actualización

Fecha: 2026-08-18

Tarea: `A000` — Inventariar y aislar el trabajo local existente

Estado: **DONE**

## Criterio de clasificación

- **Incluido:** forma parte de la línea base documental de la actualización.
- **Diferido:** se conserva intacto, pero no se atribuye todavía a la siguiente
  versión; deberá decidirse y validarse en la tarea indicada.
- **Descartado:** se excluiría de la actualización sin eliminar el archivo local.

## Inventario y decisión

| Cambio local | Procedencia comprobable | Decisión A000 | Tarea de decisión | Riesgos y pruebas pendientes |
| --- | --- | --- | --- | --- |
| `docs/PLAN_ACTUALIZACION_HERRAMIENTA.md` | Plan local creado el 2026-08-18 y autorizado por Yeison para ejecutar `A000` | **Incluido** como documento de control; no implica aprobar las tareas posteriores | `A001` fijará alcance y versión | Mantener sus estados alineados con `docs/CURRENT_STATE.md` y no interpretar el plan como autorización de publicación |
| `packaging/nsis/installer.nsi` | Diff local ya identificado por el plan como trabajo del usuario | **Diferido**; se conserva sin atribuirlo a una versión | `A010` y `A013` | Textos de identidad y año duplicados; confirmar localización y comportamiento MUI; ampliar la prueba del script y construir/probar el instalador real |
| `src/gtfs_explorer/presentation/desktop/main_window.py` | Diff local ya identificado por el plan como trabajo del usuario | **Diferido**; se conserva junto a `startup_intro.py` como una sola unidad funcional | `A010` y `A011` | El diálogo modal se ejecuta en cada arranque; faltan decisión de frecuencia, prueba del flujo `run_window` y comprobación accesible/visual |
| `src/gtfs_explorer/presentation/desktop/startup_intro.py` | Archivo local no seguido, enlazado únicamente desde el cambio de `main_window.py` | **Diferido**; no se considera incorporado ni terminado | `A010` y `A011` | Depende del import local anterior; textos y estilos están embebidos; faltan pruebas unitarias, accesibilidad, traducción y validación visual |
| `src/gtfs_explorer/presentation/desktop/overview/widget.py` | Diff local ya identificado por el plan como trabajo del usuario | **Diferido**; se conserva sin atribuirlo a una versión | `A010` y `A012` | Identidad y año duplicados; falta comprobar estados vacío/sin feed/con feed, foco, contraste y pruebas Qt del bloque de bienvenida |
| `examples/ctm-mallorca-es.zip` | Feed GTFS del portal oficial de datos abiertos del Consorci de Transports de Mallorca (CTM), con licencia declarada CC BY 4.0 | **Excluido de la actualización por decisión de alcance** | Ninguna; `A021` no podrá usar este ZIP | No incorporar a artefactos ni al recorrido de ejemplo; el archivo local se conserva sin cambios |

No se descarta ningún cambio en `A000`. Los cambios diferidos permanecen en el
árbol de trabajo exactamente como estaban.

## Aislamiento del feed externo

- Ruta local: `examples/ctm-mallorca-es.zip`.
- Procedencia: [portal de datos abiertos del CTM](https://www.tib.org/es/sobre-ctm/portal-de-transparencia/datos-abiertos), consultado el 2026-08-18.
- Licencia declarada por el portal: Creative Commons Attribution 4.0
  International (CC BY 4.0).
- Tamaño: `6.391.538` bytes.
- SHA-256:
  `60CD4FCB34F95DD11BE3DF39BEA772AE643A18D28042B7CCA080A7CB0E08E794`.
- Contiene once archivos GTFS en la raíz: `agency.txt`, `stops.txt`,
  `routes.txt`, `calendar.txt`, `calendar_dates.txt`, `trips.txt`,
  `stop_times.txt`, `shapes.txt`, `feed_info.txt`, `levels.txt` y
  `pathways.txt`.
- El pipeline portable empaqueta la distribución generada, los recursos locales
  declarados y los recursos del mapa; no copia `examples/`. El instalador se
  construye exclusivamente desde ese ZIP portable verificado. Por tanto, el
  feed no entra actualmente en ninguno de los dos artefactos.

El ZIP permanece fuera del alcance de la actualización por decisión expresa y
no se auditará ni se incorporará a artefactos.

## Línea base reproducible

Antes de `A000`, `git status --short` mostraba tres archivos seguidos
modificados y tres archivos no seguidos: el diálogo inicial, el feed externo y
el plan de actualización. `A000` solo añade este inventario y actualiza la
documentación de estado; no reescribe ni elimina el trabajo inventariado.

La siguiente tarea posible es `A001`. Debe ejecutarse en otra sesión y no se
considera autorizada por el cierre de `A000`.
