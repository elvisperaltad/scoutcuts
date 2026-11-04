"""Recuperar, del montaje que entrega el scout, que tramos del crudo conservo.

Es la pieza que convierte un par (crudo, montaje) en material etiquetado sin que nadie
marque nada, asi que lo que se prueba es justo lo que puede salir mal: que un plano
quieto parta un tramo en dos, y que un corte de verdad no se pierda.
"""

from __future__ import annotations

import numpy as np
import pytest

import alinear
from alinear import Tramo


def test_juntar_une_los_que_se_tocan():
    unidos = alinear.juntar([Tramo(0.0, 1.0, 1.0), Tramo(1.1, 2.0, 1.0)], holgura=0.2)
    assert len(unidos) == 1
    assert unidos[0].inicio == 0.0 and unidos[0].fin == 2.0


def test_juntar_une_los_que_se_solapan():
    """El mejor encaje puede retroceder un fotograma dentro de un plano quieto."""
    unidos = alinear.juntar([Tramo(0.0, 1.2, 1.0), Tramo(1.1, 2.0, 1.0)], holgura=0.2)
    assert len(unidos) == 1
    assert (unidos[0].inicio, unidos[0].fin) == (0.0, 2.0)


def test_juntar_respeta_un_corte_de_verdad():
    unidos = alinear.juntar([Tramo(0.0, 1.0, 1.0), Tramo(5.0, 6.0, 1.0)], holgura=0.2)
    assert len(unidos) == 2


def test_tramos_parte_donde_el_encaje_salta():
    """Indices 0..9 del crudo y luego 50..59: son dos trozos, no uno."""
    indices = np.array(list(range(10)) + list(range(50, 60)))
    corr = np.ones(len(indices))
    encontrados = alinear.tramos(indices, corr, fps=10.0)
    assert len(encontrados) == 2
    assert encontrados[0].inicio == pytest.approx(0.0)
    assert encontrados[1].inicio == pytest.approx(5.0)


def test_tramos_descarta_lo_que_no_viene_del_crudo():
    """Un fotograma con correlacion baja no salio de ese video."""
    indices = np.arange(10)
    corr = np.full(10, 0.3)
    assert alinear.tramos(indices, corr, fps=10.0) == []


def test_tramos_ignora_los_trozos_de_un_par_de_fotogramas():
    indices = np.array([0, 1] + list(range(50, 60)))
    corr = np.ones(len(indices))
    encontrados = alinear.tramos(indices, corr, fps=10.0)
    assert len(encontrados) == 1


def _escribir(ruta, fotogramas, fps=10.0):
    import cv2
    alto, ancho = fotogramas[0].shape[:2]
    v = cv2.VideoWriter(str(ruta), cv2.VideoWriter_fourcc(*"mp4v"), fps, (ancho, alto))
    for f in fotogramas:
        v.write(f)
    v.release()


def test_alinea_un_montaje_contra_su_crudo(tmp_path):
    """De punta a punta: se recorta un montaje de un crudo y se recuperan sus tramos."""
    rng = np.random.default_rng(7)
    # Cada fotograma distinto de los demas: si no, el encaje seria ambiguo por diseno.
    crudo = [np.repeat(np.repeat(rng.integers(0, 255, (12, 20, 3), dtype=np.uint8), 16, 0),
                       16, 1) for _ in range(60)]
    ruta_crudo = tmp_path / "crudo.mp4"
    ruta_montaje = tmp_path / "montaje.mp4"
    _escribir(ruta_crudo, crudo)
    _escribir(ruta_montaje, crudo[10:20] + crudo[40:50])

    encontrados, duracion, media = alinear.alinear(str(ruta_crudo), str(ruta_montaje))

    assert media > 0.9
    assert duracion == pytest.approx(6.0, abs=0.2)
    assert len(encontrados) == 2
    assert encontrados[0].inicio == pytest.approx(1.0, abs=0.15)
    assert encontrados[1].inicio == pytest.approx(4.0, abs=0.15)


def test_trocear_el_montaje_no_cambia_el_resultado():
    """La memoria se acota recorriendo el montaje por bloques; el encaje ha de ser igual.

    Es toda la garantia del troceado: si el bloque cambiara algun encaje, alinear una
    jornada larga daria tramos distintos que alinear un turno corto.
    """
    rng = np.random.default_rng(3)
    crudo = rng.normal(size=(400, 64)).astype(np.float32)
    crudo /= np.linalg.norm(crudo, axis=1, keepdims=True)
    montaje = crudo[np.array([5, 6, 7, 200, 201, 202, 350, 351])]

    de_una = alinear.encajes(montaje, crudo, bloque=10_000)
    a_trozos = alinear.encajes(montaje, crudo, bloque=3)

    assert np.array_equal(de_una[0], a_trozos[0])
    assert np.allclose(de_una[1], a_trozos[1])
    assert np.array_equal(de_una[0], [5, 6, 7, 200, 201, 202, 350, 351])


def test_el_coste_crece_con_el_crudo_no_con_el_montaje():
    """Acotar el bloque es lo que hace que una jornada larga no reviente la memoria."""
    firmas_mb, bloque_corto = alinear.coste(n_crudo=100_000, n_montaje=50)
    _, bloque_largo = alinear.coste(n_crudo=100_000, n_montaje=500_000)
    assert bloque_largo < firmas_mb          # el bloque deja de crecer
    assert bloque_corto < bloque_largo       # salvo que el montaje sea mas corto que el
