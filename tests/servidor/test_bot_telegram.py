"""Pruebas del bot de Telegram: logica de negocio y handlers, todo con mocks.

Nunca se levanta un Application real de telegram ni se toca la red: las
funciones de negocio (verificar_video, ingresar_video, mensajes) son casi
puras y se prueban directo; los handlers se prueban con objetos Update /
Message falsos (no instancias reales de `telegram`), y `iniciar_bot_en_segundo_plano`
se prueba inyectando una Application falsa via el parametro `construir_app`.
"""

import asyncio
import io
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("telegram", reason="falta el extra [telegram] (pip install -e .[telegram])")


def _piezas(tmp_path):
    from cortador.servidor.almacen import Almacen
    from cortador.servidor.cola import Cola
    from cortador.servidor.usuarios import Usuarios

    almacen = Almacen(tmp_path / "datos")
    cola = Cola(almacen, lambda trabajo, guardia: None)
    usuarios = Usuarios(tmp_path / "usuarios")
    return almacen, cola, usuarios


class _ArchivoTgFalso:
    """Imita un Video/Document de telegram: file_name, file_size y get_file()."""

    def __init__(self, file_name, file_size, contenido=b"contenido-del-video"):
        self.file_name = file_name
        self.file_size = file_size
        self._contenido = contenido
        self.get_file = AsyncMock(return_value=self)
        self.download_as_bytearray = AsyncMock(return_value=bytearray(self._contenido))


class _MensajeFalso:
    def __init__(self, video=None, document=None):
        self.video = video
        self.document = document
        self.reply_text = AsyncMock()


class _UpdateFalso:
    def __init__(self, telegram_id, mensaje):
        self.effective_user = SimpleNamespace(id=telegram_id)
        self.message = mensaje


class _AppFalsa:
    """Application falsa: nunca abre socket, solo registra handlers."""

    def __init__(self):
        self.bot = MagicMock(name="bot")
        self.handlers = []
        self._detenido = threading.Event()

    def add_handler(self, manejador):
        self.handlers.append(manejador)

    def run_polling(self, **kwargs):
        self._detenido.wait(10)

    def stop_running(self):
        self._detenido.set()


# ---------------------------------------------------------------------------
# mensajes puros: /start y /estado
# ---------------------------------------------------------------------------


def test_mensaje_start_de_usuario_no_registrado_pide_acceso():
    from cortador.servidor import bot_telegram as mod

    texto = mod.mensaje_start(None)

    assert "administrador" in texto.lower()
    assert "activad" in texto.lower()


def test_mensaje_start_de_usuario_registrado_saluda_por_nombre(tmp_path):
    from cortador.servidor import bot_telegram as mod

    _, _, usuarios = _piezas(tmp_path)
    usuario = usuarios.crear("111", "Ana Scout")

    texto = mod.mensaje_start(usuario)

    assert "Ana Scout" in texto
    assert "video" in texto.lower()


def test_mensaje_estado_de_usuario_no_registrado_pide_acceso():
    from cortador.servidor import bot_telegram as mod

    assert mod.mensaje_estado(None, almacen=None) == mod.mensaje_start(None)


def test_mensaje_estado_sin_trabajos_lo_dice_claro(tmp_path):
    from cortador.servidor import bot_telegram as mod

    almacen, _, usuarios = _piezas(tmp_path)
    usuario = usuarios.crear("111", "Ana Scout")

    texto = mod.mensaje_estado(usuario, almacen=almacen)

    assert "video" in texto.lower()
    assert "ningun" in texto.lower() or "ningún" in texto.lower() or "no" in texto.lower()


def test_mensaje_estado_lista_los_trabajos_con_estado_traducido(tmp_path):
    from cortador.servidor import almacen as alm
    from cortador.servidor import bot_telegram as mod

    almacen, _, usuarios = _piezas(tmp_path)
    usuario = usuarios.crear("111", "Ana Scout")
    trabajo = almacen.crear("turno.mp4", 10, propietario="111")
    trabajo.estado = alm.LISTO
    trabajo.mensaje = "Tu montaje esta listo."
    almacen.guardar_estado(trabajo)

    texto = mod.mensaje_estado(usuario, almacen=almacen)

    assert "turno.mp4" in texto
    assert "listo" in texto.lower()
    # nada de jerga tecnica (estados internos en snake_case, rutas, ids)
    assert trabajo.id not in texto


