import json
import threading

import pytest

from cortador.servidor import almacen as mod

VIDEO = ("archivo", ("turno.mov", b"contenido-de-video", "video/quicktime"))


def _entrega(mensaje="Tu montaje está listo.", contenido=b"montaje"):
    """Procesador falso: entrega un resultado sin tocar ffmpeg."""
    def procesar(trabajo, guardia):
        if contenido is not None:
            guardia.ruta_resultado(trabajo).write_bytes(contenido)
        trabajo.estado = mod.LISTO
        trabajo.mensaje = mensaje
        guardia.guardar_estado(trabajo)

    return procesar


def _subir(servicio, archivo=VIDEO):
    return servicio.cliente.post(
        "/v1/trabajos", files=dict([archivo]), headers=servicio.cabeceras)


def _carpetas(servicio):
    raiz = servicio.datos / "trabajos"
    return sorted(p.name for p in raiz.iterdir()) if raiz.is_dir() else []


def test_salud_responde_sin_token(servicio):
    activo = servicio()

    respuesta = activo.cliente.get("/salud")

    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "ok"


def test_sin_token_configurado_el_servicio_se_niega_a_arrancar():
    pytest.importorskip("fastapi", reason="falta el extra `servidor`")
    from cortador.servidor import api

    for entorno in ({}, {"SCOUTCUTS_TOKEN_QA": "   "}, {"SCOUTCUTS_TOKEN_QA": "corto"}):
        with pytest.raises(api.FaltaConfiguracion) as fallo:
            api.Config.desde_entorno(entorno)
        assert "SCOUTCUTS_TOKEN_QA" in str(fallo.value)

    with pytest.raises(api.FaltaConfiguracion):
        api.crear_app(entorno={})


def test_subir_consultar_y_descargar_el_montaje(servicio):
    activo = servicio(_entrega())

    creado = _subir(activo)
    assert creado.status_code == 201
    cuerpo = creado.json()
    identificador = cuerpo["id"]
    assert cuerpo["estado"] in (mod.RECIBIDO, mod.EN_COLA, mod.PROCESANDO, mod.LISTO)
    assert cuerpo["mensaje"]
    assert "turno.mov" not in identificador

    assert activo.cola.esperar(10) is True
    estado = activo.cliente.get(f"/v1/trabajos/{identificador}", headers=activo.cabeceras)
    assert estado.status_code == 200
    datos = estado.json()
    assert datos["estado"] == mod.LISTO
    assert datos["mensaje"] == "Tu montaje está listo."
    assert datos["resultado_disponible"] is True
    assert datos["nombre"] == "turno.mov"

    descarga = activo.cliente.get(
        f"/v1/trabajos/{identificador}/resultado", headers=activo.cabeceras)
    assert descarga.status_code == 200
    assert descarga.content == b"montaje"
    assert "attachment" in descarga.headers["content-disposition"]


def test_la_descarga_borra_el_video_de_entrada(servicio):
    activo = servicio(_entrega())

    identificador = _subir(activo).json()["id"]
    assert activo.cola.esperar(10) is True
    trabajo = activo.almacen.estado(identificador)
    assert activo.almacen.ruta_entrada(trabajo).exists()

    activo.cliente.get(f"/v1/trabajos/{identificador}/resultado", headers=activo.cabeceras)

    assert not activo.almacen.ruta_entrada(trabajo).exists()
    assert activo.almacen.estado(identificador).descargado is True


@pytest.mark.parametrize("cabeceras", [
    {},
    {"Authorization": "Bearer token-equivocado"},
    {"Authorization": "Basic token-de-pruebas-del-qa"},
])
def test_peticiones_sin_token_valido_se_rechazan(servicio, cabeceras):
    activo = servicio(_entrega())

    respuesta = activo.cliente.post("/v1/trabajos", files=dict([VIDEO]), headers=cabeceras)

    assert respuesta.status_code == 401
    mensaje = respuesta.json()["mensaje"]
    assert "acceso" in mensaje.lower() or "identificarte" in mensaje.lower()
    assert "token-de-pruebas" not in json.dumps(respuesta.json())


