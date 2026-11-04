# Por dónde seguir

> **Aviso (2026-11-05): este documento quedó desactualizado en su primera
> sección.** Describe un plan de servidor que, para cuando se escribió, era
> futuro — pero el servidor YA ESTÁ DESPLEGADO Y EN PRODUCCIÓN desde hace
> semanas (`144.202.57.21`, `scoutcuts.com`), incluyendo la zona de
> entrenamiento QA multi-disciplina (defensa/bateo/pitcheo/catcher). La
> fuente de verdad del estado del servidor es **`CONTINUAR_SERVIDOR.md`**;
> el día a día con el porqué de cada decisión está en **`BITACORA.md`**. El
> resto de este archivo (detección de swings, calibración, pares
> crudo/montaje pendientes) sigue vigente como lista de trabajo pendiente
> del motor de visión, no del servidor.

## Servidor de usuarios y descargas: YA DESPLEGADO (ver CONTINUAR_SERVIDOR.md)

Sección histórica, conservada por contexto. En su momento se planeó usar
`144.202.57.21`, compartido con CanastaRD, aislando el servicio en su propia
base/usuario PostgreSQL y puerto interno (arquitectura original en
[`SERVIDOR_CONTROL.md`](SERVIDOR_CONTROL.md)). Ese plan ya se ejecutó: el
estado real, verificado en vivo, está en `CONTINUAR_SERVIDOR.md`.

## Runtime portátil construido; falta validación del QA

El EXE PyInstaller sin firma fue bloqueado por la política Code Integrity empresarial.
Existe un builder alternativo para empaquetar el `pythonw.exe` embeddable oficial firmado,
OpenCV, NumPy, Tk, FFmpeg/FFprobe y los perfiles. `CortadorTurnosQA-Portable.zip` ya fue
construido, verificado íntegramente, diagnosticado y abierto desde una extracción limpia.
Falta la prueba decisiva en la computadora del QA mediante `INICIAR_CORTADOR.bat`: procesar
bateo, revisar V/N/Q, confirmar resultados y crear el paquete de evidencia. No enviar
`DatosQA` completo: usar **Crear paquete para enviar**. No hay subida automática.

## 2026-10-08 · Primera aplicación de escritorio

Existe un MVP Windows en `src/cortador/app.py`. Se abre con doble clic en
`iniciar_app.bat` o con:

```
.venv\Scripts\python.exe -m cortador app
```

La pantalla principal está pensada para scouts no técnicos: acepta la ruta de la carpeta
del jugador (pegada o elegida con **Examinar**) y tiene una única acción,
**Procesar carpeta**. Descubre MOV/MP4/M4V/AVI fuente, usa internamente las decisiones
revisadas que estén junto a cada video y escribe bateo y defensa en `Resultados`. Un worker único
procesa los videos secuencialmente, mantiene Tkinter libre y aísla los errores por video.

Los bateos nuevos ya tienen revisión integrada: si exactamente una configuración de
`perfiles/` coincide con la resolución real, se detectan candidatos con márgenes 3/2,
se guarda `<stem>.marcas.json`, se abre la ventana V/N/Q y se exportan las marcas válidas.
El scout solo elige la carpeta. Sin coincidencia única o sin marcas válidas el video queda
pendiente; un fallo no detiene los posteriores. Las decisiones existentes tienen
preferencia y un sidecar defensivo válido impide clasificar el video como bateo nuevo.

## 2026-10-06 · Defensa revisada y nuevos márgenes de bateo

Bateo usa ahora 3,0 s antes y 2,0 s después del pico, por confirmación directa del
cliente; los solapamientos se fusionan. Una sesión del agente creada con otros parámetros
no se adopta ni se reescribe: hay que reanudar con sus valores originales o usar otra
carpeta de trabajo.

Defensa no pasa por el detector de swings. Su entrada es un manifiesto humano v1 y su
salida son exactamente dos repeticiones `adelante`, dos `derecha` y dos `izquierda`:

```
cortador defensa VIDEO --marcas archivo.defensa.json --salida defensa_6.mp4
```

El corte añade 2,0 s antes del inicio de preparación y 0,3 s después del tiro; se pueden
cambiar con `--antes-extra` y `--despues-tiro`. Las incompletas no entran y, si hay más
de dos completas de una categoría, una persona debe marcar exactamente dos con
`seleccionada: true`. No automatizar pelota, dirección ni acciones defensivas hasta contar
con suficiente material etiquetado.

## 2026-09-30 · Nueva línea: agente local

La entrada principal es ahora:

```
cortador agente jornada.mp4 --perfil perfiles/camara.json --trabajo trabajo-jornada
```

(Requiere `.venv\Scripts\python.exe -m pip install -e .` y el entorno activado; sin
activarlo, `.venv\Scripts\python.exe -m cortador agente ...`.) Termina con 0 si completó
y con 2 si espera revisión humana.

`src/cortador/agente.py` coordina corte, candidatos, revisión humana y compactado. Guarda
`estado-agente.json` de forma atómica y permite reanudar con el mismo comando. No usa IA
ni servicios externos. `--no-interactivo` es apto para automatización, pero se detiene
ante marcas pendientes: no hay información suficiente para decidir solo si hubo pelota.

Las próximas mejoras deben mantener esa frontera. Antes de automatizar la validez hacen
falta los materiales enumerados abajo y una medida que demuestre que la señal sirve.

Última sesión: **2026-09-30**. Lo de cada día, con el porqué, está en `BITACORA.md`.

## Dónde quedó

El motor corta la jornada por bateador (etapas 0-4) y, dentro de cada turno, propone los
swings, deja marcarlos a mano y exporta el turno sin tiempos muertos (etapas 5-6).
**116 tests en verde.**

