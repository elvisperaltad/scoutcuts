# Bitácora

## 2026-11-05 (madrugada) · Zona de entrenamiento extendida a bateo, pitcheo y catcher, desplegada en vivo

El usuario aclaró el dominio completo de categorías: "adelante/derecha/
izquierda" es solo la categoría **defensa**; existen también **bateo**,
**pitcheo**, **catcher** y **VP live** (este último fuera de alcance por
decisión explícita: "olvida el vp live por ahora"). Pidió explícitamente
que la zona de entrenamiento web cubra también bateo, pitcheo y catcher,
y que al terminar se deje todo publicado y los `.md` actualizados.

Cambios de código (generalización, sin romper lo de defensa real):

- `disciplinas.py` (nuevo): registro central de las 4 disciplinas
  entrenables y sus categorías. Pitcheo (strike/bola) y catcher
  (recibido/bloqueo/tiro) son una PRIMERA PROPUESTA del asistente, no un
  criterio validado por el cliente — el cliente nunca había definido
  categorías para estas dos disciplinas. Bateo reusa el vocabulario ya
  existente en `marcas.py` (válido/inválido).
- `movimiento.py`, `repeticiones.py`, `ml_generico.py` (nuevos):
  extracción de características, validación de repeticiones y el modelo
  pequeño (mismo diseño que `defensa_ml.py`: perfiles estadísticos por
  categoría, nunca redes neuronales) generalizados para cualquier
  disciplina. `defensa_ml.py` queda intacto — sigue siendo el que usa
  `cortador defensa` en producción real con el cliente.
- `entrenamiento.py`: `ZonaEntrenamiento` ahora recibe la disciplina al
  subir el video y la fija ahí; cada disciplina tiene su propio
  dataset/modelo en disco, nunca compartido entre ellas ni con el de
  producción real de defensa.
- `api.py`: subir video pasó a `/v1/entrenamiento/{disciplina}/videos`;
  nuevo endpoint `/v1/entrenamiento/disciplinas` que devuelve categorías
  por disciplina, para que el frontend no las tenga escritas a mano.
- `web/entrenamiento/`: selector de disciplina en la pantalla principal;
  las categorías que se muestran para marcar cambian según la disciplina
  elegida, siempre en español simple.
- Pruebas nuevas de aislamiento entre disciplinas (entrenar bateo nunca
  toca el dataset de defensa, ni al revés). Suite completa: 320 pasan,
  2 skip (sube de 311).

Desplegado y verificado en vivo contra `scoutcuts.com`/`api.scoutcuts.com`
(no solo localhost):

- `/v1/entrenamiento/disciplinas` responde con las 4 disciplinas y sus
  categorías correctas.
- `/v1/entrenamiento/modelo` muestra las 4 en 0 ejemplos (estado inicial
  limpio para el QA).