def test_sin_token_no_crea_carpeta_de_trabajo(servicio):
    """La autenticacion debe cortar antes de leer el multipart: si un cliente
    sin token pudiera llegar a crear la carpeta, estaria gastando disco y CPU
    del servidor de un solo nucleo antes de que se lo rechace."""
    activo = servicio(_entrega())

    respuesta = activo.cliente.post(
        "/v1/trabajos", files=dict([VIDEO]), headers={})

    assert respuesta.status_code == 401
    assert _carpetas(activo) == []


def test_una_segunda_subida_simultanea_se_rechaza_con_503(servicio, monkeypatch):
    """El servidor tiene un solo nucleo: dos subidas escribiendo a disco a la
    vez no las termina antes, solo arriesga la memoria. Mientras hay una
    subida en curso, la siguiente debe recibir 503 de inmediato, no esperar
    turno detras de la que ya esta escribiendo a disco."""
    empezo = threading.Event()
    continuar = threading.Event()

    activo = servicio(_entrega())
    original = type(activo.almacen).guardar_entrada

    def lenta(self, trabajo, flujo, **kw):
        empezo.set()
        assert continuar.wait(10)
        return original(self, trabajo, flujo, **kw)

    monkeypatch.setattr(type(activo.almacen), "guardar_entrada", lenta)

    hilo = None
    try:
        resultado = {}

        def enviar_primero():
            resultado["primero"] = _subir(activo)

        hilo = threading.Thread(target=enviar_primero)
        hilo.start()
        assert empezo.wait(10)

        segunda = _subir(activo)

        assert segunda.status_code == 503
        assert "otro" in segunda.json()["mensaje"].lower() or \
            "momento" in segunda.json()["mensaje"].lower()
    finally:
        continuar.set()
        if hilo is not None:
            hilo.join(10)
    assert resultado["primero"].status_code == 201


def test_extension_no_soportada_responde_con_mensaje_claro(servicio):
    activo = servicio(_entrega())

    respuesta = _subir(activo, ("archivo", ("notas.pdf", b"x", "application/pdf")))

    assert respuesta.status_code in (400, 415)
    mensaje = respuesta.json()["mensaje"].lower()
    assert "video" in mensaje and "mp4" in mensaje
    assert _carpetas(activo) == []


def test_archivo_demasiado_grande_se_rechaza_y_no_deja_basura(servicio):
    activo = servicio(_entrega(), limite_bytes=16)

    respuesta = _subir(
        activo, ("archivo", ("turno.mp4", b"x" * 4096, "video/mp4")))

    assert respuesta.status_code == 413
    assert "grande" in respuesta.json()["mensaje"].lower()
    assert _carpetas(activo) == []


def test_falta_el_archivo_se_explica_sin_jerga(servicio):
    activo = servicio(_entrega())

    respuesta = activo.cliente.post("/v1/trabajos", headers=activo.cabeceras)

    assert respuesta.status_code == 400
    mensaje = respuesta.json()["mensaje"].lower()
    assert "video" in mensaje
    assert "field" not in mensaje and "body" not in mensaje


def test_estado_informa_la_posicion_en_la_cola_en_espanol(servicio):
    empezo = threading.Event()
    suelta = threading.Event()

    def procesar(trabajo, guardia):
        empezo.set()
        assert suelta.wait(10)

    activo = servicio(procesar)
    try:
        primero = _subir(activo).json()["id"]
        assert empezo.wait(10)
        segundo = _subir(activo).json()["id"]

        en_curso = activo.cliente.get(
            f"/v1/trabajos/{primero}", headers=activo.cabeceras).json()
        en_espera = activo.cliente.get(
            f"/v1/trabajos/{segundo}", headers=activo.cabeceras).json()

        assert en_curso["estado"] == mod.PROCESANDO
        assert en_curso["posicion"] == 0
        assert "analiza" in en_curso["mensaje"].lower()
        assert en_espera["posicion"] == 1
        assert "1" in en_espera["mensaje"]
        assert "delante" in en_espera["mensaje"].lower()
        assert en_espera["resultado_disponible"] is False
    finally:
        suelta.set()


