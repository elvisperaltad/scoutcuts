"""Pruebas de `cortador.defensa_ml`: aprendizaje incremental de defensa a
partir de caracteristicas numericas, nunca del video.
"""

from __future__ import annotations

import json

import pytest

from cortador.defensa_ml import (
    Caracteristicas,
    CategoriaDesconocida,
    Dataset,
    ModeloDefensa,
)


def test_caracteristicas_rechaza_valores_invalidos():
    with pytest.raises(ValueError):
        Caracteristicas(duracion=0.0, fuerza_pico=1.0, centro_x=0.5)
    with pytest.raises(ValueError):
        Caracteristicas(duracion=1.0, fuerza_pico=-1.0, centro_x=0.5)
    with pytest.raises(ValueError):
        Caracteristicas(duracion=1.0, fuerza_pico=1.0, centro_x=1.5)


def test_dataset_vacio_tiene_las_tres_categorias_sin_ejemplos():
    dataset = Dataset.vacio()
    assert set(dataset.ejemplos) == {"adelante", "derecha", "izquierda"}
    assert dataset.total_ejemplos() == 0


def test_agregar_categoria_desconocida_falla():
    dataset = Dataset.vacio()
    with pytest.raises(CategoriaDesconocida):
        dataset.agregar("pitcheo", Caracteristicas(1.0, 1.0, 0.5))


def test_dataset_guardar_y_cargar_solo_contiene_numeros_nunca_rutas_de_video(tmp_path):
    dataset = Dataset.vacio()
    dataset.agregar("adelante", Caracteristicas(duracion=4.4, fuerza_pico=12.3, centro_x=0.5))
    dataset.agregar("derecha", Caracteristicas(duracion=6.4, fuerza_pico=9.1, centro_x=0.8))
    dataset.agregar("izquierda", Caracteristicas(duracion=3.3, fuerza_pico=10.0, centro_x=0.2))

    ruta = tmp_path / "dataset_defensa.json"
    dataset.guardar(ruta)

    # El contenido en disco es solo numeros: ninguna cadena que parezca una
    # ruta de archivo de video o un nombre de video.
    crudo = ruta.read_text(encoding="utf-8")
    assert ".mp4" not in crudo.lower()
    assert ".mov" not in crudo.lower()

    recargado = Dataset.cargar(ruta)
    assert recargado.total_ejemplos() == 3
    assert recargado.ejemplos["adelante"][0].duracion == 4.4


def test_dataset_cargar_ruta_inexistente_devuelve_vacio(tmp_path):
    dataset = Dataset.cargar(tmp_path / "no-existe.json")
    assert dataset.total_ejemplos() == 0


def _dataset_minimo() -> Dataset:
    dataset = Dataset.vacio()
    # "adelante": pico fuerte, centrado.
    dataset.agregar("adelante", Caracteristicas(duracion=4.4, fuerza_pico=20.0, centro_x=0.5))
    # "derecha": igual de fuerte pero hacia el lado derecho del encuadre.
    dataset.agregar("derecha", Caracteristicas(duracion=6.4, fuerza_pico=20.0, centro_x=0.9))
    # "izquierda": hacia el lado izquierdo.
    dataset.agregar("izquierda", Caracteristicas(duracion=6.4, fuerza_pico=20.0, centro_x=0.1))
    return dataset


def test_calibrar_sin_al_menos_un_ejemplo_por_categoria_falla():
    dataset = Dataset.vacio()
    dataset.agregar("adelante", Caracteristicas(4.4, 20.0, 0.5))
    with pytest.raises(ValueError, match="derecha"):
        ModeloDefensa.calibrar(dataset)


def test_modelo_clasifica_correctamente_un_ejemplo_claro_de_cada_categoria():
    modelo = ModeloDefensa.calibrar(_dataset_minimo())

    categoria, confianza = modelo.clasificar(Caracteristicas(4.3, 19.5, 0.5))
    assert categoria == "adelante"

    categoria, confianza = modelo.clasificar(Caracteristicas(6.3, 19.8, 0.92))
    assert categoria == "derecha"

    categoria, confianza = modelo.clasificar(Caracteristicas(6.5, 20.2, 0.08))
    assert categoria == "izquierda"


