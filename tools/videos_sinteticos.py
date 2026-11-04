"""Helpers de video sintetico para pruebas de defensa, compartidos entre
`tests/test_defensa_ml.py` y `tests/servidor/test_entrenamiento.py`.

Vive en `tools/` (ya en sys.path via tests/conftest.py) para evitar la
ambiguedad de nombres entre los dos `conftest.py` del arbol de pruebas
(raiz y tests/servidor/), que Python no puede distinguir al importarlos
por nombre simple sin que `tests/` sea un paquete real.
"""

from __future__ import annotations

import pytest


def crear_video_con_movimiento_lateral(ruta, lado: str, fps: float = 20.0,
                                        ancho: int = 320, alto: int = 240,
                                        segundos: float = 2.0):
    """Video sintetico real (sin ffmpeg: OpenCV puede escribirlo y leerlo
    directamente) con un cuadrado blanco moviendose de un lado al otro del
    encuadre, para probar codigo de defensa contra fotogramas reales, no
    datos inventados a mano."""
    import cv2
    import numpy as np

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    escritor = cv2.VideoWriter(str(ruta), fourcc, fps, (ancho, alto))
    n_fotogramas = int(segundos * fps)
    x_inicio, x_fin = (20, 20) if lado == "quieto" else (
        (ancho - 60, 20) if lado == "izquierda" else (20, ancho - 60)
    )
    for i in range(n_fotogramas):
        frame = np.zeros((alto, ancho, 3), dtype=np.uint8)
        t = i / max(n_fotogramas - 1, 1)
        x = int(x_inicio + (x_fin - x_inicio) * t)
        frame[90:150, x:x + 40] = 255
        escritor.write(frame)
    escritor.release()


@pytest.fixture
def cv2_disponible():
    try:
        import cv2  # noqa: F401
    except ImportError:
        pytest.skip("opencv no esta instalado en este entorno")