def test_descarga_usa_x_accel_redirect_cuando_esta_activado(servicio):
    activo = servicio(_entrega(), accel=True)

    identificador = _subir(activo).json()["id"]
    assert activo.cola.esperar(10) is True
    respuesta = activo.cliente.get(
        f"/v1/trabajos/{identificador}/resultado", headers=activo.cabeceras)

    assert respuesta.status_code == 200
    interna = respuesta.headers["x-accel-redirect"]
    assert interna.startswith("/protegido/")
    assert identificador in interna
    assert respuesta.content == b""          # el archivo lo sirve nginx
    assert "attachment" in respuesta.headers["content-disposition"]


def test_descarga_antes_de_tiempo_explica_que_todavia_no_esta(servicio):
    empezo = threading.Event()
    suelta = threading.Event()

    def procesar(trabajo, guardia):
        empezo.set()
        assert suelta.wait(10)

    activo = servicio(procesar)
    try:
        identificador = _subir(activo).json()["id"]
        assert empezo.wait(10)
        respuesta = activo.cliente.get(
            f"/v1/trabajos/{identificador}/resultado", headers=activo.cabeceras)

        assert respuesta.status_code == 409
        assert "analiza" in respuesta.json()["mensaje"].lower()
    finally:
        suelta.set()


def test_trabajo_listo_sin_montaje_explica_que_no_hubo_swings(servicio):
    sin_swings = "Revisamos el video y no encontramos swings."
    activo = servicio(_entrega(mensaje=sin_swings, contenido=None))

    identificador = _subir(activo).json()["id"]
    assert activo.cola.esperar(10) is True
    estado = activo.cliente.get(
        f"/v1/trabajos/{identificador}", headers=activo.cabeceras).json()
    descarga = activo.cliente.get(
        f"/v1/trabajos/{identificador}/resultado", headers=activo.cabeceras)

    assert estado["resultado_disponible"] is False
    assert descarga.status_code == 404
    assert "swings" in descarga.json()["mensaje"].lower()


def test_pendiente_de_revision_llega_al_scout_en_espanol(servicio):
    aviso = "La cámara de este video todavía no está configurada."

    def procesar(trabajo, guardia):
        trabajo.estado = mod.PENDIENTE_REVISION
        trabajo.mensaje = aviso
        guardia.guardar_estado(trabajo)

    activo = servicio(procesar)
    identificador = _subir(activo).json()["id"]
    assert activo.cola.esperar(10) is True

    estado = activo.cliente.get(
        f"/v1/trabajos/{identificador}", headers=activo.cabeceras).json()

    assert estado["estado"] == mod.PENDIENTE_REVISION
    assert estado["mensaje"] == aviso
    assert estado["resultado_disponible"] is False


@pytest.mark.parametrize("identificador", ["inventado", "../../etc/passwd", "f" * 32])
def test_identificador_desconocido_responde_404_sin_pistas(servicio, identificador):
    activo = servicio(_entrega())

    respuesta = activo.cliente.get(
        f"/v1/trabajos/{identificador}", headers=activo.cabeceras)

    assert respuesta.status_code == 404
    mensaje = respuesta.json()["mensaje"]
    assert "trabajos" not in mensaje.lower()
    assert ":" not in mensaje and "\\" not in mensaje


@pytest.mark.parametrize("origen,permitido", [
    ("https://scoutcuts.com", True),
    ("https://www.scoutcuts.com", True),
    ("http://scoutcuts.com", False),
    ("https://scoutcuts.com.malicioso.net", False),
])
def test_cors_solo_permite_el_sitio_de_scoutcuts(servicio, origen, permitido):
    activo = servicio(_entrega())

    respuesta = activo.cliente.options("/v1/trabajos", headers={
        "Origin": origen,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization",
    })

    concedido = respuesta.headers.get("access-control-allow-origin")
    assert (concedido == origen) is permitido


