# Evidencia T094 — 2026-08-13

## Entorno

- VirtualBox 7.2.14, VM nueva `GTFS-T094-Clean`.
- Windows 11 Home x64 `10.0.26200.8037`, instalado desde una ISO detectada por VirtualBox como Windows 11 25H2 en español.
- ISO SHA-256: `f5495dfcea4294c7924420ad860f409623575436f85a8d0a66a6bd9a1c3433d6`.
- Cuenta de prueba `t094standard`, miembro de `Usuarios` y ausente de `Administradores`.
- NIC virtual con enlace desconectado; `ipconfig` confirmó `medios desconectados`.
- No se instaló Python, Git ni otra herramienta de desarrollo. Windows exponía únicamente el alias de Microsoft Store `WindowsApps\\python.exe`.

## Artefactos verificados dentro de la VM

| Archivo | Bytes | SHA-256 |
|---|---:|---|
| `GTFS-Explorer-Portable-0.1.0-win-x64.zip` | 135254516 | `5aed5b5de2b5580305bc91c04d2ff551ae86bdd40f422901fbd47fe85757f922` |
| `GTFS-Explorer-Setup-0.1.0-win-x64.exe` | 100044852 | `1efccc59214aa1334c3c346e2f832a2855c9486b24f60717e27e65e7f8d51391` |
| `valid_full.zip` | 1945 | `26050ad9703e3995f4e4c4e7756f61d2f6744b843cbeed93adaefab4b420a4b5` |

## Resultado P01

1. El ZIP se extrajo como usuario estándar en `C:\\Users\\t094standard\\T094\\P01`.
2. Se lanzó `GTFS Explorer.exe` mediante Guest Control; el proceso terminó.
3. Se repitió desde la sesión interactiva con `Win+R`; tampoco apareció la ventana.
4. El ejecutable creó `workspace\\logs\\gtfs-explorer.log` y registró una excepción no controlada durante `exec_module`.

Resultado: **FALLIDO, severidad alta**. No pudieron ejecutarse creación de proyecto, importación, validación, consultas, exportación, ayuda ni mapa.

## Archivos

- `P01-clean-standard-offline.png`: sesión estándar limpia con red desconectada.
- `P01-after-interactive-launch.png`: escritorio tras el lanzamiento interactivo, sin ventana de la aplicación.
- `P01-gtfs-explorer.log`: log creado por el portable durante la reproducción.

La instantánea `BASE-CLEAN-STANDARD` conserva el estado previo a copiar los artefactos. Los casos restantes se detuvieron según la regla de bloqueo grave de la matriz.
