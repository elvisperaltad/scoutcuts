"""Las marcas: que swing valio y cual no, puestas por una persona.

Existe porque el criterio del cliente -- vale el swing solo si le lanzaron una
pelota -- no es hoy detectable en el material disponible: a 1024x576 y 915 kbps la
pelota mide unos 5 px en la zona de vuelo, la malla de la jaula se interpone y el
audio llega mudo. Hasta que haya material que lo permita, lo pone una persona.

El fichero de marcas no es solo un paso intermedio para exportar: es el material
etiquetado con el que despues se podra ajustar un detector automatico. Por eso
guarda tambien la fuerza del pico y el motivo, no unicamente el si o el no.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .eventos import Candidato

VALIDO = "valido"          # hubo pelota lanzada
INVALIDO = "invalido"      # swing de calentamiento, o nada
SIN_DECIDIR = "pendiente"

ESTADOS = (VALIDO, INVALIDO, SIN_DECIDIR)


@dataclass
class Marca:
    inicio: float
    fin: float
    instante: float             # el pico que la origino
    estado: str = SIN_DECIDIR
    fuerza: float = 0.0
    nota: str = ""

    def __post_init__(self) -> None:
        if self.estado not in ESTADOS:
            raise ValueError(f"Estado desconocido: {self.estado}")
        if self.fin <= self.inicio:
            raise ValueError("El tramo de una marca no puede estar vacio")

    @property
    def duracion(self) -> float:
        return self.fin - self.inicio


@dataclass
class Cuaderno:
    """Todas las marcas de un turno, con la trazabilidad de donde salieron."""

    video: str
    marcas: list[Marca] = field(default_factory=list)
    creado: str = ""
    perfil: str = ""

    @classmethod
    def desde_candidatos(cls, video: str, candidatos: list[Candidato],
                         antes: float, despues: float, perfil: str = "") -> "Cuaderno":
        marcas = []
        for c in candidatos:
            inicio, fin = c.tramo(antes, despues)
            marcas.append(Marca(inicio=inicio, fin=fin, instante=c.instante, fuerza=c.fuerza))
        return cls(video=video, marcas=marcas, perfil=perfil)

    @property
    def validas(self) -> list[Marca]:
        return [m for m in self.marcas if m.estado == VALIDO]

    @property
    def pendientes(self) -> list[Marca]:
        return [m for m in self.marcas if m.estado == SIN_DECIDIR]

    def resumen(self) -> str:
        v = sum(1 for m in self.marcas if m.estado == VALIDO)
        i = sum(1 for m in self.marcas if m.estado == INVALIDO)
        p = len(self.marcas) - v - i
        return f"{len(self.marcas)} candidatos: {v} validos, {i} descartados, {p} sin decidir"

    def guardar(self, ruta: str | Path) -> None:
        """Escribe a un temporal y reemplaza al final: un fallo deja el anterior."""
        destino = Path(ruta)
        destino.parent.mkdir(parents=True, exist_ok=True)
        datos = asdict(self)
        datos["creado"] = self.creado or datetime.now(timezone.utc).isoformat(timespec="seconds")
        texto = json.dumps(datos, indent=2, ensure_ascii=False)
        temporal = destino.with_name(destino.name + ".tmp")
        try:
            with temporal.open("w", encoding="utf-8") as archivo:
                archivo.write(texto)
                archivo.flush()
                os.fsync(archivo.fileno())
            os.replace(temporal, destino)
        finally:
            if temporal.exists():
                temporal.unlink()

    @classmethod
    def cargar(cls, ruta: str | Path) -> "Cuaderno":
        datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
        marcas = [Marca(**m) for m in datos.pop("marcas", [])]
        return cls(marcas=marcas, **datos)


def fundir(cuaderno: Cuaderno, separacion: float = 0.0) -> list[tuple[float, float]]:
    """Tramos validos, en orden y sin solaparse.

    Dos marcas validas que se tocan (o que quedan a menos de `separacion`) salen como
    un solo tramo: cortar entre ellas produciria un salto donde no lo hay.
    """
    tramos = sorted((m.inicio, m.fin) for m in cuaderno.validas)
    if not tramos:
        return []
    fundidos = [list(tramos[0])]
    for inicio, fin in tramos[1:]:
        if inicio - fundidos[-1][1] <= separacion:
            fundidos[-1][1] = max(fundidos[-1][1], fin)
        else:
            fundidos.append([inicio, fin])
    return [(a, b) for a, b in fundidos]