def test_un_error_interno_no_expone_trazas_ni_rutas(servicio, monkeypatch):
    activo = servicio(_entrega(), errores_crudos=False)
    identificador = _subir(activo).json()["id"]
    assert activo.cola.esperar(10) is True

    def estallar(_identificador):
        raise OSError("no se pudo leer C:/Users/Ana/DatosQA/servidor/estado.json")

    monkeypatch.setattr(activo.almacen, "estado", estallar)
    respuesta = activo.cliente.get(
        f"/v1/trabajos/{identificador}", headers=activo.cabeceras)

    assert respuesta.status_code == 500
    texto = json.dumps(respuesta.json(), ensure_ascii=False)
    assert "Traceback" not in texto
    for secreto in ("C:/Users", "Ana", "estado.json"):
        assert secreto not in texto


def test_subir_purga_lo_vencido_sin_tocar_lo_reciente(servicio):
    activo = servicio(_entrega(), max_edad_horas=0.0)

    viejo = _subir(activo).json()["id"]
    assert activo.cola.esperar(10) is True
    nuevo = _subir(activo).json()["id"]

    assert not activo.almacen.carpeta(viejo).exists()
    assert activo.almacen.carpeta(nuevo).exists()


def test_borrar_solo_elimina_las_sondas_de_verificacion(servicio):
    """El E2E de despliegue sube una sonda real al servidor en vivo y necesita
    poder limpiarla al terminar. Ese borrado tiene que ser imposible de usar
    contra material de un scout: con la marca `verificacion=1` el DELETE
    responde 204 y la carpeta desaparece; sin esa marca responde 404 y la
    carpeta sigue intacta, aunque el token sea el correcto."""
    activo = servicio(_entrega())

    sonda = activo.cliente.post(
        "/v1/trabajos?verificacion=1", files=dict([VIDEO]),
        headers=activo.cabeceras)
    assert sonda.status_code == 201
    id_sonda = sonda.json()["id"]
    assert activo.cola.esperar(10) is True

    borrado = activo.cliente.delete(
        f"/v1/trabajos/{id_sonda}", headers=activo.cabeceras)

    assert borrado.status_code == 204
    assert not activo.almacen.carpeta(id_sonda).exists()

    id_real = _subir(activo).json()["id"]
    assert activo.cola.esperar(10) is True

    negado = activo.cliente.delete(
        f"/v1/trabajos/{id_real}", headers=activo.cabeceras)

    assert negado.status_code == 404
    assert activo.almacen.carpeta(id_real).exists()
    assert activo.almacen.estado(id_real).estado == mod.LISTO


def test_config_desde_entorno_lee_el_token_del_bot_si_esta_presente(tmp_path):
    pytest.importorskip("fastapi", reason="falta el extra `servidor`")
    from cortador.servidor import api

    sin_token = api.Config.desde_entorno({
        "SCOUTCUTS_TOKEN_QA": "x" * 20, "SCOUTCUTS_DATOS": str(tmp_path),
    })
    assert sin_token.telegram_token is None

    con_token = api.Config.desde_entorno({
        "SCOUTCUTS_TOKEN_QA": "x" * 20, "SCOUTCUTS_DATOS": str(tmp_path),
        "SCOUTCUTS_TELEGRAM_BOT_TOKEN": "123:ABC-token-secreto",
    })
    assert con_token.telegram_token == "123:ABC-token-secreto"


def test_config_usuarios_raiz_usa_subcarpeta_de_raiz_por_defecto(tmp_path):
    pytest.importorskip("fastapi", reason="falta el extra `servidor`")
    from cortador.servidor import api

    config = api.Config(token="x" * 20, raiz=tmp_path)
    assert config.usuarios_raiz == tmp_path / "usuarios"

    config_explicito = api.Config(
        token="x" * 20, raiz=tmp_path, usuarios_base=tmp_path / "otra_carpeta")
    assert config_explicito.usuarios_raiz == tmp_path / "otra_carpeta"


