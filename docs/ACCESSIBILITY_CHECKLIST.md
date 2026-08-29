# Checklist de accesibilidad de interfaz

Estado: P1-29 (2026-08-27). La interfaz inicial está en castellano; el catálogo
`resources/i18n/es.json` permite añadir otros idiomas sin alterar las vistas.

- [x] El flujo principal tiene acciones de teclado: `Ctrl+O` abre proyecto,
  `Ctrl+I` importa, `Ctrl+W` cierra, `Ctrl+,` abre ajustes y `F1` abre la ayuda
  local existente.
- [x] Los selectores, tablas, detalles, exportación y navegación tienen nombre
  accesible; los controles de acción añaden una descripción cuando aporta contexto.
- [x] El foco sigue el orden visual: navegación, contenido y controles de cada vista.
- [x] Los estados se expresan con texto, no solo con color o iconos; IDs y valores
  de tablas permanecen seleccionables y copiables.
- [x] Los colores de mapa usan fondo neutro, texto blanco sobre agrupaciones azules y
  borde oscuro en paradas; no transmiten el estado sin texto equivalente en la UI Qt.
- [x] Se prueba que no falten claves del catálogo y se dispone de pseudo-localización
  (`pseudo_localize`) para revisión manual de textos largos.

P1-29 auditó MainWindow, navegación, proyecto/resumen, importación y progreso,
RAW, exploración relacional, validación, exportación, mapas y gestor offline,
historial, recovery y diálogos propios. Se conservaron los controles estándar de
Qt para flechas, Enter, Escape, completer, tablas y paginación; se añadieron
labels/buddies donde faltaban y metadata accesible en controles compactos.

Limitaciones conocidas: la accesibilidad cartográfica avanzada del lienzo
MapLibre/WebGL y la prueba manual con lector de pantalla quedan en BACKLOG.
P1-29 no certifica compatibilidad con NVDA, JAWS o Narrator ni rehace el tema
visual.

Revisión manual antes de release: recorrer con Tab/Mayús+Tab y lector de pantalla
en Windows, comprobar foco visible del tema Qt final y ejecutar una sesión con
pseudo-localización para detectar desbordes.
