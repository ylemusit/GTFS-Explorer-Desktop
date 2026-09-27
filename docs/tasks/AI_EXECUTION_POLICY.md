# AI execution policy v1.0

Esta política orienta el perfil de cada run; el contrato de tarea no fija modelo. Las recomendaciones son hipótesis operativas, sujetas a disponibilidad, coste autorizado y evidencia del proyecto. La [guía oficial de modelos](https://developers.openai.com/api/docs/guides/model-selection) aconseja experimentar con tareas comparables; no convierte estas rutas locales en rankings demostrados.

## Clases de tarea

| TASK_CLASS | Representa / excluye | Riesgo | Contexto típico | Verificación típica | Inicio orientativo |
|---|---|---|---|---|---|
| READ_ONLY_ANALYSIS | Inspección acotada / edición | bajo | archivos señalados | procedencia y hallazgos | Luna Medium |
| DOCUMENTATION | Documento acotado / cambio funcional | bajo | contrato y docs relacionados | consistencia y diff | Luna Medium |
| MECHANICAL_CHANGE | Cambio repetitivo conocido / diseño nuevo | bajo | patrón y archivos afectados | check focal | Luna Medium |
| BOUNDED_IMPLEMENTATION | Implementación delimitada / varias arquitecturas | medio | módulo, contrato y tests | tests focales | Terra Medium |
| CROSS_LAYER_IMPLEMENTATION | Cambio coordinado entre capas / refactor libre | alto | límites de capas y tests | focal e integrado según riesgo | Terra Medium |
| DIAGNOSTIC_INVESTIGATION | Causa incierta acotada / fix supuesto | medio | logs y rutas concretas | reproducción e hipótesis | Sol Medium |
| ARCHITECTURE_SECURITY | Contratos o seguridad / mantenimiento rutinario | alto | ADR, amenazas, contratos | revisión y checks pertinentes | Sol Medium |
| RELEASE_ACCEPTANCE | Gate o aceptación / desarrollo de feature | alto | candidata y evidencia | gate y aceptación separados | Sol Medium |
| LONG_HORIZON_INVESTIGATION | Exploración dependiente de resultados / tarea pequeña | alto | manifiesto progresivo | checkpoints verificables | Sol Medium |

## Routing y escalado

- **Luna Medium:** documentación acotada, comprobaciones, mecánica y bugs conocidos mínimos.
- **Terra Medium:** implementación cotidiana delimitada e integración moderada con patrón existente; worker inicial mientras la evidencia local lo respalde.
- **Sol Medium:** diagnóstico difícil, varias causas plausibles, arquitectura, integridad o trabajo transversal.
- **Sol High:** excepcional, solo ante límite de razonamiento demostrado.
- **Astra Medium:** auditoría exploratoria amplia o problema muy ambiguo. Requiere autorización explícita por coste; no exige que Sol haya fallado.
- **XHigh, Max:** justificación y autorización explícitas. **Ultra:** solo valorar para trabajo realmente paralelizable y con autorización; nunca escalón automático.

No asumir que más razonamiento mejora el resultado. La guía oficial indica que los valores de esfuerzo disponibles dependen del modelo: [reasoning effort](https://developers.openai.com/api/docs/guides/reasoning).

Antes de escalar, clasificar causa: `MISSING_CONTEXT` → aportar contexto; `ENVIRONMENT`/`DEPENDENCY` → reparar entorno/dependencia; `PERMISSION` → solicitar autorización; `AMBIGUOUS_REQUIREMENT` → aclarar contrato; `SCOPE_TOO_LARGE` → dividir tarea; `TEST_DEFECT` → corregir solo si está demostrado; `WRONG_HYPOTHESIS` → formular otra; `REASONING_LIMIT` → proponer más razonamiento; `MODEL_CAPABILITY_LIMIT` → proponer otro modelo. Un fallo sin causa no justifica escalar.

Primer intento permitido. Un retry exige evidencia o hipótesis nueva; máximo un intento por hipótesis equivalente y dos intentos totales antes de `BLOCKED` o revisión de escalado. No reintentar variaciones equivalentes en bucle.

`NORMAL_TASK` es el modo habitual. `LONG_HORIZON_INVESTIGATION` se reserva para exploración, profiling, flakiness, causa desconocida o auditoría amplia donde el siguiente paso dependa del resultado anterior. Codex Goals puede ayudar, pero no es requisito.

El `EXECUTION_BOUNDARY` de cada tarea aplica privilegio mínimo. No se infieren permisos de un modelo o clase.

## Resource guard (normativo)

Antes de una operación, estimar su alcance cuando sea razonablemente posible.
Si se espera superar cualquiera de estos umbrales, hacer STOP y obtener
autorización humana explícita antes de proceder:

- 20.000 archivos inspeccionados/leídos.
- 5 GB de datos leídos.
- 5 minutos de ejecución estimada.

Son umbrales de autorización (`AUTHORIZATION_GUARD`), no timeouts técnicos:
una orden no se mata automáticamente al superar cinco minutos. Si una operación
supera inesperadamente un umbral, detenerla en la siguiente oportunidad segura
y comunicar `RESOURCE_GUARD_TRIGGERED`. Las operaciones grandes explícitamente
autorizadas con ese alcance pueden ejecutarse.

La regla cubre recorridos recursivos de repositorios/árboles, hashing recursivo,
datasets, entornos virtuales, cachés de dependencias y builds, bases de datos,
backups, artefactos generados y árboles de binarios grandes. Preferir alternativas
acotadas: `git status`, `git diff --name-only`, manifests, lecturas y hashes de
archivos concretos y conjuntos de rutas conocidos.

## Operaciones Git por impacto (normativo)

Clasificar por efecto real, protegiendo trabajo del usuario, historia,
referencias y remotos. Si una operación combina impactos, aplicar todos los
requisitos correspondientes; el nombre del comando no reduce la protección.

| Categoría | Ejemplos | Autorización |
|---|---|---|
| `SAFE_INSPECTION` | `git status`, `git diff`, `git show`, `git log`, `git ls-files`, `git ls-remote` | Normalmente permitida dentro del alcance de la tarea; sin aprobación adicional para inspección ordinaria. |
| `INDEX_OR_WORKTREE_MUTATION` | `git add`, `git restore`, `git stash` | Requiere autorización de la tarea cuando cambia el estado del usuario. |
| `DESTRUCTIVE_OR_LOSS_RISK` | `git reset`, `git clean`, descartar/restaurar cambios del usuario | Requiere autorización humana explícita. |
| `HISTORY_OR_REFERENCE_MUTATION` | commit, amend, rebase, merge, crear/eliminar tags, eliminar branches, manipular refs directamente | Requiere autorización explícita, salvo que el contrato de tarea autorice expresamente la operación exacta. |
| `REMOTE_MUTATION` | push, force push, eliminar branches/tags remotos | Requiere autorización explícita. Force push y mutaciones remotas destructivas requieren autorización específica; un permiso genérico de publicación no basta. |
