# Cortador de turnos al bate

Parte un mp4 largo de una jornada de academia (cámara fija, ~3 h, una sola toma)
en un mp4 por turno al bate.

**Alcance:** entra un mp4, salen mp4 por turno, mismo formato, sin audio. Nada más.
Fuera del alcance: nombrado de ficheros, subida al portal, identificación de peloteros,
evaluación.

## Regla

El turno cambia cuando cambia la persona que está en el cajón de bateo. Con cámara fija
el cajón es un rectángulo fijo de la imagen, así que la segmentación es un problema de
presencia e identidad sobre un recorte pequeño.

## Etapas

| # | Etapa | Entra | Sale |
|---|-------|-------|------|
| 0 | Calibración (una vez por cámara) | 1 fotograma | ROI guardado |
| 1 | Muestreo de keyframes recortados al ROI | mp4 de 3 h | ~5.400 recortes |
| 2 | Presencia | recortes | ocupado / vacío |
| 3 | Identidad (apariencia del torso) | recortes ocupados | agrupación |
| 4 | Reglas y corte | segmentos | N ficheros mp4 |

## Uso

```
python -m cortador calibrar  jornada.mp4 --perfil perfiles/academia1.json
python -m cortador cortar    jornada.mp4 --perfil perfiles/academia1.json --salida salida/
python -m cortador analizar  jornada.mp4 --perfil perfiles/academia1.json   # sin exportar
```

## Estado

Fase 1 (motor por línea de comandos). Los detectores de presencia e identidad tienen
una implementación base con OpenCV puro; el diseño acordado contempla sustituirlas por
YOLOv8n y OSNet/CLIP cuando lleguen los dos vídeos reales del cliente.

## Entorno (Windows)

Python 3.12 y ffmpeg 9.0.1 se instalaron con winget. Si `ffmpeg` no aparece en el PATH
de una terminal ya abierta, ábrela de nuevo o apunta a los binarios:

```
set CORTADOR_FFMPEG=C:\Users\<usuario>\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build\bin\ffmpeg.exe
set CORTADOR_FFPROBE=...\ffprobe.exe
```

Preparar el entorno y pasar las pruebas:

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt pytest
.venv\Scripts\python.exe tools\make_fixture.py     # genera la jornada de prueba
.venv\Scripts\python.exe -m pytest
```

## Jornada sintética de prueba

`tools/make_fixture.py` genera un mp4 de 440 s con los cuatro casos límite del diseño
(turno normal, salir y volver antes de 25 s, relevo sin hueco, cruce de 8 s) y su verdad
de referencia en JSON. El motor la resuelve hoy con 5 turnos de 5, la fusión correcta y
el cruce descartado. No sustituye a las dos jornadas reales del cliente: sirve para que
las reglas no se rompan mientras llegan.
