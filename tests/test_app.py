import json
import threading
from pathlib import Path

import pytest

from cortador import agente, cli


def _manifiesto(video):
    repeticiones = []
    for categoria, base in (("adelante", 1), ("derecha", 11), ("izquierda", 21)):
        repeticiones.extend([
            {"categoria": categoria, "inicio": base, "tiro": base + 1, "estado": "completa"},
            {"categoria": categoria, "inicio": base + 3, "tiro": base + 4, "estado": "completa"},
        ])
    return {"version": 1, "video": video, "repeticiones": repeticiones}


def test_tarea_defensa_valida_calcula_tramos_y_exporta(tmp_path):
    from cortador.app import tarea_defensa

    video = tmp_path / "defensa.mp4"
    video.write_bytes(b"video")
    manifiesto = tmp_path / "defensa.json"
    manifiesto.write_text(json.dumps(_manifiesto(video.name)), encoding="utf-8")
    salida = tmp_path / "salida.mp4"
    llamadas = []
    mensajes = []

    def exportar(video_arg, tramos, salida_arg):
        llamadas.append((video_arg, tramos, salida_arg))
        return salida_arg

    resultado = tarea_defensa(
        video, manifiesto, salida, 1.5, 0.2,
        registrar=mensajes.append, exportar=exportar,
    )

    assert resultado.codigo == 0
    assert resultado.estado == "completado"
    assert llamadas == [(str(video), [
        (0.0, 2.2), (2.5, 5.2), (9.5, 12.2),
        (12.5, 15.2), (19.5, 22.2), (22.5, 25.2),
    ], str(salida))]
    assert any("6 repeticiones" in mensaje for mensaje in mensajes)


def test_tarea_defensa_rechaza_margen_invalido_antes_de_exportar(tmp_path):
    from cortador.app import tarea_defensa

    with pytest.raises(ValueError, match="margen"):
        tarea_defensa("video.mp4", "marcas.json", "salida.mp4", -1, 0.3,
                      exportar=lambda *args: pytest.fail("no debe exportar"))


@pytest.mark.parametrize("estado,codigo", [
    (agente.PAUSA_HUMANA, 2),
    (agente.COMPLETADO, 0),
])
def test_tarea_bateo_propaga_estado_codigo_y_logs(estado, codigo):
    from cortador.app import tarea_bateo

    mensajes = []

    def ejecutar(video, perfil, trabajo, **opciones):
        opciones["registrar"]("avance del motor")
        assert opciones["interactivo"] is False
        return estado

    resultado = tarea_bateo(
        "jornada.mp4", "perfil.json", "trabajo", interactivo=False,
        registrar=mensajes.append, ejecutar=ejecutar,
    )

    assert (resultado.estado, resultado.codigo) == (estado, codigo)
    assert "avance del motor" in mensajes
    assert any("Código de salida" in mensaje for mensaje in mensajes)


def test_tarea_bateo_interactiva_confirma_revision_sin_leer_consola():
    from cortador.app import tarea_bateo

    def ejecutar(video, perfil, trabajo, **opciones):
        assert opciones["interactivo"] is True
        assert opciones["preguntar"]("pregunta que no debe llegar a input") == "s"
        return agente.COMPLETADO

    resultado = tarea_bateo(
        "jornada.mp4", "perfil.json", "trabajo", interactivo=True,
        ejecutar=ejecutar,
    )

    assert resultado.codigo == 0


def test_parser_app_no_importa_tkinter_y_llama_lanzador(monkeypatch):
    args = cli.construir_parser().parse_args(["app"])
    assert args.comando == "app"

    llamadas = []
    monkeypatch.setattr("cortador.app.abrir", lambda: llamadas.append("abrir"))
    assert cli.main(["app"]) == 0
    assert llamadas == ["abrir"]


