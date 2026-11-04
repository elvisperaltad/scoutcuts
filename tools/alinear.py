"""Recupera, de un turno ya editado por el scout, que tramos del original conservo.

El scout entrega dos ficheros del mismo turno: el crudo y el montaje que el sabe que
quiere. Ese par es material etiquetado sin que nadie tenga que marcar nada: alineando
el montaje contra el crudo salen los tramos que el conservo, y con ellos se puede medir
cuanto se acerca el motor a lo que el hace a mano.

El metodo es correlacion de miniaturas. Cada fotograma se reduce a una rejilla pequena
en gris y se normaliza (media 0, norma 1); asi la comparacion no depende del brillo ni
del contraste, que cambian al recomprimir. Se recorta ademas un margen para que la
marca de agua de la app de edicion no pese en la medida.

Un tramo es un tramo de fotogramas del montaje cuyos mejores encajes en el crudo avanzan
de uno en uno. Donde el encaje da un salto, hubo un corte.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

REJILLA = (64, 36)     # ancho x alto de la miniatura
MARGEN = 0.08          # fraccion del fotograma que se recorta por cada lado
CORRELACION_MIN = 0.80  # por debajo, el fotograma no viene del crudo
BLOQUE = 512            # fotogramas de montaje por pasada, para acotar la memoria
SALTO_MAX = 2          # fotogramas de deriva tolerados dentro de un mismo tramo
TRAMO_MIN = 3          # fotogramas; por debajo es ruido de alineado
JUNTAR = 0.20          # s; dos tramos mas cerca que esto son en realidad uno


@dataclass(frozen=True)
class Tramo:
    """Un trozo del crudo que sobrevivio al montaje."""

    inicio: float
    fin: float
    correlacion: float

    @property
    def duracion(self) -> float:
        return self.fin - self.inicio


def firmas(ruta: str) -> tuple[np.ndarray, float]:
    """Miniatura normalizada de cada fotograma, como filas de una matriz."""
    captura = cv2.VideoCapture(ruta)
    if not captura.isOpened():
        raise RuntimeError(f"No se pudo abrir {ruta}")
    fps = captura.get(cv2.CAP_PROP_FPS)
    filas: list[np.ndarray] = []
    try:
        while True:
            hay, fotograma = captura.read()
            if not hay:
                break
            alto, ancho = fotograma.shape[:2]
            mx, my = int(ancho * MARGEN), int(alto * MARGEN)
            centro = fotograma[my : alto - my, mx : ancho - mx]
            mini = cv2.resize(cv2.cvtColor(centro, cv2.COLOR_BGR2GRAY), REJILLA,
                              interpolation=cv2.INTER_AREA).astype(np.float32).ravel()
            mini -= mini.mean()
            norma = np.linalg.norm(mini)
            filas.append(mini / norma if norma > 1e-6 else mini)
    finally:
        captura.release()
    if not filas:
        raise RuntimeError(f"{ruta} no tiene fotogramas legibles")
    return np.stack(filas), fps


def encajes(montaje: np.ndarray, crudo: np.ndarray,
            bloque: int = BLOQUE) -> tuple[np.ndarray, np.ndarray]:
    """Para cada fotograma del montaje, su mejor pareja en el crudo y cuanto se parecen.

    Con las firmas normalizadas el producto escalar ES la correlacion, asi que esto es
    un unico producto de matrices... cuyo tamano es el producto de las dos duraciones.
    Para un turno de dos minutos son megabytes; para una jornada de 3 h, 151 GB. Por eso
    el montaje se recorre por bloques: el resultado es identico y la memoria queda en
    `bloque x crudo` en vez de `montaje x crudo`.

    Se probo tambien seguir la continuidad -- tras encajar el fotograma i, mirar solo el
    siguiente del crudo-- que seria O(montaje) en vez de O(montaje x crudo). No sirve con
    esta camara: al estar fija y la escena casi quieta, un fotograma cualquiera correlaciona
    0,9998 con el vecino del sitio equivocado, exactamente igual que con el correcto. No
    hay umbral que separe un corte de una continuacion, y el alineado deriva. Medido.
    """
    indices = np.empty(len(montaje), dtype=np.int64)
    correlaciones = np.empty(len(montaje), dtype=np.float32)
    for desde in range(0, len(montaje), bloque):
        trozo = montaje[desde : desde + bloque]
        producto = trozo @ crudo.T
        mejores = producto.argmax(axis=1)
        indices[desde : desde + len(trozo)] = mejores
        correlaciones[desde : desde + len(trozo)] = producto[np.arange(len(trozo)), mejores]
    return indices, correlaciones


def coste(n_crudo: int, n_montaje: int) -> tuple[float, float]:
    """Memoria (MB) de las firmas del crudo y del bloque mas grande."""
    dims = REJILLA[0] * REJILLA[1]
    return n_crudo * dims * 4 / 1e6, min(BLOQUE, n_montaje) * n_crudo * 4 / 1e6


def tramos(indices: np.ndarray, correlaciones: np.ndarray, fps: float) -> list[Tramo]:
    """Agrupa los encajes en tramos continuos del crudo."""
    encontrados: list[Tramo] = []
    grupo: list[int] = []

    def cerrar() -> None:
        if len(grupo) < TRAMO_MIN:
            return
        primero, ultimo = indices[grupo[0]], indices[grupo[-1]]
        encontrados.append(Tramo(
            inicio=round(float(primero) / fps, 2),
            fin=round(float(ultimo + 1) / fps, 2),
            correlacion=round(float(np.mean(correlaciones[grupo])), 3),
        ))

    for i, (j, c) in enumerate(zip(indices, correlaciones)):
        if c < CORRELACION_MIN:
            cerrar()
            grupo = []
            continue
        if grupo and not (0 < j - indices[grupo[-1]] <= SALTO_MAX):
            cerrar()
            grupo = []
        grupo.append(i)
    cerrar()
    return encontrados


def juntar(encontrados: list[Tramo], holgura: float = JUNTAR) -> list[Tramo]:
    """Une los tramos que en realidad son uno solo.

    Dentro de un plano quieto hay fotogramas casi identicos, y el mejor encaje puede
    retroceder un fotograma o saltar dos. Eso parte un tramo continuo en trozos que se
    tocan o incluso se solapan. Aqui se vuelven a pegar.
    """
    if not encontrados:
        return []
    unidos = [encontrados[0]]
    for t in encontrados[1:]:
        previo = unidos[-1]
        if t.inicio - previo.fin <= holgura:
            peso_previo, peso_nuevo = previo.duracion, t.duracion
            total = peso_previo + peso_nuevo
            unidos[-1] = Tramo(
                inicio=previo.inicio,
                fin=max(previo.fin, t.fin),
                correlacion=round((previo.correlacion * peso_previo
                                   + t.correlacion * peso_nuevo) / total, 3) if total else 0.0,
            )
        else:
            unidos.append(t)
    return unidos


def alinear(ruta_crudo: str, ruta_montaje: str) -> tuple[list[Tramo], float, float]:
    firmas_crudo, fps_crudo = firmas(ruta_crudo)
    firmas_montaje, _ = firmas(ruta_montaje)
    if firmas_crudo.shape[1] != firmas_montaje.shape[1]:
        raise RuntimeError("Los dos videos no tienen la misma forma de fotograma")
    firmas_mb, bloque_mb = coste(len(firmas_crudo), len(firmas_montaje))
    if firmas_mb + bloque_mb > 1500:
        print(f"  aviso: el crudo dura {len(firmas_crudo) / fps_crudo / 60:.0f} min y hara"
              f" falta ~{firmas_mb + bloque_mb:.0f} MB de memoria.")
        print("  Esta herramienta esta pensada para pares de UN turno (minutos), no para"
              " jornadas enteras.")
    indices, correlaciones = encajes(firmas_montaje, firmas_crudo)
    return (juntar(tramos(indices, correlaciones, fps_crudo)),
            len(firmas_crudo) / fps_crudo,
            float(np.mean(correlaciones)))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("crudo", help="el turno tal como se grabo")
    p.add_argument("montaje", help="el turno ya editado por el scout")
    p.add_argument("--salida", help="JSON donde escribir los tramos")
    args = p.parse_args()

    encontrados, duracion, media = alinear(args.crudo, args.montaje)
    total = sum(t.duracion for t in encontrados)

    print(f"\n  {Path(args.crudo).name}  ->  {Path(args.montaje).name}")
    print(f"  correlacion media {media:.3f}\n")
    print("    #   del crudo          dura   corr")
    for n, t in enumerate(encontrados, 1):
        print(f"   {n:2d}   {t.inicio:6.2f}-{t.fin:6.2f}  {t.duracion:6.2f}s  {t.correlacion:.3f}")
    descartado = (1 - total / duracion) * 100 if duracion else 0
    print(f"\n  {len(encontrados)} tramos, {total:.1f}s de {duracion:.1f}s "
          f"-- el scout descarta el {descartado:.0f}%")

    if args.salida:
        Path(args.salida).write_text(json.dumps({
            "crudo": args.crudo,
            "montaje": args.montaje,
            "duracion": round(duracion, 2),
            "tramos": [{"inicio": t.inicio, "fin": t.fin, "correlacion": t.correlacion}
                       for t in encontrados],
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  -> {args.salida}")


if __name__ == "__main__":
    main()
