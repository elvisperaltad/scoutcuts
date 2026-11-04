"""Bot de Telegram: recibe videos de scouts, los encola y entrega el resultado.

Reglas de diseno clave (ver AGENTS/README del proyecto):

- Nunca se expone al scout jerga tecnica, perfiles de camara, rutas de
  archivo ni manifiestos: todos los mensajes van en espanol llano.
- El bot comparte la MISMA Almacen y la MISMA Cola que la API HTTP; nunca
  crea las suyas. Eso lo garantiza quien llama a `iniciar_bot_en_segundo_plano`
  (normalmente `api.crear_app`).
- El token nunca se hardcodea ni se imprime: se recibe como parametro desde
  la variable de entorno SCOUTCUTS_TELEGRAM_BOT_TOKEN.
- El video original SIEMPRE se borra tras entregar el resultado (hay menores
  de edad involucrados), via `Almacen.marcar_descargado`.

Separacion deliberada para poder probar sin un Application real de telegram:
las funciones `mensaje_*`, `verificar_video`, `ingresar_video` y
`entregar_resultado` son casi puras (reciben Almacen/Cola/Usuarios/Bot como
parametros explicitos) y no importan nada de `telegram.ext`. Los `manejar_*`
son la capa delgada que traduce un Update/Context de telegram a esas
llamadas, y se prueban con objetos falsos (mocks), no con un bot real.

Nota sobre /estado y api.py: `_mensaje_estado` de `api.py` calcula el
mensaje para un trabajo en curso (incluye la posicion en la fila via
`cola.posicion`). Aqui replicamos el mismo estilo de mensaje en vez de
importar `api.py`: importar api.py desde aqui crearia una dependencia
circular rara (api.py seria quien arranca el bot en su evento de startup),
y el bot no necesita calcular posicion en cola para un listado retrospectivo
de trabajos, solo mostrar el estado final o en curso de cada uno.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from . import almacen as alm
from .almacen import Almacen, ArchivoNoAceptado, Trabajo
from .cola import Cola
from .usuarios import Usuario, Usuarios

_LOGGER = logging.getLogger("cortador.servidor.bot_telegram")

# Limites reales de la API de Telegram en modo nube (no configurables salvo
# que se corra un Local Bot API Server, ver TELEGRAM_BOT.md):
LIMITE_DESCARGA_BYTES = 20 * 1024 * 1024    # getFile: maximo que se puede bajar
LIMITE_SUBIDA_BYTES = 50 * 1024 * 1024      # sendVideo: maximo que se puede subir

MENSAJE_SIN_ACCESO = (
    "Tu cuenta todavia no esta activada en ScoutCuts. Pide acceso al "
    "administrador y en cuanto te active podras mandar tus videos aqui."
)
MENSAJE_SALUDO = (
    "Hola, {nombre}. Mandame un video del turno al bate y te devuelvo el "
    "montaje recortado por este mismo chat."
)
MENSAJE_SIN_TRABAJOS = "Todavia no has mandado ningun video."
MENSAJE_VIDEO_MUY_GRANDE_PARA_DESCARGAR = (
    "Este video es muy grande para enviarlo por Telegram en este momento. "
    "Pide ayuda al administrador para mandarlo por otra via."
)
MENSAJE_VIDEO_MUY_GRANDE_PARA_SUBIR = (
    "Tu montaje quedo listo, pero el archivo es muy grande para enviarlo por "
    "Telegram. Pide ayuda al administrador para que te lo entregue por otra via."
)

_TRADUCCION_ESTADO = {
    alm.RECIBIDO: "recibido, a punto de entrar en la fila",
    alm.EN_COLA: "en la fila, esperando su turno",
    alm.PROCESANDO: "en proceso ahora mismo",
    alm.LISTO: "listo",
    alm.PENDIENTE_REVISION: "pendiente de revision por el equipo",
    alm.ERROR: "con un problema al procesarlo",
}


# ---------------------------------------------------------------------------
# mensajes (casi puros, en espanol llano)
# ---------------------------------------------------------------------------


def mensaje_start(usuario: Usuario | None) -> str:
    """Texto de /start: pide acceso si no esta registrado, saluda si lo esta."""
    if usuario is None:
        return MENSAJE_SIN_ACCESO
    return MENSAJE_SALUDO.format(nombre=usuario.nombre or "scout")


def mensaje_estado(usuario: Usuario | None, *, almacen: Almacen | None) -> str:
    """Texto de /estado: lista los trabajos recientes en lenguaje llano."""
    if usuario is None:
        return mensaje_start(None)
    trabajos = almacen.trabajos_de(usuario.telegram_id) if almacen else []
    if not trabajos:
        return MENSAJE_SIN_TRABAJOS
    lineas = ["Tus videos recientes:"]
    for trabajo in trabajos:
        traducido = _TRADUCCION_ESTADO.get(trabajo.estado, trabajo.estado)
        lineas.append(f"- {trabajo.nombre}: {traducido}")
    return "\n".join(lineas)


# ---------------------------------------------------------------------------
# logica de negocio de recepcion de video (sin tocar telegram.ext)
# ---------------------------------------------------------------------------


def verificar_video(telegram_id: str, tamano_bytes: int, *,
                    usuarios: Usuarios) -> tuple[bool, str]:
    """Valida registro, cuota y tamano ANTES de intentar descargar nada."""
    usuario = usuarios.por_telegram_id(telegram_id)
    if usuario is None:
        return False, MENSAJE_SIN_ACCESO
    puede, motivo = usuarios.puede_subir(usuario)
    if not puede:
        return False, motivo
    if int(tamano_bytes or 0) > LIMITE_DESCARGA_BYTES:
        return False, MENSAJE_VIDEO_MUY_GRANDE_PARA_DESCARGAR
    return True, ""


def ingresar_video(telegram_id: str, nombre_archivo: str, tamano_bytes: int,
                   flujo_binario, *, almacen: Almacen, cola: Cola,
                   usuarios: Usuarios) -> str:
    """Crea el trabajo, guarda el binario, lo encola y registra el uso de cuota.

    Asume que `verificar_video` ya se llamo y dio permiso: esta funcion no
    vuelve a chequear cuota para no reintroducir una condicion de carrera
    entre el chequeo y el registro (quien llama hace ambas cosas en el mismo
    flujo del handler).
    """
    try:
        trabajo = almacen.crear(nombre_archivo, tamano_bytes, propietario=str(telegram_id))
    except ArchivoNoAceptado as err:
        return str(err)
    almacen.guardar_entrada(trabajo, flujo_binario)
    posicion = cola.encolar(trabajo)
    usuario = usuarios.por_telegram_id(telegram_id)
    if usuario is not None:
        usuarios.registrar_uso(usuario)
    if posicion and posicion >= 1:
        plural = "videos" if posicion > 1 else "video"
        return (
            f"Recibimos tu video. Hay {posicion} {plural} delante del tuyo; "
            "te avisamos por aqui en cuanto este listo."
        )
    return "Recibimos tu video y ya lo estamos procesando. Te avisamos por aqui."


# ---------------------------------------------------------------------------
# entrega del resultado (callback `al_terminar` de la Cola)
# ---------------------------------------------------------------------------


async def entregar_resultado(bot, trabajo: Trabajo, almacen: Almacen) -> None:
    """Envia el resultado (o el motivo de por que no) y borra el original.

    El borrado del video original SIEMPRE ocurre al final, sin excepcion,
    porque el trabajo llego a un estado final y hay menores de edad
    involucrados: no hace falta conservar el original ni si fallo la entrega
    por Telegram (seguiria disponible por la API HTTP si hiciera falta).
    """
    chat_id = int(trabajo.propietario)
    try:
        if trabajo.estado == alm.LISTO:
            await _entregar_listo(bot, trabajo, almacen, chat_id)
        else:
            await bot.send_message(chat_id=chat_id, text=trabajo.mensaje)
    finally:
        almacen.marcar_descargado(trabajo)


async def _entregar_listo(bot, trabajo: Trabajo, almacen: Almacen, chat_id: int) -> None:
    ruta = almacen.ruta_resultado(trabajo)
    if not ruta.exists():
        # LISTO sin montaje (no se detectaron swings): el mensaje ya lo explica.
        await bot.send_message(chat_id=chat_id, text=trabajo.mensaje)
        return
    if ruta.stat().st_size > LIMITE_SUBIDA_BYTES:
        await bot.send_message(chat_id=chat_id, text=MENSAJE_VIDEO_MUY_GRANDE_PARA_SUBIR)
        return
    with ruta.open("rb") as video:
        await bot.send_video(chat_id=chat_id, video=video, caption=trabajo.mensaje)


def construir_al_terminar(bot, loop: asyncio.AbstractEventLoop,
                          almacen: Almacen) -> Callable[[Trabajo], None]:
    """Fabrica el callback sincrono que la Cola invoca desde su propio hilo.

    La Cola corre en un hilo de trabajador aparte, nunca en el event loop del
    bot: el callback reenvia la coroutine con `run_coroutine_threadsafe` en
    vez de ejecutarla directo (eso rompería el loop del bot si se llamara
    desde otro hilo).
    """
    def al_terminar(trabajo: Trabajo) -> None:
        if not trabajo.propietario:
            return  # trabajo subido por la API HTTP publica, sin dueno de Telegram
        futuro = asyncio.run_coroutine_threadsafe(
            entregar_resultado(bot, trabajo, almacen), loop)
        futuro.result(60)

    return al_terminar


# ---------------------------------------------------------------------------
# handlers delgados: traducen Update/Context a las funciones de arriba
# ---------------------------------------------------------------------------


async def manejar_start(update, _contexto, *, usuarios: Usuarios) -> None:
    telegram_id = str(update.effective_user.id)
    usuario = usuarios.por_telegram_id(telegram_id)
    if usuario is None:
        # El administrador necesita este id para registrar al scout con
        # `cortador usuarios crear --telegram-id ...`; sin este log no
        # tendria forma practica de conseguirlo salvo pedirselo aparte.
        _LOGGER.info(
            "Un telegram_id sin cuenta escribio /start: %s. "
            "Para activarlo: cortador usuarios crear --telegram-id %s --nombre <nombre>",
            telegram_id, telegram_id,
        )
    await update.message.reply_text(mensaje_start(usuario))


async def manejar_estado(update, _contexto, *, usuarios: Usuarios, almacen: Almacen) -> None:
    telegram_id = str(update.effective_user.id)
    usuario = usuarios.por_telegram_id(telegram_id)
    await update.message.reply_text(mensaje_estado(usuario, almacen=almacen))


async def manejar_video(update, _contexto, *, almacen: Almacen, cola: Cola,
                        usuarios: Usuarios) -> None:
    """Un video (o un documento de tipo video) llego al chat."""
    telegram_id = str(update.effective_user.id)
    archivo_tg = update.message.video or update.message.document
    if archivo_tg is None:
        return
    nombre = getattr(archivo_tg, "file_name", None) or "video.mp4"
    tamano = int(getattr(archivo_tg, "file_size", 0) or 0)

    puede, motivo = verificar_video(telegram_id, tamano, usuarios=usuarios)
    if not puede:
        if usuarios.por_telegram_id(telegram_id) is None:
            # Mismo motivo que en manejar_start: el administrador necesita
            # este id para activar la cuenta con `cortador usuarios crear`.
            _LOGGER.info(
                "Un telegram_id sin cuenta mando un video: %s. "
                "Para activarlo: cortador usuarios crear --telegram-id %s --nombre <nombre>",
                telegram_id, telegram_id,
            )
        await update.message.reply_text(motivo)
        return

    archivo = await archivo_tg.get_file()
    contenido = await archivo.download_as_bytearray()
    import io
    mensaje = ingresar_video(
        telegram_id, nombre, tamano, io.BytesIO(bytes(contenido)),
        almacen=almacen, cola=cola, usuarios=usuarios)
    await update.message.reply_text(mensaje)


# ---------------------------------------------------------------------------
# arranque en segundo plano (hilo daemon con su propio event loop)
# ---------------------------------------------------------------------------


def registrar_handlers(app, *, almacen: Almacen, cola: Cola, usuarios: Usuarios) -> None:
    """Registra /start, /estado y la recepcion de video/documento en `app`."""
    from telegram.ext import CommandHandler, MessageHandler, filters

    app.add_handler(CommandHandler(
        "start", lambda update, ctx: manejar_start(update, ctx, usuarios=usuarios)))
    app.add_handler(CommandHandler(
        "estado", lambda update, ctx: manejar_estado(
            update, ctx, usuarios=usuarios, almacen=almacen)))
    app.add_handler(MessageHandler(
        filters.VIDEO | filters.Document.VIDEO,
        lambda update, ctx: manejar_video(
            update, ctx, almacen=almacen, cola=cola, usuarios=usuarios)))


class _ControlBot:
    """Manija para detener limpiamente el hilo daemon del bot."""

    def __init__(self, hilo: threading.Thread, app) -> None:
        self._hilo = hilo
        self._app = app

    def detener(self, timeout: float | None = None) -> bool:
        try:
            self._app.stop_running()
        except Exception:  # noqa: BLE001 - mejor esfuerzo al detener
            _LOGGER.exception("No se pudo detener el bot de Telegram limpiamente.")
        self._hilo.join(timeout)
        return not self._hilo.is_alive()


def _construir_app_por_defecto(token: str):
    from telegram.ext import Application

    return Application.builder().token(token).build()


def _arranque_seguro(token: str, err: BaseException) -> str:
    """Texto de log sin el token, incluso si la excepcion de telegram lo incluye.

    La libreria `python-telegram-bot` a veces mete el token crudo en su
    propio mensaje de error (p. ej. `InvalidToken`). Nunca se loguea el
    traceback completo de este fallo (podria repetir el token en una capa
    interna); solo el tipo de excepcion y el mensaje ya depurado.
    """
    mensaje = f"{type(err).__name__}: {err}"
    if token:
        mensaje = mensaje.replace(token, "***")
    return mensaje


class _FiltroToken(logging.Filter):
    """Redacta el token del bot si aparece en el mensaje ya formateado.

    Se usa en logs propios (ver `_arranque_seguro`); no es la defensa
    principal contra la fuga del token desde dentro de `python-telegram-bot`
    (ver `_logging_de_telegram_silenciado`).
    """

    def __init__(self, token: str) -> None:
        super().__init__()
        self._token = token

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._token:
            return True
        texto = record.getMessage()
        if self._token in texto:
            record.msg = texto.replace(self._token, "***")
            record.args = ()
        return True


@contextmanager
def _logging_de_telegram_silenciado():
    """Mientras el bot arranca, sube el nivel del logger `telegram.*` a CRITICAL.

    La libreria `python-telegram-bot` loguea el token crudo dentro del
    mensaje de `InvalidToken` desde sus propios loggers internos (p. ej.
    `telegram.ext._utils.networkloop`), fuera de nuestro control. Filtrar un
    record ya emitido no es fiable: los filtros de un Logger solo corren
    para los handlers de ESE logger, no para los de sus ancestros cuando el
    record se propaga (`Logger.callHandlers` no vuelve a aplicar el filtro
    del logger raiz). Elevar el nivel es la unica forma simple de garantizar
    que nunca se emite el token: la regla de "nunca loguear secretos" es
    inviolable incluso para dependencias de terceros. El bot sigue
    informando el fallo por su cuenta, ya depurado, via `_LOGGER.error`.
    """
    logger_telegram = logging.getLogger("telegram")
    nivel_previo = logger_telegram.level
    logger_telegram.setLevel(logging.CRITICAL + 1)
    try:
        yield
    finally:
        logger_telegram.setLevel(nivel_previo)


def iniciar_bot_en_segundo_plano(
    token: str, almacen: Almacen, cola: Cola, usuarios: Usuarios, *,
    construir_app: Callable[[str], object] = _construir_app_por_defecto,
) -> _ControlBot:
    """Arranca el bot en un hilo daemon aparte, con su propio event loop.

    `Application.run_polling` es bloqueante y arma su propio loop con
    `asyncio.get_event_loop()`; por eso corre en un hilo dedicado y nunca en
    el loop de uvicorn/FastAPI. El token nunca se imprime ni se loguea: se
    silencian los loggers internos de `telegram` mientras arranca (ver
    `_logging_de_telegram_silenciado`) y el fallo se reporta por nuestra
    cuenta, ya depurado, via `_arranque_seguro`.

    El callback `al_terminar` de la Cola se conecta DESPUES de crear y fijar
    el event loop de este hilo (pero antes de bloquear en `run_polling`), ya
    que `construir_al_terminar` necesita ese loop concreto para poder
    reenviarle la entrega del resultado via `run_coroutine_threadsafe`.
    """
    app = construir_app(token)
    registrar_handlers(app, almacen=almacen, cola=cola, usuarios=usuarios)

    def _correr() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        cola.conectar_al_terminar(construir_al_terminar(app.bot, loop, almacen))
        try:
            with _logging_de_telegram_silenciado():
                app.run_polling(close_loop=False, stop_signals=None)
        except Exception as err:  # noqa: BLE001 - un fallo aqui no debe tumbar la API HTTP
            # Sin exc_info: el traceback de telegram puede repetir el token
            # crudo en uno de sus frames internos.
            _LOGGER.error(
                "El bot de Telegram se detuvo por un error: %s",
                _arranque_seguro(token, err),
            )

    hilo = threading.Thread(target=_correr, name="scoutcuts-bot-telegram", daemon=True)
    hilo.start()
    return _ControlBot(hilo, app)