def test_worker_unico_rechaza_segundo_trabajo_y_publica_eventos():
    from cortador.app import WorkerUnico

    entrada = threading.Event()
    salida = threading.Event()
    worker = WorkerUnico()

    def tarea(registrar):
        registrar("trabajando")
        entrada.set()
        assert salida.wait(2)
        return "listo"

    assert worker.iniciar(tarea) is True
    assert entrada.wait(2)
    assert worker.iniciar(lambda registrar: None) is False
    salida.set()
    worker.esperar(2)

    eventos = []
    while not worker.eventos.empty():
        eventos.append(worker.eventos.get_nowait())
    assert eventos == [("log", "trabajando"), ("ok", "listo")]
    assert worker.ocupado is False


def _cuaderno(video, validas=1):
    return {
        "video": video,
        "marcas": [
            {"inicio": i * 2.0, "fin": i * 2.0 + 1.0,
             "instante": i * 2.0 + .5, "estado": "valido"}
            for i in range(validas)
        ],
    }


def test_descubrir_carpeta_encuentra_bateo_defensa_y_excluye_derivados(tmp_path):
    from cortador.app import descubrir_carpeta_jugador

    (tmp_path / "bateo.MP4").write_bytes(b"")
    (tmp_path / "bateo.marcas.json").write_text(
        json.dumps(_cuaderno("bateo.MP4")), encoding="utf-8")
    (tmp_path / "fildeo.mp4").write_bytes(b"")
    (tmp_path / "fildeo_defensa_6.json").write_text(
        json.dumps(_manifiesto("fildeo.mp4")), encoding="utf-8")
    (tmp_path / "nuevo.MOV").write_bytes(b"")
    for nombre in ("bateo_compacto.mp4", "fildeo_resultado.MP4", "bateo_clip_01.mp4"):
        (tmp_path / nombre).write_bytes(b"")
    resultados = tmp_path / "Resultados"
    resultados.mkdir()
    (resultados / "viejo.mp4").write_bytes(b"")

    hallazgo = descubrir_carpeta_jugador(tmp_path)

    assert [item.video.name for item in hallazgo.videos] == [
        "bateo.MP4", "fildeo.mp4", "nuevo.MOV",
    ]
    assert [item.tipo for item in hallazgo.videos] == ["bateo", "defensa", None]
    assert all("json" not in item.mensaje.lower() for item in hallazgo.videos)


def test_tarea_carpeta_exporta_bateo_y_defensa_sin_exponer_sidecars(tmp_path):
    from cortador.app import tarea_carpeta_jugador

    bateo = tmp_path / "bateo.mp4"
    defensa = tmp_path / "defensa.mp4"
    bateo.write_bytes(b"")
    defensa.write_bytes(b"")
    (tmp_path / "bateo.marcas.json").write_text(
        json.dumps(_cuaderno(bateo.name, 2)), encoding="utf-8")
    (tmp_path / "defensa_defensa_6.json").write_text(
        json.dumps(_manifiesto(defensa.name)), encoding="utf-8")
    llamadas = []
    mensajes = []

    def exportar(video, tramos, salida):
        llamadas.append((Path(video).name, tramos, Path(salida)))
        return Path(salida)

    resultado = tarea_carpeta_jugador(tmp_path, registrar=mensajes.append, exportar=exportar)

    assert resultado.codigo == 0
    assert [x[0] for x in llamadas] == ["bateo.mp4", "defensa.mp4"]
    assert llamadas[0][2] == tmp_path / "Resultados" / "bateo_bateo.mp4"
    assert llamadas[1][2] == tmp_path / "Resultados" / "defensa_defensa.mp4"
    assert "encontrados: 2" in resultado.detalle.lower()
    assert "generados: 2" in resultado.detalle.lower()
    assert not any("json" in mensaje.lower() for mensaje in mensajes)


