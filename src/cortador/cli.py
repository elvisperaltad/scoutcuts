"""Interfaz por linea de comandos (fase 1: sin pantalla de revision)."""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from . import ffmpeg
from .canal import analizar, cortar
from .perfil import Perfil
from .reglas import Ajustes


def _ajustes_desde(args: argparse.Namespace) -> Ajustes:
    ajustes = Ajustes(
        gap_fusion=args.gap_fusion,
        min_duracion=args.min_duracion,
        colchon=args.colchon,
    )
    if args.umbral_cambio is not None:
        ajustes = replace(ajustes, umbral_cambio=args.umbral_cambio)
    return ajustes


def _tabla(segmentos) -> str:
    lineas = [f"{'#':>3}  {'inicio':>9}  {'fin':>9}  {'duracion':>9}  notas"]
    for i, s in enumerate(segmentos, start=1):
        lineas.append(
            f"{i:>3}  {_hms(s.inicio):>9}  {_hms(s.fin):>9}  {s.duracion:>8.1f}s  "
            + ", ".join(s.notas)
        )
    return "\n".join(lineas)


def _hms(t: float) -> str:
    h, resto = divmod(int(t), 3600)
    m, s = divmod(resto, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def cmd_calibrar(args: argparse.Namespace) -> int:
    """Dibuja el ROI del cajon sobre un fotograma y lo guarda como perfil de camara."""
    import cv2
    import numpy as np

    info = ffmpeg.info(args.video)
    instante = args.instante if args.instante is not None else info.duracion / 2



    proc = subprocess.run(
        [ffmpeg.ruta_ffmpeg(), "-v", "error", "-ss", f"{instante:.3f}", "-i", args.video,
         "-frames:v", "1", "-f", "image2pipe", "-vcodec", "rawvideo", "-pix_fmt", "bgr24", "-"],
        capture_output=True,
    )
    fotograma = np.frombuffer(proc.stdout, dtype=np.uint8)
    if fotograma.size < info.ancho * info.alto * 3:
        print("No se pudo extraer el fotograma de calibracion.", file=sys.stderr)
        return 1
    fotograma = fotograma[: info.ancho * info.alto * 3].reshape(info.alto, info.ancho, 3).copy()

    print("Arrastra el rectangulo sobre los DOS cajones y el plato. ENTER para confirmar.")
    x, y, ancho, alto = cv2.selectROI("Calibrar cajon de bateo", fotograma, showCrosshair=False)
    cv2.destroyAllWindows()
    if ancho == 0 or alto == 0:
        print("Calibracion cancelada.", file=sys.stderr)
        return 1

    perfil = Perfil(x=int(x), y=int(y), ancho=int(ancho), alto=int(alto),
                    video_ancho=info.ancho, video_alto=info.alto, origen=Path(args.video).name)
    perfil.guardar(args.perfil)
    print(f"Perfil guardado en {args.perfil}: {perfil.crop}")
    return 0


def cmd_analizar(args: argparse.Namespace) -> int:
    perfil = Perfil.cargar(args.perfil)
    resultado = analizar(args.video, perfil, _ajustes_desde(args), args.detector,
                         args.modo_identidad, registrar=print)
    print()
    print(_tabla(resultado.segmentos))
    return 0


def cmd_cortar(args: argparse.Namespace) -> int:
    perfil = Perfil.cargar(args.perfil)
    resultado = cortar(args.video, perfil, args.salida, _ajustes_desde(args), args.detector,
                       args.modo_identidad, registrar=print)
    print()
    print(_tabla(resultado.segmentos))
    print(f"\n{len(resultado.clips)} clips en {args.salida}")
    return 0


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cortador",
        description="Parte una jornada de academia en un mp4 por turno al bate.",
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    def comunes(p: argparse.ArgumentParser) -> None:
        p.add_argument("video")
        p.add_argument("--perfil", required=True, help="JSON del perfil de camara (ROI)")

    def parametros(p: argparse.ArgumentParser) -> None:
        p.add_argument("--gap-fusion", type=float, default=Ajustes.gap_fusion, dest="gap_fusion",
                       help="segundos de ausencia que aun se fusionan si vuelve el mismo pelotero")
        p.add_argument("--min-duracion", type=float, default=Ajustes.min_duracion, dest="min_duracion",
                       help="descarta lo que dure menos (gente cruzando el cuadro)")
        p.add_argument("--detector", choices=("color", "yolo"), default="color",
                       help="presencia. color: OpenCV puro. yolo: YOLOv8n, mejor si el fondo cambia")
        p.add_argument("--identidad", choices=("color", "cnn"), default="color", dest="modo_identidad",
                       help="apariencia. color: histograma. cnn: ResNet-18, separa personas parecidas")
        p.add_argument("--umbral-cambio", type=float, default=None, dest="umbral_cambio",
                       help="distancia de apariencia a partir de la cual son dos peloteros")
        p.add_argument("--colchon", type=float, default=Ajustes.colchon,
                       help="segundos de margen a cada lado del turno")

    p_cal = sub.add_parser("calibrar", help="dibujar el ROI del cajon (una vez por camara)")
    p_cal.add_argument("video")
    p_cal.add_argument("--perfil", required=True)
    p_cal.add_argument("--instante", type=float, default=None, help="segundo del fotograma a usar")
    p_cal.set_defaults(func=cmd_calibrar)

    p_ana = sub.add_parser("analizar", help="detectar turnos sin exportar nada")
    comunes(p_ana)
    parametros(p_ana)
    p_ana.set_defaults(func=cmd_analizar)

    p_cor = sub.add_parser("cortar", help="detectar turnos y exportar un mp4 por turno")
    comunes(p_cor)
    parametros(p_cor)
    p_cor.add_argument("--salida", required=True, help="carpeta donde dejar los clips")
    p_cor.set_defaults(func=cmd_cortar)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ffmpeg.FfmpegNoEncontrado, RuntimeError, ValueError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
