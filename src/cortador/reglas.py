"""Etapa 4a: de la serie de ocupacion a los turnos.

Todas las reglas son deterministas y ajustables a mano. Son estas cuatro las que
deciden la calidad del resultado, no el detector:

1. El pelotero sale y vuelve  -> fusionar si vuelve la misma apariencia antes de 25 s.
2. Dos peloteros se relevan sin hueco -> partir donde salta la apariencia.
3. Zurdos y diestros -> resuelto en la calibracion, con un ROI que cubre los dos cajones.
4. Entrenadores cruzando el cuadro -> descartar lo que dure menos de 20 s.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field, replace
from typing import Callable, Sequence

import numpy as np

from . import identidad

Descriptor = np.ndarray | None


@dataclass(frozen=True)
class Ajustes:
    gap_fusion: float = 25.0        # hueco maximo que se fusiona si vuelve el mismo
    min_duracion: float = 20.0      # por debajo de esto es alguien cruzando, no un turno
    umbral_cambio: float = identidad.UMBRAL_CAMBIO
    colchon: float = 2.0            # segundos de margen a cada lado
    ventana_cambio: int = 3         # recortes a cada lado al buscar el relevo sin hueco
    min_separacion_cambio: float = 15.0  # no partir dos veces casi seguidas


@dataclass
class Segmento:
    inicio: float
    fin: float
    descriptor: Descriptor = None
    muestras: int = 0
    notas: list[str] = field(default_factory=list)

    @property
    def duracion(self) -> float:
        return self.fin - self.inicio


def _fin_de_muestra(tiempos: Sequence[float], i: int) -> float:
    """Instante en que deja de valer la muestra i (el inicio de la siguiente)."""
    if i + 1 < len(tiempos):
        return tiempos[i + 1]
    if len(tiempos) >= 2:
        return tiempos[i] + (tiempos[-1] - tiempos[0]) / (len(tiempos) - 1)
    return tiempos[i]


def agrupar(tiempos: Sequence[float], ocupado: Sequence[bool]) -> list[tuple[int, int]]:
    """Tramos [i, j] de muestras consecutivas ocupadas."""
    tramos: list[tuple[int, int]] = []
    inicio: int | None = None
    for i, hay_alguien in enumerate(ocupado):
        if hay_alguien and inicio is None:
            inicio = i
        elif not hay_alguien and inicio is not None:
            tramos.append((inicio, i - 1))
            inicio = None
    if inicio is not None:
        tramos.append((inicio, len(ocupado) - 1))
    return tramos


def partir_por_apariencia(
    tramo: tuple[int, int],
    tiempos: Sequence[float],
    descs: Sequence[Descriptor],
    ajustes: Ajustes,
    dist: Callable[[Descriptor, Descriptor], float] = identidad.distancia,
) -> list[tuple[int, int]]:
    """Caso 2: uno sale mientras el otro ya entra y el cajon nunca queda vacio.

    El limite lo marca el salto en la apariencia, no el hueco.
    """
    i, j = tramo
    k = ajustes.ventana_cambio
    if j - i + 1 < 2 * k:
        return [tramo]

    cortes: list[int] = []
    for c in range(i + k, j - k + 2):
        antes = identidad.promedio(list(descs[c - k : c]))
        despues = identidad.promedio(list(descs[c : c + k]))
        if dist(antes, despues) <= ajustes.umbral_cambio:
            continue
        if cortes and tiempos[c] - tiempos[cortes[-1]] < ajustes.min_separacion_cambio:
            continue
        cortes.append(c)

    partes: list[tuple[int, int]] = []
    anterior = i
    for c in cortes:
        partes.append((anterior, c - 1))
        anterior = c
    partes.append((anterior, j))
    return partes


def fusionar(segmentos: list[Segmento], ajustes: Ajustes,
             dist: Callable[[Descriptor, Descriptor], float] = identidad.distancia) -> list[Segmento]:
    """Caso 1: el pelotero se ajusta el guante y vuelve. Un turno, no dos clips."""
    if not segmentos:
        return []
    salida = [segmentos[0]]
    for actual in segmentos[1:]:
        previo = salida[-1]
        hueco = actual.inicio - previo.fin
        mismo = dist(previo.descriptor, actual.descriptor) <= ajustes.umbral_cambio
        if 0 <= hueco <= ajustes.gap_fusion and mismo:
            salida[-1] = Segmento(
                inicio=previo.inicio,
                fin=actual.fin,
                descriptor=identidad.promedio([previo.descriptor, actual.descriptor]),
                muestras=previo.muestras + actual.muestras,
                notas=previo.notas + [f"fusionado (hueco {hueco:.0f} s)"],
            )
        else:
            salida.append(actual)
    return salida


def descartar_cortos(segmentos: list[Segmento], ajustes: Ajustes) -> list[Segmento]:
    """Caso 4: un entrenador cruzando el cuadro no es un turno."""
    return [s for s in segmentos if s.duracion >= ajustes.min_duracion]


def aplicar_colchon(segmentos: list[Segmento], ajustes: Ajustes, duracion: float) -> list[Segmento]:
    return [
        replace(s, inicio=max(0.0, s.inicio - ajustes.colchon), fin=min(duracion, s.fin + ajustes.colchon))
        for s in segmentos
    ]


def ajustar_a_keyframes(segmentos: list[Segmento], keyframes: Sequence[float],
                        duracion: float) -> list[Segmento]:
    """Siempre hacia fuera: keyframe anterior al inicio y posterior al final.

    Nunca se pierde metraje; como mucho sobra un segundo por lado.
    """
    if not keyframes:
        return segmentos
    salida = []
    for s in segmentos:
        idx = bisect_right(keyframes, s.inicio) - 1
        inicio = keyframes[max(0, idx)]
        idx = bisect_left(keyframes, s.fin)
        fin = keyframes[idx] if idx < len(keyframes) else duracion
        salida.append(replace(s, inicio=inicio, fin=max(fin, inicio)))
    return salida


def segmentar(
    tiempos: Sequence[float],
    ocupado: Sequence[bool],
    descs: Sequence[Descriptor],
    keyframes: Sequence[float],
    duracion: float,
    ajustes: Ajustes | None = None,
    dist: Callable[[Descriptor, Descriptor], float] = identidad.distancia,
) -> list[Segmento]:
    ajustes = ajustes or Ajustes()

    segmentos: list[Segmento] = []
    for tramo in agrupar(tiempos, ocupado):
        for i, j in partir_por_apariencia(tramo, tiempos, descs, ajustes, dist):
            segmentos.append(Segmento(
                inicio=tiempos[i],
                fin=_fin_de_muestra(tiempos, j),
                descriptor=identidad.promedio(list(descs[i : j + 1])),
                muestras=j - i + 1,
            ))

    segmentos = fusionar(segmentos, ajustes, dist)
    segmentos = descartar_cortos(segmentos, ajustes)
    segmentos = aplicar_colchon(segmentos, ajustes, duracion)
    segmentos = ajustar_a_keyframes(segmentos, keyframes, duracion)
    return segmentos