# ---------------------------------------------------------------------------
# logica de negocio de recepcion de video
# ---------------------------------------------------------------------------


def test_verificar_video_de_usuario_no_registrado(tmp_path):
    from cortador.servidor import bot_telegram as mod

    _, _, usuarios = _piezas(tmp_path)

    puede, motivo = mod.verificar_video("999", 1000, usuarios=usuarios)

    assert puede is False
    assert "administrador" in motivo.lower()


def test_verificar_video_de_usuario_sin_cuota(tmp_path):
    from cortador.servidor import bot_telegram as mod

    _, _, usuarios = _piezas(tmp_path)
    usuario = usuarios.crear("111", "Ana", cuota_mensual=1)
    usuarios.registrar_uso(usuario)

    puede, motivo = mod.verificar_video("111", 1000, usuarios=usuarios)

    assert puede is False
    assert "cuota" in motivo.lower()


def test_verificar_video_que_excede_el_limite_de_descarga(tmp_path):
    from cortador.servidor import bot_telegram as mod

    _, _, usuarios = _piezas(tmp_path)
    usuarios.crear("111", "Ana")

    puede, motivo = mod.verificar_video(
        "111", mod.LIMITE_DESCARGA_BYTES + 1, usuarios=usuarios)

    assert puede is False
    assert "grande" in motivo.lower()
    assert "administrador" in motivo.lower()


def test_verificar_video_valido_puede_continuar(tmp_path):
    from cortador.servidor import bot_telegram as mod

    _, _, usuarios = _piezas(tmp_path)
    usuarios.crear("111", "Ana")

    puede, motivo = mod.verificar_video("111", 1000, usuarios=usuarios)

    assert puede is True
    assert motivo == ""


def test_ingresar_video_crea_trabajo_lo_encola_y_registra_uso(tmp_path):
    from cortador.servidor import bot_telegram as mod

    almacen, cola, usuarios = _piezas(tmp_path)
    usuarios.crear("111", "Ana", cuota_mensual=20)
    try:
        mensaje = mod.ingresar_video(
            "111", "turno.mp4", 19, io.BytesIO(b"contenido-de-video"),
            almacen=almacen, cola=cola, usuarios=usuarios)

        assert mensaje
        trabajos = almacen.trabajos_de("111")
        assert len(trabajos) == 1
        assert trabajos[0].propietario == "111"
        assert usuarios.por_telegram_id("111").usados_mes == 1
    finally:
        cola.detener(5)


# ---------------------------------------------------------------------------
# handlers (traducen Update/Context a las funciones de negocio)
# ---------------------------------------------------------------------------


def test_manejar_video_de_usuario_no_registrado_no_crea_trabajo(tmp_path):
    from cortador.servidor import bot_telegram as mod

    almacen, cola, usuarios = _piezas(tmp_path)
    try:
        archivo_tg = _ArchivoTgFalso("turno.mp4", 1000)
        mensaje = _MensajeFalso(video=archivo_tg)
        update = _UpdateFalso(999, mensaje)

        asyncio.run(mod.manejar_video(
            update, None, almacen=almacen, cola=cola, usuarios=usuarios))

        mensaje.reply_text.assert_awaited_once()
        texto = mensaje.reply_text.await_args.args[0]
        assert "administrador" in texto.lower()
        assert almacen.trabajos_de("999") == []
        archivo_tg.get_file.assert_not_awaited()
    finally:
        cola.detener(5)


def test_manejar_video_de_usuario_no_registrado_deja_rastro_en_el_log(tmp_path, caplog):
    """Mismo motivo que para /start: el administrador necesita el

    telegram_id para activar la cuenta con `cortador usuarios crear`.
    """
    import logging

    from cortador.servidor import bot_telegram as mod

    almacen, cola, usuarios = _piezas(tmp_path)
    try:
        archivo_tg = _ArchivoTgFalso("turno.mp4", 1000)
        mensaje = _MensajeFalso(video=archivo_tg)
        update = _UpdateFalso(999, mensaje)

        with caplog.at_level(logging.INFO):
            asyncio.run(mod.manejar_video(
                update, None, almacen=almacen, cola=cola, usuarios=usuarios))

        assert "999" in caplog.text
    finally:
        cola.detener(5)


