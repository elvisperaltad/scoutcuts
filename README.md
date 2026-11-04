# Cortador de turnos al bate

## Distribución portátil y evidencia QA

La entrega vigente, el checksum, las instrucciones para el probador y la lista de datos
recopilados están consolidados en [`ENTREGA_QA.md`](ENTREGA_QA.md).
El servidor designado para usuarios, licencias y descargas, junto con su aislamiento y
plan de implementación, está documentado en [`SERVIDOR_CONTROL.md`](SERVIDOR_CONTROL.md).
Los resultados y conclusiones acumuladas de las pruebas externas están en
[`ANALISIS_QA.md`](ANALISIS_QA.md).
La decisión sobre el uso desde teléfonos y tabletas, con los tiempos medidos que la
sustentan, está en [`ACCESO_MOVIL.md`](ACCESO_MOVIL.md).
El relevo exacto para continuar la API y el despliegue sin perder contexto está en
[`CONTINUAR_SERVIDOR.md`](CONTINUAR_SERVIDOR.md).
La ubicación y reglas del repositorio editable para el Claude del QA están en
[`DESARROLLO_REMOTO.md`](DESARROLLO_REMOTO.md).
El acceso root completo para un segundo desarrollador de confianza, con GitHub
como fuente de verdad del código, está en [`ACCESO_DESARROLLADOR.md`](ACCESO_DESARROLLADOR.md).

El proyecto tiene una distribución Windows PyInstaller, pero su EXE sin firma fue bloqueado
por la política Code Integrity empresarial. Como alternativa se implementó un builder que
empaqueta el `pythonw.exe` embeddable oficial firmado: el QA extrae el ZIP completo y abre
`INICIAR_CORTADOR.bat`. Cada procesamiento conserva localmente
en `DatosQA` un JSON de corrida, el log y copias depuradas de las decisiones. No copia
videos ni resultados, y no sube nada. La GUI crea un ZIP limitado a esa evidencia.

Builder alternativo: ejecutar `python tools/build_portable_runtime.py`; acepta
`CORTADOR_PYTHON_EMBED_ZIP` para reutilizar el ZIP embeddable oficial ya descargado.
FFmpeg/FFprobe se buscan por `CORTADOR_FFMPEG`/`CORTADOR_FFPROBE` o `PATH`. Genera
`dist/CortadorTurnosQA-Portable/`, ZIP y checksum SHA-256 sin borrar los artefactos de
PyInstaller. La edición real se construyó, pasó su diagnóstico de Tk/NumPy/OpenCV/FFmpeg,
se extrajo desde el ZIP en otra carpeta y abrió correctamente mediante el runtime oficial
firmado. La validación final pendiente es la corrida del QA en otra computadora.

Parte un mp4 largo de una jornada de academia (cámara fija, ~3 h, una sola toma)
en un mp4 por turno al bate.

**Alcance:** entra un mp4, salen mp4 por turno, mismo formato, sin audio. Y, dentro de
cada turno, un segundo pase que quita los tiempos muertos y deja solo los swings que
valen. Fuera del alcance: nombrado de ficheros, subida al portal, identificación de
peloteros, evaluación.

**Contexto operativo confirmado:** el scout graba una sesión completa y después extrae
aproximadamente 10–20 turnos para crear el vídeo nuevo. En una jornada hay muchas
personas que evaluar. Este producto evalúa y recorta al **bateador**; el lanzador no
siempre aparece y sus vídeos pertenecen a otro flujo, por lo que nunca debe usarse como
señal necesaria para este sistema.

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
| 5 | Candidatos de swing | un turno | ~20 instantes con actividad |
| 6 | Marcado y compactado | candidatos | el turno sin tiempo muerto |
| — | Medida contra el montaje del scout | par (crudo, montaje) | precisión / cobertura |

## Uso

### Aplicación de escritorio (Windows)

Para una persona no técnica, haz doble clic en `iniciar_app.bat`. También se puede abrir
desde una terminal:

```
.venv\Scripts\python.exe -m cortador app
```

La ventana pide solamente la **Carpeta del jugador**. Se puede pegar la ruta o elegirla
con **Examinar** y luego pulsar una sola vez **Procesar carpeta**. La aplicación encuentra
videos MOV, MP4, M4V y AVI, procesa primero cualquier decisión existente y guarda los
montajes en la subcarpeta `Resultados`. El registro informa cada archivo y un resumen de
encontrados, listos, generados, pendientes y errores.

