# Guía de usuario

## 1. Qué es GTFS Explorer

GTFS Explorer Desktop es una aplicación local para importar, validar, explorar,
visualizar y exportar feeds GTFS Schedule. Cada proyecto es un workspace local;
el feed no se sube a Internet y la aplicación no usa telemetría.

## 2. Requisitos

La versión actual está preparada para Windows x64. Necesita espacio para el
workspace, los datos importados y, si se usan, los paquetes de mapas offline.
Los feeds grandes pueden tardar un tiempo significativo.

## 3. Crear un proyecto

En la barra de acciones, elige **Nuevo proyecto**, indica el nombre y selecciona
el workspace. El destino inicial es `Documentos/GTFS Explorer/Projects`, pero
puedes elegir otra carpeta. El directorio debe existir y ser escribible.

## 4. Abrir, cerrar y reabrir

Usa **Abrir proyecto** para seleccionar un workspace existente y **Cerrar
proyecto** para dejarlo sin proyecto activo. Después puedes abrirlo de nuevo.
Un workspace solo puede tener un escritor activo; si está en uso, cierra la
otra instancia y vuelve a intentarlo.

## 5. Importar GTFS

Desde **Importar feed**, selecciona un ZIP, una carpeta GTFS o un CSV compatible.
La aplicación prepara la fuente, carga sus filas, normaliza los datos, valida
el feed y finaliza el workspace. La fuente original no se mueve.

## 6. Estado y progreso

La vista muestra la fase actual, el archivo que se está procesando, las filas
cuando existe un contador fiable y el tiempo transcurrido. Algunas fases usan
progreso determinado y otras actividad indeterminada. No se muestra una ETA
porque no sería fiable.

## 7. Resultado de importación y validación

`IMPORT COMPLETED + VALID` significa que la importación terminó y el feed no
tiene incidencias que lo hagan inválido. `IMPORT COMPLETED + INVALID` significa
que terminó técnicamente, pero el feed contiene incidencias formales. **INVALID
no es un fallo técnico**: el feed sigue siendo inspeccionable.

`FAILED` indica un error técnico de la operación. `CANCELLED` indica que la
persona usuaria la canceló. Si se cancela una reimportación, el feed anterior
permanece disponible según el contrato del proyecto.

## 8. Validación

La vista **Validación** permite filtrar y buscar incidencias. Cada fila puede
mostrar categoría (`FATAL`, `ERROR`, `WARNING` o `NOTICE`), archivo, fila física,
campo, regla, entidad y mensaje. Puedes abrir la ayuda local de una regla o ir
a su origen RAW. No hay una puntuación agregada.

## 9. Explorar rutas y horarios

En **Rutas** selecciona ruta, servicio, sentido (`direction_id`) y `trip`. Los
selectores admiten búsqueda por ID o etiqueta. Un `trip` es una ejecución de una
ruta y un `service` determina sus fechas. Los campos `arrival_time` y
`departure_time` conservan la semántica GTFS; horas como `25:30:00` son válidas
y representan tiempo transcurrido del día de servicio.

## 10. RAW

La pestaña **RAW** permite elegir tablas, paginar, ordenar y filtrar los datos
conservados de la fuente. `Fila fuente` significa la línea física del archivo
original, por ejemplo `stops.txt · fila 125`; no es `stop_sequence`, una fila
visible ni un índice SQL. RAW es inspección, no un editor. La vista cargada se
puede copiar o exportar cuando la acción esté disponible.

## 11. Mapas

El mapa separa el overlay local de rutas, shapes y paradas del mapa base:

- **AUTO** prefiere un paquete local con cobertura y usa el proveedor online si
  está disponible fuera de esa cobertura.
- **OFFLINE** bloquea las peticiones externas; sin cobertura muestra el overlay
  sobre un fondo neutro.
- **ONLINE** solicita teselas interactivas del proveedor remoto configurado.

Los tipos de ruta extendidos soportados por GTFS Explorer, como `route_type 715`,
se reconocen sin cambiar su ID.

## 12. Mapas offline

En Ajustes, **Mapas offline** muestra la biblioteca global, cobertura, estado y
fuente. Puedes importar un paquete y eliminarlo con confirmación. Un PMTiles
válido no siempre es un mapa base renderizable: un vector sin perfil de estilo
queda como **Sin estilo compatible**. No hay catálogo público automático ni
descarga masiva de teselas interactivas.

## 13. Exportaciones

El asistente ofrece JSON, CSV, GeoJSON, Mini-GTFS, GTFS completo modificado,
nueva versión GTFS y KML/KMZ. JSON es un bundle derivado; GeoJSON contiene
geometrías y paradas con coordenadas válidas; CSV ofrece la salida tabular de la
selección. El modo `faithful` conserva los valores de origen y
`spreadsheet-safe` neutraliza fórmulas para hojas de cálculo; no son
equivalentes byte a byte. KML y KMZ no son formatos disponibles en la línea
estable anterior; en 0.2.0 son salidas geoespaciales locales con perfiles para Google
Earth y Google My Maps.