def test_config_desde_entorno_lee_scoutcuts_usuarios_si_esta_presente(tmp_path):
    """La misma variable que lee `cortador usuarios ...` (cli.py) debe

    llegar hasta la API: si el administrador crea cuentas con
    SCOUTCUTS_USUARIOS=/ruta/x pero la API arranca sin leer esa variable,
    el bot busca las cuentas en el default (`SCOUTCUTS_DATOS/usuarios`) y
    nunca encuentra a nadie que el admin acaba de registrar.
    """
    pytest.importorskip("fastapi", reason="falta el extra `servidor`")
    from cortador.servidor import api

    otra = tmp_path / "usuarios_aparte"
    config = api.Config.desde_entorno({
        "SCOUTCUTS_TOKEN_QA": "x" * 20, "SCOUTCUTS_DATOS": str(tmp_path),
        "SCOUTCUTS_USUARIOS": str(otra),
    })
    assert config.usuarios_raiz == otra

    sin_variable = api.Config.desde_entorno({
        "SCOUTCUTS_TOKEN_QA": "x" * 20, "SCOUTCUTS_DATOS": str(tmp_path),
    })
    assert sin_variable.usuarios_raiz == tmp_path / "usuarios"


def test_un_token_de_telegram_invalido_no_impide_que_salud_responda(servicio, caplog):
    """Un fallo al arrancar el bot (p. ej. token invalido) se registra en el
    logger estandar, pero /salud debe seguir respondiendo 200: la regla de
    oro es que el bot nunca tumbe la API HTTP."""
    import logging

    from cortador.servidor import api as api_mod

    activo = servicio(_entrega())
    config_con_token_malo = api_mod.Config(
        token=activo.config.token, raiz=activo.datos, accel=False,
        telegram_token="token-invalido-no-apunta-a-nada",
    )
    with caplog.at_level(logging.ERROR):
        app = api_mod.crear_app(
            config_con_token_malo, almacen=activo.almacen, cola=activo.cola)
        from fastapi.testclient import TestClient

        with TestClient(app) as cliente:
            respuesta = cliente.get("/salud")

    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "ok"
    # El token invalido nunca debe aparecer en los logs.
    assert "token-invalido-no-apunta-a-nada" not in caplog.text


def test_fallo_sincrono_al_construir_el_bot_tampoco_filtra_el_token(servicio, caplog, monkeypatch):
    """Si el bot falla ANTES de arrancar su hilo propio (p. ej. error al

    construir el `Application`), `crear_app` atrapa la excepcion en su
    propio `except` — ese camino no pasa por la redaccion de
    `bot_telegram._correr`, asi que debe redactar el token el mismo.
    """
    import logging

    from cortador.servidor import api as api_mod
    from cortador.servidor import bot_telegram as bot_mod

    token_secreto = "123:token-secreto-de-construccion"

    def _construir_que_falla(*_args, **_kwargs):
        raise RuntimeError(f"fallo simulado con el token {token_secreto} adentro")

    monkeypatch.setattr(bot_mod, "iniciar_bot_en_segundo_plano", _construir_que_falla)

    activo = servicio(_entrega())
    config_con_token = api_mod.Config(
        token=activo.config.token, raiz=activo.datos, accel=False,
        telegram_token=token_secreto,
    )
    with caplog.at_level(logging.ERROR):
        app = api_mod.crear_app(
            config_con_token, almacen=activo.almacen, cola=activo.cola)
        from fastapi.testclient import TestClient

        with TestClient(app) as cliente:
            respuesta = cliente.get("/salud")

    assert respuesta.status_code == 200
    assert token_secreto not in caplog.text


NOMBRE_INSTALADOR = "CortadorTurnosQA-Portable.zip"


