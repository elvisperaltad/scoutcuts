"""Etapa 1: decodificar solo los keyframes y recortar el ROI.

Con un GOP de 2 s, una jornada de 3 h son unos 5.400 recortes pequenos en vez de
324.000 fotogramas completos. Es la etapa que domina el tiempo de proceso.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

import numpy as np

from . import ffmpeg
from .perfil import Perfil

ANCHO_MUESTRA = 224


def alto_muestra(perfil: Perfil, ancho: int = ANCHO_MUESTRA) -> int:
    """Alto del recorte escalado, forzado a par (lo exige el escalador)."""
    alto = round(perfil.alto * ancho / perfil.ancho)
    return max(2, alto + (alto % 2))


@dataclass
class Muestras:
    """Recortes del ROI, uno por keyframe, alineados con sus instantes."""

    tiempos: list[float]
    imagenes: np.ndarray  # (n, alto, ancho, 3) en RGB

    def __len__(self) -> int:
        return len(self.tiempos)


def muestrear(ruta_video: str, perfil: Perfil, ancho: int = ANCHO_MUESTRA) -> Muestras:
    tiempos = ffmpeg.keyframes(ruta_video)
    if not tiempos:
        raise RuntimeError("El video no declara keyframes; revisa el fichero de entrada.")

    alto = alto_muestra(perfil, ancho)
    cmd = [
        ffmpeg.ruta_ffmpeg(), "-v", "error",
        "-skip_frame", "nokey",
        "-i", ruta_video,
        "-fps_mode", "passthrough",
        "-vf", f"{perfil.crop},scale={ancho}:{alto}",
        "-f", "image2pipe", "-vcodec", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        cola = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-8:]
        raise RuntimeError("Fallo el muestreo:\n" + "\n".join(cola))

    bytes_por_frame = ancho * alto * 3
    n = len(proc.stdout) // bytes_por_frame
    if n == 0:
        raise RuntimeError("El muestreo no devolvio ningun fotograma.")

    imagenes = np.frombuffer(proc.stdout[: n * bytes_por_frame], dtype=np.uint8)
    imagenes = imagenes.reshape(n, alto, ancho, 3)

    # ffprobe y ffmpeg pueden discrepar en un fotograma al final del fichero.
    n = min(n, len(tiempos))
    return Muestras(tiempos=tiempos[:n], imagenes=imagenes[:n])
