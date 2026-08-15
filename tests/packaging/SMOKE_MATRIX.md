# T094 — Matriz de smoke en Windows limpio

Válida solo en VM/Sandbox recién creada, sin herramientas de desarrollo ni GTFS Explorer previo. Iniciar sesión con usuario estándar, copiar los artefactos y desconectar la red antes de abrir la aplicación.

## Artefactos fijados

| Artefacto | SHA-256 |
|---|---|
| `GTFS-Explorer-Portable-0.1.0-win-x64.zip` | `6843fbf5bb1d30106fd239597fda9e7651225bd28dccf07972d9d57515a4fb7d` |
| `GTFS-Explorer-Setup-0.1.0-win-x64.exe` | `4a5d441395263ce5b6fca3dd3e9cf104a4dfa2fa43441d8b6d31c3e7e1d13dc9` |

Confirmar con `Get-FileHash -Algorithm SHA256` y comprobar que el manifiesto del setup contiene ambos hashes.

| ID | Entorno/artefacto | Pasos críticos | Resultado | Evidencia requerida |
|---|---|---|---|---|
| P01 | Windows limpio offline, estándar, ZIP local | Abrir, crear proyecto, importar fixture, validar, consultar, exportar JSON/CSV, abrir ayuda y mapa de un viaje. | **PASS:** recorrido funcional completo confirmado por el responsable del proyecto con el portable fijado. El mapa PMTiles, la ruta, las paradas y el popup se visualizaron; JSON, CSV y ayuda local funcionaron sin conexión. | Captura manual del mapa y confirmación del responsable el 2026-08-15; hash fijado en esta matriz. |
| P02 | Igual, ZIP extraído en USB o ruta con espacios/acentos | Repetir arranque, importación y exportación mínima. | **PASS:** recorrido confirmado por el responsable del proyecto con el portable fijado. | Confirmación manual del responsable el 2026-08-15; hash fijado en esta matriz. |
| I01 | Windows limpio offline, estándar, setup | Instalar sin elevación; Inicio/Escritorio; repetir P01; comprobar programa en `%LOCALAPPDATA%\\Programs\\GTFS Explorer` y workspace fuera de ella. | **PASS:** instalación y recorrido funcional confirmados por el responsable del proyecto con el setup fijado. | Confirmación manual del responsable el 2026-08-15; hash fijado en esta matriz. |
| I02 | Igual, perfil/ruta Unicode | Repetir instalación, proyecto y desinstalación; el workspace debe permanecer. | **PASS:** instalación, proyecto, desinstalación y conservación del workspace confirmados por el responsable del proyecto. | Confirmación manual del responsable el 2026-08-15; hash fijado en esta matriz. |
| I03 | Upgrade real desde N-1, offline, estándar | Instalar N-1, crear proyecto, actualizar a 0.1.0 y abrirlo. | **SKIP JUSTIFICADO:** 0.1.0 es la primera versión instalable y no existe un setup N-1 verificable. | Causa aceptada para esta primera release; deberá ejecutarse desde la siguiente versión instalable. |

## Ejecución 2026-08-13

- VM nueva: `GTFS-T094-Clean`, Windows 11 Home x64, versión `10.0.26200.8037`, sin Python ni Git instalados; el alias de Microsoft Store para `python.exe` no es un runtime.
- Usuario: `t094standard`, miembro únicamente de `Usuarios`.
- Offline: enlace de la NIC virtual desconectado antes de iniciar la sesión estándar; `ipconfig` informó `medios desconectados`.
- Portable recibido en el invitado: `5aed5b5de2b5580305bc91c04d2ff551ae86bdd40f422901fbd47fe85757f922`.
- Setup recibido en el invitado: `1efccc59214aa1334c3c346e2f832a2855c9486b24f60717e27e65e7f8d51391`.
- Fixture ficticio `valid_full.zip`: `26050ad9703e3995f4e4c4e7756f61d2f6744b843cbeed93adaefab4b420a4b5`.
- Reproducción P01: lanzamiento mediante Guest Control y lanzamiento interactivo con `Win+R`; ambos terminaron sin ventana. El log portable registró `UNHANDLED_EXCEPTION error=<built-in method exec_module ...> returned NULL without setting an exception`.
- Decisión: aplicar la regla de parada por bloqueo grave; no continuar con importación, exportación ni instalador hasta corregir y regenerar ambos artefactos.

## Reejecución de stoppers 2026-08-14

- VM nueva `GTFS-T094-Clean-2`, creada desde la misma ISO después de detectar que
  la instantánea anterior se había capturado durante la instalación de Windows.
- Snapshot válido tomado con la VM apagada: `BASE-CLEAN-STANDARD-OFFLINE`.
- Portable: `006d4131c8150113c5b034a1c3bc05b62017cb5c08cf9bb2d6ad3731dfcccfee`.
- Setup: `b5369c8839407455d10066e3631e5c5eb57c4d8cb8eeefd61e21e8010170fbe4`.
- P01, P02 e I01 superan el runtime smoke que carga DuckDB y `MainWindow`; P01 e
  I01 además muestran la ventana principal real.
- Los stoppers técnicos quedan corregidos, pero T094 permanece abierta hasta
  completar los recorridos funcionales restantes o registrar sus skips.

## Corrección del mapa en blanco 2026-08-14

- El recorrido manual P01 creó el proyecto, importó `valid_full.zip` y validó el
  feed, pero el mapa no representó `SH1` ni `S1` sobre el fondo neutro.
- La consola real de Qt WebEngine mostró que JavaScript buscaba
  `commandAvailable`, mientras Qt exponía la señal como `command_available`.
  El fallo impedía recibir `mapReady` y enviar las capas al WebEngine.
