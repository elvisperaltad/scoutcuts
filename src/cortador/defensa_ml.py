"""Modelo pequeno que aprende a clasificar jugadas defensivas por su categoria
(adelante/derecha/izquierda) a partir de caracteristicas numericas del
movimiento -- nunca del video en si.

Por que existe: hoy defensa es 100% marcado manual porque nadie sabe
detectar la pelota de forma confiable en este material. Esto no resuelve
eso -- sigue siendo una persona quien decide DONDE esta cada jugada y si
es valida. Lo que aprende el modelo es algo mas chico y mas honesto: dado
que una persona ya marco una ventana de tiempo como una jugada completa de
una categoria, aprender a reconocer esa categoria a partir de COMO se
mueve (fuerza del pico, duracion, hacia que lado del encuadre) para que la
siguiente vez el sistema pueda proponerla solo, igual que ya hace con el
umbral fijo de bateo.

Privacidad: el modelo NUNCA guarda el video ni un fotograma. Solo guarda
tres numeros por ejemplo (duracion, fuerza del pico, posicion horizontal
del movimiento) y la categoria que una persona ya habia marcado. El video
se puede borrar inmediatamente despues de extraer esos tres numeros sin
perder nada que el modelo necesite.

Honestidad sobre el tamano del dato: con 1 o 2 videos marcados el modelo
es flojo a proposito -- `calibrar()` exige al menos un ejemplo de cada
categoria, pero la confianza que devuelve sera baja hasta que haya mas
ejemplos. Mejora de forma incremental: cada manifiesto `.defensa.json`
nuevo que llega AGREGA ejemplos al mismo dataset acumulado en vez de
empezar de cero.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from . import defensa as defensa_mod

VERSION = 1


def extraer_caracteristicas(ruta_video: str | Path, inicio: float, tiro: float) -> "Caracteristicas":
    """Lee los fotogramas de la ventana [inicio, tiro] y devuelve solo tres
    numeros: duracion, fuerza del pico de movimiento, y hacia que lado del
    encuadre se concentro ese movimiento (0.0 = borde izquierdo, 1.0 =
    borde derecho). Nunca retiene un fotograma ni una ruta de video mas
    alla de esta funcion: quien la llama puede borrar el video de inmediato
    despues sin perder nada que el modelo necesite.
    """
    import cv2
    import numpy as np

    captura = cv2.VideoCapture(str(ruta_video))
    if not captura.isOpened():
        raise RuntimeError(f"No se pudo abrir {ruta_video}")
    try:
        ancho = int(captura.get(cv2.CAP_PROP_FRAME_WIDTH))
        captura.set(cv2.CAP_PROP_POS_MSEC, inicio * 1000.0)

        anterior = None
        fuerza_pico = 0.0
        centro_ponderado = 0.0
        peso_total = 0.0
        while True:
            posicion = captura.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            if posicion > tiro:
                break
            hay, fotograma = captura.read()
            if not hay:
                break
            gris = cv2.cvtColor(fotograma, cv2.COLOR_BGR2GRAY).astype(np.int16)
            if anterior is not None:
                diferencia = np.abs(gris - anterior)
                fuerza = float(diferencia.mean())
                fuerza_pico = max(fuerza_pico, fuerza)
                peso_columna = diferencia.mean(axis=0).astype(np.float64)
                suma = float(peso_columna.sum())
                if suma > 0:
                    indices = np.arange(ancho, dtype=np.float64)
                    centro_ponderado += float((peso_columna * indices).sum())
                    peso_total += suma
            anterior = gris
    finally:
        captura.release()

    centro_x = (centro_ponderado / peso_total / max(ancho - 1, 1)) if peso_total > 0 else 0.5
    return Caracteristicas(
        duracion=max(tiro - inicio, 1e-6),
        fuerza_pico=fuerza_pico,
        centro_x=min(max(centro_x, 0.0), 1.0),
    )


@dataclass(frozen=True)
class Caracteristicas:
    """Tres numeros extraidos del movimiento en una ventana de tiempo.

    Nunca un pixel, nunca el video: solo lo que hace falta para reconocer
    la categoria la proxima vez.
    """

    duracion: float
    fuerza_pico: float
    centro_x: float  # 0.0 = borde izquierdo del ROI, 1.0 = borde derecho

    def __post_init__(self) -> None:
        if self.duracion <= 0:
            raise ValueError("duracion debe ser positiva")
        if self.fuerza_pico < 0:
            raise ValueError("fuerza_pico no puede ser negativa")
        if not (0.0 <= self.centro_x <= 1.0):
            raise ValueError("centro_x debe estar entre 0.0 y 1.0")


class CategoriaDesconocida(ValueError):
    pass


@dataclass
class Dataset:
    """Ejemplos acumulados por categoria. Persiste solo numeros."""

    ejemplos: dict[str, list[Caracteristicas]]

    @classmethod
    def vacio(cls) -> "Dataset":
        return cls(ejemplos={c: [] for c in defensa_mod.CATEGORIAS})

    def agregar(self, categoria: str, caracteristicas: Caracteristicas) -> None:
        if categoria not in defensa_mod.CATEGORIAS:
            raise CategoriaDesconocida(f"Categoria desconocida: {categoria}")
        self.ejemplos.setdefault(categoria, []).append(caracteristicas)

    def total_ejemplos(self) -> int:
        return sum(len(v) for v in self.ejemplos.values())

    def guardar(self, ruta: str | Path) -> None:
        destino = Path(ruta)
        destino.parent.mkdir(parents=True, exist_ok=True)
        datos = {
            "version": VERSION,
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
    def cargar(cls, ruta: str | Path) -> "Dataset":
        ruta = Path(ruta)
        if not ruta.exists():
            return cls.vacio()
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        ejemplos = {
            categoria: [Caracteristicas(**c) for c in lista]
            for categoria, lista in datos.get("ejemplos", {}).items()
        }
        for categoria in defensa_mod.CATEGORIAS:
            ejemplos.setdefault(categoria, [])
        return cls(ejemplos=ejemplos)


def _media_desviacion(valores: list[float]) -> tuple[float, float]:
    media = sum(valores) / len(valores)
    if len(valores) == 1:
        # Con un solo ejemplo no hay forma de medir dispersion real; se usa
        # una desviacion de reserva generosa para no sobre-confiar nunca en
        # un unico dato.
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
class ModeloDefensa:
    """Calibrado desde un Dataset: media y desviacion por categoria.

    Clasifica un ejemplo nuevo por la categoria cuyo perfil este mas cerca
    (distancia normalizada por la desviacion de cada caracteristica, el
    equivalente simple de una gaussiana naive). Nada de redes neuronales ni
    dependencias pesadas: con el tamano de dato que hay hoy (1-2 videos),
    un modelo mas complejo solo memorizaria ruido.
    """

    perfiles: dict[str, _PerfilCategoria]
    total_ejemplos: int

    @classmethod
    def calibrar(cls, dataset: Dataset) -> "ModeloDefensa":
        faltantes = [c for c in defensa_mod.CATEGORIAS if not dataset.ejemplos.get(c)]
        if faltantes:
            raise ValueError(
                "Faltan ejemplos para calibrar las categorias: "
                + ", ".join(faltantes)
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
        return cls(perfiles=perfiles, total_ejemplos=dataset.total_ejemplos())

    def _distancia(self, perfil: _PerfilCategoria, c: Caracteristicas) -> float:
        dz = (c.duracion - perfil.media_duracion) / perfil.desv_duracion
        fz = (c.fuerza_pico - perfil.media_fuerza) / perfil.desv_fuerza
        cz = (c.centro_x - perfil.media_centro_x) / perfil.desv_centro_x
        return math.sqrt(dz * dz + fz * fz + cz * cz)

    def clasificar(self, c: Caracteristicas) -> tuple[str, float]:
        """Devuelve (categoria_mas_probable, confianza entre 0.0 y 1.0).

        Confianza baja (cerca de 0) con poco dato o un ejemplo atipico es
        intencional: el sistema debe preferir marcar "revisar" en vez de
        inventar una categoria segura que no lo es.
        """
        distancias = {
            categoria: self._distancia(perfil, c)
            for categoria, perfil in self.perfiles.items()
        }
        mejor = min(distancias, key=lambda k: distancias[k])
        # Confianza: que tan lejos esta la segunda mejor opcion de la
        # elegida, normalizado. Si todas las categorias quedan igual de
        # cerca, la confianza cae a 0 en vez de elegir una al azar.
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
            "total_ejemplos": self.total_ejemplos,
            "perfiles": {c: asdict(p) for c, p in self.perfiles.items()},
        }
        destino.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def cargar(cls, ruta: str | Path) -> "ModeloDefensa":
        datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
        perfiles = {c: _PerfilCategoria(**p) for c, p in datos["perfiles"].items()}
        return cls(perfiles=perfiles, total_ejemplos=datos["total_ejemplos"])


def ruta_dataset_por_defecto() -> Path:
    """Junto al home del proyecto, nunca junto a un video especifico: el
    dataset acumula ejemplos de TODOS los videos marcados, no solo el
    ultimo."""
    return Path(__file__).resolve().parents[2] / "modelos" / "dataset_defensa.json"


def ruta_modelo_por_defecto() -> Path:
    return Path(__file__).resolve().parents[2] / "modelos" / "modelo_defensa.json"


def actualizar_desde_manifiesto(
    ruta_video: str | Path,
    manifiesto: "defensa_mod.Manifiesto",
    *,
    ruta_dataset: str | Path | None = None,
    ruta_modelo: str | Path | None = None,
) -> tuple[Dataset, ModeloDefensa | None]:
    """Extrae caracteristicas de las repeticiones ya elegidas por una persona
    en `manifiesto`, las agrega al dataset acumulado en disco, y recalibra
    el modelo si ya hay al menos un ejemplo de cada categoria.

    Debe llamarse ANTES de borrar `ruta_video`: a partir de aqui el video ya
    no hace falta para nada, solo los tres numeros por repeticion que ya
    quedaron extraidos y guardados.
    """
    ruta_dataset = Path(ruta_dataset) if ruta_dataset else ruta_dataset_por_defecto()
    ruta_modelo = Path(ruta_modelo) if ruta_modelo else ruta_modelo_por_defecto()

    dataset = Dataset.cargar(ruta_dataset)
    for repeticion in manifiesto.seleccionadas:
        caracteristicas = extraer_caracteristicas(
            ruta_video, repeticion.inicio, repeticion.tiro
        )
        dataset.agregar(repeticion.categoria, caracteristicas)
    dataset.guardar(ruta_dataset)

    modelo = None
    try:
        modelo = ModeloDefensa.calibrar(dataset)
    except ValueError:
        pass  # todavia falta al menos una categoria; se recalibrara despues
    if modelo is not None:
        modelo.guardar(ruta_modelo)
    return dataset, modelo
