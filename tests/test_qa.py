import json
import os
import zipfile
from pathlib import Path

import pytest


def test_directorio_datos_frozen_y_desarrollo(tmp_path, monkeypatch):
    from cortador import qa

    monkeypatch.setattr(qa.sys, "frozen", True, raising=False)
    monkeypatch.setattr(qa.sys, "executable", str(tmp_path / "portable" / "Cortador.exe"))
    assert qa.directorio_datos() == tmp_path / "portable" / "DatosQA"

    monkeypatch.delattr(qa.sys, "frozen", raising=False)
    assert qa.directorio_datos() == Path(__file__).resolve().parents[1] / "DatosQA"
    assert qa.directorio_datos(tmp_path / "inyectado") == tmp_path / "inyectado"


def test_corrida_atomica_sin_pii_y_copia_etiqueta(tmp_path, monkeypatch):
    from cortador import qa

    fuente = tmp_path / "Jugador Uno" / "turno.marcas.json"
    fuente.parent.mkdir()
    fuente.write_text('{"video":"C:/Users/Ana/secreto.mp4","marcas":[]}', encoding="utf-8")
    reemplazos = []
    real_replace = os.replace
    monkeypatch.setattr(qa.os, "replace", lambda a, b: (reemplazos.append((Path(a), Path(b))), real_replace(a, b))[1])

    corrida = qa.CorridaQA(fuente.parent, base=tmp_path / "qa", run_id="r-1")
    corrida.agregar_video(fuente.parent / "turno.mp4", tipo="bateo",
                          perfil="C:/privado/perfiles/camara.json")
    corrida.actualizar_video("turno.mp4", candidatos=[{"instante": 2, "fuerza": .8}],
                              decisiones=[{"inicio": 1, "fin": 3, "instante": 2,
                                           "estado": "valido", "nota": "ok"}],
                              validos=1, pendientes=0, salida=fuente.parent / "Resultados/x.mp4")
    copia = corrida.copiar_etiqueta(fuente, "turno.mp4")
    destino = corrida.finalizar("completado", "bien")

    datos = json.loads(destino.read_text(encoding="utf-8"))
    texto = json.dumps(datos)
    assert datos["carpeta_jugador"] == "Jugador Uno"
    assert datos["videos"][0]["perfil"] == "camara.json"
    assert datos["videos"][0]["salida"] == "x.mp4"
    assert "C:/" not in texto and "Ana" not in texto
    assert copia.name.startswith("r-1_")
    assert json.loads(copia.read_text(encoding="utf-8"))["video"] == "secreto.mp4"
    assert reemplazos and reemplazos[-1][0].suffix == ".tmp"
    assert not reemplazos[-1][0].exists()


def test_paquete_incluye_solo_evidencia_permitida(tmp_path):
    from cortador.qa import crear_paquete_qa

    base = tmp_path / "DatosQA"
    (base / "corridas").mkdir(parents=True)
    (base / "etiquetas").mkdir()
    (base / "corridas/r.json").write_text("{}", encoding="utf-8")
    (base / "etiquetas/e.json").write_text("{}", encoding="utf-8")
    (base / "app.log").write_text("log", encoding="utf-8")
    (base / "video.mp4").write_bytes(b"NO")
    (base / "anterior.zip").write_bytes(b"NO")
    destino = crear_paquete_qa(base=base, destino=tmp_path / "paquete.zip")

    with zipfile.ZipFile(destino) as archivo:
        assert set(archivo.namelist()) == {"corridas/r.json", "etiquetas/e.json", "app.log"}


def test_evidencia_es_best_effort(tmp_path, monkeypatch):
    from cortador import qa

    corrida = qa.CorridaQA(tmp_path, base=tmp_path / "qa", run_id="r")
    monkeypatch.setattr(qa.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("disco")))
    assert corrida.finalizar("error", "fallo") is None
    monkeypatch.setattr(Path, "open", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disco")))
    assert qa.registrar_log("ERROR", "fallo", base=tmp_path / "qa") is False


def test_log_de_error_no_expone_rutas_absolutas(tmp_path):
    from cortador import qa

    try:
        raise RuntimeError("falló C:/Users/Ana/Videos/jugador.mp4")
    except RuntimeError as err:
        assert qa.registrar_log("ERROR", str(err), base=tmp_path / "qa", excepcion=err)

    texto = (tmp_path / "qa" / "app.log").read_text(encoding="utf-8")
    assert "C:/Users" not in texto
    assert "Ana" not in texto
    assert "jugador.mp4" in texto


def test_tarea_carpeta_registra_revision_pendientes_y_error(tmp_path):
    from cortador import ffmpeg
    from cortador.app import tarea_carpeta_jugador

    jugador = tmp_path / "jugador"
    jugador.mkdir()
    (jugador / "pendiente.mp4").write_bytes(b"video")
    base = tmp_path / "evidencia"
    perfiles = tmp_path / "perfiles"
    perfiles.mkdir()

    resultado = tarea_carpeta_jugador(
        jugador, perfiles=perfiles, qa_base=base,
        obtener_info=lambda ruta: ffmpeg.InfoVideo(ruta, 640, 360, 12.5, 30, "h264"),
    )

    registro = next((base / "corridas").glob("*.json"))
    datos = json.loads(registro.read_text(encoding="utf-8"))
    assert resultado.codigo == 2
    assert datos["estado"] == "completado"
    assert datos["videos"][0]["pendientes"] == 1
    assert datos["videos"][0]["metadatos"] == {
        "ancho": 640, "alto": 360, "fps": 30, "duracion": 12.5, "codec": "h264"
    }
    assert "jugador" == datos["carpeta_jugador"]
