# GTFS Explorer Desktop — análisis y plan maestro de construcción

Versión del documento: 1.0

Fecha: 11/08/2026

Estado: Aprobado como línea base técnica; implementación no iniciada

Propietario y autor del producto: Yeison Arbey Carrillo Lemus
Todos los derechos reservados.

## 0. Cómo usar este documento

Este documento es la especificación ejecutable inicial de GTFS Explorer Desktop. Su objetivo es que una persona o un modelo de IA de razonamiento bajo pueda construir el producto por tareas pequeñas, verificables y sin reconstruir el alcance desde conversaciones antiguas.

Orden de autoridad durante la implementación:

1. Código y pruebas existentes.
2. `AGENTS.md`.
3. `docs/CURRENT_STATE.md`.
4. Este plan maestro y la tarea concreta que se esté ejecutando.
5. `docs/ARCHITECTURE.md`, `docs/DECISIONS.md` y `docs/DOMAIN.md`.
6. El chat de origen, solo como contexto histórico.

Reglas obligatorias para el agente ejecutor:

- Ejecutar una sola tarea `Txxx` por chat, salvo que Yeison autorice expresamente otra cosa.
- No empezar una tarea si sus dependencias no están terminadas.
- No inventar archivos, campos GTFS, contratos, versiones ni resultados de pruebas.
- No avanzar a UI, mapas, simulación o Realtime antes de superar sus puertas de entrada.
- Aplicar el cambio mínimo que complete la tarea.
- Ejecutar las pruebas indicadas en la ficha de la tarea.
- Ejecutar siempre `git diff --check` y `git status --short` si el repositorio usa Git.
- No declarar una tarea terminada si queda un criterio de aceptación sin demostrar.
- Si surge una decisión que modifica un contrato público, seguridad, licencia, coste o persistencia, detenerse y pedir decisión a Yeison.
- No introducir secretos ni enviar feeds del usuario a servicios externos.
- Actualizar `docs/CURRENT_STATE.md` solo cuando cambie materialmente el estado del producto.

Plantilla de inicio para cada chat de implementación:

```text
Objetivo único: ejecutar la tarea Txxx de docs/PLAN_MAESTRO_CONSTRUCCION.md.
Lee AGENTS.md, docs/CURRENT_STATE.md y únicamente la ficha Txxx y sus dependencias.
No amplíes el alcance. No empieces otra tarea.
Antes de modificar, confirma qué archivos están directamente relacionados.
Al terminar informa: cambio, archivos, pruebas ejecutadas y riesgo real pendiente.
```

## 1. Conclusión ejecutiva

GTFS Explorer Desktop es técnicamente viable como aplicación Windows portable, local y sin servidores. Puede construirse con coste obligatorio de licencias e infraestructura de **0 €** usando software de código abierto y datos cartográficos autorizados. Eso no significa coste total cero: el desarrollo, las pruebas, el mantenimiento, el almacenamiento, el ancho de banda y la revisión de licencias consumen tiempo y recursos.

El repositorio analizado no contiene todavía aplicación, pruebas ni el ZIP de demostración citado en el chat. Contiene documentación plantilla y una conversación de definición. Por tanto, a 11/08/2026 el proyecto se encuentra en fase de arquitectura y planificación, no en fase de implementación.

La visión completa es demasiado grande para un único MVP. La división profesional queda así:

- **MVP técnico:** núcleo de GTFS Schedule, importación segura, DuckDB, consultas, validación interna y exportaciones sin UI compleja.
- **MVP de producto:** aplicación Windows con resumen, tablas, rutas, viajes, paradas, horarios, validador y exportación; mapa de shapes y paradas con fondo vacío.
- **v1.0:** producto portable estable, mapas PMTiles opcionales, Mini-GTFS coherente, manual, instalador, rendimiento y pruebas en Windows limpio.
- **Después de v1.0:** simulador y GTFS Realtime. Son productos evolutivos, no requisitos encubiertos del primer lanzamiento.

Las correcciones más importantes respecto al chat inicial son:

1. GTFS Schedule no es “cualquier extensión”. El formato oficial usa principalmente archivos `.txt` delimitados dentro de ZIP y también contempla actualmente `locations.geojson`. Los `.csv` se admitirán como importación compatible, no como GTFS oficial.
2. GTFS Realtime (`.pb`) es un estándar y flujo separado. No debe mezclarse con el importador Schedule.
3. No se asignará una nota como “94/100” sin un sistema de ponderación validado. Se mostrarán errores, advertencias y avisos trazables.
4. No se distribuirán teselas de `tile.openstreetmap.org` para uso offline. Se usarán paquetes PMTiles obtenidos o generados con licencia compatible.
5. No se cargará todo el feed en Pandas. DuckDB será la fuente de consulta y la UI paginará.
6. No se prometerá Mini-GTFS para extensiones desconocidas: se exportará únicamente cuando pueda demostrarse el cierre de dependencias.

## 2. Definición del producto

### 2.1 Propuesta de valor

GTFS Explorer Desktop es una aplicación Windows offline-first para importar, inspeccionar, validar, relacionar, visualizar y transformar feeds GTFS Schedule sin exigir Python, SQL, navegador externo ni conexión a Internet al usuario final.

Debe resolver cinco trabajos:

1. Entender rápidamente qué contiene un feed.
2. Recorrer las relaciones ruta → viaje → horario → parada → geometría → servicio.
3. Encontrar problemas estructurales, referenciales, temporales y geográficos.
4. Extraer información reutilizable como JSON, GeoJSON, CSV o Mini-GTFS.
5. Servir de herramienta de ingeniería y aprendizaje, no de planificador de viajes para pasajeros.

### 2.2 Usuarios objetivo

- Desarrolladores e integradores de transporte.
- Analistas de datos y personal GIS.
- Operadores o técnicos que revisan feeds.
- Estudiantes y usuarios que necesitan comprender GTFS.

No se asume todavía un comprador, cliente u organización usuaria confirmada. Antes de convertir el proyecto en producto comercial se deben validar problema, frecuencia de uso, alternativas, comprador y disposición a pagar.

### 2.3 Caso de uso central de v1.0

1. El usuario ejecuta `GTFSExplorer.exe`.
2. Abre un ZIP GTFS o una carpeta extraída.
3. La aplicación hace inventario y comprobaciones de seguridad.
4. Importa a un espacio de trabajo aislado.
5. Conserva los valores originales y crea una representación tipada.
6. Muestra resumen, entidades, relaciones y problemas.
7. Permite filtrar ruta, servicio, sentido y viaje.
8. Dibuja shapes y paradas; el mapa base es opcional.
9. Exporta una selección en formatos explícitos.
10. No modifica el feed de entrada.

### 2.4 Fuera de alcance de v1.0

- Edición del feed original.
- Planificación de viajes y cálculo de transbordos.
- AVL, despacho, conducción o navegación GPS.
- Cuentas, nube, telemetría o colaboración multiusuario.
- Descarga automática de feeds de terceros.
- GTFS Realtime, aunque se preservarán puntos de extensión.
- Simulación operacional, salvo el contrato de diseño futuro.
- Soporte Linux/macOS.
- Publicación en Microsoft Store.
- Inferir datos que no estén en el feed, como límites de velocidad.

## 3. Alcance por entregas y puertas de calidad

| Entrega | Contenido verificable | Puerta de salida |
|---|---|---|
| M0 | Repositorio, herramientas, fixtures, contratos y seguridad básica | Tests y calidad ejecutables localmente |
| M1 Núcleo | Importación Schedule, esquema DuckDB, consultas y validador interno | Feed válido y feeds defectuosos importados/rechazados de forma determinista |
| M2 Exportación | JSON, GeoJSON, CSV y subconjunto core | Salidas reproducibles, atómicas y reimportables cuando corresponda |
| M3 Desktop | Shell, apertura, progreso, resumen, tablas y exploradores | Flujo end-to-end sin consola ni dependencias externas |
| M4 Mapas | MapLibre local, bridge, shapes, paradas y PMTiles opcional | Spike técnico y pruebas de rendimiento superados |
| M5 v1.0 | Ayuda, portable, instalador, licencias, VM limpia y benchmarks | Checklist de release completo y artefactos con hashes |
| M6 futura | Simulador | Motor temporal independiente probado |
| M7 futura | GTFS Realtime | Vinculación Schedule/Realtime definida y probada |

No se permite iniciar M3 hasta que M1 y los contratos de consulta estén estables. No se permite iniciar M4 hasta completar `T070`, el spike vinculante del mapa.

## 4. Requisitos funcionales

### 4.1 Entrada e importación

- **RF-001:** abrir un `.zip` GTFS Schedule.
- **RF-002:** abrir una carpeta con archivos oficiales extraídos.
- **RF-003:** admitir archivos `.csv` equivalentes solo en modo compatibilidad y mostrar que la entrada no es un paquete GTFS oficial.
- **RF-004:** inventariar nombres, tamaños, hashes, columnas, codificación y número de filas.
- **RF-005:** no modificar nunca la entrada.
- **RF-006:** admitir UTF-8 y UTF-8 con BOM en modo oficial; otras codificaciones requieren modo compatibilidad y elección explícita.
- **RF-007:** preservar valores y columnas desconocidas en staging.
- **RF-008:** permitir cancelar una importación sin dejar un proyecto utilizable a medias.
- **RF-009:** detectar duplicados de nombre ignorando mayúsculas/minúsculas, rutas anidadas, path traversal, enlaces y bombas ZIP.
- **RF-010:** identificar la versión del importador y la revisión de la especificación usada.

### 4.2 Exploración y relaciones

- **RF-020:** resumen de agencias, rutas, paradas, viajes, stop times, servicios, shapes, periodo y archivos.
- **RF-021:** tablas paginadas y ordenables con filtros parametrizados.
- **RF-022:** exploración encadenada de ruta, servicio, `direction_id` y viaje.
- **RF-023:** inspector de parada con rutas, viajes, servicios y secuencias relacionadas.
- **RF-024:** matriz de horarios generada bajo demanda.
- **RF-025:** interpretación de horas mayores o iguales a `24:00:00` como segundos desde el inicio del día de servicio.
- **RF-026:** vista técnica del archivo original y vista humana del modelo normalizado.
- **RF-027:** copiar valores y exportar el resultado filtrado.
- **RF-028:** mostrar nombre e ID; no ocultar los IDs técnicos.

### 4.3 Geometría y mapa

- **RF-030:** dibujar shapes como líneas y paradas como puntos en WGS84.
- **RF-031:** funcionar sin mapa base.
- **RF-032:** aceptar un paquete PMTiles local validado.
- **RF-033:** ajustar extensión y activar/desactivar capas.
- **RF-034:** mostrar propiedades de parada y shape.
- **RF-035:** calcular distancia parada-shape únicamente cuando exista una asociación inequívoca entre viaje, shape y parada.
- **RF-036:** simplificar y cargar geometría según extensión/zoom para feeds grandes.

### 4.4 Validación

- **RF-040:** emitir problemas con código estable, severidad, archivo, fila, campo, entidad, mensaje y ayuda.
- **RF-041:** validar estructura, cabeceras, tipos, dominios, referencias, horarios, secuencias, calendarios y coordenadas.
- **RF-042:** separar reglas de especificación, buenas prácticas y reglas propias.
- **RF-043:** filtrar y exportar el informe.
- **RF-044:** navegar desde un problema a la fila o entidad afectada.
- **RF-045:** poder ejecutar opcionalmente MobilityData GTFS Validator y conservar su informe sin confundirlo con el validador interno.

### 4.5 Exportación

- **RF-050:** JSON semántico normalizado y versionado.
- **RF-051:** GeoJSON RFC 7946 con coordenadas `[longitud, latitud]`.
- **RF-052:** CSV fiel y, como opción distinta, CSV protegido para hojas de cálculo.
- **RF-053:** exportación de rutas, viajes, paradas, shapes y resultados filtrados.
- **RF-054:** Mini-GTFS solo para selecciones y archivos cuyas dependencias estén implementadas.
- **RF-055:** escribir en temporal, validar y renombrar atómicamente al destino.
- **RF-056:** generar manifiesto con selección, fecha, versión, hashes, archivos incluidos/excluidos y advertencias.

### 4.6 Aplicación y ayuda

- **RF-060:** arrastrar y soltar, selector de archivo y elementos recientes sin guardar datos del feed.
- **RF-061:** operaciones largas en segundo plano con progreso y cancelación.
- **RF-062:** manual offline, buscable y ayuda contextual.
- **RF-063:** interfaz inicial en español y textos preparados para i18n.
- **RF-064:** modo portable y modo instalado.
- **RF-065:** recuperación segura tras cierre inesperado.

## 5. Requisitos no funcionales

- **RNF-001 Compatibilidad:** Windows 10/11 de 64 bits. La versión mínima exacta se fija en `T001` tras comprobar Qt y WebEngine.
- **RNF-002 Offline:** importación, consulta, validación interna, exportación, ayuda y mapas sin base funcionarán sin red.
- **RNF-003 Privacidad:** sin telemetría, cuentas ni subida automática de feeds.
- **RNF-004 Integridad:** entrada de solo lectura; salidas atómicas; esquema con migraciones.
- **RNF-005 Rendimiento:** UI nunca bloqueada más de 200 ms por trabajo evitable; tablas paginadas; consultas cancelables.
- **RNF-006 Escala:** objetivo inicial probado de 5 millones de `stop_times`, 100.000 viajes, 50.000 paradas y 2 GB comprimidos en un equipo de referencia.
- **RNF-007 Equipo de referencia:** 4 núcleos, 8 GB RAM, SSD y Windows 10/11 x64.
- **RNF-008 Memoria:** límite configurable de DuckDB; valor inicial 50 % de RAM y máximo de temporales configurable.
- **RNF-009 Seguridad:** extracción confinada, SQL parametrizado, HTML escapado, CSP estricta y sin ejecución de contenido del feed.
- **RNF-010 Observabilidad:** logs rotatorios locales sin filas, nombres de persona, coordenadas masivas ni rutas completas por defecto.
- **RNF-011 Accesibilidad:** navegación por teclado, foco visible, contraste y textos no dependientes solo del color.
- **RNF-012 Reproducibilidad:** dependencias bloqueadas, esquema y exportaciones versionados, builds con hashes.
- **RNF-013 Portabilidad:** ningún path absoluto del equipo de build dentro del artefacto.
- **RNF-014 Mantenibilidad:** cobertura de los contratos críticos y capas sin importaciones desde dominio hacia UI/infraestructura.

