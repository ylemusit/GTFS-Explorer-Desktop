# Historial de cambios

## 0.2.1 — Unreleased

- Experiencia de bienvenida actualizada.
- Identidad profesional unificada de GTFS Explorer Desktop.
- Nuevo icono de aplicación GTFS Explorer.
- Ilustración raster de bienvenida con titlebar, botón de inicio, versión y
  copyright dinámicos.

No añade nuevas capacidades funcionales GTFS ni está publicada.

## 0.1.0 — 2026-09-02

Primera versión estable local de GTFS Explorer Desktop. Se distribuye como
aplicación Windows x64 portable y como instalador por usuario. Esta versión no
añade funcionalidades respecto a RC2.

- Portable e instalador estables con manifiestos, SHA-256, SBOM CycloneDX 1.5
  y avisos de terceros.
- Aceptación manual corta completada con éxito sobre los artefactos estables.
- Firma de código, accesibilidad manual con lector de pantalla y benchmark
  LARGE quedan diferidos; no se incluyen datos CTM ni cartografía comercial.

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.

## 0.1.0-rc2 — 2026-09-01

Candidata local para aceptación manual. No está publicada ni autorizada para
distribución.

- Cierre técnico de Fase 2: importación, validación, exploración y exportación
  Mini-GTFS con round-trip cubierto por E2E.
- Correcciones de workflows de importación, export pack, layout maximizado,
  ventana desacoplable del mapa, rutas y ayuda local.
- Portable e instalador preparados con etiqueta `rc2`; CTM, smokes de paquete,
  runtime instalado y mapa quedan sujetos a la evidencia de los artefactos
  generados en esta candidata.

### Límites y backlog diferido

- La aceptación visual nativa de Windows y la revisión manual con lector de
  pantalla siguen siendo pendientes.
- El benchmark LARGE y la firma de código siguen fuera de este cierre.
- No se incluyen datos CTM ni cartografía comercial en los artefactos.

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.

## 0.1.0-rc1 — 2026-08-15

Primera candidata local de GTFS Explorer Desktop. No está publicada ni
autorizada para distribución.

- Aplicación Windows x64 portable y offline-first para importar, explorar,
  validar y exportar GTFS Schedule.
- Exportaciones JSON, GeoJSON, CSV y Mini-GTFS con los límites declarados.
- Mapa local de shapes y paradas, con PMTiles regional opcional servido solo por
  loopback protegido.
- Ayuda local, accesibilidad base, diagnóstico local, portable, instalador por
  usuario, SBOM, avisos de terceros y textos de licencia.
- La matriz T094 confirmó portable e instalador offline; el upgrade I03 queda
  aplazado a la siguiente versión instalable porque no existe un N-1 previo.

### Límites y avisos conocidos

- El benchmark de flujo completo solo acredita el perfil sintético pequeño;
  RNF-006 no se promete todavía.
- No se distribuyen Java/MobilityData ni datos de mapa por defecto.
- Falta revisión jurídica del cumplimiento LGPL de Qt/PySide6 antes de venta o
  publicación.
- Firma de código, datos cartográficos comerciales y publicación requieren
  autorización expresa de Yeison.

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.
