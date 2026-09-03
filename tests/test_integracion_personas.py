"""Pipeline completo sobre la jornada con personas reales.

Es la unica prueba que dice algo sobre los detectores del diseno: sobre rectangulos de
colores YOLO no detecta a nadie, y con razon.

Se salta si falta el fixture o las dependencias pesadas:
    python tools/make_fixture.py --personas
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cortador import ffmpeg
from cortador.canal import analizar
from cortador.perfil import Perfil

RAIZ = Path(__file__).resolve().parents[1]
VIDEO = RAIZ / "fixtures" / "jornada_personas.mp4"
PERFIL = RAIZ / "fixtures" / "perfil_personas.json"
ESPERADO = RAIZ / "fixtures" / "jornada_personas.esperado.json"

TOLERANCIA = 6.0  # s: aqui el borde lo pone la ventana de apariencia, no solo el keyframe


def _hay_dependencias() -> bool:
    try:
        import torch  # noqa: F401
        import ultralytics  # noqa: F401

        ffmpeg.ruta_ffmpeg()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not (_hay_dependencias() and VIDEO.exists() and ESPERADO.exists()),
    reason="hacen falta torch, ultralytics y el fixture (make_fixture.py --personas)",
)

COMBINACIONES = [("color", "cnn"), ("yolo", "cnn")]


@pytest.fixture(scope="module")
def esperado():
    return json.loads(ESPERADO.read_text(encoding="utf-8"))["turnos"]


@pytest.fixture(scope="module")
def resultados():
    perfil = Perfil.cargar(PERFIL)
    return {
        (det, ident): analizar(str(VIDEO), perfil, detector=det, modo_identidad=ident)
        for det, ident in COMBINACIONES
    }


@pytest.mark.parametrize("combinacion", COMBINACIONES)
def test_encuentra_los_cinco_turnos(resultados, esperado, combinacion):
    assert len(resultados[combinacion].segmentos) == len(esperado)


@pytest.mark.parametrize("combinacion", COMBINACIONES)
def test_cada_turno_contiene_el_metraje_real(resultados, esperado, combinacion):
    for detectado, real in zip(resultados[combinacion].segmentos, esperado):
        assert detectado.inicio <= real["inicio"] + TOLERANCIA
        assert detectado.fin >= real["fin"] - TOLERANCIA


@pytest.mark.parametrize("combinacion", COMBINACIONES)
def test_el_relevo_sin_hueco_da_dos_turnos_seguidos(resultados, combinacion):
    """P-03 y P-04 se relevan en el segundo 275 sin que el cajon quede vacio."""
    segmentos = resultados[combinacion].segmentos
    relevo = [s for s in segmentos if 260 <= s.inicio <= 290]
    assert len(relevo) == 1, "el segundo turno del relevo tiene que empezar donde acaba el otro"


def test_el_histograma_de_color_no_separa_personas_parecidas():
    """Por que existe `identidad_cnn`, medido y no supuesto.

    Con personas reales, dos peloteros distintos quedan por debajo del umbral de
    cambio del histograma, asi que el motor los fusionaria en un solo turno.
    """
    import sys

    sys.path.insert(0, str(RAIZ / "tools"))
    from make_fixture import sprites_de_personas

    from cortador import identidad

    sprites = sprites_de_personas()
    def desc(etiqueta):
        img = sprites[etiqueta]
        alto, ancho = img.shape[:2]
        return identidad.descriptor(img, caja=(0, 0, ancho, alto))

    distancia = identidad.distancia(desc("P-01"), desc("P-02"))
    assert distancia < identidad.UMBRAL_CAMBIO