- Se corrigió el contrato, se añadieron regresiones para el nombre Qt real y la
  sincronización de recursos, y se regeneraron los recursos web.
- La revisión visual posterior confirmó un segundo defecto: el `stretch` del
  contenedor absorbía la altura y dejaba el WebEngine en una franja. Se eliminó
  ese reparto, el explorador y el mapa reciben expansión vertical, el lienzo
  exige 240 px mínimos y MapLibre recalcula su tamaño antes de ajustar capas.
- Ruff y mypy pasaron. La suite obtuvo 210/211 en la ejecución completa; el único
  fallo fue el spike gráfico WebEngine y pasó al repetirlo con `map_loaded=true`,
  ruta/parada renderizadas y sin errores de consola. Las 20 pruebas específicas
  del mapa/layout pasaron. El build portable superó su runtime smoke y
  portable/setup se reconstruyeron con los hashes fijados actuales.
- Los hashes anteriores quedan como evidencia histórica y no sirven para cerrar
  ningún caso de la matriz actual. Falta repetir la prueba visual real.

No cerrar T094 mientras haya un caso pendiente o fallido. Bloqueos graves: no arranque, elevación, pérdida de proyecto, dependencia de red, hash distinto o fallo de import/export/mapa/ayuda.

## Cierre manual 2026-08-15

- El responsable del proyecto confirmó P01, P02, I01 e I02 con los artefactos
  fijados al inicio de la matriz.
- La última comprobación de P01 confirmó exportación JSON, exportación CSV fiel y
  apertura/búsqueda de la ayuda local sin conexión.
- I03 queda omitido con causa verificable: no existe una versión instalable N-1
  anterior a 0.1.0. La prueba de upgrade pasa a ser obligatoria en la próxima
  versión que disponga de dicho artefacto.
- Resultado final: cuatro casos PASS, un SKIP justificado y cero bloqueadores de
  severidad alta. T094 puede cerrarse.

## Corrección de sincronización MapLibre/QWebChannel 2026-08-15

- MapLibre podía completar el evento `load` antes de que QWebChannel publicase
  `GTFSExplorerMapBridge`. En ese orden no se emitía `mapReady` y Qt no enviaba
  las capas GeoJSON, aunque el lienzo ya tuviera altura suficiente.
- El mapa ahora espera explícitamente el evento local de bridge disponible antes
  de informar `mapReady`; los eventos de viewport y click también se ignoran de
  forma segura hasta entonces.
- Se añadieron regresiones de contrato, se regeneraron los recursos web offline
  y los artefactos de esta tabla. Falta la comprobación visual manual de `SH1` y
  `S1` en P01 e I01.

## Corrección de recursos y smoke gráfico del binario 2026-08-15

- La inspección remota del portable defectuoso demostró que el HTML intentaba
  cargar `web/map/qt_resources` un nivel por encima de `GTFS Explorer Portable`.
  Nuitka no garantizaba `sys.frozen`, por lo que el resolver tomaba erróneamente
  la ruta del árbol fuente aunque los recursos sí estuvieran incluidos.
- El mapa localiza ahora primero los recursos junto a `sys.executable` y conserva
  la ruta del repositorio solo para desarrollo. El runtime smoke comprueba además
  que existen los cuatro recursos web obligatorios.
- El build ejecuta un smoke gráfico desde el propio EXE compilado: abre WebEngine,
  inyecta una línea y una parada sintéticas, captura el lienzo y falla si el bridge
  no está listo o no aparecen al menos 20 píxeles de ruta.
- El ZIP final y el payload extraído del setup, probados por separado y sin usar
  Python del sistema, informaron `bridge_ready=true`, cero errores y 1.134 píxeles
  de ruta en 878×240. Ambos contienen el mismo `GTFS Explorer.exe` con SHA-256
  `4165926d5ba022f4f71213be8f16c07d9964226ac58b88cc283c484ccb46ebd9`.
- `7z test` verificó los 153 archivos de cada artefacto. Esta evidencia automática
  evita volver a publicar un binario con el mapa vacío, pero P01 e I01 siguen
  necesitando la confirmación manual del recorrido con `valid_full.zip`.
- Una reproducción posterior confirmó que el primer `replace` aún devolvía
  `false` porque `isStyleLoaded()` no era verdadero dentro del callback `load`.
  El payload más reciente queda ahora en cola y se aplica automáticamente en
  `idle`. La captura automatizada del widget real muestra la línea `SH1` y la
  parada `S1`; los hashes de la tabla corresponden a esta corrección.

## Ejemplo GoLines y mapa regional real 2026-08-15

- `examples/golines-asturias/generated/golines-asturias-demo.gtfs.zip` contiene
  6 rutas, 12 viajes, 56 paradas, 129 stop times y 7.050 puntos de shape. La
  importación real terminó `READY` con cero errores.
- El mapa de Asturias se empaquetó bajo el contrato v1 con PMTiles verificado,
  hashes, bbox, licencia y atribución. Los horarios derivados de CENTROBUS se
  limitan a evaluación local por falta de permiso específico de redistribución.
- La prueba conjunta descubrió y corrigió CORS entre la página `file://` y el
  loopback, además de restaurar las capas GTFS después de `map.setStyle()`.
- El widget real con OG1 produjo una captura con 2.664 píxeles de ruta y 129.181
  píxeles cartográficos. El EXE extraído del ZIP y el extraído del setup pasaron
  por separado con 1.319 píxeles de ruta y 154.631 de mapa, bridge y paquete
  activos, y cero errores. Ambos EXE son idénticos, SHA-256
  `0b43858363980a3fd5fa56c77e9088a7effdb93a50d9b5c08c14c4874ea99e25`.
- `7z test` verificó los 153 archivos de cada artefacto. Los hashes fijados al
  inicio de esta matriz corresponden a este build.
