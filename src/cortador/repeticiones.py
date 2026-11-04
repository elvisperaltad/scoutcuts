"""Validacion generica de repeticiones marcadas a mano: categoria, ventana
de tiempo, y si quedo completa. Comun a las disciplinas entrenables (ver
`disciplinas.py`) -- cada una trae su propia lista de categorias validas,
pero la validacion de forma es identica.

`cortador.defensa` reexporta estas mismas piezas con su lista de
categorias fija (compatibilidad con el manifiesto `.defensa.json` que ya
usa `cortador defensa` en produccion); este modulo es la version generica
que usa la zona de entrenamiento web para las demas disciplinas.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

ESTADOS = ("completa", "incompleta")


@dataclass(frozen=True)
class Repeticion:
    categoria: str
    inicio: float
    tiro: float
    estado: str
    seleccionada: bool | None = None


def _numero(valor: object, campo: str) -> float:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ValueError(f"'{campo}' debe ser un numero")
    numero = float(valor)
    if not math.isfinite(numero):
        raise ValueError(f"'{campo}' debe ser finito")
    return numero


def _repeticion(datos: object, indice: int, categorias: tuple[str, ...]) -> Repeticion:
    if not isinstance(datos, dict):
        raise ValueError(f"La repeticion {indice} debe ser un objeto")
    categoria = datos.get("categoria")
    estado = datos.get("estado")
    if categoria not in categorias:
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


def repeticiones_desde_lista(crudas: object, categorias: tuple[str, ...]) -> tuple[Repeticion, ...]:
    """Convierte una lista de objetos sin validar en repeticiones ya validadas,
    contra el conjunto de categorias de una disciplina especifica."""
    if not isinstance(crudas, list):
        raise ValueError("'repeticiones' debe ser una lista")
    return tuple(_repeticion(valor, i, categorias) for i, valor in enumerate(crudas, start=1))