Los límites de RNF-006 son objetivos de aceptación, no hechos demostrados. `T095` debe medirlos y ajustar cifras documentadas.

## 6. Arquitectura definitiva

```text
PySide6 / Qt Widgets
        |
        v
Servicios de aplicación ---- QWebChannel ---- MapLibre local
        |                                      |
        v                                      v
Dominio y contratos                  app:// + PMTiles local
        |
        v
Repositorios / consultas / validadores / exportadores
        |
        v
DuckDB del proyecto + staging + caché controlada
        ^
        |
Importador seguro <- ZIP / directorio / CSV compatible
```

### 6.1 Capas

1. **Dominio:** identificadores, tiempos de servicio, selecciones, resultados, problemas y contratos. No conoce Qt, DuckDB ni archivos físicos.
2. **Aplicación:** casos de uso, transacciones, progreso, cancelación y autorización de operaciones locales.
3. **Infraestructura:** ZIP, CSV, DuckDB, geometría, exportadores, logs y sistema de archivos.
4. **Presentación:** Qt Widgets, modelos paginados, diálogos y bridge del mapa.
5. **Recursos web:** MapLibre, PMTiles JS, estilos, sprites, fuentes y CSP, todos bloqueados por versión.

### 6.2 Reglas de dependencia

- `domain` no importa `application`, `infrastructure` ni `presentation`.
- `application` depende de interfaces del dominio, no de widgets.
- `infrastructure` implementa puertos; no muestra diálogos.
- `presentation` llama casos de uso; no ejecuta SQL.
- El JavaScript del mapa no accede directamente a DuckDB ni al sistema de archivos.
- No se introduce un ORM: añade complejidad y no resuelve el carácter analítico del dominio.

### 6.3 Árbol objetivo

```text
GTFS Explorer Desktop/
├── AGENTS.md
├── pyproject.toml
├── uv.lock
├── README.md
├── LICENSES/
├── docs/
├── src/gtfs_explorer/
│   ├── __main__.py
│   ├── domain/
│   │   ├── entities.py
│   │   ├── selections.py
│   │   ├── service_time.py
│   │   ├── validation.py
│   │   └── ports.py
│   ├── application/
│   │   ├── commands/
│   │   ├── queries/
│   │   ├── jobs/
│   │   └── settings.py
│   ├── infrastructure/
│   │   ├── importing/
│   │   ├── duckdb/
│   │   │   ├── migrations/
│   │   │   └── repositories/
│   │   ├── validation/
│   │   ├── geometry/
│   │   ├── exporting/
│   │   └── filesystem/
│   ├── presentation/
│   │   ├── desktop/
│   │   ├── models/
│   │   └── map_bridge/
│   └── resources/
│       ├── map_web/
│       ├── help/
│       └── i18n/
├── schemas/
│   ├── gtfs_schedule/
│   ├── json_export/
│   └── project/
├── tests/
│   ├── unit/
│   ├── contract/
│   ├── integration/
│   ├── ui/
│   ├── packaging/
│   └── fixtures/
├── tools/
├── packaging/
│   ├── portable/
│   └── nsis/
└── web/map/
    ├── package.json
    ├── package-lock.json
    └── src/
```

## 7. Stack técnico decidido

| Área | Decisión | Motivo | Alternativa descartada inicialmente |
|---|---|---|---|
| Lenguaje | Python 3.12 x64, versión exacta bloqueada | Ecosistema y compatibilidad conservadora | 3.13/3.14 hasta comprobar todas las ruedas |
| Escritorio | PySide6 + Qt Widgets | UI nativa, oficial y empaquetable | Streamlit por navegador/servidor y peor portabilidad |
| Mapa | Qt WebEngine + MapLibre GL JS | Capas dinámicas, WebGL, PMTiles | Folium para producto final |
| Datos | DuckDB persistente por proyecto | Analítica embebida, CSV y grandes tablas | SQLite como motor principal |
| Dataframes | Ninguno obligatorio | DuckDB y lotes Python bastan al inicio | Pandas/Polars hasta que un perfil justifique uno |
| Geometría | Shapely | Distancias, líneas y operaciones GIS | GeoPandas por peso y alcance innecesario |
| Modelos | `dataclasses` y tipos Python | Contratos pequeños y explícitos | Pydantic sin necesidad demostrada |
| Dependencias | `pyproject.toml` + `uv.lock` | Entorno reproducible y rápido | `requirements.txt` sin bloqueo transitivo |
| Tests | pytest | Ecosistema estándar | Framework propio |
| Calidad | Ruff + mypy | Lint/formato/tipos | Varias herramientas solapadas |
| Build | `pyside6-deploy`/Nuitka, modo `standalone` | Recomendación oficial y carpeta portable inspeccionable | `onefile` por arranque, temporales y depuración |
| Instalador | NSIS | Gratuito incluso para uso comercial | Inno Setup como dependencia base por política comercial actual |
| Validador formal | Adaptador a MobilityData CLI | Canónico y salida JSON/HTML | Reimplementar todo el estándar |

La versión exacta de cada dependencia se decide y prueba en `T001`; después queda bloqueada. No se debe actualizar una dependencia durante otra tarea funcional.

## 8. Cobertura GTFS y modelo de compatibilidad

### 8.1 Línea base de especificación

La fuente normativa es la referencia oficial GTFS Schedule. El registro de esquema guardará una revisión fechada, inicialmente la vigente al ejecutar `T014`. No se codificará la especificación únicamente en condicionales Python: cada archivo y campo tendrá metadatos versionados.

Grupos que el inventario debe reconocer:

- Core: `agency.txt`, `stops.txt`, `routes.txt`, `trips.txt`, `stop_times.txt`, `calendar.txt`, `calendar_dates.txt`.
- Geometría/operación: `shapes.txt`, `frequencies.txt`, `transfers.txt`.
- Estaciones: `pathways.txt`, `levels.txt`.
- Metadatos/i18n: `translations.txt`, `feed_info.txt`, `attributions.txt`.
- Tarifas heredadas: `fare_attributes.txt`, `fare_rules.txt`.
- Fares v2: `timeframes.txt`, `rider_categories.txt`, `fare_media.txt`, `fare_products.txt`, `fare_leg_rules.txt`, `fare_leg_join_rules.txt`, `fare_transfer_rules.txt`.
- Áreas/redes: `areas.txt`, `stop_areas.txt`, `networks.txt`, `route_networks.txt`.
- Ubicaciones flexibles: `location_groups.txt`, `location_group_stops.txt`, `locations.geojson`.
- Reserva: `booking_rules.txt`.

La lista debe confirmarse contra la referencia oficial durante `T014`; si cambia, se registra una decisión y una migración de esquema. “Reconocer” no significa disponer desde el primer MVP de una pantalla semántica específica: todos los archivos conocidos se inventariarían y preservarían, el core se tipa primero y los opcionales se incorporan por tareas explícitas.

### 8.1.1 Cobertura implementada

| Archivos | Estado | Representación actual |
|---|---|---|
| Core | Tipado (T016) | Tablas `gtfs_*`, lexemas de fecha/hora y problemas de conversión. |
| `shapes.txt` | Tipado (T017) | Puntos, coordenadas, secuencia y distancia en `gtfs_shapes`. |
| `frequencies.txt`, `transfers.txt` | Tipado (T017) | Horas de servicio, headway y todos los campos de transferencia sin inferir reglas condicionales. |
| `feed_info.txt`, `attributions.txt` | Tipado (T017) | Metadatos y atribuciones visibles en tablas dedicadas. |
| Resto de archivos reconocidos | Staging/inventario | Sin interpretación adicional hasta su tarea explícita. |

### 8.2 Modos de entrada

| Modo | Entrada | Semántica |
|---|---|---|
| Estricto | ZIP raíz o carpeta con nombres oficiales `.txt`/`locations.geojson` | Puede declararse GTFS Schedule |
| Compatible | `.csv`, delimitador/codificación no oficial o archivo parcial | Nunca se declara feed GTFS válido sin completar y validar |
| Proyecto | Espacio de trabajo ya importado | Reabre por versión de esquema y hash |
| Realtime futuro | Protobuf `.pb` | Flujo separado después de v1.0 |

Reglas:

- Un `routes.csv` compatible se normaliza como origen externo, no se renombra silenciosamente a oficial.
- Un archivo individual puede explorarse en modo parcial, pero no habilita Mini-GTFS.
- Los archivos desconocidos aparecen en inventario y se conservan opcionalmente; no participan en relaciones ni subconjuntos sin un adaptador.
- Los nombres se comparan sin distinguir mayúsculas en Windows, pero se conserva la grafía original.

## 9. Modelo de datos interno

### 9.1 Principio de doble representación

Cada importación mantiene:

1. **Manifiesto de origen:** huella, tamaños, nombres, columnas y estado.
2. **Staging fiel:** valores como texto, número de fila, columnas extra y lexema original.
3. **Modelo tipado:** columnas adecuadas para consulta y reglas.
4. **Resultados derivados:** calendarios, geometrías, métricas y problemas regenerables.

No se corrige el dato del usuario durante la importación. Una conversión fallida produce `NULL` en la columna tipada más un problema referenciado; el staging sigue disponible.

### 9.2 Convenciones

- Todos los IDs GTFS son `VARCHAR` y se comparan de forma binaria.
- Cadena vacía y ausencia se distinguen durante parsing; la normalización aplica la regla del campo.
- Fechas GTFS se guardan como `DATE` y se conserva el texto fuente.
- Horas se guardan como `service_seconds INTEGER` más el texto `HH:MM:SS`; no se usan tipos `TIME` porque GTFS permite valores superiores a 24 horas.
- Latitud/longitud se guardan como `DOUBLE` y se validan antes de geometría.
- Enumeraciones se tipan como entero pequeño más validación de dominio.
- `direction_id` conserva 0/1 y nunca se etiqueta automáticamente como ida/vuelta.
- Coordenadas GeoJSON siempre se emiten `[lon, lat]`.
- Métricas de distancia se calculan en una proyección local apropiada o con cálculo geodésico, nunca en grados.

### 9.3 Tablas de control

```text
schema_migrations(version, applied_at)
projects(project_id, name, status, created_at, updated_at, schema_version)
feeds(feed_id, project_id, source_name, source_sha256, import_mode,
      spec_revision, importer_version, imported_at, status)
source_files(file_id, feed_id, original_name, canonical_name, media_type,
             size_bytes, sha256, row_count, encoding, delimiter, status)
source_columns(file_id, ordinal, original_name, canonical_name, known, required)
import_jobs(job_id, feed_id, state, started_at, finished_at, progress, error_code)
validation_issues(issue_id, feed_id, validator, rule_code, severity, category,
                  file_name, row_number, field_name, entity_type, entity_id,
                  message_key, details_json, created_at)
export_jobs(export_id, feed_id, selection_json, format, schema_version,
            status, output_sha256, created_at)
```

El esquema normalizado usa prefijo `gtfs_` y el staging `stg_`. Las vistas de consulta usan `v_`. Las tablas derivadas usan `drv_`. Cada migración es incremental, inmutable y probada desde una base vacía y desde la versión anterior.

### 9.4 Índices y materializaciones

No se crearán índices masivos por costumbre. Primero se miden consultas. Candidatos iniciales:

- `gtfs_trips(route_id, service_id, direction_id)`.
- `gtfs_stop_times(trip_id, stop_sequence)`.
- `gtfs_stop_times(stop_id)`.
- `gtfs_shapes(shape_id, shape_pt_sequence)`.

Las matrices de horario y GeoJSON de vista se generan bajo demanda y se cachean con clave compuesta por `feed_hash + query_version + selection + options`.

## 10. Pipeline de importación

```text
Seleccionar entrada
  -> identificar modo
  -> preflight de tamaño/espacio
  -> inventario seguro
  -> hash
  -> extracción confinada si procede
  -> verificar nombres y encoding
  -> crear proyecto IMPORTING
  -> cargar staging por lotes
  -> normalizar core
  -> validar
  -> crear derivados mínimos
  -> commit y estado READY
  -> limpiar temporales
```

### 10.1 Límites iniciales configurables

- Tamaño ZIP comprimido: 2 GiB.
- Total descomprimido: 20 GiB.
- Una entrada: 10 GiB.
- Número de entradas: 256.
- Ratio total de compresión: 200:1.
- Profundidad de directorio en modo estricto: 0.
- Memoria DuckDB: 50 % de RAM.
- Temporales DuckDB: máximo configurable, valor inicial 50 % del espacio libre al iniciar, con tope documentado por el usuario.

Estos valores son defensas iniciales y deben someterse a fixtures legítimos grandes. Superarlos no debe provocar un bypass: la UI ofrece cancelar o cambiar límites en configuración avanzada, dejando registro local de la decisión.

### 10.2 Seguridad del ZIP

