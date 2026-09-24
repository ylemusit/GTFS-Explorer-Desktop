# Estado actual del producto

## Target version

`0.2.2` — hotfix GTFS-023 en `main`.

## Product status

Fuente preparada para el cierre final de release. Esquema de proyecto actual: 11;
cadena de migración: `8 → 9 → 10 → 11`; esquema de informe: `1.1.0`.

## PASS

- Original GTFS y tablas `gtfs_*` inmutables; edición por Working Copy,
  revisiones y ChangeSets (DEC-020).
- GTFS-021 y GTFS-022: CLOSED.
- GTFS-023: ACCEPTED; corrección de contratos enum y diagnóstico de importación.
- `V0.2.2_CANONICAL_GATE_FINAL_002`: 648 passed, 0 failed, 1 skip legítimo.
- Bizkaibus `run_004_gtfs023_candidate001`: importación completa, validación
  `VALID`, 0 detectadas, 0 persistidas y 0 omitidas; no requiere repetición.

## PARTIAL

- El build final, los smokes Portable/Setup, hashes, backup recuperable y
  publicación controlada pertenecen al cierre de `0.2.2`; firma, SmartScreen y
  revisión jurídica siguen siendo gates distintos.

## Open blockers

- Ninguno de producto conocido. No se declara publicación, firma ni
  certificación de Microsoft hasta completar sus gates correspondientes.

## Deferred

- La propagación avanzada de horarios queda fuera de `0.2.2`.

## Last verified

V0.2.2_CANONICAL_GATE_FINAL_002: PASS, exit code 0, 648 passed, 0 failed y
1 skip legítimo. GTFS-023-CANDIDATE-001 y Bizkaibus
`run_004_gtfs023_candidate001`: ACCEPTED.

## Next authorized phase

Cierre final controlado de `0.2.2`: commit limpio, build, aceptación,
recuperación y verificación de publicación según el descriptor autorizado.

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.
