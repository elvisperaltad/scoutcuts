# Acceso desde teléfonos y tabletas

> **Estado (2026-11-04): la PWA descrita en este documento ya está construida y
> desplegada en producción en `https://scoutcuts.com`.** Login por código de acceso,
> subida con progreso, lista de trabajos con auto-refresco, descarga, instalable
> (manifest + service worker). Verificado con navegador real contra el dominio real
> sobre HTTPS. Detalle técnico en `BITACORA.md` y en la skill `cortador-turnos`. El
> análisis y las decisiones de este documento siguen vigentes como justificación de
> por qué se construyó así; lo que describían como plan en las secciones siguientes ya
> es el estado actual, no una propuesta.

Pregunta del propietario: los scouts quieren usar el sistema desde iPhone, iPad y Android.
¿Conviene procesar el video en el servidor o construir aplicaciones nativas para cada
plataforma?

## Recomendación

Procesar en el servidor y entregar la interfaz como una aplicación web instalable (PWA).
No construir aplicaciones nativas en esta etapa.

## Por qué no aplicaciones nativas ahora

- Serían dos desarrollos distintos, uno para iOS y otro para Android, más el mantenimiento
  del escritorio que ya existe.
- Apple exige revisión de App Store, cuenta de desarrollador de pago y tiempos de aprobación.
  Cada corrección del detector quedaría esperando autorización.
- El motor actual depende de OpenCV y FFmpeg en Python. Llevar eso a un teléfono implica
  reescribirlo, no portarlo.
- El trabajo pesado en el teléfono consume batería y se degrada mucho en equipos de gama baja.
- Un cambio del algoritmo obligaría a que cada scout actualice su aplicación. Hoy todavía
  estamos afinando la detección con los datos del QA, así que necesitamos poder corregir sin
  depender del usuario.

## Por qué el servidor es la opción correcta

- El motor ya existe, está probado con 134 pruebas y no hay que reescribirlo.
- Una sola interfaz web sirve para iPhone, iPad, Android, Windows y Mac.
- Las mejoras del detector llegan a todos de inmediato, sin actualizaciones ni tiendas.
- Centraliza el control de usuarios, licencias y dispositivos que ya estamos montando en
  `scoutcuts.com`.
- Las etiquetas de cada corrida llegan solas, en lugar de depender de que el usuario envíe un
  paquete manualmente como hace hoy el QA.
- El teléfono solo graba, sube y reproduce. Eso sí lo hace bien cualquier equipo moderno.

La aplicación de escritorio portátil no se tira: sigue siendo útil para el QA, para trabajar
sin internet y para videos muy pesados.

## Medidas reales, no estimaciones

Tomadas el 2026-11-03.

En el equipo de desarrollo:

- Detección de candidatos sobre el video de 70.9 s a 1024×576: 3.56 s, unas 20 veces más
  rápido que el tiempo real.
- Corte y unión de tres tramos: 0.84 s, porque se copia el video sin recodificar.

En el servidor actual (`144.202.57.21`, un núcleo, 950 MiB de RAM):

- Decodificar 30 s de 720p: 1.39 s.
- Recodificar 30 s de 720p con x264: 16.35 s, es decir 1.83 veces el tiempo real.
- Cortar sin recodificar: 0.08 s.

Lectura de estos números: cortar es casi gratis porque no se recodifica. Lo que cuesta es
decodificar para detectar. Un video de 10 minutos debería analizarse en aproximadamente uno a
tres minutos en este servidor, procesando de uno en uno.

## Limitación honesta del servidor actual

Un núcleo y 950 MiB de RAM alcanzan para la primera etapa, pero no para varios scouts
trabajando a la vez. Con dos o tres videos simultáneos la cola se hará evidente.

Además hay un problema de espacio: quedan unos 16 GB libres y los videos reales de este
proyecto pesan entre 8 y 134 MB cada uno. Subir material sin borrar nada llena el disco rápido.

Decisiones que esto obliga a tomar:

1. Procesar en una cola de un trabajo a la vez y mostrar la posición al usuario.
2. Borrar el video original automáticamente poco después de entregar el resultado, con un
   plazo corto y visible para el scout.
3. Ampliar el servidor cuando haya usuarios reales. Un plan con más núcleos y memoria es
   barato comparado con desarrollar aplicaciones nativas.
4. Mover el almacenamiento de videos a almacenamiento de objetos si el volumen crece.

## Lo que el teléfono sí debe hacer

- Grabar o elegir el video.
- Subirlo con reanudación, porque las conexiones móviles se cortan.
- Mostrar el progreso del análisis.
- Permitir la revisión de candidatos dudosos con botones grandes, no con teclas.
- Reproducir y descargar el resultado.
- Instalarse en la pantalla de inicio como una aplicación.

## Lo que el servidor debe hacer

- Autenticar al scout y validar su licencia.
- Recibir la subida y ponerla en cola.
- Ejecutar detección, revisión y montaje con el mismo motor actual.
- Entregar el resultado por descarga protegida.
- Registrar las etiquetas para seguir mejorando el detector.
- Eliminar el material según la política de retención.

## Consideración de privacidad

Hoy el video nunca sale de la computadora del usuario. Con el servidor sí sale. Esto importa
porque se graba a menores en academias. Antes de abrir el servicio hay que definir y mostrar:
cuánto tiempo se conserva cada video, quién puede verlo, cómo se borra y qué consentimiento
dio la academia. La opción de escritorio sigue disponible para quien no quiera subir nada.

## Orden sugerido

1. Terminar la API de usuarios, licencias y descargas que ya está planificada. **Hecho.**
2. Añadir subida de video, cola de trabajos y entrega del resultado. **Hecho.**
3. Publicar la interfaz web instalable. **Hecho y en producción (2026-11-04).** Falta
   que un QA real la pruebe desde su propio teléfono y devuelva evidencia.
4. Medir tiempos reales con material de scouts antes de prometer capacidad.
5. Ampliar el servidor cuando los números lo justifiquen.
6. Evaluar aplicaciones nativas solo si aparece una necesidad que la web no cubra, como grabar
   con guías en pantalla o trabajar completamente sin conexión.