- Rechazar rutas absolutas, `..`, ADS de NTFS, nombres reservados y entradas que escapen del directorio resuelto.
- Rechazar enlaces simbólicos y tipos especiales.
- Detectar colisiones tras normalización Unicode y comparación case-insensitive.
- Comprobar espacio libre antes y durante la extracción.
- Extraer a un directorio aleatorio dentro del workspace.
- No abrir HTML, scripts, ejecutables ni fórmulas contenidos en el feed.
- Borrar temporales incompletos al cancelar o al recuperar la siguiente ejecución.

### 10.3 CSV/GTFS

En modo estricto se usan las reglas oficiales: UTF-8, coma, cabecera y quoting CSV. No se deja al sniffer cambiar silenciosamente el contrato. En modo compatible se muestra y confirma codificación/delimitador detectados. Los IDs y horas entran primero como texto; `ignore_errors` no se activa por defecto porque perder filas silenciosamente destruiría trazabilidad.

## 11. Servicios de consulta

Todos devuelven DTOs paginados o iteradores; nunca widgets ni relaciones DuckDB sin materializar.

```text
FeedSummaryQuery(feed_id)
RawTableQuery(feed_id, file, filters, sort, page_token, page_size)
RoutesQuery(feed_id, filters)
RouteContextQuery(feed_id, route_id)
TripsQuery(feed_id, route_id, service_id?, direction_id?)
TripTimelineQuery(feed_id, trip_id)
StopContextQuery(feed_id, stop_id, service_date?)
TimetableMatrixQuery(feed_id, route_id, service_ids, direction_id, limit)
ShapeQuery(feed_id, shape_id, tolerance?, bbox?)
ValidationIssuesQuery(feed_id, filters, page_token)
```

Condiciones:

- Filtros se compilan desde una lista blanca y parámetros; no se concatena SQL de usuario.
- SQL avanzado queda fuera de v1.0 por seguridad y soporte.
- La paginación preferirá keyset; `OFFSET` solo en tablas pequeñas.
- Cada respuesta incluye versión del contrato y del feed.
- Una tarea de UI no puede cambiar un contrato de consulta sin prueba contractual.

## 12. Validación

### 12.1 Contrato de problema

```json
{
  "validator": "gtfs-explorer",
  "rule_code": "GTFS_REF_STOP_ID_MISSING",
  "severity": "ERROR",
  "category": "REFERENCE",
  "file": "stop_times.txt",
  "row": 42,
  "field": "stop_id",
  "entity": {"type": "trip", "id": "T1"},
  "message": "stop_id referencia una parada inexistente",
  "help_id": "validation/GTFS_REF_STOP_ID_MISSING"
}
```

Severidades:

- `FATAL`: no puede completarse la importación.
- `ERROR`: viola una regla obligatoria; el feed no es válido.
- `WARNING`: riesgo o buena práctica incumplida.
- `NOTICE`: información accionable no invalidante.

Estado agregado:

- `IMPORT_FAILED` si hay fatal.
- `INVALID` si hay errores.
- `VALID_WITH_WARNINGS` si no hay errores y sí warnings.
- `VALID` si no hay errores ni warnings.

No se calcula una puntuación numérica en v1.0.

### 12.2 Capas

1. Preflight de contenedor y archivos.
2. Esquema: cabeceras, requeridos condicionales y duplicados.
3. Parsing: tipos, rangos, enumeraciones y formatos.
4. Referencias entre entidades.
5. Reglas temporales y secuencias.
6. Calendarios y vigencia.
7. Geometría y coordenadas.
8. Buenas prácticas, separadas de validez.
9. MobilityData opcional, identificado con su versión.

El JAR/Java de MobilityData no se convierte en dependencia obligatoria del core. Se ofrecerá un paquete ampliado o configuración sidecar. Si se distribuye, se fija versión, se incluyen licencia/NOTICE y runtime Java compatible.

## 13. Contratos de exportación

### 13.1 JSON semántico

Nombre: `gtfs-explorer.bundle.json`. Versión inicial: `1.0.0`. Debe validarse con JSON Schema.

Estructura normalizada, sin duplicar shapes y paradas por cada viaje:

```json
{
  "schema_version": "1.0.0",
  "generator": {"name": "GTFS Explorer Desktop", "version": "0.1.0"},
  "source": {"sha256": "...", "spec_revision": "YYYY-MM-DD"},
  "selection": {"route_ids": ["D1"], "trip_ids": [], "service_ids": []},
  "agencies": [],
  "routes": [],
  "services": [],
  "stops": [],
  "shapes": [],
  "trips": [
    {
      "trip_id": "D1_WD_O_0700",
      "route_id": "D1",
      "service_id": "WD",
      "direction_id": 0,
      "shape_id": "D1_OUT",
      "stop_times": [
        {
          "stop_id": "OVD_P1",
          "stop_sequence": 1,
          "arrival": "07:00:00",
          "arrival_service_seconds": 25200,
          "departure": "07:00:00",
          "departure_service_seconds": 25200
        }
      ]
    }
  ],
  "transfers": [],
  "metadata": {},
  "warnings": []
}
```

No se incluyen path local, nombre de usuario de Windows ni contenido no seleccionado. Los arrays mantienen un orden determinista.

### 13.2 GeoJSON

- `FeatureCollection` RFC 7946.
- CRS implícito WGS84; no se añade un miembro `crs` obsoleto.
- `LineString` por `shape_id`; `Point` por parada seleccionada.
- Propiedades mínimas: tipo, ID, route/trip asociados cuando sea inequívoco y `geometry_source`.
- Si se construye una línea desde paradas por ausencia de shape, se etiqueta `geometry_source=derived_stop_sequence`; nunca se presenta como shape original.
- Números no finitos se rechazan.

### 13.3 CSV

- **CSV fiel:** conserva valores; destinado a reuso técnico.
- **CSV seguro para hoja de cálculo:** neutraliza celdas que empiezan por `=`, `+`, `-`, `@`, tabulador o retorno; se etiqueta como transformación y no es reimportable como copia exacta.
- UTF-8 con BOM solo si el usuario selecciona compatibilidad Excel; por defecto UTF-8 sin BOM.

### 13.4 Mini-GTFS

Selecciones habilitadas inicialmente: una o varias rutas, opcionalmente restringidas por viajes/servicios. Una parada aislada no constituye Mini-GTFS; se exporta como JSON/GeoJSON/CSV.

Algoritmo de cierre:

1. Seleccionar `routes`.
2. Resolver `trips` y filtros autorizados.
3. Resolver `stop_times`.
4. Resolver paradas y ancestros de estación necesarios.
5. Resolver `shapes` usados.
6. Resolver servicios en `calendar`/`calendar_dates`.
7. Resolver agencias.
8. Resolver transfers solo si sus extremos permanecen y la semántica sigue válida.
9. Resolver pathways/levels de las estaciones incluidas si se soportan.
10. Resolver tarifas y traducciones únicamente con reglas de dependencia implementadas.
11. Añadir `feed_info`/atribuciones ajustadas y manifiesto externo.
12. Escribir `.txt` oficiales, validar referencias, ejecutar reimportación y crear ZIP raíz.

Un archivo opcional no soportado se excluye con warning en el manifiesto. Nunca se copia entero si introduciría entidades ajenas o referencias rotas.

## 14. Diseño del mapa

### 14.1 Integración

- MapLibre GL JS y PMTiles JS se compilan en build; Node.js no se distribuye.
- Qt sirve el bundle y PMTiles mediante HTTP efímero enlazado exclusivamente a `127.0.0.1`.
- QWebChannel transporta comandos y eventos pequeños y tipados.
- El servidor usa puerto y token aleatorios, valida `Host`, solo admite recursos/métodos cerrados y responde `206`/`416` correctamente; no sirve rutas arbitrarias.
- No se escucha en interfaces LAN/WAN y el servidor se cierra con la vista.
- CSP de release: `default-src 'none'`; se habilitan solo `self`, QWebChannel, workers e imágenes locales imprescindibles.

### 14.2 Contrato Python → JavaScript

Comandos versionados:

```text
initialize(config)
setStyle(style_descriptor)
setViewport(bounds)
replaceShapes(feature_collection_chunk)
replaceStops(feature_collection_chunk)
setSelection(entity_ref)
clearLayers()
```

Eventos:

```text
mapReady(capabilities)
featureClicked(entity_ref)
viewportChanged(bounds, zoom)
mapError(code, safe_message)
```

Los payloads validan tamaño y esquema. Para grandes volúmenes se consulta por `bbox`, zoom y límite; no se envía todo el feed al WebEngine.

### 14.3 Paquete de mapa offline

```text
map-package/
├── package.json
├── basemap.pmtiles
├── style.json
├── sprites/
├── fonts/
└── LICENSES/
```

`package.json` declara versión, área, bbox, zooms, fecha de datos, fuente, licencia, atribución y SHA-256. Sin paquete válido se muestra fondo neutro, shapes y paradas. El producto no descarga ni empaqueta teselas del servidor estándar de OpenStreetMap.

### 14.4 Runbook gratuito para crear un mapa regional

Esta operación es de preparación de datos y no la realiza automáticamente la aplicación. Ruta recomendada sin pagar licencias:

1. Descargar una release fijada de `pmtiles` CLI desde el repositorio oficial y verificar el hash publicado si existe.
2. Elegir en la página oficial de builds de Protomaps un basemap compatible con la versión de estilo. Un planeta completo ronda actualmente 120 GB; no debe descargarse completo si solo se necesita una región.
3. Crear un GeoJSON de límite o una bbox de la zona autorizada.
4. Extraer directamente desde el archivo remoto autorizado o desde una copia local:

   ```powershell
   .\pmtiles.exe show <URL_O_ARCHIVO_FUENTE>
   .\pmtiles.exe extract <URL_O_ARCHIVO_FUENTE> .\basemap.pmtiles --region .\region.geojson --maxzoom=14
   .\pmtiles.exe verify .\basemap.pmtiles
   Get-FileHash -Algorithm SHA256 .\basemap.pmtiles
   ```

5. Empaquetar el estilo de Protomaps compatible y sus fuentes/sprites localmente; no dejar URLs CDN en el estilo offline.
6. Crear `package.json` con fuente, fecha, bbox, zoom, licencia ODbL, atribución y hashes.
7. Abrir el paquete en GTFS Explorer sin red y ejecutar el smoke T074.

La extracción remota anterior usa el archivo PMTiles que su proveedor ofrece expresamente para rangos; no usa `tile.openstreetmap.org`. Para control completo puede generarse el basemap desde un extracto `.osm.pbf` autorizado con el pipeline abierto Protomaps/Planetiler, Java 21+ y Maven. Esa ruta consume más CPU, RAM, disco y tiempo aunque la licencia del software/datos no tenga tarifa.

## 15. UI de v1.0

Navegación lateral:

1. Resumen.
2. Rutas y viajes.
3. Paradas.
4. Horarios.
5. Shapes/mapa.
6. Archivos/tablas.
7. Validación.
8. Exportar.
9. Ayuda.

Estados globales explícitos: `NO_PROJECT`, `IMPORTING`, `READY`, `INVALID`, `CANCELLED`, `FAILED`, `MIGRATION_REQUIRED`.

Reglas UX:

- No habilitar una acción imposible.
- Mostrar progreso por fase, no porcentaje ficticio cuando no pueda calcularse.
- Los errores incluyen acción siguiente.
- Cerrar la aplicación durante un job solicita cancelar o esperar.
- La UI recuerda preferencias, no datos del feed, salvo consentimiento para recientes.
- Nunca cargar millones de filas en `QTableWidget`; usar `QAbstractTableModel` paginado.
- Los filtros encadenados muestran nombre e ID y se reinician de forma determinista.

## 16. Workspace, caché y recuperación

### 16.1 Estructura

```text
workspace/
├── projects/<project_id>/
│   ├── project.json
│   ├── data.duckdb
│   ├── cache/
│   └── reports/
├── temp/<job_id>/
├── logs/
└── settings.json
```

Modo portable se activa con `portable.flag` junto al ejecutable. Usa `workspace/` junto a la aplicación si es escribible. Si el USB/carpeta es de solo lectura o no tiene espacio, se solicita una ubicación; no se cae silenciosamente a una ruta que rompa expectativas de privacidad. El modo instalado usa `%LOCALAPPDATA%\GTFS Explorer`.

`project.json` tiene JSON Schema, versión, feed hash, estado y referencias relativas. No contiene credenciales. Al iniciar:

1. Detectar jobs incompletos.
2. Marcar proyecto `RECOVERY_REQUIRED`.
3. Validar base y migraciones.
4. Ofrecer reintentar o limpiar solo temporales.
5. Nunca borrar el feed fuente.

La caché es descartable y versionada. Si no coincide su clave, se elimina de forma segura y se regenera.

## 17. Seguridad y privacidad

Amenazas y controles mínimos:

| Amenaza | Control |
|---|---|
| ZIP Slip/bomba ZIP | Resolución confinada, cuotas, ratios, espacio y cancelación |
| CSV malformado | Parser estricto, staging fiel, límites de línea/campo y errores trazables |
| Inyección SQL | Consultas parametrizadas y filtros de lista blanca |
| Fórmulas CSV | Exportación Excel-safe explícita |
| XSS en mapa/ayuda | Escape, JSON serializado, CSP y recursos locales |
| Navegación WebEngine | Bloqueo de URL remota y descargas en release |
| Exposición en logs | IDs técnicos minimizados, rutas truncadas, sin filas completas |
| Sobrescritura de salida | Confirmación, temporal y reemplazo atómico |
| DLL hijacking portable | Directorios controlados, build limpio, no cargar plugins desde cwd arbitrario |
| Dependencias vulnerables | lockfile, inventario/SBOM y revisión antes de release |
| Telemetría accidental | No incluir SDK analítico ni llamadas de red automáticas |

