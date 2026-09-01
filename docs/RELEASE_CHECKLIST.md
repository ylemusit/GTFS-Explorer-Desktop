# Checklist de release candidate

Versión candidata: `0.1.0-rc2`
Fecha: 2026-09-01
Estado: **RC local en preparación; no autorizada para publicación o distribución.**

## Fase 3 — Freeze + RC2

- [x] `v0.1.0-rc1` preservado sin modificar.
- [x] E2E: 11 passed.
- [x] Full suite: 526 passed.
- [x] `tools/check.ps1`, Ruff, mypy y `git diff --check`: PASS.
- [x] Portable RC2, runtime smoke y mapa: PASS.
- [x] Installed RC2, upgrade/uninstall y package smoke: PASS.
- [ ] CTM empaquetado y round-trip Mini-GTFS nativo: no reclamar hasta obtener evidencia fresca.
- [x] Hashes y manifests RC2: PASS.
- [ ] Tag anotado: se creará solo tras incorporar el estado final congelado.

### Artefactos RC2

- Portable: `dist/GTFS-Explorer-Portable-0.1.0-rc2-win-x64.zip` —
  `b99060d6201fe4459292ecd4bf1b0b72a92140500fbacbe4597af71f01ca79bd`.
- Setup: `dist/GTFS-Explorer-Setup-0.1.0-rc2-win-x64.exe` —
  `314545b35d7c965f2a1e3865c5801d427c6fa1b064f9fd86cc04f823ca60d20f`.

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

## Gates de autorización pendientes

- [ ] Revisión jurídica de LGPL/Qt WebEngine para la forma concreta de
  distribución.
- [ ] Decisión de licencia propia y estrategia comercial.
- [ ] Autorización expresa de Yeison para publicar o distribuir.

## Revalidación reproducible

```powershell
.\.venv\Scripts\python.exe tools\prepare_release_candidate.py --verify-only
.\.venv\Scripts\python.exe tools\prepare_release_candidate.py --label rc1
Get-FileHash -Algorithm SHA256 .\dist\GTFS-Explorer-Portable-0.1.0-win-x64.zip
Get-FileHash -Algorithm SHA256 .\dist\GTFS-Explorer-Setup-0.1.0-win-x64.exe
```

El segundo comando no recompila ni mueve binarios: solo vuelve a comprobar los
artefactos y regenera metadatos locales de la RC.

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.
