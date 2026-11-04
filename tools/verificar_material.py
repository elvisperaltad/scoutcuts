"""Dice si un video sirve para detectar automaticamente que hubo pelota lanzada.

Existe por lo que se aprendio al mirar el primer material que llego: dos videos
pasados por WhatsApp y por InShot en los que la pelota simplemente no esta. No es
que el detector fallara -- es que a 1024x576 y 915 kbps la pelota mide unos 5 px en
la zona de vuelo, la compresion la borra y el audio llegaba mudo.

Antes de gastar tiempo en un detector sobre material nuevo, se pasa esto.

    python tools/verificar_material.py jornada.mp4
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cortador import ffmpeg  # noqa: E402

# La pelota mide 7,3 cm. Para reconocerla en vuelo hacen falta unos 8 px de diametro:
# por debajo de eso es un par de pixeles grises que el codec no tiene por que conservar.
PX_MINIMOS = 8.0
# Ancho tipico del encuadre de una jaula de bateo, de valla a valla.
ESCENA_M = 12.0
BITRATE_MINIMO = 4_000_000       # bits/s
LADO_MINIMO = 1080               # alto del fotograma


def _probe(ruta: str) -> dict:
    salida = ffmpeg.ejecutar([
        ffmpeg.ruta_ffprobe(), "-v", "error",
        "-show_entries",
        "stream=codec_type,codec_name,width,height,avg_frame_rate,bit_rate:"
        "format=duration,size,bit_rate",
        "-of", "json", ruta,
    ])
    return json.loads(salida)


def _nivel_audio(ruta: str) -> float | None:
    """dB de pico. None si no hay pista de audio."""
    proc = subprocess.run(
        [ffmpeg.ruta_ffmpeg(), "-v", "info", "-i", ruta, "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    for linea in (proc.stderr or "").splitlines():
        if "max_volume" in linea:
            return float(linea.split("max_volume:")[1].replace("dB", "").strip())
    return None


def _intervalo_keyframes(ruta: str, duracion: float) -> float:
    tiempos = ffmpeg.keyframes(ruta)
    if len(tiempos) < 2:
        return duracion
    huecos = [b - a for a, b in zip(tiempos, tiempos[1:])]
    return sum(huecos) / len(huecos)


def revisar(ruta: str) -> int:
    datos = _probe(ruta)
    video = next((s for s in datos["streams"] if s["codec_type"] == "video"), None)
    audio = next((s for s in datos["streams"] if s["codec_type"] == "audio"), None)
    if video is None:
        print("No tiene flujo de video.", file=sys.stderr)
        return 2

    ancho, alto = int(video["width"]), int(video["height"])
    duracion = float(datos["format"]["duration"])
    bitrate = int(datos["format"].get("bit_rate") or 0)
    num, _, den = video["avg_frame_rate"].partition("/")
    fps = float(num) / float(den) if float(den or 0) else 0.0
    px_pelota = 0.073 / ESCENA_M * ancho
    gop = _intervalo_keyframes(ruta, duracion)
    pico = _nivel_audio(ruta) if audio else None

    print(f"  {Path(ruta).name}")
    print(f"  {ancho}x{alto}  {fps:.0f} fps  {duracion:.1f}s  {bitrate / 1e6:.2f} Mbps")
    print()

    problemas: list[str] = []
    avisos: list[str] = []

    def linea(ok: bool, texto: str, aviso: bool = False) -> None:
        marca = "ok" if ok else ("~ " if aviso else "NO")
        print(f"  [{marca}]  {texto}")

    ok = alto >= LADO_MINIMO
    linea(ok, f"resolucion {ancho}x{alto} (minimo recomendado 1920x{LADO_MINIMO})")
    if not ok:
        problemas.append(f"El fotograma es de {alto}p; con menos de {LADO_MINIMO}p la "
                         "pelota no sobrevive a la compresion.")

    ok = px_pelota >= PX_MINIMOS
    linea(ok, f"pelota estimada: {px_pelota:.1f} px de diametro (minimo {PX_MINIMOS:.0f})")
    if not ok:
        problemas.append(f"A este ancho la pelota queda en {px_pelota:.1f} px. Sube la "
                         "resolucion o acerca la camara.")

    ok = bitrate >= BITRATE_MINIMO
    linea(ok, f"bitrate {bitrate / 1e6:.2f} Mbps (minimo {BITRATE_MINIMO / 1e6:.0f})")
    if not ok:
        problemas.append("Bitrate demasiado bajo: es la huella de haber pasado por "
                         "WhatsApp o por una app de edicion. Pide el fichero original.")

    ok = fps >= 50
    linea(ok, f"{fps:.0f} fps (60 seria mejor: a 30 el swing dura 2-3 fotogramas)", aviso=True)
    if not ok:
        avisos.append("A 30 fps se puede trabajar, pero a 60 el instante del contacto "
                      "se ve mucho mejor.")

    if audio is None:
        linea(False, "sin pista de audio")
        problemas.append("Sin audio. El golpe del bate es la senal mas fiable de que "
                         "hubo pelota: graba con sonido.")
    elif pico is None or pico <= -90:
        linea(False, f"audio presente pero mudo (pico {pico} dB)")
        problemas.append("La pista de audio esta en silencio; alguna app la silencio "
                         "por el camino.")
    else:
        linea(True, f"audio con senal (pico {pico:.1f} dB)")

    ok = gop <= 2.5
    linea(ok, f"keyframe cada {gop:.2f}s", aviso=True)
    if gop >= 0.95 and abs(gop - round(gop)) < 0.05:
        avisos.append(f"Keyframes en segundos exactos (cada {gop:.0f}s): recuerda que "
                      "eso mete picos falsos en cualquier medida de diferencia entre "
                      "fotogramas. El motor ya los descarta.")

    print()
    if problemas:
        print("  NO SIRVE para detectar la pelota automaticamente:")
        for p in problemas:
            print(f"    - {p}")
    else:
        print("  SIRVE: tiene resolucion, bitrate y audio suficientes.")
    for a in avisos:
        print(f"    aviso: {a}")

    print()
    print("  Se puede marcar a mano en cualquier caso:")
    print(f"    cortador marcar \"{ruta}\" --perfil perfiles/<camara>.json")
    return 1 if problemas else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("video", nargs="+")
    args = parser.parse_args()
    peor = 0
    for i, ruta in enumerate(args.video):
        if i:
            print("\n" + "-" * 66 + "\n")
        peor = max(peor, revisar(ruta))
    return peor


if __name__ == "__main__":
    raise SystemExit(main())