Los feeds de transporte pueden ser públicos, privados o estar sujetos a licencia. La aplicación no interpreta “descargable” como autorización de redistribución. Cada exportación conserva atribuciones aplicables y permite al usuario documentar la licencia de origen.

## 18. Empaquetado, distribución y licencias

### 18.1 Artefactos

```text
dist/
├── GTFSExplorer-<version>-windows-x64-portable.zip
├── GTFSExplorer-<version>-windows-x64-setup.exe
├── SHA256SUMS.txt
├── THIRD_PARTY_NOTICES.html
├── SBOM.cdx.json
└── release-manifest.json
```

El portable será una carpeta `standalone`, no un único EXE autoextraíble. Es más fácil de inspeccionar, arranca antes y evita depender del directorio temporal. El ZIP contendrá `portable.flag`, runtime, recursos, manual, licencias y un workspace vacío.

El instalador NSIS será por usuario y sin privilegios administrativos por defecto. Creará acceso directo, desinstalador y asociación opcional de `.zip` solo si puede distinguir de forma segura un GTFS; en v1.0 es preferible no registrar la extensión genérica `.zip`.

### 18.2 Licencias relevantes

- PySide6/Qt for Python: LGPLv3/GPLv3 o licencia comercial. La distribución propietaria sin coste requiere revisión y cumplimiento real de LGPLv3, bibliotecas reemplazables cuando aplique, textos de licencia, código fuente/oferta correspondiente de Qt modificado y avisos. No es asesoramiento jurídico.
- DuckDB: licencia permisiva MIT.
- MapLibre GL JS: licencia BSD-3-Clause.
- PMTiles: licencia permisiva; la licencia del software no concede derechos sobre los datos cartográficos almacenados.
- MobilityData GTFS Validator: Apache-2.0.
- OpenStreetMap: datos ODbL con atribución y obligaciones sobre bases derivadas; sus servidores de teselas tienen una política separada que prohíbe descarga masiva/offline.
- NSIS: código abierto y gratuito para cualquier uso según su documentación oficial.

`T093` debe generar un inventario desde las versiones realmente bloqueadas. Este documento no sustituye ese control ni una revisión jurídica antes de venta pública.

### 18.3 Firma de código

La firma no es necesaria para construir o probar. Un ejecutable sin firmar es gratuito, pero Windows SmartScreen puede advertir al usuario. Para producción pública:

- Azure Artifact Signing Basic figura a 9,99 USD/mes por cuenta y 5.000 firmas/mes, más impuestos; la elegibilidad depende del tipo de entidad y país.
- Microsoft estima certificados OV de terceros alrededor de 300–500 USD/año.
- Alternativa gratuita: release sin firma con SHA-256 publicado. Es válida técnicamente, pero ofrece peor confianza y adopción.

No se contratará firma, mapas o Qt comercial sin autorización expresa de Yeison.

## 19. Análisis económico y alternativa gratuita

Precios consultados el 11/08/2026; pueden cambiar. Las cifras de horas son estimaciones de planificación, no hechos comprobados.

### 19.1 Coste monetario obligatorio

| Concepto | MVP/v1.0 con alternativa libre |
|---|---:|
| Python, PySide6 bajo LGPL, DuckDB, Shapely, MapLibre, PMTiles | 0 € |
| pytest, Ruff, mypy, uv, Nuitka/pyside6-deploy | 0 € |
| NSIS | 0 € |
| MobilityData Validator + runtime Java abierto | 0 € |
| Datos OSM obtenidos legalmente y herramientas libres | 0 € de licencia |
| Servidor/API/cuenta de usuario | 0 €; no se necesitan |
| Firma de código | 0 € si se distribuye sin firmar |
| **Total obligatorio en efectivo** | **0 €**, usando equipo, Internet y almacenamiento existentes |

El total 0 € no incluye electricidad, desgaste/equipo, Internet, USB, tiempo de trabajo, copias de seguridad ni posible asesoría jurídica.

### 19.2 Opcionales de pago

| Opción | Coste orientativo actual | Alternativa gratuita |
|---|---:|---|
| Firma Azure Artifact Signing Basic | 9,99 USD/mes + impuestos | Sin firma + hashes; peor SmartScreen |
| Certificado OV de CA | 300–500 USD/año estimados por Microsoft | Igual que arriba |
| MapTiler Cloud comercial | desde 25 USD/mes + impuestos | PMTiles local generado desde OSM autorizado o fondo vacío |
| MapTiler on-prem comercial | desde 2.500 USD/año | Pipeline abierto propio y PMTiles |
| Qt comercial | precio bajo consulta | Cumplimiento LGPLv3 con PySide6/Qt permitido |
| Inno Setup en uso comercial | licencia solicitada por el proveedor | NSIS, gratuito para cualquier uso |
| Soporte/CI/almacenamiento premium | variable | Builds locales y repositorio dentro de cuotas gratuitas |

### 19.3 Coste de desarrollo

| Alcance | Estimación de esfuerzo solo, con experiencia Python/desktop |
|---|---:|
| MVP técnico M0–M2 | 160–260 horas |
| MVP de producto M0–M3 | 280–450 horas acumuladas |
| v1.0 M0–M5 | 500–800 horas acumuladas |
| Visión con simulador y Realtime | 700–1.100 horas acumuladas |

Ejemplos de valoración, sin afirmar una tarifa de mercado:

- v1.0 a 30 €/h: 15.000–24.000 €.
- v1.0 a 60 €/h: 30.000–48.000 €.
- Trabajo propio: puede requerir 0 € de desembolso laboral, pero consume las mismas horas.

La vía gratuita recomendada es: desarrollo propio, stack abierto, portable sin firma durante pilotos, fondo de mapa vacío más paquetes PMTiles generados legalmente, validación local y distribución manual con hashes. Firma y mapas comerciales solo se valoran después de validar usuarios, comprador y pago.

## 20. Estrategia de pruebas

### 20.1 Pirámide

- Unitarias: tiempos GTFS, selección, cierre de dependencias, paths y reglas.
- Contrato: JSON Schema, puertos, DTOs, mensajes del mapa y problemas.
- Integración: importación → DuckDB → consulta → exportación → reimportación.
- Diferenciales: comparar validación formal con MobilityData sin exigir identidad de reglas propias.
- UI: modelos, estados, navegación y smoke tests mínimos.
- Packaging: arranque y flujo básico en VM Windows limpia y sin Internet.
- Rendimiento: fixtures sintéticos reproducibles con métricas de tiempo, RAM y disco.
- Seguridad: ZIP malicioso, CSV extremo, HTML/JS en campos, paths largos y cancelación.

### 20.2 Fixtures mínimos

1. `demo_valid_minimal.zip`: core válido y pequeño.
2. `demo_valid_full.zip`: opcionales soportados.
3. `times_over_24h.zip`.
4. `multi_agency.zip`.
5. `no_shapes.zip`.
6. `calendar_dates_only.zip`.
7. `invalid_references.zip`.
8. `invalid_timetable.zip`.
9. `invalid_geometry.zip`.
10. `extensions_unknown_columns.zip`.
11. `nested_files.zip`.
12. `malicious_zip_slip.zip` generado en test, no distribuido como artefacto ejecutable.
13. `csv_injection_values.zip`.
14. Fixture grande sintético generado, no almacenado completo en Git.

El `GTFS_COMPLETO_DEMO_ASTURIAS.zip` citado en la conversación no está en este repositorio. Si se recupera, debe verificarse, versionarse como fixture o mantenerse fuera con un script reproducible; no se asumirá que existe.

### 20.3 Comandos objetivo

```powershell
uv sync --frozen --all-groups
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q
uv run pytest tests/integration -q
uv run python tools/check_licenses.py
uv run python tools/build_portable.py
uv run pytest tests/packaging -q
```

Los comandos se crean y documentan en las tareas correspondientes; no deben afirmarse disponibles antes de implementarlos.

## 21. Definition of Done

### 21.1 Para una tarea

- Dependencias cumplidas.
- Alcance y fuera de alcance respetados.
- Código y documentación coherentes.
- Tests nuevos para comportamiento nuevo o corregido.
- Pruebas indicadas ejecutadas y con resultado registrado.
- Sin errores de formato, tipo o `git diff --check` en archivos tocados.
- Sin secretos, binarios accidentales ni datos privados.
- `CURRENT_STATE.md` actualizado solo si corresponde.

### 21.2 Para v1.0

- Todos los RF de v1.0 demostrados o formalmente retirados mediante decisión.
- Cero fallos conocidos de severidad crítica/alta.
- Core importado sin pérdida silenciosa.
- Mini-GTFS reimportable para el alcance declarado.
- JSON y GeoJSON validados contra sus contratos.
- UI usable sin consola, Python o Internet.
- Portable e instalador probados en Windows limpio.
- Ejecución desde ruta con espacios, Unicode y USB probada.
- Recuperación tras cancelación/cierre probada.
- Benchmark publicado para el equipo de referencia.
- Licencias, atribuciones, SBOM, hashes y manual incluidos.
- No hay telemetría ni tráfico de red no solicitado.
- Simulador y Realtime no bloquean el release.

## 22. Protocolo de ejecución para Codex con razonamiento bajo

### 22.1 Máquina de estados de una tarea

```text
PENDING -> READY -> IN_PROGRESS -> VERIFIED -> DONE
                  \-> BLOCKED
```

- `READY`: todas las dependencias constan como `DONE` en `CURRENT_STATE.md` o el registro de tareas.
- `VERIFIED`: las pruebas de la ficha han pasado realmente.
- `DONE`: se ha entregado el resumen y no queda criterio pendiente.
- `BLOCKED`: falta una decisión externa; no significa “difícil”.

### 22.2 Secuencia obligatoria

1. Leer `AGENTS.md`, `CURRENT_STATE.md` y la ficha exacta.
2. Comprobar dependencias y estado del árbol de trabajo.
3. Localizar solo archivos indicados; si no existen y la tarea ordena crearlos, crearlos.
4. Escribir una comprobación que falle cuando sea práctico.
5. Implementar el mínimo.
6. Ejecutar la prueba específica.
7. Ejecutar calidad proporcional.
8. Revisar diff y archivos no relacionados.
9. Actualizar estado si cambia materialmente.
10. Cerrar con evidencia.

### 22.3 Reglas contra bucles y ambigüedad

- Tras dos intentos equivalentes fallidos, no repetir. Leer el error, reducir el caso y documentar una hipótesis distinta.
- No cambiar de biblioteca para ocultar un error sin decisión técnica.
- No generar pantallas placeholder para “avanzar”.
- No usar datos inventados fuera de `tests/fixtures`.
- No relajar una validación ni marcar `xfail/skip` sin explicar y autorizar el motivo.
- No editar el lockfile durante una tarea ajena a dependencias.
- No modificar esquema sin migración y prueba.
- No cambiar un formato público sin subir versión y prueba de compatibilidad.
- Si una tarea enumera una puerta, el fallo de la puerta bloquea las posteriores.

### 22.4 Formato de cierre obligatorio

```text
Tarea: Txxx — DONE/VERIFIED/BLOCKED
Cambio: ...
Archivos: ...
Pruebas ejecutadas: comando -> resultado
Criterios demostrados: ...
Pendiente o riesgo real: ...
No realizado por estar fuera de alcance: ...
```

## 23. Mapa de dependencias

```text
T000 -> T001 -> T002 -> T003
                  |       |
                  v       v
                T004    T005
                          | \
                          |  +-> T020 -> T021
                          v              |
                    T010 -> T011 -> T012 -> T013 -> T014
                                      |               |
                                      +-------+-------+
                                              v
                                    T015 -> T016 -> T017 -> T018
                                              |
                                              v
                                      T022 -> T023 -> T024
                                              |
                     +------------------------+------------------+
                     v                                           v
              T030..T035                                  T040..T046
                     \                                           /
                      +----------------T050..T057----------------+
                                         |
                                         v
                                  T060..T066
                                         |
                                         v
                                  T070..T076
                                         |
                                         v
                                  T080..T096
                                         |
                                   RELEASE v1.0
                                         |
                                  F100 / F110
```

La figura resume, pero la ficha concreta manda. Los rangos no autorizan ejecutar varias tareas juntas.

## 24. Plan maestro por tareas

Cada ficha es una unidad de trabajo. “Archivos” indica rutas previsibles, no permiso para tocar otros módulos sin justificación.

### Fase A — Gobierno y base reproducible

#### T000 — Confirmar línea base documental

- **Objetivo:** convertir el plan aprobado en el punto de partida del repositorio.
- **Alcance:** revisar coherencia de `CURRENT_STATE`, arquitectura, decisiones, dominio y este plan; registrar estado `PLANNED`.
- **Archivos:** `docs/*.md`, `README.md` si existe.
- **Dependencias:** ninguna.
- **Criterios de aceptación:** no quedan plantillas `AAAA-MM-DD` ni contradicciones de estado; autoría y derechos constan.
- **Pruebas:** búsqueda de placeholders y enlaces locales rotos básicos.
- **Terminado:** documentación coherente y sin afirmar que existe código.
- **Riesgos:** duplicar información; mantener este documento como plan y los otros como resúmenes normativos.
- **Fuera de alcance:** crear código.

#### T001 — Fijar plataforma y versiones

