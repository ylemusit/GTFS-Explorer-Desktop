# GTFS Explorer — North Star de producto

## Definición

GTFS Explorer es una plataforma profesional local-first de aseguramiento de
calidad y ciclo de vida de datos de transporte. Permite a operadores,
autoridades, integradores y consultoras inspeccionar, validar, comparar,
diagnosticar, corregir y documentar feeds de movilidad de manera trazable y
reproducible.

No se define como un editor GTFS: el editor es una capacidad para resolver
incidencias controladamente dentro de ese ciclo.

## Problema y propuesta de valor

Los equipos técnicos reciben feeds con calidad, procedencia y cambios difíciles
de explicar. La propuesta es convertir un feed y sus incidencias en evidencia
reproducible: qué cambió, por qué importa, qué se corrigió y qué resultado se
verificó. Esto reduce revisión manual, riesgo de aceptación y tiempo de
coordinación entre proveedor y destinatario.

## Ciclo de valor

| Etapa | Estado | Alcance |
| --- | --- | --- |
| Receive | CURRENT | Apertura local segura y procedencia por hash. |
| Inspect | CURRENT | Exploración relacional, raw y mapa local. |
| Validate | CURRENT | Reglas trazables, severidades e informe técnico. |
| Compare | NEXT | Diff de versiones con cambio, causa e impacto. |
| Diagnose | CURRENT / NEXT | Problemas trazables hoy; priorización causa-impacto después. |
| Correct | CURRENT | Working Copy, revisiones y ChangeSets no destructivos. |
| Verify | CURRENT | Revalidación, exportación atómica y Mini-GTFS reimportable. |
| Document | CURRENT / NEXT | Informes técnicos hoy; informe profesional reproducible después. |
| Approve / Publish | FUTURE | Flujo de aceptación y publicación, no automatizado en 0.2.0. |
| Monitor | FUTURE | Revisión programada, alertas e histórico recurrente. |

## Usuarios y oferta posible

| Perfil | Problema / job-to-be-done | Valor | Dificultad comercial | Oferta posible |
| --- | --- | --- | --- | --- |
| Consultora pequeña/mediana | Auditar un feed y sustentar hallazgos ante cliente. | Evidencia, informe y paquete reproducible. | Media; ciclo de venta relativamente corto. | GTFS Health Check o auditoría por proyecto. |
| Integrador SAE-CAD-AVL | Entregar/aceptar feeds entre sistemas y aislar regresiones. | Diff, diagnóstico e incidente acotado. | Media-alta; integración y confianza. | Validación de entrega y soporte de aceptación. |
| Operador pequeño/mediano | Corregir publicación sin equipo especializado. | Lista priorizada y corrección controlada. | Media; presupuesto limitado. | Health Check con recomendaciones. |
| Autoridad/consorcio pequeño | Verificar calidad de feeds de proveedores. | Criterio repetible y evidencia de aceptación. | Alta; contratación pública. | Auditoría independiente o piloto acotado. |
| Equipo técnico de transporte | Investigar y explicar defectos complejos. | Menos tiempo de diagnóstico y contexto compartible. | Baja dentro de un piloto, sin comprador confirmado. | Servicio técnico recurrente. |
| Gran operador/administración | Gobernar múltiples proveedores y versiones. | Histórico, automatización y control contractual. | Muy alta; requisitos de seguridad, SLA y compra. | Futuro enterprise, tras validación. |

## Diferenciación a validar

Abrir GTFS, mostrar rutas, edición básica o validación estándar básica no son
diferenciación suficiente. La dirección diferencial es:

| Capacidad | Clasificación |
| --- | --- |
| Validación trazable, Working Copy, revisiones, ChangeSets, Mini-GTFS | CURRENT |
| GTFS Diff, relación causa-impacto, informe profesional, evidencia versionada | NEXT |
| Incident Package/Mini-GTFS orientado a soporte | NEXT, requiere comprobar demanda |
| Batch validation, CLI/CI e histórico de feeds | FUTURE, validación comercial requerida |
| Aceptación/auditoría de proveedores y monitorización | FUTURE, validación comercial requerida |

## Principios

- Local-first, sin nube preventiva ni datos de cliente fuera del control acordado.
- La evidencia debe poder repetirse con hashes, reglas y versiones identificadas.
- Una métrica de calidad sólo se ofrecerá cuando exista metodología defendible;
  hasta entonces se comunican errores, avisos, notices, integridad, cobertura,
  frescura y riesgo de cambio.
- Ninguna capacidad grande entra sin cerrar una versión, demanda real o una
  propuesta comercial concreta.

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.
