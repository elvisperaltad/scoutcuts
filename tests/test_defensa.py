"""Manifiesto humano y exportación de las seis repeticiones defensivas."""

from __future__ import annotations

import json

import pytest

from cortador import cli
from cortador.defensa import cargar, tramos_exportables


def _repeticion(categoria, inicio, tiro, estado="completa", **extras):
    return {
        "categoria": categoria,
        "inicio": inicio,
        "tiro": tiro,
        "estado": estado,
        **extras,
    }


def _datos(video="defensa.mp4"):
    return {
        "version": 1,
        "video": video,
        "repeticiones": [
            _repeticion("derecha", 20.0, 22.0),
            _repeticion("adelante", 1.0, 3.0),
            _repeticion("izquierda", 50.0, 52.0, estado="incompleta"),
            _repeticion("adelante", 10.0, 12.0),
            _repeticion("izquierda", 40.0, 42.0),
            _repeticion("derecha", 30.0, 32.0),
            _repeticion("izquierda", 50.0, 52.0),
        ],
    }


def _guardar(tmp_path, datos):
    ruta = tmp_path / "defensa.json"
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    return ruta


def test_carga_seis_completas_equilibradas_y_excluye_incompletas(tmp_path):
    manifiesto = cargar(_guardar(tmp_path, _datos()), "defensa.mp4")

    elegidas = manifiesto.seleccionadas
    assert [r.inicio for r in elegidas] == [1.0, 10.0, 20.0, 30.0, 40.0, 50.0]
    assert {categoria: sum(r.categoria == categoria for r in elegidas)
            for categoria in ("adelante", "derecha", "izquierda")} == {
                "adelante": 2, "derecha": 2, "izquierda": 2,
            }


def test_tramos_aplican_margenes_y_limitan_el_inicio_a_cero(tmp_path):
    manifiesto = cargar(_guardar(tmp_path, _datos()), "defensa.mp4")
    assert tramos_exportables(manifiesto) == [
        (0.0, 3.3), (8.0, 12.3), (18.0, 22.3),
        (28.0, 32.3), (38.0, 42.3), (48.0, 52.3),
    ]
    assert tramos_exportables(manifiesto, antes_extra=0.5, despues_tiro=0.1)[0] == (0.5, 3.1)


def test_exceso_de_completas_exige_seleccion_explicita(tmp_path):
    datos = _datos()
    datos["repeticiones"].append(_repeticion("adelante", 60.0, 62.0))
    with pytest.raises(ValueError, match="seleccion"):
        cargar(_guardar(tmp_path, datos), "defensa.mp4")

    for repeticion in datos["repeticiones"]:
        if repeticion["categoria"] == "adelante":
            repeticion["seleccionada"] = repeticion["inicio"] in (10.0, 60.0)
    manifiesto = cargar(_guardar(tmp_path, datos), "defensa.mp4")
    assert [r.inicio for r in manifiesto.seleccionadas if r.categoria == "adelante"] == [10.0, 60.0]


@pytest.mark.parametrize("cambio,mensaje", [
    (("version", 2), "version"),
    (("video", "otro.mp4"), "video"),
])
def test_rechaza_version_o_video_incorrectos(tmp_path, cambio, mensaje):
    datos = _datos()
    datos[cambio[0]] = cambio[1]
    with pytest.raises(ValueError, match=mensaje):
        cargar(_guardar(tmp_path, datos), "defensa.mp4")


@pytest.mark.parametrize("repeticion", [
    _repeticion("centro", 1.0, 2.0),
    _repeticion("adelante", -1.0, 2.0),
    _repeticion("adelante", 3.0, 2.0),
    _repeticion("adelante", 1.0, 2.0, estado="dudosa"),
])
def test_rechaza_categoria_tiempos_y_estado_invalidos(tmp_path, repeticion):
    datos = _datos()
    datos["repeticiones"][0] = repeticion
    with pytest.raises(ValueError):
        cargar(_guardar(tmp_path, datos), "defensa.mp4")


