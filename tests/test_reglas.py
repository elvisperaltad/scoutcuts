"""Las cuatro reglas del diseno, sin video de por medio.

Los descriptores son vectores one-hot por pelotero y la distancia inyectada solo
mira quien es: asi se prueba la logica de segmentacion y no el descriptor.
"""

from __future__ import annotations

import numpy as np
import pytest

from cortador.reglas import Ajustes, Segmento, ajustar_a_keyframes, segmentar

DT = 2.0  # muestreo cada 2 s, como el GOP del material real
PELOTEROS = ["P-01", "P-02", "P-03", "P-04", "cruce"]


def desc(etiqueta: str) -> np.ndarray:
    v = np.zeros(len(PELOTEROS), dtype=np.float32)
    v[PELOTEROS.index(etiqueta)] = 1.0
    return v


def dist(a, b) -> float:
    if a is None or b is None or not a.any() or not b.any():
        return 1.0
    return 0.0 if int(np.argmax(a)) == int(np.argmax(b)) else 1.0


def construir(guion: list[tuple[float, float, str]], duracion: float):
    """(tiempos, ocupado, descriptores, keyframes) a partir de tramos ocupados."""
    tiempos = [round(i * DT, 3) for i in range(int(duracion / DT))]
    ocupado, descs = [], []
    for t in tiempos:
        quien = next((e for ini, fin, e in guion if ini <= t < fin), None)
        ocupado.append(quien is not None)
        descs.append(desc(quien) if quien else None)
    return tiempos, ocupado, descs, list(tiempos)


def turnos(guion, duracion=440.0, ajustes=None):
    tiempos, ocupado, descs, keyframes = construir(guion, duracion)
    return segmentar(tiempos, ocupado, descs, keyframes, duracion,
                     ajustes or Ajustes(), dist=dist)


def test_turno_normal_se_detecta_entero():
    resultado = turnos([(20.0, 80.0, "P-01")])
    assert len(resultado) == 1
    # El colchon de 2 s se ajusta ademas al keyframe exterior.
    assert resultado[0].inicio <= 20.0
    assert resultado[0].fin >= 80.0
    assert resultado[0].duracion == pytest.approx(64.0, abs=DT)


def test_sale_a_ajustarse_el_guante_y_vuelve_es_un_solo_turno():
    resultado = turnos([(20.0, 80.0, "P-01"), (98.0, 140.0, "P-01")])  # hueco de 18 s
    assert len(resultado) == 1
    assert "fusionado" in resultado[0].notas[0]
    assert resultado[0].fin >= 140.0


def test_hueco_largo_del_mismo_pelotero_son_dos_turnos():
    resultado = turnos([(20.0, 80.0, "P-01"), (120.0, 180.0, "P-01")])  # hueco de 40 s
    assert len(resultado) == 2


def test_dos_peloteros_con_hueco_corto_no_se_fusionan():
    resultado = turnos([(20.0, 80.0, "P-01"), (98.0, 160.0, "P-02")])  # hueco de 18 s
    assert len(resultado) == 2


def test_relevo_sin_hueco_se_parte_por_apariencia():
    resultado = turnos([(20.0, 80.0, "P-03"), (80.0, 140.0, "P-04")])
    assert len(resultado) == 2
    assert resultado[0].fin == pytest.approx(resultado[1].inicio, abs=6.0)


def test_entrenador_cruzando_no_es_un_turno():
    resultado = turnos([(20.0, 80.0, "P-01"), (100.0, 108.0, "cruce")])  # cruce de 8 s
    assert len(resultado) == 1


def test_los_bordes_se_ajustan_siempre_hacia_fuera():
    keyframes = [0.0, 2.0, 4.0, 6.0, 8.0, 10.0]
    segmento = Segmento(inicio=3.5, fin=7.2)
    ajustado = ajustar_a_keyframes([segmento], keyframes, duracion=10.0)[0]
    assert ajustado.inicio == 2.0   # keyframe anterior
    assert ajustado.fin == 8.0      # keyframe posterior
    assert ajustado.inicio <= segmento.inicio and ajustado.fin >= segmento.fin


def test_el_colchon_no_se_sale_del_video():
    resultado = turnos([(0.0, 60.0, "P-01")], duracion=62.0)
    assert resultado[0].inicio >= 0.0
    assert resultado[0].fin <= 62.0


def test_sin_nadie_en_el_cajon_no_hay_turnos():
    assert turnos([], duracion=60.0) == []
