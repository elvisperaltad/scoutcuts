"""Puente entre un trabajo subido al servidor y el motor de corte existente.

No reimplementa nada: elige el perfil de camara por resolucion, llama al
detector, guarda las marcas como material etiquetado y exporta el montaje.

Si no hay exactamente un perfil compatible, el trabajo queda pendiente de
revision. Inventar un ROI produciria recortes equivocados y, peor, etiquetas
equivocadas que luego ensucian el entrenamiento.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable

from .. import ffmpeg, marcas, qa
from ..compactar import exportar as exportar_real
from ..eventos import ANTES, DESPUES, detectar as detectar_real
from ..perfil import Perfil
from . import almacen as alm
from .almacen import Almacen, Trabajo

NOTA_SIN_REVISAR = "Propuesto por el servidor; sin revision humana todavia."

MENSAJE_LISTO = "Tu montaje esta listo para descargar."
MENSAJE_SIN_SWINGS = (
    "No detectamos swings en este video. Revisa que se vea el cajon de bateo "
    "completo y vuelve a intentarlo."
)


def _perfiles_por_defecto() -> Path:
    return Path(qa.recursos("perfiles"))


def perfil_compatible(carpeta: str | Path, ancho: int, alto: int) -> Perfil | None:
    """Unico perfil cuya resolucion coincide exactamente; None si hay 0 o varios."""
    encontrados: list[Perfil] = []
    for ruta in sorted(Path(carpeta).glob("*.json")):
        try:
            candidato = Perfil.cargar(ruta)
        except (OSError, ValueError, TypeError):
            continue
        if candidato.video_ancho == ancho and candidato.video_alto == alto:
            encontrados.append(candidato)
    return encontrados[0] if len(encontrados) == 1 else None


def _mensaje_pendiente(ancho: int, alto: int) -> str:
    return (
        f"Todavia no tenemos una configuración de cámara para videos de {ancho}x{alto}. "
        "Lo revisamos y te avisamos; no hace falta que vuelvas a subirlo."
    )


def procesar(trabajo: Trabajo, almacen: Almacen, *,
             perfiles: str | Path | None = None,
             qa_base: str | Path | None = None,
             obtener_info: Callable[[str], object] = ffmpeg.info,
             detectar: Callable[..., Iterable] = detectar_real,
             exportar: Callable[..., object] = exportar_real) -> Trabajo:
    """Analiza el video del trabajo y deja su estado final guardado en disco."""
    entrada = almacen.ruta_entrada(trabajo)
    corrida = qa.CorridaQA(trabajo.id, base=qa_base)
    try:
        info = obtener_info(str(entrada))
        ancho = int(getattr(info, "ancho", 0) or 0)
        alto = int(getattr(info, "alto", 0) or 0)
        corrida.agregar_video(entrada, tipo="bateo", info=info)

        perfil = perfil_compatible(perfiles or _perfiles_por_defecto(), ancho, alto)
        if perfil is None:
            return _pendiente(trabajo, almacen, corrida, entrada, ancho, alto)

        candidatos = list(detectar(str(entrada), perfil))
        cuaderno = _cuaderno(trabajo, candidatos, perfil)
        cuaderno.guardar(almacen.ruta_marcas(trabajo))
        etiqueta = corrida.copiar_etiqueta(almacen.ruta_marcas(trabajo), entrada.name)

        trabajo.candidatos = len(candidatos)
        trabajo.validos = len(cuaderno.validas)
        tramos = marcas.fundir(cuaderno)
        corrida.actualizar_video(
            entrada.name, perfil=perfil.origen or "perfil compatible",
            candidatos=[round(c.instante, 3) for c in candidatos],
            validos=trabajo.validos,
        )
        if not tramos:
            return _sin_swings(trabajo, almacen, corrida, etiqueta)

        exportar(str(entrada), tramos, almacen.ruta_resultado(trabajo))
        trabajo.duracion = round(sum(fin - inicio for inicio, fin in tramos), 3)
        trabajo.estado = alm.LISTO
        trabajo.mensaje = MENSAJE_LISTO
        trabajo.detalle = ""
        almacen.guardar_estado(trabajo)
        corrida.actualizar_video(entrada.name, salida=almacen.ruta_resultado(trabajo).name)
        corrida.finalizar("completado", f"{trabajo.validos} jugadas, {trabajo.duracion} s")
        return trabajo
    except BaseException as err:
        corrida.finalizar("error", alm.depurar_texto(f"{type(err).__name__}: {err}"))
        raise


def _cuaderno(trabajo: Trabajo, candidatos: list, perfil: Perfil) -> marcas.Cuaderno:
    """Cuaderno con el nombre depurado y los candidatos conservados.

    Sin nadie que revise en el servidor, un candidato descartado se perderia para
    siempre; se conserva como valido y la nota deja claro que falta revision.
    """
    cuaderno = marcas.Cuaderno.desde_candidatos(
        f"entrada{trabajo.extension}", candidatos, ANTES, DESPUES,
        perfil=perfil.origen or "perfil compatible",
    )
    for marca in cuaderno.marcas:
        marca.estado = marcas.VALIDO
        marca.nota = NOTA_SIN_REVISAR
    return cuaderno


def _pendiente(trabajo: Trabajo, almacen: Almacen, corrida: qa.CorridaQA,
               entrada: Path, ancho: int, alto: int) -> Trabajo:
    trabajo.estado = alm.PENDIENTE_REVISION
    trabajo.mensaje = _mensaje_pendiente(ancho, alto)
    almacen.guardar_estado(trabajo)
    corrida.actualizar_video(entrada.name, error=f"sin perfil para {ancho}x{alto}")
    corrida.finalizar("pendiente_revision", f"sin perfil para {ancho}x{alto}")
    return trabajo


def _sin_swings(trabajo: Trabajo, almacen: Almacen, corrida: qa.CorridaQA,
                etiqueta: Path | None) -> Trabajo:
    trabajo.estado = alm.LISTO
    trabajo.duracion = 0.0
    trabajo.mensaje = MENSAJE_SIN_SWINGS
    almacen.guardar_estado(trabajo)
    corrida.finalizar("completado", "sin candidatos de swing")
    return trabajo
