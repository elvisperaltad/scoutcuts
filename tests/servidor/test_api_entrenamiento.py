"""Pruebas de los endpoints `/v1/entrenamiento/*`: zona de entrenamiento
PUBLICA (se entra solo con el enlace, sin token ni login), aislada de la
produccion real por carpeta y dataset, y compartida por las cuatro
disciplinas (defensa, bateo, pitcheo, catcher).
"""

from __future__ import annotations

import pytest

from videos_sinteticos import crear_video_con_movimiento_lateral


@pytest.fixture
def servicio_con_entrenamiento(servicio, tmp_path):
    """Variante de la fixture `servicio` con la carpeta de la zona apuntada
    a un tmp_path propio.

    No configura ninguna credencial de entrenamiento: ya no existe. Lo que
    aisla la zona es la carpeta (`entrenamiento_base`), nunca un token.
    """
    pytest.importorskip("fastapi", reason="falta el extra `servidor`")
    from cortador.servidor import api as api_mod

    def construir(procesar=None):
        activo = servicio(procesar)
        config = api_mod.Config(
            token=activo.config.token, raiz=activo.datos, accel=False,
            entrenamiento_base=tmp_path / "zona_qa",
        )
        from cortador.servidor.almacen import Almacen
        app = api_mod.crear_app(
            config, almacen=Almacen(activo.datos), cola=activo.cola)
        from fastapi.testclient import TestClient
        cliente = TestClient(app)
        return cliente, config

    return construir


def _video_real(tmp_path, lado="derecha", nombre="practica.mp4"):
    ruta = tmp_path / nombre
    crear_video_con_movimiento_lateral(ruta, lado=lado, segundos=2.0)
    return ruta


def test_config_desde_entorno_no_tiene_credencial_de_entrenamiento():
    """La zona es publica: no debe quedar ni rastro de una variable de
    entorno que la active o la proteja."""
    pytest.importorskip("fastapi", reason="falta el extra `servidor`")
    from cortador.servidor import api as api_mod

    config = api_mod.Config.desde_entorno({
        "SCOUTCUTS_TOKEN_QA": "un-token-de-produccion-bien-largo",
        "SCOUTCUTS_DATOS": "/tmp/datos",
    })

    assert not hasattr(config, "token_entrenamiento")


def test_las_rutas_existen_sin_configurar_nada(servicio):
    """La zona ya no depende de ninguna variable de entorno: con la
    configuracion minima de produccion, sus rutas ya responden."""
    activo = servicio()
    respuesta = activo.cliente.get("/v1/entrenamiento/modelo")
    assert respuesta.status_code == 200


def test_la_zona_por_defecto_vive_fuera_de_la_carpeta_de_trabajos(servicio):
    """Aislamiento sin credencial: la carpeta por defecto de la zona nunca
    puede ser la de los videos de clientes reales."""
    activo = servicio()
    assert activo.config.entrenamiento_raiz != activo.config.raiz
    assert activo.config.entrenamiento_raiz.name == "entrenamiento_qa"


def test_disciplinas_sin_authorization(servicio_con_entrenamiento):
    cliente, _ = servicio_con_entrenamiento()
    respuesta = cliente.get("/v1/entrenamiento/disciplinas")
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    ids = {d["id"] for d in cuerpo["disciplinas"]}
    assert ids == {"defensa", "bateo", "pitcheo", "catcher"}
    defensa = next(d for d in cuerpo["disciplinas"] if d["id"] == "defensa")
    assert {c["id"] for c in defensa["categorias"]} == {"adelante", "derecha", "izquierda"}


def test_disciplinas_anuncia_limite_y_extensiones_para_la_pagina(servicio_con_entrenamiento):
    """La pagina publica explica el limite y los formatos al QA; los toma de
    aqui para no quedarse desfasada respecto del backend."""
    from cortador.servidor import entrenamiento as ent

    cliente, _ = servicio_con_entrenamiento()
    cuerpo = cliente.get("/v1/entrenamiento/disciplinas").json()

    assert cuerpo["limite_bytes"] == ent.LIMITE_BYTES_POR_DEFECTO
    assert set(cuerpo["extensiones"]) == set(ent.EXTENSIONES_PERMITIDAS)
    assert ".m4v" in cuerpo["extensiones"]


def test_estado_del_modelo_sin_ejemplos_sin_authorization(servicio_con_entrenamiento):
    cliente, _ = servicio_con_entrenamiento()
    respuesta = cliente.get("/v1/entrenamiento/modelo")
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert set(cuerpo) == {"defensa", "bateo", "pitcheo", "catcher"}
    assert cuerpo["defensa"]["total_ejemplos"] == 0
    assert set(cuerpo["defensa"]["categorias"]) == {"adelante", "derecha", "izquierda"}