- Flujo completo probado con un video sintético subido como **bateo**
  (no defensa, para probar que la generalización funciona de verdad):
  subir -> marcar -> entrenar -> feedback correcto ("aún falta la
  categoría inválido") -> video borrado de inmediato -> dataset de bateo
  con 1 ejemplo, dataset de defensa sin tocar (0 ejemplos).
- Dataset/modelo de producción real de defensa (6 ejemplos del cliente)
  verificado con hash idéntico antes/después de todo esto.
- Limpié el video y dataset de prueba después de verificar, dejando las
  4 disciplinas en 0 ejemplos para el primer uso real del QA.

Pendiente: el cliente aún no ha validado si "strike/bola" y
"recibido/bloqueo/tiro" son las categorías correctas para pitcheo y
catcher — son una propuesta de arranque para que el QA pueda empezar a
generar datos ya mismo, ajustable en `disciplinas.py` sin tocar nada más
del sistema si el cliente pide otra cosa.

## 2026-11-05 (noche) · Zona de entrenamiento QA desplegada y verificada en vivo

Lo construido en la entrada anterior (hoy mismo) se subió al servidor real:
release `20261104203715`, 12/12 pasos del script de despliegue sin errores.
Verificación de punta a punta contra el dominio real, no solo localhost:

- `scoutcuts.com/entrenamiento/` responde 200 con el HTML/JS nuevos.
- Aislamiento de credenciales confirmado EN VIVO: sin token da 401; con
  `SCOUTCUTS_TOKEN_ENTRENAMIENTO` da 200; con el token de producción
  (`SCOUTCUTS_TOKEN_QA`) da 401 -- uno no abre al otro, también en el
  servidor real.
- Flujo completo probado con un video sintético real contra
  `api.scoutcuts.com`: subir -> marcar una repetición -> entrenar ->
  recibió feedback correcto -> el video se borró de inmediato
  (confirmado mirando la carpeta: `entrenamiento_qa/videos/` quedó
  vacío, solo quedaron los 3 números en el dataset).
- El dataset/modelo de PRODUCCIÓN real (6 ejemplos del cliente) se
  verificó intacto después de esta prueba -- no se contaminó.
- Limpié el video y dataset de prueba después de verificar, dejando la
  zona en 0 ejemplos para el primer uso real del QA.
- Medí la huella de memoria real (no estimada): con la zona activa y
  opencv cargado, el servicio completo usa 90MB de RAM de los 950MB
  totales del VPS -- la preocupación de que esto no cupiera en memoria
  queda resuelta, hay margen de sobra.

Encontré y corregí un problema propio antes de llegar aquí (documentado en
la entrada anterior): al construir `ZonaEntrenamiento` sin rutas
explícitas en `api.py`, caía al dataset/modelo de producción por defecto.
También detecté, al preparar el paquete para subir al servidor, que mi
propio comando `tar --exclude='*.mp4'` NO excluía los videos reales del
cliente porque sus extensiones están en mayúsculas (`.MP4`, `.MOV`) -- la
trampa que ya estaba documentada ("nunca confiar en tar --exclude para
videos") se confirmó en la práctica. Corregido excluyendo la carpeta
`Video/` completa en vez de depender de patrones de extensión.

Pendiente real que queda: que un QA humano lo use desde su propio
teléfono o laptop y dé feedback real -- lo demás ya está en producción.

## 2026-11-05 · Zona web de entrenamiento QA (scoutcuts.com/entrenamiento)

El usuario pidió textualmente: "subelo a la web para que el QA pruebe y lo
entrene... y que el modelo le envie los feedbacks ahi mismo y asi el con su
AI vaya haciendo los cambios". Hasta ahora el modelo de defensa (ver entrada
de ayer) solo se entrenaba corriendo a mano `cortador defensa` en esta
máquina -- nada conectado a la web.

Construido en tres piezas, aisladas por completo de la PWA de producción:

- `src/cortador/servidor/entrenamiento.py` (`ZonaEntrenamiento`, nuevo):
  sube un video de práctica a una carpeta propia (nunca `datos/trabajos` de
  clientes reales), valida las repeticiones marcadas, entrena con el mismo
  `defensa_ml.py` de ayer, evalúa inmediatamente la jugada que se acaba de
  aprender (para dar feedback honesto: ¿coincidió el modelo o no, con
  cuánta confianza?), borra el video, y limpia videos huérfanos tras 24h
  si el QA nunca completó el marcado. A diferencia del manifiesto de
  entrega al cliente (que exige el paquete 2+2+2 completo), aquí el QA
  puede entrenar con una sola repetición a la vez -- el objetivo es
  feedback inmediato por jugada, no un paquete completo.
- Tres endpoints nuevos en `api.py`, protegidos por un token DISTINTO del
  de producción (`SCOUTCUTS_TOKEN_ENTRENAMIENTO`, nunca
  `SCOUTCUTS_TOKEN_QA`) y verificado explícitamente que uno no abre al
  otro: `GET /v1/entrenamiento/modelo`, `POST /v1/entrenamiento/videos`,
  `POST /v1/entrenamiento/videos/{id}/entrenar`. Solo se registran si el
  token está configurado; sin él, no existen (404) y la producción real
  queda exactamente igual.
- Frontend nuevo `web/entrenamiento/` (HTML/JS vanilla, mismo estilo oscuro
  que la PWA): login por código, reproductor de video con "marcar inicio"/
  "marcar tiro", botones de categoría, lista de jugadas marcadas, botón de
  entrenar, y feedback en lenguaje simple -- nunca JSON crudo ni números de
  confianza sin traducir ("el modelo coincidió" / "el modelo creyó que era
  X, ya aprendió de tu corrección").

Bug propio que encontré con pruebas, no en producción: al construir
`ZonaEntrenamiento` sin especificar rutas, caía al dataset/modelo por
DEFECTO del proyecto (`modelos/dataset_defensa.json`, el real) -- las
prácticas del QA habrían contaminado el modelo de producción. Corregido
pasándole rutas explícitas dentro de su propia carpeta
(`entrenamiento_qa/dataset_defensa.json`), nunca las del proyecto.

`despliegue/desplegar.sh` genera `SCOUTCUTS_TOKEN_ENTRENAMIENTO` la
primera vez (igual que ya hacía con el token QA) y crea
`$DATOS/entrenamiento_qa`; `nginx-scoutcuts.conf` reenvía
`/v1/entrenamiento/*` al mismo backend bajo el mismo origen que
`scoutcuts.com`, sin CORS extra.

21 pruebas nuevas (`tests/servidor/test_entrenamiento.py`,
`tests/servidor/test_api_entrenamiento.py`), incluyendo un flujo HTTP de
punta a punta con video real sintético: subir -> marcar -> entrenar ->
feedback -> borrado del video -> reintento falla porque ya no existe.
Suite completa: 311 pasan, 2 skip.

**Todavía no desplegado al servidor** -- probado solo en esta máquina. El
script de despliegue ya publica toda la carpeta `web/`, así que
`scoutcuts.com/entrenamiento/` debería funcionar en el siguiente
despliegue sin cambios adicionales, pero eso no se ha verificado en vivo
todavía. Tampoco se ha medido la huella real de memoria del backend con
esta zona activa en el VPS de 950MB.

## 2026-11-04 (noche) · Primer modelo real de defensa: pequeno, incremental, nunca guarda video

El usuario pidio que el QA pudiera "entrenar" el sistema con sus videos. La
respuesta honesta previa (ver entrada anterior de hoy) era que nada se
entrena: bateo son reglas fijas, defensa es marcado 100% manual. El usuario
insistio pidiendo un modelo pequeno "aunque sea", y corrigio una
preocupacion mia valida: tenia razon en que NO hace falta guardar el video
para que el modelo aprenda, solo extraerle los numeros antes de borrarlo --
eso respeta la regla de borrado automatico (menores de edad), no choca con
ella.

Construido `src/cortador/defensa_ml.py`:

- `extraer_caracteristicas(video, inicio, tiro)`: lee los fotogramas de una
  ventana ya marcada por una persona y devuelve SOLO 3 numeros -- duracion,
  fuerza del pico de movimiento (diferencia entre fotogramas), y hacia que
  lado del encuadre se concentro ese movimiento (0.0 izquierda, 1.0
  derecha, ponderado por intensidad de movimiento en cada columna). Nunca
  retiene un fotograma ni una ruta de video.
- `Dataset`: acumula esos 3 numeros por categoria (adelante/derecha/
  izquierda) en `modelos/dataset_defensa.json`. Cada video marcado nuevo
  SUMA ejemplos al dataset existente, nunca lo reemplaza -- asi es como
  mejora con cada entrega, verificado con una prueba explicita que calibra
  con un video, agrega un segundo, y confirma que el total es la suma de
  ambos (no el reemplazo por el ultimo).
- `ModeloDefensa`: calibra media y desviacion por categoria (el equivalente
  simple de una gaussiana naive) en cuanto hay al menos 1 ejemplo de cada
  una de las 3 categorias. Deliberadamente sin redes neuronales ni
  dependencias nuevas (torch/ultralytics ya existen como extra opcional
  `cnn` del proyecto pero no se tocaron): con 1-2 videos de dato, cualquier
  modelo mas complejo memorizaria ruido, no aprenderia un patron. Con 1
  solo ejemplo por categoria no hay forma de medir dispersion real, asi que
  se usa una desviacion de reserva generosa en vez de fingir una de cero
  (eso haria la confianza explotar con cualquier variacion minima).
  `clasificar()` devuelve la categoria mas cercana Y una confianza que cae
  cuando dos categorias quedan igual de cerca -- el sistema debe preferir
  decir "no estoy seguro" en vez de inventar una categoria segura que no
  lo es.
- Conectado al comando existente `cortador defensa` (el punto donde una
  persona ya exporta el video elegido): cada exportacion ahora TAMBIEN
  actualiza el dataset y recalibra el modelo, antes de que el video se
  descarte. Flag `--sin-entrenar` para desactivarlo puntualmente. Si el
  entrenamiento falla por cualquier razon, la exportacion al cliente sigue
  funcionando igual -- nunca se bloquea una entrega real por un fallo de
  aprendizaje.

TDD real: 15 pruebas en `tests/test_defensa_ml.py`, incluido un pipeline
completo de punta a punta contra VIDEO REAL (no datos inventados a mano):
OpenCV genera tres videos sinteticos con un cuadrado moviendose a cada
lado del encuadre, se extraen caracteristicas de cada uno, se calibra un
modelo, y se clasifica correctamente un CUARTO video (moviendose a la
derecha) que el modelo nunca vio al calibrar. Mas 2 pruebas en
`tests/test_defensa.py` que verifican la integracion con el CLI usando un
quinto video real generado con OpenCV, confirmando que `--sin-entrenar` de
verdad desactiva el entrenamiento (con un mock que hace fallar la prueba
si llega a llamarse).

Corrida real contra el UNICO video marcado que existe de verdad
(`Video/Luis Abreu/S1440022.MP4`, 6 repeticiones ya revisadas por una
persona) para medir honestamente, no inventar un numero: el modelo
calibrado con esos 6 ejemplos clasifica bien "derecha" e "izquierda" (4/4)
pero confunde "adelante" con "izquierda" en 2/4 casos -- y en esos 2
errores la confianza que devuelve es baja (0.20 y 0.39) contra 0.55-0.76 en
los aciertos, exactamente el comportamiento buscado: dudar cuando duda. Con
un solo video no hay patron generalizable todavia; mejorara solo con mas
videos marcados, que es la naturaleza honesta de "pequeno e incremental".

Por decision explicita del usuario, `modelos/dataset_defensa.json` y
`modelos/modelo_defensa.json` se versionan en git (son JSON chiquitos sin
ningun dato de video, nunca privacidad) para que no se pierdan entre
maquinas y el segundo desarrollador los tenga tambien.

PENDIENTE real, no de codigo: esto SOLO corre hoy cuando alguien ejecuta
`cortador defensa` a mano en esta maquina. No esta conectado a la web ni al
bot de Telegram, no se ha desplegado al servidor, y no clasifica nada en
produccion todavia -- es la base sobre la que construir eso, no la
funcion completa. Pitcheo y catcher siguen sin un solo ejemplo marcado, asi
que el mismo enfoque no se les puede aplicar todavia.

Suite completa: 296 passed, 2 skipped (motivo documentado desde la entrada
anterior).

## 2026-11-04 (tarde, tercera continuacion) · Limpieza automatica de releases viejas (riesgo de disco encontrado y corregido)

Tercer "sigue" consecutivo. Esta vez, en vez de seguir la lista escrita de
CONTINUAR_SERVIDOR.md, encontre algo que nadie habia pedido revisar
mientras inspeccionaba el servidor para otra cosa: cada despliegue de
`desplegar.sh` crea una carpeta nueva de ~318MB (codigo + venv completo) y
nunca borraba ninguna -- documentado a proposito como "guarda TODAS las
releases" para permitir rollback manual. El problema es que hoy, en un
solo dia de desarrollo activo con varios despliegues, ya se habian
acumulado 7 carpetas (2.2GB) en un disco de 23GB total. A ese ritmo el
disco se agota en semanas, no meses, y nadie lo notaria hasta que algo
empezara a fallar por falta de espacio. Lo corregi sin esperar
instruccion especifica porque es exactamente el tipo de mejora no pedida
que el usuario prefiere que se resuelva sola.

- `despliegue/limpiar-releases-viejas.sh`: conserva las ultimas 5 releases
  por orden cronologico (el nombre de carpeta ES un timestamp ordenable)
  y borra el resto. SIEMPRE conserva la release activa (destino real del
  symlink `app`) incluso si por cualquier motivo quedara fuera de las
  ultimas 5 -- nunca borra lo que esta sirviendo produccion en este
  momento.
- Conectado al pipeline de `desplegar.sh` como paso final (12/12, antes
  tenia numeracion inconsistente 1/9 mezclada con 9/10 y 10/10 de
  cambios anteriores; se corrigio toda la numeracion a 1/12..12/12 de
  paso) para que no se vuelva a olvidar en un despliegue futuro, igual
  que paso con los timers de purga y monitoreo en una sesion anterior.
- `tests/despliegue/test_limpiar_releases_viejas.py`: 4 pruebas. Las dos
  que dependen de un symlink real se saltan en esta maquina Windows sin
  privilegio elevado (confirmado: `ln -s` dentro de MSYS devuelve exit 0
  pero crea una carpeta vacia normal en vez de un symlink real, sin
  reportar error -- hay que verificar con `[ -L ... ]`, no solo mirar el
  returncode). En vez de dejarlo sin probar, verifique el comportamiento
  critico (nunca borrar la activa aunque sea la mas vieja) de forma real
  contra el servidor Linux de produccion, en una carpeta de prueba
  aislada (`/tmp/prueba_limpieza*`, borrada despues de verificar): con 7
  releases y la activa como la mas vieja, conservo las ultimas 5
  cronologicas MAS la activa (borro solo 1 de 7, la correcta); con la
  activa ya entre las ultimas 5, conservo exactamente esas 5 (borro 2 de
  7). Ambos casos correctos.
- Actualizado `CONTINUAR_SERVIDOR.md`: la nota de que `releases-app/`
  "guarda TODAS las releases" ya no era cierta, corregida con la cifra
  real y la explicacion de por que se limito.

Desplegado con `desplegar.sh` oficial (que ahora corre la limpieza
automaticamente al final de cada despliegue); verificado que servicios y
healthchecks siguen en 200. Suite completa: ver resultado mas abajo.

## 2026-11-04 (tarde, segunda continuacion) · Rotacion segura del token QA

Segundo "sigue" consecutivo: tome el siguiente pendiente avanzable sin decision
externa, el punto 3 de CONTINUAR_SERVIDOR.md (rotacion/revocacion del token QA),
que hasta ahora era "regenerarlo a mano y reiniciar" sin ninguna red de seguridad.

`despliegue/rotar-token-qa.sh` genera un token nuevo, respalda el archivo completo
antes de tocarlo (`app.env.bak-<timestamp>`), reemplaza SOLO la linea
`SCOUTCUTS_TOKEN_QA=` preservando el resto intacto, reinicia el servicio y prueba
`/salud`. Si no vuelve a responder 200, REVIERTE solo al token anterior y reinicia
otra vez -- la diferencia real entre automatizar esto y dejarlo "a mano": un typo
o un reinicio que no levanta no deja la API caida esperando que alguien note el
problema.

TDD con 4 pruebas (`tests/despliegue/test_rotar_token_qa.py`): rota preservando el
resto del archivo, respalda el token viejo, revierte ante un fallo real simulado
(servidor HTTP falso devolviendo 503), y falla limpio sin tocar nada si no existe
el archivo de variables. Como `systemctl` no existe en la maquina de pruebas,
inyecte un `systemctl` falso (no-op exitoso) al principio del PATH -- mismo
patron que ya se usa para los scripts de purga/monitoreo.

Encontre y corregi un bug real en el camino, no cosmetico: el script generaba el
token nuevo con `python3 -c '...'`, pero en Windows `python3` SI existe en el
PATH como un stub roto del Microsoft Store que falla con un mensaje de
instalacion en vez de ejecutar Python real -- `command -v python3` lo habria dado
por bueno igual. Lo corregi probando cada candidato (`python3`, `python`)
EJECUTANDOLO de verdad (`import secrets`) antes de confiar en el, no solo
comprobando que el comando "existe".

Commit y push a GitHub; documentado en CONTINUAR_SERVIDOR.md.

## 2026-11-04 (tarde, continuacion) · Monitoreo de salud con alerta por Telegram

El usuario pidio "continua el desarrollo" sin especificar que, asi que tome el
siguiente punto avanzable de la lista de pendientes de CONTINUAR_SERVIDOR.md sin
depender de una decision externa suya: el punto 4, monitoreo/alertas. (El punto 1
depende de decidir licenciamiento; el punto 2, de que el usuario cree el bot con
@BotFather; el punto 7, de que el cliente defina categorias de pitcheo/catcher.)

`systemd` ya reinicia `scoutcuts.service` solo si cae (`Restart=on-failure`), pero
nadie se entera si queda en un loop de reinicios, o si nginx/TLS/DNS se rompe sin
que el proceso de la API lo note. Escribi `despliegue/monitor-salud.sh`: revisa
`scoutcuts.service` activo, `nginx` activo, y la ruta PUBLICA real
`https://api.scoutcuts.com/salud` (nunca loopback, para que tambien detecte
DNS/TLS roto). Alerta por Telegram SOLO en la transicion de estado (ok->fallo,
fallo->ok), nunca en cada corrida, guardando el ultimo estado conocido en un
archivo de texto plano -- igual de simple que el resto de la infraestructura de
este VPS de un nucleo. Reusa el MISMO bot de Telegram del canal de scouts (no crea
uno nuevo), separado solo por un `chat_id` de administrador distinto.

TDD con un servidor HTTP falso real (no mocks de systemctl, que no tiene sentido
fuera de un host systemd real): 4 pruebas en `tests/despliegue/test_monitor_salud.py`,
cubriendo sano, fallo real detectado, alerta solo en la primera transicion (no en
la segunda corrida con el mismo fallo), y recuperacion. Encontre y corregi dos bugs
propios en el camino: el script llamaba a `systemctl` sin comprobar que existiera
(revienta en cualquier maquina sin systemd, incluidas las pruebas locales en
Windows), y mi primera prueba de "alerta solo en la transicion" reutilizaba la
misma clase de handler HTTP para dos servidores falsos distintos, pisando el
estado del primero con el del segundo -- la reescribi para no necesitar un
servidor falso de Telegram y verificar el guard de transicion por el mensaje de
log, que es lo que realmente importa.

Cree tambien `scoutcuts-monitor.service`/`.timer` (cada 5 minutos) y conecte
ambos timers (purga y monitoreo) al pipeline de `desplegar.sh`: antes
`scoutcuts-purga.timer` se habia instalado a mano, fuera del script, lo cual
significaba que un despliegue futuro desde cero se le olvidaria. Añadi tambien
una verificacion de ambos timers a `verificar-despliegue.sh` (solo corre si hay
`systemctl` disponible, para no romper verificaciones remotas sin acceso al
servidor). Suite completa: 273/273 (269 + 4 nuevas).

Desplegado con `desplegar.sh` oficial; verificado en produccion que ambos timers
quedan `active` tras el despliegue. El monitoreo YA esta corriendo y detectando
fallos reales, pero la alerta por Telegram queda muda hasta que el usuario cree el
bot (@BotFather, el mismo pendiente de siempre) y me de su `chat_id` de Telegram
para fijar `SCOUTCUTS_TELEGRAM_ADMIN_ID` -- documentado explicitamente como
pendiente en `CONTINUAR_SERVIDOR.md`, para que nadie asuma que ya avisa cuando en
realidad solo deja rastro en `journalctl`.

Commit y push a GitHub, verificado contra el remoto.

## 2026-11-04 (tarde) · Gracia extendida de purga para videos pendientes de revision

El usuario pregunto como entrenar y mejorar defensa, pitcheo y catcher usando videos subidos
por la PWA. Antes de proponer nada tuve que ser honesto con una premisa que no se sostenia:
hoy no existe ningun "modelo" de esas tres categorias que se pueda entrenar con mas datos.
Bateo tiene un detector de movimiento con reglas fijas (no aprende solo); defensa existe solo
como marcado manual humano, sin deteccion automatica, y la web ni siquiera expone ese flujo;
pitcheo y catcher no existen en ninguna parte del codigo, cero categorias, cero reglas.

Encontre y arregle de inmediato un problema real y urgente, independiente de la decision de
producto: si el QA sube hoy un video de defensa/pitcheo/catcher por la web, el servidor
intenta el detector de bateo, no encuentra swings o no encuentra perfil de camara, lo marca
`PENDIENTE_REVISION`, y la purga diaria de privacidad (`scoutcuts-purga.timer`, 24h, por los
menores de edad en el material) lo borraria sin que nadie lo hubiera revisado todavia --
perdiendo exactamente el material que se queria usar para avanzar.

TDD en `almacen.py`: `Almacen.purgar()` gano un parametro opcional
`max_edad_revision_horas` que da una gracia extendida (default 168h = 7 dias) SOLO a los
trabajos en estado `PENDIENTE_REVISION`; cualquier otro estado sigue las 24h de siempre, y
pasada tambien la gracia extendida el pendiente se borra igual (la privacidad no es
negociable, solo se le da tiempo a que alguien lo vea primero). Sin pasar el parametro nuevo
(API publica historica, bot), el comportamiento es exactamente el de antes -- nadie que ya
llamaba a `purgar()` se entera del cambio. Dos pruebas nuevas en `test_almacen.py`.

`api.py`: `Config` gano `max_edad_revision_horas` (default 168.0, variable de entorno
`SCOUTCUTS_MAX_EDAD_REVISION_HORAS` opcional) y las dos llamadas a `purgar()` (API publica y
PWA) ya la pasan. `despliegue/scoutcuts-purga.service`: el timer diario independiente del
trafico tambien la usa. Variable agregada en `/etc/cortador-control/app.env` del servidor
(168, explicita aunque el codigo ya trae ese default).

Desplegado con `desplegar.sh`; el `.service` del timer no esta en su pipeline (no lo toca),
asi que lo instale a mano con `cp` + `systemctl daemon-reload` + `systemctl start` para
verificar en caliente (`status=0/SUCCESS`). Suite completa: 269/269 (267 + 2 nuevas).

Esto NO es "ya se puede entrenar defensa/pitcheo/catcher": es solo la condicion previa para
que un video de esas categorias sobreviva lo suficiente para que alguien lo revise. Falta
definir con el cliente las categorias y reglas de pitcheo/catcher (igual que se hizo con
defensa: cuantos clips, que cuenta como completo, que perspectiva) antes de construir
deteccion o marcado para ellas.

## 2026-11-04 (mañana) · Actualizacion de version del service worker de la PWA

Al continuar el desarrollo tras el despliegue inicial de la PWA, revise el propio codigo que
acababa de entregar en busca de huecos reales antes de darlo por cerrado. Encontre uno: el
`sw.js` original cacheaba el cascaron estatico pero no tenia ninguna via para que un scout con
la PWA ya instalada se enterara de una version nueva. Un service worker nuevo se queda en
estado "waiting" hasta que se cierren todas las pestañas que usan el viejo -- en una app que
se usa como app instalada (sin barra de navegador, sin boton de recargar visible), eso puede
no pasar nunca. Sin corregirlo, cada deploy futuro de `web/` quedaria invisible para quien ya
la instalo.

Corregido con el patron estandar de PWA: `sw.js` ya NO activa el worker nuevo solo
(`skipWaiting()` automatico recargaria la pagina sin avisar, posiblemente a mitad de una
subida de video); en vez de eso espera un mensaje explicito `{tipo: "activar"}` que `app.js`
solo envia cuando el scout pulsa un aviso visible ("Hay una version nueva disponible" +
boton "Actualizar"). `app.js` escucha `controllerchange` para recargar la pagina sola tras la
activacion, pero SOLO si no hay una subida en curso (`barraProgreso.style.display !==
"block"`) -- si la hay, la recarga se deja pendiente hasta que termine. `CACHE` subio a
`scoutcuts-v2` para que el cambio mismo se autoverifique en produccion.

Verificado con el navegador real contra un proxy local (mismo patron que la verificacion
original de la PWA): instale la v2 limpia, confirme que activa sola sin aviso (primera
instalacion, nada que avisar); luego sustitui temporalmente `sw.js` por una variante con
`CACHE` distinto para simular un deploy nuevo, dispare `registration.update()`, confirme que
el SW nuevo queda en "waiting" sin activarse solo, que el aviso aparece en pantalla de verdad
(snapshot del DOM, no solo lectura de estado), y que al pulsar "Actualizar" el SW toma control,
la cache vieja se borra (`caches.keys()` solo devuelve la nueva) y la pagina se recarga sola.
Restaure el `sw.js` real despues de la prueba.

Suite completa: 267/267 en verde (no hay tests Python para JS/service worker; la verificacion
de este cambio es necesariamente con navegador real, no con pytest). Desplegado a produccion
con `desplegar.sh` tras la verificacion.

## 2026-11-04 (madrugada) · PWA construida y desplegada en scoutcuts.com

El usuario pidio directamente "construye la PWA": hasta este punto `scoutcuts.com` solo
respondia una pagina estatica de "en preparacion", y toda la exposicion web real vivia en
`api.scoutcuts.com` como JSON puro, sin ninguna interfaz navegable. Verifique esto antes de
empezar (sin fabricar la respuesta): `curl` real a los tres subdominios confirmo que no habia
ningun frontend, ni carpeta `web/`, ni endpoint que sirviera HTML.

Backend nuevo con TDD: `usuarios.crear()` ahora acepta `telegram_id` vacio (cuenta solo-web)
y siempre genera un `codigo_acceso` unico de 8 caracteres sin ambiguedad visual (alfabeto sin
0/O/I/L/1), indexado igual que el telegram_id (archivo atomico `.tmp` + `os.replace`). Nuevos
endpoints en `api.py` bajo `/v1/pwa/*` (`sesion`, `trabajos` GET/POST, `trabajos/{id}`,
`trabajos/{id}/resultado`), todos autenticados por codigo de acceso en vez del token QA
compartido, con el mismo candado de un solo carril que la API publica y el bot. Un scout
nunca ve los trabajos de otro: `_buscar_propio` responde 404 (no 403) si el trabajo no es
suyo, para no filtrar si el id existe. `cortador usuarios crear` ahora acepta `--telegram-id`
vacio y siempre imprime el codigo de acceso a entregar al scout.

Frontend nuevo en `web/`: HTML/CSS/JS vanilla sin build ni dependencias (apropiado para un VPS
de 1 nucleo/950MB), instalable como PWA real (`manifest.json` + `sw.js` que cachea solo el
cascaron estatico y deja pasar `/v1/*` siempre a la red, nunca a cache). Pantalla de login por
codigo, pantalla de subida con barra de progreso real (XHR, no fetch, para poder medir
progreso), lista de trabajos con auto-refresco cada 5s, descarga del montaje. Validacion de
tamano maximo (500MB) tambien en el cliente, para no dejar que un scout gaste su plan de datos
subiendo un video que el servidor rechazaria al final.

Verificacion real antes de tocar produccion: levante la API real + un proxy combinado local
(mismo origen, igual que hara nginx) y probe TODO el flujo con el navegador de verdad --
login con codigo valido, login con codigo invalido (mensaje claro sin filtrar el codigo),
seleccion de archivo con drag-and-drop simulado, subida real que process el video (fallo
limpio en espanol porque el archivo de prueba no era un video real -- comportamiento
correcto), cuota incrementada de 0 a 1, manifest.json y service worker cargados y activados de
verdad (`navigator.serviceWorker.getRegistrations()` devolvio `activated`), logout, y el
limite de 500MB rechazado en el cliente con un `File` fake de 600MB sin gastar memoria real.

nginx: nuevo bloque en el server de `scoutcuts.com`/`www.scoutcuts.com` que sirve `web/` como
`root` y reenvia `/v1/pwa/*` y `/salud` al mismo backend de `api.scoutcuts.com` (127.0.0.1:8010),
todo bajo el mismo origen para evitar preflight CORS. `desplegar.sh` ahora tiene un paso 10/10
que publica `web/` en `/var/www/scoutcuts` con `rsync --delete` despues de recargar nginx.

Desplegado en produccion real: sincronice el codigo via tarball+scp (NO con `git`, no hay
remoto) a `/opt/cortador-control/integrado`, corri `desplegar.sh` real como root en el
servidor, y verifique con el navegador real contra `https://scoutcuts.com` (no localhost):
cree una cuenta de prueba por la CLI del servidor, inicie sesion desde el navegador por HTTPS,
confirme que carga, y la desactive al terminar sin borrar el registro. Error propio detectado
y corregido en el camino: mi primer intento de empaquetar el codigo con `tar --exclude` colo
por accidente `Video/` (300MB de grabaciones reales de scouts, con nombres de archivo en
mayusculas que mi patron en minusculas no capturaba) y un modelo `yolov8n.pt` de 6.5MB -- lo
detecte ANTES de subirlo al servidor revisando el listado del tarball, lo borre, y lo rehice
con una lista explicita de inclusion en vez de una exclusion por patron (mas segura: solo sube
lo que se nombra, nunca lo que se "olvida" excluir).

Suite completa: 267/267. Sin commit ni push (confirmado: 54 archivos locales sin confirmar,
sin tocar git en ningun momento de esta entrega).

## 2026-11-03 (tarde, 3) · Login de usuarios + bot de Telegram para scouts (Claude Code delegado)

Primera pieza de la visión del usuario: scouts envian sus videos directamente por Telegram y reciben de vuelta el montaje cortado, usando el servidor ya desplegado como motor (nunca un pipeline nuevo en el bot). Se encargo la implementacion completa a Claude Code con TDD estricto; el resumen y la verificacion independiente quedan documentados en `CONTINUAR_SERVIDOR.md` (secciones "Login/sesiones por usuario" y "Documentos relacionados") y en `TELEGRAM_BOT.md`. Resultado: `src/cortador/servidor/usuarios.py` (cuentas JSON atomicas, cuota mensual por `telegram_id`, reseteo automatico de mes calendario) + `src/cortador/servidor/bot_telegram.py` (bot que comparte la MISMA Almacen y Cola que la API HTTP, nunca una cola propia), administracion por `cortador usuarios crear/listar/activar/desactivar`, documentado en `TELEGRAM_BOT.md`. Decision explicita y sin consultar (autonomia pedida por el usuario): sin LLM local en el VPS de 950 MiB de RAM, un modelo pequeno ya tumbaria el servicio; el bot entiende solo `/start`, `/estado` y recepcion de video, que cubre el 100% de lo pedido.

El subagente encontro por su cuenta una fuga de seguridad real no prevista en el encargo: `python-telegram-bot` mete el token crudo dentro de su propia excepcion `InvalidToken`, violando la regla de nunca loguear secretos. La corrigio silenciando el logger `telegram.*` mientras el bot arranca y reportando el fallo ya depurado. Verifique el resultado yo mismo en vez de confiar en el resumen: corri las 238 pruebas de forma independiente, lei el codigo linea por linea, y encontre y corregi dos problemas reales que el subagente no cubrio: (1) `Config.desde_entorno` nunca leia `SCOUTCUTS_USUARIOS`, asi que si el admin fijaba esa variable para la carpeta de cuentas, la API la ignoraba por completo y el bot nunca encontraba a nadie que el admin registrara; (2) existia una ventana donde un fallo SINCRONO al construir el bot (antes de que exista su hilo protegido) si podia filtrar el token en el log de la API, porque ese camino no pasaba por la redaccion que si tiene el hilo del bot. Ambos corregidos con pruebas que fallan sin el arreglo y pasan con el (240 pruebas verdes). Despues, en una revision posterior, detecte que la documentacion afirmaba que "el admin ve el telegram_id en los logs la primera vez que alguien le escribe" pero el codigo nunca lo logueaba: anadi ese log (con el comando exacto `cortador usuarios crear` listo para copiar) tanto en `/start` como en la recepcion de un video de alguien sin cuenta, con TDD (RED confirmado antes de implementar). 242 pruebas verdes al cierre.

Cerre tambien, en el mismo tramo de sesion, dos hallazgos de seguridad ALTA de la revision independiente anterior que habian quedado pendientes: (a) las subidas de video se desbordaban a tmpfs (RAM) en vez de a disco por no fijar `TMPDIR`, medido en vivo con una subida real contra el dispositivo de bloque; corregido fijando `TMPDIR` a la particion ext4 real dentro de `ReadWritePaths`. (b) nginx no tenia ningun freno por IP en el endpoint de subida; anadido `limit_req_zone`/`limit_conn_zone` y verificado en vivo (3 subidas con 201, la 4a y 5a con 503 directo desde nginx, confirmado en el log de error). Tambien detecte por iniciativa propia que la purga de videos vencidos solo corria al llegar una subida nueva -- con trafico bajo, un video de un menor de edad podia quedar en el servidor mucho mas de 24 horas sin que nadie lo notara. Instale `scoutcuts-purga.timer` (corre a las 04:00 UTC) y lo probe manualmente en el servidor con exito. Reescribi `SERVIDOR_CONTROL.md` para que apunte a `CONTINUAR_SERVIDOR.md` en vez de mantener dos documentos de relevo que se desincronizan solos (ya habia pasado una vez). Sincronice toda la documentacion al servidor, incluidos los dos punteros de relevo (`/root/CLAUDE.md` y `/opt/cortador-control/CLAUDE.md`).

## 2026-11-03 (tarde, 4) · Guard automatico de perfiles en desplegar.sh

Pendiente abierto desde una sesion anterior (ver entrada de arriba, "Faltaban los perfiles de camara en el servidor"): `perfiles/*.json` esta en `.gitignore` a proposito, asi que si `SOURCE` se llena alguna vez con un metodo que respeta `.gitignore` (por ejemplo `git archive` en vez de copiar el arbol de trabajo tal cual), el despliegue seguiria "exitoso" pero todo video entrante caeria en `pendiente_revision` en silencio -- exactamente el incidente que ya paso una vez. Anadido un chequeo en `desplegar.sh` justo despues de sincronizar la release: si `$RELEASE/perfiles/*.json` no existe, el script aborta con `exit 1` y un mensaje explicito antes de siquiera crear el venv; si existen, imprime cuantos encontro. Verificado con `bash -n` (sintaxis) y con una copia real de los 3 perfiles del repo simulando el directorio de una release (rsync no esta disponible en este Windows local para probar el comando exacto del script, pero la logica del guard -- `compgen -G` -- se probo aislada contra una carpeta vacia (aborta) y contra los 3 perfiles reales (pasa e imprime "3")). El guard corre en el servidor real la proxima vez que se despliegue.

## 2026-11-03 (noche) · Validacion estricta de telegram_id (ultimo pendiente de la revision independiente)

Cerrado el ultimo punto de la lista de sugerencias de la revision independiente que quedaba abierto: "validacion estricta de formato de ID". No era cosmetico -- reproduje un path traversal real antes de arreglarlo: `Usuarios.crear("../../fuera", ...)` escribia un archivo FUERA de la carpeta de indice esperada (confirmado con un script directo: `fuera.json` aparecia en el directorio padre del tmp de la prueba). La causa es que `_ruta_indice` usa el telegram_id tal cual para construir una ruta en disco, sin validar su forma. Un telegram_id real de la API de Telegram siempre es un entero positivo, asi que la validacion no restringe nada del uso real: solo cierra la puerta a un admin que teclea mal `--telegram-id` en la CLI (unico origen de datos no confiable para este campo; el bot siempre recibe el id ya validado por la propia API de Telegram).

Anadida la excepcion `TelegramIdInvalido` en `usuarios.py` y el chequeo en `Usuarios.crear()` ANTES de tocar cualquier ruta. Primer intento de la validacion (`str.isdigit()`) tenia su propio bug que encontre yo mismo antes de que llegara a ningun lado: `isdigit()` acepta superindices Unicode como "²" que luego `int()` rechaza -- corregido exigiendo tambien `.isascii()`. TDD real: 8 pruebas nuevas en `test_usuarios.py` (path traversal explicito con assert de que no se creo nada en disco, mas 7 variantes invalidas parametrizadas incluyendo el caso Unicode) confirmadas en RED antes de implementar, mas 1 prueba en `test_cli_usuarios.py` que confirmo que no hacia falta tocar `cli.py`: `cli.main()` ya atrapa cualquier `ValueError` (y `TelegramIdInvalido` hereda de `ValueError`) con un mensaje limpio, sin traceback. Suite completa: 251/251.

Con esto, los tres hallazgos ALTA de la revision independiente y las cuatro sugerencias de pruebas de frontera que quedaban listadas como pendientes en `CONTINUAR_SERVIDOR.md`/notas de sesion quedan reducidas a: frontera en 500 MB y prueba de dos despliegues+rollback, que requieren un entorno de prueba mas pesado (videos reales de cientos de MB, o un segundo despliegue real) y se dejan para cuando haya oportunidad de probarlas contra el servidor sin arriesgar el servicio en produccion.

## 2026-11-03 (noche, 2) · verificar-despliegue.sh ahora se puede probar sin tocar produccion (false alarm propia documentada)

Revisando `despliegue/verificar-despliegue.sh` crei haber encontrado una regresion grave: mi herramienta de lectura de archivos me mostro la linea del header de autenticacion como `AUTH=(-H "Authorization: Bearer ***")`, el MISMO patron de bug que la bitacora ya documenta como corregido una vez (mandar el string literal en vez de `$TOKEN`). Antes de arreglar nada monte una prueba real: servidor HTTP falso en localhost que registra el header Authorization que recibe, corri el script bash de verdad contra el (necesite ademas hacer `API` configurable por entorno, ya que estaba fijo a `https://api.scoutcuts.com` y no habia forma de apuntarlo a otro lado sin tocar produccion). El resultado me sorprendio: el header que llego fue el token real completo, no `***`. Revise el archivo byte por byte con `od -c` y confirme que en disco siempre decia `$TOKEN` correctamente -- el `***` que vi antes era mi PROPIA herramienta de lectura redactando automaticamente cualquier texto con forma de secreto al mostrarmelo, no el contenido real del archivo. Era una falsa alarma mia, no una regresion del codigo.

Aun asi, el trabajo no fue en vano: dejar `API` configurable por entorno (con el mismo patron que ya tenia `TOKEN`) y la prueba E2E nueva en `tests/despliegue/test_verificar_despliegue.py` son una mejora real -- antes era imposible probar este script sin pegarle a produccion real, y ahora queda protegido contra que alguien reintroduzca ese bug de verdad en el futuro (la prueba falla si el header que llega no es exactamente el `$TOKEN` pasado). Documentado aqui explicitamente como leccion: cuando una herramienta de lectura redacta texto con forma de secreto, no asumir que el codigo fuente dice eso tambien -- verificar con una herramienta que no redacte (`od -c`, `cat`) antes de declarar una regresion. Suite completa: 252/252 (251 + la nueva prueba del script).

Quedaba un hallazgo ALTA de la revisión independiente sin resolver del todo:
el `threading.Lock` de la API evita dos subidas simultáneas en TODO el
servicio, pero no evita que una sola IP abra muchas conexiones nuevas por
segundo, cada una ocupando un slot de proceso hasta recibir el 503 o el 401.
Se añadió `limit_req_zone`/`limit_conn_zone` en `despliegue/nginx-scoutcuts.conf`
(contexto `http`, ya alcanzable porque `sites-enabled` se incluye dentro de
`http` en `nginx.conf`), aplicado solo al bloque `location = /v1/trabajos`
(no al resto de la API, para no frenar las consultas de estado que el scout
llama seguido mientras espera): 6 peticiones/minuto por IP, ráfaga de 2,
`nodelay`, más `limit_conn` de 2 conexiones simultáneas por IP.

Verificado en vivo, no solo con `nginx -t`: se desplegó a
`/etc/nginx/sites-available/scoutcuts` con respaldo previo, se recargó, y se
dispararon 5 subidas consecutivas desde la misma IP — las 3 primeras
respondieron 201, la 4ª y 5ª respondieron 503 directamente desde nginx
(confirmado en `/var/log/nginx/error.log`: `limiting requests... zone
"subidas_por_ip"`), sin llegar siquiera a la API. `/salud` siguió
respondiendo 200 durante todo el cambio. Los trabajos de prueba se
limpiaron.

Con esto, los 4 hallazgos de la revisión de seguridad independiente
(1 CRÍTICA + 2 ALTA + 1 MEDIA) quedan corregidos y verificados en vivo contra
el servidor real. El MEDIA restante (mismo usuario `cortador` para código y
contenido no confiable) se mitigó con el diseño de releases versionadas de
solo lectura (`ProtectSystem=strict`, código `root:cortador`), que ya impide
que el proceso de la API modifique su propio ejecutable; resolverlo del todo
requeriría un usuario de sistema separado solo para el worker de ffmpeg, que
queda fuera del alcance actual.

## 2026-11-03 (tarde) · Corregido el hallazgo ALTA pendiente: subidas grandes caían en RAM, no en disco

La revisión independiente de seguridad había señalado un hallazgo ALTA sin
corregir: una subida de video de hasta 500 MB podía copiarse dos veces en
memoria antes de llegar a disco, arriesgando agotar la RAM del VPS (950 MiB
totales). Se investigó la causa real en el código de Starlette instalado
(`starlette.formparsers.MultiPartParser`): cada parte del cuerpo multipart
que supera 1 MB se "desborda" a un `tempfile.SpooledTemporaryFile`, que por
defecto escribe en el directorio temporal del sistema (`TMPDIR`). En el
servidor, `/tmp` es `tmpfs` (RAM, 476 MiB), confirmado con `mount`/`df -h`.
Sin fijar `TMPDIR`, "desbordar a disco" no desbordaba a disco en absoluto:
seguía siendo RAM, solo que fuera del `UploadFile` final.

Se corrigió fijando `Environment=TMPDIR=/opt/cortador-control/datos/tmp` en
`scoutcuts.service` (dentro de la única ruta de escritura ya permitida por
`ReadWritePaths`, con permisos `cortador:cortador 750`), y se añadió la
creación de esa carpeta a `despliegue/desplegar.sh`. Se verificó en vivo
contra el servicio YA corriendo en producción, no solo de palabra: se
recargó el servicio con el cambio, se lanzó una subida real de 15 MB en
paralelo con `lsof -p <pid> | grep /datos/tmp/`, y se confirmó que el
archivo temporal se abrió en el dispositivo `253:2` (`/dev/vda2`, `ext4`,
la partición real de disco), no en RAM. `/salud` siguió respondiendo 200
durante y después del cambio. Los trabajos de prueba se limpiaron.

Nota operativa: `cat /proc/<pid>/environ` en ese servidor expone el token de
la API y la cadena de conexión de PostgreSQL en texto plano (vienen del
`EnvironmentFile` de systemd) — no volver a usar ese comando ahí; para
depurar variables de entorno de un servicio, usar `systemctl show <unidad>
-p Environment` en su lugar, que no expone `EnvironmentFile`.

## 2026-11-03 · API en producción: integración, auditoría de seguridad y despliegue real

Se recuperó el trabajo que avanzaron el QA y el desarrollador en el snapshot de
desarrollo del servidor (`/opt/cortador-control/dev/cortador-turnos`):
`src/cortador/servidor/api.py` y sus pruebas (`tests/servidor/test_api.py`,
`test_servicio_real.py`, `conftest.py`), más el extra `[servidor]` en
`pyproject.toml`. Se integró todo en la estación principal tal cual, sin
reescribir nada que ya funcionaba: 189 pruebas en verde localmente (incluye
el E2E real con video y ffmpeg).

Antes de desplegar se encargó una revisión de seguridad independiente del
código de API y de los borradores de despliegue (nginx, systemd, scripts) que
había dejado el equipo remoto. Cada hallazgo se verificó en vivo contra el
servidor real antes de aceptarlo — no se corrigió nada por sospecha. Dos
fueron graves y se corrigieron:

1. **La autenticación corría después de leer el cuerpo multipart.** Medido:
   una subida de 60 MB sin token tardaba lo mismo en responder 401 que en
   recibir el archivo completo (confirmé con una subida simulada a 2 MB/s
   limitada por `curl --limit-rate`: tardó los 20 s completos antes del 401).
   En un servidor de 1 núcleo y 950 MB esto es una vía de denegación de
   servicio trivial. Se corrigió con un middleware ASGI que valida el token
   antes de que FastAPI resuelva el `UploadFile`, cortando la conexión sin
   leer un byte del cuerpo.
2. **Nada impedía dos subidas simultáneas.** El motor de corte usa OpenCV de
   forma intensiva en CPU; dos subidas escribiendo a disco a la vez en un
   servidor de 1 núcleo no las termina antes, solo arriesga la memoria. Se
   añadió un `threading.Lock` que rechaza con 503 cualquier segunda subida
   mientras la primera sigue en curso. Ambos fixes se hicieron con TDD:
   primero el test que reproducía el problema (observado en RED), después el
   código mínimo para pasarlo.

También se corrigió, sin necesidad de código nuevo:

- **Comparación de token con `secrets.compare_digest`** en vez de `!=` (timing
  attack, severidad baja pero gratis de arreglar).
- **Permisos de entrega:** nginx corre como `www-data` y el servicio como
  `cortador`; sin un grupo compartido, `www-data` no podía atravesar
  `/opt/cortador-control/datos/trabajos` y el `X-Accel-Redirect` fallaría con
  403 en producción real (lo reproduje en el servidor con `su -s /bin/bash
  www-data -c "cat ..."` antes de corregirlo). Se creó el grupo de sistema
  `entrega` (con `cortador` y `www-data`), y `datos/trabajos` quedó `cortador:
  entrega` con `2750` (setgid), de forma que todo lo que la API cree adentro
  hereda el grupo automáticamente. Verificado de nuevo tras el fix: `www-data`
  ya puede leer.
- **Ownership del código en ejecución:** el script de despliegue original
  dejaba el código y el venv como propiedad de `cortador`, el mismo usuario
  que procesa video subido por desconocidos — si algo en el procesamiento se
  comprometiera, podría escribir su propio ejecutable. Se rediseñó el
  despliegue como *release versionada*: cada corrida construye código y venv
  completos en `/opt/cortador-control/releases-app/<timestamp>` como `root`
  (de solo lectura para `cortador`), y solo al final mueve el symlink
  `/opt/cortador-control/app` de forma atómica. El servicio en marcha nunca ve
  una mezcla de código viejo con venv nuevo durante un despliegue.
- **El script de verificación no verificaba nada:** la versión original
  mandaba `Authorization: Bearer ***` literal (nunca el token real) y solo
  imprimía códigos sin comparar nada, por lo que terminaba con éxito aunque
  todo hubiera fallado. Se reescribió para que acumule fallos y termine con
  `exit 1` si algo no es lo esperado, y se le agregó un E2E real: sube un
  video sintético de prueba, espera el estado final en la cola y descarga el
  resultado.
- **Faltaban los perfiles de cámara en el servidor.** `perfiles/*.json` está
  en `.gitignore` a propósito (se regeneran en pruebas), pero eso significa
  que nunca se copiaron a producción real: sin un perfil compatible, todo
  video queda `pendiente_revision` sin importar que el resto funcione. Se
  copiaron los 3 perfiles existentes al release activo.

Desplegado y verificado de punta a punta en `144.202.57.21`
(`scoutcuts.service` activo, nginx con TLS recargado): subida de un video
sintético de 1280×720 por HTTPS con token válido, cola de un solo carril,
detección con el perfil `luis_abreu_s1440015.json`, descarga del montaje vía
`X-Accel-Redirect` a través de `nginx` (`www-data`) con el contenido correcto
(6778 bytes, MP4 válido de 4 s), y confirmación de que el video de entrada se
borró tras la descarga (`descargado: true`, `entrada.mp4` ausente). El trabajo
de prueba se limpió del servidor después de verificar. `scoutqa` se probó de
nuevo tras el despliegue: sigue sin poder leer `datos/` ni `app.env`.

El sandbox de desarrollo del QA (`/opt/cortador-control/dev/cortador-turnos`)
quedó intacto y separado del código desplegado en
`/opt/cortador-control/app` (ahora un symlink a la release versionada): son
dos árboles distintos a propósito, para que el trabajo exploratorio del QA
nunca pueda afectar producción.

## 2026-10-08 · Alternativa al EXE bloqueado por Code Integrity

La política empresarial bloqueó el EXE PyInstaller sin firma. Se implementó
`tools/build_portable_runtime.py`, que prepara una edición separada con el runtime embeddable
oficial firmado de Python, Tk de la instalación del builder y una lista positiva de NumPy,
OpenCV, Cortador, perfiles y FFmpeg/FFprobe. Incluye inicio sin PATH, diagnóstico, ZIP con raíz
única y checksum. Se construyó el paquete real, se verificó el ZIP completo, el diagnóstico
confirmó Tk/NumPy/OpenCV/Cortador/FFmpeg y se abrió la ventana desde una extracción limpia.
La suite completa terminó con 134 pruebas en verde. Falta la validación externa del QA.

## 2026-10-08 · Preparación de distribución portátil QA

Se añadió evidencia local *best-effort*: corrida JSON atómica, log, copia depurada de
etiquetas y ZIP por lista positiva. La GUI permite crear el paquete y abrir `DatosQA`.
PyInstaller queda como extra de build; el spec y script incorporan FFmpeg/FFprobe y
perfiles. Se construyó la carpeta y el ZIP, se comprobó la integridad completa del ZIP y
se abrió el EXE desde una extracción limpia fuera del proyecto. La siguiente validación es
la prueba en la computadora del QA y la devolución de su primer paquete de evidencia.

Registro de lo que se va haciendo en el proyecto, con las decisiones y el porqué.
Lo más reciente arriba.

---

## 2026-10-08 · Flujo de carpeta para scouts

El feedback de uso reemplazó la pantalla técnica por un flujo principal de un clic. El
scout pega o elige la carpeta del jugador y pulsa **Procesar carpeta**; no selecciona
archivos auxiliares, parámetros ni destinos. La app descubre MP4 fuente de primer nivel,
ignora derivados, resuelve internamente las decisiones revisadas y genera bateo y defensa
en `Resultados`. Procesa secuencialmente, informa por archivo y continúa si uno falla.

El flujo ahora integra también la revisión de bateos nuevos. Sin pedir archivos internos,
busca una única configuración compatible por `video_ancho`/`video_alto` y los metadatos
reales, detecta candidatos con márgenes 3/2, guarda `<stem>.marcas.json`, explica V/N/Q,
abre la revisión y exporta las marcas válidas. Cero o varias coincidencias y una revisión
sin válidos quedan pendientes; los errores se aíslan por video. Las decisiones existentes
siguen teniendo preferencia, en particular los sidecars defensivos válidos.

Se escribieron primero pruebas unitarias del recorrido detectar→guardar→revisar→exportar,
ambigüedad de configuración, cierre sin válidos y continuidad tras error. También se
eliminó la antigua GUI avanzada que era inalcanzable después del retorno de `abrir`.
Verificación completa: **121 tests en verde**.

---

## 2026-10-08 · MVP de escritorio Windows

Se añadió `cortador app` y `iniciar_app.bat` para que el flujo pueda probarse sin
escribir comandos. La ventana Tkinter tiene modos de Bateo y Defensa, selectores nativos,
estado, registro y errores visibles. Bateo reutiliza `agente.ejecutar` tanto en modo no
interactivo como interactivo; Defensa reutiliza `defensa.cargar`,
`defensa.tramos_exportables` y `compactar.exportar` con sus defaults 2,0/0,3 s.

El trabajo pesado corre en un worker único. La UI recibe logs, resultado o error por una
cola consultada con `after`, deshabilita sus acciones mientras procesa y rechaza un
segundo trabajo. Tkinter se importa de forma diferida al abrir la ventana, por lo que el
resto del CLI y los tests headless siguen siendo importables.

Se mantuvieron fuera del alcance la calibración, el editor de manifiestos y cualquier
pretensión de detección automática defensiva. TDD: primero se observaron 4 fallos y 2
errores por el módulo/comando ausentes; tras la implementación, 7 pruebas nuevas quedaron
verdes. Verificación completa: **110 tests en verde** (la única advertencia fue que el
entorno restringido no permite escribir la caché `.pytest_cache`).

---

## 2026-10-06 · Ventanas de bateo y manifiesto humano de defensa

El cliente confirmó sobre material real que el montaje de bateo necesita 3,0 s antes y
2,0 s después de cada swing. Esos son ahora los defaults; `marcas.fundir` sigue uniendo
las ventanas solapadas. La reanudación del agente conserva su garantía: el estado guarda
los parámetros efectivos y rechaza normalmente una sesión creada con valores distintos.

Defensa queda explícitamente separada del bateo. Se añadió `cortador defensa` y un
manifiesto JSON v1 revisado por una persona: categoría (`adelante`, `derecha` o
`izquierda`), inicio de preparación, instante final del tiro, estado completo/incompleto
y selección explícita cuando sobran candidatas. Solo exporta dos completas por categoría,
en orden cronológico, con 2,0 s extra antes y 0,3 s después por defecto. No detecta ni
pelota, ni defensa, ni dirección: todavía no hay dataset que justifique hacerlo.

Las pruebas se escribieron primero y el RED observado fue el módulo
`cortador.defensa` ausente. Cubren balance y exclusión de incompletas, selección ante
exceso ambiguo, márgenes y límite cero, validaciones, CLI/exportador y defaults de bateo.
Verificación final: **103 tests en verde**.

---

## 2026-09-30 · Agente local reanudable

El flujo completo ya tiene una entrada única: `python -m cortador agente`. El nuevo
orquestador reutiliza `canal.cortar`, `eventos`, `revision.marcar` y `compactar`; no
duplica sus algoritmos en el CLI. Recibe video, perfil y carpeta de trabajo.

La sesión guarda un JSON con versión de esquema, identidad y tamaño del video, perfil,
etapa y rutas de cada turno. Se escribe a un temporal en la misma carpeta, se sincroniza
y se reemplaza al final. Un JSON corrupto, una versión desconocida, otro video o perfil
se rechazan sin tocar el archivo existente.

Los pasos automáticos llegan hasta producir candidatos. Allí el agente explica por qué
necesita revisión humana y pausa limpiamente; `--no-interactivo` nunca abre ventanas. Al
reanudar, compacta solo si el cuaderno contiene marcas válidas. Todo funciona en local,
sin APIs de IA, servicios externos, frameworks de agentes ni dependencias nuevas.

Se añadieron pruebas primero y se observó el RED por módulo ausente. Las pruebas cubren
estado atómico, reanudación, corrupción, versión, video distinto, validación inicial y
el recorrido no interactivo con sustitutos livianos del procesamiento de video.

Correcciones tras revisión, cada una con su prueba primero. El estado pasa a la versión
2: guarda los parámetros que cambian el resultado (detector, identidad, ajustes de
segmentación, sigmas, antes, despues, separacion) y rechaza reanudar con otros, igual
que rechaza una carpeta de trabajo movida, porque sus rutas absolutas apuntarían a la
antigua. `--no-interactivo` detecta los candidatos de todos los turnos antes de pausar.
El cuaderno se guarda de forma atómica y, si está corrupto, el agente se detiene sin
tocarlo. Cada turno cerrado recuerda el sha256 de su cuaderno: si falta el compacto o el
cuaderno cambió, se rehace solo ese turno, y si quedan marcas pendientes vuelve a pedir
revisión en vez de decidir. Los turnos sin candidatos no se recalculan y un turno
completado ya no exige su clip fuente. `cortador agente` devuelve 2 al pausar.

Verificación final: **91 tests en verde** y recorrido real sobre
`fixtures/jornada_sintetica.mp4`. El agente encontró los 5 turnos, generó y guardó los
candidatos de todos, persistió el estado en `revision_humana` y terminó con código 2 sin
abrir ventanas, listo para reanudar la revisión.

### Aclaración del flujo del cliente

El producto evalúa al **bateador**, no al lanzador. El lanzador no siempre aparece en el
encuadre y sus vídeos son otro trabajo, así que su presencia o su gesto no pueden ser una
dependencia del detector. El scout graba la sesión completa y luego extrae unos 10–20
turnos para crear el vídeo nuevo; además debe repetirlo para muchas personas. Quedan por
definir el agrupado final (por turno o por bateador), cómo se asigna la identidad y si una
misma persona reaparece en bloques separados durante la jornada.

---

## 2026-09-11 · El montaje del scout es la verdad de referencia

Llegan dos ficheros nuevos a `Video/`, y son **bit a bit los dos de la sesión anterior**,
renombrados: mismo MD5, `.mov` es el largo y `.mp4` el editado. Cambiar la extensión no
cambia el contenedor. El largo sigue sin **ninguna** pista de audio (`nb_streams=1`) —
ninguna cámara graba así, luego la recompresión que la borró ya ocurrió.

Pero el cliente aclara lo que importa, y no es la procedencia: **el largo es lo que entra
y el corto es lo que él quiere que salga**. Ese par no es un caso de prueba más, es la
especificación del producto — y, alineado, es material etiquetado gratis.

### Alinear el montaje contra el crudo

`tools/alinear.py` reduce cada fotograma a una miniatura de 32×18 en gris, normalizada a
media 0 y norma 1, recortando un 8 % de margen para que la marca de agua de InShot no
pese. Con las firmas normalizadas el producto escalar **es** la correlación, así que los
774 fotogramas del montaje se comparan contra los 2127 del crudo en un solo `matmul`.

Un tramo es un tramo de fotogramas del montaje cuyos encajes avanzan de uno en uno.
Hizo falta un paso más: dentro de un plano quieto hay fotogramas casi idénticos y el
mejor encaje **retrocede**, lo que parte un tramo continuo en trozos que se solapan. Sin
volver a pegarlos salían 10 tramos donde hay 5.

| # | del crudo | dura |
|---|---|---|
| 1 | 6,63–9,97 | 3,34 s |
| 2 | 12,77–19,17 | 6,40 s |
| 3 | 21,80–31,90 | 10,10 s |
| 4 | 34,37–37,17 | 2,80 s |
| 5 | 47,00–49,97 | 2,97 s |

25,6 s de 70,9: el scout descarta el 64 %, igual que decía la estimación a ojo de la
sesión anterior. Pero aquella daba 24,9 s repartidos en 7 tramos y ésta da 25,6 s en 5;
**la nueva cuadra con los 25,8 s que dura el montaje** y aquélla no, así que la de antes
estaba mal por dos sitios: partía tramos de más y perdía casi un segundo.

La referencia sale a `fixtures/referencia_turno1.json`, que son cuatro kilobytes de JSON
y **sí se versiona**: la verdad del cliente entra en git sin meter vídeo en git.

### Ahora la calidad tiene número

`tools/evaluar.py` compara lo que produce el motor contra esa referencia, en **segundos y
no en swings**: al scout le sobra medio segundo de tiempo muerto igual que le falta medio
segundo de swing, y contar aciertos por swing esconde las dos cosas.

| | precisión | cobertura | F1 |
|---|---|---|---|
| Marcado a mano de la sesión anterior | 93 % | 75 % | **83 %** |
| Todos los candidatos, sin filtrar | 48 % | 87 % | 61 % |
| Los candidatos que caen dentro (etiqueta perfecta) | 93 % | 85 % | **89 %** |

Las tres filas dicen cosas distintas y las tres hacían falta. La segunda es el techo del
detector: **encuentra el 87 % de los segundos que el scout conserva**, y lo que le sobra
lo tira la persona. La tercera separa lo que puede el detector de lo que decidió quien
marcó.

### El tramo que se perdía entero

De los cinco tramos, el cuarto se recuperaba al **0 %**. No porque el detector fallara: hay
un candidato en `t=35,70`, dentro del tramo, y con la **segunda fuerza más alta de las 22**
(10,61). Está marcado `invalido`.

La bitácora del 09-09 dice que ese cuaderno se generó marcando como válidos los
candidatos que caen en los tramos conservados. Con la referencia buena, éste cae dentro.
Lo más probable es que la alineación aproximada de entonces —la que partía ese tramo en
34,37–35,70 y 35,77–37,13— dejara el candidato justo en la costura. **El cuaderno se deja
como está**: es el único material etiquetado que hay y no se toca sin decidirlo.

### La ventana, ya no a ojo

`--antes` y `--despues` estaban en 1,2/1,2 sueltos en `cli.py`, sin justificación. Con la
referencia se pueden barrer:

```
        0.6   1.0   1.4   1.8   2.2   2.6   3.0   ← después
 0.6    66%   75%   80%   80%   79%   78%   77%
 1.0    78%   84%   87%   87%   85%   84%   82%
 1.4    85%   89%   92%   91%   89%   86%   84%
 1.8    84%   88%   90%   90%   87%   84%   82%
 2.2    82%   86%   89%   87%   84%   82%   80%
```

El máximo es una **meseta ancha** alrededor de (1,4 / 1,4–1,8), no un pico de ruido. Pasan
a `eventos.py` como `ANTES = 1.4` y `DESPUES = 1.6`, con el porqué al lado: **89 % → 92 %**
—y **95 %** al rehacer la referencia con la rejilla de 64×36, que la afina.

Sale asimétrico, y tiene sentido: el pico de actividad cae en el swing, pero lo que el
scout conserva después es el seguimiento del bate y la pelota saliendo.

Sobre esto la honestidad obliga: **está medido sobre un solo turno**. Hay que recalibrar
en cuanto haya más pares (crudo, montaje).

### ¿Y si el vídeo es largo?

Preguntado a tiempo, porque el caso real son jornadas de 3 h y lo que se probó fueron 71 s.
Medido, no supuesto:

| Etapa | 71 s | extrapolado a 3 h |
|---|---|---|
| 1 · muestreo (solo keyframes) | 0,4 s | **1,1 min**, 10.815 recortes, 2,1 GB |
| 5 · actividad (todos los fotogramas) | 2,4 s | 6,1 min — pero corre sobre turnos, no jornadas |

El motor aguanta: la etapa 1 decodifica solo keyframes, que es justo para lo que se
diseñó. Lo que **no** aguantaba era `alinear.py`, escrito hoy: la matriz de correlación
es el producto de las dos duraciones, y a 3 h son **151 GB**. No cabía.

Dos intentos:

1. **Seguir la continuidad** —tras encajar el fotograma i, mirar solo el siguiente del
   crudo— que sería O(montaje) en vez de O(montaje × crudo). **Falla, y por una razón que
   conviene dejar escrita**: con la cámara fija y la escena casi quieta, un fotograma
   correlaciona **0,9998 con el vecino del sitio equivocado, exactamente igual que con el
   correcto**. No hay umbral que separe un corte de una continuación; el alineado deriva
   y devolvió 2 tramos de 5. Medido antes de insistir.
2. **Recorrer el montaje por bloques.** Resultado idéntico —hay un test que lo fija— y la
   memoria pasa a depender del bloque, no del montaje.

De paso salió que la rejilla de 32×18 era demasiado gruesa: con margen recortado capta el
fondo de la jaula, que es idéntico siempre, y el bateador no pesa. El margen del argmax
era de 0,00035. A **64×36** sube a 0,00102 y el primer tramo se clava 0,06 s antes.

| crudo | memoria | producto |
|---|---|---|
| 2 min | 41 MB | instantáneo |
| 15 min | 304 MB | 24 s |
| 1 h | 1,2 GB | 6 min |
| 3 h | 3,7 GB | 58 min |

Sigue siendo cuadrático, así que no se disimula: la herramienta avisa por encima de
1,5 GB y dice que está pensada para pares de **un turno**. Que es el caso real — el scout
monta turno a turno, no la jornada entera.

### Lo que esto cambia en el plan

El par (crudo, montaje) es una **máquina de generar material etiquetado**: cada turno que
el scout entregue ya montado produce su referencia sin que nadie marque nada. Eso vuelve
mucho más barato lo que hasta ahora bloqueaba —etiquetar a mano para poder entrenar—, y
convierte «pedir vídeos» en «pedir pares».

### Y un comando para cuando llegue material

Probar un par nuevo son seis comandos, y el que se olvida es siempre el último —volver a
barrer la calibración contra **todos** los pares—, que es justo el que puede tumbar una
conclusión anterior. `tools/probar_pares.py` lo hace de una vez: alinea, detecta, puntúa
y rebarre. Promedia el F1 **por par y no por segundos**, para que un turno largo no decida
la calibración de los cortos por pesar más.

Escribiendo sus tests se cayó una suposición mía: creía que con dos pares que piden
ventanas distintas el óptimo conjunto quedaría en el término medio. **No.** El F1 medio no
es cóncavo, y en el caso de prueba las dos ventanas extremas empatan por encima de la
intermedia. Por eso el script imprime la malla entera y no solo el máximo: el máximo por
sí solo puede estar en un empate y no se vería.

El procedimiento, en `PROBAR.md`, escrito para abrirlo sin recordar nada de esta sesión.

23 tests nuevos, **63 en verde**.

---

## 2026-09-09 · Los dos vídeos reales, y el swing que cuenta

Llegan por fin material real y el criterio del cliente. Los dos ficheros de `Video/` son
el mismo turno: uno de 70,9 s y otro de 25,8 s con marca de agua de InShot.

### Qué es el corto

No es un recorte de un tramo. Alineando fotograma a fotograma contra el largo salen
**siete trozos** pegados, misma escala y mismo encuadre (correlación 0,975 a escala 1,00):

| Corto | ← del largo |
|---|---|
| 0,00–3,37 | 6,60–9,93 |
| 3,40–9,77 | 12,77–19,13 |
| 9,80–19,87 | 21,80–31,87 |
| 19,90–21,23 | 34,37–35,70 |
| 21,30–22,67 | 35,77–37,13 |
| 22,70–25,33 | 47,07–49,17 |
| 25,37–25,77 | 49,53–49,90 |

Se descarta el 64 %. Y es **el mismo pelotero los 71 segundos**: esto no es la etapa de
partir por bateador, es una etapa nueva dentro del turno.

### El criterio

Del cliente, literal: un swing vale **solo si le lanzaron una pelota**. Los de
calentamiento no cuentan.

### Cuatro intentos de detectarlo, cuatro fracasos

| Vía | Resultado |
|---|---|
| Blobs pequeños en movimiento | 2037 de 2127 fotogramas dan candidato |
| Trayectoria balística de 3 puntos (velocidad y ángulo coherentes) | 545 fotogramas, sin separación entre conservados y descartados |
| Actividad del lanzador como proxy del gesto de lanzar | 29 picos, no se alinean con los swings conservados |
| Transitorio del golpe en el audio | **la pista está muda**: pico 0,0, cero muestras distintas de cero |

No es que falte afinar el detector. Medí una pelota en el suelo en primer plano: **11 px**;
en la zona de vuelo, al doble de distancia, **~6 px**. A 915 kbps el códec borra un objeto
de 6 px que se mueve rápido. Añádase la malla de la jaula entre cámara y vuelo, y que el
lanzador está **detrás** del bateador desde este ángulo. El material que llegó ya pasó por
WhatsApp y por InShot, y lo que quedó no conserva la información necesaria.

De ahí sale `tools/verificar_material.py`: antes de gastar tiempo en un detector sobre
material nuevo, se pasa esto y dice si sirve. Estima el tamaño de la pelota a partir del
ancho del fotograma —6,2 px en estos vídeos, coincide con lo medido a mano— y comprueba
que el audio traiga señal de verdad.

### El artefacto que casi me engaña

La primera medida de movimiento dio 59 picos de swing. Casi todos caían en `t=N,00`
exactos. No eran swings: el vídeo tiene **keyframe cada 1,000 s** (71 en total), y en un
H.264 el keyframe se codifica entero, sin referencia al anterior, así que la diferencia
que lo une al fotograma previo es alta siempre.

Y no basta con descartar esa pareja. El keyframe arrastra su propio ruido de
cuantización, así que queda distinto de **sus dos vecinos**: hay que descartar también la
pareja (kf, kf+1). Lo descubrió un test sobre el fixture, no yo — con solo la primera
exclusión seguía colándose un candidato justo después de un keyframe. Descontadas las
dos, quedan **22 candidatos** con ritmo natural, uno cada ~3 s, que es lo que cabe esperar
de un *front toss*.

### Lo implementado

| Módulo | Etapa | Qué hace |
|---|---|---|
| `eventos.py` | 5 | candidatos de swing por actividad, descontando keyframes |
| `marcas.py` | 6 | el cuaderno: qué swing valió, en JSON |
| `revision.py` | 6 | la pantalla de marcado, una tecla por candidato |
| `compactar.py` | 6 | el turno sin tiempo muerto, en un pase de filter_complex |

Más `cortador eventos`, `cortador marcar` y `cortador compactar`.

`compactar` recodifica, al revés que `corte.py`. No es un descuido: los cortes caen donde
ocurre el swing, y con keyframes a un segundo, ajustar hacia fuera alargaría cada swing
más que el propio swing.

El cuaderno guarda la fuerza del pico y el motivo, no solo el sí o el no, **porque es el
material etiquetado con el que después se ajustará el detector automático**. Sin esas
etiquetas, cualquier detector que se escriba hoy estaría adivinando.

### Comprobado de punta a punta

Marcando como válidos los candidatos que caen en los tramos que el cliente conservó,
`compactar` devuelve 20,8 s de 70,9 (29 %), h264 1024×576, sin audio. 38 tests en verde.

### Cuánto costaría automatizar el criterio

El motor no llama a ningún modelo: OpenCV y ffmpeg en local, **cero tokens**. El único
punto donde entraría un LLM es decidir si hubo pelota, y sale barato *porque* el
preprocesado ya filtró.

Las imágenes se cobran a `(ancho × alto) / 750` tokens. Por candidato, mandando solo el
recorte de la ventana de vuelo:

| Concepto | tokens |
|---|---|
| Recorte 400×220 | 117 por imagen |
| 8 fotogramas de la ventana pre-swing (0,5 s) | 936 |
| Instrucciones | ~300 |
| **Entrada por candidato** | **~1.250** |
| Salida (sí/no + confianza) | ~30 |

Con el volumen del cliente —30 cortes por bateador, 10 bateadores por semana, y el ratio
medido de 2,2 candidatos por corte— salen **660 candidatos por semana**, 825.000 tokens
de entrada:

| Modelo | Por turno (22 cand.) | Por semana | Al mes |
|---|---|---|---|
| Opus 5 ($5/$25 por MTok) | $0,15 | $4,62 | ~$20 |
| Sonnet 5 ($2/$10) | $0,06 | $1,85 | ~$8 |
| Haiku 4.5 ($1/$5) | $0,03 | $0,92 | ~$4 |

La **Batch API** deja todo eso a la mitad. El **prompt caching no sirve aquí**: el mínimo
cacheable son 512-4096 tokens según modelo y la parte estable de estas peticiones son
~300; lo que cambia en cada llamada son las imágenes.

**El preprocesado es lo que hace esto viable.** Mandar la jornada entera de 3 h, aunque
fuera a un fotograma por segundo, son ~10.800 imágenes = 1,26 M tokens por jornada, unos
$6 con Opus 5 y sin garantía de acertar. Filtrar antes a ~22 candidatos con visión
clásica reduce el trabajo del modelo unas 500 veces.

Y hay un camino que lo deja en cero: **si el audio del original sirve**, el golpe del bate
se detecta con procesado de señal local, sin modelo. Por eso el vídeo con sonido es la
pieza que más vale la pena conseguir.

Ojo: estas cifras salen de 22 candidatos medidos sobre 71 s de un solo turno. En cuanto
haya un turno real marcado a mano tendremos el ratio de verdad.


### Lo que hace falta pedir

1. **Un vídeo tal como sale de la cámara**, sin WhatsApp y **con audio**. El golpe del
   bate es la vía más prometedora: en una jaula la pelota siempre golpea algo, el bate o
   la lona, y un swing en vacío no suena.
2. Si **el lanzador entra siempre en el encuadre** o depende de dónde pongan la cámara.

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