def test_tarea_carpeta_informa_pendiente_y_aisla_error(tmp_path):
    from cortador import ffmpeg
    from cortador.app import tarea_carpeta_jugador

    for nombre in ("falla.mp4", "pendiente.mp4", "sirve.mp4"):
        (tmp_path / nombre).write_bytes(b"")
    for nombre in ("falla", "sirve"):
        (tmp_path / f"{nombre}.marcas.json").write_text(
            json.dumps(_cuaderno(f"{nombre}.mp4")), encoding="utf-8")
    mensajes = []

    def exportar(video, tramos, salida):
        if Path(video).name == "falla.mp4":
            raise RuntimeError("fallo simulado")
        return Path(salida)

    perfiles = tmp_path / "perfiles"
    perfiles.mkdir()
    resultado = tarea_carpeta_jugador(
        tmp_path, registrar=mensajes.append, exportar=exportar, perfiles=perfiles,
        obtener_info=lambda ruta: ffmpeg.InfoVideo(ruta, 1024, 576, 20, 30, "h264"),
    )

    assert resultado.codigo == 1
    assert "generados: 1" in resultado.detalle.lower()
    assert "pendientes: 1" in resultado.detalle.lower()
    assert "errores: 1" in resultado.detalle.lower()
    assert any("pendiente.mp4" in m and "pendiente" in m.lower() for m in mensajes)
    assert any("falla.mp4" in m and "error" in m.lower() for m in mensajes)


def test_tarea_carpeta_sin_videos_listos_da_respuesta_humana(tmp_path):
    from cortador import ffmpeg
    from cortador.app import tarea_carpeta_jugador

    (tmp_path / "nuevo.mp4").write_bytes(b"")
    mensajes = []

    perfiles = tmp_path / "perfiles"
    perfiles.mkdir()
    resultado = tarea_carpeta_jugador(
        tmp_path, registrar=mensajes.append, perfiles=perfiles,
        obtener_info=lambda ruta: ffmpeg.InfoVideo(ruta, 1024, 576, 20, 30, "h264"),
    )

    assert resultado.codigo == 2
    assert "ningún video está listo" in resultado.detalle.lower()
    assert "configuración" in " ".join(mensajes).lower()
    assert not any("json" in mensaje.lower() for mensaje in mensajes)


def _perfil(ruta, ancho=1024, alto=576):
    ruta.write_text(json.dumps({
        "x": 10, "y": 10, "ancho": 100, "alto": 100,
        "video_ancho": ancho, "video_alto": alto,
    }), encoding="utf-8")


def test_video_nuevo_con_perfil_unico_detecta_guarda_revisa_y_exporta(tmp_path):
    from cortador import ffmpeg, marcas
    from cortador.app import tarea_carpeta_jugador
    from cortador.eventos import Candidato

    video = tmp_path / "nuevo.mov"
    video.write_bytes(b"")
    perfiles = tmp_path / "perfiles"
    perfiles.mkdir()
    _perfil(perfiles / "camara.json")
    llamadas = []
    mensajes = []

    def detectar(ruta, perfil):
        llamadas.append(("detectar", Path(ruta), perfil.video_ancho))
        return [Candidato(4.0, 8.0)]

    def revisar(cuaderno, destino):
        llamadas.append(("revisar", Path(destino)))
        assert Path(destino).exists()
        cuaderno.marcas[0].estado = marcas.VALIDO
        cuaderno.guardar(destino)
        return cuaderno

    def exportar(ruta, tramos, destino):
        llamadas.append(("exportar", Path(ruta), tramos, Path(destino)))
        return destino

    resultado = tarea_carpeta_jugador(
        tmp_path, registrar=mensajes.append, perfiles=perfiles,
        obtener_info=lambda ruta: ffmpeg.InfoVideo(ruta, 1024, 576, 20, 30, "h264"),
        detectar=detectar, revisar=revisar, exportar=exportar,
    )

    assert [x[0] for x in llamadas] == ["detectar", "revisar", "exportar"]
    assert llamadas[2][2] == [(1.0, 6.0)]
    assert llamadas[2][3] == tmp_path / "Resultados" / "nuevo_bateo.mp4"
    assert (tmp_path / "nuevo.marcas.json").exists()
    guardado = json.loads((tmp_path / "nuevo.marcas.json").read_text(encoding="utf-8"))
    assert guardado["perfil"]
    assert "listos: 1" in resultado.detalle.lower()
    assert "generados: 1" in resultado.detalle.lower()
    assert any("v conserva, n descarta y q termina" in m.lower() for m in mensajes)


