# Roadmap de producto

## Después de 0.2.0

No se presupone una versión 0.3. Tras cerrar 0.2.0 habrá una
**COMMERCIAL VALIDATION PHASE**. La estrategia inicial es service-led product:

`AUDIT -> RECURRING SERVICE -> PROFESSIONAL SOFTWARE -> AUTOMATION / ENTERPRISE`

El primer cliente puede recibir el resultado de un servicio; no necesita
instalar GTFS Explorer.

## Oferta inicial: GTFS Health Check

Hipótesis de oferta para validar, no tarifa oficial: revisión de un feed con
Quality Report, incidencias priorizadas, recomendaciones, Mini-GTFS o Incident
Package cuando aplique, hashes/versiones y evidencia reproducible. El precio,
alcance contractual y responsabilidad sólo se determinan tras conversaciones y
validación comercial.

## Prioridades condicionadas

| Prioridad | Iniciativas | Condición |
| --- | --- | --- |
| P1 | GTFS Diff; informe profesional HTML/PDF; Incident/Mini-GTFS Package; hash, evidencia y versionado. | Validar que el Health Check necesita estos outputs. |
| P2 | Batch validation; CLI; historial de feeds. | Cliente recurrente, volumen repetido o integración solicitada. |
| P3 | Metodología/índice de calidad; monitorización continua. | Métrica defendible y necesidad recurrente demostrada. |
| P4 | GTFS Realtime. | Contrato o demanda probada que justifique complejidad operacional. |
| P5 | NeTEx / SIRI. | Cliente/contrato que cubra especialización y mantenimiento. |

## Política cloud

**NO CLOUD UNTIL RECURRING NEED.** No se crearán preventivamente SaaS backend,
autenticación, billing, licencia, base de datos cloud, Kubernetes ni
monitorización. Un flujo programado de descarga, validación, diff, informe y
alerta sólo se evaluará con necesidad recurrente o contrato.

## Gates de validación de mercado

| Gate | Evidencia mínima | Puede desbloquear |
| --- | --- | --- |
| G0 | 0.2 estable y alcance cerrado. | Prospección estructurada. |
| G1 | 30 prospects cualificados. | Ajuste de mensaje y segmentos. |
| G2 | 10 conversaciones reales. | Refinar oferta y piloto. |
| G3 | 3 organizaciones interesadas en piloto. | Preparación de piloto acotado. |
| G4 | 1 auditoría pagada. | Inversión focal que reduzca entrega. |
| G5 | 3 clientes pagadores. | Servicio recurrente y P2 evaluable. |
| G6 | Primer objetivo MRR configurable alcanzado. | Automatización/inversión ligera. |
| G7 | Segundo objetivo MRR configurable alcanzado. | Evaluar infraestructura recurrente. |
| G8 | Decisión explícita de dedicación principal. | Plan empresarial separado. |

Los importes de MRR permanecen configurables e hipotéticos hasta validación.

## Prioridad inicial de cliente

1. Consultoras de movilidad pequeñas/medianas: necesidad de entregables y
   acceso más directo a proyectos.
2. Integradores SAE-CAD-AVL: alto valor de aceptación, aunque ciclos mayores.
3. Operadores pequeños/medianos: dolor operativo, sensibilidad a presupuesto.
4. Autoridades pequeñas/consorcios: potencial de control, compra más lenta.
5. Grandes operadores/administraciones: después de prueba de credibilidad,
   soporte y contratación.

## Ecosistema (hipótesis, sin fusión)

GTFS Explorer se posiciona en calidad y datos de transporte; GoLines en
navegación/operación; AppDCBUS en inspección/operativa. Juntos podrían
comunicar Transit Technology / Digital Operations, pero siguen siendo
productos y repositorios independientes.

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.
