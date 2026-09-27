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

El descriptor declara cada nivel como `required`, `not_required` o `conditional`:
`FOCAL`, `INTEGRATED_GATE`, `PACKAGING`, `SECURITY`, `VISUAL` y
`EXTERNAL_ACCEPTANCE`. El resultado de cada nivel se registra aparte del estado
de ejecución y del estado de aceptación.

Para cada verificación `conditional`, registrar la condición que controla su
aplicabilidad, si se cumplió (`true`, `false` o `unknown` si no pudo determinarse)
y el resultado: `PASS`, `FAIL`, `NOT_RUN`, `NOT_APPLICABLE` o `BLOCKED`.
Condición falsa implica `NOT_APPLICABLE`; condición cumplida sin ejecución,
`NOT_RUN` o `BLOCKED` según la causa; condición indeterminada, `BLOCKED`.
`PASS` exige que la verificación se haya ejecutado satisfactoriamente; una
verificación no ejecutada nunca es `PASS`.

`EXTERNAL_ACCEPTANCE` es un nivel de verificación/aceptación. El actor o sistema
externo que acepta y el artefacto/evidencia que lo acredita se describen aparte
en `EXTERNAL_ACCEPTANCE_PROVIDER` del contrato. Declarar el nivel no acredita
que se haya obtenido esa aceptación.

Los harnesses de una sola investigación, logs, capturas y resultados de una
ejecución no son tests permanentes: se conservan en Engineering o Artifacts.
