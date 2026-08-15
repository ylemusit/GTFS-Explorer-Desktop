# T092 — Pruebas manuales del instalador NSIS

Ejecutar en una VM Windows limpia como usuario estándar, offline después de
copiar el setup. Registrar la versión exacta y los SHA-256 de setup y manifiesto.

| Caso | Acción | Resultado esperado |
|---|---|---|
| Instalación limpia | Ejecutar el setup y abrir la aplicación desde Inicio y Escritorio. | No pide elevación; instala en `%LOCALAPPDATA%\Programs\GTFS Explorer`; ambos accesos abren la aplicación. |
| Workspace separado | Crear/importar un proyecto y cerrar. | Los datos se escriben en `%LOCALAPPDATA%\GTFS Explorer`, no en el directorio de instalación. |
| Upgrade N-1 | Instalar la versión previa, crear un proyecto y ejecutar el setup de la versión actual. | La aplicación se actualiza y el proyecto permanece accesible. |
| Desinstalación | Desinstalar desde Aplicaciones instaladas. | Desaparecen programa, accesos y entrada de desinstalación; `%LOCALAPPDATA%\GTFS Explorer` permanece intacto. |
| Ruta Unicode | Instalar con un perfil de usuario/ruta que contenga `ñ` o caracteres acentuados. | Instalación, arranque, proyecto y desinstalación funcionan. |

No declarar el setup apto para release hasta completar estos casos en la VM de
T094. La ausencia de firma puede activar SmartScreen.
