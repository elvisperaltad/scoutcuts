"""Encadenado de las cinco etapas."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

from . import corte, ffmpeg, identidad, muestreo, presencia
from .perfil import Perfil
from .reglas import Ajustes, Segmento, segmentar

DETECTORES = ("color", "yolo")
IDENTIDADES = ("color", "cnn")


@dataclass
class Resultado:
    info: ffmpeg.InfoVideo
    segmentos: list[Segmento]
    muestras: int
    serie_ocupacion: np.ndarray
    detector: str
    identidad: str
    clips: list[Path] = field(default_factory=list)


def analizar(ruta_video: str, perfil: Perfil, ajustes: Ajustes | None = None,
             detector: str = "color", modo_identidad: str = "color",
             registrar=lambda _: None) -> Resultado:
    if detector not in DETECTORES:
        raise ValueError(f"Detector desconocido: {detector}. Usa uno de {DETECTORES}.")
    if modo_identidad not in IDENTIDADES:
        raise ValueError(f"Identidad desconocida: {modo_identidad}. Usa una de {IDENTIDADES}.")

    ajustes = ajustes or Ajustes()
    info = ffmpeg.info(ruta_video)

    registrar("[1/4] muestreando keyframes")
    muestras = muestreo.muestrear(ruta_video, perfil)
    registrar(f"      {len(muestras)} recortes de {info.duracion:.0f} s de video")

    registrar(f"[2/4] presencia en el cajon ({detector})")
    cajas = None
    fondo = presencia.estimar_fondo(muestras.imagenes)
    if detector == "yolo":
        from . import presencia_yolo

        mascara, serie, cajas = presencia_yolo.ocupado(muestras.imagenes)
    else:
        mascara, serie = presencia.ocupado(muestras.imagenes, fondo=fondo)
    registrar(f"      {int(mascara.sum())} recortes ocupados ({mascara.mean() * 100:.0f} %)")

    registrar(f"[3/4] apariencia ({modo_identidad})")
    if modo_identidad == "cnn":
        from . import identidad_cnn as apariencia

        if ajustes.umbral_cambio == identidad.UMBRAL_CAMBIO:  # sin tocar por el usuario
            ajustes = replace(ajustes, umbral_cambio=apariencia.UMBRAL_CAMBIO)
    else:
        apariencia = identidad
    descs = apariencia.descriptores(muestras.imagenes, fondo, mascara, cajas)

    registrar("[4/4] reglas")
    segmentos = segmentar(
        tiempos=muestras.tiempos,
        ocupado=mascara.tolist(),
        descs=descs,
        keyframes=muestras.tiempos,
        duracion=info.duracion,
        ajustes=ajustes,
        apariencia=apariencia,
    )
    registrar(f"      {len(segmentos)} turnos")

    return Resultado(info=info, segmentos=segmentos, muestras=len(muestras),
                     serie_ocupacion=serie, detector=detector, identidad=modo_identidad)


def cortar(ruta_video: str, perfil: Perfil, carpeta_salida: str | Path,
           ajustes: Ajustes | None = None, detector: str = "color",
           modo_identidad: str = "color", registrar=lambda _: None) -> Resultado:
    resultado = analizar(ruta_video, perfil, ajustes, detector, modo_identidad, registrar)
    registrar(f"[+] exportando {len(resultado.segmentos)} clips")
    resultado.clips = corte.exportar(ruta_video, resultado.segmentos, carpeta_salida)
    return resultado
