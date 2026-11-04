import io
import json
from pathlib import Path

import pytest

from cortador import ffmpeg
from cortador.eventos import Candidato


def _almacen(tmp_path):
    from cortador.servidor.almacen import Almacen

    return Almacen(tmp_path / "datos")


def _trabajo(guardia, nombre="turno de Luis.mov"):
    trabajo = guardia.crear(nombre, 5)
    guardia.guardar_entrada(trabajo, io.BytesIO(b"video"))
    return trabajo


def _perfiles(tmp_path, ancho=1024, alto=576, cuantos=1):
    carpeta = tmp_path / "perfiles"
    carpeta.mkdir(exist_ok=True)
    for indice in range(cuantos):
        (carpeta / f"camara{indice}.json").write_text(json.dumps({
            "x": 390, "y": 150, "ancho": 140, "alto": 180,
            "video_ancho": ancho, "video_alto": alto,
            "origen": f"camara{indice}.mp4",
        }), encoding="utf-8")
    return carpeta


def _info(ancho=1024, alto=576):
    return lambda ruta: ffmpeg.InfoVideo(ruta, ancho, alto, 70.9, 30.0, "h264")


def _exportar(registro):
    def exportar(video, tramos, salida):
        registro.append((Path(video).name, list(tramos), Path(salida)))
        Path(salida).parent.mkdir(parents=True, exist_ok=True)
        Path(salida).write_bytes(b"montaje")
        return Path(salida)

    return exportar


def test_perfil_compatible_detecta_marca_y_exporta_el_montaje(tmp_path):
    from cortador.servidor import almacen as mod
    from cortador.servidor import procesador

    guardia = _almacen(tmp_path)
    trabajo = _trabajo(guardia)
    exportados = []

    resultado = procesador.procesar(
        trabajo, guardia,
        perfiles=_perfiles(tmp_path), qa_base=tmp_path / "qa",
        obtener_info=_info(), exportar=_exportar(exportados),
        detectar=lambda ruta, perfil: [Candidato(10.0, 8.0), Candidato(12.0, 9.0)],
    )

    assert resultado.estado == mod.LISTO
    assert resultado.candidatos == 2
    assert guardia.ruta_resultado(trabajo).exists()
    assert exportados and exportados[0][1] == [(7.0, 14.0)]   # ventanas 3/2 fusionadas
    assert exportados[0][2] == guardia.ruta_resultado(trabajo)
    assert resultado.duracion == pytest.approx(7.0)
    assert resultado.mensaje and "montaje" in resultado.mensaje.lower()
    # el estado quedó guardado en disco, no sólo en memoria
    assert guardia.estado(trabajo.id).estado == mod.LISTO


def test_las_marcas_quedan_guardadas_para_mejorar_el_detector(tmp_path):
    from cortador import marcas
    from cortador.servidor import procesador

    guardia = _almacen(tmp_path)
    trabajo = _trabajo(guardia)

    procesador.procesar(
        trabajo, guardia,
        perfiles=_perfiles(tmp_path), qa_base=tmp_path / "qa",
        obtener_info=_info(), exportar=_exportar([]),
        detectar=lambda ruta, perfil: [Candidato(10.0, 8.0)],
    )

    cuaderno = marcas.Cuaderno.cargar(guardia.ruta_marcas(trabajo))
    assert len(cuaderno.marcas) == 1
    assert cuaderno.validas                      # sin persona que revise, se conservan
    assert cuaderno.marcas[0].nota
    assert cuaderno.perfil
    # Nada del nombre que subió el scout ni de su ruta entra en el material etiquetado.
    texto = guardia.ruta_marcas(trabajo).read_text(encoding="utf-8")
    assert "Luis" not in texto
    assert ":" not in cuaderno.video and "/" not in cuaderno.video


