"""Etapa 5: candidatos de swing dentro de un turno.

El turno ya recortado sigue teniendo mas tiempo muerto que swings: el pelotero se
acomoda, espera, el lanzador recoge pelotas. Esta etapa no decide que es un swing
valido -- eso depende de si hubo pelota lanzada, y eso hoy lo pone una persona en
`cortador marcar`. Lo que hace es proponer los instantes en los que ocurre *algo*,
para no revisar el turno entero a mano.

El detector es la actividad en el ROI del cajon, fotograma a fotograma. Con una
correccion que no es opcional: en un H.264 el keyframe se codifica entero y sin
referencia al anterior, asi que la diferencia entre un keyframe y el fotograma que
lo precede es alta *siempre*, haya o no movimiento. Sobre el material de WhatsApp,
con un keyframe por segundo, ignorar esto llena la lista de picos falsos clavados
en los segundos redondos. Por eso se descartan esas parejas de fotogramas.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from . import ffmpeg
from .perfil import Perfil

SIGMAS = 2.2           # cuanto ha de superar la media para ser pico
SEPARACION = 0.4       # s minimos entre dos picos: por debajo es el mismo swing
VENTANA_MAX = 0.2      # s a cada lado en los que el pico ha de ser el maximo

# Ventana confirmada por el cliente sobre material real: 3 s antes muestran la
# preparación completa y 2 s después conservan el seguimiento sin entrar demasiado
# en el siguiente swing. Las ventanas solapadas se fusionan en `marcas.fundir`.
ANTES = 3.0            # s de tramo antes del pico
DESPUES = 2.0          # s de tramo despues del pico


@dataclass(frozen=True)
class Candidato:
    """Un instante con actividad; todavia no se sabe si vale."""

    instante: float
    fuerza: float       # actividad del pico, en niveles de gris por pixel

    def tramo(self, antes: float, despues: float) -> tuple[float, float]:
        return max(0.0, self.instante - antes), self.instante + despues


def _parejas_sucias(ruta: str, fps: float, total: int) -> set[int]:
    """Parejas de fotogramas que no se pueden comparar, por el indice del segundo.

    El keyframe se codifica entero y sin referencia al anterior, asi que arrastra su
    propio ruido de cuantizacion: queda distinto de sus DOS vecinos. Se descartan por
    tanto las dos parejas que lo tocan, (kf-1, kf) y (kf, kf+1). Quedarse solo con la
    primera deja pasar picos falsos justo despues de cada keyframe.
    """
    sucias: set[int] = set()
    for t in ffmpeg.keyframes(ruta):
        i = int(round(t * fps))
        for j in (i, i + 1):
            if 0 <= j < total:
                sucias.add(j)
    return sucias


def actividad(ruta_video: str, perfil: Perfil) -> tuple[np.ndarray, float]:
    """Serie de actividad por fotograma en el ROI. NaN donde no es medible."""
    captura = cv2.VideoCapture(ruta_video)
    if not captura.isOpened():
        raise RuntimeError(f"No se pudo abrir {ruta_video}")
    fps = captura.get(cv2.CAP_PROP_FPS) or ffmpeg.info(ruta_video).fps

    x, y, ancho, alto = perfil.x, perfil.y, perfil.ancho, perfil.alto
    serie: list[float] = []
    anterior = None
    try:
        while True:
            hay, fotograma = captura.read()
            if not hay:
                break
            gris = cv2.cvtColor(fotograma[y : y + alto, x : x + ancho], cv2.COLOR_BGR2GRAY)
            gris = gris.astype(np.int16)
            if anterior is not None:
                serie.append(float(np.abs(gris - anterior).mean()))
            anterior = gris
    finally:
        captura.release()

    valores = np.array(serie, dtype=np.float64)
    sucias = _parejas_sucias(ruta_video, fps, len(valores) + 1)
    for i in range(len(valores)):
        if (i + 1) in sucias:          # valores[i] compara el fotograma i+1 con el i
            valores[i] = np.nan
    return valores, fps


def detectar(ruta_video: str, perfil: Perfil, sigmas: float = SIGMAS) -> list[Candidato]:
    """Instantes con actividad muy por encima de la del resto del turno."""
    valores, fps = actividad(ruta_video, perfil)
    if np.all(np.isnan(valores)):
        return []

    umbral = np.nanmean(valores) + sigmas * np.nanstd(valores)
    radio = max(1, int(round(VENTANA_MAX * fps)))
    minimo = max(1, int(round(SEPARACION * fps)))

    candidatos: list[Candidato] = []
    ultimo = -minimo
    for i in range(radio, len(valores) - radio):
        v = valores[i]
        if np.isnan(v) or v < umbral:
            continue
        if v < np.nanmax(valores[i - radio : i + radio + 1]):
            continue
        if i - ultimo < minimo:
            continue
        candidatos.append(Candidato(instante=(i + 1) / fps, fuerza=float(v)))
        ultimo = i
    return candidatos
