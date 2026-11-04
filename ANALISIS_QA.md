# Análisis de las primeras etiquetas del QA

## Material recibido

Carpeta: `JSON de QA`

- `S1440017.marcas.json`
- `S1440021.marcas.json`

Los archivos contienen decisiones de bateo completas, sin candidatos pendientes. No incluyen los videos, metadatos técnicos de la corrida ni el paquete generado por **Crear paquete para enviar**.

## Resumen cuantitativo

| Video | Candidatos | Válidos | Inválidos | Pendientes | Rendimiento de revisión |
|---|---:|---:|---:|---:|---:|
| S1440017 | 9 | 8 | 1 | 0 | 88.89 % válidos |
| S1440021 | 16 | 3 | 13 | 0 | 18.75 % válidos |
| Total | 25 | 11 | 14 | 0 | 44.00 % válidos |

El rendimiento de revisión indica qué porcentaje de candidatos terminó conservado. No mide todavía cobertura: sin el video y sin un montaje de referencia no se puede saber si el detector omitió swings reales.

## Tramos válidos después de fusionar solapamientos

### S1440017

- 8.912–17.682 s
- 24.995–37.903 s
- 49.819–54.819 s
- 59.729–66.264 s
- Duración total estimada: 33.213 s

### S1440021

- 43.613–48.613 s
- 54.624–59.624 s
- 86.690–91.690 s
- Duración total estimada: 15.000 s

## Hallazgos

1. El detector se comportó de manera muy diferente entre ambos videos. En S1440017 casi todos los candidatos fueron útiles; en S1440021 hubo 13 falsos positivos de 16 candidatos.
2. La fuerza del movimiento no sirve como umbral global. Los válidos abarcan aproximadamente 5.944–15.754 y los inválidos 5.892–23.052. En S1440021 varios movimientos inválidos fueron más fuertes que los swings conservados.
3. No se debe subir el umbral únicamente para reducir candidatos: podría eliminar swings reales. Primero hay que identificar visualmente qué movimientos produjeron los falsos positivos de S1440021.
4. Los campos `nota` están vacíos. Sabemos qué se descartó, pero no si fue preparación, recolocación, movimiento del receptor, salida del cajón u otra causa.
5. El campo `perfil` está vacío en ambos archivos. Se corrigió la aplicación para que futuras corridas guarden una identificación de la configuración de cámara utilizada.
6. Los JSON recibidos directamente contienen una ruta absoluta y el nombre del usuario de Windows del QA. Para futuras entregas debe usarse **Crear paquete para enviar**, que depura las rutas antes de generar el ZIP.
7. Estas etiquetas sí sirven para medir la precisión de los candidatos presentados y conservar decisiones humanas. No bastan para entrenar o corregir un detector visual porque no contienen píxeles. Para estudiar los falsos positivos se necesitan los videos correspondientes o muestras visuales autorizadas.

## Cambios aplicados a partir de esta entrega

- Se añadió una prueba para exigir que futuras marcas registren la configuración de cámara.
- Se corrigió el flujo de bateo nuevo para llenar el campo `perfil` al crear el cuaderno.
- Los originales recibidos no se modificaron.

## Próxima entrega solicitada al QA

1. Pulsar **Crear paquete para enviar** y entregar el ZIP generado, no solamente los archivos `.marcas.json` originales.
2. Conservar los videos S1440017 y S1440021. Para reproducir y clasificar los falsos positivos, enviarlos por el canal acordado o autorizar la extracción de pequeños clips de candidatos.
3. Informar si el resultado final omitió algún swing real. Esa respuesta es necesaria para medir cobertura, no solo precisión.
4. Para cada candidato dudoso, añadir una razón de descarte cuando la interfaz futura la permita.

## Interpretación provisional

Con estas dos muestras hay 25 candidatos etiquetados, pero todavía no hay suficiente evidencia para cambiar los parámetros generales. La diferencia entre 88.89 % y 18.75 % sugiere que la cámara, el encuadre o el tipo de movimiento influyen más que la fuerza bruta del pico. El siguiente ajuste debe basarse en los fotogramas de S1440021 y no en un umbral calculado solamente con estos JSON.