def test_confianza_cae_cuando_el_ejemplo_esta_a_medio_camino_entre_dos_categorias():
    modelo = ModeloDefensa.calibrar(_dataset_minimo())
    # centro_x=0.5 esta justo entre "derecha" (0.9) e "izquierda" (0.1), y
    # "adelante" tambien esta en 0.5 -- el caso ambiguo real.
    _, confianza_clara = modelo.clasificar(Caracteristicas(4.4, 20.0, 0.5))
    _, confianza_ambigua = modelo.clasificar(Caracteristicas(5.5, 20.0, 0.5))
    # La clara (coincide exactamente con el perfil de "adelante") debe tener
    # mas confianza que una a medio camino entre dos perfiles.
    assert confianza_clara >= confianza_ambigua


def test_modelo_guardar_y_cargar_preserva_la_clasificacion(tmp_path):
    modelo = ModeloDefensa.calibrar(_dataset_minimo())
    ruta = tmp_path / "modelo_defensa.json"
    modelo.guardar(ruta)

    recargado = ModeloDefensa.cargar(ruta)
    categoria_original, _ = modelo.clasificar(Caracteristicas(4.3, 19.5, 0.5))
    categoria_recargada, _ = recargado.clasificar(Caracteristicas(4.3, 19.5, 0.5))
    assert categoria_original == categoria_recargada == "adelante"
    assert recargado.total_ejemplos == 3


def test_un_solo_ejemplo_por_categoria_calibra_pero_con_desviacion_de_reserva():
    """Con 1 ejemplo no hay forma de medir dispersion real; el modelo no debe
    reventar ni fingir una desviacion de cero (eso haria la confianza
    explotar con cualquier variacion minima, un sobreajuste real)."""
    dataset = Dataset.vacio()
    dataset.agregar("adelante", Caracteristicas(4.4, 20.0, 0.5))
    dataset.agregar("derecha", Caracteristicas(6.4, 20.0, 0.9))
    dataset.agregar("izquierda", Caracteristicas(6.4, 20.0, 0.1))

    modelo = ModeloDefensa.calibrar(dataset)
    for perfil in modelo.perfiles.values():
        assert perfil.desv_duracion > 0
        assert perfil.desv_fuerza > 0
        assert perfil.desv_centro_x > 0


from videos_sinteticos import crear_video_con_movimiento_lateral as _crear_video_con_movimiento_lateral
from videos_sinteticos import cv2_disponible  # noqa: F401 - fixture usada por los tests de este modulo


def test_extraer_caracteristicas_de_un_video_real_moviendose_a_la_derecha(tmp_path, cv2_disponible):
    from cortador.defensa_ml import extraer_caracteristicas

    ruta = tmp_path / "derecha.mp4"
    _crear_video_con_movimiento_lateral(ruta, lado="derecha")

    caracteristicas = extraer_caracteristicas(str(ruta), inicio=0.0, tiro=2.0)

    assert caracteristicas.duracion == pytest.approx(2.0, abs=0.1)
    assert caracteristicas.fuerza_pico > 0.0
    # El cuadrado termino cerca del borde derecho: el centro ponderado debe
    # quedar mas cerca de 1.0 que de 0.0.
    assert caracteristicas.centro_x > 0.5


def test_extraer_caracteristicas_de_un_video_real_moviendose_a_la_izquierda(tmp_path, cv2_disponible):
    from cortador.defensa_ml import extraer_caracteristicas

    ruta = tmp_path / "izquierda.mp4"
    _crear_video_con_movimiento_lateral(ruta, lado="izquierda")

    caracteristicas = extraer_caracteristicas(str(ruta), inicio=0.0, tiro=2.0)

    assert caracteristicas.centro_x < 0.5


