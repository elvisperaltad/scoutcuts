"""Extraccion de caracteristicas numericas del movimiento, compartida por
las cuatro disciplinas entrenables (bateo, defensa, pitcheo, catcher).

Nunca lee ni guarda el video mas alla de esta funcion: quien la llama puede
borrar el video de inmediato despues sin perder nada que un modelo pequeno
necesite para aprender. Ver `ml_generico.py` para como se usa esto para
entrenar, y `defensa_ml.py` para el modelo especifico de defensa que ya
corre en produccion desde el comando `cortador defensa`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def extraer_caracteristicas(ruta_video: str | Path, inicio: float, tiro: float) -> "Caracteristicas":
    """Lee los fotogramas de la ventana [inicio, tiro] y devuelve solo tres
    numeros: duracion, fuerza del pico de movimiento, y hacia que lado del
    encuadre se concentro ese movimiento (0.0 = borde izquierdo, 1.0 =
    borde derecho). Nunca retiene un fotograma ni una ruta de video mas
    alla de esta funcion: quien la llama puede borrar el video de inmediato
    despues sin perder nada que el modelo necesite.
    """
    import cv2
    import numpy as np

    captura = cv2.VideoCapture(str(ruta_video))
    if not captura.isOpened():
        raise RuntimeError(f"No se pudo abrir {ruta_video}")
    try:
        ancho = int(captura.get(cv2.CAP_PROP_FRAME_WIDTH))
        captura.set(cv2.CAP_PROP_POS_MSEC, inicio * 1000.0)

        anterior = None
        fuerza_pico = 0.0
        centro_ponderado = 0.0
        peso_total = 0.0
        while True:
            posicion = captura.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            if posicion > tiro:
                break
            hay, fotograma = captura.read()
            if not hay:
                break
            gris = cv2.cvtColor(fotograma, cv2.COLOR_BGR2GRAY).astype(np.int16)
            if anterior is not None:
                diferencia = np.abs(gris - anterior)
                fuerza = float(diferencia.mean())
                fuerza_pico = max(fuerza_pico, fuerza)
                peso_columna = diferencia.mean(axis=0).astype(np.float64)
                suma = float(peso_columna.sum())
                if suma > 0:
                    indices = np.arange(ancho, dtype=np.float64)
                    centro_ponderado += float((peso_columna * indices).sum())
                    peso_total += suma
            anterior = gris
    finally:
        captura.release()

    centro_x = (centro_ponderado / peso_total / max(ancho - 1, 1)) if peso_total > 0 else 0.5
    return Caracteristicas(
        duracion=max(tiro - inicio, 1e-6),
        fuerza_pico=fuerza_pico,
        centro_x=min(max(centro_x, 0.0), 1.0),
    )


@dataclass(frozen=True)
class Caracteristicas:
    """Tres numeros extraidos del movimiento en una ventana de tiempo.

    Nunca un pixel, nunca el video: solo lo que hace falta para reconocer
    la categoria la proxima vez.
    """

    duracion: float
    fuerza_pico: float
    centro_x: float  # 0.0 = borde izquierdo del ROI, 1.0 = borde derecho

    def __post_init__(self) -> None:
        if self.duracion <= 0:
            raise ValueError("duracion debe ser positiva")
        if self.fuerza_pico < 0:
            raise ValueError("fuerza_pico no puede ser negativa")
        if not (0.0 <= self.centro_x <= 1.0):
            raise ValueError("centro_x debe estar entre 0.0 y 1.0")