Solo puede correr un trabajo a la vez. Un error en un video queda informado y no impide
intentar los siguientes. Para un bateo nuevo, la app compara la resolución real con las
configuraciones de cámara internas. Si hay exactamente una compatible, detecta candidatos,
guarda las marcas junto al video, abre la revisión (`V` conserva, `N` descarta y `Q`
termina) y genera `Resultados/<nombre>_bateo.mp4` si quedó alguna jugada válida. El scout
no selecciona configuraciones ni JSON. Cero o varias configuraciones compatibles, o una
revisión sin jugadas válidas, dejan el video pendiente. Un sidecar defensivo válido nunca
se reclasifica automáticamente como bateo.

Los comandos suponen el paquete instalado en el entorno (ver **Entorno**) y el entorno
activado con `.venv\Scripts\activate`; así existe el comando `cortador`. Sin activarlo,
`.venv\Scripts\cortador.exe` o `.venv\Scripts\python.exe -m cortador` hacen lo mismo.

La forma recomendada para una persona no técnica es el agente local:

```
cortador agente jornada.mp4 --perfil perfiles/academia1.json --trabajo trabajo-jornada
```

Ese único comando analiza y corta la jornada, detecta candidatos dentro de cada turno,
abre la revisión humana cuando hace falta y compacta únicamente las marcas válidas. Se
puede cerrar durante la revisión y ejecutar exactamente el mismo comando para reanudar:
salir con `Q`/ESC, o pulsar `G`, guarda las marcas; cerrar con Ctrl+C puede perder lo
marcado desde el último guardado. El avance queda en `trabajo-jornada/estado-agente.json`;
los turnos, cuadernos y resultados quedan en subcarpetas de la misma carpeta.

Para automatización o diagnóstico sin ventanas:

```
cortador agente jornada.mp4 --perfil perfiles/academia1.json --trabajo trabajo-jornada --no-interactivo
```

El modo no interactivo detecta los candidatos de todos los turnos, compacta los que ya
tienen todas sus marcas decididas y se detiene cuando la validez de algún swing necesita
una persona. Una ejecución posterior sin `--no-interactivo` abre el marcado. El comando
termina con código 0 si la jornada quedó completa, 2 si espera revisión humana y 1 ante
un error.

Reanudar exige los mismos parámetros (`--detector`, `--identidad`, los de segmentación,
`--sigmas`, `--antes`, `--despues`, `--separacion`) y la carpeta de trabajo en su sitio.
El estado o un cuaderno corruptos, de una versión desconocida, de otro video, de otro
perfil, con otros parámetros o de una carpeta movida se rechazan sin sobrescribirlos. Si
una jornada completada pierde un compacto o se edita un cuaderno, el mismo comando rehace
solo esos turnos, sin volver a cortar la jornada; si la edición deja marcas pendientes,
vuelve a pedir revisión.

El agente es un orquestador Python local: **no usa APIs de IA, servicios externos ni
nuevas dependencias**, y no intenta inferir si hubo pelota.

Los comandos por etapa siguen disponibles:

```
cortador calibrar  jornada.mp4 --perfil perfiles/academia1.json
cortador cortar    jornada.mp4 --perfil perfiles/academia1.json --salida salida/
cortador analizar  jornada.mp4 --perfil perfiles/academia1.json   # sin exportar

# dentro de un turno ya cortado: quitar el tiempo muerto
cortador eventos   turno_01.mp4 --perfil perfiles/academia1.json
cortador marcar    turno_01.mp4 --perfil perfiles/academia1.json
cortador compactar turno_01.mp4 --salida turno_01_compacto.mp4

# defensa: seis repeticiones elegidas y revisadas por una persona
cortador defensa defensa.mp4 --marcas defensa.defensa.json --salida defensa_6.mp4

# con los detectores pesados
cortador cortar jornada.mp4 --perfil perfiles/academia1.json --salida salida/ --detector yolo --identidad cnn
```

## Flujo de defensa

Defensa es un flujo distinto al bateo. No se detectan automáticamente ni la jugada,
ni la pelota, ni su dirección: una persona revisa el video y prepara un manifiesto JSON
v1. El entregable contiene exactamente seis repeticiones completas: dos `adelante`, dos
`derecha` y dos `izquierda`, conservadas en orden cronológico.

El esquema es:

```json
{
  "version": 1,
  "video": "defensa.mp4",
  "repeticiones": [
    {
      "categoria": "adelante",
      "inicio": 7.8,
      "tiro": 14.2,
      "estado": "completa"
    }
  ]
}
```