def test_pipeline_completo_extraer_y_clasificar_con_video_real(tmp_path, cv2_disponible):
    """De punta a punta: dos videos sinteticos reales (derecha/izquierda) se
    convierten en caracteristicas, calibran un modelo, y un tercer video
    nuevo se clasifica correctamente -- sin que el modelo vea nunca el
    video, solo los tres numeros extraidos."""
    from cortador.defensa_ml import extraer_caracteristicas

    ruta_adelante = tmp_path / "adelante.mp4"
    ruta_derecha = tmp_path / "derecha.mp4"
    ruta_izquierda = tmp_path / "izquierda.mp4"
    _crear_video_con_movimiento_lateral(ruta_adelante, lado="quieto", segundos=1.0)
    _crear_video_con_movimiento_lateral(ruta_derecha, lado="derecha", segundos=2.0)
    _crear_video_con_movimiento_lateral(ruta_izquierda, lado="izquierda", segundos=2.0)

    dataset = Dataset.vacio()
    dataset.agregar("adelante", extraer_caracteristicas(str(ruta_adelante), 0.0, 1.0))
    dataset.agregar("derecha", extraer_caracteristicas(str(ruta_derecha), 0.0, 2.0))
    dataset.agregar("izquierda", extraer_caracteristicas(str(ruta_izquierda), 0.0, 2.0))
    modelo = ModeloDefensa.calibrar(dataset)

    # Un video NUEVO (no visto al calibrar), tambien moviendose a la
    # derecha: el modelo debe reconocer la categoria sin haber visto este
    # archivo especifico.
    ruta_nueva = tmp_path / "derecha_nueva.mp4"
    _crear_video_con_movimiento_lateral(ruta_nueva, lado="derecha", segundos=2.0)
    caracteristicas_nuevas = extraer_caracteristicas(str(ruta_nueva), 0.0, 2.0)
    categoria, _ = modelo.clasificar(caracteristicas_nuevas)
    assert categoria == "derecha"


def test_actualizar_desde_manifiesto_agrega_al_dataset_acumulado_existente(tmp_path, cv2_disponible):
    """El segundo video marcado debe SUMAR ejemplos al dataset del primero,
    no reemplazarlo -- asi es como el modelo mejora con cada entrega nueva
    en vez de olvidar lo aprendido antes."""
    from cortador.defensa import Manifiesto, Repeticion
    from cortador.defensa_ml import actualizar_desde_manifiesto, Dataset

    ruta_dataset = tmp_path / "dataset.json"
    ruta_modelo = tmp_path / "modelo.json"

    def _manifiesto(categoria: str) -> Manifiesto:
        rep = Repeticion(categoria=categoria, inicio=0.0, tiro=2.0, estado="completa",
                          seleccionada=True)
        return Manifiesto(video="v.mp4", repeticiones=(rep,), seleccionadas=(rep,))

    ruta_v1 = tmp_path / "v1.mp4"
    _crear_video_con_movimiento_lateral(ruta_v1, lado="derecha", segundos=2.0)
    actualizar_desde_manifiesto(
        ruta_v1, _manifiesto("derecha"),
        ruta_dataset=ruta_dataset, ruta_modelo=ruta_modelo,
    )
    assert Dataset.cargar(ruta_dataset).total_ejemplos() == 1

    ruta_v2 = tmp_path / "v2.mp4"
    _crear_video_con_movimiento_lateral(ruta_v2, lado="izquierda", segundos=2.0)
    actualizar_desde_manifiesto(
        ruta_v2, _manifiesto("izquierda"),
        ruta_dataset=ruta_dataset, ruta_modelo=ruta_modelo,
    )
    dataset_final = Dataset.cargar(ruta_dataset)
    assert dataset_final.total_ejemplos() == 2, (
        "el segundo video debio SUMAR un ejemplo, no reemplazar el dataset"
    )
    assert len(dataset_final.ejemplos["derecha"]) == 1
    assert len(dataset_final.ejemplos["izquierda"]) == 1


def test_actualizar_desde_manifiesto_no_calibra_modelo_hasta_tener_las_tres_categorias(tmp_path, cv2_disponible):
    from cortador.defensa import Manifiesto, Repeticion
    from cortador.defensa_ml import actualizar_desde_manifiesto

    rep = Repeticion(categoria="adelante", inicio=0.0, tiro=1.0, estado="completa",
                      seleccionada=True)
    manifiesto = Manifiesto(video="v.mp4", repeticiones=(rep,), seleccionadas=(rep,))
    ruta_video = tmp_path / "v.mp4"
    _crear_video_con_movimiento_lateral(ruta_video, lado="quieto", segundos=1.0)

    _, modelo, _ = actualizar_desde_manifiesto(
        ruta_video, manifiesto,
        ruta_dataset=tmp_path / "dataset.json", ruta_modelo=tmp_path / "modelo.json",
    )
    assert modelo is None
    assert not (tmp_path / "modelo.json").exists()
