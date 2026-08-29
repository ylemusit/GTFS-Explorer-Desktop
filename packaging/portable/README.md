# Portable standalone

Genera una carpeta Windows x64 autosuficiente y un ZIP para ejecutar sin una
instalación de Python. No es un ejecutable único: Qt WebEngine y sus recursos
deben permanecer junto a `GTFS Explorer.exe`.

Desde la raíz del repositorio:

```powershell
.\.venv\Scripts\python.exe .\tools\build_portable.py
```

El resultado queda fuera de Git en `dist/`:

- `GTFS-Explorer-Portable-<versión>-win-x64.zip`;
- su fichero `.sha256`;
- dentro del ZIP, `manifest.json` con el hash de cada fichero distribuido.

Para un build local aislado se pueden usar `--output-dir` y `--label`; la versión
del producto no cambia y el comportamiento por defecto sigue publicando en `dist/`:

```powershell
.\.venv\Scripts\python.exe .\tools\build_portable.py `
  --output-dir .\dist\regression\CTM-001-regression-01 `
  --label CTM-001-regression-01
```

El directorio aislado también contiene el hash y el manifiesto externo del ZIP.

El `pysidedeploy.spec` versionado es el contrato de módulos Qt y recursos.
El script usa una copia temporal porque `pyside6-deploy` reescribe su spec con
rutas absolutas. La prueba de VM limpia forma parte de T094.

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.
