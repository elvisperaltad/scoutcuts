"""Agente local: estado durable y avance sin decisiones inventadas."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from cortador import agente
from cortador.eventos import ANTES, DESPUES, SIGMAS, Candidato
from cortador.marcas import SIN_DECIDIR, VALIDO, Cuaderno
from cortador.perfil import Perfil
from cortador.reglas import Ajustes


def _entradas(tmp_path: Path) -> tuple[Path, Path, Path]:
    video = tmp_path / "jornada.mp4"
    video.write_bytes(b"video-local")
    perfil = tmp_path / "perfil.json"
    Perfil(x=0, y=0, ancho=10, alto=10, video_ancho=20, video_alto=20).guardar(perfil)
    return video, perfil, tmp_path / "trabajo"


def test_estado_se_guarda_atomicamente_y_se_reanuda(tmp_path):
    video, perfil, trabajo = _entradas(tmp_path)
    estado = agente.Estado.nuevo(video, perfil, trabajo)

    agente.guardar_estado(estado)
    vuelto = agente.cargar_estado(trabajo, video)

    assert vuelto.version == agente.VERSION_ESTADO
    assert vuelto.video == str(video.resolve())
    assert vuelto.perfil == str(perfil.resolve())
    assert not agente.ruta_estado(trabajo).with_suffix(".json.tmp").exists()


def test_estado_corrupto_se_rechaza_sin_sobrescribirlo(tmp_path):
    video, _, trabajo = _entradas(tmp_path)
    trabajo.mkdir()
    ruta = agente.ruta_estado(trabajo)
    original = "{esto no es json"
    ruta.write_text(original, encoding="utf-8")

    with pytest.raises(agente.ErrorEstado, match="corrupto"):
        agente.cargar_estado(trabajo, video)

    assert ruta.read_text(encoding="utf-8") == original


def test_estado_de_otro_video_se_rechaza_sin_destruirlo(tmp_path):
    video, perfil, trabajo = _entradas(tmp_path)
    agente.guardar_estado(agente.Estado.nuevo(video, perfil, trabajo))
    original = agente.ruta_estado(trabajo).read_bytes()
    otro = tmp_path / "otra.mp4"
    otro.write_bytes(b"otro")

    with pytest.raises(agente.ErrorEstado, match="otro video"):
        agente.cargar_estado(trabajo, otro)

    assert agente.ruta_estado(trabajo).read_bytes() == original


def test_version_desconocida_se_rechaza(tmp_path):
    video, perfil, trabajo = _entradas(tmp_path)
    estado = agente.Estado.nuevo(video, perfil, trabajo)
    agente.guardar_estado(estado)
    ruta = agente.ruta_estado(trabajo)
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["version"] = 999
    ruta.write_text(json.dumps(datos), encoding="utf-8")

    with pytest.raises(agente.ErrorEstado, match="version"):
        agente.cargar_estado(trabajo, video)


def test_flujo_no_interactivo_corta_detecta_espera_y_compacta(tmp_path, monkeypatch):
    video, perfil, trabajo = _entradas(tmp_path)
    llamadas = []

    def cortar_falso(ruta_video, perfil_cargado, carpeta, **opciones):
        llamadas.append("cortar")
        turno = Path(carpeta) / "turno_01.mp4"
        turno.parent.mkdir(parents=True, exist_ok=True)
        turno.write_bytes(b"turno")
        return SimpleNamespace(clips=[turno])

    def detectar_falso(ruta_video, perfil_cargado, sigmas):
        llamadas.append("detectar")
        return [Candidato(instante=2.0, fuerza=8.0)]

    def compactar_falso(ruta_video, tramos, destino):
        llamadas.append("compactar")
        salida = Path(destino)
        salida.parent.mkdir(parents=True, exist_ok=True)
        salida.write_bytes(b"compacto")
        return salida

    monkeypatch.setattr(agente, "cortar", cortar_falso)
    monkeypatch.setattr(agente.ffmpeg, "info", lambda ruta: SimpleNamespace(ancho=20, alto=20))
    monkeypatch.setattr(agente.eventos, "detectar", detectar_falso)
    monkeypatch.setattr(agente.compactar, "exportar", compactar_falso)

    mensajes = []
    resultado = agente.ejecutar(video, perfil, trabajo, interactivo=False,
                                registrar=mensajes.append)

    assert resultado == agente.PAUSA_HUMANA
    assert llamadas == ["cortar", "detectar"]
    estado = agente.cargar_estado(trabajo, video)
    assert len(estado.turnos) == 1
    cuaderno = Cuaderno.cargar(estado.turnos[0].marcas)
    assert len(cuaderno.pendientes) == 1
    assert any("revision humana" in mensaje.lower() for mensaje in mensajes)

    cuaderno.marcas[0].estado = VALIDO
    cuaderno.guardar(estado.turnos[0].marcas)
    resultado = agente.ejecutar(video, perfil, trabajo, interactivo=False,
                                registrar=mensajes.append)

    assert resultado == agente.COMPLETADO
    assert llamadas == ["cortar", "detectar", "compactar"]
    estado = agente.cargar_estado(trabajo, video)
    assert estado.etapa == agente.COMPLETADO
    assert Path(estado.turnos[0].salida).exists()


def test_valida_video_y_perfil_antes_de_crear_estado(tmp_path):
    video = tmp_path / "no-existe.mp4"
    perfil = tmp_path / "no-existe.json"
    trabajo = tmp_path / "trabajo"

    with pytest.raises(ValueError, match="video"):
        agente.ejecutar(video, perfil, trabajo, interactivo=False)

    assert not agente.ruta_estado(trabajo).exists()


def test_rechaza_perfil_de_otra_resolucion(tmp_path, monkeypatch):
    video, perfil, trabajo = _entradas(tmp_path)
    monkeypatch.setattr(agente.ffmpeg, "info", lambda ruta: SimpleNamespace(ancho=1920, alto=1080))

    with pytest.raises(ValueError, match="resolucion"):
        agente.ejecutar(video, perfil, trabajo, interactivo=False)

    assert not agente.ruta_estado(trabajo).exists()


def test_cli_agente_ofrece_modo_no_interactivo():
    from cortador.cli import construir_parser

    args = construir_parser().parse_args([
        "agente", "jornada.mp4", "--perfil", "perfil.json",
        "--trabajo", "sesion", "--no-interactivo",
    ])

    assert args.comando == "agente"
    assert args.interactivo is False


def _simular(monkeypatch, turnos: int = 1, candidatos: dict | None = None) -> list[str]:
    """Sustituye el video pesado; ``candidatos`` va por nombre de clip."""
    llamadas: list[str] = []
    candidatos = candidatos or {}

    def cortar_falso(ruta_video, perfil_cargado, carpeta, **opciones):
        llamadas.append("cortar")
        clips = []
        for numero in range(1, turnos + 1):
            clip = Path(carpeta) / f"turno_{numero:02d}.mp4"
            clip.parent.mkdir(parents=True, exist_ok=True)
            clip.write_bytes(b"turno")
            clips.append(clip)
        return SimpleNamespace(clips=clips)

    def detectar_falso(ruta_video, perfil_cargado, sigmas):
        nombre = Path(ruta_video).name
        llamadas.append(f"detectar {nombre}")
        return candidatos.get(nombre, [Candidato(instante=2.0, fuerza=8.0)])

    def compactar_falso(ruta_video, tramos, destino):
        llamadas.append(f"compactar {Path(ruta_video).name}")
        salida = Path(destino)
        salida.parent.mkdir(parents=True, exist_ok=True)
        salida.write_bytes(b"compacto")
        return salida

    monkeypatch.setattr(agente, "cortar", cortar_falso)
    monkeypatch.setattr(agente.ffmpeg, "info", lambda ruta: SimpleNamespace(ancho=20, alto=20))
    monkeypatch.setattr(agente.eventos, "detectar", detectar_falso)
    monkeypatch.setattr(agente.compactar, "exportar", compactar_falso)
    return llamadas


def _decidir(trabajo: Path, video: Path, nombre: str, estado_marca: str = VALIDO) -> None:
    """Hace de persona: decide todas las marcas de un turno."""
    estado = agente.cargar_estado(trabajo, video)
    turno = next(t for t in estado.turnos if Path(t.video).name == nombre)
    cuaderno = Cuaderno.cargar(turno.marcas)
    for marca in cuaderno.marcas:
        marca.estado = estado_marca
    cuaderno.guardar(turno.marcas)


def _completar(tmp_path: Path, monkeypatch, turnos: int = 2):
    video, perfil, trabajo = _entradas(tmp_path)
    llamadas = _simular(monkeypatch, turnos=turnos)
    agente.ejecutar(video, perfil, trabajo, interactivo=False, registrar=lambda m: None)
    for numero in range(1, turnos + 1):
        _decidir(trabajo, video, f"turno_{numero:02d}.mp4")
    resultado = agente.ejecutar(video, perfil, trabajo, interactivo=False,
                                registrar=lambda m: None)
    assert resultado == agente.COMPLETADO
    llamadas.clear()
    return video, perfil, trabajo, llamadas


def test_rechaza_carpeta_de_trabajo_movida(tmp_path):
    video, perfil, trabajo = _entradas(tmp_path)
    agente.guardar_estado(agente.Estado.nuevo(video, perfil, trabajo))
    movida = tmp_path / "movida"
    trabajo.rename(movida)
    original = agente.ruta_estado(movida).read_bytes()

    with pytest.raises(agente.ErrorEstado, match="se movió"):
        agente.cargar_estado(movida, video)

    assert agente.ruta_estado(movida).read_bytes() == original
    assert not trabajo.exists()


def test_estado_guarda_los_parametros_que_afectan_resultados(tmp_path, monkeypatch):
    video, perfil, trabajo = _entradas(tmp_path)
    _simular(monkeypatch)

    agente.ejecutar(video, perfil, trabajo, interactivo=False, registrar=lambda m: None)

    datos = json.loads(agente.ruta_estado(trabajo).read_text(encoding="utf-8"))
    assert datos["version"] == agente.VERSION_ESTADO == 2
    assert datos["parametros"] == {
        "detector": "color",
        "identidad": "color",
        "ajustes": asdict(Ajustes()),
        "sigmas": SIGMAS,
        "antes": ANTES,
        "despues": DESPUES,
        "separacion": 0.5,
    }


@pytest.mark.parametrize("cambio", [
    {"detector": "yolo"},
    {"identidad": "cnn"},
    {"ajustes": Ajustes(gap_fusion=10.0)},
    {"sigmas": 9.0},
    {"antes": 0.1},
    {"despues": 0.1},
    {"separacion": 2.0},
])
def test_rechaza_reanudar_con_otros_parametros(tmp_path, monkeypatch, cambio):
    video, perfil, trabajo = _entradas(tmp_path)
    _simular(monkeypatch)
    agente.ejecutar(video, perfil, trabajo, interactivo=False, registrar=lambda m: None)
    original = agente.ruta_estado(trabajo).read_bytes()

    with pytest.raises(agente.ErrorEstado, match="parámetros"):
        agente.ejecutar(video, perfil, trabajo, interactivo=False,
                        registrar=lambda m: None, **cambio)

    assert agente.ruta_estado(trabajo).read_bytes() == original


def test_no_interactivo_detecta_todos_los_turnos_antes_de_pausar(tmp_path, monkeypatch):
    video, perfil, trabajo = _entradas(tmp_path)
    llamadas = _simular(monkeypatch, turnos=3)

    resultado = agente.ejecutar(video, perfil, trabajo, interactivo=False,
                                registrar=lambda m: None)

    assert resultado == agente.PAUSA_HUMANA
    assert llamadas == ["cortar", "detectar turno_01.mp4", "detectar turno_02.mp4",
                        "detectar turno_03.mp4"]
    estado = agente.cargar_estado(trabajo, video)
    assert all(Path(t.marcas).exists() for t in estado.turnos)

    _decidir(trabajo, video, "turno_02.mp4")
    llamadas.clear()
    resultado = agente.ejecutar(video, perfil, trabajo, interactivo=False,
                                registrar=lambda m: None)

    assert resultado == agente.PAUSA_HUMANA
    assert llamadas == ["compactar turno_02.mp4"]


def test_cuaderno_corrupto_es_error_estado_sin_sobrescribirlo(tmp_path, monkeypatch):
    video, perfil, trabajo = _entradas(tmp_path)
    _simular(monkeypatch)
    agente.ejecutar(video, perfil, trabajo, interactivo=False, registrar=lambda m: None)
    ruta = Path(agente.cargar_estado(trabajo, video).turnos[0].marcas)
    ruta.write_text("{roto", encoding="utf-8")

    with pytest.raises(agente.ErrorEstado, match="cuaderno"):
        agente.ejecutar(video, perfil, trabajo, interactivo=False, registrar=lambda m: None)

    assert ruta.read_text(encoding="utf-8") == "{roto"


def test_completado_recompacta_solo_el_compacto_que_falta(tmp_path, monkeypatch):
    video, perfil, trabajo, llamadas = _completar(tmp_path, monkeypatch)
    estado = agente.cargar_estado(trabajo, video)
    Path(estado.turnos[0].salida).unlink()

    resultado = agente.ejecutar(video, perfil, trabajo, interactivo=False,
                                registrar=lambda m: None)

    assert resultado == agente.COMPLETADO
    assert llamadas == ["compactar turno_01.mp4"]
    assert Path(estado.turnos[0].salida).exists()


def test_completado_recompacta_si_el_cuaderno_cambio(tmp_path, monkeypatch):
    video, perfil, trabajo, llamadas = _completar(tmp_path, monkeypatch)
    ruta = Path(agente.cargar_estado(trabajo, video).turnos[1].marcas)
    cuaderno = Cuaderno.cargar(ruta)
    cuaderno.marcas[0].fin += 0.4
    cuaderno.guardar(ruta)

    resultado = agente.ejecutar(video, perfil, trabajo, interactivo=False,
                                registrar=lambda m: None)

    assert resultado == agente.COMPLETADO
    assert llamadas == ["compactar turno_02.mp4"]

    llamadas.clear()
    assert agente.ejecutar(video, perfil, trabajo, interactivo=False,
                           registrar=lambda m: None) == agente.COMPLETADO
    assert llamadas == []


def test_completado_con_marcas_devueltas_a_pendiente_pausa_sin_decidir(tmp_path, monkeypatch):
    video, perfil, trabajo, llamadas = _completar(tmp_path, monkeypatch)
    _decidir(trabajo, video, "turno_01.mp4", SIN_DECIDIR)

    resultado = agente.ejecutar(video, perfil, trabajo, interactivo=False,
                                registrar=lambda m: None)

    assert resultado == agente.PAUSA_HUMANA
    assert llamadas == []
    ruta = agente.cargar_estado(trabajo, video).turnos[0].marcas
    assert len(Cuaderno.cargar(ruta).pendientes) == 1


def test_reanudacion_identica_salta_turnos_sin_candidatos(tmp_path, monkeypatch):
    video, perfil, trabajo = _entradas(tmp_path)
    llamadas = _simular(monkeypatch, turnos=2, candidatos={"turno_01.mp4": []})
    agente.ejecutar(video, perfil, trabajo, interactivo=False, registrar=lambda m: None)
    llamadas.clear()

    resultado = agente.ejecutar(video, perfil, trabajo, interactivo=False,
                                registrar=lambda m: None)

    assert resultado == agente.PAUSA_HUMANA
    assert llamadas == []


def test_jornada_sin_turnos_completa_sin_volver_a_cortar(tmp_path, monkeypatch):
    video, perfil, trabajo = _entradas(tmp_path)
    llamadas = _simular(monkeypatch, turnos=0)

    assert agente.ejecutar(video, perfil, trabajo, interactivo=False,
                           registrar=lambda m: None) == agente.COMPLETADO
    assert llamadas == ["cortar"]

    llamadas.clear()
    assert agente.ejecutar(video, perfil, trabajo, interactivo=False,
                           registrar=lambda m: None) == agente.COMPLETADO
    assert llamadas == []


def test_turno_completado_no_exige_el_clip_fuente(tmp_path, monkeypatch):
    video, perfil, trabajo = _entradas(tmp_path)
    llamadas = _simular(monkeypatch, turnos=2)
    agente.ejecutar(video, perfil, trabajo, interactivo=False, registrar=lambda m: None)
    _decidir(trabajo, video, "turno_01.mp4")
    agente.ejecutar(video, perfil, trabajo, interactivo=False, registrar=lambda m: None)
    primero = agente.cargar_estado(trabajo, video).turnos[0]
    assert Path(primero.salida).exists()
    Path(primero.video).unlink()
    llamadas.clear()

    resultado = agente.ejecutar(video, perfil, trabajo, interactivo=False,
                                registrar=lambda m: None)

    assert resultado == agente.PAUSA_HUMANA
    assert "compactar turno_01.mp4" not in llamadas


@pytest.mark.parametrize("resultado, codigo", [
    (agente.PAUSA_HUMANA, 2),
    (agente.COMPLETADO, 0),
])
def test_cli_main_agente_distingue_pausa_de_completado(monkeypatch, resultado, codigo):
    from cortador import cli

    monkeypatch.setattr(cli.agente_mod, "ejecutar", lambda *a, **k: resultado)

    assert cli.main(["agente", "jornada.mp4", "--perfil", "perfil.json",
                     "--no-interactivo"]) == codigo