- **Objetivo:** comprobar una combinación compatible de Python, PySide6 WebEngine, DuckDB, Shapely, Nuitka y herramientas.
- **Alcance:** mini smoke temporal, tabla de versiones y decisión de Windows mínimo.
- **Archivos:** `pyproject.toml`, `uv.lock`, `docs/DECISIONS.md`, `tools/smoke_dependencies.py`.
- **Dependencias:** T000.
- **Criterios de aceptación:** importan módulos x64, abre/cierra `QWebEngineView`, DuckDB crea/consulta base, Shapely calcula una distancia y Nuitka reconoce el entorno.
- **Pruebas:** ejecutar smoke en Windows objetivo y registrar versiones exactas.
- **Terminado:** lockfile reproducible y DEC actualizada.
- **Riesgos:** ruedas incompatibles; cambiar una versión cada vez y repetir smoke.
- **Fuera de alcance:** UI del producto.

#### T002 — Crear esqueleto por capas

- **Objetivo:** materializar el árbol objetivo con entrypoint mínimo.
- **Alcance:** paquetes, configuración de build, CLI `--version` y ventana vacía identificada como pre-alpha.
- **Archivos:** `src/`, `pyproject.toml`, `tests/`, `README.md`.
- **Dependencias:** T001.
- **Criterios de aceptación:** instalación editable, imports respetan capas, `python -m gtfs_explorer --version` funciona.
- **Pruebas:** test de imports y smoke del entrypoint.
- **Terminado:** no hay lógica GTFS ni pantallas ficticias.
- **Riesgos:** sobrearquitectura; crear solo paquetes usados por tareas inmediatas.
- **Fuera de alcance:** importador y diseño visual.

#### T003 — Calidad y comandos canónicos

- **Objetivo:** disponer de lint, formato, tipos y tests con un único flujo documentado.
- **Alcance:** configurar Ruff, mypy, pytest, marcadores y script PowerShell o Python no destructivo.
- **Archivos:** `pyproject.toml`, `tools/check.ps1`, `README.md`.
- **Dependencias:** T002.
- **Criterios de aceptación:** los comandos de desarrollo pasan desde clon limpio sincronizado.
- **Pruebas:** ejecutar el flujo completo.
- **Terminado:** ninguna comprobación se silencia globalmente para lograr verde.
- **Riesgos:** configuración demasiado estricta; excepciones locales justificadas.
- **Fuera de alcance:** CI remoto.

#### T004 — Crear fixtures GTFS reproducibles

- **Objetivo:** generar los fixtures mínimos sin depender del ZIP histórico ausente.
- **Alcance:** generador determinista y primeros feeds válido/defectuosos core.
- **Archivos:** `tests/fixtures/build_fixtures.py`, `tests/fixtures/specs/`, `.gitignore`.
- **Dependencias:** T002, T003.
- **Criterios de aceptación:** mismo input produce mismos contenidos lógicos y manifiesto; los ZIP no contienen timestamps variables o se normalizan.
- **Pruebas:** hashes/contenidos y apertura con `zipfile`.
- **Terminado:** fixture válido documentado como ficticio.
- **Riesgos:** fixture autocumple el parser; luego añadir feeds externos autorizados.
- **Fuera de alcance:** copiar datos reales sin licencia.

#### T005 — Rutas, settings y modo portable

- **Objetivo:** definir ubicaciones escribibles antes de crear datos.
- **Alcance:** resolución installed/portable, `portable.flag`, espacio libre, settings con JSON Schema y paths relativos.
- **Archivos:** `application/settings.py`, `infrastructure/filesystem/paths.py`, `schemas/project/`, tests.
- **Dependencias:** T002, T003.
- **Criterios de aceptación:** paths con espacios/Unicode, carpeta no escribible y portable se comportan según sección 16.
- **Pruebas:** unitarias con temporales y permisos simulados.
- **Terminado:** no se escribe en cwd arbitrario ni se usa una ruta silenciosa.
- **Riesgos:** diferencias de permisos Windows; incluir prueba en VM más adelante.
- **Fuera de alcance:** persistir proyectos.

### Fase B — Entrada e importación segura

#### T010 — Contrato de fuente y manifiesto

- **Objetivo:** representar cualquier entrada sin abrirla todavía como feed válido.
- **Alcance:** DTOs `InputSource`, `SourceEntry`, `SourceManifest`, hashes y estados.
- **Archivos:** `domain/source.py`, `domain/ports.py`, tests unitarios.
- **Dependencias:** T004, T005.
- **Criterios de aceptación:** manifiesto no contiene paths sensibles serializados; orden y hash son deterministas.
- **Pruebas:** archivos, carpetas vacías, Unicode y duplicados lógicos.
- **Terminado:** contrato versionado y sin dependencia de ZIP/Qt.
- **Riesgos:** confundir hash del contenedor con contenido; conservar ambos cuando aplique.
- **Fuera de alcance:** extracción.

#### T011 — Lector ZIP confinado

- **Objetivo:** inventariar y extraer ZIP sin escapar de cuotas ni workspace.
- **Alcance:** controles de sección 10, cancelación y errores tipados.
- **Archivos:** `infrastructure/importing/zip_source.py`, `domain/errors.py`, tests de seguridad.
- **Dependencias:** T010.
- **Criterios de aceptación:** rechaza traversal, absoluto, ADS, symlink, colisión case/Unicode, exceso de ratio/tamaño/entradas y falta de espacio.
- **Pruebas:** matriz maliciosa generada en memoria; ZIP válido se extrae y verifica.
- **Terminado:** toda ruta resuelta se comprueba bajo el temporal antes de escribir.
- **Riesgos:** falsos positivos en feeds grandes; cuotas configurables, nunca omitidas.
- **Fuera de alcance:** interpretar CSV.

#### T012 — Fuente directorio y archivo compatible

- **Objetivo:** inventariar carpeta extraída y `.csv` parcial con las mismas garantías.
- **Alcance:** sin seguir enlaces/reparse points, root estricto, archivos regulares permitidos.
- **Archivos:** `infrastructure/importing/directory_source.py`, tests.
- **Dependencias:** T010, T011.
- **Criterios de aceptación:** mismo manifiesto lógico para ZIP y carpeta equivalentes; subcarpetas se reportan.
- **Pruebas:** enlace, archivo bloqueado, path largo, nombres repetidos y carpeta válida.
- **Terminado:** la fuente nunca se modifica.
- **Riesgos:** junctions Windows; resolver y rechazar si salen de raíz.
- **Fuera de alcance:** UI de selección.

#### T013 — Parser tabular fiel

- **Objetivo:** leer GTFS estricto y CSV compatible sin perder lexemas ni filas silenciosamente.
- **Alcance:** UTF-8/BOM, cabecera, quoting, límites, número de fila, detección compatible confirmable.
- **Archivos:** `infrastructure/importing/tabular_reader.py`, fixtures y tests.
- **Dependencias:** T012.
- **Criterios de aceptación:** IDs con ceros, horas >24 h, comas citadas, saltos y columnas extra se preservan; encoding inválido produce problema.
- **Pruebas:** casos RFC CSV, GTFS y archivos defectuosos.
- **Terminado:** `ignore_errors` no está activo y todo rechazo indica fila.
- **Riesgos:** líneas gigantes; límite configurable con mensaje.
- **Fuera de alcance:** tipos GTFS.

#### T014 — Registro versionado de especificación

- **Objetivo:** codificar archivos, campos, requerimientos condicionales, tipos, enums y referencias de GTFS Schedule.
- **Alcance:** revisión oficial fechada, JSON/YAML propio validado y cargador tipado.
- **Archivos:** `schemas/gtfs_schedule/<revision>/`, `domain/spec.py`, tests.
- **Dependencias:** T003.
- **Criterios de aceptación:** lista cotejada con referencia oficial; cada regla tiene ID estable y fuente; esquema se valida a sí mismo.
- **Pruebas:** snapshots controlados y casos de requisitos condicionales.
- **Terminado:** revisión exacta documentada; no copiar ejemplos como norma.
- **Riesgos:** deriva de la especificación; nueva revisión requiere tarea/migración.
- **Fuera de alcance:** Realtime.

#### T015 — Staging DuckDB fiel

- **Objetivo:** cargar por lotes todas las tablas inventariadas conservando texto y procedencia.
- **Alcance:** tablas `stg_*`, columnas extra, fila fuente, transacción y rollback.
- **Archivos:** `infrastructure/duckdb/migrations/`, `importing/staging_loader.py`, tests de integración.
- **Dependencias:** T013, T014, T020.
- **Criterios de aceptación:** recuentos coinciden con fuente; cancelación revierte; tablas desconocidas quedan inventariadas sin ejecutarse.
- **Pruebas:** feeds pequeños, errores a mitad y cancelación.
- **Terminado:** no se carga el feed entero en memoria Python.
- **Riesgos:** orden circular con T020; resolver ejecutando T020 antes en el registro real.
- **Fuera de alcance:** normalización.

#### T016 — Normalización core

- **Objetivo:** poblar tablas tipadas de los archivos core.
- **Alcance:** agencia, stops, routes, trips, stop_times, calendar y calendar_dates; conversiones y problemas.
- **Archivos:** `importing/normalizers/core.py`, migraciones, tests.
- **Dependencias:** T014, T015, T021.
- **Criterios de aceptación:** lexema y valor tipado trazables; vacíos/requeridos/horas >24 correctos; ninguna corrección silenciosa.
- **Pruebas:** fixtures core válidos y defectuosos.
- **Terminado:** importación core transaccional.
- **Riesgos:** calendario condicional; cubrir combinaciones oficiales.
- **Fuera de alcance:** opcionales.

#### T017 — Normalización de geometría y opcionales prioritarios

- **Objetivo:** tipar shapes, frequencies, transfers, feed_info y attributions.
- **Alcance:** solo archivos enumerados; el resto permanece en staging/inventario.
- **Archivos:** `normalizers/geometry.py`, `normalizers/optional.py`, migraciones y tests.
- **Dependencias:** T016.
- **Criterios de aceptación:** shapes ordenables, frecuencias y transfers conservan semántica; metadata visible.
- **Pruebas:** fixture full y casos límite.
- **Terminado:** tabla de cobertura actualizada.
- **Riesgos:** semántica avanzada de transferencias; no inferir reglas.
- **Fuera de alcance:** fares v2, pathways y flex.

#### T018 — Orquestador de importación

- **Objetivo:** unir preflight, staging, normalización y validación mínima en un job recuperable.
- **Alcance:** estados, progreso por fase, cancel token, commit y limpieza.
- **Archivos:** `application/commands/import_feed.py`, `application/jobs/`, tests integración.
- **Dependencias:** T011–T017, T022.
- **Criterios de aceptación:** `READY`, `INVALID`, `CANCELLED` y `FAILED` son reproducibles; no existe `READY` parcial.
- **Pruebas:** éxito, invalidación, cancelación en cada fase y fallo de disco simulado.
- **Terminado:** flujo invocable sin UI.
- **Riesgos:** progreso falso; usar pasos/filas conocidas y estado indeterminado cuando corresponda.
- **Fuera de alcance:** diálogo Qt.

### Fase C — Persistencia y consultas

#### T020 — Migraciones y conexión DuckDB

- **Objetivo:** crear base por proyecto con migraciones transaccionales y límites de recursos.
- **Alcance:** gestor de conexión, pragmas/settings, temp path, schema version y backup previo a migración.
- **Archivos:** `infrastructure/duckdb/database.py`, `migrations/`, tests.
- **Dependencias:** T001, T005.
- **Criterios de aceptación:** base vacía y versión anterior migran; migración fallida revierte; conexión no se comparte entre threads.
- **Pruebas:** integración con cierres y corrupción controlada.
- **Terminado:** toda conexión se cierra en tests y aplicación.
- **Riesgos:** límites DuckDB no abarcan toda memoria; benchmark y control de threads.
- **Fuera de alcance:** tablas GTFS concretas salvo control.

#### T021 — Puertos y repositorios base

- **Objetivo:** separar casos de uso de SQL.
- **Alcance:** unidad de trabajo, feed/project repositories y resultados paginados.
- **Archivos:** `domain/ports.py`, `duckdb/repositories/`, tests contrato.
- **Dependencias:** T020.
- **Criterios de aceptación:** aplicación usa puertos; SQL queda en infraestructura; errores se traducen a dominio.
- **Pruebas:** contrato contra DuckDB temporal.
- **Terminado:** no hay dependencia circular.
- **Riesgos:** repositorio genérico excesivo; interfaces por caso real.
- **Fuera de alcance:** todas las queries funcionales.

#### T022 — Metadatos de proyecto/feed/job

- **Objetivo:** persistir manifiestos, estados y hashes de forma consistente.
- **Alcance:** tablas de control, `project.json` y reconciliación al abrir.
- **Archivos:** repositorios, JSON Schema, tests.
- **Dependencias:** T010, T020, T021.
- **Criterios de aceptación:** DB y descriptor coinciden; hash evita confundir feeds homónimos.
- **Pruebas:** reapertura, descriptor ausente/inválido y feed cambiado.
- **Terminado:** paths persistidos son relativos cuando pertenecen al proyecto.
- **Riesgos:** dos fuentes de verdad; DuckDB manda y JSON es descriptor verificable.
- **Fuera de alcance:** historial de versiones del feed.

#### T023 — Persistencia de proyectos y caché

- **Objetivo:** abrir/cerrar proyectos y cachear derivados descartables.
- **Alcance:** claves versionadas, bloqueo de escritor único y política de invalidez.
- **Archivos:** `application/commands/open_project.py`, `infrastructure/filesystem/cache.py`, tests.
- **Dependencias:** T022.
- **Criterios de aceptación:** caché vieja se ignora; dos escritores se bloquean con mensaje; lector no ve estado parcial.
- **Pruebas:** concurrencia local y cambio de versión.
- **Terminado:** borrar caché no pierde datos importados.
- **Riesgos:** locks huérfanos; PID/tiempo y recuperación conservadora.
- **Fuera de alcance:** colaboración multiusuario.

