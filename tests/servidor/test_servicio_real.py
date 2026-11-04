"""Prueba de extremo a extremo con el material real del proyecto.

Sube el video del scout por la API, espera la cola y comprueba que el montaje
entregado se puede abrir. Se salta si falta ffmpeg o el video; para ver los
números de la corrida:

    .venv\\Scripts\\python.exe -m pytest tests/servidor/test_servicio_real.py -s
"""

from pathlib import Path

import pytest

from cortador import ffmpeg, marcas

RAIZ = Path(__file__).resolve().parents[2]
VIDEO = RAIZ / "Video" / "carlos" / "VIDEO-2026-09-08-18-36-39.mov"
PERFILES = RAIZ / "perfiles"


def _hay_ffmpeg() -> bool:
    try:
        ffmpeg.ruta_ffmpeg()
        ffmpeg.ruta_ffprobe()
        return True
    except ffmpeg.FfmpegNoEncontrado:
        return False


pytestmark = pytest.mark.skipif(
    not (_hay_ffmpeg() and VIDEO.is_file() and PERFILES.is_dir()),
    reason="hace falta ffmpeg y el video real del proyecto",
)


def test_el_scout_sube_su_video_y_recibe_el_montaje(servicio, tmp_path):
    from cortador.servidor import almacen as mod

    activo = servicio(perfiles=PERFILES)
    original = ffmpeg.info(str(VIDEO))

    with VIDEO.open("rb") as flujo:
        creado = activo.cliente.post(
            "/v1/trabajos",
            files={"archivo": (VIDEO.name, flujo, "video/quicktime")},
            headers=activo.cabeceras,
        )
    assert creado.status_code == 201
    identificador = creado.json()["id"]

    assert activo.cola.esperar(900) is True, "la cola no terminó a tiempo"
    estado = activo.cliente.get(
        f"/v1/trabajos/{identificador}", headers=activo.cabeceras).json()
    assert estado["estado"] == mod.LISTO, estado["mensaje"]
    assert estado["resultado_disponible"] is True

    trabajo = activo.almacen.estado(identificador)
    cuaderno = marcas.Cuaderno.cargar(activo.almacen.ruta_marcas(trabajo))
    tramos = marcas.fundir(cuaderno)

    descarga = activo.cliente.get(
        f"/v1/trabajos/{identificador}/resultado", headers=activo.cabeceras)
    assert descarga.status_code == 200
    entregado = tmp_path / "montaje-entregado.mp4"
    entregado.write_bytes(descarga.content)

    montaje = ffmpeg.info(str(entregado))
    print(
        f"\nE2E real · entrada {original.duracion:.1f} s {original.ancho}x{original.alto}"
        f" · candidatos {len(cuaderno.marcas)} · tramos {len(tramos)}"
        f" · montaje {montaje.duracion:.1f} s {montaje.ancho}x{montaje.alto}"
        f" · {entregado.stat().st_size / 1024:.0f} KiB\n{estado['mensaje']}"
    )

    assert len(cuaderno.marcas) > 0
    assert montaje.duracion > 0
    assert montaje.duracion < original.duracion
    assert (montaje.ancho, montaje.alto) == (original.ancho, original.alto)
    # El original se borra al entregarlo: el servidor no acumula video de menores.
    assert not activo.almacen.ruta_entrada(trabajo).exists()