def test_descarga_del_instalador_pide_el_codigo_por_formulario_y_lo_entrega_por_nginx(
        servicio, tmp_path):
    """Entrega protegida del instalador (descargas.scoutcuts.com).

    El ZIP pesa ~231 MiB en un servidor de un solo nucleo: la API nunca debe
    leerlo ni enviarlo ella misma, solo autorizar y delegar el envio a nginx
    con `X-Accel-Redirect` (cuerpo vacio). El codigo de acceso viaja en el
    cuerpo de un POST, nunca en la URL: en la URL quedaria en los logs de
    nginx, en el historial del navegador y en el Referer. Descargar el
    instalador no es procesar un video, asi que no gasta cuota mensual.
    """
    carpeta = tmp_path / "releases"
    activo = servicio(_entrega(), descargas=carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / NOMBRE_INSTALADOR).write_bytes(b"PK\x03\x04" + b"instalador" * 1024)

    from cortador.servidor.usuarios import Usuarios

    usuarios = Usuarios(activo.config.usuarios_raiz)
    ana = usuarios.crear("", "Ana Scout", cuota_mensual=20)
    inactivo = usuarios.crear("", "Luis Baja", cuota_mensual=20)
    usuarios.desactivar(inactivo)

    pagina = activo.cliente.get("/v1/descargas")

    assert pagina.status_code == 200
    assert "text/html" in pagina.headers["content-type"]
    html = pagina.text.lower()
    assert "<form" in html
    assert 'method="post"' in html or "method='post'" in html
    assert "/v1/descargas/instalador" in html
    assert 'name="codigo_acceso"' in html or "name='codigo_acceso'" in html

    entrega = activo.cliente.post(
        "/v1/descargas/instalador", data={"codigo_acceso": ana.codigo_acceso})

    assert entrega.status_code == 200
    assert entrega.content == b""            # el ZIP lo sirve nginx, no Python
    assert entrega.headers["x-accel-redirect"] == f"/protegido/{NOMBRE_INSTALADOR}"
    disposicion = entrega.headers["content-disposition"]
    assert "attachment" in disposicion
    assert NOMBRE_INSTALADOR in disposicion
    assert usuarios.por_codigo_acceso(ana.codigo_acceso).usados_mes == 0

    falso = activo.cliente.post(
        "/v1/descargas/instalador", data={"codigo_acceso": "CODIGO-FALSO"})
    desactivada = activo.cliente.post(
        "/v1/descargas/instalador", data={"codigo_acceso": inactivo.codigo_acceso})

    assert falso.status_code == 401
    assert desactivada.status_code == 401
    # Misma respuesta exacta: quien prueba codigos al azar no puede deducir
    # cual existe y solo esta desactivado.
    assert falso.text == desactivada.text
    assert "x-accel-redirect" not in falso.headers
    assert "x-accel-redirect" not in desactivada.headers
    for secreto in ("CODIGO-FALSO", inactivo.codigo_acceso, str(carpeta)):
        assert secreto not in falso.text + desactivada.text


def test_config_descargas_lee_scoutcuts_descargas_con_default_bajo_raiz(tmp_path):
    """La carpeta de instaladores se configura como el resto (una variable y
    un default dentro de `raiz`), nunca una ruta absoluta escrita en codigo."""
    pytest.importorskip("fastapi", reason="falta el extra `servidor`")
    from cortador.servidor import api

    base = {"SCOUTCUTS_TOKEN_QA": "x" * 20, "SCOUTCUTS_DATOS": str(tmp_path)}
    otra = tmp_path / "releases_aparte"

    config = api.Config.desde_entorno({**base, "SCOUTCUTS_DESCARGAS": str(otra)})
    assert config.descargas_raiz == otra

    sin_variable = api.Config.desde_entorno(base)
    assert sin_variable.descargas_raiz == tmp_path / "descargas"

    explicito = api.Config(
        token="x" * 20, raiz=tmp_path, descargas_base=tmp_path / "otra_carpeta")
    assert explicito.descargas_raiz == tmp_path / "otra_carpeta"
