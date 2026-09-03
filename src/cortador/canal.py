"""Encadenado de las cinco etapas."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import corte, ffmpeg, identidad, muestreo, presencia
from .perfil import Perfil
from .reglas import Ajustes, Segmento, segmentar


@dataclass
class Resultado:
    info: ffmpeg.InfoVideo
    segmentos: list[Segmento]
    muestras: int
    serie_ocupacion: np.ndarray
    clips: list[Path]


def analizar(ruta_video: str, perfil: Perfil, ajustes: Ajustes | None = None,
             registrar=lambda _: None) -> Resultado:
    info = ffmpeg.info(ruta_video)

    registrar("[1/4] muestreando keyframes")
    muestras = muestreo.muestrear(ruta_video, perfil)
    registrar(f"      {len(muestras)} recortes de {info.duracion:.0f} s de video")

    registrar("[2/4] presencia en el cajon")
    fondo = presencia.estimar_fondo(muestras.imagenes)
    mascara, serie = presencia.ocupado(muestras.imagenes, fondo=fondo)
    registrar(f"      {int(mascara.sum())} recortes ocupados ({mascara.mean() * 100:.0f} %)")

    registrar("[3/4] apariencia")
    descs = identidad.descriptores(muestras.imagenes, fondo, mascara)

    registrar("[4/4] reglas")
    segmentos = segmentar(
        tiempos=muestras.tiempos,
        ocupado=mascara.tolist(),
        descs=descs,
        keyframes=muestras.tiempos,
        duracion=info.duracion,
        ajustes=ajustes,
    )
    registrar(f"      {len(segmentos)} turnos")

    return Resultado(info=info, segmentos=segmentos, muestras=len(muestras),
                     serie_ocupacion=serie, clips=[])


def cortar(ruta_video: str, perfil: Perfil, carpeta_salida: str | Path,
           ajustes: Ajustes | None = None, registrar=lambda _: None) -> Resultado:
    resultado = analizar(ruta_video, perfil, ajustes, registrar)
    registrar(f"[+] exportando {len(resultado.segmentos)} clips")
    resultado.clips = corte.exportar(ruta_video, resultado.segmentos, carpeta_salida)
    return resultado
