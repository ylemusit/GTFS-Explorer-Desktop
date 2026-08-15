# Evidencia de corrección T094 — 2026-08-14

## Entorno

- VirtualBox 7.2.14, VM nueva `GTFS-T094-Clean-2`.
- Windows 11 Home x64 `10.0.26200.8037`, ISO SHA-256
  `f5495dfcea4294c7924420ad860f409623575436f85a8d0a66a6bd9a1c3433d6`.
- Cuenta `t094standard`, miembro únicamente de `Usuarios`.
- Snapshot apagado `BASE-CLEAN-STANDARD-OFFLINE`; enlace de NIC desconectado antes
  de iniciar la sesión de prueba.
- Sin Python, Git ni herramientas de desarrollo instaladas.

## Artefactos comprobados dentro de la VM

| Archivo | Bytes | SHA-256 |
|---|---:|---|
| `GTFS-Explorer-Portable-0.1.0-win-x64.zip` | 135278485 | `006d4131c8150113c5b034a1c3bc05b62017cb5c08cf9bb2d6ad3731dfcccfee` |
| `GTFS-Explorer-Setup-0.1.0-win-x64.exe` | 100046278 | `b5369c8839407455d10066e3631e5c5eb57c4d8cb8eeefd61e21e8010170fbe4` |
| `valid_full.zip` | 1945 | `26050ad9703e3995f4e4c4e7756f61d2f6744b843cbeed93adaefab4b420a4b5` |

## Resultados ejecutados

- **P01, stopper de arranque:** `--runtime-smoke` devolvió `0` desde una
  extracción local y la ventana principal se abrió realmente. El smoke carga
  DuckDB, ejecuta una consulta en memoria e importa `MainWindow`.
- **P02, ruta con espacios:** `--runtime-smoke` devolvió `0` desde
  `C:\Users\t094standard\T094\USB Simulado Acentos`.
- **I01, stopper de instalador:** instalación silenciosa por usuario, sin UAC;
  runtime smoke `0`, accesos directos de Escritorio e Inicio presentes y ventana
  principal abierta desde `%LOCALAPPDATA%\Programs\GTFS Explorer`.

## Alcance pendiente de la matriz

Esta ejecución confirma que los dos bloqueos técnicos encontrados —carga de
DuckDB en standalone y snapshot limpio inconsistente— están solucionados. No
declara completados los recorridos manuales de importación, validación,
consultas, exportaciones, ayuda, mapa, desinstalación/persistencia ni I03. I03
continúa sin setup N-1 verificable para la primera versión.
