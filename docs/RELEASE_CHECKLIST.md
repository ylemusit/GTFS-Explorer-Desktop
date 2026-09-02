# Checklist de release estable

Versión: `0.1.0`
Fecha: 2026-09-03
Estado: **release estable local listo; no publicado.**

## Stable 0.1.0

- [x] `v0.1.0-rc1` preservado sin modificar.
- [x] `v0.1.0-rc2` preservado sin modificar.
- [x] E2E: 11 passed.
- [x] Full suite: 527 passed.
- [x] `tools/check.ps1`, Ruff, mypy y `git diff --check`: PASS.
- [x] Portable estable, runtime smoke y mapa: PASS.
- [x] Installed estable, upgrade/uninstall y package smoke: PASS.
- [x] Aceptación manual corta de 10–15 minutos: PASS.
- [x] Hashes y manifests estables confirmados.
- [x] Tag anotado `v0.1.0` creado tras aceptación manual.

### Artefactos estables

- Portable: `GTFS-Explorer-Portable-0.1.0-win-x64.zip` —
  `3ec30816ce532c1d97f9530af3c08744b018d26cae9b09b4ed8f25116775984f`.
- Setup: `GTFS-Explorer-Setup-0.1.0-win-x64.exe` —
  `dbee78348284e1d9a3c767f48256063a93a1c4831ba5d8637cfa9d435a5a3dec`.

## Gates técnicos

- [x] Dependencias T080--T095 completadas en `docs/TASK_STATUS.json`.
- [x] Portable Windows x64 existente y hash lateral coincidente.
- [x] Instalador por usuario existente, con manifiesto y hash lateral coincidentes.
- [x] ZIP portable íntegro, con ejecutable, recursos de mapa, licencias, avisos y
  SBOM incluidos.
- [x] Matriz T094: P01, P02, I01 e I02 aprobados offline en Windows limpio.
- [x] I03 documentado como skip justificado: `0.1.0` no tiene instalador N-1.
- [x] Rendimiento: perfil pequeño publicado; RNF-006 no se declara soportado.
- [x] Sin bloqueadores conocidos de severidad crítica o alta en T094.

## Entregables RC

- [x] `CHANGELOG.md` con alcance, límites y avisos.
- [x] `dist/GTFS-Explorer-0.1.0-rc1/SHA256SUMS.txt`.
- [x] `dist/GTFS-Explorer-0.1.0-rc1/release-manifest.json`.
- [x] `THIRD_PARTY_NOTICES.html` y `SBOM.cdx.json` extraídos de la RC para su
  inspección junto al manifiesto.

## Aceptación manual corta

- [x] Instalar, abrir y navegar por las vistas principales.
- [x] Crear proyecto, importar feed pequeño o Mini-GTFS y validar.
- [x] Explorar mapa; probar DOCKED/DETACHED y maximizar/restaurar.
- [x] Exportar y reimportar Mini-GTFS.
- [x] Abrir README/guía y desinstalar.

## Gates de autorización pendientes

- [ ] Revisión jurídica de LGPL/Qt WebEngine para la forma concreta de
  distribución.
- [ ] Decisión de licencia propia y estrategia comercial.
- [ ] Autorización expresa de Yeison para publicar o distribuir.

## Revalidación reproducible

```powershell
Get-FileHash -Algorithm SHA256 .\dist\GTFS-Explorer-Portable-0.1.0-win-x64.zip
Get-FileHash -Algorithm SHA256 .\dist\GTFS-Explorer-Setup-0.1.0-win-x64.exe
```

Estos comandos solo comprueban los artefactos; no recompilan ni mueven binarios.

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.
