# Cuando lleguen vídeos nuevos

## Probar la distribución QA

El EXE PyInstaller sin firma fue bloqueado por Code Integrity en el Windows empresarial.
La alternativa es construir con `python tools/build_portable_runtime.py`, copiar
`CortadorTurnosQA-Portable.zip` a un Windows sin Python ni FFmpeg, extraerlo completo y
abrir `INICIAR_CORTADOR.bat`. Si no abre, ejecutar `DIAGNOSTICO.bat`. Procesar una carpeta, revisar con V/N/Q
y comprobar los MP4 bajo `Resultados`. El paquete creado desde la GUI sólo puede
contener `corridas/*.json`, `etiquetas/*.json` y `app.log`; nunca videos o resultados.
La edición real ya se construyó y se verificó desde una extracción limpia: diagnóstico
correcto y ventana abierta. La validación definitiva pendiente es procesar videos en la
computadora del QA y devolver el primer paquete de evidencia.

Qué pedir, cómo comprobar que sirve, y cómo probar el motor contra ello. Pensado para
abrirlo sin recordar nada de la sesión anterior.

---

## 1 · Qué pedir, exactamente

Hay **dos peticiones distintas** y sirven para cosas distintas. Conviene no mezclarlas.

### A · Pares (crudo + montaje) — para medir el motor

De cada turno, **los dos ficheros**:

- el **crudo**, tal como quedó antes de editar;
- el **montaje** que el scout hizo con él.

El montaje solo no vale para nada. El par sí: alineándolos sale, sin que nadie marque
nada a mano, qué tramos conservó. Eso es la verdad de referencia contra la que se mide
el motor, y es la forma barata de conseguir material etiquetado.

**Con dos o tres pares ya se sabe si el 95 % actual es real o es que se ajustó a un solo
turno.** Es lo que más falta hace.

### B · Un vídeo tal como sale de la cámara — para automatizar lo de la pelota

Otra cosa, y sigue pendiente. Sirve para saber si el criterio del cliente —un swing vale
solo si le lanzaron una pelota— se puede detectar solo, o se queda a mano para siempre.

Cómo pedirlo sin que se estropee por el camino:

- Desde la **galería del móvil que grabó**, no un reenvío de un reenvío.
- Enviado **como documento / archivo** (WhatsApp: 📎 → *Documento*, no *Galería*), o por
  Drive, WeTransfer o cable. Mandarlo por *Galería* lo recomprime y deshace el favor.
- **Con audio.** Es la vía más prometedora: en una jaula la pelota siempre golpea algo,
  el bate o la lona, y un swing en vacío no suena.
- Idealmente 1080p y 60 fps.

**Señal rápida sin abrir nada:** si pesa ~4-8 MB por minuto, volvió a pasar por WhatsApp.
El original debería ir por encima de 30 MB/min.

---

## 2 · Comprobar que el material sirve

```
python tools/verificar_material.py Video/loquesea.mp4
```

Dice si sirve y, si no, por qué no. Comprueba resolución, bitrate, fps, keyframes y **si
el audio trae señal de verdad** (no basta con que exista la pista: las dos que llegaron
estaban mudas, y el largo ni siquiera tenía pista).

Esto es lo primero, siempre. Ahorra tardes enteras persiguiendo una pelota que el códec
ya había borrado.

---

## 3 · Probar el motor contra los pares

Un solo comando hace todo: alinear, detectar, puntuar y recalibrar.

```
python tools/probar_pares.py --perfil perfiles/camara.json ^
    Video/turno1_crudo.mp4 Video/turno1_montaje.mp4 ^
    Video/turno2_crudo.mp4 Video/turno2_montaje.mp4
```

