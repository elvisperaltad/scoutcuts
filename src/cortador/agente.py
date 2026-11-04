"""Orquestador local y reanudable del flujo completo.

No decide si un swing vale. Prepara candidatos, deja esa decisión en el cuaderno
para una persona y solo compacta marcas que ya estén como ``valido``.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import compactar, eventos, ffmpeg
from .canal import cortar
from .marcas import Cuaderno, fundir
from .perfil import Perfil
from .reglas import Ajustes

VERSION_ESTADO = 2
ARCHIVO_ESTADO = "estado-agente.json"
PAUSA_HUMANA = "revision_humana"
COMPLETADO = "completado"
SIN_CANDIDATOS = "sin_candidatos"
SIN_VALIDAS = "sin_marcas_validas"


class ErrorEstado(ValueError):
    """El estado guardado no es seguro para esta ejecución."""


@dataclass
class Turno:
    video: str
    marcas: str
    salida: str
    etapa: str = "pendiente"
    huella: str = ""        # sha256 del cuaderno con el que se cerró el turno


@dataclass
class Estado:
    version: int
    video: str
    perfil: str
    trabajo: str
    tamano_video: int
    parametros: dict = field(default_factory=dict)
    etapa: str = "preparado"
    turnos: list[Turno] = field(default_factory=list)
    actualizado: str = ""

    @classmethod
    def nuevo(cls, video: str | Path, perfil: str | Path, trabajo: str | Path,
              parametros: dict | None = None) -> "Estado":
        ruta_video = Path(video).resolve()
        return cls(
            version=VERSION_ESTADO,
            video=str(ruta_video),
            perfil=str(Path(perfil).resolve()),
            trabajo=str(Path(trabajo).resolve()),
            tamano_video=ruta_video.stat().st_size,
            parametros=parametros or {},
        )


def parametros_de(detector: str, identidad: str, ajustes: Ajustes, sigmas: float,
                  antes: float, despues: float, separacion: float) -> dict:
    """Todo lo que cambia el resultado; reanudar con otros valores mezclaría criterios."""
    return {
        "detector": detector,
        "identidad": identidad,
        "ajustes": asdict(ajustes),
        "sigmas": float(sigmas),
        "antes": float(antes),
        "despues": float(despues),
        "separacion": float(separacion),
    }


def ruta_estado(trabajo: str | Path) -> Path:
    return Path(trabajo) / ARCHIVO_ESTADO


def guardar_estado(estado: Estado) -> None:
    """Guarda en el mismo directorio y reemplaza al final, nunca a medias."""
    destino = ruta_estado(estado.trabajo)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_suffix(destino.suffix + ".tmp")
    estado.actualizado = datetime.now(timezone.utc).isoformat(timespec="seconds")
    datos = json.dumps(asdict(estado), indent=2, ensure_ascii=False, sort_keys=True)
    try:
        with temporal.open("w", encoding="utf-8", newline="\n") as archivo:
            archivo.write(datos)
            archivo.flush()
            os.fsync(archivo.fileno())
        os.replace(temporal, destino)
    finally:
        if temporal.exists():
            temporal.unlink()


def cargar_estado(trabajo: str | Path, video: str | Path) -> Estado | None:
    destino = ruta_estado(trabajo)
    if not destino.exists():
        return None
    try:
        datos = json.loads(destino.read_text(encoding="utf-8"))
        turnos = [Turno(**turno) for turno in datos.pop("turnos", [])]
        estado = Estado(turnos=turnos, **datos)
    except (OSError, json.JSONDecodeError, TypeError, KeyError) as err:
        raise ErrorEstado(
            f"El estado {destino} está corrupto; no se modificó. "
            "Corrígelo o mueve la carpeta de trabajo."
        ) from err

    if estado.version != VERSION_ESTADO:
        raise ErrorEstado(
            f"La version {estado.version} del estado no es compatible "
            f"con la version {VERSION_ESTADO}; no se modificó."
        )
    if os.path.normcase(estado.trabajo) != os.path.normcase(str(Path(trabajo).resolve())):
        raise ErrorEstado(
            f"La carpeta de trabajo se movió o se copió desde {estado.trabajo}; sus "
            "rutas apuntan allí. Devuélvela a su sitio o usa otra carpeta de trabajo."
        )
    esperado = str(Path(video).resolve())
    if estado.video != esperado:
        raise ErrorEstado(
            f"La carpeta contiene el estado de otro video ({estado.video}); "
            "usa otra carpeta de trabajo."
        )
    ruta_video = Path(esperado)
    if ruta_video.exists() and ruta_video.stat().st_size != estado.tamano_video:
        raise ErrorEstado(
            "El video cambió desde que se creó el estado; usa otra carpeta de trabajo."
        )
    return estado


def _validar(video: Path, perfil: Path) -> Perfil:
    if not video.is_file():
        raise ValueError(f"No existe el video de entrada: {video}")
    if not perfil.is_file():
        raise ValueError(f"No existe el perfil: {perfil}")
    try:
        perfil_cargado = Perfil.cargar(perfil)
    except (OSError, json.JSONDecodeError, TypeError, KeyError) as err:
        raise ValueError(f"El perfil no es un JSON válido: {perfil}") from err
    info = ffmpeg.info(str(video))
    if (perfil_cargado.video_ancho, perfil_cargado.video_alto) != (info.ancho, info.alto):
        raise ValueError(
            "El perfil corresponde a otra resolucion: "
            f"{perfil_cargado.video_ancho}x{perfil_cargado.video_alto}, pero el video es "
            f"{info.ancho}x{info.alto}. Calibra un perfil para este material."
        )
    return perfil_cargado


def _crear_turnos(estado: Estado, perfil: Perfil, registrar: Callable[[str], None],
                  detector: str, identidad: str, ajustes: Ajustes) -> None:
    carpeta = Path(estado.trabajo) / "turnos"
    registrar("Analizando la jornada y cortando los turnos...")
    resultado = cortar(
        estado.video, perfil, carpeta, ajustes=ajustes, detector=detector,
        modo_identidad=identidad, registrar=registrar,
    )
    estado.turnos = [
        Turno(
            video=str(Path(clip).resolve()),
            marcas=str((Path(estado.trabajo) / "marcas" /
                        f"{Path(clip).stem}.marcas.json").resolve()),
            salida=str((Path(estado.trabajo) / "compactos" /
                        f"{Path(clip).stem}_compacto.mp4").resolve()),
        )
        for clip in resultado.clips
    ]
    estado.etapa = "turnos_cortados"
    guardar_estado(estado)
    registrar(f"Se encontraron y guardaron {len(estado.turnos)} turnos.")


def _huella(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest() if ruta.is_file() else ""


def _al_dia(turno: Turno) -> bool:
    """Un turno cerrado se salta si su cuaderno y su compacto siguen como se dejaron."""
    if turno.etapa == SIN_CANDIDATOS:
        return True
    if turno.etapa not in (COMPLETADO, SIN_VALIDAS):
        return False
    if turno.etapa == COMPLETADO and not Path(turno.salida).is_file():
        return False
    return bool(turno.huella) and _huella(Path(turno.marcas)) == turno.huella


def _cargar_cuaderno(ruta: Path) -> Cuaderno:
    try:
        return Cuaderno.cargar(ruta)
    except (OSError, ValueError, TypeError, KeyError) as err:
        raise ErrorEstado(
            f"El cuaderno {ruta} está corrupto; no se modificó. "
            "Corrígelo a mano o bórralo para volver a detectar ese turno."
        ) from err


def _revisar_interactivamente(cuaderno: Cuaderno, destino: Path,
                              preguntar: Callable[[str], str]) -> Cuaderno:
    respuesta = preguntar("¿Abrir ahora la revisión humana? [S/n] ").strip().lower()
    if respuesta not in ("", "s", "si", "sí"):
        return cuaderno
    from .revision import marcar

    return marcar(cuaderno, destino)


def ejecutar(video: str | Path, perfil: str | Path, trabajo: str | Path, *,
             interactivo: bool = True, detector: str = "color", identidad: str = "color",
             sigmas: float = eventos.SIGMAS, antes: float = eventos.ANTES,
             despues: float = eventos.DESPUES, separacion: float = 0.5,
             ajustes: Ajustes | None = None, registrar: Callable[[str], None] = print,
             preguntar: Callable[[str], str] = input) -> str:
    """Avanza hasta completar o hasta necesitar una decisión humana."""
    ruta_video = Path(video).resolve()
    ruta_perfil = Path(perfil).resolve()
    ruta_trabajo = Path(trabajo).resolve()
    perfil_cargado = _validar(ruta_video, ruta_perfil)
    ajustes = ajustes or Ajustes()
    parametros = parametros_de(detector, identidad, ajustes, sigmas, antes, despues,
                               separacion)

    estado = cargar_estado(ruta_trabajo, ruta_video)
    if estado is None:
        estado = Estado.nuevo(ruta_video, ruta_perfil, ruta_trabajo, parametros)
        guardar_estado(estado)
        registrar(f"Sesión creada en {ruta_trabajo}")
    elif estado.perfil != str(ruta_perfil):
        raise ErrorEstado(
            f"La sesión usa otro perfil ({estado.perfil}); usa otra carpeta de trabajo."
        )
    elif estado.parametros != parametros:
        distintos = sorted(clave for clave in parametros
                           if estado.parametros.get(clave) != parametros[clave])
        raise ErrorEstado(
            f"La sesión se creó con otros parámetros ({', '.join(distintos)}); "
            "repite los mismos valores o usa otra carpeta de trabajo."
        )
    else:
        registrar(f"Reanudando la sesión: {estado.etapa}.")

    if not estado.turnos and estado.etapa != COMPLETADO:
        _crear_turnos(estado, perfil_cargado, registrar, detector, identidad, ajustes)

    hay_pendientes = False
    for indice, turno in enumerate(estado.turnos, start=1):
        # Antes de exigir el clip: un turno cerrado no lo necesita si su compacto sigue.
        if _al_dia(turno):
            continue
        ruta_turno = Path(turno.video)
        ruta_marcas = Path(turno.marcas)
        if not ruta_turno.is_file():
            raise ErrorEstado(f"Falta el turno ya registrado: {ruta_turno}")
        if turno.etapa in (COMPLETADO, SIN_VALIDAS):
            registrar(f"Turno {indice}: falta el compacto o el cuaderno cambió; se reconcilia.")

        if not ruta_marcas.exists():
            registrar(f"Turno {indice}/{len(estado.turnos)}: detectando candidatos...")
            candidatos = eventos.detectar(str(ruta_turno), perfil_cargado, sigmas)
            if not candidatos:
                turno.etapa = SIN_CANDIDATOS
                guardar_estado(estado)
                registrar(f"Turno {indice}: no se detectaron candidatos; se omite.")
                continue
            cuaderno = Cuaderno.desde_candidatos(
                str(ruta_turno), candidatos, antes, despues, perfil=str(ruta_perfil)
            )
            cuaderno.guardar(ruta_marcas)
            turno.etapa = PAUSA_HUMANA
            estado.etapa = PAUSA_HUMANA
            guardar_estado(estado)
        else:
            cuaderno = _cargar_cuaderno(ruta_marcas)

        if cuaderno.pendientes:
            registrar(
                f"Turno {indice}: {cuaderno.resumen()}. La validez requiere revision "
                "humana; el agente no puede decidir si hubo pelota."
            )
            turno.etapa = PAUSA_HUMANA
            if not interactivo:
                registrar(f"Pendiente de revisar: {ruta_marcas}")
                hay_pendientes = True
                continue
            cuaderno = _revisar_interactivamente(cuaderno, ruta_marcas, preguntar)
            if cuaderno.pendientes:
                estado.etapa = PAUSA_HUMANA
                guardar_estado(estado)
                registrar("La revisión quedó pendiente. Puedes reanudar con el mismo comando.")
                return PAUSA_HUMANA

        tramos = fundir(cuaderno, separacion)
        if tramos:
            registrar(f"Turno {indice}: compactando {len(tramos)} tramos válidos...")
            compactar.exportar(str(ruta_turno), tramos, turno.salida)
            turno.etapa = COMPLETADO
        else:
            turno.etapa = SIN_VALIDAS
            registrar(f"Turno {indice}: la revisión no dejó swings válidos; no se exporta.")
        turno.huella = _huella(ruta_marcas)
        guardar_estado(estado)

    if hay_pendientes:
        estado.etapa = PAUSA_HUMANA
        guardar_estado(estado)
        registrar("Siguiente paso: ejecuta de nuevo sin --no-interactivo para revisar "
                  "los turnos pendientes.")
        return PAUSA_HUMANA

    estado.etapa = COMPLETADO
    guardar_estado(estado)
    registrar(f"Proceso completado. Resultados en {Path(estado.trabajo) / 'compactos'}")
    return COMPLETADO
