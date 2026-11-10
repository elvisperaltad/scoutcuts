"""Pruebas de `cortador.servidor.entrenamiento`: zona aislada donde el QA
sube videos de practica, los marca, y recibe feedback del modelo mientras
lo entrena -- separada por completo de la PWA de produccion real, y
compartida por las cuatro disciplinas (defensa, bateo, pitcheo, catcher).
"""

from __future__ import annotations

import io
import json

import pytest

from videos_sinteticos import crear_video_con_movimiento_lateral as _crear_video_con_movimiento_lateral
from videos_sinteticos import cv2_disponible  # noqa: F401 - fixture usada por los tests de este modulo


def _zona(tmp_path):
    from cortador.servidor.entrenamiento import ZonaEntrenamiento

    return ZonaEntrenamiento(tmp_path / "zona_qa")


def _subir_video_real(zona, tmp_path, disciplina="defensa", lado="derecha", nombre="practica.mp4"):
    ruta = tmp_path / nombre
    _crear_video_con_movimiento_lateral(ruta, lado=lado, segundos=2.0)
    with ruta.open("rb") as flujo:
        return zona.subir(disciplina, nombre, flujo), ruta


def _manifiesto_con_una_repeticion(categoria, inicio=0.0, tiro=2.0):
    return [{
        "categoria": categoria, "inicio": inicio, "tiro": tiro,
        "estado": "completa", "seleccionada": True,
    }]


def test_subir_guarda_el_video_de_practica_aislado(tmp_path, cv2_disponible):
    zona = _zona(tmp_path)
    video, _ = _subir_video_real(zona, tmp_path)

    recuperado = zona.video(video.id)
    assert recuperado.nombre == "practica.mp4"
    assert recuperado.disciplina == "defensa"
    assert zona._ruta_video(recuperado).exists()
    # Aislado: nunca comparte carpeta con la raiz de produccion real.
    assert "zona_qa" in str(zona.raiz)


def test_subir_rechaza_disciplina_desconocida(tmp_path):
    from cortador.servidor.entrenamiento import DisciplinaDesconocida

    zona = _zona(tmp_path)
    with pytest.raises(DisciplinaDesconocida):
        zona.subir("vp_live", "documento.mp4", io.BytesIO(b"x"))


def test_subir_rechaza_formato_no_soportado(tmp_path):
    from cortador.servidor.entrenamiento import ArchivoDePracticaNoAceptado

    zona = _zona(tmp_path)
    with pytest.raises(ArchivoDePracticaNoAceptado):
        zona.subir("defensa", "documento.txt", io.BytesIO(b"no es un video"))


def test_subir_rechaza_video_demasiado_grande(tmp_path):
    from cortador.servidor.entrenamiento import ArchivoDePracticaNoAceptado

    zona = _zona(tmp_path)
    zona.limite_bytes = 10
    with pytest.raises(ArchivoDePracticaNoAceptado):
        zona.subir("defensa", "grande.mp4", io.BytesIO(b"x" * 1000))


def test_subir_rechaza_cuando_la_zona_llego_a_su_presupuesto(tmp_path):
    """La zona es publica: sin este techo, una sola IP podria llenar el
    disco del VPS con video de practica antes de que corra la limpieza."""
    from cortador.servidor.entrenamiento import ZonaDePracticaLlena, ZonaEntrenamiento

    zona = ZonaEntrenamiento(tmp_path / "zona_qa", limite_total_bytes=200)
    zona.subir("defensa", "primero.mp4", io.BytesIO(b"x" * 300))
    assert zona.bytes_pendientes() >= 200

    with pytest.raises(ZonaDePracticaLlena):
        zona.subir("defensa", "segundo.mp4", io.BytesIO(b"x" * 10))


