"""Etapa 2, version del diseno: detector de personas restringido al recorte.

Mismo contrato que `presencia`: una serie de ocupacion por instante. Aqui la serie es
la confianza de la mejor deteccion de persona dentro del recorte, y ademas se devuelve
la caja, que la etapa de identidad aprovecha para mirar solo al pelotero.

Es preferible al detector por color cuando el fondo no es estable (sombras que giran a
lo largo de la tarde, gente al fondo, la camara que vibra con el viento): YOLO no
depende de que el cajon vacio se parezca a si mismo.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

MODELO = "yolov8n.pt"
UMBRAL_CONF = 0.35
CLASE_PERSONA = 0
LOTE = 32


@dataclass
class Deteccion:
    confianza: float
    caja: tuple[int, int, int, int] | None  # x0, y0, x1, y1 dentro del recorte


class DetectorPersonas:
    def __init__(self, modelo: str = MODELO, umbral_conf: float = UMBRAL_CONF,
                 lote: int = LOTE) -> None:
        from ultralytics import YOLO  # import perezoso: torch tarda en cargar

        self.red = YOLO(modelo)
        self.umbral_conf = umbral_conf
        self.lote = lote

    def detectar(self, imagenes: np.ndarray) -> list[Deteccion]:
        """Una deteccion por recorte: la persona mas segura, o confianza 0."""
        salida: list[Deteccion] = []
        for inicio in range(0, len(imagenes), self.lote):
            trozo = imagenes[inicio : inicio + self.lote]
            # ultralytics espera BGR cuando se le pasan arrays, como OpenCV.
            lote_bgr = [img[:, :, ::-1] for img in trozo]
            for resultado in self.red.predict(
                lote_bgr, classes=[CLASE_PERSONA], conf=self.umbral_conf,
                verbose=False, device="cpu",
            ):
                salida.append(_mejor(resultado))
        return salida


def _mejor(resultado) -> Deteccion:
    cajas = resultado.boxes
    if cajas is None or len(cajas) == 0:
        return Deteccion(confianza=0.0, caja=None)
    confianzas = cajas.conf.cpu().numpy()
    i = int(np.argmax(confianzas))
    x0, y0, x1, y1 = cajas.xyxy[i].cpu().numpy().astype(int)
    return Deteccion(confianza=float(confianzas[i]), caja=(int(x0), int(y0), int(x1), int(y1)))


def ocupado(imagenes: np.ndarray, umbral_conf: float = UMBRAL_CONF,
            modelo: str = MODELO) -> tuple[np.ndarray, np.ndarray, list[tuple | None]]:
    """(mascara de ocupacion, serie de confianza, caja por recorte)."""
    detecciones = DetectorPersonas(modelo=modelo, umbral_conf=umbral_conf).detectar(imagenes)
    serie = np.array([d.confianza for d in detecciones], dtype=np.float32)
    cajas = [d.caja for d in detecciones]
    return serie >= umbral_conf, serie, cajas
