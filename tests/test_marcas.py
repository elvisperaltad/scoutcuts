"""Marcas y compactado: la parte que no necesita ni video ni ventana."""

from __future__ import annotations

import pytest

from cortador.compactar import _cadena_filtros, duracion_total
from cortador.eventos import Candidato
from cortador.marcas import INVALIDO, SIN_DECIDIR, VALIDO, Cuaderno, Marca, fundir


def _cuaderno(*estados: str) -> Cuaderno:
    marcas = [
        Marca(inicio=float(i * 10), fin=float(i * 10 + 2), instante=float(i * 10 + 1), estado=e)
        for i, e in enumerate(estados)
    ]
    return Cuaderno(video="x.mp4", marcas=marcas)


def test_candidato_tramo_no_baja_de_cero():
    c = Candidato(instante=0.5, fuerza=9.0)
    assert c.tramo(1.2, 1.2) == (0.0, 1.7)


def test_marca_rechaza_tramo_vacio():
    with pytest.raises(ValueError):
        Marca(inicio=5.0, fin=5.0, instante=5.0)


def test_marca_rechaza_estado_desconocido():
    with pytest.raises(ValueError):
        Marca(inicio=0.0, fin=1.0, instante=0.5, estado="quiza")


def test_cuaderno_desde_candidatos_deja_todo_pendiente():
    candidatos = [Candidato(instante=10.0, fuerza=8.0), Candidato(instante=20.0, fuerza=9.0)]
    c = Cuaderno.desde_candidatos("x.mp4", candidatos, antes=1.0, despues=1.0)
    assert [m.estado for m in c.marcas] == [SIN_DECIDIR, SIN_DECIDIR]
    assert c.marcas[0].inicio == 9.0 and c.marcas[0].fin == 11.0
    assert len(c.pendientes) == 2


def test_resumen_cuenta_los_tres_estados():
    c = _cuaderno(VALIDO, VALIDO, INVALIDO, SIN_DECIDIR)
    assert "4 candidatos: 2 validos, 1 descartados, 1 sin decidir" == c.resumen()


def test_fundir_solo_devuelve_los_validos():
    c = _cuaderno(VALIDO, INVALIDO, VALIDO)
    assert fundir(c) == [(0.0, 2.0), (20.0, 22.0)]


def test_fundir_une_los_que_casi_se_tocan():
    c = Cuaderno(video="x.mp4", marcas=[
        Marca(inicio=10.0, fin=12.0, instante=11.0, estado=VALIDO),
        Marca(inicio=12.3, fin=14.0, instante=13.0, estado=VALIDO),
        Marca(inicio=20.0, fin=22.0, instante=21.0, estado=VALIDO),
    ])
    assert fundir(c, separacion=0.5) == [(10.0, 14.0), (20.0, 22.0)]
    assert fundir(c, separacion=0.0) == [(10.0, 12.0), (12.3, 14.0), (20.0, 22.0)]


def test_fundir_absorbe_el_tramo_contenido_en_otro():
    c = Cuaderno(video="x.mp4", marcas=[
        Marca(inicio=10.0, fin=20.0, instante=15.0, estado=VALIDO),
        Marca(inicio=12.0, fin=14.0, instante=13.0, estado=VALIDO),
    ])
    assert fundir(c) == [(10.0, 20.0)]


def test_fundir_sin_validos_no_devuelve_nada():
    assert fundir(_cuaderno(INVALIDO, SIN_DECIDIR)) == []


def test_cuaderno_va_y_vuelve_del_disco(tmp_path):
    c = _cuaderno(VALIDO, INVALIDO)
    c.marcas[0].nota = "buen contacto"
    ruta = tmp_path / "sub" / "marcas.json"
    c.guardar(ruta)
    vuelto = Cuaderno.cargar(ruta)
    assert vuelto.video == c.video
    assert [m.estado for m in vuelto.marcas] == [VALIDO, INVALIDO]
    assert vuelto.marcas[0].nota == "buen contacto"
    assert vuelto.creado  # se sella al guardar


def test_cuaderno_guardar_preserva_el_anterior_si_falla(tmp_path, monkeypatch):
    from cortador import marcas

    ruta = tmp_path / "marcas.json"
    _cuaderno(VALIDO).guardar(ruta)
    original = ruta.read_bytes()

    def reemplazo_roto(origen, destino):
        raise OSError("disco lleno")

    monkeypatch.setattr(marcas.os, "replace", reemplazo_roto)
    with pytest.raises(OSError):
        _cuaderno(INVALIDO, INVALIDO).guardar(ruta)

    assert ruta.read_bytes() == original
    assert list(tmp_path.iterdir()) == [ruta]


def test_duracion_total_suma_los_tramos():
    assert duracion_total([(0.0, 2.5), (10.0, 12.0)]) == pytest.approx(4.5)


def test_cadena_de_filtros_recorta_y_concatena():
    filtros = _cadena_filtros([(1.0, 3.0), (10.0, 12.5)])
    assert "trim=start=1.000:end=3.000" in filtros
    assert "trim=start=10.000:end=12.500" in filtros
    assert filtros.endswith("[v0][v1]concat=n=2:v=1:a=0[salida]")


def test_compactar_sin_tramos_avisa():
    from cortador import compactar

    with pytest.raises(ValueError):
        compactar.exportar("x.mp4", [], "salida.mp4")


def test_la_vista_se_pinta_sin_abrir_ventana():
    """Las piezas de dibujo de la pantalla de marcado son puras y se pueden probar."""
    import numpy as np

    from cortador.revision import _escalar, _pintar

    fotograma = np.zeros((576, 1024, 3), dtype=np.uint8)
    c = _cuaderno(VALIDO, SIN_DECIDIR)
    vista = _pintar(fotograma, c.marcas[0], 0, 2, c)
    assert vista.shape == fotograma.shape
    assert vista.any(), "no se pinto nada encima"
    assert not fotograma.any(), "se modifico el fotograma original"


def test_escalar_solo_encoge():
    import numpy as np

    from cortador.revision import ANCHO_MAX, _escalar

    grande = np.zeros((2160, 3840, 3), dtype=np.uint8)
    assert _escalar(grande).shape[1] == ANCHO_MAX
    pequeno = np.zeros((360, 640, 3), dtype=np.uint8)
    assert _escalar(pequeno).shape == pequeno.shape
