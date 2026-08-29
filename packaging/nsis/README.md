# Instalador NSIS

`installer.nsi` es UTF-8 con BOM (`UTF8SIG`) y declara `Unicode true` antes de
cualquier compresión. La toolchain esperada es NSIS 3.x Unicode (3.12 en la
matriz de referencia); no se mantiene compatibilidad con el compilador ANSI
histórico. `makensis` no forma parte del entorno de esta tarea.

El instalador instala GTFS Explorer Desktop para el usuario actual en
`%LOCALAPPDATA%\Programs\GTFS Explorer`. No solicita privilegios de administrador,
crea accesos directos en Inicio y Escritorio y registra el desinstalador solo en
`HKCU`.

Los proyectos, ajustes, caché y logs pertenecen a `%LOCALAPPDATA%\GTFS Explorer`.
El desinstalador no toca esa ubicación. Las actualizaciones reemplazan únicamente
el directorio de instalación. No se registra la extensión genérica `.zip`.

Para generar el setup a partir del ZIP portable de T091, con NSIS 3 instalado y
`makensis` disponible en `PATH`:

```powershell
.\.venv\Scripts\python.exe .\tools\build_installer.py
```

El resultado se publica en `dist/` junto a un manifiesto y un SHA-256. El setup
no está firmado; Windows SmartScreen puede mostrar una advertencia hasta que se
firme una futura distribución.

La comprobación no compiladora `--check-makensis` informa `AVAILABLE / ...` o
`SKIPPED / TOOL_NOT_AVAILABLE`. La ausencia del binario no es un resultado de
compilación satisfactorio: el gate binario queda registrado como
`NSIS_BINARY_GATE = PENDING_P1_32`, que requiere construir `Setup.exe` con
`makensis` real, instalar, revisar textos y Properties, y desinstalar.

Para construir desde un portable etiquetado en un directorio aislado, se pueden
reutilizar los mismos parámetros sin alterar la versión efectiva:

```powershell
.\.venv\Scripts\python.exe .\tools\build_installer.py `
  --makensis 'C:\Program Files (x86)\NSIS\makensis.exe' `
  --output-dir .\dist\regression\CTM-001-regression-01 `
  --label CTM-001-regression-01
```

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.
