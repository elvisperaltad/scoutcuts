"""Registro central de las disciplinas entrenables desde la zona web de QA.

Bateo reusa el vocabulario YA establecido para el marcado manual (ver
`marcas.py`: VALIDO/INVALIDO -- vale el swing si le lanzaron pelota).

Pitcheo y catcher NO tenian ninguna categoria definida por el cliente
todavia (ver CONTINUAR_SERVIDOR.md, punto 8): las de aqui son una PRIMERA
PROPUESTA razonable para que el QA pueda empezar a generar datos ya mismo,
no un criterio validado por el cliente. Son solo estas listas: si el
cliente define otro criterio, se ajustan aqui sin tocar nada mas del
sistema. El dataset viejo no se pierde, solo deja de alimentar al modelo
si cambian los nombres de categoria.
"""

from __future__ import annotations

DISCIPLINAS: dict[str, tuple[str, ...]] = {
    "defensa": ("adelante", "derecha", "izquierda"),
    "bateo": ("valido", "invalido"),
    "pitcheo": ("strike", "bola"),
    "catcher": ("recibido", "bloqueo", "tiro"),
}

NOMBRES_DISCIPLINA: dict[str, str] = {
    "defensa": "Defensa",
    "bateo": "Bateo",
    "pitcheo": "Pitcheo",
    "catcher": "Catcher",
}

NOMBRES_CATEGORIA: dict[str, str] = {
    "adelante": "Adelante",
    "derecha": "Derecha",
    "izquierda": "Izquierda",
    "valido": "Swing valido (le lanzaron pelota)",
    "invalido": "Swing invalido (calentamiento o sin pelota)",
    "strike": "Strike",
    "bola": "Bola",
    "recibido": "Recibido limpio",
    "bloqueo": "Bloqueo",
    "tiro": "Tiro a base",
}


class DisciplinaDesconocida(ValueError):
    pass


def categorias(disciplina: str) -> tuple[str, ...]:
    try:
        return DISCIPLINAS[disciplina]
    except KeyError:
        raise DisciplinaDesconocida(f"Disciplina desconocida: {disciplina}") from None


def nombre_disciplina(disciplina: str) -> str:
    return NOMBRES_DISCIPLINA.get(disciplina, disciplina)


def nombre_categoria(categoria: str) -> str:
    return NOMBRES_CATEGORIA.get(categoria, categoria)