#### T024 — Recuperación y limpieza

- **Objetivo:** gestionar temporales y jobs incompletos sin borrar datos válidos.
- **Alcance:** detección al inicio, cuarentena, reintento y limpieza confirmada.
- **Archivos:** `application/commands/recover_workspace.py`, filesystem, tests.
- **Dependencias:** T018, T023.
- **Criterios de aceptación:** crash simulado no deja proyecto READY falso; solo rutas verificadas bajo workspace se eliminan.
- **Pruebas:** estados interrumpidos y paths manipulados.
- **Terminado:** toda operación destructiva muestra objetivo exacto.
- **Riesgos:** pérdida de datos; preferir cuarentena.
- **Fuera de alcance:** reparación de DuckDB corrupto.

#### T030 — Cálculo de servicios y fechas

- **Objetivo:** resolver qué `service_id` opera en una fecha y el periodo global.
- **Alcance:** calendar, excepciones, solo calendar_dates y límites.
- **Archivos:** `domain/service_calendar.py`, query/repository, tests.
- **Dependencias:** T016, T021.
- **Criterios de aceptación:** precedencia de excepciones y feeds sin calendar correctos.
- **Pruebas:** fines de semana, add/remove, rangos vacíos y fechas extremas.
- **Terminado:** contrato independiente de UI.
- **Riesgos:** zona horaria no equivale a calendario; no mezclar.
- **Fuera de alcance:** Realtime.

#### T031 — Consulta ruta → viaje → parada

- **Objetivo:** implementar filtros encadenados y timeline de viaje.
- **Alcance:** rutas, servicios, direction_id, trips, stop_times y stops.
- **Archivos:** `application/queries/routes.py`, SQL repositorio, tests.
- **Dependencias:** T016, T021, T030.
- **Criterios de aceptación:** orden por stop_sequence y tiempos de servicio; IDs sin nombre siguen visibles.
- **Pruebas:** multiagencia, direction null/0/1, trips similares y tiempos >24.
- **Terminado:** consultas parametrizadas y paginadas donde proceda.
- **Riesgos:** asumir ida/vuelta; prohibido.
- **Fuera de alcance:** UI.

#### T032 — Inspector de parada

- **Objetivo:** reconstruir contexto de una parada sin consultas N+1.
- **Alcance:** rutas, servicios, próximos eventos del feed y secuencias limitadas.
- **Archivos:** `application/queries/stops.py`, repositorio, tests.
- **Dependencias:** T030, T031.
- **Criterios de aceptación:** se distingue “horario del feed” de tiempo real; fecha opcional explícita.
- **Pruebas:** parent station, parada sin viajes y múltiples rutas.
- **Terminado:** payload con límites y paginación.
- **Riesgos:** “próximo” ambiguo; exigir fecha/hora de servicio o llamarlo “eventos programados”.
- **Fuera de alcance:** predicción.

#### T033 — Matriz de horarios

- **Objetivo:** producir una matriz acotada por ruta/servicio/dirección.
- **Alcance:** trips comparables, orden estable, celdas ausentes y límite de columnas.
- **Archivos:** `application/queries/timetable.py`, tests.
- **Dependencias:** T031.
- **Criterios de aceptación:** no bloquea con miles de viajes; informa truncado y permite exportar completo.
- **Pruebas:** patrones distintos, loops, missing times y >24h.
- **Terminado:** no se fuerza toda la matriz a memoria si supera límite.
- **Riesgos:** viajes con patrones diferentes; agrupar por patrón, no alinear incorrectamente.
- **Fuera de alcance:** edición.

#### T034 — Geometría y distancia parada-shape

- **Objetivo:** construir líneas y métricas reproducibles.
- **Alcance:** orden de puntos, longitud, bbox, proyección y distancia para trip/shape concreto.
- **Archivos:** `infrastructure/geometry/`, queries, tests.
- **Dependencias:** T017, T021.
- **Criterios de aceptación:** no calcula metros sobre grados; geometría inválida produce issue y no crash.
- **Pruebas:** antimeridiano documentado, puntos repetidos, shape corto y coordenadas inválidas.
- **Terminado:** unidades y método constan en DTO.
- **Riesgos:** proyección global; seleccionar por ubicación o usar geodésico.
- **Fuera de alcance:** map matching.

#### T035 — Inspector raw paginado

- **Objetivo:** consultar staging con filtros seguros y exportables.
- **Alcance:** columnas, contains/equality/rangos tipados, sort y page token.
- **Archivos:** `application/queries/raw.py`, repositorio, tests.
- **Dependencias:** T015, T021.
- **Criterios de aceptación:** no admite SQL; columnas se validan contra manifiesto; respuesta acotada.
- **Pruebas:** inyección en filtro/columna, Unicode, tablas grandes y token inválido.
- **Terminado:** UI puede consumir sin conocer DuckDB.
- **Riesgos:** filtros lentos; límites y cancelación.
- **Fuera de alcance:** editor de consultas.

### Fase D — Validación

#### T040 — Framework de reglas y problemas

- **Objetivo:** ejecutar reglas deterministas y persistir el contrato de sección 12.
- **Alcance:** registro, severidad, categorías, lotes, cancelación y mensajes localizables.
- **Archivos:** `domain/validation.py`, `infrastructure/validation/engine.py`, migraciones, tests.
- **Dependencias:** T014, T021, T022.
- **Criterios de aceptación:** códigos únicos/estables; una regla falla de forma aislada sin ocultar las restantes seguras.
- **Pruebas:** registro duplicado, cancelación y orden determinista.
- **Terminado:** sin score numérico.
- **Riesgos:** explosión de issues; deduplicación y límites sin perder recuento.
- **Fuera de alcance:** reglas específicas.

#### T041 — Reglas de contenedor y esquema

- **Objetivo:** validar nombres, presencia, cabeceras, columnas y condicionales.
- **Alcance:** reglas derivadas de T014 y separación estricto/compatible/parcial.
- **Archivos:** `validation/structure.py`, tests.
- **Dependencias:** T040.
- **Criterios de aceptación:** cada incumplimiento cita regla y fuente; no marca compatible como oficial.
- **Pruebas:** matriz de archivos core/condicionales, duplicados y extras.
- **Terminado:** cobertura del registro documentada.
- **Riesgos:** reglas normativas desactualizadas; versión en cada run.
- **Fuera de alcance:** referencias.

#### T042 — Reglas de tipos, dominios y referencias

- **Objetivo:** detectar conversiones, rangos, enums y claves ausentes.
- **Alcance:** core y opcionales tipados en T017.
- **Archivos:** `validation/fields.py`, `validation/references.py`, tests.
- **Dependencias:** T016, T017, T040.
- **Criterios de aceptación:** issue apunta a fila/campo; referencias se validan en lote.
- **Pruebas:** todos los IDs principales, null/vacío y coordenadas/rangos.
- **Terminado:** sin N+1 por fila.
- **Riesgos:** cascada de errores; issue raíz y conteo de dependientes controlado.
- **Fuera de alcance:** todos los opcionales futuros.

#### T043 — Reglas temporales y de secuencia

- **Objetivo:** validar horas, orden, stop_sequence, pickup/drop-off y frecuencias soportadas.
- **Alcance:** reglas oficiales y checks propios etiquetados.
- **Archivos:** `validation/timetable.py`, tests.
- **Dependencias:** T016, T040.
- **Criterios de aceptación:** >24h válido; retrocesos reales y secuencias duplicadas detectados.
- **Pruebas:** midnight, missing arrival/departure, loops y frequencies.
- **Terminado:** no confundir tiempo de servicio con fecha civil.
- **Riesgos:** interpolación permitida por GTFS; seguir referencia.
- **Fuera de alcance:** puntualidad real.

#### T044 — Reglas geográficas

- **Objetivo:** validar coordenadas, shapes y distancia contextual.
- **Alcance:** rangos, secuencias, geometría degenerada, bbox y umbral configurable de parada-shape como warning propio.
- **Archivos:** `validation/geometry.py`, tests.
- **Dependencias:** T034, T040.
- **Criterios de aceptación:** método/unidad/umbral visibles; no se asocia parada a shape ambiguo.
- **Pruebas:** coordenadas cero legítimas/ilegítimas según contexto, shape roto y distancias.
- **Terminado:** problemas navegables.
- **Riesgos:** falsos positivos; regla propia desactivable y no normativa.
- **Fuera de alcance:** corregir geometrías.

#### T045 — Buenas prácticas e informe

- **Objetivo:** añadir recomendaciones separadas y exportar JSON/HTML seguro.
- **Alcance:** subconjunto documentado de best practices, filtros y resumen por severidad.
- **Archivos:** `validation/best_practices.py`, `exporting/validation_report.py`, recursos HTML, tests.
- **Dependencias:** T041–T044.
- **Criterios de aceptación:** HTML escapa campos; informe indica versión y origen de reglas.
- **Pruebas:** XSS en nombres/IDs, snapshot estructural y JSON Schema.
- **Terminado:** `VALID` no depende de notices.
- **Riesgos:** informe enorme; paginar HTML o adjuntar JSON.
- **Fuera de alcance:** dashboard web.

#### T046 — Adaptador MobilityData

- **Objetivo:** ejecutar opcionalmente CLI oficial con versión fijada y capturar reportes.
- **Alcance:** detección Java/JAR sidecar, proceso sin shell, timeout/cancelación y salida JSON/HTML.
- **Archivos:** `infrastructure/validation/mobilitydata.py`, configuración, tests con stub y prueba manual controlada.
- **Dependencias:** T045.
- **Criterios de aceptación:** ausencia del sidecar no rompe core; comando no concatena entrada; versión aparece en UI/informe.
- **Pruebas:** stub éxito/error/timeout y un feed con release fijada.
- **Terminado:** licencias/NOTICE documentados si se empaqueta.
- **Riesgos:** Java aumenta tamaño y superficie; paquete ampliado separado.
- **Fuera de alcance:** descargar automáticamente el JAR.

### Fase E — Exportaciones

#### T050 — Infraestructura de salida atómica

- **Objetivo:** centralizar destinos, nombres, overwrite, temporales, hashes y manifiesto.
- **Alcance:** writer seguro y cancelable.
- **Archivos:** `infrastructure/exporting/atomic_output.py`, dominio export, tests.
- **Dependencias:** T005, T021.
- **Criterios de aceptación:** fallo/cancelación no deja archivo final parcial; path se valida fuera de internals protegidos.
- **Pruebas:** destino existente, disco simulado lleno, Unicode y cancelación.
- **Terminado:** overwrite siempre explícito.
- **Riesgos:** rename no atómico entre volúmenes; temporal en directorio destino.
- **Fuera de alcance:** formatos.

#### T051 — JSON Schema público

- **Objetivo:** fijar `gtfs-explorer.bundle` 1.0.0 con ejemplos y compatibilidad.
- **Alcance:** schema, semver, orden, nullabilidad, tiempos y metadata.
- **Archivos:** `schemas/json_export/1.0.0/`, docs y tests contrato.
- **Dependencias:** T030–T034.
- **Criterios de aceptación:** ejemplo mínimo/completo válidos y ejemplos defectuosos rechazados.
- **Pruebas:** JSON Schema y golden files semánticos.
- **Terminado:** cambio breaking exige 2.0.0.
- **Riesgos:** duplicación/volumen; diseño normalizado.
- **Fuera de alcance:** API HTTP.

#### T052 — Exportador JSON

- **Objetivo:** emitir bundles deterministas por selección.
- **Alcance:** core, shapes y opcionales soportados; streaming cuando sea grande.
- **Archivos:** `infrastructure/exporting/json_exporter.py`, tests.
- **Dependencias:** T050, T051.
- **Criterios de aceptación:** schema válido, orden determinista, sin path local y hash estable para contenido lógico fijando timestamp de test.
- **Pruebas:** ruta/trip/stop, >24h, Unicode y export grande.
- **Terminado:** warnings de omisión incluidos.
- **Riesgos:** JSON enorme; advertir tamaño y permitir cancelación.
- **Fuera de alcance:** NDJSON salvo decisión futura.

#### T053 — Exportador GeoJSON

- **Objetivo:** emitir paradas y shapes conformes a RFC 7946.
- **Alcance:** selección, propiedades, geometría original/derivada y bbox opcional.
- **Archivos:** `infrastructure/exporting/geojson_exporter.py`, schema/tests.
- **Dependencias:** T034, T050.
- **Criterios de aceptación:** lon/lat correctos, sin NaN/Infinity, features trazables.
- **Pruebas:** validar estructura, shapes ausentes/degenerados y Unicode.
- **Terminado:** geometría derivada etiquetada.
- **Riesgos:** demasiados puntos; opción de simplificación explícita sin alterar default.
- **Fuera de alcance:** reproyección de salida.

#### T054 — Exportador CSV fiel y seguro

- **Objetivo:** exportar tablas/filtrados diferenciando fidelidad y hoja de cálculo.
- **Alcance:** encoding, delimitador fijo, quoting, BOM opcional y neutralización.
- **Archivos:** `infrastructure/exporting/csv_exporter.py`, tests.
- **Dependencias:** T035, T050.
- **Criterios de aceptación:** round-trip del modo fiel; payloads de fórmula neutralizados solo en modo seguro.
- **Pruebas:** caracteres iniciales peligrosos, saltos, comillas y Excel-compatible.
- **Terminado:** modo visible en nombre/manifiesto.
- **Riesgos:** cambiar datos sin avisar; UI obliga a elegir descripción clara.
- **Fuera de alcance:** XLSX.

