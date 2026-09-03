"""Pipeline completo sobre la jornada sintetica, comparado con su verdad de referencia.

Se salta si no hay ffmpeg o si no se ha generado el fixture:
    python tools/make_fixture.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cortador import ffmpeg
from cortador.canal import analizar, cortar
from cortador.perfil import Perfil

RAIZ = Path(__file__).resolve().parents[1]
VIDEO = RAIZ / "fixtures" / "jornada_sintetica.mp4"
PERFIL = RAIZ / "fixtures" / "perfil_sintetica.json"
ESPERADO = RAIZ / "fixtures" / "jornada_sintetica.esperado.json"

TOLERANCIA = 4.0  # s: el borde se ajusta al keyframe exterior y lleva colchon


def _hay_ffmpeg() -> bool:
    try:
        ffmpeg.ruta_ffmpeg()
        ffmpeg.ruta_ffprobe()
        return True
    except ffmpeg.FfmpegNoEncontrado:
        return False


pytestmark = pytest.mark.skipif(
    not (_hay_ffmpeg() and VIDEO.exists() and ESPERADO.exists()),
    reason="hace falta ffmpeg y el fixture (python tools/make_fixture.py)",
)


@pytest.fixture(scope="module")
def resultado():
    return analizar(str(VIDEO), Perfil.cargar(PERFIL))


@pytest.fixture(scope="module")
def esperado():
    return json.loads(ESPERADO.read_text(encoding="utf-8"))["turnos"]


def test_encuentra_todos_los_turnos_y_ninguno_de_mas(resultado, esperado):
    assert len(resultado.segmentos) == len(esperado)


def test_cada_turno_contiene_el_metraje_real(resultado, esperado):
    """Ajustar hacia fuera: el clip nunca se come el turno."""
    for detectado, real in zip(resultado.segmentos, esperado):
        assert detectado.inicio <= real["inicio"] + TOLERANCIA
        assert detectado.fin >= real["fin"] - TOLERANCIA


def test_el_pelotero_que_sale_y_vuelve_es_un_unico_clip(resultado):
    fusionados = [s for s in resultado.segmentos if any("fusionado" in n for n in s.notas)]
    assert len(fusionados) == 1
    assert fusionados[0].duracion > 100  # los dos tramos de P-02, no uno solo


def test_el_cruce_de_ocho_segundos_no_genera_clip(resultado):
    # El cruce ocurre entre 350 y 358 s: ningun turno debe empezar ahi.
    assert not any(348 <= s.inicio <= 360 for s in resultado.segmentos)


def test_los_clips_exportados_son_validos_y_sin_audio(tmp_path):
    resultado = cortar(str(VIDEO), Perfil.cargar(PERFIL), tmp_path)
    original = ffmpeg.info(str(VIDEO))
    assert len(resultado.clips) == len(resultado.segmentos)
    for clip in resultado.clips:
        assert clip.stat().st_size > 0
        info = ffmpeg.info(str(clip))
        assert info.codec == original.codec        # copia de flujo, sin recodificar
        assert (info.ancho, info.alto) == (original.ancho, original.alto)
        assert info.duracion > 0
        pistas = ffmpeg.ejecutar([
            ffmpeg.ruta_ffprobe(), "-v", "error", "-show_entries", "stream=codec_type",
            "-of", "csv=p=0", str(clip),
        ])
        assert "audio" not in pistas
