"""La puntuacion del motor contra lo que el scout entrego a mano.

Se mide en segundos, no en swings: al scout le molesta medio segundo de tiempo muerto
tanto como le falta medio segundo de swing, y contar por swing esconde las dos cosas.
Lo que se prueba aqui es que precision y cobertura no se confundan -- es el error
clasico, y con el un motor que propone el turno entero pareceria perfecto.
"""

from __future__ import annotations

import json

import pytest

from evaluar import comparar, fundir_simple, por_tramo, _cargar_propuesta


def test_acierto_perfecto():
    m = comparar([(0.0, 2.0)], [(0.0, 2.0)])
    assert m["precision"] == 1.0 and m["cobertura"] == 1.0 and m["f1"] == 1.0


def test_sin_solape():
    m = comparar([(0.0, 2.0)], [(5.0, 7.0)])
    assert m["precision"] == 0.0 and m["cobertura"] == 0.0 and m["f1"] == 0.0


def test_proponer_de_mas_hunde_la_precision_pero_no_la_cobertura():
    """Un motor que devuelve el turno entero: lo recupera todo y no sirve de nada."""
    m = comparar([(0.0, 10.0)], [(2.0, 4.0)])
    assert m["cobertura"] == 1.0
    assert m["precision"] == pytest.approx(0.2)
    assert m["sobran"] == pytest.approx(8.0)


def test_proponer_de_menos_hunde_la_cobertura_pero_no_la_precision():
    m = comparar([(2.0, 3.0)], [(2.0, 6.0)])
    assert m["precision"] == 1.0
    assert m["cobertura"] == pytest.approx(0.25)
    assert m["faltan"] == pytest.approx(3.0)


def test_fundir_no_cuenta_dos_veces_el_mismo_segundo():
    """Dos candidatos vecinos solapan sus tramos; sin fundir, la precision saldria mal."""
    assert fundir_simple([(0.0, 2.0), (1.0, 3.0)]) == [(0.0, 3.0)]
    m = comparar(fundir_simple([(0.0, 2.0), (1.0, 3.0)]), [(0.0, 3.0)])
    assert m["precision"] == 1.0


def test_fundir_deja_en_paz_los_separados():
    assert fundir_simple([(4.0, 5.0), (0.0, 1.0)]) == [(0.0, 1.0), (4.0, 5.0)]


def test_por_tramo_senala_el_que_se_pierde_entero():
    cubierto = por_tramo([(0.0, 1.0)], [(0.0, 1.0), (9.0, 10.0)])
    assert cubierto[0][1] == 1.0
    assert cubierto[1][1] == 0.0


def test_carga_un_cuaderno_y_se_queda_solo_con_lo_valido(tmp_path):
    ruta = tmp_path / "x.marcas.json"
    ruta.write_text(json.dumps({"video": "v.mp4", "marcas": [
        {"inicio": 0.0, "fin": 2.0, "instante": 1.0, "estado": "valido", "fuerza": 1.0},
        {"inicio": 5.0, "fin": 7.0, "instante": 6.0, "estado": "invalido", "fuerza": 1.0},
        {"inicio": 9.0, "fin": 11.0, "instante": 10.0, "estado": "pendiente", "fuerza": 1.0},
    ]}), encoding="utf-8")
    assert _cargar_propuesta(str(ruta)) == [(0.0, 2.0)]
