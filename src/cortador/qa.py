"""Evidencia local y privada para las corridas de QA."""

from __future__ import annotations

import json
import os
import re
import sys
import traceback
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__

SCHEMA_VERSION = 1


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def directorio_datos(base: str | Path | None = None) -> Path:
    if base is not None:
        return Path(base)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "DatosQA"
    return Path(__file__).resolve().parents[2] / "DatosQA"


def recursos(subcarpeta: str | None = None) -> Path:
    """Raíz de recursos, compatible con PyInstaller y el árbol de desarrollo."""
    raiz = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return raiz / subcarpeta if subcarpeta else raiz


def _seguro(nombre: str) -> str:
    limpio = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(nombre).name).strip("._")
    return limpio or "archivo"


def _texto_seguro(valor: object) -> str:
    texto = str(valor)
    # Los errores de librerías suelen incrustar rutas. Conservamos sólo el basename.
    texto = re.sub(r"[A-Za-z]:[\\/](?:[^\s:'\"<>|]+[\\/])+([^\s:'\"<>|]+)", r"\1", texto)
    texto = re.sub(r"/(?:[^\s/'\"]+/)+([^\s/'\"]+)", r"\1", texto)
    return texto


def _depurar_json(valor: Any) -> Any:
    if isinstance(valor, dict):
        return {clave: (Path(dato).name if clave == "video" and isinstance(dato, str)
                        else _depurar_json(dato)) for clave, dato in valor.items()}
    if isinstance(valor, list):
        return [_depurar_json(item) for item in valor]
    if isinstance(valor, str) and (Path(valor).is_absolute() or re.match(r"^[A-Za-z]:[\\/]", valor)):
        return Path(valor.replace("\\", "/")).name
    return valor


def registrar_log(nivel: str, mensaje: object, *, base: str | Path | None = None,
                  excepcion: BaseException | None = None) -> bool:
    try:
        raiz = directorio_datos(base)
        raiz.mkdir(parents=True, exist_ok=True)
        linea = f"{_ahora().isoformat(timespec='seconds')} {nivel.upper()} {_texto_seguro(mensaje)}\n"
        if excepcion is not None:
            linea += _texto_seguro("".join(traceback.format_exception(excepcion)))
        with (raiz / "app.log").open("a", encoding="utf-8") as archivo:
            archivo.write(linea)
        return True
    except Exception:
        return False


class CorridaQA:
    """Acumula evidencia ya depurada de rutas/PII y la persiste al finalizar."""

    def __init__(self, carpeta_jugador: str | Path, *, base: str | Path | None = None,
                 run_id: str | None = None) -> None:
        ahora = _ahora()
        self.base = directorio_datos(base)
        self.id = run_id or ahora.strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
        self.datos: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "app_version": __version__,
            "fecha_utc": ahora.isoformat(timespec="seconds"),
            "carpeta_jugador": Path(str(carpeta_jugador).rstrip("/\\")).name,
            "estado": "iniciada", "resumen": "", "videos": [],
        }

    def agregar_video(self, video: str | Path, *, tipo: str | None = None,
                      perfil: str | Path | None = None, info: object | None = None) -> None:
        ruta = Path(video)
        metadatos = {}
        for origen, destino in (("ancho", "ancho"), ("alto", "alto"),
                                ("fps", "fps"), ("duracion", "duracion"),
                                ("codec", "codec")):
            valor = getattr(info, origen, None) if info is not None else None
            if valor is not None:
                metadatos[destino] = valor
        try:
            tamano = ruta.stat().st_size
        except OSError:
            tamano = None
        self.datos["videos"].append({
            "nombre": ruta.name, "extension": ruta.suffix.lower(), "tamano_bytes": tamano,
            "metadatos": metadatos, "tipo": tipo, "perfil": Path(perfil).name if perfil else None,
            "candidatos": [], "decisiones": [], "validos": 0, "pendientes": 0,
            "salida": None, "error": None,
        })

    def actualizar_video(self, nombre: str, **campos: Any) -> None:
        video = next((v for v in self.datos["videos"] if v["nombre"] == Path(nombre).name), None)
        if video is None:
            self.agregar_video(nombre)
            video = self.datos["videos"][-1]
        permitidos = {"tipo", "perfil", "candidatos", "decisiones", "validos",
                      "pendientes", "salida", "error", "metadatos"}
        for clave, valor in campos.items():
            if clave not in permitidos:
                continue
            if clave in {"perfil", "salida"} and valor:
                valor = Path(valor).name
            elif clave == "error" and valor:
                valor = _texto_seguro(valor)
            video[clave] = valor

    def copiar_etiqueta(self, origen: str | Path | None, video: str | Path) -> Path | None:
        if not origen:
            return None
        try:
            origen = Path(origen)
            destino = self.base / "etiquetas" / f"{_seguro(self.id)}_{_seguro(Path(video).stem)}_{_seguro(origen.name)}"
            destino.parent.mkdir(parents=True, exist_ok=True)
            # Los sidecars antiguos pueden guardar la ruta completa del video.
            datos = _depurar_json(json.loads(origen.read_text(encoding="utf-8")))
            temporal = destino.with_suffix(destino.suffix + ".tmp")
            temporal.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(temporal, destino)
            return destino
        except Exception as err:
            registrar_log("ERROR", "No se pudo copiar una etiqueta de QA", base=self.base,
                          excepcion=err)
            return None

    def finalizar(self, estado: str, resumen: str) -> Path | None:
        self.datos["estado"], self.datos["resumen"] = estado, _texto_seguro(resumen)
        destino = self.base / "corridas" / f"{_seguro(self.id)}.json"
        temporal = destino.with_suffix(".tmp")
        try:
            destino.parent.mkdir(parents=True, exist_ok=True)
            with temporal.open("w", encoding="utf-8") as archivo:
                json.dump(_depurar_json(self.datos), archivo, indent=2, ensure_ascii=False)
                archivo.flush()
                os.fsync(archivo.fileno())
            os.replace(temporal, destino)
            return destino
        except Exception as err:
            registrar_log("ERROR", "No se pudo guardar la corrida de QA", base=self.base,
                          excepcion=err)
            return None
        finally:
            try:
                temporal.unlink(missing_ok=True)
            except OSError:
                pass


def crear_paquete_qa(destino: str | Path | None = None, *,
                     base: str | Path | None = None) -> Path:
    raiz = directorio_datos(base)
    marca = _ahora().strftime("%Y%m%dT%H%M%SZ")
    destino = Path(destino) if destino else raiz / f"PaqueteQA-{marca}.zip"
    destino.parent.mkdir(parents=True, exist_ok=True)
    permitidos = [raiz / "app.log"]
    for carpeta in ("corridas", "etiquetas"):
        permitidos.extend(sorted((raiz / carpeta).glob("*.json")))
    temporal = destino.with_suffix(destino.suffix + ".tmp")
    try:
        with zipfile.ZipFile(temporal, "w", zipfile.ZIP_DEFLATED) as archivo:
            for ruta in permitidos:
                if ruta.is_file():
                    archivo.write(ruta, ruta.relative_to(raiz).as_posix())
        os.replace(temporal, destino)
    finally:
        temporal.unlink(missing_ok=True)
    return destino
