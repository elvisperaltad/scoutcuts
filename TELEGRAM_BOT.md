# Bot de Telegram para scouts

ScoutCuts puede recibir videos directamente por Telegram: el scout manda el
video por chat, el servidor lo corta igual que por la API HTTP, y el montaje
vuelve por el mismo chat. No hace falta instalar ninguna app ni usar la web.

## 1. Registrar un scout (administrador)

Solo un administrador puede activar cuentas; un scout nunca se auto-registra.
El comando no necesita el extra `[servidor]` instalado (ni FastAPI), solo
`cortador` en el `.venv`:

```bash
cortador usuarios crear --raiz /ruta/a/usuarios \
  --telegram-id 123456789 --nombre "Ana Scout" --cuota 20
```

- `--telegram-id`: el ID numerico de Telegram del scout (se lo puede pasar
  el propio scout escribiendole a `/start` a `@userinfobot`, o el admin lo
  ve en los logs del servicio la primera vez que alguien sin cuenta le
  escribe `/start` o le manda un video: el log incluye el comando exacto
  `cortador usuarios crear --telegram-id ... --nombre <nombre>` para copiar
  y pegar).
- `--cuota`: videos permitidos por mes (default 20). El contador se
  resetea solo al empezar cada mes calendario.
- `--raiz`: carpeta donde vive el almacenamiento de cuentas. Si se usa la
  variable de entorno `SCOUTCUTS_USUARIOS` en vez del flag, no hace falta
  repetirla en cada comando.

Otros comandos de administracion:

```bash
cortador usuarios listar --raiz /ruta/a/usuarios
cortador usuarios desactivar --raiz /ruta/a/usuarios --id <id-interno>
cortador usuarios activar --raiz /ruta/a/usuarios --id <id-interno>
```

El `<id-interno>` (un uuid hex) se muestra en la salida de `crear` y de
`listar`.

## 2. Configurar el token del bot

1. Crea el bot con [@BotFather](https://t.me/BotFather) en Telegram
   (`/newbot`) y copia el token que te da.
2. Exporta `SCOUTCUTS_TELEGRAM_BOT_TOKEN` en el entorno del servidor, junto
   con el resto de variables `SCOUTCUTS_*` que ya usa la API:

```bash
export SCOUTCUTS_TELEGRAM_BOT_TOKEN="123456789:AAAbbbCCCdddEEEfffGGGhhh"
```

Si esta variable no esta presente, el servidor arranca exactamente igual
pero sin el bot activo: la API HTTP nunca depende de que el bot este
configurado. Si el token es invalido o la libreria `python-telegram-bot` no
esta instalada (falta el extra `[telegram]`), el fallo queda en el log del
servidor y `/salud` sigue respondiendo 200: un problema del bot nunca tumba
el servicio HTTP.

Instala el extra con:

```bash
pip install -e .[telegram]
```

El token nunca se imprime en pantalla, nunca se loguea (ni siquiera si la
propia libreria de Telegram intenta incluirlo en una excepcion interna) y
nunca se hardcodea en el codigo: viaja solo por esa variable de entorno.

## 3. Limites REALES de la API de Telegram en modo nube

Dos limites que no dependen de ScoutCuts, sino de como funciona la API
publica de Telegram (`api.telegram.org`), y que esta primera version
respeta sin intentar saltarlos:

- **Descarga (`getFile`): maximo 20 MB.** Si un scout manda un video mas
  pesado, el bot ni siquiera intenta bajarlo (fallaria a mitad de camino):
  responde de inmediato explicando que el video es muy grande para
  Telegram en este momento y que pida ayuda al administrador.
- **Subida (`sendVideo`): maximo 50 MB.** Si el montaje resultante pesa
  mas de eso, el bot NO intenta subirlo (se cortaria a medias): avisa al
  scout que el resultado quedo listo pero es muy grande para entregarlo por
  Telegram, y que pida ayuda al administrador (por ejemplo, para que se lo
  pasen por otra via). El trabajo sigue disponible por la API HTTP normal
  si hiciera falta.

### ¿Y si se necesita superar esos limites?

Existe la opcion de correr un **Local Bot API Server**
(`telegram-bot-api`, el servidor que corre el propio Telegram y que se
puede alojar uno mismo): eleva el limite de subida a 2 GB y quita el limite
practico de descarga. Pero requiere un `api_id` y un `api_hash` propios,
que se obtienen registrando una aplicacion en
[my.telegram.org](https://my.telegram.org) — **credenciales que solo el
dueño del proyecto puede generar** (requieren el numero de telefono y la
cuenta de Telegram del propio dueño; un agente automatizado no puede
crearlas por si mismo). Si en el futuro hace falta, es un cambio de
infraestructura aparte: correr ese servidor y apuntar la libreria de
Telegram a el en vez de a `api.telegram.org`. Esta primera version no lo
necesita porque los montajes de un turno al bate suelen pesar bastante
menos de 50 MB.

## 4. Por que esta version NO usa un modelo de lenguaje (LLM)

El bot entiende solo comandos explicitos (`/start`, `/estado`) y la
recepcion de un archivo de video: no interpreta lenguaje libre ("mandame el
turno de ayer", "¿cuánto me falta de cuota?"). Esto es una decision de
infraestructura, no de producto:

- El VPS de produccion tiene **950 MB de RAM total**. Un modelo pequeño de
  1-3B de parametros en formato int4 (la cuantizacion mas agresiva que
  sigue siendo usable) ya necesita entre 700 MB y 1 GB solo para cargar los
  pesos en memoria, antes de procesar un solo mensaje. En ese VPS, cargar
  un LLM local tumbaria el servicio de corte de video (que ya usa su propia
  memoria para OpenCV/ffmpeg) o el propio sistema operativo.
- Nada de lo que hace el bot (registrar, validar cuota, encolar, avisar el
  resultado) necesita generar lenguaje libre: son reglas explicitas con
  mensajes fijos en español, exactamente como la API HTTP. Un LLM aqui
  seria complejidad sin beneficio real.

Si en el futuro se quiere conversacion libre de verdad (entender frases
naturales en vez de comandos), la forma correcta de hacerlo es que el LLM
pequeño viva en **otra maquina** (no en este VPS de 950 MB) y el bot le
consulte por red **solo para la capa de conversacion** — nunca para el
corte de video en si, que sigue siendo 100% determinista y corre en el
mismo VPS de siempre.
