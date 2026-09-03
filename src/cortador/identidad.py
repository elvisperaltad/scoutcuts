"""Etapa 3: apariencia del pelotero que ocupa el cajon.

Separa a dos peloteros que se relevan sin dejar hueco y reconoce al mismo cuando
vuelve tras salirse a ajustarse el guante.

Implementacion base: histograma HS (tono y saturacion) de los pixeles que se apartan
del fondo, es decir del propio pelotero y no de la tierra. Es un descriptor pobre pero
determinista y sin dependencias pesadas. El diseno acordado contempla sustituirlo por
OSNet o CLIP; lo unico que consume el resto del motor es `distancia`.
"""

from __future__ import annotations

import cv2
import numpy as np

from .presencia import UMBRAL_PIXEL, mascara_frente

BINS_H = 24
BINS_S = 8
# Por encima de esta distancia se consideran dos peloteros distintos.
UMBRAL_CAMBIO = 0.35


def descriptor(imagen: np.ndarray, fondo: np.ndarray,
               umbral_pixel: int = UMBRAL_PIXEL) -> np.ndarray:
    """Histograma HS normalizado de la silueta (lo que difiere del fondo)."""
    mascara = mascara_frente(imagen, fondo, umbral_pixel)
    if not mascara.any():
        return np.zeros(BINS_H * BINS_S, dtype=np.float32)

    hsv = cv2.cvtColor(imagen, cv2.COLOR_RGB2HSV)
    hist = cv2.calcHist([hsv], [0, 1], mascara, [BINS_H, BINS_S], [0, 180, 0, 256])
    cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
    return hist.flatten().astype(np.float32)


def descriptores(imagenes: np.ndarray, fondo: np.ndarray,
                 mascara_ocupado: np.ndarray) -> list[np.ndarray | None]:
    """Un descriptor por recorte ocupado; None donde el cajon esta vacio."""
    return [
        descriptor(imagen, fondo) if hay_alguien else None
        for imagen, hay_alguien in zip(imagenes, mascara_ocupado)
    ]


def distancia(a: np.ndarray | None, b: np.ndarray | None) -> float:
    """Distancia de Bhattacharyya en [0, 1]. 0 = misma apariencia."""
    if a is None or b is None or not a.any() or not b.any():
        return 1.0
    return float(cv2.compareHist(a, b, cv2.HISTCMP_BHATTACHARYYA))


def promedio(descs: list[np.ndarray | None]) -> np.ndarray | None:
    """Descriptor representativo de un tramo ocupado."""
    validos = [d for d in descs if d is not None and d.any()]
    if not validos:
        return None
    media = np.mean(validos, axis=0).astype(np.float32)
    total = media.sum()
    return media / total if total else media