def test_manejar_video_de_usuario_sin_cuota_no_crea_trabajo(tmp_path):
    from cortador.servidor import bot_telegram as mod

    almacen, cola, usuarios = _piezas(tmp_path)
    try:
        usuario = usuarios.crear("111", "Ana", cuota_mensual=1)
        usuarios.registrar_uso(usuario)
        archivo_tg = _ArchivoTgFalso("turno.mp4", 1000)
        mensaje = _MensajeFalso(video=archivo_tg)
        update = _UpdateFalso(111, mensaje)

        asyncio.run(mod.manejar_video(
            update, None, almacen=almacen, cola=cola, usuarios=usuarios))

        texto = mensaje.reply_text.await_args.args[0]
        assert "cuota" in texto.lower()
        assert almacen.trabajos_de("111") == []
        archivo_tg.get_file.assert_not_awaited()
    finally:
        cola.detener(5)


def test_manejar_video_valido_crea_trabajo_lo_encola_y_registra_uso(tmp_path):
    from cortador.servidor import bot_telegram as mod

    almacen, cola, usuarios = _piezas(tmp_path)
    try:
        usuarios.crear("111", "Ana", cuota_mensual=20)
        archivo_tg = _ArchivoTgFalso("turno.mp4", 1000, contenido=b"contenido-de-video")
        mensaje = _MensajeFalso(video=archivo_tg)
        update = _UpdateFalso(111, mensaje)

        asyncio.run(mod.manejar_video(
            update, None, almacen=almacen, cola=cola, usuarios=usuarios))

        archivo_tg.get_file.assert_awaited_once()
        trabajos = almacen.trabajos_de("111")
        assert len(trabajos) == 1
        assert almacen.ruta_entrada(trabajos[0]).read_bytes() == b"contenido-de-video"
        assert usuarios.por_telegram_id("111").usados_mes == 1
        mensaje.reply_text.assert_awaited_once()
    finally:
        cola.detener(5)


def test_manejar_video_documento_tambien_funciona_igual_que_video(tmp_path):
    from cortador.servidor import bot_telegram as mod

    almacen, cola, usuarios = _piezas(tmp_path)
    try:
        usuarios.crear("111", "Ana", cuota_mensual=20)
        archivo_tg = _ArchivoTgFalso("turno.mp4", 1000, contenido=b"video-como-documento")
        mensaje = _MensajeFalso(document=archivo_tg)
        update = _UpdateFalso(111, mensaje)

        asyncio.run(mod.manejar_video(
            update, None, almacen=almacen, cola=cola, usuarios=usuarios))

        assert len(almacen.trabajos_de("111")) == 1
    finally:
        cola.detener(5)


def test_manejar_video_que_excede_el_limite_de_descarga_no_descarga_nada(tmp_path):
    from cortador.servidor import bot_telegram as mod

    almacen, cola, usuarios = _piezas(tmp_path)
    try:
        usuarios.crear("111", "Ana", cuota_mensual=20)
        archivo_tg = _ArchivoTgFalso("grande.mp4", mod.LIMITE_DESCARGA_BYTES + 1)
        mensaje = _MensajeFalso(video=archivo_tg)
        update = _UpdateFalso(111, mensaje)

        asyncio.run(mod.manejar_video(
            update, None, almacen=almacen, cola=cola, usuarios=usuarios))

        texto = mensaje.reply_text.await_args.args[0]
        assert "grande" in texto.lower()
        archivo_tg.get_file.assert_not_awaited()
        assert almacen.trabajos_de("111") == []
    finally:
        cola.detener(5)


def test_manejar_start_llama_al_mensaje_correspondiente(tmp_path):
    from cortador.servidor import bot_telegram as mod

    _, cola, usuarios = _piezas(tmp_path)
    try:
        usuarios.crear("111", "Ana Scout")
        mensaje = _MensajeFalso()
        update = _UpdateFalso(111, mensaje)

        asyncio.run(mod.manejar_start(update, None, usuarios=usuarios))

        texto = mensaje.reply_text.await_args.args[0]
        assert "Ana Scout" in texto
    finally:
        cola.detener(5)


