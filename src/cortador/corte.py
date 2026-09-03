"""Etapa 4b: exportar cada turno con copia de flujo.

Como la salida conserva el formato de entrada no hay que recodificar: -c copy copia
los paquetes tal cual, mismo codec, misma resolucion, mismo bitrate y cero perdida
generacional. -an descarta el audio.
"""

from __future__ import annotations

from pathlib import Path

from . import ffmpeg
from .reglas import Segmento


def nombre_clip(indice: int) -> str:
    return f"turno_{indice:02d}.mp4"


def exportar(ruta_video: str, segmentos: list[Segmento], carpeta_salida: str | Path) -> list[Path]:
    carpeta = Path(carpeta_salida)
    carpeta.mkdir(parents=True, exist_ok=True)

    generados: list[Path] = []
    for indice, seg in enumerate(segmentos, start=1):
        destino = carpeta / nombre_clip(indice)
        # -ss antes de -i busca el keyframe anterior: es el ajuste hacia fuera.
        ffmpeg.ejecutar([
            ffmpeg.ruta_ffmpeg(), "-v", "error", "-y",
            "-ss", f"{seg.inicio:.3f}",
            "-i", ruta_video,
            "-t", f"{seg.duracion:.3f}",
            "-map", "0:v:0", "-an", "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            "-movflags", "+faststart",
            str(destino),
        ])
        generados.append(destino)
    return generados