Las salidas GTFS 0.2.0 parten únicamente de una WorkingRevision confirmada.
El editor visual conserva `ORIGINAL_GTFS` inmutable, registra comandos
reversibles y obliga a resolver dependencias antes de borrar o reasignar datos.
La edición de paradas, shapes, horarios, servicios, agencias y atribuciones se
mantiene en un borrador que puede guardar, reabrir, deshacer, rehacer,
confirmar o descartar. Importar KML/KMZ solo propone geometría existente y
rechaza recursos externos, entidades XML y contenedores inseguros.

Mini-GTFS es un subconjunto autocontenido con las dependencias necesarias,
reimportable y validado localmente antes de publicarse. Conserva IDs, horas
superiores a 24 y tipos de ruta extendidos según la selección; no es una
certificación del feed oficial del proveedor.

Los nombres propuestos son seguros y predecibles, por ejemplo
`gtfs-export-route-R1-geojson.geojson`. Puedes elegir otro destino y el asistente
no sobrescribe un archivo existente sin confirmación.

## 14. Historial

El historial registra operaciones de importación y exportación con sus estados.
`INTERRUPTED` significa que una operación quedó iniciada pero no alcanzó un
estado terminal debido a una interrupción.

## 15. Cancelación

Usa **Cancelar** durante una operación. La interfaz muestra `Cancelando…` hasta
que termina la limpieza. Una cancelación no se presenta como `FAILED`.

## 16. Directorios

Los destinos iniciales son `Projects`, `Imports`, `Exports`, `Maps` y
`Diagnostics` dentro de `Documentos/GTFS Explorer`. `recovery` está dentro del
workspace. Son valores predeterminados, no ubicaciones obligatorias. La
biblioteca gestionada de mapas tiene una ubicación local específica. La fuente
original no se mueve silenciosamente.

## 17. Recovery

Al abrir un workspace, GTFS Explorer puede detectar un descriptor recuperable,
una copia de seguridad recuperable o un proyecto que no puede recuperarse
automáticamente. Solo ofrece restaurar candidatos validados y conserva un
snapshot antes de reemplazar un archivo. Nunca sobrescribe una base dañada con
una reparación especulativa. Si no hay candidato válido, conserva el original y
requiere una decisión manual.

## 18. Diagnósticos

Ante un error, usa la acción de diagnóstico si está disponible. Puedes revisar
la previsualización antes de exportar el ZIP. El diagnóstico se sanea según el
contrato local y no se envía automáticamente.

## 19. Accesibilidad y teclado

Puedes recorrer la interfaz con `Tab` y `Mayús+Tab`, activar controles con
`Enter`, cerrar diálogos con `Escape` y usar las flechas en selectores y tablas.
Los selectores buscables, las tablas y los estados tienen nombres o texto
accesible. La revisión manual con lectores de pantalla sigue pendiente; no se
declara certificación NVDA, JAWS o Narrator.

Atajos disponibles: Nuevo, Abrir y Cerrar usan los atajos estándar del sistema;
`Ctrl+I` importa, `Ctrl+W` cierra, `Ctrl+,` abre Ajustes, `Esc` cancela cuando
corresponde y `F1` abre esta ayuda local. La ayuda funciona sin proyecto y sin
conexión.

## 20. Privacidad y limitaciones conocidas

La aplicación es local-first: no sube feeds, no usa cuentas, analytics ni
telemetría. En `OFFLINE` no se realizan peticiones externas. En `ONLINE`, el
proveedor puede recibir la IP/conexión, las coordenadas de tesela `z/x/y`, la
zona aproximada visible y headers normales. No recibe `route_id`, `trip_id`,
`stop_id`, shapes GTFS, nombres del feed, workspace ni historial.

Problemas habituales: un proyecto en uso requiere cerrar la otra instancia;
un feed `INVALID` puede inspeccionarse y debe corregirse en su fuente; un mapa
offline sin cobertura usa fondo neutro; un PMTiles sin estilo no se selecciona;
un mapa online no disponible deja el overlay local; y un recovery requiere
seguir la opción validada que ofrezca la aplicación.

La revisión visual con lectores de pantalla nativos y la aceptación visual
manual de Windows siguen siendo gates separados del smoke técnico; no se
declaran certificados por este manual.

## Ayuda local y distribución

La ayuda integrada se incluye como recurso local buscable y se abre desde
**Ayuda** o `F1`, sin depender de Internet. El inventario que P1-32 debe incluir
en portable e instalador está en [`HELP_PACKAGING_MANIFEST.json`](HELP_PACKAGING_MANIFEST.json).

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.
