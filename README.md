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

# con los detectores pesados
python -m cortador cortar jornada.mp4 --perfil perfiles/academia1.json --salida salida/ \
    --detector yolo --identidad cnn
```

## Detectores

Las etapas 2 y 3 tienen dos implementaciones cada una, elegibles por línea de comandos:

| Etapa | Por defecto | La otra |
|---|---|---|
| 2 · presencia | diferencia con el fondo, OpenCV puro | `--detector yolo` · YOLOv8n |
| 3 · identidad | histograma HS del torso | `--identidad cnn` · ResNet-18 + histograma |

Las de por defecto no necesitan más que numpy y OpenCV. Las otras necesitan torch,
torchvision y ultralytics, unos 2,5 GB: `pip install -r requirements-cnn.txt`.

Sobre la jornada de prueba con personas reales, lo que marca la diferencia es
`--identidad cnn`: con el histograma salen 4 turnos de 5, porque dos peloteros vestidos
de forma parecida quedan a 0,32 y el umbral de fusión está en 0,35. `--detector yolo` no
cambia el resultado aquí, porque el fondo del fixture es perfectamente estable; se espera
que importe con material real, donde la luz gira a lo largo de la tarde.

El umbral de apariencia es el parámetro más delicado del motor y no se fija a ojo:

```
python tools/calibrar_umbral.py jornada.mp4 --perfil perfil.json --identidad cnn
```

imprime, tramo a tramo, el hueco y la distancia al anterior, y dice qué haría la regla.
Con eso se ve dónde cae la frontera en ese material concreto y se ajusta con
`--umbral-cambio`.

## Estado

Fase 1 (motor por línea de comandos), 21 tests en verde. Pendiente de las dos jornadas
reales del cliente para volver a calibrar contra material de verdad.

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
de referencia en JSON. En dos versiones:

```
python tools/make_fixture.py              # peloteros = rectángulos de color
python tools/make_fixture.py --personas   # peloteros = personas reales recortadas
```

La segunda es la única que dice algo sobre YOLO: sobre rectángulos de colores no detecta
a nadie, y con razón. Resultado actual, 5 turnos de 5:

| Fixture | Detector / identidad | Turnos |
|---|---|---|
| formas | color / color | 5 ✓ |
| personas | color / color | 4 ✗ · fusiona P-01 con P-02 |
| personas | color / cnn | 5 ✓ |
| personas | yolo / cnn | 5 ✓ |

No sustituye a las dos jornadas reales del cliente: sirve para que las reglas no se
rompan mientras llegan, y para tener contra qué comparar cuando lleguen.
