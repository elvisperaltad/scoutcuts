# Entrega portátil para QA

Estado de la entrega: construida y validada localmente el 2026-10-09.

## Archivo que debe enviarse

`dist/CortadorTurnosQA-Portable.zip`

- Tamaño verificado: 242,398,363 bytes (231.2 MiB).
- SHA-256: `440c50a4408862562c8ff22b3a5dad965a31f369e1b5116dfc6503105f871e79`.
- Checksum guardado en `dist/CortadorTurnosQA-Portable.zip.sha256`.

No enviar la carpeta del repositorio, el entorno `.venv`, `DatosQA` completo ni el artefacto PyInstaller `CortadorTurnosQA-portable.zip`. Ese EXE sin firma fue bloqueado por una política empresarial de Windows. La entrega correcta usa el runtime oficial firmado de Python y tiene `Portable` con P mayúscula en el nombre.

## Instrucciones para el QA

1. Copiar `CortadorTurnosQA-Portable.zip` a la computadora de prueba.
2. Extraer el ZIP completo. No ejecutar la aplicación desde dentro del ZIP.
3. Abrir `INICIAR_CORTADOR.bat`.
4. Seleccionar la carpeta completa del jugador.
5. Pulsar **Procesar carpeta**.
6. Cuando aparezca la revisión de bateo:
   - `V`: conservar la jugada.
   - `N`: descartar la jugada.
   - `Q`: terminar, guardar y continuar con la exportación.
7. Comprobar los videos generados en la subcarpeta `Resultados` de la carpeta del jugador.
8. Al terminar las pruebas, pulsar **Crear paquete para enviar** y devolver únicamente ese ZIP de evidencia.

Si la aplicación no abre, ejecutar `DIAGNOSTICO.bat` y enviar una captura completa del resultado.

## Evidencia que acumula la aplicación

Cada vez que se pulsa **Procesar carpeta**, la aplicación conserva localmente:

- Fecha, estado y resumen de la corrida.
- Nombre del archivo y extensión.
- Tamaño, resolución, FPS, duración y códec del video, cuando están disponibles.
- Tipo de procesamiento inferido.
- Configuración de cámara seleccionada.
- Instantes y fuerza de los candidatos detectados.
- Decisiones finales, límites de cada tramo, estado y nota.
- Cantidad de jugadas válidas y pendientes.
- Nombre del resultado generado.
- Errores y trazas de diagnóstico depuradas.
- Copias de los archivos de decisiones para conservar las etiquetas aunque se mueva la carpeta original.

La evidencia queda en `DatosQA`, junto a la aplicación portátil. El botón **Crear paquete para enviar** empaqueta únicamente:

- `corridas/*.json`
- `etiquetas/*.json`
- `app.log`

## Privacidad y seguridad

- No se copian videos originales.
- No se incluyen resultados MP4.
- No se guardan nombre de usuario, hostname, credenciales ni rutas absolutas.
- No se realiza ninguna subida automática.
- La recopilación es local y de mejor esfuerzo: un fallo al escribir evidencia no debe detener el procesamiento.

## Cobertura actual y límites conocidos

- Bateo nuevo: selecciona automáticamente una configuración compatible por resolución, detecta candidatos, abre la revisión V/N/Q y genera el compacto con las jugadas conservadas.
- Material ya revisado: se vuelve a procesar sin pedir archivos técnicos al scout.
- Defensa nueva: todavía no tiene detección y revisión integrada completa; necesita más desarrollo y ejemplos etiquetados.
- Una resolución o posición de cámara sin una configuración única compatible puede dejar el video pendiente.
- La aplicación no promete detección automática de la pelota en material comprimido o de baja resolución.

## Qué debe probar el QA

Usar carpetas distintas y registrar, como mínimo:

- Videos MP4 y MOV.
- Diferentes resoluciones y duraciones.
- Carpetas con uno y varios videos.
- Casos con candidatos válidos, falsos positivos y sin jugadas válidas.
- Repetición de una corrida sobre la misma carpeta.
- Nombres de carpetas y archivos con espacios y acentos.
- Cancelación y cierre normal de la revisión.
- Creación y devolución del paquete QA.

Por cada problema, anotar qué esperaba, qué ocurrió y con qué video sucedió. No hace falta enviar el video dentro del paquete QA; si el equipo necesita reproducir un fallo visual, debe solicitar ese archivo por el canal acordado.

## Validación realizada antes de entregar

- Suite completa: 134 pruebas aprobadas.
- Diagnóstico portátil correcto para Tkinter, NumPy, OpenCV, Cortador, FFmpeg y FFprobe.
- ZIP comprobado completamente, sin entradas corruptas.
- Sin videos, secretos, `DatosQA`, pruebas, cachés, Torch ni Ultralytics dentro del ZIP.
- Runtime `pythonw.exe` con firma válida de Python Software Foundation.
- Aplicación abierta correctamente desde una extracción limpia fuera del proyecto.
- `git diff --check` sin errores; solamente avisos de conversión LF/CRLF en archivos existentes.

La validación pendiente es la ejecución real en la computadora del QA y el análisis del primer paquete de evidencia devuelto.
