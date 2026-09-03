"""Etapa 3, version del diseno: embedding de apariencia del torso.

El histograma de color de `identidad` distingue bien uniformes de colores distintos,
pero se queda corto con personas reales vestidas de forma parecida: en la jornada de
prueba dos peloteros distintos quedaban a 0,32, por debajo del umbral de cambio, y el
motor los fusionaba en un solo turno.

Aqui el descriptor es el vector de caracteristicas de una ResNet-18 preentrenada,
recortada al torso. No es un modelo de re-identificacion (OSNet o CLIP, que es lo que
contempla el diseno), pero separa personas mucho mejor que el color y no necesita nada
mas de lo ya instalado.

Se combina con el histograma: la CNN aporta la forma y la textura, el histograma el
color del uniforme, que en beisbol es informacion util y no ruido.
"""

from __future__ import annotations

import numpy as np

from . import identidad

ENTRADA = 128           # lado al que se escala el torso antes de la red
PESO_COLOR = 0.35       # cuanto pesa el histograma frente a la CNN
UMBRAL_CAMBIO = 0.06    # ver tools/calibrar_umbral.py: mismo pelotero <= 0,011; distintos >= 0,107

Caja = tuple[int, int, int, int]


class EmbeddingTorso:
    """Extractor de caracteristicas. Cargar una vez y reutilizar: la red tarda en abrir."""

    def __init__(self, entrada: int = ENTRADA) -> None:
        import torch
        import torchvision

        self.torch = torch
        self.entrada = entrada
        pesos = torchvision.models.ResNet18_Weights.IMAGENET1K_V1
        red = torchvision.models.resnet18(weights=pesos)
        red.fc = torch.nn.Identity()  # nos quedamos con el vector de 512
        self.red = red.eval()
        self.normalizar = pesos.transforms()

    def _torso(self, imagen: np.ndarray, caja: Caja | None) -> np.ndarray:
        alto, ancho = imagen.shape[:2]
        if caja is None:
            return imagen
        x0, y0, x1, y1 = caja
        alto_caja = max(1, y1 - y0)
        ty0 = int(np.clip(y0 + identidad.TORSO[0] * alto_caja, 0, alto - 1))
        ty1 = int(np.clip(y0 + identidad.TORSO[1] * alto_caja, ty0 + 1, alto))
        tx0 = int(np.clip(x0, 0, ancho - 1))
        tx1 = int(np.clip(x1, tx0 + 1, ancho))
        return imagen[ty0:ty1, tx0:tx1]

    def __call__(self, imagenes: list[np.ndarray], cajas: list[Caja | None]) -> list[np.ndarray]:
        import cv2

        torch = self.torch
        lote = []
        for imagen, caja in zip(imagenes, cajas):
            torso = self._torso(imagen, caja)
            if torso.size == 0:
                torso = imagen
            torso = cv2.resize(torso, (self.entrada, self.entrada), interpolation=cv2.INTER_AREA)
            lote.append(torch.from_numpy(np.ascontiguousarray(torso)).permute(2, 0, 1))

        tensor = torch.stack(lote)
        with torch.no_grad():
            salida = self.red(self.normalizar(tensor))
        salida = torch.nn.functional.normalize(salida, dim=1)
        return [v.numpy().astype(np.float32) for v in salida]


def descriptores(imagenes: np.ndarray, fondo: np.ndarray | None,
                 mascara_ocupado: np.ndarray, cajas: list[Caja | None] | None = None,
                 lote: int = 32) -> list[np.ndarray | None]:
    """Un descriptor por recorte ocupado; None donde el cajon esta vacio.

    El vector es la concatenacion del embedding de la CNN y el histograma de color,
    cada uno con su peso, para que una sola distancia coseno mire las dos cosas.
    """
    indices = [i for i, hay_alguien in enumerate(mascara_ocupado) if hay_alguien]
    salida: list[np.ndarray | None] = [None] * len(imagenes)
    if not indices:
        return salida

    extractor = EmbeddingTorso()
    for inicio in range(0, len(indices), lote):
        trozo = indices[inicio : inicio + lote]
        recortes = [imagenes[i] for i in trozo]
        cajas_trozo = [cajas[i] if cajas is not None else None for i in trozo]
        vectores = extractor(recortes, cajas_trozo)
        for i, vector, imagen, caja in zip(trozo, vectores, recortes, cajas_trozo):
            color = identidad.descriptor(imagen, fondo, caja=caja)
            norma = np.linalg.norm(color)
            color = (color / norma) if norma else color
            salida[i] = np.concatenate([vector, PESO_COLOR * color]).astype(np.float32)
    return salida


def distancia(a: np.ndarray | None, b: np.ndarray | None) -> float:
    """Distancia coseno reescalada a [0, 1]. 0 = misma persona."""
    if a is None or b is None or not a.any() or not b.any():
        return 1.0
    coseno = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
    return float(np.clip((1.0 - coseno) / 2.0, 0.0, 1.0))


def promedio(descs: list[np.ndarray | None]) -> np.ndarray | None:
    validos = [d for d in descs if d is not None and d.any()]
    if not validos:
        return None
    media = np.mean(validos, axis=0).astype(np.float32)
    norma = np.linalg.norm(media)
    return media / norma if norma else media
