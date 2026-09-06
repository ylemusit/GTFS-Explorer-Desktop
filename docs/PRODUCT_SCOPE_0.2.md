# Alcance de producto — Desktop 0.2.0

## Definición de la versión

**GTFS Explorer Desktop 0.2.0 = Visual GTFS Workbench estable.** Es una
versión finita: una estación de trabajo local para inspeccionar, validar y
corregir GTFS Schedule sin modificar el original, no el inicio de una cadena
indefinida de funcionalidades.

## Estado preservado

`PAUSED_BY_STRATEGIC_REBASELINE`

El punto de reanudación es el árbol actual de
`feature/0.2.0-visual-editor`, con el editor no destructivo basado en Working
Copy, revisiones y ChangeSets (DEC-020) y el gate técnico async/UI registrado
como PASS técnico. No se deben reinterpretar, limpiar ni adelantar los cambios
existentes durante la reanudación. La próxima tarea deberá tener descriptor
propio y atacar un único pendiente MUST HAVE.

## Clasificación de pendientes

| Clase | Pendiente |
| --- | --- |
| MUST HAVE TO CLOSE 0.2 | Aceptación visual nativa manual del editor en Windows: DPI, WebEngine, accesibilidad y flujo real. Registrar resultado separado del smoke técnico. |
| MUST HAVE TO CLOSE 0.2 | Gate de distribución sólo cuando se autorice: resolver legítimamente el bloqueo de Defender y completar evidencia de packaging/release. No desactivar Defender ni añadir exclusiones. |
| SHOULD HAVE | Propagación avanzada de horarios, si una tarea focal demuestra que es necesaria para completar un flujo de corrección ya incluido. |
| BACKLOG | Sesión multirruta adicional, preview, mapa Recorrido, Stop Inspector, edición geométrica adicional, nuevas capacidades de horarios, ajustes DPI no revelados por aceptación y cualquier expansión del editor. |

La corrección de una regresión demostrada en un MUST HAVE no es feature creep;
la incorporación de una capacidad nueva sí lo es hasta que pase el gate de
features.

## Fuera de 0.2.0

- GTFS Diff y calidad causa-impacto como propuesta comercial.
- Reporting profesional PDF/HTML, Incident Package orientado a cliente e
  histórico de feeds.
- Batch, CLI/CI, monitorización, backend SaaS, autenticación, facturación,
  licensing/DRM y servidor de cuentas.
- GTFS Realtime, NeTEx, SIRI, routing automático y operaciones 24x7.

## Gate de funcionalidades

Una feature grande sólo puede entrar si cumple, con evidencia documentada, al
menos una condición:

1. Es necesaria para cerrar correctamente 0.2.0.
2. La solicita un cliente o piloto real.
3. Habilita de forma directa una propuesta comercial definida.

Si no cumple una condición, queda en BACKLOG. El feature creep es un riesgo
estratégico prioritario porque retrasa la evidencia de valor y el cierre de
versión.

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.
