"""Selección humana revisada de repeticiones defensivas.

No intenta detectar la pelota ni inferir la dirección. Solo valida un manifiesto
hecho por una persona y convierte sus seis repeticiones elegidas en tramos.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

VERSION = 1
CATEGORIAS = ("adelante", "derecha", "izquierda")
ESTADOS = ("completa", "incompleta")
ANTES_EXTRA = 2.0
DESPUES_TIRO = 0.3


@dataclass(frozen=True)
class Repeticion:
    categoria: str
    inicio: float
    tiro: float
    estado: str
    seleccionada: bool | None = None


@dataclass(frozen=True)
class Manifiesto:
    video: str
    repeticiones: tuple[Repeticion, ...]
    seleccionadas: tuple[Repeticion, ...]


def _numero(valor: object, campo: str) -> float:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ValueError(f"'{campo}' debe ser un numero")
    numero = float(valor)
    if not math.isfinite(numero):
        raise ValueError(f"'{campo}' debe ser finito")
    return numero


def _repeticion(datos: object, indice: int) -> Repeticion:
    if not isinstance(datos, dict):
        raise ValueError(f"La repeticion {indice} debe ser un objeto")
    categoria = datos.get("categoria")
    estado = datos.get("estado")
    if categoria not in CATEGORIAS:
        raise ValueError(f"Categoria invalida en la repeticion {indice}: {categoria}")
    if estado not in ESTADOS:
        raise ValueError(f"Estado invalido en la repeticion {indice}: {estado}")
    inicio = _numero(datos.get("inicio"), "inicio")
    tiro = _numero(datos.get("tiro"), "tiro")
    if inicio < 0 or tiro <= inicio:
        raise ValueError(
            f"Tiempos invalidos en la repeticion {indice}: inicio={inicio}, tiro={tiro}"
        )
    seleccionada = datos.get("seleccionada")
    if seleccionada is not None and not isinstance(seleccionada, bool):
        raise ValueError("'seleccionada' debe ser true o false")
    return Repeticion(categoria, inicio, tiro, estado, seleccionada)


def repeticiones_desde_lista(crudas: object) -> tuple[Repeticion, ...]:
    """Convierte una lista de objetos sin validar en repeticiones ya validadas.

    Compartido por `cargar` (manifiesto en disco) y por el endpoint web de
    entrenamiento (manifiesto recibido como JSON en el cuerpo del POST): la
    validacion de cada repeticion es identica en ambos casos, solo cambia de
    donde vienen los datos crudos.
    """
    if not isinstance(crudas, list):
        raise ValueError("'repeticiones' debe ser una lista")
    return tuple(_repeticion(valor, i) for i, valor in enumerate(crudas, start=1))


def seleccionar(repeticiones: tuple[Repeticion, ...]) -> tuple[Repeticion, ...]:
    """De las repeticiones ya validadas, elige las 2+2+2 que se exportan.

    Misma regla en ambos flujos: con exactamente 2 completas de una
    categoria se usan esas 2; con mas de 2, hace falta marcar 'seleccionada'
    en exactamente 2.
    """
    elegidas: list[Repeticion] = []
    for categoria in CATEGORIAS:
        completas = [r for r in repeticiones
                     if r.categoria == categoria and r.estado == "completa"]
        if len(completas) < 2:
            raise ValueError(f"Faltan repeticiones completas de la categoria {categoria}")
        if len(completas) == 2:
            seleccion = completas
        else:
            seleccion = [r for r in completas if r.seleccionada is True]
            if len(seleccion) != 2:
                raise ValueError(
                    f"Hay {len(completas)} completas de {categoria}: la seleccion debe "
                    "marcar exactamente dos con 'seleccionada': true"
                )
        elegidas.extend(seleccion)
    elegidas.sort(key=lambda repeticion: repeticion.inicio)
    return tuple(elegidas)


def cargar(ruta: str | Path, video: str | Path) -> Manifiesto:
    """Carga y valida un manifiesto v1 correspondiente al video indicado."""
    datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    if not isinstance(datos, dict):
        raise ValueError("El manifiesto debe ser un objeto JSON")
    if datos.get("version") != VERSION:
        raise ValueError(f"La version del manifiesto no es compatible; se requiere {VERSION}")
    video_manifestado = datos.get("video")
    if not isinstance(video_manifestado, str) or not video_manifestado:
        raise ValueError("El manifiesto no indica un video valido")
    if os.path.normcase(Path(video_manifestado).name) != os.path.normcase(Path(video).name):
        raise ValueError(
            f"El manifiesto corresponde a otro video ({video_manifestado}), no a {Path(video).name}"
        )
    repeticiones = repeticiones_desde_lista(datos.get("repeticiones"))
    elegidas = seleccionar(repeticiones)
    return Manifiesto(video_manifestado, repeticiones, elegidas)


def tramos_exportables(manifiesto: Manifiesto, antes_extra: float = ANTES_EXTRA,
                       despues_tiro: float = DESPUES_TIRO) -> list[tuple[float, float]]:
    """Devuelve los seis tramos elegidos, con márgenes y en orden cronológico."""
    antes = _numero(antes_extra, "antes_extra")
    despues = _numero(despues_tiro, "despues_tiro")
    if antes < 0 or despues < 0:
        raise ValueError("Los margenes de defensa no pueden ser negativos")
    return [
        (max(0.0, repeticion.inicio - antes), repeticion.tiro + despues)
        for repeticion in manifiesto.seleccionadas
    ]
