# Instalador NSIS

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

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.
