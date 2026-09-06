# Estructura del repositorio

## Tres espacios con responsabilidades distintas

- **GTFS Explorer Desktop** es el repositorio activo: código fuente, recursos
  mantenidos, tests permanentes, migraciones soportadas, scripts de desarrollo,
  documentación canónica y configuración necesaria.
- **GTFS Explorer Engineering** conserva conocimiento histórico: decisiones,
  investigaciones, incidentes, experimentos y análisis de gates.
- **GTFS Explorer Artifacts** conserva builds, manifests, hashes y evidencias
  de validación o release.

El repositorio activo no debe contener copias de builds, evidencias de una
ejecución concreta ni diagnósticos de una máquina. Los fixtures y tests que
forman parte de la regresión permanente sí permanecen en `tests/`.

No file is kept in the active repository solely because it once participated
in development.

La trazabilidad histórica se obtiene mediante el historial Git, las etiquetas
inmutables, el archivo Engineering cuando existe valor consultable y el
almacén Artifacts cuando se trata de evidencia o distribución. La etiqueta
`v0.2.0` conserva el árbol original y no se reescribe.

## Árbol activo

`src/` contiene el producto Python; `web/` sus recursos web; `schemas/` los
contratos; `tests/` las pruebas permanentes; `tools/` el tooling mantenido;
`packaging/` Portable y NSIS; `docs/` la documentación; y `examples/` ejemplos.

Los artefactos temporales se generan fuera del árbol rastreado y los archivos
locales están cubiertos por `.gitignore`.

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.
