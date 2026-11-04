"""La pantalla de marcado: un candidato en bucle y una tecla que lo decide.

Es deliberadamente tonta. Reproduce el tramo del candidato una y otra vez sobre una
ventana de OpenCV -- la misma dependencia que ya usa el resto del motor -- y espera.
No intenta adivinar nada: quien mira decide si le lanzaron una pelota, que es lo que
el detector no sabe hacer.

Teclas:
  V / flecha arriba    vale: hubo pelota lanzada
  N / flecha abajo     no vale: swing de calentamiento, o nada
  espacio              dejarlo pendiente y seguir
  flecha izq / der     candidato anterior / siguiente
  A / S                mover el inicio del tramo 0,2 s atras / adelante
  K / L                mover el fin del tramo 0,2 s atras / adelante
  G                    guardar sin salir
  Q / ESC              guardar y salir
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .marcas import INVALIDO, SIN_DECIDIR, VALIDO, Cuaderno, Marca

VENTANA = "Marcar swings  ·  V vale  ·  N no vale  ·  Q guardar y salir"
PASO = 0.2              # s que mueve cada ajuste de limites
ANCHO_MAX = 1280        # la ventana no crece mas que esto

_COLORES = {VALIDO: (80, 220, 80), INVALIDO: (70, 70, 230), SIN_DECIDIR: (200, 200, 200)}
_ETIQUETAS = {VALIDO: "VALE", INVALIDO: "NO VALE", SIN_DECIDIR: "pendiente"}


class _Reproductor:
    """Fotogramas de un tramo, leidos una vez y reutilizados en el bucle."""

    def __init__(self, ruta: str) -> None:
        self.captura = cv2.VideoCapture(ruta)
        if not self.captura.isOpened():
            raise RuntimeError(f"No se pudo abrir {ruta}")
        self.fps = self.captura.get(cv2.CAP_PROP_FPS) or 30.0
        self._cache: dict[tuple[float, float], list[np.ndarray]] = {}

    def tramo(self, inicio: float, fin: float) -> list[np.ndarray]:
        clave = (round(inicio, 2), round(fin, 2))
        if clave in self._cache:
            return self._cache[clave]
        self.captura.set(cv2.CAP_PROP_POS_MSEC, max(0.0, inicio) * 1000)
        fotogramas = []
        while len(fotogramas) < int((fin - inicio) * self.fps) + 1:
            hay, fotograma = self.captura.read()
            if not hay:
                break
            fotogramas.append(fotograma)
        if len(self._cache) > 8:            # no acumular el turno entero en memoria
            self._cache.clear()
        self._cache[clave] = fotogramas
        return fotogramas

    def cerrar(self) -> None:
        self.captura.release()


def _hms(t: float) -> str:
    m, s = divmod(t, 60)
    return f"{int(m)}:{s:05.2f}"


def _pintar(fotograma: np.ndarray, marca: Marca, indice: int, total: int,
            cuaderno: Cuaderno) -> np.ndarray:
    lienzo = fotograma.copy()
    alto, ancho = lienzo.shape[:2]
    color = _COLORES[marca.estado]

    cv2.rectangle(lienzo, (0, 0), (ancho, 62), (0, 0, 0), -1)
    cv2.rectangle(lienzo, (0, alto - 34), (ancho, alto), (0, 0, 0), -1)
    cv2.rectangle(lienzo, (0, 0), (ancho - 1, alto - 1), color, 3)

    cv2.putText(lienzo, f"{indice + 1}/{total}", (14, 42),
                cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 2)
    cv2.putText(lienzo, _ETIQUETAS[marca.estado], (110, 42),
                cv2.FONT_HERSHEY_SIMPLEX, 1.1, color, 2)
    cv2.putText(lienzo, f"{_hms(marca.inicio)} - {_hms(marca.fin)}  ({marca.duracion:.1f}s)",
                (330, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (210, 210, 210), 1)
    cv2.putText(lienzo, cuaderno.resumen(), (14, alto - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (190, 190, 190), 1)
    return lienzo


def _escalar(fotograma: np.ndarray) -> np.ndarray:
    ancho = fotograma.shape[1]
    if ancho <= ANCHO_MAX:
        return fotograma
    factor = ANCHO_MAX / ancho
    return cv2.resize(fotograma, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)


def marcar(cuaderno: Cuaderno, destino: str | Path) -> Cuaderno:
    """Abre la ventana y no vuelve hasta que se cierra. Guarda al salir."""
    if not cuaderno.marcas:
        raise ValueError("El cuaderno no tiene ningun candidato que marcar")

    reproductor = _Reproductor(cuaderno.video)
    espera = max(1, int(1000 / reproductor.fps))
    indice = 0
    fotograma_actual = 0

    cv2.namedWindow(VENTANA, cv2.WINDOW_AUTOSIZE)
    try:
        while True:
            marca = cuaderno.marcas[indice]
            fotogramas = reproductor.tramo(marca.inicio, marca.fin)
            if not fotogramas:
                indice = min(indice + 1, len(cuaderno.marcas) - 1)
                continue

            fotograma_actual %= len(fotogramas)
            vista = _pintar(_escalar(fotogramas[fotograma_actual]), marca,
                            indice, len(cuaderno.marcas), cuaderno)
            cv2.imshow(VENTANA, vista)
            fotograma_actual += 1

            tecla = cv2.waitKey(espera) & 0xFF
            if tecla == 255:
                continue

            anterior = indice
            if tecla in (ord("q"), ord("Q"), 27):
                break
            elif tecla in (ord("v"), ord("V"), 82):        # 82 = flecha arriba
                marca.estado = VALIDO
                indice = min(indice + 1, len(cuaderno.marcas) - 1)
            elif tecla in (ord("n"), ord("N"), 84):        # 84 = flecha abajo
                marca.estado = INVALIDO
                indice = min(indice + 1, len(cuaderno.marcas) - 1)
            elif tecla == ord(" "):
                indice = min(indice + 1, len(cuaderno.marcas) - 1)
            elif tecla in (81, ord("p")):                  # 81 = flecha izquierda
                indice = max(indice - 1, 0)
            elif tecla in (83, ord("m")):                  # 83 = flecha derecha
                indice = min(indice + 1, len(cuaderno.marcas) - 1)
            elif tecla in (ord("a"), ord("A")):
                marca.inicio = max(0.0, marca.inicio - PASO)
            elif tecla in (ord("s"), ord("S")):
                marca.inicio = min(marca.inicio + PASO, marca.fin - PASO)
            elif tecla in (ord("k"), ord("K")):
                marca.fin = max(marca.fin - PASO, marca.inicio + PASO)
            elif tecla in (ord("l"), ord("L")):
                marca.fin += PASO
            elif tecla in (ord("g"), ord("G")):
                cuaderno.guardar(destino)

            if indice != anterior:
                fotograma_actual = 0
    finally:
        reproductor.cerrar()
        cv2.destroyAllWindows()

    cuaderno.guardar(destino)
    return cuaderno