def test_estado_del_modelo_de_una_disciplina(servicio_con_entrenamiento):
    cliente, _ = servicio_con_entrenamiento()
    respuesta = cliente.get("/v1/entrenamiento/modelo/bateo")
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["disciplina"] == "bateo"
    assert cuerpo["modelo_calibrado"] is False


def test_estado_del_modelo_de_disciplina_desconocida_404(servicio_con_entrenamiento):
    cliente, _ = servicio_con_entrenamiento()
    respuesta = cliente.get("/v1/entrenamiento/modelo/vp_live")
    assert respuesta.status_code == 404


@pytest.mark.parametrize("cabeceras", [
    {},
    {"Authorization": "Bearer lo-que-sea"},
    {"Authorization": "cualquier-cosa-que-no-es-bearer"},
])
def test_la_zona_contesta_igual_con_o_sin_authorization(
        servicio_con_entrenamiento, cabeceras):
    """Ninguna cabecera de autorizacion cambia nada: ni abre ni cierra. Que
    un QA llegue con una Authorization pegada de otra pestana no debe
    hacerle recibir un 401 incomprensible."""
    cliente, _ = servicio_con_entrenamiento()
    respuesta = cliente.get("/v1/entrenamiento/modelo", headers=cabeceras)
    assert respuesta.status_code == 200


def test_el_token_de_produccion_no_es_relevante_en_la_zona(servicio_con_entrenamiento):
    """El token QA de produccion no abre nada aqui porque aqui no hay nada
    que abrir: mandarlo da exactamente la misma respuesta que no mandarlo."""
    cliente, config = servicio_con_entrenamiento()
    con_token = cliente.get(
        "/v1/entrenamiento/modelo",
        headers={"Authorization": f"Bearer {config.token}"},
    )
    sin_token = cliente.get("/v1/entrenamiento/modelo")
    assert con_token.status_code == sin_token.status_code == 200
    assert con_token.json() == sin_token.json()


def test_la_produccion_sigue_exigiendo_su_token(servicio_con_entrenamiento):
    """Abrir la zona de entrenamiento no debe haber aflojado nada de
    produccion: la subida real sigue siendo 401 sin credencial."""
    cliente, _ = servicio_con_entrenamiento()
    assert cliente.get("/v1/trabajos/cualquiera").status_code == 401
    respuesta = cliente.post(
        "/v1/trabajos",
        files={"archivo": ("x.mp4", b"no deberia leerse", "video/mp4")},
    )
    assert respuesta.status_code == 401


def test_subir_entrenar_y_recibir_feedback_de_punta_a_punta(servicio_con_entrenamiento, tmp_path):
    """El flujo completo que usara el QA, sin una sola credencial: subir,
    marcar una repeticion, entrenar, y recibir feedback -- con video real,
    no datos de mentira."""
    cliente, _ = servicio_con_entrenamiento()

    ruta = _video_real(tmp_path, lado="derecha")
    with ruta.open("rb") as flujo:
        subida = cliente.post(
            "/v1/entrenamiento/defensa/videos",
            files={"archivo": ("practica.mp4", flujo, "video/mp4")},
        )
    assert subida.status_code == 201
    assert subida.json()["disciplina"] == "defensa"
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
    )
    assert reintento.status_code == 404


def test_subir_no_toca_el_almacen_de_produccion(servicio_con_entrenamiento, tmp_path):
    """La prueba de aislamiento que importa ahora que no hay token: un video
    de practica nunca aparece como trabajo de un cliente real."""
    cliente, config = servicio_con_entrenamiento()
    ruta = _video_real(tmp_path, lado="derecha")
    with ruta.open("rb") as flujo:
        subida = cliente.post(
            "/v1/entrenamiento/defensa/videos",
            files={"archivo": ("practica.mp4", flujo, "video/mp4")},
        )
    identificador = subida.json()["id"]

    carpeta_trabajos = config.raiz / "trabajos"
    trabajos = (
        [p.name for p in carpeta_trabajos.iterdir()] if carpeta_trabajos.is_dir() else []
    )
    assert identificador not in trabajos
    # Ni consultandolo con la credencial de produccion: para el Almacen real
    # ese id simplemente no existe.
    consulta = cliente.get(
        f"/v1/trabajos/{identificador}",
        headers={"Authorization": f"Bearer {config.token}"},
    )
    assert consulta.status_code == 404


def test_subir_a_disciplina_desconocida_devuelve_404(servicio_con_entrenamiento, tmp_path):
    cliente, _ = servicio_con_entrenamiento()
    ruta = _video_real(tmp_path, lado="derecha")
    with ruta.open("rb") as flujo:
        respuesta = cliente.post(
            "/v1/entrenamiento/vp_live/videos",
            files={"archivo": ("practica.mp4", flujo, "video/mp4")},
        )
    assert respuesta.status_code == 404