def test_el_presupuesto_se_libera_al_borrarse_el_video(tmp_path, cv2_disponible):
    """Entrenar borra el video, asi que el presupuesto vuelve a estar libre:
    el techo no puede dejar la zona inservible para siempre."""
    from cortador.servidor.entrenamiento import ZonaEntrenamiento

    zona = ZonaEntrenamiento(tmp_path / "zona_qa", limite_total_bytes=10 * 1024 * 1024)
    video, _ = _subir_video_real(zona, tmp_path, lado="derecha")
    assert zona.bytes_pendientes() > 0

    zona.entrenar_con_manifiesto(
        video.id, _manifiesto_con_una_repeticion("derecha"), "practica.mp4"
    )

    assert zona.bytes_pendientes() == 0
    assert zona.hay_espacio() is True


def test_entrenar_con_manifiesto_borra_el_video_tras_extraer(tmp_path, cv2_disponible):
    """La prueba mas importante de privacidad: tras entrenar, el video de
    practica ya no debe existir en disco -- ni el archivo ni su carpeta."""
    zona = _zona(tmp_path)
    video, ruta_original = _subir_video_real(zona, tmp_path, lado="derecha")
    carpeta = zona._carpeta(video.id)
    assert carpeta.exists()

    resultado = zona.entrenar_con_manifiesto(
        video.id, _manifiesto_con_una_repeticion("derecha"), "practica.mp4"
    )

    assert not carpeta.exists(), "el video de practica debio borrarse tras entrenar"
    assert ruta_original.exists(), "el ORIGINAL subido por el test sigue existiendo (es otro archivo)"
    assert resultado.ejemplos_agregados == 1
    assert resultado.total_ejemplos_dataset == 1


def test_entrenar_rechaza_categoria_de_otra_disciplina(tmp_path, cv2_disponible):
    """Un video subido como 'bateo' nunca debe poder entrenarse con una
    categoria de 'defensa' (o viceversa): la disciplina la fija la subida,
    no el manifiesto."""
    zona = _zona(tmp_path)
    video, _ = _subir_video_real(zona, tmp_path, disciplina="bateo", nombre="swing.mp4")

    with pytest.raises(ValueError):
        zona.entrenar_con_manifiesto(
            video.id, _manifiesto_con_una_repeticion("derecha"), "swing.mp4"
        )
    # Al fallar la validacion, el video de practica NO debe haberse borrado.
    assert zona._carpeta(video.id).exists()


def test_disciplinas_nunca_comparten_dataset(tmp_path, cv2_disponible):
    """Entrenar bateo no debe tocar el dataset de defensa, ni al revés."""
    zona = _zona(tmp_path)
    video_bateo, _ = _subir_video_real(zona, tmp_path, disciplina="bateo", nombre="swing.mp4")
    zona.entrenar_con_manifiesto(
        video_bateo.id, _manifiesto_con_una_repeticion("valido"), "swing.mp4"
    )

    estado_defensa = zona.estado_modelo("defensa")
    estado_bateo = zona.estado_modelo("bateo")
    assert estado_defensa["total_ejemplos"] == 0
    assert estado_bateo["total_ejemplos"] == 1
    assert estado_bateo["ejemplos_por_categoria"]["valido"] == 1


def test_entrenar_con_manifiesto_de_otro_video_falla_sin_tocar_nada(tmp_path, cv2_disponible):
    zona = _zona(tmp_path)
    video, _ = _subir_video_real(zona, tmp_path, lado="derecha")

    with pytest.raises(ValueError):
        zona.entrenar_con_manifiesto(
            video.id, _manifiesto_con_una_repeticion("derecha"), "otro.mp4"
        )

    # Al fallar la validacion, el video de practica NO debe haberse borrado.
    assert zona._carpeta(video.id).exists()


def test_entrenar_dos_veces_el_mismo_video_la_segunda_falla(tmp_path, cv2_disponible):
    """Tras entrenar y borrar, un segundo intento sobre el mismo id debe
    fallar con un mensaje claro, nunca reventar ni reentrenar con datos
    fantasma."""
    from cortador.servidor.entrenamiento import VideoDePracticaNoEncontrado

    zona = _zona(tmp_path)
    video, _ = _subir_video_real(zona, tmp_path, lado="derecha")
    zona.entrenar_con_manifiesto(
        video.id, _manifiesto_con_una_repeticion("derecha"), "practica.mp4"
    )

    with pytest.raises(VideoDePracticaNoEncontrado):
        zona.entrenar_con_manifiesto(
            video.id, _manifiesto_con_una_repeticion("derecha"), "practica.mp4"
        )


