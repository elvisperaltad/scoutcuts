"""Pruebas de los endpoints `/v1/entrenamiento/*`: zona de entrenamiento QA
expuesta por la API, aislada de la produccion real por un token distinto.
"""

from __future__ import annotations

import pytest

from videos_sinteticos import crear_video_con_movimiento_lateral


TOKEN_ENTRENAMIENTO = "token-de-entrenamiento-del-qa"


@pytest.fixture
def servicio_con_entrenamiento(servicio, tmp_path):
    """Variante de la fixture `servicio` con el token de entrenamiento
    tambien configurado (por defecto `servicio` no lo activa, para que las
    pruebas normales de produccion nunca vean estas rutas)."""
    pytest.importorskip("fastapi", reason="falta el extra `servidor`")
    from cortador.servidor import api as api_mod

    def construir(procesar=None):
        activo = servicio(procesar)
        config = api_mod.Config(
            token=activo.config.token, raiz=activo.datos, accel=False,
            token_entrenamiento=TOKEN_ENTRENAMIENTO,
            entrenamiento_base=tmp_path / "zona_qa",
        )
        from cortador.servidor.almacen import Almacen
        app = api_mod.crear_app(
            config, almacen=Almacen(activo.datos), cola=activo.cola)
        from fastapi.testclient import TestClient
        cliente = TestClient(app)
        return cliente, config

    return construir


def _cabeceras():
    return {"Authorization": f"Bearer {TOKEN_ENTRENAMIENTO}"}


def _video_real(tmp_path, lado="derecha", nombre="practica.mp4"):
    ruta = tmp_path / nombre
    crear_video_con_movimiento_lateral(ruta, lado=lado, segundos=2.0)
    return ruta


def test_sin_token_de_entrenamiento_configurado_las_rutas_no_existen(servicio):
    """Sin SCOUTCUTS_TOKEN_ENTRENAMIENTO, estas rutas no deben registrarse
    en absoluto: la produccion real no debe ni saber que existen."""
    activo = servicio()
    respuesta = activo.cliente.get("/v1/entrenamiento/modelo")
    assert respuesta.status_code == 404


def test_estado_del_modelo_sin_ejemplos(servicio_con_entrenamiento):
    cliente, _ = servicio_con_entrenamiento()
    respuesta = cliente.get("/v1/entrenamiento/modelo", headers=_cabeceras())
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["total_ejemplos"] == 0
    assert cuerpo["modelo_calibrado"] is False
    assert set(cuerpo["categorias"]) == {"adelante", "derecha", "izquierda"}


def test_estado_del_modelo_requiere_el_token_correcto(servicio_con_entrenamiento):
    cliente, _ = servicio_con_entrenamiento()
    respuesta = cliente.get(
        "/v1/entrenamiento/modelo",
        headers={"Authorization": "Bearer token-equivocado"},
    )
    assert respuesta.status_code == 401


def test_el_token_de_produccion_no_sirve_para_entrenamiento(servicio_con_entrenamiento):
    """Aislamiento de credenciales: el token QA de produccion NUNCA debe
    abrir la zona de entrenamiento."""
    cliente, config = servicio_con_entrenamiento()
    respuesta = cliente.get(
        "/v1/entrenamiento/modelo",
        headers={"Authorization": f"Bearer {config.token}"},
    )
    assert respuesta.status_code == 401


def test_subir_entrenar_y_recibir_feedback_de_punta_a_punta(servicio_con_entrenamiento, tmp_path):
    """El flujo completo que usara el QA: subir, marcar una repeticion,
    entrenar, y recibir feedback -- con video real, no datos de mentira."""
    cliente, _ = servicio_con_entrenamiento()

    ruta = _video_real(tmp_path, lado="derecha")
    with ruta.open("rb") as flujo:
        subida = cliente.post(
            "/v1/entrenamiento/videos",
            files={"archivo": ("practica.mp4", flujo, "video/mp4")},
            headers=_cabeceras(),
        )
    assert subida.status_code == 201
    identificador = subida.json()["id"]

    entrenar = cliente.post(
        f"/v1/entrenamiento/videos/{identificador}/entrenar",
        json={
            "video": "practica.mp4",
            "repeticiones": [{
                "categoria": "derecha", "inicio": 0.0, "tiro": 2.0,
                "estado": "completa", "seleccionada": True,
            }],
        },
        headers=_cabeceras(),
    )
    assert entrenar.status_code == 200
    cuerpo = entrenar.json()
    assert cuerpo["ejemplos_agregados"] == 1
    assert cuerpo["total_ejemplos_dataset"] == 1

    # Entrenar dos veces el mismo video debe fallar: ya se borro.
    reintento = cliente.post(
        f"/v1/entrenamiento/videos/{identificador}/entrenar",
        json={
            "video": "practica.mp4",
            "repeticiones": [{
                "categoria": "derecha", "inicio": 0.0, "tiro": 2.0,
                "estado": "completa", "seleccionada": True,
            }],
        },
        headers=_cabeceras(),
    )
    assert reintento.status_code == 404


def test_subir_formato_no_soportado_devuelve_415(servicio_con_entrenamiento):
    cliente, _ = servicio_con_entrenamiento()
    respuesta = cliente.post(
        "/v1/entrenamiento/videos",
        files={"archivo": ("documento.txt", b"no es un video", "text/plain")},
        headers=_cabeceras(),
    )
    assert respuesta.status_code == 415
