# Historial de cambios

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
