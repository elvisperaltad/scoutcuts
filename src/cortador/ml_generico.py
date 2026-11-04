"""Modelo pequeno, generico para cualquier disciplina entrenable (ver
`disciplinas.py`): aprende a clasificar una repeticion marcada por su
categoria a partir de tres caracteristicas numericas del movimiento --
nunca del video en si. La misma idea que ya corre en produccion para
defensa (`defensa_ml.py`, usado por `cortador defensa`), generalizada para
que la zona de entrenamiento web pueda ofrecer bateo, pitcheo y catcher
sin duplicar la logica por cada una.

Privacidad: igual que `defensa_ml.py` -- nunca se guarda el video ni un
fotograma, solo tres numeros por ejemplo y la categoria ya marcada por una
persona. El video se puede borrar de inmediato despues de extraer esos
numeros sin perder nada que el modelo necesite.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from . import disciplinas as disciplinas_mod
from .movimiento import Caracteristicas, extraer_caracteristicas

VERSION = 1

__all__ = [
    "Caracteristicas", "extraer_caracteristicas", "Dataset", "Modelo",
    "ruta_dataset_por_defecto", "ruta_modelo_por_defecto",
    "actualizar_desde_repeticiones",
]


class CategoriaDesconocida(ValueError):
    pass


@dataclass
class Dataset:
    """Ejemplos acumulados por categoria, para UNA disciplina. Persiste
    solo numeros, nunca video."""

    disciplina: str
    ejemplos: dict[str, list[Caracteristicas]]

    @classmethod
    def vacio(cls, disciplina: str) -> "Dataset":
        return cls(disciplina=disciplina,
                    ejemplos={c: [] for c in disciplinas_mod.categorias(disciplina)})

    def agregar(self, categoria: str, caracteristicas: Caracteristicas) -> None:
        if categoria not in disciplinas_mod.categorias(self.disciplina):
            raise CategoriaDesconocida(f"Categoria desconocida: {categoria}")
        self.ejemplos.setdefault(categoria, []).append(caracteristicas)

    def total_ejemplos(self) -> int:
        return sum(len(v) for v in self.ejemplos.values())

    def guardar(self, ruta: str | Path) -> None:
        destino = Path(ruta)
        destino.parent.mkdir(parents=True, exist_ok=True)
        datos = {
            "version": VERSION,
            "disciplina": self.disciplina,
            "ejemplos": {
                categoria: [asdict(c) for c in lista]
                for categoria, lista in self.ejemplos.items()
            },
        }
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
    def cargar(cls, ruta: str | Path, disciplina: str) -> "Dataset":
        ruta = Path(ruta)
        if not ruta.exists():
            return cls.vacio(disciplina)
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        ejemplos = {
            categoria: [Caracteristicas(**c) for c in lista]
            for categoria, lista in datos.get("ejemplos", {}).items()
        }
        for categoria in disciplinas_mod.categorias(disciplina):
            ejemplos.setdefault(categoria, [])
        return cls(disciplina=disciplina, ejemplos=ejemplos)


def _media_desviacion(valores: list[float]) -> tuple[float, float]:
    media = sum(valores) / len(valores)
    if len(valores) == 1:
        return media, max(abs(media) * 0.5, 1e-6)
    varianza = sum((v - media) ** 2 for v in valores) / (len(valores) - 1)
    desviacion = math.sqrt(varianza)
    return media, max(desviacion, 1e-6)


@dataclass(frozen=True)
class _PerfilCategoria:
    media_duracion: float
    desv_duracion: float
    media_fuerza: float
    desv_fuerza: float
    media_centro_x: float
    desv_centro_x: float
    n_ejemplos: int


@dataclass
class Modelo:
    """Calibrado desde un Dataset de una disciplina: media y desviacion por
    categoria. Mismo clasificador simple (distancia normalizada, el
    equivalente de una gaussiana naive) que `defensa_ml.ModeloDefensa` --
    nada de redes neuronales: con el tamano de dato que hay hoy, algo mas
    complejo memorizaria ruido en vez de aprender un patron."""

    disciplina: str
    perfiles: dict[str, _PerfilCategoria]
    total_ejemplos: int

    @classmethod
    def calibrar(cls, dataset: Dataset) -> "Modelo":
        categorias = disciplinas_mod.categorias(dataset.disciplina)
        faltantes = [c for c in categorias if not dataset.ejemplos.get(c)]
        if faltantes:
            raise ValueError(
                "Faltan ejemplos para calibrar las categorias: " + ", ".join(faltantes)
            )
        perfiles: dict[str, _PerfilCategoria] = {}
        for categoria, ejemplos in dataset.ejemplos.items():
            if not ejemplos:
                continue
            duraciones = [e.duracion for e in ejemplos]
            fuerzas = [e.fuerza_pico for e in ejemplos]
            centros = [e.centro_x for e in ejemplos]
            md, dd = _media_desviacion(duraciones)
            mf, df = _media_desviacion(fuerzas)
            mc, dc = _media_desviacion(centros)
            perfiles[categoria] = _PerfilCategoria(
                media_duracion=md, desv_duracion=dd,
                media_fuerza=mf, desv_fuerza=df,
                media_centro_x=mc, desv_centro_x=dc,
                n_ejemplos=len(ejemplos),
            )
        return cls(disciplina=dataset.disciplina, perfiles=perfiles,
                   total_ejemplos=dataset.total_ejemplos())

    def _distancia(self, perfil: _PerfilCategoria, c: Caracteristicas) -> float:
        dz = (c.duracion - perfil.media_duracion) / perfil.desv_duracion
        fz = (c.fuerza_pico - perfil.media_fuerza) / perfil.desv_fuerza
        cz = (c.centro_x - perfil.media_centro_x) / perfil.desv_centro_x
        return math.sqrt(dz * dz + fz * fz + cz * cz)

    def clasificar(self, c: Caracteristicas) -> tuple[str, float]:
        """Devuelve (categoria_mas_probable, confianza entre 0.0 y 1.0).

        Confianza baja con poco dato o un ejemplo atipico es intencional:
        prefiere marcar duda en vez de inventar una categoria segura."""
        distancias = {
            categoria: self._distancia(perfil, c)
            for categoria, perfil in self.perfiles.items()
        }
        mejor = min(distancias, key=lambda k: distancias[k])
        ordenadas = sorted(distancias.values())
        mejor_d, segunda_d = ordenadas[0], ordenadas[1] if len(ordenadas) > 1 else ordenadas[0]
        total = mejor_d + segunda_d
        confianza = 0.0 if total == 0 else max(0.0, (segunda_d - mejor_d) / total)
        return mejor, confianza

    def guardar(self, ruta: str | Path) -> None:
        destino = Path(ruta)
        destino.parent.mkdir(parents=True, exist_ok=True)
        datos = {
            "version": VERSION,
            "disciplina": self.disciplina,
            "total_ejemplos": self.total_ejemplos,
            "perfiles": {c: asdict(p) for c, p in self.perfiles.items()},
        }
        destino.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def cargar(cls, ruta: str | Path) -> "Modelo":
        datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
        perfiles = {c: _PerfilCategoria(**p) for c, p in datos["perfiles"].items()}
        return cls(disciplina=datos.get("disciplina", ""), perfiles=perfiles,
                   total_ejemplos=datos["total_ejemplos"])


def ruta_dataset_por_defecto(disciplina: str) -> Path:
    """Junto al home del proyecto, un archivo por disciplina: cada una
    acumula ejemplos de TODOS los videos marcados de esa disciplina, nunca
    solo del ultimo."""
    return Path(__file__).resolve().parents[2] / "modelos" / f"dataset_{disciplina}.json"


def ruta_modelo_por_defecto(disciplina: str) -> Path:
    return Path(__file__).resolve().parents[2] / "modelos" / f"modelo_{disciplina}.json"


def actualizar_desde_repeticiones(
    ruta_video: str | Path,
    disciplina: str,
    repeticiones: "tuple",
    *,
    ruta_dataset: str | Path | None = None,
    ruta_modelo: str | Path | None = None,
) -> tuple[Dataset, Modelo | None, list[tuple[str, Caracteristicas]]]:
    """Extrae caracteristicas de las repeticiones ya marcadas por una
    persona (de `cortador.repeticiones.Repeticion`), las agrega al dataset
    acumulado de esa disciplina, y recalibra el modelo si ya hay al menos
    un ejemplo de cada categoria.

    Debe llamarse ANTES de borrar `ruta_video`: a partir de aqui el video
    ya no hace falta, solo los tres numeros por repeticion que quedaron
    extraidos y guardados."""
    ruta_dataset = Path(ruta_dataset) if ruta_dataset else ruta_dataset_por_defecto(disciplina)
    ruta_modelo = Path(ruta_modelo) if ruta_modelo else ruta_modelo_por_defecto(disciplina)

    dataset = Dataset.cargar(ruta_dataset, disciplina)
    extraidas: list[tuple[str, Caracteristicas]] = []
    for repeticion in repeticiones:
        caracteristicas = extraer_caracteristicas(ruta_video, repeticion.inicio, repeticion.tiro)
        dataset.agregar(repeticion.categoria, caracteristicas)
        extraidas.append((repeticion.categoria, caracteristicas))
    dataset.guardar(ruta_dataset)

    modelo = None
    try:
        modelo = Modelo.calibrar(dataset)
    except ValueError:
        pass  # todavia falta al menos una categoria; se recalibrara despues
    if modelo is not None:
        modelo.guardar(ruta_modelo)
    return dataset, modelo, extraidas
