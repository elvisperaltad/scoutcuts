"""Almacenamiento en disco de los trabajos subidos al servidor.

Un trabajo es una carpeta con identificador opaco. Nunca se usa el nombre del
archivo del scout como ruta: ese nombre puede traer su nombre propio, el del
jugador o una ruta completa de su telefono.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO, Iterator

from ..app import _EXTENSIONES_VIDEO
from ..qa import _texto_seguro

EXTENSIONES_PERMITIDAS = frozenset(_EXTENSIONES_VIDEO)

RECIBIDO = "recibido"
EN_COLA = "en_cola"
PROCESANDO = "procesando"
LISTO = "listo"
PENDIENTE_REVISION = "pendiente_revision"
ERROR = "error"

ESTADOS = (RECIBIDO, EN_COLA, PROCESANDO, LISTO, PENDIENTE_REVISION, ERROR)

LIMITE_POR_DEFECTO = 500 * 1024 * 1024

_LARGO_ID = 32


class ArchivoNoAceptado(ValueError):
    """El archivo subido no se puede procesar; el mensaje es para el scout."""


class TrabajoDesconocido(LookupError):
    """No existe un trabajo con ese identificador."""


def depurar_texto(valor: object) -> str:
    """Quita rutas y nombres de usuario, conservando el nombre del archivo."""
    return _texto_seguro(valor)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _sello() -> str:
    return _ahora().isoformat(timespec="seconds")


@dataclass
class Trabajo:
    """Estado completo de un video subido, tal como se guarda en disco."""

    id: str
    nombre: str
    extension: str
    tamano_bytes: int = 0
    estado: str = RECIBIDO
    mensaje: str = ""
    detalle: str = ""
    candidatos: int = 0
    validos: int = 0
    duracion: float = 0.0
    descargado: bool = False
    propietario: str = ""
    verificacion: bool = False
    creado: str = field(default_factory=_sello)
    actualizado: str = field(default_factory=_sello)


class Almacen:
    """Carpeta raiz con un subdirectorio por trabajo."""

    def __init__(self, raiz: str | Path, *, limite_bytes: int = LIMITE_POR_DEFECTO) -> None:
        self.raiz = Path(raiz)
        self.limite_bytes = int(limite_bytes)

    @property
    def trabajos(self) -> Path:
        return self.raiz / "trabajos"

    def carpeta(self, identificador: str) -> Path:
        return self.trabajos / self._validar_id(identificador)

    def ruta_entrada(self, trabajo: Trabajo) -> Path:
        return self.carpeta(trabajo.id) / f"entrada{trabajo.extension}"

    def ruta_resultado(self, trabajo: Trabajo) -> Path:
        return self.carpeta(trabajo.id) / "resultado.mp4"

    def ruta_marcas(self, trabajo: Trabajo) -> Path:
        return self.carpeta(trabajo.id) / "marcas.json"

    def _ruta_estado(self, identificador: str) -> Path:
        return self.carpeta(identificador) / "estado.json"

    @staticmethod
    def _validar_id(identificador: object) -> str:
        texto = str(identificador or "")
        if len(texto) != _LARGO_ID or not texto.isalnum():
            raise TrabajoDesconocido("No encontramos ese trabajo.")
        return texto

    def crear(self, nombre_archivo: str, tamano_bytes: int = 0,
             *, propietario: str = "", verificacion: bool = False) -> Trabajo:
        """Reserva la carpeta del trabajo tras validar nombre y tamano.

        `propietario` es opcional y queda vacio por defecto (compatibilidad
        con la API HTTP publica, que no tiene usuarios). El bot de Telegram
        lo usa para guardar el telegram_id de quien subio el video, y asi
        poder avisarle cuando el trabajo termine.

        `verificacion` marca las sondas del E2E de despliegue: nadie las va
        a revisar, asi que no deben recibir la gracia extendida de purgar().
        """
        nombre = Path(str(nombre_archivo).replace("\\", "/")).name.strip()
        extension = Path(nombre).suffix.lower()
        if extension not in EXTENSIONES_PERMITIDAS:
            aceptadas = ", ".join(sorted(e.lstrip(".") for e in EXTENSIONES_PERMITIDAS))
            raise ArchivoNoAceptado(
                "Ese archivo no es un video que podamos procesar. "
                f"Sube un video en formato {aceptadas}."
            )
        if int(tamano_bytes or 0) > self.limite_bytes:
            raise ArchivoNoAceptado(
                "El video es demasiado grande. El limite es "
                f"{self.limite_bytes // (1024 * 1024)} MB."
            )
        trabajo = Trabajo(
            id=uuid.uuid4().hex,
            nombre=nombre,
            extension=extension,
            tamano_bytes=int(tamano_bytes or 0),
            propietario=str(propietario or ""),
            verificacion=bool(verificacion),
        )
        self.carpeta(trabajo.id).mkdir(parents=True, exist_ok=True)
        self.guardar_estado(trabajo)
        return trabajo

    def guardar_entrada(self, trabajo: Trabajo, flujo: BinaryIO,
                        *, trozo: int = 1024 * 1024) -> int:
        """Copia el video subido a disco cortando si supera el limite."""
        destino = self.ruta_entrada(trabajo)
        destino.parent.mkdir(parents=True, exist_ok=True)
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
                        raise ArchivoNoAceptado(
                            "El video es demasiado grande. El limite es "
                            f"{self.limite_bytes // (1024 * 1024)} MB."
                        )
                    archivo.write(datos)
                archivo.flush()
                os.fsync(archivo.fileno())
            os.replace(temporal, destino)
        except BaseException:
            temporal.unlink(missing_ok=True)
            destino.unlink(missing_ok=True)
            raise
        trabajo.tamano_bytes = escritos
        self.guardar_estado(trabajo)
        return escritos

    def guardar_estado(self, trabajo: Trabajo) -> Path:
        """Escribe estado.json de forma atomica."""
        trabajo.actualizado = _sello()
        destino = self._ruta_estado(trabajo.id)
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporal = destino.with_suffix(".tmp")
        try:
            with temporal.open("w", encoding="utf-8") as archivo:
                json.dump(asdict(trabajo), archivo, indent=2, ensure_ascii=False)
                archivo.flush()
                os.fsync(archivo.fileno())
            os.replace(temporal, destino)
        finally:
            temporal.unlink(missing_ok=True)
        return destino

    def estado(self, identificador: str) -> Trabajo:
        ruta = self._ruta_estado(identificador)
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            raise TrabajoDesconocido("No encontramos ese trabajo.") from err
        conocidos = {campo for campo in Trabajo.__dataclass_fields__}
        return Trabajo(**{k: v for k, v in datos.items() if k in conocidos})

    def trabajos_de(self, propietario: str) -> list[Trabajo]:
        """Todos los trabajos de ese propietario (p. ej. un telegram_id).

        Usado por /estado del bot de Telegram para listar los trabajos
        recientes de un scout sin tener que preguntar por cada id.
        """
        if not self.trabajos.is_dir():
            return []
        resultado = []
        for carpeta in sorted(self.trabajos.iterdir()):
            if not carpeta.is_dir():
                continue
            try:
                trabajo = self.estado(carpeta.name)
            except TrabajoDesconocido:
                continue
            if trabajo.propietario == str(propietario or ""):
                resultado.append(trabajo)
        return resultado

    def marcar_descargado(self, trabajo: Trabajo) -> Trabajo:
        """El scout ya tiene su montaje: el video original deja de hacer falta."""
        trabajo.descargado = True
        self.ruta_entrada(trabajo).unlink(missing_ok=True)
        self.guardar_estado(trabajo)
        return trabajo

    def purgar(self, max_edad_horas: float, *,
              max_edad_revision_horas: float | None = None) -> Iterator[str]:
        """Borra trabajos vencidos y las entradas ya entregadas.

        `max_edad_revision_horas` da una gracia extendida solo a los
        trabajos en `PENDIENTE_REVISION`: son videos (p. ej. defensa,
        pitcheo o catcher subidos por la web, que todavia no tienen
        deteccion automatica) que un humano aun no ha revisado. Sin esto,
        la purga normal de privacidad los borraria en 24h junto con el
        resto, perdiendo material que nadie llego a ver. Si no se pasa
        (compatibilidad con la API publica y el bot, que llaman a purgar
        sin este parametro), pendiente_revision usa el mismo limite que
        cualquier otro estado.
        """
        if not self.trabajos.is_dir():
            return
        limite = _ahora() - timedelta(hours=float(max_edad_horas))
        limite_revision = (
            _ahora() - timedelta(hours=float(max_edad_revision_horas))
            if max_edad_revision_horas is not None else limite
        )
        for carpeta in sorted(self.trabajos.iterdir()):
            if not carpeta.is_dir():
                continue
            try:
                trabajo = self.estado(carpeta.name)
            except TrabajoDesconocido:
                if self._fecha_respaldo(carpeta) < limite:
                    shutil.rmtree(carpeta, ignore_errors=True)
                    yield carpeta.name
                continue
            con_gracia = (
                trabajo.estado == PENDIENTE_REVISION and not trabajo.verificacion
            )
            limite_trabajo = limite_revision if con_gracia else limite
            if self._fecha(trabajo.creado, carpeta) < limite_trabajo:
                shutil.rmtree(carpeta, ignore_errors=True)
                yield carpeta.name
                continue
            if trabajo.descargado:
                self.ruta_entrada(trabajo).unlink(missing_ok=True)

    def _fecha(self, texto: str, carpeta: Path) -> datetime:
        try:
            fecha = datetime.fromisoformat(texto)
        except (TypeError, ValueError):
            return self._fecha_respaldo(carpeta)
        return fecha if fecha.tzinfo else fecha.replace(tzinfo=timezone.utc)

    @staticmethod
    def _fecha_respaldo(carpeta: Path) -> datetime:
        try:
            marca = carpeta.stat().st_mtime
        except OSError:
            return _ahora()
        return datetime.fromtimestamp(marca, timezone.utc)
