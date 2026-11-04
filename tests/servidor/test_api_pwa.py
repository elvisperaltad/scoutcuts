"""Pruebas de los endpoints de la PWA: login por codigo de acceso, subida,
consulta y descarga ligados a la cuenta del scout (no al token QA global)."""

import json
import threading

import pytest

from cortador.servidor import almacen as mod

VIDEO = ("archivo", ("turno.mov", b"contenido-de-video", "video/quicktime"))


def _entrega(mensaje="Tu montaje esta listo.", contenido=b"montaje"):
    def procesar(trabajo, guardia):
        if contenido is not None:
            guardia.ruta_resultado(trabajo).write_bytes(contenido)
        trabajo.estado = mod.LISTO
        trabajo.mensaje = mensaje
        guardia.guardar_estado(trabajo)

    return procesar


def _usuarios_de(activo):
    from cortador.servidor.usuarios import Usuarios

    return Usuarios(activo.config.usuarios_raiz)


def _crear_cuenta(activo, nombre="Ana Scout", cuota_mensual=20):
    return _usuarios_de(activo).crear("", nombre, cuota_mensual=cuota_mensual)


def _cabeceras_pwa(usuario):
    return {"Authorization": f"Bearer {usuario.codigo_acceso}"}


def _subir_pwa(activo, usuario, archivo=VIDEO):
    return activo.cliente.post(
        "/v1/pwa/trabajos", files=dict([archivo]), headers=_cabeceras_pwa(usuario))


def test_sesion_con_codigo_valido_devuelve_datos_de_la_cuenta(servicio):
    activo = servicio(_entrega())
    usuario = _crear_cuenta(activo, nombre="Ana Scout", cuota_mensual=15)

    respuesta = activo.cliente.post(
        "/v1/pwa/sesion", json={"codigo_acceso": usuario.codigo_acceso})

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["nombre"] == "Ana Scout"
    assert cuerpo["cuota_mensual"] == 15
    assert cuerpo["usados_mes"] == 0


def test_sesion_con_codigo_invalido_responde_401_sin_detalles(servicio):
    activo = servicio(_entrega())

    respuesta = activo.cliente.post(
        "/v1/pwa/sesion", json={"codigo_acceso": "CODIGO-FALSO"})

    assert respuesta.status_code == 401
    assert "CODIGO-FALSO" not in json.dumps(respuesta.json())


def test_sesion_de_cuenta_desactivada_responde_401(servicio):
    activo = servicio(_entrega())
    usuarios = _usuarios_de(activo)
    usuario = _crear_cuenta(activo)
    usuarios.desactivar(usuario)

    respuesta = activo.cliente.post(
        "/v1/pwa/sesion", json={"codigo_acceso": usuario.codigo_acceso})

    assert respuesta.status_code == 401


def test_subir_por_pwa_crea_trabajo_con_propietario_y_consume_cuota(servicio):
    activo = servicio(_entrega())
    usuario = _crear_cuenta(activo, cuota_mensual=20)

    respuesta = _subir_pwa(activo, usuario)

    assert respuesta.status_code == 201
    identificador = respuesta.json()["id"]
    assert activo.cola.esperar(10) is True

    trabajo = activo.almacen.estado(identificador)
    assert trabajo.propietario == usuario.id

    usuarios = _usuarios_de(activo)
    recargado = usuarios.por_codigo_acceso(usuario.codigo_acceso)
    assert recargado.usados_mes == 1


def test_subir_por_pwa_sin_codigo_responde_401_y_no_crea_carpeta(servicio):
    activo = servicio(_entrega())

    respuesta = activo.cliente.post("/v1/pwa/trabajos", files=dict([VIDEO]))

    assert respuesta.status_code == 401
    raiz = activo.datos / "trabajos"
    assert not raiz.is_dir() or list(raiz.iterdir()) == []


def test_subir_por_pwa_con_cuota_agotada_responde_mensaje_claro(servicio):
    activo = servicio(_entrega())
    usuario = _crear_cuenta(activo, cuota_mensual=1)
    _usuarios_de(activo).registrar_uso(usuario)
    usuario = _usuarios_de(activo).por_codigo_acceso(usuario.codigo_acceso)

    respuesta = _subir_pwa(activo, usuario)

    assert respuesta.status_code in (409, 403)
    mensaje = respuesta.json()["mensaje"].lower()
    assert "cuota" in mensaje or "límite" in mensaje or "limite" in mensaje


def test_listar_trabajos_pwa_solo_devuelve_los_de_la_cuenta_propia(servicio):
    activo = servicio(_entrega())
    ana = _crear_cuenta(activo, nombre="Ana")
    luis = _crear_cuenta(activo, nombre="Luis")

    _subir_pwa(activo, ana)
    assert activo.cola.esperar(10) is True
    _subir_pwa(activo, luis)
    assert activo.cola.esperar(10) is True

    respuesta = activo.cliente.get("/v1/pwa/trabajos", headers=_cabeceras_pwa(ana))

    assert respuesta.status_code == 200
    trabajos = respuesta.json()["trabajos"]
    assert len(trabajos) == 1


def test_consultar_trabajo_de_otro_usuario_responde_404(servicio):
    activo = servicio(_entrega())
    ana = _crear_cuenta(activo, nombre="Ana")
    luis = _crear_cuenta(activo, nombre="Luis")

    identificador = _subir_pwa(activo, ana).json()["id"]
    assert activo.cola.esperar(10) is True

    respuesta = activo.cliente.get(
        f"/v1/pwa/trabajos/{identificador}", headers=_cabeceras_pwa(luis))

    assert respuesta.status_code == 404


def test_descargar_resultado_propio_por_pwa_funciona_y_borra_el_original(servicio):
    activo = servicio(_entrega())
    usuario = _crear_cuenta(activo)

    identificador = _subir_pwa(activo, usuario).json()["id"]
    assert activo.cola.esperar(10) is True
    trabajo = activo.almacen.estado(identificador)
    assert activo.almacen.ruta_entrada(trabajo).exists()

    respuesta = activo.cliente.get(
        f"/v1/pwa/trabajos/{identificador}/resultado", headers=_cabeceras_pwa(usuario))

    assert respuesta.status_code == 200
    assert respuesta.content == b"montaje"
    assert not activo.almacen.ruta_entrada(trabajo).exists()


def test_descargar_resultado_de_otro_usuario_por_pwa_responde_404(servicio):
    activo = servicio(_entrega())
    ana = _crear_cuenta(activo, nombre="Ana")
    luis = _crear_cuenta(activo, nombre="Luis")

    identificador = _subir_pwa(activo, ana).json()["id"]
    assert activo.cola.esperar(10) is True

    respuesta = activo.cliente.get(
        f"/v1/pwa/trabajos/{identificador}/resultado", headers=_cabeceras_pwa(luis))

    assert respuesta.status_code == 404


def test_una_segunda_subida_pwa_simultanea_se_rechaza_con_503(servicio, monkeypatch):
    """Mismo candado global que las subidas por la API publica y el bot: un
    solo nucleo, una sola escritura a disco a la vez sin importar el canal."""
    empezo = threading.Event()
    continuar = threading.Event()

    activo = servicio(_entrega())
    usuario = _crear_cuenta(activo)
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
            resultado["primero"] = _subir_pwa(activo, usuario)

        hilo = threading.Thread(target=enviar_primero)
        hilo.start()
        assert empezo.wait(10)

        segunda = _subir_pwa(activo, usuario)

        assert segunda.status_code == 503
    finally:
        continuar.set()
        if hilo is not None:
            hilo.join(10)
    assert resultado["primero"].status_code == 201
