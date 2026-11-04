"""Deteccion de candidatos de swing sobre video real.

El caso que de verdad importa aqui es el artefacto de keyframe: en un H.264 la
diferencia entre un keyframe y el fotograma anterior es alta siempre, y si no se
descarta, los candidatos salen clavados en los segundos redondos.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from cortador import eventos, ffmpeg
from cortador.perfil import Perfil

RAIZ = Path(__file__).resolve().parents[1]
VIDEO = RAIZ / "fixtures" / "jornada_sintetica.mp4"
PERFIL = RAIZ / "fixtures" / "perfil_sintetica.json"


def _hay_ffmpeg() -> bool:
    try:
        ffmpeg.ruta_ffmpeg()
        ffmpeg.ruta_ffprobe()
        return True
    except ffmpeg.FfmpegNoEncontrado:
        return False


necesita_video = pytest.mark.skipif(
    not VIDEO.exists() or not PERFIL.exists() or not _hay_ffmpeg(),
    reason="hace falta ffmpeg y el fixture: python tools/make_fixture.py",
)


def test_defaults_de_bateo_reflejan_el_montaje_confirmado():
    assert eventos.ANTES == 3.0
    assert eventos.DESPUES == 2.0


@necesita_video
def test_los_fotogramas_de_keyframe_quedan_fuera_de_la_medida():
    perfil = Perfil.cargar(PERFIL)
    valores, fps = eventos.actividad(str(VIDEO), perfil)

    huecos = np.flatnonzero(np.isnan(valores))
    assert huecos.size > 0, "ningun fotograma quedo marcado como no medible"

    # cada instante de keyframe tiene que caer dentro de un hueco
    for t in ffmpeg.keyframes(str(VIDEO)):
        i = int(round(t * fps))
        if 0 < i <= len(valores):
            assert np.isnan(valores[i - 1]), f"el keyframe de t={t:.2f}s sigue midiendose"


@necesita_video
def test_ningun_candidato_sale_de_una_pareja_contaminada():
    """Las parejas prohibidas son (kf-1, kf) y (kf, kf+1); la de antes es legitima."""
    perfil = Perfil.cargar(PERFIL)
    candidatos = eventos.detectar(str(VIDEO), perfil)
    fps = ffmpeg.info(str(VIDEO)).fps
    prohibidos = set()
    for t in ffmpeg.keyframes(str(VIDEO)):
        i = int(round(t * fps))
        prohibidos.update({i, i + 1})

    for c in candidatos:
        indice = int(round(c.instante * fps))
        assert indice not in prohibidos, (
            f"candidato en t={c.instante:.2f}s (fotograma {indice}) sale de una "
            "pareja tocada por un keyframe"
        )


@necesita_video
def test_los_candidatos_salen_ordenados_y_separados():
    perfil = Perfil.cargar(PERFIL)
    candidatos = eventos.detectar(str(VIDEO), perfil)
    instantes = [c.instante for c in candidatos]
    assert instantes == sorted(instantes)
    for a, b in zip(instantes, instantes[1:]):
        assert b - a >= eventos.SEPARACION - 1e-6


@necesita_video
def test_subir_sigmas_no_agranda_la_lista():
    perfil = Perfil.cargar(PERFIL)
    flojo = eventos.detectar(str(VIDEO), perfil, sigmas=1.5)
    duro = eventos.detectar(str(VIDEO), perfil, sigmas=3.5)
    assert len(duro) <= len(flojo)
