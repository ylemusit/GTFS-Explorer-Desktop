# P1-32 — Packaging Windows

Estado: DONE técnico local. No se ha publicado ni firmado ningún artefacto.

## Build

- Producto: GTFS Explorer Desktop `0.1.0`.
- Fuente: `HEAD 3cfccdba7554ca815f4eff77d3cb376b8eb228da` más los cambios locales
  existentes y los cambios de packaging de esta tarea; no se exigió worktree limpio.
- Bundler: Nuitka `2.6.9` mediante `pyside6-deploy`.
- Python `3.12.10`, PySide6/Qt `6.8.3`, DuckDB `1.1.3`, Shapely `2.1.2`.
- NSIS: `C:\Program Files (x86)\NSIS\makensis.exe` (compilación Unicode real).

Salida aislada: `dist/P1-32-packaging-20260828/`.

## Artefactos

El `release-manifest.json`, `checksums.txt` y los sidecars `.sha256` de la salida
son la fuente de hashes del build final. El portable contiene una sola raíz,
`GTFS Explorer Portable`, con `portable.flag`, ayuda, licencias, SBOM, MapLibre,
PMTiles y recursos Qt/WebEngine.

El manual `docs/USER_GUIDE.md` se incluye porque lo exige
`docs/HELP_PACKAGING_MANIFEST.json`; la ayuda integrada `index.json` permanece
dentro de los recursos de la aplicación.

## Pruebas ejecutadas

- Tests de packaging, licencias y ayuda: `24 passed`.
- Portable real: runtime smoke PASS y mapa/WebEngine gráfico PASS
  (`bridge_ready=True`, `route_blue_pixels=48`).
- Portable extraído en carpeta independiente: runtime smoke PASS; ejecutable,
  ayuda, manifest, `QtWebEngineProcess.exe` y recursos presentes.
- Installer real: NSIS compilado PASS; instalación silenciosa PASS; runtime del
  EXE instalado PASS.
- Metadata PE: ProductName `GTFS Explorer Desktop`, versión `0.1.0.0`,
  InternalName `GTFS Explorer`, OriginalFilename `GTFS Explorer.exe`, autor y
  copyright canónicos.
- Uninstall real PASS: EXE, recursos, registro y accesos directos eliminados;
  el sentinel de `Documents/GTFS Explorer/Projects` permaneció intacto.
- Reinstall/fresh install: PASS. No se ejecutó upgrade P1-33.
- Firma digital: unsigned; fuera del alcance de P1-32.
- SBOM: CycloneDX existente incluido; no se añadió infraestructura nueva.
- Screen reader: `PENDING`, no se certificó NVDA/JAWS/Narrator.

## Limitaciones y gates

La distribución portable no promete zero-footprint: settings, caché y mapas
gestionados siguen las rutas locales definidas por P1-24. OFFLINE no realiza
requests remotos; ONLINE depende de conectividad. El benchmark SMALL no se
convierte en gate de packaging y permanece `NOT VERIFIED` si vuelve a expirar.

No se han probado escenarios de upgrade, publicación, firma ni SmartScreen.

P1-33_READY = YES.