#### T055 — Motor de cierre Mini-GTFS core

- **Objetivo:** calcular conjunto transitivo para rutas/trips/servicios core.
- **Alcance:** pasos 1–7 de sección 13.4 y reporte de inclusión.
- **Archivos:** `domain/subset.py`, `application/queries/subset.py`, tests.
- **Dependencias:** T030, T031, T042.
- **Criterios de aceptación:** no quedan FK core rotas; selección vacía/ambigua falla con motivo.
- **Pruebas:** multiruta, multiagencia, calendar_dates-only y paradas compartidas.
- **Terminado:** algoritmo puro probado antes de escribir ZIP.
- **Riesgos:** filtros eliminan servicio necesario; propiedades de cierre en tests.
- **Fuera de alcance:** opcionales complejos.

#### T056 — Cierre de opcionales soportados

- **Objetivo:** incorporar shapes, transfers, metadata, traducciones y opcionales declarados.
- **Alcance:** matriz de dependencia por archivo y estrategia `include/filter/exclude/error`.
- **Archivos:** `domain/subset_rules.py`, registro y tests.
- **Dependencias:** T017, T055.
- **Criterios de aceptación:** cada archivo conocido tiene política explícita; desconocidos no se copian silenciosamente.
- **Pruebas:** relaciones compartidas y archivos parcialmente seleccionables.
- **Terminado:** tabla de cobertura publicada.
- **Riesgos:** fares v2/flex complejos; excluir hasta tarea específica.
- **Fuera de alcance:** afirmar cobertura total de todos los opcionales.

#### T057 — Escritor y revalidación Mini-GTFS

- **Objetivo:** escribir ZIP oficial raíz, reimportarlo y validar antes de publicar.
- **Alcance:** serialización `.txt`, orden determinista, feed_info/atribución y manifiesto externo.
- **Archivos:** `infrastructure/exporting/gtfs_subset.py`, tests integración.
- **Dependencias:** T050, T055, T056, T045.
- **Criterios de aceptación:** salida se reimporta, no tiene errores core y coincide con selección.
- **Pruebas:** end-to-end y, si disponible, MobilityData.
- **Terminado:** no aparece archivo final si revalidación falla.
- **Riesgos:** validador formal no disponible; internal obligatorio y formal registrado como ejecutado/no disponible.
- **Fuera de alcance:** modificar feed fuente.

### Fase F — Aplicación de escritorio

#### T060 — Shell y máquina de estados UI

- **Objetivo:** crear ventana, navegación y estados sin lógica duplicada.
- **Alcance:** layout, acciones, status bar, settings visuales y estado global.
- **Archivos:** `presentation/desktop/main_window.py`, `application/ui_state.py`, tests UI.
- **Dependencias:** T002, T018, T024.
- **Criterios de aceptación:** acciones habilitadas por estado; cerrar durante job gestiona cancelación.
- **Pruebas:** transiciones de estado y smoke Qt offscreen/cuando sea viable.
- **Terminado:** sin datos hardcodeados como si fueran reales.
- **Riesgos:** UI antes de contratos; dependencias lo impiden.
- **Fuera de alcance:** estilo final.

#### T061 — Abrir/importar con progreso

- **Objetivo:** conectar drop/file dialog al orquestador en worker.
- **Alcance:** preflight, confirmaciones, progreso por fases, cancelación y errores.
- **Archivos:** UI import, job adapters, tests.
- **Dependencias:** T018, T060.
- **Criterios de aceptación:** UI permanece responsiva; no se comparte conexión DuckDB entre threads; cancelación limpia.
- **Pruebas:** smoke con fixture y cancelación.
- **Terminado:** flujo completo sin consola.
- **Riesgos:** señales tras destruir ventana; ownership y desconexión probados.
- **Fuera de alcance:** recientes.

#### T062 — Resumen del feed

- **Objetivo:** mostrar métricas, periodo, archivos y estado de validación.
- **Alcance:** cards/tablas accesibles y navegación a problemas.
- **Archivos:** `presentation/desktop/overview/`, query summary, tests.
- **Dependencias:** T018, T060.
- **Criterios de aceptación:** métricas proceden de consulta; ausente y cero se distinguen.
- **Pruebas:** feed válido/inválido/parcial/multiagencia.
- **Terminado:** fecha y unidades claras.
- **Riesgos:** contar staging frente a normalizado; etiquetar origen.
- **Fuera de alcance:** gráficos decorativos.

#### T063 — Tablas e inspector raw

- **Objetivo:** implementar modelo paginado reutilizable y filtros seguros.
- **Alcance:** `QAbstractTableModel`, sort, copiar, filtros y exportar vista.
- **Archivos:** `presentation/models/paged_table.py`, raw view, tests.
- **Dependencias:** T035, T054, T060.
- **Criterios de aceptación:** no carga dataset completo; token inválido se recupera; copiar respeta selección.
- **Pruebas:** modelo con páginas, sort/filter y tabla grande sintética.
- **Terminado:** sin SQL en UI.
- **Riesgos:** scroll y latencia; prefetch acotado.
- **Fuera de alcance:** edición de celdas.

#### T064 — Rutas, viajes, paradas y horarios

- **Objetivo:** materializar el explorador relacional principal.
- **Alcance:** filtros encadenados, timeline, inspector parada y matriz por patrón.
- **Archivos:** vistas `routes/`, `trips/`, `stops/`, `timetable/`.
- **Dependencias:** T031–T033, T060, T063.
- **Criterios de aceptación:** selección sincronizada y reinicio determinista; nombre+ID; >24h visible.
- **Pruebas:** flujos con fixtures y estados vacíos.
- **Terminado:** no etiqueta direction_id como ida/vuelta sin dato.
- **Riesgos:** task grande; implementar subviews en commits internos sin abrir otras funciones.
- **Fuera de alcance:** mapa, que llega después.

#### T065 — Vista de validación

- **Objetivo:** listar, filtrar, explicar y navegar problemas.
- **Alcance:** severidades, categorías, detalle, link local de ayuda y export report.
- **Archivos:** `presentation/desktop/validation/`, tests.
- **Dependencias:** T045, T060, T063.
- **Criterios de aceptación:** navegación a raw/entidad; no hay score; origen de regla visible.
- **Pruebas:** issues masivos, XSS textual tratado como texto y filtros.
- **Terminado:** MobilityData separado visualmente si existe.
- **Riesgos:** sobrecargar UI; detalle bajo demanda.
- **Fuera de alcance:** autocorrección.

#### T066 — Asistente de exportación

- **Objetivo:** seleccionar alcance/formato/opciones/destino con previsualización de dependencias.
- **Alcance:** JSON, GeoJSON, CSV y Mini-GTFS; confirmación overwrite; progreso/cancelación.
- **Archivos:** `presentation/desktop/exporter/`, tests.
- **Dependencias:** T052–T057, T060.
- **Criterios de aceptación:** opciones incompatibles deshabilitadas con motivo; resultado muestra hash y warnings.
- **Pruebas:** cada formato, cancelación y destino existente.
- **Terminado:** el usuario sabe si salida es oficial, compatible o derivada.
- **Riesgos:** demasiadas opciones; defaults seguros y ayuda contextual.
- **Fuera de alcance:** subir salida a Internet.

### Fase G — Mapas

#### T070 — Spike vinculante Qt WebEngine/MapLibre/PMTiles

- **Objetivo:** demostrar en un prototipo aislado que el stack satisface offline, bridge y rangos PMTiles.
- **Alcance:** loopback local protegido, CSP, QWebChannel, click de feature, PMTiles pequeño local, build standalone y medición de tamaño/arranque.
- **Archivos:** `spikes/map_webengine/`, informe en `docs/DECISIONS.md`; no integrar en producción.
- **Dependencias:** T001, T034, T060.
- **Criterios de aceptación:** sin red, render de línea/punto, evento ida/vuelta, range requests correctos y ejecución empaquetada.
- **Pruebas:** monitor de red local, paths Unicode/espacios, PMTiles corrupto y reinicio.
- **Terminado:** decisión GO o NO-GO con evidencia; si NO-GO, detener T071–T075.
- **Riesgos:** superficie local del loopback; mitigar con bind estricto, token efímero, `Host`, allowlist, CSP y ciclo de vida acotado.
- **Fuera de alcance:** mapa final.

#### T071 — Pipeline de recursos web

- **Objetivo:** bloquear y compilar MapLibre/PMTiles JS sin runtime Node para usuario.
- **Alcance:** npm lock, build reproducible, hashes, licencias y copia a recursos Qt.
- **Archivos:** `web/map/`, `tools/build_map_assets.py`, `LICENSES/`.
- **Dependencias:** T070 GO.
- **Criterios de aceptación:** build offline con caché preparada/CI documentada; bundle sin URLs/CDN ocultas.
- **Pruebas:** build, escaneo de URLs y hash estable dentro de límites de toolchain.
- **Terminado:** Node queda solo en desarrollo.
- **Riesgos:** dependencias npm transitivas; minimizar y auditar.
- **Fuera de alcance:** capas GTFS.

#### T072 — Bridge tipado del mapa

- **Objetivo:** implementar comandos/eventos versionados y límites de payload.
- **Alcance:** DTOs, serialización, readiness, errores y navegación bloqueada.
- **Archivos:** `presentation/map_bridge/`, JS bridge y tests contrato.
- **Dependencias:** T071.
- **Criterios de aceptación:** mensajes inválidos rechazados sin crash; página solo crea un QWebChannel.
- **Pruebas:** contrato Python/JS, tamaños máximos y eventos fuera de orden.
- **Terminado:** bridge no expone filesystem/SQL.
- **Riesgos:** carrera antes de `mapReady`; cola acotada.
- **Fuera de alcance:** queries.

#### T073 — Shapes y paradas interactivos

- **Objetivo:** conectar selección de UI a capas GeoJSON con fondo vacío.
- **Alcance:** capas, colores saneados, popups seguros, fit bounds y click sincronizado.
- **Archivos:** vistas mapa, queries adaptadoras, JS layers, tests.
- **Dependencias:** T034, T064, T072.
- **Criterios de aceptación:** shape/paradas correctos, falta de shape tratada, XSS mostrado como texto.
- **Pruebas:** fixtures, colores inválidos, geometría vacía y interacción.
- **Terminado:** mapa esencial funciona sin Internet ni basemap.
- **Riesgos:** payload grande; límites preparan T075.
- **Fuera de alcance:** todos los routes simultáneos sin límite.

#### T074 — Paquete PMTiles offline

- **Objetivo:** validar/cargar el formato de paquete de sección 14.3 y mostrar atribución.
- **Alcance:** manifiesto, hashes, bbox/zooms, style/sprites/fonts, selección y fallback.
- **Archivos:** `infrastructure/maps/package.py`, servidor loopback, UI settings, tests.
- **Dependencias:** T070 GO, T072, T073.
- **Criterios de aceptación:** paquete válido abre; corrupto/licencia ausente falla seguro; atribución siempre visible.
- **Pruebas:** paquete fixture pequeño, rangos, USB y offline.
- **Terminado:** ninguna descarga desde OSM estándar.
- **Riesgos:** tamaño; mapas son paquetes separados del portable base.
- **Fuera de alcance:** generador mundial integrado.

#### T075 — Nivel de detalle y rendimiento del mapa

- **Objetivo:** mantener respuesta con muchas paradas/shapes.
- **Alcance:** bbox queries, clustering/simplificación visual, cancelación de viewport antiguo y caché.
- **Archivos:** queries geo, bridge/layers, benchmark.
- **Dependencias:** T073, T074.
- **Criterios de aceptación:** no se envía dataset completo; pan/zoom descarta respuestas obsoletas; métricas publicadas.
- **Pruebas:** fixture grande, zooms, selección persistente y estrés.
- **Terminado:** límites reales sustituyen estimaciones.
- **Riesgos:** simplificación cambia visual; selección detallada usa geometría original.
- **Fuera de alcance:** 3D y terreno.

#### T076 — Empaquetador y runbook de mapa gratuito

- **Objetivo:** hacer reproducible la creación de un paquete regional compatible sin teselas OSM prohibidas.
- **Alcance:** wrapper de `pmtiles extract/verify`, manifiesto, hashes, style/assets locales y documentación de licencia; fuente indicada por el usuario.
- **Archivos:** `tools/build_map_package.py`, `schemas/map_package/`, `docs/MAPS_OFFLINE.md`, tests.
- **Dependencias:** T074.
- **Criterios de aceptación:** una región fixture se empaqueta, valida y abre sin red; ninguna URL CDN queda en el paquete; atribución visible.
- **Pruebas:** CLI ausente/versión incorrecta, fuente remota stub/local, hash corrupto y paquete completo.
- **Terminado:** comando y versiones están documentados; no se versiona un mapa regional grande en Git.
- **Riesgos:** términos/licencia de la fuente; exigir metadatos y confirmación, sin asumir autorización.
- **Fuera de alcance:** descargar el planeta, alojar teselas o redistribuir mapas sin revisión.

### Fase H — Producto, ayuda y release

#### T080 — Manual integrado y ayuda contextual

- **Objetivo:** explicar conceptos, flujos, errores, mapas y exportaciones offline.
- **Alcance:** contenido versionado, índice/búsqueda local y `help_id` de reglas.
- **Archivos:** `resources/help/`, UI help, tests de enlaces.
- **Dependencias:** T065, T066, T076.
- **Criterios de aceptación:** todos los RF principales y códigos públicos enlazan a ayuda; sin links obligatorios a red.
- **Pruebas:** enlaces, búsqueda, assets y HTML seguro.
- **Terminado:** diferencia route/trip/service/direction y >24h explicada.
- **Riesgos:** deriva; ayuda se actualiza en misma tarea que contrato.
- **Fuera de alcance:** curso completo.

