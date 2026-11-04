"""Zona de entrenamiento para el QA: sube videos de practica, los marca, y
recibe feedback inmediato del modelo mientras lo entrena.

Aislada de la PWA de produccion real: otra carpeta en disco, otro token,
nunca toca el Almacen/Cola de clientes reales (ver api.py, seccion
"Zona de entrenamiento QA"). El video de practica se borra automaticamente
despues de extraer sus caracteristicas para entrenar, igual que ya pasa con
el video de un cliente real tras entregarlo: una vez que el modelo aprendio
de el, el video deja de hacer falta.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from .. import defensa as defensa_mod
from .. import defensa_ml as defensa_ml_mod
from ..app import _EXTENSIONES_VIDEO

EXTENSIONES_PERMITIDAS = frozenset(_EXTENSIONES_VIDEO)
LIMITE_BYTES_POR_DEFECTO = 500 * 1024 * 1024
_LARGO_ID = 32

MENSAJE_SIN_VIDEO = "No subiste ningun video. Elige un video y vuelve a intentarlo."
MENSAJE_VIDEO_GRANDE = "Ese video pesa demasiado."
MENSAJE_FORMATO_NO_SOPORTADO = "Ese archivo no es un video que podamos procesar."
MENSAJE_NO_ENCONTRADO = "No encontramos ese video de practica."
MENSAJE_YA_ENTRENADO = "Este video de practica ya se uso para entrenar y ya no existe."


class VideoDePracticaNoEncontrado(LookupError):
    pass


class ArchivoDePracticaNoAceptado(ValueError):
    pass


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class VideoDePractica:
    """Un video que el QA subio a la zona de entrenamiento, antes de marcarlo.

    Vive un tiempo corto: desde que se sube hasta que el QA envia su
    manifiesto marcado (entrena y se borra) o hasta que vence la gracia de
    limpieza (se borra sin entrenar, para no acumular video de practica sin
    limite en disco).
    """

    id: str
    nombre: str
    extension: str
    creado: str = field(default_factory=lambda: _ahora().isoformat(timespec="seconds"))


@dataclass
class ResultadoEntrenamiento:
    """Lo que el QA ve de vuelta tras enviar su manifiesto marcado."""

    ejemplos_agregados: int
    total_ejemplos_dataset: int
    modelo_calibrado: bool
    categorias_cubiertas: list[str]
    categorias_faltantes: list[str]
    evaluacion: list[dict]


class ZonaEntrenamiento:
    """Almacen aislado para la zona de entrenamiento QA (nunca produccion)."""

    def __init__(self, raiz: str | Path, *,
                limite_bytes: int = LIMITE_BYTES_POR_DEFECTO,
                ruta_dataset: str | Path | None = None,
                ruta_modelo: str | Path | None = None) -> None:
        self.raiz = Path(raiz)
        self.limite_bytes = int(limite_bytes)
        self.ruta_dataset = (
            Path(ruta_dataset) if ruta_dataset else defensa_ml_mod.ruta_dataset_por_defecto()
        )
        self.ruta_modelo = (
            Path(ruta_modelo) if ruta_modelo else defensa_ml_mod.ruta_modelo_por_defecto()
        )
        self._cerrojo = threading.Lock()

    @property
    def _carpeta_videos(self) -> Path:
        return self.raiz / "videos"

    def _carpeta(self, identificador: str) -> Path:
        return self._carpeta_videos / self._validar_id(identificador)

    def _ruta_video(self, video: VideoDePractica) -> Path:
        return self._carpeta(video.id) / f"entrada{video.extension}"

    def _ruta_estado(self, identificador: str) -> Path:
        return self._carpeta(identificador) / "video.json"

    @staticmethod
    def _validar_id(identificador: object) -> str:
        texto = str(identificador or "")
        if len(texto) != _LARGO_ID or not texto.isalnum():
            raise VideoDePracticaNoEncontrado(MENSAJE_NO_ENCONTRADO)
        return texto

    def subir(self, nombre_archivo: str, flujo: BinaryIO, *,
              trozo: int = 1024 * 1024) -> VideoDePractica:
        """Guarda un video de practica nuevo; nunca lo asocia a un cliente real."""
        nombre = Path(str(nombre_archivo).replace("\\", "/")).name.strip()
        extension = Path(nombre).suffix.lower()
        if extension not in EXTENSIONES_PERMITIDAS:
            raise ArchivoDePracticaNoAceptado(MENSAJE_FORMATO_NO_SOPORTADO)
        video = VideoDePractica(id=uuid.uuid4().hex, nombre=nombre, extension=extension)
        carpeta = self._carpeta(video.id)
        carpeta.mkdir(parents=True, exist_ok=True)
        destino = self._ruta_video(video)
        temporal = destino.with_suffix(destino.suffix + ".tmp")
        escritos = 0
        try:
            with temporal.open("wb") as archivo:
                while True:
                    datos = flujo.read(trozo)
                    if not datos:
                        break
                    escritos += len(datos)
                    if escritos > self.limite_bytes:
                        raise ArchivoDePracticaNoAceptado(MENSAJE_VIDEO_GRANDE)
                    archivo.write(datos)
                archivo.flush()
                os.fsync(archivo.fileno())
            os.replace(temporal, destino)
        except BaseException:
            temporal.unlink(missing_ok=True)
            shutil.rmtree(carpeta, ignore_errors=True)
            raise
        self._guardar_estado(video)
        return video

    def _guardar_estado(self, video: VideoDePractica) -> None:
        destino = self._ruta_estado(video.id)
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporal = destino.with_suffix(".tmp")
        try:
            with temporal.open("w", encoding="utf-8") as archivo:
                json.dump(asdict(video), archivo, indent=2, ensure_ascii=False)
                archivo.flush()
                os.fsync(archivo.fileno())
            os.replace(temporal, destino)
        finally:
            temporal.unlink(missing_ok=True)

    def video(self, identificador: str) -> VideoDePractica:
        ruta = self._ruta_estado(identificador)
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            raise VideoDePracticaNoEncontrado(MENSAJE_NO_ENCONTRADO) from err
        conocidos = {campo for campo in VideoDePractica.__dataclass_fields__}
        return VideoDePractica(**{k: v for k, v in datos.items() if k in conocidos})

    def entrenar_con_manifiesto(self, identificador: str, repeticiones_crudas: object,
                                nombre_video_manifiesto: str) -> ResultadoEntrenamiento:
        """Valida las repeticiones marcadas, extrae caracteristicas de las
        que esten en estado 'completa', entrena, y BORRA el video de
        practica -- en ese orden, y antes de devolver nada al QA.

        A diferencia del manifiesto de entrega al cliente (`cortador
        defensa`, que exige exactamente 2+2+2 repeticiones para exportar un
        video final), aqui el QA puede marcar y enviar UNA sola repeticion
        a la vez: el objetivo es feedback inmediato por cada jugada que
        marca, no un paquete completo. Las repeticiones en estado
        'incompleta' se ignoran para entrenar, nunca fallan la peticion.

        El entrenamiento debe correr ANTES de borrar el video: es la unica
        razon para que exista el video en disco en primer lugar.
        """
        with self._cerrojo:
            video = self.video(identificador)
            ruta_video = self._ruta_video(video)
            if not ruta_video.exists():
                raise VideoDePracticaNoEncontrado(MENSAJE_YA_ENTRENADO)
            if os.path.normcase(Path(nombre_video_manifiesto).name) != os.path.normcase(video.nombre):
                raise ValueError(
                    "El manifiesto corresponde a otro video, no al que subiste."
                )
            repeticiones = defensa_mod.repeticiones_desde_lista(repeticiones_crudas)
            completas = tuple(r for r in repeticiones if r.estado == "completa")
            if not completas:
                raise ValueError(
                    "No hay ninguna repeticion marcada como 'completa' en lo que enviaste."
                )
            manifiesto = defensa_mod.Manifiesto(video.nombre, repeticiones, completas)

            dataset, modelo, extraidas = defensa_ml_mod.actualizar_desde_manifiesto(
                ruta_video, manifiesto,
                ruta_dataset=self.ruta_dataset, ruta_modelo=self.ruta_modelo,
            )

            # A partir de aqui el video ya no hace falta: se borro su carpeta
            # completa (video + estado), nunca solo el archivo de video.
            shutil.rmtree(self._carpeta(identificador), ignore_errors=True)

            evaluacion: list[dict] = []
            for categoria_real, caracteristicas in extraidas:
                fila: dict = {"categoria_marcada": categoria_real}
                if modelo is not None:
                    predicha, confianza = modelo.clasificar(caracteristicas)
                    fila["categoria_predicha"] = predicha
                    fila["confianza"] = round(confianza, 2)
                    fila["coincide"] = predicha == categoria_real
                else:
                    fila["categoria_predicha"] = None
                    fila["confianza"] = None
                    fila["coincide"] = None
                evaluacion.append(fila)
            faltantes = [
                c for c in defensa_mod.CATEGORIAS if not dataset.ejemplos.get(c)
            ]
            cubiertas = [c for c in defensa_mod.CATEGORIAS if c not in faltantes]
            return ResultadoEntrenamiento(
                ejemplos_agregados=len(completas),
                total_ejemplos_dataset=dataset.total_ejemplos(),
                modelo_calibrado=modelo is not None,
                categorias_cubiertas=cubiertas,
                categorias_faltantes=faltantes,
                evaluacion=evaluacion,
            )

    def limpiar_vencidos(self, max_edad_horas: float) -> list[str]:
        """Borra videos de practica subidos y nunca marcados (gracia corta).

        Sin esto, un QA que sube un video y nunca completa el marcado dejaria
        ese video acumulandose en disco para siempre -- la zona de
        entrenamiento tiene la misma regla de limpieza automatica que la
        produccion real, solo que aqui no hay "pendiente_revision": o se
        entrena y se borra, o vence la gracia y se borra igual.
        """
        from datetime import timedelta

        borrados: list[str] = []
        if not self._carpeta_videos.is_dir():
            return borrados
        limite = _ahora() - timedelta(hours=float(max_edad_horas))
        for carpeta in sorted(self._carpeta_videos.iterdir()):
            if not carpeta.is_dir():
                continue
            try:
                video = self.video(carpeta.name)
                creado = datetime.fromisoformat(video.creado)
                if creado.tzinfo is None:
                    creado = creado.replace(tzinfo=timezone.utc)
            except (VideoDePracticaNoEncontrado, ValueError, TypeError):
                try:
                    creado = datetime.fromtimestamp(carpeta.stat().st_mtime, timezone.utc)
                except OSError:
                    creado = _ahora()
            if creado < limite:
                shutil.rmtree(carpeta, ignore_errors=True)
                borrados.append(carpeta.name)
        return borrados


def estado_modelo(ruta_dataset: str | Path, ruta_modelo: str | Path) -> dict:
    """Resumen del estado del modelo para mostrar al QA: nunca expone rutas,
    perfiles numericos crudos ni nada que no sea una cuenta y una lista de
    categorias que ya puede o no puede reconocer todavia."""
    dataset = defensa_ml_mod.Dataset.cargar(ruta_dataset)
    conteos = {c: len(dataset.ejemplos.get(c, [])) for c in defensa_mod.CATEGORIAS}
    calibrado = Path(ruta_modelo).exists()
    return {
        "total_ejemplos": dataset.total_ejemplos(),
        "ejemplos_por_categoria": conteos,
        "modelo_calibrado": calibrado,
        "categorias": list(defensa_mod.CATEGORIAS),
    }