@pytest.mark.parametrize("cantidad", [0, 2])
def test_video_nuevo_sin_perfil_unico_compatible_queda_pendiente(tmp_path, cantidad):
    from cortador import ffmpeg
    from cortador.app import tarea_carpeta_jugador

    (tmp_path / "nuevo.mp4").write_bytes(b"")
    perfiles = tmp_path / "perfiles"
    perfiles.mkdir()
    for indice in range(cantidad):
        _perfil(perfiles / f"camara{indice}.json")
    mensajes = []

    resultado = tarea_carpeta_jugador(
        tmp_path, registrar=mensajes.append, perfiles=perfiles,
        obtener_info=lambda ruta: ffmpeg.InfoVideo(ruta, 1024, 576, 20, 30, "h264"),
        detectar=lambda *_: pytest.fail("no debe detectar"),
    )

    assert resultado.codigo == 2
    assert "pendientes: 1" in resultado.detalle.lower()
    assert any("configuración" in m.lower() and "1024x576" in m for m in mensajes)


def test_revision_de_video_nuevo_sin_validos_queda_pendiente(tmp_path):
    from cortador import ffmpeg
    from cortador.app import tarea_carpeta_jugador
    from cortador.eventos import Candidato

    (tmp_path / "nuevo.mp4").write_bytes(b"")
    perfiles = tmp_path / "perfiles"
    perfiles.mkdir()
    _perfil(perfiles / "camara.json")

    resultado = tarea_carpeta_jugador(
        tmp_path, perfiles=perfiles,
        obtener_info=lambda ruta: ffmpeg.InfoVideo(ruta, 1024, 576, 20, 30, "h264"),
        detectar=lambda *_: [Candidato(4.0, 8.0)],
        revisar=lambda cuaderno, destino: cuaderno,
        exportar=lambda *_: pytest.fail("no debe exportar"),
    )

    assert resultado.codigo == 2
    assert "pendientes: 1" in resultado.detalle.lower()
    assert "errores: 0" in resultado.detalle.lower()


def test_error_en_video_nuevo_no_detiene_el_siguiente(tmp_path):
    from cortador import ffmpeg, marcas
    from cortador.app import tarea_carpeta_jugador
    from cortador.eventos import Candidato

    for nombre in ("a.mp4", "b.mp4"):
        (tmp_path / nombre).write_bytes(b"")
    perfiles = tmp_path / "perfiles"
    perfiles.mkdir()
    _perfil(perfiles / "camara.json")
    exportados = []

    def detectar(ruta, perfil):
        if Path(ruta).name == "a.mp4":
            raise RuntimeError("fallo simulado")
        return [Candidato(4.0, 8.0)]

    def revisar(cuaderno, destino):
        cuaderno.marcas[0].estado = marcas.VALIDO
        return cuaderno

    resultado = tarea_carpeta_jugador(
        tmp_path, perfiles=perfiles,
        obtener_info=lambda ruta: ffmpeg.InfoVideo(ruta, 1024, 576, 20, 30, "h264"),
        detectar=detectar, revisar=revisar,
        exportar=lambda video, tramos, salida: exportados.append(Path(video).name),
    )

    assert exportados == ["b.mp4"]
    assert "generados: 1" in resultado.detalle.lower()
    assert "errores: 1" in resultado.detalle.lower()


@pytest.mark.parametrize("crear,mensaje", [
    (False, "no existe"),
    (True, "no se encontraron videos"),
])
def test_tarea_carpeta_ruta_invalida_o_vacia(tmp_path, crear, mensaje):
    from cortador.app import tarea_carpeta_jugador

    carpeta = tmp_path / "jugador"
    if crear:
        carpeta.mkdir()
    with pytest.raises(ValueError, match=f"(?i){mensaje}"):
        tarea_carpeta_jugador(carpeta)
