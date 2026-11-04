"""Etapa 6: el turno sin los tiempos muertos.

A diferencia de `corte.py`, aqui no se puede copiar el flujo. Los cortes caen donde
ocurre el swing, no donde el codec dejo un keyframe, y en este material los
keyframes van a un segundo de distancia: ajustar los tramos hacia fuera hasta el
keyframe anterior alargaria cada swing hasta un segundo, mas que el propio swing.
Asi que se recodifica, una sola vez y en un unico pase con filter_complex.
"""

from __future__ import annotations

from pathlib import Path

from . import ffmpeg

CRF = "18"          # practicamente sin perdida visible
PRESET = "veryfast"


def _cadena_filtros(tramos: list[tuple[float, float]]) -> str:
    partes = []
    for i, (inicio, fin) in enumerate(tramos):
        partes.append(
            f"[0:v]trim=start={inicio:.3f}:end={fin:.3f},setpts=PTS-STARTPTS[v{i}]"
        )
    etiquetas = "".join(f"[v{i}]" for i in range(len(tramos)))
    partes.append(f"{etiquetas}concat=n={len(tramos)}:v=1:a=0[salida]")
    return ";".join(partes)


def exportar(ruta_video: str, tramos: list[tuple[float, float]],
             destino: str | Path) -> Path:
    """Escribe un mp4 con solo los tramos indicados, pegados en orden."""
    if not tramos:
        raise ValueError("No hay ningun tramo valido que exportar")

    salida = Path(destino)
    salida.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg.ejecutar([
        ffmpeg.ruta_ffmpeg(), "-v", "error", "-y",
        "-i", ruta_video,
        "-filter_complex", _cadena_filtros(tramos),
        "-map", "[salida]", "-an",
        "-c:v", "libx264", "-crf", CRF, "-preset", PRESET,
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(salida),
    ])
    return salida


def duracion_total(tramos: list[tuple[float, float]]) -> float:
    return sum(fin - inicio for inicio, fin in tramos)
