# Bitácora

Registro de lo que se va haciendo en el proyecto, con las decisiones y el porqué.
Lo más reciente arriba.

---

## 2026-09-02 · Los detectores del diseño (YOLOv8n y embedding)

Se instalan las dependencias pesadas (~2,5 GB) y se implementan las versiones del diseño
de las etapas 2 y 3, elegibles por línea de comandos y sin tocar el resto del motor.

- `torch 2.14.0+cpu`, `torchvision`, `ultralytics 8.4.138`. Se usa el índice CPU de
  PyTorch a propósito: el objetivo del proyecto es correr en el portátil del scout, sin
  GPU, y la rueda con CUDA no aporta nada ahí.
- `presencia_yolo.py` → `--detector yolo`
- `identidad_cnn.py` → `--identidad cnn` (ResNet-18 sobre el torso + histograma de color)

`reglas.py` ya no llama a `identidad` directamente: recibe el módulo de apariencia, así
que cambiar de descriptor no toca la lógica de segmentación.

### Para probarlos hacía falta otro fixture

Sobre rectángulos de colores YOLO no detecta a nadie, y con razón. `make_fixture.py`
gana `--personas`, que recorta personas reales de las imágenes de ejemplo de ultralytics
y las usa como peloteros. Mismo guion, mismos cuatro casos límite.

### Lo que se aprendió al probar

**El histograma de color no separa a dos personas reales.** Con el fixture de personas
salían 4 turnos de 5: P-01 y P-02 quedaban a 0,32, por debajo del umbral de fusión de
0,35, y al estar separados por sólo 15 s el motor los daba por el mismo pelotero. Es
exactamente la debilidad que el diseño anticipaba al pedir OSNet o CLIP.

**El primer umbral de la CNN estaba mal y el motor devolvía 1 turno.** Lo puse en 0,30
por analogía con el histograma, pero la distancia coseno de un embedding vive en otra
escala. Calibrarlo con sprites y ruido sintético también salió mal (dio 0,11, y con eso
seguían saliendo 4 turnos): el ruido gaussiano no se parece a lo que cambia de verdad
entre dos fotogramas del mismo pelotero.

Lo que funcionó fue medirlo sobre el vídeo, tramo a tramo. De ahí sale
`tools/calibrar_umbral.py`, que imprime hueco y distancia entre tramos vecinos y dice qué
haría la regla. Los números reales:

| | distancia |
|---|---|
| mismo pelotero, dos tramos | ≤ 0,011 |
| dos peloteros distintos | ≥ 0,107 |

El hueco entre ambos es enorme, así que el umbral va en medio: **0,06**. Con eso salen
los 5 turnos, incluido el relevo sin hueco, que antes se perdía.

### Resultado

| Fixture | Detector / identidad | Turnos |
|---|---|---|
| formas | color / color | 5 ✓ |
| personas | color / color | 4 ✗ |
| personas | color / cnn | 5 ✓ |
| personas | yolo / cnn | 5 ✓ |

**Quien arregla el problema es la identidad, no YOLO.** El detector por color acierta la
presencia igual de bien (77 % contra 76 %) porque el fondo del fixture es perfectamente
estable. YOLO debería importar con material real, donde la luz gira a lo largo de la
tarde, pero eso hoy es una expectativa, no un dato.

21 tests en verde.

### Aviso para cuando lleguen los vídeos reales

El umbral 0,06 está calibrado contra seis personas recortadas de dos fotos. **Hay que
volver a pasar `calibrar_umbral.py` sobre las jornadas reales**, y probablemente saldrá
otro número: allí el mismo pelotero cambia de postura, se agacha y batea, y dos peloteros
comparten el uniforme de la academia. Ese es el caso que este fixture no sabe imitar.

---

## 2026-09-02 · Fase 1: motor por línea de comandos

Se crea el repo en `C:\Dev\projects\cortador-turnos` (git local, sin remoto) y se
implementa el motor completo del diseño acordado.

### Entorno

No había ni Python ni ffmpeg en la máquina. Instalados con winget:

- Python 3.12.10 → `AppData\Local\Programs\Python\Python312`
- ffmpeg 9.0.1 (Gyan, full build) → `AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg*`

Si ffmpeg no aparece en el PATH de una terminal ya abierta, el código lo acepta por
las variables `CORTADOR_FFMPEG` y `CORTADOR_FFPROBE`.

**Stack elegido:** Python + OpenCV + ffmpeg. Se descartó Node + ffmpeg-static, que no
habría necesitado instalar nada, porque la parte de visión es más cómoda en Python.

### Lo implementado

Las cinco etapas del desglose técnico, una por módulo:

| Módulo | Etapa | Qué hace |
|---|---|---|
| `perfil.py` | 0 · calibración | El ROI del cajón, en JSON, una vez por cámara |
| `muestreo.py` | 1 · muestreo | Decodifica solo keyframes y recorta el ROI |
| `presencia.py` | 2 · presencia | ¿Hay alguien en el cajón? |
| `identidad.py` | 3 · identidad | Apariencia, para el relevo sin hueco |
| `reglas.py` | 4 · reglas | Fusionar, descartar, colchón, ajuste a keyframe |
| `corte.py` | 4 · corte | Exporta con `-c copy -an` |
| `canal.py` | — | Encadena las cinco |
| `cli.py` | — | `calibrar`, `analizar`, `cortar` |

### Prueba sin vídeo del cliente

`tools/make_fixture.py` genera una jornada sintética de 440 s que contiene a propósito
los cuatro casos límite del diseño, más su verdad de referencia en JSON:

1. turno normal (P-01)
2. el pelotero sale 18 s y vuelve (P-02) → debe salir **un** clip
3. relevo sin hueco (P-03 → P-04) → deben salir **dos**
4. un cruce de 8 s → **ningún** clip

Resultado actual: **5 turnos de 5**, con la fusión correcta y el cruce descartado. Los
clips salen h264 480×270, sin pista de audio y por copia de flujo.

### Dos correcciones que salieron de probar

**La presencia comparaba en luminancia.** Detectaba 16 % de ocupación en vez de 77 % y
encontraba 1 turno de 5. Cuatro de los cinco uniformes del fixture tenían casi la misma
luminancia que la tierra del cajón:

| | dif. luminancia | dif. color (canal más dispar) | umbral |
|---|---|---|---|
| P-01 | 16,9 | 64 | 28 |
| P-02 | 25,5 | 100 | 28 |
| P-03 | **80,3** | 100 | 28 |
| P-04 | 10,2 | 68 | 28 |
| P-05 | 10,6 | 80 | 28 |

Ahora compara canal a canal. El fixture se deja "difícil" a propósito: un uniforme del
mismo brillo que la tierra es un caso real, no un artificio de la prueba.

**El fondo aprendía la silueta del pelotero.** La mediana temporal se contamina cuando el
cajón está ocupado la mayor parte del tiempo. Se estima en dos pasadas: mediana, y luego
mediana de los recortes más quietos respecto a esa primera estimación, que son los del
cajón vacío.

### Estado

14 tests en verde: 9 de reglas (sin vídeo, con la distancia de apariencia inyectada) y
5 de integración sobre el fixture.

### Pendiente

- **Del cliente, y sigue siendo lo que bloquea todo:** cuántos minutos les lleva hoy
  partir una jornada, y dos jornadas completas grabadas por ellos con sus cortes manuales.
  Sin el primero no hay listón que superar; sin las segundas no hay nada que validar.
- Sustituir presencia e identidad por los detectores del diseño (YOLOv8n, OSNet/CLIP).
- Fase 2: la pantalla de revisión. Es el grueso del trabajo y del valor.