def test_sin_perfil_compatible_queda_pendiente_y_no_inventa_recorte(tmp_path):
    from cortador.servidor import almacen as mod
    from cortador.servidor import procesador

    guardia = _almacen(tmp_path)
    trabajo = _trabajo(guardia)

    resultado = procesador.procesar(
        trabajo, guardia,
        perfiles=_perfiles(tmp_path, ancho=1280, alto=720), qa_base=tmp_path / "qa",
        obtener_info=_info(1024, 576),
        detectar=lambda *_: pytest.fail("no debe detectar sin perfil"),
        exportar=lambda *_: pytest.fail("no debe exportar sin perfil"),
    )

    assert resultado.estado == mod.PENDIENTE_REVISION
    assert "1024x576" in resultado.mensaje
    assert "cámara" in resultado.mensaje.lower()
    assert not guardia.ruta_resultado(trabajo).exists()
    assert guardia.estado(trabajo.id).estado == mod.PENDIENTE_REVISION


def test_varios_perfiles_compatibles_tambien_quedan_pendientes(tmp_path):
    from cortador.servidor import almacen as mod
    from cortador.servidor import procesador

    guardia = _almacen(tmp_path)
    trabajo = _trabajo(guardia)

    resultado = procesador.procesar(
        trabajo, guardia,
        perfiles=_perfiles(tmp_path, cuantos=2), qa_base=tmp_path / "qa",
        obtener_info=_info(),
        detectar=lambda *_: pytest.fail("no debe detectar"),
        exportar=lambda *_: pytest.fail("no debe exportar"),
    )

    assert resultado.estado == mod.PENDIENTE_REVISION


def test_sin_candidatos_queda_listo_y_explica_que_no_hubo_swings(tmp_path):
    from cortador.servidor import almacen as mod
    from cortador.servidor import procesador

    guardia = _almacen(tmp_path)
    trabajo = _trabajo(guardia)

    resultado = procesador.procesar(
        trabajo, guardia,
        perfiles=_perfiles(tmp_path), qa_base=tmp_path / "qa",
        obtener_info=_info(),
        detectar=lambda ruta, perfil: [],
        exportar=lambda *_: pytest.fail("no debe exportar sin candidatos"),
    )

    assert resultado.estado == mod.LISTO
    assert resultado.candidatos == 0
    assert "swing" in resultado.mensaje.lower()
    assert not guardia.ruta_resultado(trabajo).exists()
    assert guardia.ruta_marcas(trabajo).exists()


def test_la_corrida_alimenta_la_evidencia_de_qa_sin_datos_personales(tmp_path):
    from cortador.servidor import procesador

    guardia = _almacen(tmp_path)
    trabajo = _trabajo(guardia)
    base = tmp_path / "qa"

    procesador.procesar(
        trabajo, guardia,
        perfiles=_perfiles(tmp_path), qa_base=base,
        obtener_info=_info(), exportar=_exportar([]),
        detectar=lambda ruta, perfil: [Candidato(10.0, 8.0)],
    )

    corrida = next((base / "corridas").glob("*.json"))
    datos = json.loads(corrida.read_text(encoding="utf-8"))
    texto = json.dumps(datos, ensure_ascii=False)
    assert datos["estado"] == "completado"
    assert datos["videos"][0]["candidatos"]
    assert datos["videos"][0]["metadatos"]["ancho"] == 1024
    assert "Luis" not in texto
    assert "C:/" not in texto and "C:\\" not in texto
    assert str(tmp_path) not in texto
    assert list((base / "etiquetas").glob("*.json"))


def test_un_fallo_del_motor_se_propaga_pero_deja_la_evidencia(tmp_path):
    from cortador.servidor import procesador

    guardia = _almacen(tmp_path)
    trabajo = _trabajo(guardia)
    base = tmp_path / "qa"

    def detectar(ruta, perfil):
        raise RuntimeError("fallo simulado del detector")

    with pytest.raises(RuntimeError):
        procesador.procesar(
            trabajo, guardia,
            perfiles=_perfiles(tmp_path), qa_base=base,
            obtener_info=_info(), detectar=detectar,
        )

    corrida = next((base / "corridas").glob("*.json"))
    assert json.loads(corrida.read_text(encoding="utf-8"))["estado"] == "error"
