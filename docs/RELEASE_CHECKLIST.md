# Checklist de release candidate

Versión candidata: `0.1.0-rc1`
Fecha: 2026-08-15
Estado: **RC local preparada; no autorizada para publicación o distribución.**

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