def test_manejar_start_de_usuario_no_registrado_deja_rastro_en_el_log(tmp_path, caplog):
    """El administrador necesita el telegram_id del scout para registrarlo

    con `cortador usuarios crear`. Sin un log, no tiene forma practica de
    conseguirlo salvo pedirselo aparte por fuera de Telegram.
    """
    import logging

    from cortador.servidor import bot_telegram as mod

    _, cola, usuarios = _piezas(tmp_path)
    try:
        mensaje = _MensajeFalso()
        update = _UpdateFalso(999, mensaje)

        with caplog.at_level(logging.INFO):
            asyncio.run(mod.manejar_start(update, None, usuarios=usuarios))

        assert "999" in caplog.text
    finally:
        cola.detener(5)


def test_manejar_estado_llama_al_mensaje_correspondiente(tmp_path):
    from cortador.servidor import bot_telegram as mod

    almacen, cola, usuarios = _piezas(tmp_path)
    try:
        usuarios.crear("111", "Ana Scout")
        mensaje = _MensajeFalso()
        update = _UpdateFalso(111, mensaje)

        asyncio.run(mod.manejar_estado(update, None, usuarios=usuarios, almacen=almacen))

        texto = mensaje.reply_text.await_args.args[0]
        assert "video" in texto.lower()
    finally:
        cola.detener(5)


# ---------------------------------------------------------------------------
# entrega del resultado (callback al_terminar de la Cola)
# ---------------------------------------------------------------------------


def test_entregar_resultado_listo_sube_video_y_marca_descargado(tmp_path):
    from cortador.servidor import almacen as alm
    from cortador.servidor import bot_telegram as mod

    almacen, cola, _ = _piezas(tmp_path)
    try:
        trabajo = almacen.crear("turno.mp4", 10, propietario="111")
        almacen.guardar_entrada(trabajo, io.BytesIO(b"entrada"))
        almacen.ruta_resultado(trabajo).write_bytes(b"montaje")
        trabajo.estado = alm.LISTO
        almacen.guardar_estado(trabajo)

        bot = MagicMock()
        bot.send_video = AsyncMock()
        bot.send_message = AsyncMock()

        asyncio.run(mod.entregar_resultado(bot, trabajo, almacen))

        bot.send_video.assert_awaited_once()
        assert bot.send_video.await_args.kwargs["chat_id"] == 111
        bot.send_message.assert_not_awaited()
        assert almacen.estado(trabajo.id).descargado is True
        assert not almacen.ruta_entrada(trabajo).exists()
    finally:
        cola.detener(5)


def test_entregar_resultado_pendiente_revision_envia_mensaje_sin_video(tmp_path):
    from cortador.servidor import almacen as alm
    from cortador.servidor import bot_telegram as mod

    almacen, cola, _ = _piezas(tmp_path)
    try:
        trabajo = almacen.crear("turno.mp4", 10, propietario="111")
        almacen.guardar_entrada(trabajo, io.BytesIO(b"entrada"))
        trabajo.estado = alm.PENDIENTE_REVISION
        trabajo.mensaje = "Todavia no tenemos configuracion para esta camara."
        almacen.guardar_estado(trabajo)

        bot = MagicMock()
        bot.send_video = AsyncMock()
        bot.send_message = AsyncMock()

        asyncio.run(mod.entregar_resultado(bot, trabajo, almacen))

        bot.send_video.assert_not_awaited()
        bot.send_message.assert_awaited_once_with(
            chat_id=111, text=trabajo.mensaje)
        assert almacen.estado(trabajo.id).descargado is True
    finally:
        cola.detener(5)