def test_subir_formato_no_soportado_devuelve_415(servicio_con_entrenamiento):
    cliente, _ = servicio_con_entrenamiento()
    respuesta = cliente.post(
        "/v1/entrenamiento/defensa/videos",
        files={"archivo": ("documento.txt", b"no es un video", "text/plain")},
    )
    assert respuesta.status_code == 415


def test_subir_m4v_se_acepta(servicio_con_entrenamiento):
    """`.m4v` esta entre las extensiones del motor: la zona publica la
    acepta igual que `.mp4` (no se cae en el 415 de formato)."""
    cliente, _ = servicio_con_entrenamiento()
    respuesta = cliente.post(
        "/v1/entrenamiento/defensa/videos",
        files={"archivo": ("practica.m4v", b"\x00\x00\x00 ftypM4V ", "video/x-m4v")},
    )
    assert respuesta.status_code == 201
    assert respuesta.json()["nombre"] == "practica.m4v"


def test_zona_llena_devuelve_503_sin_guardar_nada(servicio_con_entrenamiento, monkeypatch):
    """Freno al abuso sin cuentas ni codigos: con el presupuesto de disco de
    la zona agotado, la subida se rechaza con 503 y un mensaje claro."""
    from cortador.servidor import entrenamiento as ent

    cliente, _ = servicio_con_entrenamiento()
    monkeypatch.setattr(ent.ZonaEntrenamiento, "hay_espacio", lambda self: False)

    respuesta = cliente.post(
        "/v1/entrenamiento/defensa/videos",
        files={"archivo": ("practica.mp4", b"x" * 1024, "video/mp4")},
    )

    assert respuesta.status_code == 503
    assert respuesta.json()["mensaje"] == ent.MENSAJE_ZONA_LLENA


def test_el_presupuesto_de_la_zona_no_afecta_a_produccion(servicio_con_entrenamiento, monkeypatch):
    """El freno de la zona publica se mira solo en su propia ruta de subida:
    nunca puede rechazar la subida de un cliente real."""
    from cortador.servidor import entrenamiento as ent

    cliente, _ = servicio_con_entrenamiento()
    monkeypatch.setattr(ent.ZonaEntrenamiento, "hay_espacio", lambda self: False)

    # Sin credencial de produccion sigue siendo 401 (no 503): la zona llena
    # no es lo que decide esta ruta.
    respuesta = cliente.post(
        "/v1/trabajos", files={"archivo": ("x.mp4", b"x", "video/mp4")})
    assert respuesta.status_code == 401


def test_entrenar_bateo_no_contamina_el_estado_de_defensa(servicio_con_entrenamiento, tmp_path):
    cliente, _ = servicio_con_entrenamiento()
    ruta = _video_real(tmp_path, lado="derecha", nombre="swing.mp4")
    with ruta.open("rb") as flujo:
        subida = cliente.post(
            "/v1/entrenamiento/bateo/videos",
            files={"archivo": ("swing.mp4", flujo, "video/mp4")},
        )
    identificador = subida.json()["id"]
    cliente.post(
        f"/v1/entrenamiento/videos/{identificador}/entrenar",
        json={
            "video": "swing.mp4",
            "repeticiones": [{
                "categoria": "valido", "inicio": 0.0, "tiro": 2.0,
                "estado": "completa", "seleccionada": True,
            }],
        },
    )

    estado = cliente.get("/v1/entrenamiento/modelo").json()
    assert estado["bateo"]["total_ejemplos"] == 1
    assert estado["defensa"]["total_ejemplos"] == 0


def test_una_subida_de_practica_no_bloquea_la_de_un_cliente_real(
        servicio_con_entrenamiento, tmp_path):
    """La zona tiene su propio cerrojo: usarlo no debe dejar a un cliente
    real con un 503 de "otra subida en curso"."""
    # Procesador que no hace nada: lo que se prueba es el cerrojo de la
    # subida, no el motor de corte.
    cliente, config = servicio_con_entrenamiento(lambda trabajo, guardia: None)
    ruta = _video_real(tmp_path, lado="derecha")
    with ruta.open("rb") as flujo:
        practica = cliente.post(
            "/v1/entrenamiento/defensa/videos",
            files={"archivo": ("practica.mp4", flujo, "video/mp4")},
        )
    assert practica.status_code == 201

    with ruta.open("rb") as flujo:
        real = cliente.post(
            "/v1/trabajos",
            files={"archivo": ("real.mp4", flujo, "video/mp4")},
            headers={"Authorization": f"Bearer {config.token}"},
        )
    assert real.status_code == 201