def test_cli_defensa_valida_y_llama_al_exportador(tmp_path, monkeypatch):
    video = tmp_path / "defensa.mp4"
    video.write_bytes(b"video")
    marcas = _guardar(tmp_path, _datos(video.name))
    salida = tmp_path / "seleccion.mp4"
    llamada = {}

    def exportar(video_arg, tramos_arg, salida_arg):
        llamada.update(video=video_arg, tramos=tramos_arg, salida=salida_arg)
        return salida_arg

    monkeypatch.setattr(cli.compactar_mod, "exportar", exportar)
    codigo = cli.main([
        "defensa", str(video), "--marcas", str(marcas), "--salida", str(salida),
        "--antes-extra", "1.5", "--despues-tiro", "0.2",
    ])

    assert codigo == 0
    assert llamada == {
        "video": str(video),
        "tramos": [(0.0, 3.2), (8.5, 12.2), (18.5, 22.2),
                   (28.5, 32.2), (38.5, 42.2), (48.5, 52.2)],
        "salida": str(salida),
    }


def test_cli_defensa_devuelve_uno_ante_manifiesto_invalido(tmp_path, capsys):
    video = tmp_path / "defensa.mp4"
    video.write_bytes(b"video")
    datos = _datos(video.name)
    datos["version"] = 99
    codigo = cli.main([
        "defensa", str(video), "--marcas", str(_guardar(tmp_path, datos)),
        "--salida", str(tmp_path / "salida.mp4"),
    ])
    assert codigo == 1
    assert "error:" in capsys.readouterr().err


def test_cli_defensa_actualiza_el_modelo_con_un_video_real(tmp_path, monkeypatch, capsys):
    """El video en este test SI es real (no bytes inventados): asi se
    comprueba la ruta completa, no solo que el codigo no explote con un
    mock."""
    import cv2
    import numpy as np

    video = tmp_path / "defensa.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    escritor = cv2.VideoWriter(str(video), fourcc, 20.0, (320, 240))
    for i in range(120):
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        frame[90:150, (i % 280):(i % 280) + 40] = 255
        escritor.write(frame)
    escritor.release()

    marcas = _guardar(tmp_path, _datos(video.name))
    salida = tmp_path / "seleccion.mp4"

    def exportar(video_arg, tramos_arg, salida_arg):
        return salida_arg

    monkeypatch.setattr(cli.compactar_mod, "exportar", exportar)
    ruta_dataset = tmp_path / "dataset.json"
    ruta_modelo = tmp_path / "modelo.json"
    monkeypatch.setattr(cli.defensa_ml_mod, "ruta_dataset_por_defecto", lambda: ruta_dataset)
    monkeypatch.setattr(cli.defensa_ml_mod, "ruta_modelo_por_defecto", lambda: ruta_modelo)

    codigo = cli.main([
        "defensa", str(video), "--marcas", str(marcas), "--salida", str(salida),
    ])

    assert codigo == 0
    assert ruta_dataset.exists(), "el dataset de defensa debio actualizarse"
    salida_impresa = capsys.readouterr().out
    assert "Modelo de defensa:" in salida_impresa


def test_cli_defensa_sin_entrenar_no_toca_el_modelo(tmp_path, monkeypatch):
    video = tmp_path / "defensa.mp4"
    video.write_bytes(b"video")
    marcas = _guardar(tmp_path, _datos(video.name))
    salida = tmp_path / "seleccion.mp4"

    def exportar(video_arg, tramos_arg, salida_arg):
        return salida_arg

    monkeypatch.setattr(cli.compactar_mod, "exportar", exportar)
    llamado = {"veces": 0}

    def falla_si_se_llama(*args, **kwargs):
        llamado["veces"] += 1
        raise AssertionError("no deberia llamarse con --sin-entrenar")

    monkeypatch.setattr(cli.defensa_ml_mod, "actualizar_desde_manifiesto", falla_si_se_llama)

    codigo = cli.main([
        "defensa", str(video), "--marcas", str(marcas), "--salida", str(salida),
        "--sin-entrenar",
    ])

    assert codigo == 0
    assert llamado["veces"] == 0
