"""Localizacion y ejecucion de ffmpeg/ffprobe."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass


class FfmpegNoEncontrado(RuntimeError):
    pass


def _buscar(nombre: str, variable: str) -> str:
    ruta = os.environ.get(variable)
    if ruta and os.path.isfile(ruta):
        return ruta
    hallado = shutil.which(nombre)
    if hallado:
        return hallado
    raise FfmpegNoEncontrado(
        f"No se encuentra {nombre}. Instalalo o define {variable} con la ruta al binario."
    )


def ruta_ffmpeg() -> str:
    return _buscar("ffmpeg", "CORTADOR_FFMPEG")


def ruta_ffprobe() -> str:
    return _buscar("ffprobe", "CORTADOR_FFPROBE")


def ejecutar(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        cola = (proc.stderr or "").strip().splitlines()[-8:]
        raise RuntimeError("Fallo el comando:\n  " + " ".join(cmd) + "\n" + "\n".join(cola))
    return proc.stdout


@dataclass(frozen=True)
class InfoVideo:
    ruta: str
    ancho: int
    alto: int
    duracion: float
    fps: float
    codec: str


def info(ruta: str) -> InfoVideo:
    salida = ejecutar([
        ruta_ffprobe(), "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,avg_frame_rate,codec_name:format=duration",
        "-of", "json", ruta,
    ])
    datos = json.loads(salida)
    flujo = datos["streams"][0]
    num, _, den = flujo["avg_frame_rate"].partition("/")
    fps = float(num) / float(den) if float(den or 0) else 0.0
    return InfoVideo(
        ruta=ruta,
        ancho=int(flujo["width"]),
        alto=int(flujo["height"]),
        duracion=float(datos["format"]["duration"]),
        fps=fps,
        codec=flujo["codec_name"],
    )


def keyframes(ruta: str) -> list[float]:
    """Instantes (s) de los keyframes del flujo de video, en orden."""
    salida = ejecutar([
        ruta_ffprobe(), "-v", "error",
        "-select_streams", "v:0",
        "-skip_frame", "nokey",
        "-show_entries", "frame=pts_time",
        "-of", "csv=p=0", ruta,
    ])
    tiempos = []
    for linea in salida.splitlines():
        linea = linea.strip().rstrip(",")
        if not linea or linea == "N/A":
            continue
        tiempos.append(float(linea))
    return sorted(tiempos)
