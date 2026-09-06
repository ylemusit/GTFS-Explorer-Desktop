# Build y release

El build parte de un checkout limpio, del entorno fijado por `pyproject.toml`
y `uv.lock`, y de los scripts mantenidos en `tools/`. `tools/build_portable.py`
genera el ejecutable Windows x64 standalone y el Portable ZIP; el instalador
NSIS se genera con `tools/build_installer.py` desde el portable validado.

Los resultados no se guardan en el repositorio activo. Se depositan en GTFS
Explorer Artifacts junto con manifest, procedencia, SBOM cuando aplique y
SHA-256. La ubicación concreta puede variar por máquina o pipeline.

El código fuente, scripts y configuración permanecen en Desktop. Builds,
manifests, logs y capturas de una ejecución permanecen en Artifacts. El
diagnóstico de fallos, decisiones y análisis de experimentos permanecen en
Engineering. La procedencia debe identificar commit, versión y herramienta.

Antes de distribuir, el artefacto debe superar el smoke aplicable, la revisión
de licencias y el gate de Defender. La firma se realiza según la política
autorizada; este documento no contiene certificados, claves ni rutas privadas.
Un resultado de build local no equivale a una publicación.

Las etiquetas publicadas son inmutables. No se reescribe una etiqueta ni se
modifica un artefacto histórico para corregir una ejecución posterior.

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.
