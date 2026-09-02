# P1-32 historical release fixture

This fixture is the metadata-only copy of the original local release manifest:
`GTFS Explorer Artifacts/acceptance-builds/P1-32-packaging-20260828/release-manifest.json`.

Purpose: keep product tests reproducible without restoring historical binaries to
`Product/dist`. It records the artifact name, byte count, SHA-256, packaging
type and release metadata required by the P1-33 upgrade compatibility contract.

The original artifacts remain in the artifact store:

- `GTFS-Explorer-Portable-0.1.0-P1-32-packaging-20260828-win-x64.zip`
  - SHA-256: `8450d974df386ff6d1b1d852febbf9bb78e031493c5246be5e44e3d46232f050`
- `GTFS-Explorer-Setup-0.1.0-P1-32-packaging-20260828-win-x64.exe`
  - SHA-256: `54297c2695327697a6e1091bf36b42f2f34ef588bf8b93a8c027eb9ca71735ec`

The binary checksum test is intentionally artifact-dependent. Run it with
`GTFS_EXPLORER_ARTIFACT_STORE` set to the root of `GTFS Explorer Artifacts`; it
then resolves `acceptance-builds/P1-32-packaging-20260828` explicitly.
