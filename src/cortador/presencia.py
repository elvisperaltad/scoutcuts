"""Etapa 2: hay alguien en el cajon?

Implementacion base con OpenCV puro: modelo de fondo del recorte y fraccion de pixeles
que se apartan de el.

La comparacion es en color, canal a canal, no en luminancia. Un uniforme puede tener
exactamente el mismo brillo que la tierra del cajon y seguir siendo perfectamente
visible; en luminancia ese pelotero desaparece.

El fondo se estima en dos pasadas. La primera mediana temporal ya se acerca (cada
pelotero aporta colores distintos, asi que ninguno domina), pero en un cajon muy ocupado
arrastra color de pelotero. La segunda rehace la mediana usando solo los recortes mas
quietos respecto a esa primera estimacion, que son los del cajon vacio.

El diseno acordado contempla sustituir esto por YOLOv8n restringido al recorte cuando
lleguen los dos videos reales; la interfaz (una serie de ocupacion por instante) no cambia.
"""

from __future__ import annotations

import numpy as np

MAX_FONDO = 400          # recortes que se usan para estimar el fondo
UMBRAL_PIXEL = 28        # diferencia de color (canal mas dispar) que cuenta como frente
UMBRAL_OCUPADO = 0.06    # fraccion del ROI que hay que cubrir para considerarlo ocupado
PERCENTIL_VACIO = 30     # % de recortes mas quietos que se toman como cajon vacio


def _submuestra(imagenes: np.ndarray, maximo: int) -> np.ndarray:
    if len(imagenes) <= maximo:
        return imagenes
    return imagenes[np.linspace(0, len(imagenes) - 1, maximo).astype(int)]


def diferencia(imagenes: np.ndarray, fondo: np.ndarray) -> np.ndarray:
    """Distancia al fondo por pixel: el canal mas dispar. Forma (n, alto, ancho)."""
    if imagenes.ndim == 3:
        imagenes = imagenes[None]
    return np.abs(imagenes.astype(np.float32) - fondo[None]).max(axis=3)


def estimar_fondo(imagenes: np.ndarray, maximo: int = MAX_FONDO,
                  umbral_pixel: int = UMBRAL_PIXEL) -> np.ndarray:
    """Recorte del cajon vacio, en RGB. Forma (alto, ancho, 3)."""
    if len(imagenes) == 0:
        raise ValueError("No hay imagenes para estimar el fondo")

    seleccion = _submuestra(imagenes, maximo).astype(np.float32)
    fondo = np.median(seleccion, axis=0)

    actividad = (diferencia(seleccion, fondo) > umbral_pixel).mean(axis=(1, 2))
    corte = np.percentile(actividad, PERCENTIL_VACIO)
    quietos = seleccion[actividad <= corte]
    if len(quietos) >= 3:
        fondo = np.median(quietos, axis=0)
    return fondo


def mascara_frente(imagen: np.ndarray, fondo: np.ndarray,
                   umbral_pixel: int = UMBRAL_PIXEL) -> np.ndarray:
    """Silueta de lo que no es fondo, como uint8 0/255 (lo que espera OpenCV)."""
    return ((diferencia(imagen, fondo)[0] > umbral_pixel) * 255).astype(np.uint8)


def serie_ocupacion(imagenes: np.ndarray, umbral_pixel: int = UMBRAL_PIXEL,
                    fondo: np.ndarray | None = None) -> np.ndarray:
    """Fraccion del ROI distinta del fondo, por recorte. Valores en [0, 1]."""
    if fondo is None:
        fondo = estimar_fondo(imagenes, umbral_pixel=umbral_pixel)
    return (diferencia(imagenes, fondo) > umbral_pixel).mean(axis=(1, 2))


def ocupado(imagenes: np.ndarray, umbral_ocupado: float = UMBRAL_OCUPADO,
            umbral_pixel: int = UMBRAL_PIXEL,
            fondo: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Devuelve (mascara booleana de ocupacion, serie continua) para depurar umbrales."""
    serie = serie_ocupacion(imagenes, umbral_pixel=umbral_pixel, fondo=fondo)
    return serie >= umbral_ocupado, serie
