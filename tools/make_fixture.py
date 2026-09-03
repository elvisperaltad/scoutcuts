"""Genera una jornada sintetica para probar el motor sin video real del cliente.

Reproduce a escala los cuatro casos limite del diseno:

  * turno normal
  * el pelotero sale a ajustarse el guante y vuelve antes de 25 s  -> un solo turno
  * dos peloteros se relevan sin que el cajon quede vacio          -> dos turnos
  * un entrenador cruza el cuadro durante 8 s                      -> ningun turno

La verdad de referencia se escribe junto al mp4, en JSON, para comparar.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cortador import ffmpeg  # noqa: E402

ANCHO, ALTO, FPS = 480, 270, 5
GOP = 2.0  # segundos entre keyframes, como el material real
ROI = (180, 90, 140, 140)  # x, y, ancho, alto: los dos cajones y el plato

# (inicio, fin, etiqueta del pelotero). Etiqueta None = nadie en el cajon.
GUION = [
    (15.0, 75.0, "P-01"),
    (90.0, 140.0, "P-02"),
    (158.0, 200.0, "P-02"),   # vuelve tras 18 s: se fusiona con el anterior
    (215.0, 275.0, "P-03"),
    (275.0, 335.0, "P-04"),   # relevo sin hueco
    (350.0, 358.0, "cruce"),  # 8 s: no es un turno
    (370.0, 430.0, "P-05"),
]
DURACION = 440.0

COLORES = {
    "P-01": (196, 64, 48),
    "P-02": (48, 96, 196),
    "P-03": (232, 208, 64),
    "P-04": (64, 168, 96),
    "P-05": (168, 64, 176),
    "cruce": (232, 232, 232),
}

# Turnos que el motor deberia encontrar (fusion aplicada, cruce descartado).
ESPERADO = [
    {"inicio": 15.0, "fin": 75.0, "pelotero": "P-01"},
    {"inicio": 90.0, "fin": 200.0, "pelotero": "P-02"},
    {"inicio": 215.0, "fin": 275.0, "pelotero": "P-03"},
    {"inicio": 275.0, "fin": 335.0, "pelotero": "P-04"},
    {"inicio": 370.0, "fin": 430.0, "pelotero": "P-05"},
]


def _fondo() -> np.ndarray:
    """Tierra y valla: textura fija, para que el modelo de fondo tenga algo estable."""
    rng = np.random.default_rng(7)
    fondo = np.zeros((ALTO, ANCHO, 3), dtype=np.float32)
    fondo[:, :] = (past := np.array([132, 116, 96], dtype=np.float32))
    fondo[: ALTO // 3, :] = np.array([150, 160, 168], dtype=np.float32)  # valla al fondo
    fondo += rng.normal(0, 6, size=fondo.shape).astype(np.float32)
    for x in range(0, ANCHO, 24):  # postes de la malla
        fondo[: ALTO // 3, x : x + 2] = past
    return np.clip(fondo, 0, 255).astype(np.uint8)


def _quien(t: float) -> str | None:
    for inicio, fin, etiqueta in GUION:
        if inicio <= t < fin:
            return etiqueta
    return None


def generar(destino: Path) -> None:
    fondo = _fondo()
    rx, ry, rw, rh = ROI
    rng = np.random.default_rng(11)

    cmd = [
        ffmpeg.ruta_ffmpeg(), "-v", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{ANCHO}x{ALTO}", "-r", str(FPS), "-i", "-",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-g", str(int(FPS * GOP)), "-keyint_min", str(int(FPS * GOP)), "-sc_threshold", "0",
        "-an", str(destino),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    total = int(DURACION * FPS)
    for n in range(total):
        t = n / FPS
        cuadro = fondo.copy()
        etiqueta = _quien(t)
        if etiqueta is not None:
            color = np.array(COLORES[etiqueta], dtype=np.uint8)
            # El pelotero se mueve dentro del cajon: sin jitter, la mediana temporal
            # aprenderia su silueta como si fuera fondo.
            jx = int(rng.normal(0, 6))
            jy = int(rng.normal(0, 4))
            ancho_p, alto_p = 46, 104
            if etiqueta == "cruce":
                # cruza de lado a lado en vez de quedarse
                avance = (t - 350.0) / 8.0
                jx = int(-rw / 2 + avance * rw)
                alto_p = 88
            x0 = np.clip(rx + rw // 2 - ancho_p // 2 + jx, rx, rx + rw - ancho_p)
            y0 = np.clip(ry + rh - alto_p - 8 + jy, ry, ry + rh - alto_p)
            cuadro[y0 : y0 + alto_p, x0 : x0 + ancho_p] = color
            cuadro[y0 : y0 + 20, x0 + 12 : x0 + 34] = np.array([196, 168, 140], dtype=np.uint8)
        proc.stdin.write(cuadro.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise SystemExit("ffmpeg fallo generando el fixture")


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    carpeta = raiz / "fixtures"
    carpeta.mkdir(exist_ok=True)
    video = carpeta / "jornada_sintetica.mp4"
    generar(video)

    rx, ry, rw, rh = ROI
    perfil = {
        "x": rx, "y": ry, "ancho": rw, "alto": rh,
        "video_ancho": ANCHO, "video_alto": ALTO,
        "creado": "", "origen": video.name,
    }
    (carpeta / "perfil_sintetico.json").write_text(
        json.dumps(perfil, indent=2), encoding="utf-8")
    (carpeta / "jornada_sintetica.esperado.json").write_text(
        json.dumps({"duracion": DURACION, "turnos": ESPERADO}, indent=2, ensure_ascii=False),
        encoding="utf-8")

    tam = video.stat().st_size / 1e6
    print(f"{video}  ({tam:.1f} MB, {DURACION:.0f} s, {len(ESPERADO)} turnos esperados)")


if __name__ == "__main__":
    main()
