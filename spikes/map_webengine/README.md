# T070 — Spike Qt WebEngine, MapLibre y PMTiles

El intento inicial `spike.py` conserva la evidencia del NO-GO del scheme
handler: `QWebEngineUrlRequestJob` no puede emitir HTTP 206. La solución
aceptada está en `loopback_spike.py`.

Preparar el bundle reproducible:

```powershell
Set-Location .\spikes\map_webengine\web
npm ci
npm run build
Set-Location ..\..\..
```

Ejecutar desde la raíz del repositorio:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe .\spikes\map_webengine\loopback_spike.py
```

El prototipo está aislado de `src/`. Sirve únicamente assets cerrados y un
PMTiles v3 sintético desde `127.0.0.1`, con puerto/token efímeros, validación
`Host`, CSP y monitor de red. MapLibre renderiza una línea y una parada;
QWebChannel realiza ida/vuelta y PMTiles solicita rangos HTTP reales.

Prueba focalizada:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_map_loopback_spike.py -q
```

La evidencia standalone verificada en Windows 11 x64 fue 2,175 ms para el
arranque+smoke y 309.92 MiB antes de optimización. El render standalone debe
probarse en la sesión gráfica normal: el plugin Qt `offscreen` pierde el
contexto D3D en el binario. DEC-016 registra la decisión GO y sus límites.