Los vídeos van **en parejas y en orden**: crudo, montaje, crudo, montaje. En PowerShell el
continuador de línea es `` ` `` o se escribe todo en una línea.

Si no hay perfil para esa cámara:

```
python -m cortador calibrar Video/turno1_crudo.mp4 --perfil perfiles/camara.json
```

### Qué imprime, y qué mirar

1. **Una fila por turno** con `prec`, `cob` y `F1`. La columna `techo` es cuánto llega a
   proponer el detector: si baja mucho, el problema es el detector, no el marcado.
2. **El barrido conjunto** de `--antes` / `--despues` sobre todos los pares a la vez.
   Mira la **malla entera**, no solo el máximo: lo que vale es que el máximo sea una
   meseta ancha. Un pico aislado rodeado de números peores es ruido, no una calibración.
3. **Tramo a tramo**, cuánto se recupera de cada referencia. Un tramo al 0 % es un fallo
   concreto que se puede ir a mirar — así se encontró el de `t=35,70`.

Las referencias quedan en `fixtures/referencia_<nombre>.json`. Son JSON de unos
kilobytes y **se versionan**: la verdad del cliente entra en git sin que entre el vídeo.

### Si el barrido propone otra ventana

Tómala como diagnóstico de cobertura y tiempo sobrante, no como una orden de cambiar los
defaults. Los 3,0 s antes y 2,0 s después actuales fueron confirmados por el cliente para
que el montaje muestre la preparación. Si varios pares muestran una diferencia material,
compara ambas salidas con el cliente antes de tocar `src/cortador/eventos.py` y anota en
`BITACORA.md` contra cuántos pares se midió.

No la cambies por una diferencia de uno o dos puntos: dentro del ruido de un puñado de
turnos eso no significa nada, y una métrica mejor puede producir un montaje que el scout
prefiera menos.

---

## 4 · Marcar a mano, si hace falta

Si llega un crudo **sin** su montaje, no hay referencia y el turno hay que marcarlo:

```
python -m cortador eventos   turno.mp4 --perfil perfiles/camara.json
python -m cortador marcar    turno.mp4 --perfil perfiles/camara.json
python -m cortador compactar turno.mp4 --salida turno_compacto.mp4
```

En `marcar`: `V` vale, `N` no vale, `A/S` y `K/L` mueven los bordes, `Q` guarda y sale.
Se puede salir a medias y retomar.

Un cuaderno marcado a mano también se puede puntuar, si aparece luego su montaje:

```
python tools/evaluar.py turno.marcas.json fixtures/referencia_turno.json
```

---

## Límites que conviene saber

**El motor de cortar aguanta jornadas de 3 h.** La etapa 1 decodifica solo keyframes:
1,1 min para una jornada entera, unos 10.800 recortes, 2,1 GB de RAM.

**`alinear.py` y `probar_pares.py` no.** Comparan cada fotograma del montaje contra cada
uno del crudo, así que el coste es el producto de las dos duraciones:

| crudo | memoria | tiempo |
|---|---|---|
| 2 min | 41 MB | instantáneo |
| 15 min | 304 MB | 24 s |
| 1 h | 1,2 GB | 6 min |
| 3 h | 3,7 GB | 58 min |

Están pensados para pares de **un turno**, que es el caso real —el scout monta turno a
turno, no la jornada entera—. Avisan por encima de 1,5 GB en vez de reventar.

**No intentes acelerarlo siguiendo la continuidad** (encajar el fotograma i+1 mirando
solo el siguiente del crudo). Ya se probó y no funciona con esta cámara: al estar fija y
la escena casi quieta, un fotograma correlaciona **0,9998 con el vecino del sitio
equivocado, exactamente igual que con el correcto**. No hay umbral que separe un corte de
una continuación. Está medido y contado en `BITACORA.md`.

---

## Contexto operativo confirmado y preguntas pendientes

El sistema evalúa exclusivamente al **bateador**. El lanzador no siempre aparece y sus
vídeos son otro flujo; su presencia o su gesto no pueden ser una señal obligatoria. El
scout graba la sesión completa, extrae aproximadamente 10–20 turnos para crear el vídeo
nuevo y tiene muchas personas que evaluar.

Todavía hay que confirmar si una persona reaparece en bloques separados, cómo se la
identifica, si la salida debe ser por turno o acumulada por bateador y **cuántos minutos
lleva hoy** procesar una jornada. Sin el último dato no se puede medir el ahorro real.