def test_feedback_coincide_cuando_el_modelo_ya_tiene_las_tres_categorias(tmp_path, cv2_disponible):
    """Tras acumular las 3 categorias, el feedback de un cuarto ejemplo
    claro (derecha) debe decir que coincide con confianza no nula."""
    zona = _zona(tmp_path)

    for lado, categoria in (("derecha", "derecha"), ("izquierda", "izquierda")):
        video, _ = _subir_video_real(zona, tmp_path, lado=lado, nombre=f"{categoria}.mp4")
        zona.entrenar_con_manifiesto(
            video.id, _manifiesto_con_una_repeticion(categoria), f"{categoria}.mp4",
        )
    # "adelante" con las mismas caracteristicas base (reusa el video de
    # movimiento lateral como estandin, solo para tener las 3 categorias
    # cubiertas y poder calibrar el modelo).
    video_a, _ = _subir_video_real(zona, tmp_path, lado="derecha", nombre="adelante.mp4")
    zona.entrenar_con_manifiesto(
        video_a.id, _manifiesto_con_una_repeticion("adelante"), "adelante.mp4"
    )

    video_final, _ = _subir_video_real(zona, tmp_path, lado="derecha", nombre="final.mp4")
    resultado = zona.entrenar_con_manifiesto(
        video_final.id, _manifiesto_con_una_repeticion("derecha"), "final.mp4"
    )

    assert resultado.modelo_calibrado is True
    assert resultado.categorias_faltantes == []
    assert len(resultado.evaluacion) == 1
    fila = resultado.evaluacion[0]
    assert fila["categoria_marcada"] == "derecha"
    assert fila["categoria_predicha"] is not None
    assert fila["confianza"] is not None


def test_limpiar_vencidos_borra_videos_de_practica_nunca_marcados(tmp_path, cv2_disponible):
    zona = _zona(tmp_path)
    video, _ = _subir_video_real(zona, tmp_path, lado="derecha")
    carpeta = zona._carpeta(video.id)
    assert carpeta.exists()

    from datetime import datetime, timedelta, timezone

    # Simula que el video quedo huerfano hace mas de 24h: lo que decide la
    # limpieza es el campo 'creado' del estado persistido, no el mtime del
    # archivo en disco.
    viejo = datetime.now(timezone.utc) - timedelta(hours=48)
    datos = json.loads(zona._ruta_estado(video.id).read_text(encoding="utf-8"))
    datos["creado"] = viejo.isoformat(timespec="seconds")
    zona._ruta_estado(video.id).write_text(json.dumps(datos), encoding="utf-8")

    borrados = zona.limpiar_vencidos(max_edad_horas=24.0)

    assert video.id in borrados
    assert not carpeta.exists()


def test_estado_modelo_no_expone_rutas_ni_numeros_crudos(tmp_path, cv2_disponible):
    zona = _zona(tmp_path)
    video, _ = _subir_video_real(zona, tmp_path, lado="derecha")
    zona.entrenar_con_manifiesto(
        video.id, _manifiesto_con_una_repeticion("derecha"), "practica.mp4"
    )

    resumen = zona.estado_modelo("defensa")

    assert resumen["total_ejemplos"] == 1
    assert resumen["ejemplos_por_categoria"]["derecha"] == 1
    assert resumen["modelo_calibrado"] is False  # aun faltan 2 categorias
    assert "ruta" not in json.dumps(resumen)


def test_estado_todas_las_disciplinas_incluye_las_cuatro(tmp_path):
    zona = _zona(tmp_path)
    estado = zona.estado_todas_las_disciplinas()
    assert set(estado) == {"defensa", "bateo", "pitcheo", "catcher"}
    for resumen in estado.values():
        assert resumen["total_ejemplos"] == 0
        assert resumen["modelo_calibrado"] is False