def test_entregar_resultado_demasiado_grande_para_subir_avisa_sin_intentarlo(tmp_path, monkeypatch):
    from cortador.servidor import almacen as alm
    from cortador.servidor import bot_telegram as mod

    almacen, cola, _ = _piezas(tmp_path)
    try:
        monkeypatch.setattr(mod, "LIMITE_SUBIDA_BYTES", 10)
        trabajo = almacen.crear("turno.mp4", 10, propietario="111")
        almacen.guardar_entrada(trabajo, io.BytesIO(b"entrada"))
        almacen.ruta_resultado(trabajo).write_bytes(b"x" * 20)
        trabajo.estado = alm.LISTO
        almacen.guardar_estado(trabajo)

        bot = MagicMock()
        bot.send_video = AsyncMock()
        bot.send_message = AsyncMock()

        asyncio.run(mod.entregar_resultado(bot, trabajo, almacen))

        bot.send_video.assert_not_awaited()
        texto = bot.send_message.await_args.kwargs["text"]
        assert "grande" in texto.lower()
        assert "administrador" in texto.lower()
        assert almacen.estado(trabajo.id).descargado is True
    finally:
        cola.detener(5)


def test_construir_al_terminar_entrega_por_el_loop_correcto(tmp_path):
    """El callback de Cola corre en el hilo trabajador; debe reenviarse al
    event loop del bot via run_coroutine_threadsafe, no ejecutarse directo."""
    from cortador.servidor import almacen as alm
    from cortador.servidor import bot_telegram as mod

    almacen, cola, _ = _piezas(tmp_path)
    try:
        trabajo = almacen.crear("turno.mp4", 10, propietario="111")
        almacen.guardar_entrada(trabajo, io.BytesIO(b"entrada"))
        almacen.ruta_resultado(trabajo).write_bytes(b"montaje")
        trabajo.estado = alm.LISTO
        almacen.guardar_estado(trabajo)

        bot = MagicMock()
        bot.send_video = AsyncMock()
        bot.send_message = AsyncMock()

        loop = asyncio.new_event_loop()
        hilo_loop = threading.Thread(target=loop.run_forever, daemon=True)
        hilo_loop.start()
        try:
            al_terminar = mod.construir_al_terminar(bot, loop, almacen)
            # se llama como lo haria Cola: desde un hilo distinto al del loop
            al_terminar(trabajo)
        finally:
            loop.call_soon_threadsafe(loop.stop)
            hilo_loop.join(5)
            loop.close()

        bot.send_video.assert_awaited_once()
        assert almacen.estado(trabajo.id).descargado is True
    finally:
        cola.detener(5)


def test_al_terminar_ignora_trabajos_sin_propietario(tmp_path):
    """Un trabajo subido por la API HTTP publica (sin dueno de Telegram) no
    debe intentar enviar nada por el bot."""
    from cortador.servidor import almacen as alm
    from cortador.servidor import bot_telegram as mod

    almacen, cola, _ = _piezas(tmp_path)
    try:
        trabajo = almacen.crear("turno.mp4", 10)  # sin propietario
        trabajo.estado = alm.LISTO
        almacen.guardar_estado(trabajo)

        bot = MagicMock()
        bot.send_video = AsyncMock()
        bot.send_message = AsyncMock()
        loop = asyncio.new_event_loop()

        al_terminar = mod.construir_al_terminar(bot, loop, almacen)
        al_terminar(trabajo)

        bot.send_video.assert_not_awaited()
        bot.send_message.assert_not_awaited()
        loop.close()
    finally:
        cola.detener(5)


# ---------------------------------------------------------------------------
# arranque/parada del bot en segundo plano, sin red real
# ---------------------------------------------------------------------------


def test_registrar_handlers_registra_start_estado_y_video(tmp_path):
    from cortador.servidor import bot_telegram as mod

    almacen, cola, usuarios = _piezas(tmp_path)
    try:
        app_falsa = _AppFalsa()

        mod.registrar_handlers(app_falsa, almacen=almacen, cola=cola, usuarios=usuarios)

        assert len(app_falsa.handlers) >= 3
    finally:
        cola.detener(5)


def test_iniciar_bot_en_segundo_plano_arranca_y_se_detiene_limpio(tmp_path):
    from cortador.servidor import bot_telegram as mod

    almacen, cola, usuarios = _piezas(tmp_path)
    app_falsa = _AppFalsa()
    try:
        control = mod.iniciar_bot_en_segundo_plano(
            "token-de-prueba-nunca-real", almacen, cola, usuarios,
            construir_app=lambda token: app_falsa)

        assert len(app_falsa.handlers) >= 3
        assert control.detener(10) is True
    finally:
        cola.detener(5)