#### T081 — Accesibilidad, i18n y pulido de textos

- **Objetivo:** cerrar navegación por teclado, foco, contraste, labels y catálogo español.
- **Alcance:** textos externalizados, pseudo-localización básica y mensajes accionables.
- **Archivos:** `resources/i18n/`, vistas y checklist.
- **Dependencias:** T060–T080.
- **Criterios de aceptación:** flujo central solo teclado; no depende solo de color/icono; IDs copiables.
- **Pruebas:** checklist manual documentado y tests de claves faltantes.
- **Terminado:** castellano completo; otros idiomas preparados, no prometidos.
- **Riesgos:** layouts con texto largo; pseudo-localización.
- **Fuera de alcance:** traducciones profesionales.

#### T090 — Logging, diagnóstico y errores no controlados

- **Objetivo:** registrar lo necesario sin exponer el feed.
- **Alcance:** log rotatorio, correlation/job ID, niveles, redacción, diálogo de error y export diagnóstico consentido.
- **Archivos:** `infrastructure/logging.py`, crash handler, tests.
- **Dependencias:** T018, T060.
- **Criterios de aceptación:** no hay filas completas/rutas fuente por defecto; error conserva código y stack local solo en debug.
- **Pruebas:** secretos/payloads sintéticos, rotación y fallo no controlado.
- **Terminado:** diagnóstico exportado previsualiza contenidos.
- **Riesgos:** redacción insuficiente; allowlist de campos.
- **Fuera de alcance:** envío remoto.

#### T091 — Build portable standalone

- **Objetivo:** producir ZIP ejecutable sin Python instalado.
- **Alcance:** spec pyside6-deploy, plugins mínimos, recursos, portable.flag y script reproducible.
- **Archivos:** `packaging/portable/`, `pysidedeploy.spec`, `tools/build_portable.py`.
- **Dependencias:** T071, T080, T090.
- **Criterios de aceptación:** arranca offline en VM limpia, rutas relativas, WebEngine/mapa y DuckDB funcionan.
- **Pruebas:** smoke packaging, antivirus local sin afirmar ausencia universal de falsos positivos, hash.
- **Terminado:** tamaño/arranque registrados.
- **Riesgos:** QtWebEngine pesado; excluir solo módulos demostrablemente no usados.
- **Fuera de alcance:** un único EXE.

#### T092 — Instalador NSIS

- **Objetivo:** instalar/desinstalar por usuario sin romper datos.
- **Alcance:** accesos directos, versión, upgrade, desinstalación y separación de workspace.
- **Archivos:** `packaging/nsis/`, build script y tests manuales.
- **Dependencias:** T091.
- **Criterios de aceptación:** instalar/actualizar/desinstalar no borra proyectos sin confirmación; no requiere admin por defecto.
- **Pruebas:** VM limpia, upgrade N-1 simulado, uninstall y paths Unicode.
- **Terminado:** setup hash y manifest.
- **Riesgos:** firma ausente/SmartScreen; documentar.
- **Fuera de alcance:** Microsoft Store.

#### T093 — Licencias, atribuciones y SBOM

- **Objetivo:** demostrar qué se distribuye y bajo qué términos.
- **Alcance:** inventario Python/npm/Qt/Java opcional/mapas, LICENSES, notices y CycloneDX.
- **Archivos:** `LICENSES/`, `THIRD_PARTY_NOTICES`, `tools/check_licenses.py`, SBOM config.
- **Dependencias:** T091, T092.
- **Criterios de aceptación:** cada binario/dependencia empaquetado aparece; atribución OSM visible si hay datos OSM; revisión LGPL registrada.
- **Pruebas:** comparar artefacto con inventario y fallar ante licencia desconocida.
- **Terminado:** revisión jurídica marcada como pendiente si habrá venta.
- **Riesgos:** licencias transitivas; automatización más revisión humana.
- **Fuera de alcance:** dictamen jurídico.

#### T094 — Matriz de smoke en Windows limpio

- **Objetivo:** verificar portable e instalador como usuario real.
- **Alcance:** Windows soportados, offline, USB/carpeta, usuario estándar, paths, import/export/mapa/ayuda.
- **Archivos:** `tests/packaging/SMOKE_MATRIX.md`, evidencias y scripts seguros.
- **Dependencias:** T091–T093.
- **Criterios de aceptación:** cada combinación crítica tiene resultado y artefacto/hash exacto.
- **Pruebas:** matriz ejecutada realmente; los skips tienen causa.
- **Terminado:** cero bloqueo de severidad alta.
- **Riesgos:** entorno no disponible; no declarar release hasta ejecutarlo.
- **Fuera de alcance:** todos los antivirus corporativos.

#### T095 — Benchmarks y límites publicados

- **Objetivo:** sustituir RNF estimados por mediciones reproducibles.
- **Alcance:** import, consultas, validación, export, mapa, RAM, disco y cancelación.
- **Archivos:** `tools/benchmark_feed.py`, `docs/PERFORMANCE.md`, fixtures generados.
- **Dependencias:** T075, T091.
- **Criterios de aceptación:** equipo/config/dataset/versiones registrados; regresión umbral en CI/local razonable.
- **Pruebas:** pequeño, medio y objetivo RNF-006.
- **Terminado:** límites de UI/config/manual actualizados.
- **Riesgos:** benchmark artificial; añadir un feed real autorizado cuando exista.
- **Fuera de alcance:** promesas universales.

#### T096 — Release candidate v1.0

- **Objetivo:** cerrar checklist, artefactos, hashes, changelog y estado.
- **Alcance:** ejecutar gates, clasificar defectos y preparar RC antes de final.
- **Archivos:** `CHANGELOG.md`, `docs/RELEASE_CHECKLIST.md`, `CURRENT_STATE.md`, `dist/` fuera de Git si procede.
- **Dependencias:** T080–T095.
- **Criterios de aceptación:** Definition of Done v1.0 completa; artefactos existen, abren y hashes coinciden.
- **Pruebas:** flujo canónico completo y smoke RC.
- **Terminado:** Yeison aprueba publicación/distribución; sin autorización solo queda RC local.
- **Riesgos:** presión por omitir licencia/firma; no ocultar warnings.
- **Fuera de alcance:** publicar o pagar servicios sin permiso.

### Fase futura — Solo después de v1.0

#### F100 — Motor de simulación

- **Objetivo:** simular un viaje Schedule de forma determinista, no representar operación real.
- **Alcance:** reloj de servicio, interpolación sobre shape, eventos de parada, play/pause/seek y multiplicador.
- **Dependencias:** v1.0, T034, T073.
- **Criterios de aceptación:** motor puro sin Qt/mapa; tiempos/posición reproducibles; ausencia de shape tratada.
- **Pruebas:** >24h, dwell, frequencies y saltos.
- **Fuera de alcance:** velocidad real, tráfico, GPS y predicción.

#### F110 — GTFS Realtime

- **Objetivo:** añadir ingestión Protobuf y vinculación explícita con un feed Schedule compatible.
- **Alcance:** TripUpdates, VehiclePositions y Alerts, TTL, timestamps, IDs y estado de conexión.
- **Dependencias:** v1.0 y nueva especificación/decisión de privacidad/red.
- **Criterios de aceptación:** no mezcla feeds incompatibles; datos caducados visibles; red opt-in y secretos seguros.
- **Pruebas:** fixtures protobuf oficiales/sintéticos, reconexión y mensajes incompletos.
- **Fuera de alcance:** backend histórico, cuentas y analítica cloud.

## 25. Matriz de riesgos

| ID | Riesgo | Prob. | Impacto | Mitigación/puerta |
|---|---|---:|---:|---|
| R01 | El servidor loopback de PMTiles amplía superficie local | Baja | Alto | bind 127.0.0.1, token, Host/allowlist/CSP y T070 |
| R02 | Binario portable demasiado grande | Alta | Medio | standalone, plugins mínimos, medir; mapas/Java separados |
| R03 | LGPL/ODbL incumplidas al distribuir | Media | Alto | T093 y revisión jurídica precomercial |
| R04 | Feeds grandes agotan RAM/disco | Alta | Alto | streaming, límites, temp, benchmark y cancelación |
| R05 | Especificación GTFS cambia | Alta | Medio | registro revisionado y migraciones |
| R06 | Mini-GTFS rompe opcionales | Alta | Alto | matriz de closure, excluir explícito, reimportar/validar |
| R07 | Falsos positivos de validación geométrica | Media | Medio | reglas propias separadas, método/umbral visibles |
| R08 | SmartScreen reduce adopción sin firma | Alta | Medio | piloto con hashes; firma solo tras validación |
| R09 | Datos cartográficos elevan tamaño/coste | Alta | Medio | base opcional y paquetes regionales separados |
| R10 | UI se construye antes del núcleo | Media | Alto | gates M1/M2 y dependencias del plan |
| R11 | El chat se trata como estándar | Media | Alto | código/tests y referencia oficial mandan |
| R12 | Alcance “universal” crea soporte infinito | Alta | Alto | modos estricto/compatible y matriz de cobertura |
| R13 | Proyecto no valida usuario/comprador | Alta | Alto comercial | piloto antes de gasto/publicación |
| R14 | Modelo IA repite intentos o amplía alcance | Media | Alto | una T por chat, dos intentos y stop, cierre con evidencia |

## 26. Decisiones abiertas que requieren evidencia, no improvisación

1. Versión mínima exacta de Windows: `T001`.
2. Versiones exactas del stack: `T001`.
3. Viabilidad del transporte loopback PMTiles: demostrada por `T070` y DEC-016.
4. Qué opcionales semánticos entran realmente en v1.0: después de medir M1 y decidir en `DECISIONS.md`.
5. Si se distribuye MobilityData/JRE en un paquete “full”: `T046` + medición de T091.
6. Si se firma el release: después de piloto y con autorización de coste.
7. Licencia propia del producto y estrategia comercial: antes de publicación pública.
8. Dataset/mapa regional que se distribuirá: solo con licencia y atribución verificadas.

Mientras estén abiertas, se usa la opción conservadora descrita: Windows x64 sujeto a spike, opcionales en staging, validador sidecar, release sin firma y sin mapa base distribuido.

## 27. Validación de producto antes de monetizar

Antes de invertir en firma, mapas comerciales o Qt comercial, ejecutar un piloto con al menos 5 usuarios objetivo y 3 feeds distintos autorizados. Medir:

- Tiempo actual para inspeccionar/depurar un feed.
- Problemas que la herramienta detecta y otras alternativas no.
- Frecuencia de exportación y formato realmente necesario.
- Tamaño máximo habitual.
- Necesidad real de portable/USB/offline.
- Quién decide la compra y presupuesto.
- Alternativas actuales: validador MobilityData, herramientas GIS, scripts, Excel y visores web.
- Disposición a pagar por licencia, soporte, actualización o consultoría.

Sin esa evidencia, el proyecto es una herramienta técnica prometedora, no un negocio validado.

## 28. Fuentes técnicas verificadas

Consultadas el 11/08/2026:

- GTFS oficial — Overview: https://gtfs.org/documentation/overview/
- GTFS Schedule Reference: https://gtfs.org/documentation/schedule/reference/
- GTFS Schedule Best Practices: https://gtfs.org/documentation/schedule/schedule-best-practices/
- MobilityData GTFS Validator: https://github.com/MobilityData/gtfs-validator
- Qt for Python y licencia: https://doc.qt.io/qtforpython-6/ y https://doc.qt.io/qt-6/licensing.html
- `pyside6-deploy`: https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-deploy.html
- QWebChannel: https://doc.qt.io/qtforpython-6/overviews/qtwebchannel-javascript.html
- QWebEngine custom schemes: https://doc.qt.io/qt-6/qwebengineurlschemehandler.html
- DuckDB Python/CSV/límites: https://duckdb.org/docs/current/clients/python/overview, https://duckdb.org/docs/current/data/csv/overview y https://duckdb.org/docs/current/operations_manual/limits
- MapLibre GL JS: https://maplibre.org/maplibre-gl-js/docs
- PMTiles para MapLibre: https://docs.protomaps.com/pmtiles/maplibre
- Descargas/extracción de basemap Protomaps: https://docs.protomaps.com/basemaps/downloads y https://docs.protomaps.com/pmtiles/cli
- Construcción propia del basemap: https://docs.protomaps.com/basemaps/build
- Política de teselas OSM: https://operations.osmfoundation.org/policies/tiles/
- Licencia/datos OSM: https://osmfoundation.org/wiki/License/Licence_and_Legal_FAQ
- NSIS: https://nsis.sourceforge.io/Docs/Chapter1.html y https://nsis.sourceforge.io/License
- Azure Artifact Signing: https://learn.microsoft.com/en-us/azure/artifact-signing/how-to-change-sku
- Opciones de firma Windows: https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options
- Precios MapTiler consultados como referencia opcional: https://www.maptiler.com/cloud/pricing/ y https://www.maptiler.com/data/pricing/

## 29. Resultado de este análisis

El proyecto queda aterrizado como una construcción por contratos y puertas de calidad. **T000 queda completada por esta línea base documental**. La siguiente tarea de implementación es **T001**. No se debe crear una pantalla de producto, descargar mapas ni integrar Realtime en el siguiente chat.

Este plan cubre la visión completa, pero protege la entrega al separar lo obligatorio, lo opcional y lo futuro. Alcanzar el 100 % significa completar y demostrar cada criterio de su versión, no generar de una vez todo el código descrito ni afirmar compatibilidad no probada.
