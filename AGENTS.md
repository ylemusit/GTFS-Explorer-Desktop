# Instrucciones del proyecto

## Principio de trabajo

Trabaja con el contexto mínimo suficiente para completar la tarea actual.

No analices todo el repositorio por defecto.

Antes de modificar código:

1. Si existe `docs/CURRENT_STATE.md`, léelo.
2. Si no existe, identifica la documentación vigente que actúa como fuente central del proyecto y consulta únicamente la necesaria.
3. Identifica el objetivo concreto solicitado.
4. Localiza únicamente los archivos directamente relacionados.
5. Consulta `docs/ARCHITECTURE.md`, `docs/DECISIONS.md` o `docs/DOMAIN.md` solo si existen y la tarea realmente lo requiere.
6. Amplía el contexto únicamente si existe una razón técnica concreta.

## Una tarea = un objetivo

Cada conversación de Codex debe centrarse en un único resultado principal.

Si durante el trabajo aparece otra funcionalidad, mejora o problema independiente:

- no lo implementes dentro de la tarea actual;
- indícalo como pendiente;
- recomienda tratarlo en un chat nuevo.

No amplíes el alcance de una tarea sin necesidad.

## Implementación

Prefiere el cambio mínimo, coherente y mantenible que resuelva completamente el objetivo.

Conserva:

- arquitectura existente;
- convenciones del proyecto;
- código funcional;
- compatibilidad;
- datos existentes.

Evita:

- refactorizaciones especulativas;
- limpiezas generales no solicitadas;
- cambios cosméticos masivos;
- nuevas dependencias innecesarias;
- modificaciones fuera del alcance.

## Verificación

Antes de considerar terminada una tarea, ejecuta únicamente las comprobaciones relevantes disponibles para el cambio realizado.

Pueden incluir:

- tests;
- lint;
- typecheck;
- build;
- prueba funcional.

No ejecutes validaciones amplias y costosas si existe una comprobación específica suficiente.

Nunca afirmes que algo ha sido probado o verificado si realmente no se ha ejecutado.

## Documentación

Si existe `docs/CURRENT_STATE.md`, úsalo como referencia del estado actual.

Si el proyecto ya dispone de otra fuente central vigente para estado, alcance o decisiones, respétala y actualízala en lugar de crear documentación duplicada.

Actualiza la fuente de estado únicamente cuando una tarea cambie materialmente:

- funcionalidades disponibles;
- trabajo en curso;
- problemas conocidos;
- próximos pasos relevantes.

Actualiza `docs/ARCHITECTURE.md` solo cuando cambie la arquitectura.

Actualiza `docs/DECISIONS.md` solo cuando se tome una decisión técnica o funcional relevante que deba conservarse.

Actualiza `docs/DOMAIN.md` solo cuando cambien conceptos, reglas o terminología del dominio.

No dupliques información entre documentos.

## Finalización

Al terminar una tarea informa de forma compacta:

1. qué se ha cambiado;
2. qué archivos relevantes se han modificado;
3. cómo se ha verificado;
4. qué pendiente o riesgo real permanece, si existe.

Después de completar el objetivo principal, considera la tarea cerrada.