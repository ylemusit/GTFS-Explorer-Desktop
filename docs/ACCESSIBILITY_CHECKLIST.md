# Checklist de accesibilidad de interfaz

Estado: T081 (2026-08-13). La interfaz inicial está en castellano; el catálogo
`resources/i18n/es.json` permite añadir otros idiomas sin alterar las vistas.

- [x] El flujo principal tiene acciones de teclado: `Ctrl+O` abre proyecto,
  `Ctrl+I` importa, `Ctrl+W` cierra, `Ctrl+,` abre ajustes y `F1` ayuda.
- [x] Los selectores, tablas, detalles, exportación y navegación tienen nombre
  accesible; los controles de acción añaden una descripción cuando aporta contexto.
- [x] El foco sigue el orden visual: navegación, contenido y controles de cada vista.
- [x] Los estados se expresan con texto, no solo con color o iconos; IDs y valores
  de tablas permanecen seleccionables y copiables.
- [x] Los colores de mapa usan fondo neutro, texto blanco sobre agrupaciones azules y
  borde oscuro en paradas; no transmiten el estado sin texto equivalente en la UI Qt.
- [x] Se prueba que no falten claves del catálogo y se dispone de pseudo-localización
  (`pseudo_localize`) para revisión manual de textos largos.

Revisión manual antes de release: recorrer con Tab/Mayús+Tab y lector de pantalla
en Windows, comprobar foco visible del tema Qt final y ejecutar una sesión con
pseudo-localización para detectar desbordes.
