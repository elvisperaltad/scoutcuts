"""Etapa 3: apariencia del pelotero que ocupa el cajon.

Separa a dos peloteros que se relevan sin dejar hueco y reconoce al mismo cuando
vuelve tras salirse a ajustarse el guante.

Implementacion base: histograma HS (tono y saturacion) del pelotero. La region que se
mira depende de lo que aporte la etapa 2: si el detector devolvio una caja, se usa el
torso de esa caja, que es donde esta el uniforme; si no, se usa todo lo que difiera del
fondo. Es un descriptor pobre pero determinista y sin dependencias pesadas. El diseno
acordado contempla sustituirlo por OSNet o CLIP; lo unico que consume el resto del
motor es `distancia`.
"""

from __future__ import annotations

import cv2
import numpy as np

from .presencia import UMBRAL_PIXEL, mascara_frente

BINS_H = 24
BINS_S = 8
# Por encima de esta distancia se consideran dos peloteros distintos.
UMBRAL_CAMBIO = 0.35
# Franja de la caja que se considera torso, en fracciones de su alto.
TORSO = (0.15, 0.60)

Caja = tuple[int, int, int, int]


def _mascara_torso(forma: tuple[int, int], caja: Caja) -> np.ndarray:
    alto, ancho = forma
    x0, y0, x1, y1 = caja
    alto_caja = max(1, y1 - y0)
    ty0 = int(np.clip(y0 + TORSO[0] * alto_caja, 0, alto - 1))
    ty1 = int(np.clip(y0 + TORSO[1] * alto_caja, ty0 + 1, alto))
    tx0 = int(np.clip(x0, 0, ancho - 1))
    tx1 = int(np.clip(x1, tx0 + 1, ancho))
    mascara = np.zeros(forma, dtype=np.uint8)
    mascara[ty0:ty1, tx0:tx1] = 255
    return mascara


def descriptor(imagen: np.ndarray, fondo: np.ndarray | None = None,
               umbral_pixel: int = UMBRAL_PIXEL, caja: Caja | None = None) -> np.ndarray:
    """Histograma HS normalizado del pelotero."""
    if caja is not None:
        mascara = _mascara_torso(imagen.shape[:2], caja)
    elif fondo is not None:
        mascara = mascara_frente(imagen, fondo, umbral_pixel)
    else:
        raise ValueError("Hace falta una caja o un fondo para aislar al pelotero")

    if not mascara.any():
        return np.zeros(BINS_H * BINS_S, dtype=np.float32)

    hsv = cv2.cvtColor(imagen, cv2.COLOR_RGB2HSV)
    hist = cv2.calcHist([hsv], [0, 1], mascara, [BINS_H, BINS_S], [0, 180, 0, 256])
    cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
    return hist.flatten().astype(np.float32)


def descriptores(imagenes: np.ndarray, fondo: np.ndarray | None,
                 mascara_ocupado: np.ndarray,
                 cajas: list[Caja | None] | None = None) -> list[np.ndarray | None]:
    """Un descriptor por recorte ocupado; None donde el cajon esta vacio."""
    salida: list[np.ndarray | None] = []
    for i, (imagen, hay_alguien) in enumerate(zip(imagenes, mascara_ocupado)):
        if not hay_alguien:
            salida.append(None)
            continue
        caja = cajas[i] if cajas is not None else None
        salida.append(descriptor(imagen, fondo, caja=caja))
    return salida


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
