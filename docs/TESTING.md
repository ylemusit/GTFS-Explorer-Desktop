# Testing

Las pruebas unitarias cubren dominio, contratos y transformaciones; las de
regresión protegen bugs corregidos; las de integración cubren DuckDB,
importación, exportación y migraciones; y las de UI/GUI cubren Qt, WebEngine y
los flujos del escritorio. Los fixtures permanentes son ficticios o están
autorizados y viven en `tests/fixtures/`.

La comprobación canónica es `pwsh -NoProfile -File .\tools\check.ps1`. Durante
el desarrollo se ejecutan checks focales. El gate integrado final registra por
separado el smoke de feed real, el smoke de paquete y la aceptación visual
nativa de Windows. Un smoke técnico no acredita por sí solo la aceptación
visual.

Los harnesses de una sola investigación, logs, capturas y resultados de una
ejecución no son tests permanentes: se conservan en Engineering o Artifacts.