`inicio` marca el comienzo de la preparación revisada y `tiro` el final de la acción.
La exportación añade por defecto 2,0 s antes de `inicio` y 0,3 s después de `tiro`; el
inicio nunca baja de cero. Las repeticiones `incompleta` quedan fuera. Si hay más de dos
completas en una categoría, el manifiesto debe resolver la elección marcando exactamente
dos con `"seleccionada": true`; el programa no elige silenciosamente.

Los márgenes pueden ajustarse sin cambiar las marcas humanas:

```
cortador defensa defensa.mp4 --marcas defensa.defensa.json --salida defensa_6.mp4 \
  --antes-extra 2.0 --despues-tiro 0.3
```

El nombre guardado en `video` debe corresponder al archivo procesado. Categorías,
estados, tiempos, versión y balance inválidos se rechazan antes de llamar a ffmpeg.

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

## Qué swing vale

Un swing cuenta **solo si le lanzaron una pelota**. Los de calentamiento, no.

Ese criterio hoy **no se detecta solo**, y no por falta de detector. Sobre el primer
material recibido —dos vídeos pasados por WhatsApp y por InShot— se probaron cuatro vías
y ninguna separa los swings que el cliente conservó de los que descartó:

| Vía | Resultado |
|---|---|
| Blobs pequeños en movimiento | 2037 de 2127 fotogramas dan candidato |
| Trayectoria balística de 3 puntos | 545 fotogramas, sin separación |
| Actividad del lanzador como proxy | 29 picos, no se alinean |
| Transitorio del golpe en el audio | la pista llega muda (pico 0,0) |

La razón es medible: a 1024×576 la pelota ocupa ~6 px en la zona de vuelo, el vídeo va a
915 kbps y el códec la borra, la malla de la jaula se interpone y el lanzador queda
detrás del bateador. Antes de intentarlo sobre material nuevo:

```
python tools/verificar_material.py jornada.mp4
```

comprueba resolución, bitrate, fps, keyframes y **si el audio trae señal**, y dice si
sirve. El golpe del bate es probablemente la vía más sólida —en una jaula la pelota
siempre golpea algo y un swing en vacío no suena— pero hace falta una pista real.

Mientras tanto lo marca una persona. El cuaderno de marcas no es solo un paso para
exportar: es el material etiquetado con el que después se ajustará el detector, y por
eso guarda también la fuerza del pico y el motivo.

## Cuánto se parece a lo que hace el scout

El scout entrega el mismo turno dos veces: el crudo y el montaje que él hizo. Ese par es
la verdad de referencia, y sale de él sin marcar nada a mano:

```
python tools/alinear.py crudo.mp4 montaje.mp4 --salida fixtures/referencia_turno1.json
python tools/evaluar.py turno.marcas.json    fixtures/referencia_turno1.json
```

`alinear.py` compara miniaturas normalizadas de cada fotograma —el producto escalar de
dos firmas normalizadas *es* su correlación, así que los dos vídeos se cruzan en un solo
`matmul`— y devuelve los tramos del crudo que sobrevivieron al montaje. `evaluar.py` los
usa de referencia y puntúa.

Se mide en **segundos, no en swings**: al scout le sobra medio segundo de tiempo muerto
igual que le falta medio segundo de swing, y contar aciertos por swing esconde las dos
cosas. Sobre el turno que hay, con la ventana anterior de 1,4/1,6 s:

| | precisión | cobertura | F1 |
|---|---|---|---|
| Todos los candidatos, sin filtrar | 48 % | 95 % | 64 % |
| Los candidatos que caen dentro | 94 % | 95 % | **95 %** |

La primera fila es el techo del detector: propone el 95 % de los segundos que el scout
conserva, y lo que sobra lo tira la persona al marcar.

Con material nuevo no hace falta encadenar los comandos a mano:

```
python tools/probar_pares.py --perfil perfiles/camara.json crudo1.mp4 montaje1.mp4 crudo2.mp4 montaje2.mp4
```

alinea, detecta, puntúa y **vuelve a barrer la calibración contra todos los pares a la
vez**, que es el paso que se olvida y el que puede tumbar una conclusión anterior. El
procedimiento completo está en **`PROBAR.md`**.

Los defaults actuales de bateo son 3,0 s antes y 2,0 s después de cada swing, confirmados
por el cliente sobre material real. Las ventanas solapadas se fusionan. Sustituyen los
1,4/1,6 s anteriores, que entraban demasiado metidos en el siguiente swing. El F1 de la
tabla es por tanto una referencia histórica del detector, no una métrica de estos nuevos
márgenes de entrega; hay que volver a medirlos cuando lleguen más pares.