Y desde esta sesión la calidad tiene número. El scout entregó el mismo turno en dos
versiones —crudo y montado— y ese par es la verdad de referencia:

```
# sacar de un par (crudo, montaje) los tramos que el scout conservó
python tools/alinear.py crudo.mp4 montaje.mp4 --salida fixtures/referencia_turnoN.json

# puntuar lo que produce el motor contra esa referencia
python tools/evaluar.py turno.marcas.json fixtures/referencia_turnoN.json
```

Sobre el único turno que hay, usando la ventana anterior de 1,4/1,6 s: **precisión 94 %,
cobertura 95 %, F1 95 %**. El techo del detector —los segundos que llega a proponer— es
95 %. Es una referencia histórica; los márgenes actuales de 3,0/2,0 s responden al
criterio visual del cliente y todavía deben medirse contra más pares.

Cuando lleguen más pares, todo eso es un comando, y el procedimiento entero —qué pedir,
cómo comprobarlo, qué mirar— está en **`PROBAR.md`**:

```
python tools/probar_pares.py --perfil perfiles/camara.json crudo1.mp4 montaje1.mp4 crudo2.mp4 montaje2.mp4
```

## Lo que bloquea

### 1. Más pares (crudo, montaje), que ahora valen el doble

Esto ha cambiado de naturaleza. Antes se pedían vídeos para *mirarlos*; ahora **cada par
que el scout entregue produce su propia verdad de referencia sin que nadie marque nada**.
Es la forma barata de conseguir material etiquetado.

Qué pedir, y merece decirlo así de explícito:

- De cada turno, **los dos ficheros**: el crudo y el montaje que él hizo. El montaje solo
  no sirve; el par sí.
- Cuantos más turnos, mejor. Con dos o tres ya se puede saber si los números de arriba
  aguantan o estaban sobreajustados a este.

### 2. Un vídeo tal como sale de la cámara

Sigue haciendo falta, pero para **otra cosa**: para saber si el criterio de la pelota se
puede automatizar. Los ficheros que hay no sirven para eso, y es medible — el largo no
tiene ninguna pista de audio (`nb_streams=1`), y ninguna cámara graba así.

Cómo pedirlo sin que se estropee por el camino:

- Desde la **galería del móvil que grabó**, no un reenvío.
- Enviado **como documento / archivo** (WhatsApp: 📎 → *Documento*, no *Galería*), o por
  Drive, WeTransfer o cable.
- **Con audio.** El golpe del bate es la vía más prometedora: en una jaula la pelota
  siempre golpea algo, y un swing en vacío no suena.
- Idealmente 1080p y 60 fps.

Señal rápida: si pesa ~4-8 MB por minuto, volvió a pasar por WhatsApp. El original
debería ir por encima de 30 MB/min. Y en todo caso:

```
python tools/verificar_material.py jornada.mp4
```

### 3. Flujo real confirmado y decisiones pendientes

Confirmado por el cliente:

- El sistema evalúa al **bateador**, no al lanzador.
- El lanzador no siempre aparece en cámara y sus vídeos se procesan por separado. No se
  puede convertir su presencia o su gesto en un requisito del detector.
- El scout graba el vídeo completo y después extrae aproximadamente **10–20 turnos** para
  crear el vídeo nuevo.
- Hay muchas personas que evaluar, así que el flujo debe escalar a varias identidades en
  la misma jornada sin obligar a repetir trabajo manual innecesario.

Queda por confirmar:

- Si una misma persona vuelve en varios bloques separados durante la jornada.
- Cómo nombra o identifica hoy el scout a cada bateador.
- Si la salida deseada es un vídeo por turno o uno acumulado por bateador.
- Cuántos minutos les lleva hoy procesar una jornada. Sin eso no hay listón que superar.

### 4. Las jornadas completas, para recalibrar identidad

El umbral de identidad (0,06) sigue medido sobre seis personas recortadas de dos fotos.
Con material real hay que volver a pasar `tools/calibrar_umbral.py`.

## Decisión pendiente, pequeña pero real

En el cuaderno de `Video/`, el candidato de `t=35,70` está marcado `invalido` pero cae
dentro de un tramo que el scout conservó, y tiene la segunda fuerza más alta de las 22.
Con la referencia buena parece un error de la sesión anterior, no un juicio. **Se dejó
sin tocar**: es el único material etiquetado que hay. Corregirlo sube el F1 de 83 % a
89 %; hay que decidir si se corrige a mano o si se regenera el cuaderno desde la
referencia.

## Al retomar

1. Si hay pares nuevos: `probar_pares.py` con todos a la vez, para ver si el 95 % aguanta
   fuera de este turno. **Es lo primero, porque puede invalidar la calibración.**
2. Si hay un vídeo de cámara de verdad: `verificar_material.py`, y con eso se decide si
   el criterio de la pelota se automatiza o se queda a mano para siempre.
3. Usar el barrido para diagnosticar cobertura y tiempo sobrante. No cambiar automáticamente
   los márgenes de entrega 3,0/2,0 s: fueron elegidos por el cliente. Cualquier cambio debe
   validarse con él y anotarse en la bitácora junto con la cantidad de pares medida.

## Coste

El motor **no gasta tokens**: OpenCV y ffmpeg en local. Si más adelante un modelo decide
lo de la pelota, con el volumen del cliente son ~$20/mes con Opus 5, ~$8 con Sonnet 5,
~$4 con Haiku 4.5, y la mitad con la Batch API. El desglose está en la bitácora. Si el
audio sirve, se queda en cero.
