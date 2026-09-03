"""Imprime las distancias de apariencia reales de un video, para elegir el umbral.

El umbral de cambio decide si dos tramos vecinos son el mismo pelotero o dos distintos.
Es el parametro mas delicado del motor y no se puede fijar a ojo: depende del descriptor
y del material. Este script muestra, tramo a tramo, el hueco y la distancia al anterior,
para ver donde cae la frontera de verdad.

    python tools/calibrar_umbral.py fixtures/jornada_personas.mp4 \
        --perfil fixtures/perfil_personas.json --detector yolo --identidad cnn
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cortador import ffmpeg, identidad, muestreo, presencia  # noqa: E402
from cortador.perfil import Perfil  # noqa: E402
from cortador.reglas import Ajustes, agrupar  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("video")
    parser.add_argument("--perfil", required=True)
    parser.add_argument("--detector", choices=("color", "yolo"), default="color")
    parser.add_argument("--identidad", choices=("color", "cnn"), default="color")
    args = parser.parse_args()

    perfil = Perfil.cargar(args.perfil)
    info = ffmpeg.info(args.video)
    muestras = muestreo.muestrear(args.video, perfil)

    fondo = presencia.estimar_fondo(muestras.imagenes)
    cajas = None
    if args.detector == "yolo":
        from cortador import presencia_yolo

        mascara, _, cajas = presencia_yolo.ocupado(muestras.imagenes)
    else:
        mascara, _ = presencia.ocupado(muestras.imagenes, fondo=fondo)

    if args.identidad == "cnn":
        from cortador import identidad_cnn as apariencia
    else:
        apariencia = identidad

    descs = apariencia.descriptores(muestras.imagenes, fondo, mascara, cajas)
    tramos = agrupar(muestras.tiempos, mascara.tolist())

    print(f"{info.duracion:.0f} s · {len(muestras)} recortes · detector {args.detector} "
          f"· identidad {args.identidad}")
    print(f"umbral actual: {apariencia.UMBRAL_CAMBIO}   "
          f"gap de fusion: {Ajustes.gap_fusion} s\n")
    print(f"{'tramo':>16}  {'dur':>6}  {'hueco':>6}  {'dist. al anterior':>18}  que pasaria")

    anterior = None
    for i, j in tramos:
        inicio, fin = muestras.tiempos[i], muestras.tiempos[min(j + 1, len(muestras) - 1)]
        vector = apariencia.promedio(list(descs[i : j + 1]))
        if anterior is None:
            linea_dist, veredicto = "         —", "primer tramo"
        else:
            hueco = inicio - anterior[1]
            d = apariencia.distancia(anterior[2], vector)
            mismo = d <= apariencia.UMBRAL_CAMBIO
            if hueco > Ajustes.gap_fusion:
                veredicto = "corta (hueco largo)"
            elif mismo:
                veredicto = "FUSIONA"
            else:
                veredicto = "corta (otra persona)"
            linea_dist = f"{d:18.3f}"
        hueco_txt = "     —" if anterior is None else f"{inicio - anterior[1]:6.0f}"
        print(f"{inicio:7.0f}-{fin:<8.0f}  {fin - inicio:6.0f}  {hueco_txt}  "
              f"{linea_dist}  {veredicto}")
        anterior = (inicio, fin, vector)


if __name__ == "__main__":
    main()