Las referencias son JSON de unos pocos kilobytes y **se versionan** — la verdad del
cliente entra en git sin que entre el vídeo.

`alinear.py` es cuadrático: compara cada fotograma del montaje contra cada uno del crudo.
Va sobrado para pares de **un turno**, que es el caso real, y avisa cuando no.

| crudo | memoria | tiempo |
|---|---|---|
| 2 min | 41 MB | instantáneo |
| 15 min | 304 MB | 24 s |
| 1 h | 1,2 GB | 6 min |

El motor de cortar, en cambio, sí está pensado para jornadas de 3 h: la etapa 1 decodifica
solo keyframes y tarda **1,1 min** en una jornada entera.

## La pantalla de marcado

`cortador marcar` reproduce cada candidato en bucle y espera una tecla:

| Tecla | |
|---|---|
| `V` / ↑ | vale: hubo pelota lanzada |
| `N` / ↓ | no vale: calentamiento, o nada |
| espacio | dejarlo pendiente y seguir |
| ← / → | candidato anterior / siguiente |
| `A` `S` | mover el inicio del tramo 0,2 s |
| `K` `L` | mover el fin del tramo 0,2 s |
| `G` | guardar sin salir |
| `Q` / ESC | guardar y salir |

Cerrar con Ctrl+C no guarda: se pierde lo marcado desde el último `G`.

Las marcas van a `<video>.marcas.json`, junto al vídeo salvo que se pase `--marcas`.
Volver a lanzar `marcar` retoma el cuaderno donde estaba; `--rehacer` vuelve a detectar.

Después, `compactar` pega los tramos válidos. Aquí **sí se recodifica**, al revés que en
`cortar`: los cortes caen donde ocurre el swing, no donde el códec dejó un keyframe, y
con keyframes a un segundo el ajuste hacia fuera alargaría cada swing más que el propio
swing.

### Un detalle que contamina cualquier medida

En un H.264 el keyframe se codifica entero, sin referencia al anterior, y arrastra su
propio ruido de cuantización: queda distinto de sus **dos** vecinos. Medir movimiento por
diferencia entre fotogramas sin descontar eso llena la lista de picos falsos clavados en
los segundos redondos —en el vídeo de prueba, 59 "swings", casi todos en `t=N,00`—.
`eventos.py` descarta las dos parejas que tocan cada keyframe. Descontando solo la
anterior siguen colándose picos justo después; hay un test para eso.


## Coste

El motor no llama a ningún modelo: OpenCV y ffmpeg en local, **cero tokens**. Si algún día
un LLM decide lo de la pelota, con el volumen del cliente (30 cortes por bateador, 10
bateadores por semana) sale ~$20 al mes con Opus 5, ~$8 con Sonnet 5 y ~$4 con Haiku 4.5;
la Batch API lo deja a la mitad. El desglose está en `BITACORA.md`. Si el audio del
original sirve, el golpe del bate se detecta en local y se queda en cero.


## Estado

Fase 1 (motor por línea de comandos), el marcado de swings dentro del turno y la medida
contra el montaje del scout. **121 tests en verde**. El F1 histórico fue 95 % sobre un
solo turno y con la ventana anterior de 1,4/1,6 s; no describe todavía los nuevos márgenes.

Pendiente, y sigue siendo lo que bloquea:

- **Más pares (crudo, montaje)**. Cada uno produce su verdad de referencia sin marcar
  nada, así que son la forma barata de saber si el 92 % aguanta o está sobreajustado.
- **Un vídeo tal como sale de la cámara**, sin pasar por WhatsApp y con audio, para saber
  si el criterio de la pelota se puede automatizar. Pásale `verificar_material.py`.
- **Las dos jornadas reales del cliente**, para volver a calibrar el umbral de identidad.
- Definir si la salida final será un vídeo por turno o un vídeo acumulado por bateador,
  y cómo identifica hoy el scout a cada persona cuando procesa una jornada.

Para retomar el trabajo, `SIGUIENTE.md`. Para probar material nuevo, `PROBAR.md`.

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
.venv\Scripts\python.exe -m pip install -e .       # instala el paquete y el comando cortador
.venv\Scripts\python.exe tools\make_fixture.py     # genera la jornada de prueba
.venv\Scripts\python.exe -m pytest
```

Sin el `pip install -e .`, `python -m cortador` falla con *No module named cortador*: el
código vive en `src/`. Las pruebas no lo necesitan porque `tests/conftest.py` añade
`src/` al camino de importación.

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
