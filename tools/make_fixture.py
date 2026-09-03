"""Genera una jornada sintetica para probar el motor sin video real del cliente.

Reproduce a escala los cuatro casos limite del diseno:

  * turno normal
  * el pelotero sale a ajustarse el guante y vuelve antes de 25 s  -> un solo turno
  * dos peloteros se relevan sin que el cajon quede vacio          -> dos turnos
  * un entrenador cruza el cuadro durante 8 s                      -> ningun turno

Dos modos:

  (por defecto)  cada pelotero es un rectangulo de color. Vale para el detector por
                 color y no necesita nada instalado.
  --personas     cada pelotero es el recorte de una persona real, sacado de las
                 imagenes de ejemplo de ultralytics. Es lo unico que permite probar el
                 detector YOLO: sobre rectangulos de colores no detecta a nadie, y con
                 razon.

La verdad de referencia se escribe junto al mp4, en JSON, para comparar.
"""

from __future__ import annotations

import argparse
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

# (inicio, fin, etiqueta del pelotero).
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
ETIQUETAS = ["P-01", "P-02", "P-03", "P-04", "P-05", "cruce"]

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

ALTO_PELOTERO = 104
ALTO_CRUCE = 88


def _fondo() -> np.ndarray:
    """Tierra y valla: textura fija, para que el modelo de fondo tenga algo estable."""
    rng = np.random.default_rng(7)
    fondo = np.zeros((ALTO, ANCHO, 3), dtype=np.float32)
    tierra = np.array([132, 116, 96], dtype=np.float32)
    fondo[:, :] = tierra
    fondo[: ALTO // 3, :] = np.array([150, 160, 168], dtype=np.float32)  # valla al fondo
    fondo += rng.normal(0, 6, size=fondo.shape).astype(np.float32)
    for x in range(0, ANCHO, 24):  # postes de la malla
        fondo[: ALTO // 3, x : x + 2] = tierra
    return np.clip(fondo, 0, 255).astype(np.uint8)


def _alto_de(etiqueta: str) -> int:
    return ALTO_CRUCE if etiqueta == "cruce" else ALTO_PELOTERO


def sprites_de_formas() -> dict[str, np.ndarray]:
    sprites = {}
    for etiqueta in ETIQUETAS:
        sprite = np.zeros((_alto_de(etiqueta), 46, 3), dtype=np.uint8)
        sprite[:, :] = COLORES[etiqueta]
        sprite[:20, 12:34] = (196, 168, 140)  # cabeza
        sprites[etiqueta] = sprite
    return sprites


def sprites_de_personas() -> dict[str, np.ndarray]:
    """Recorta personas reales de las imagenes de ejemplo de ultralytics."""
    import cv2
    from ultralytics import YOLO
    from ultralytics.utils import ASSETS

    red = YOLO("yolov8n.pt")
    recortes: list[np.ndarray] = []
    for imagen in sorted(Path(ASSETS).glob("*.jpg")):
        bgr = cv2.imread(str(imagen))
        if bgr is None:
            continue
        resultado = red.predict(bgr, classes=[0], conf=0.5, verbose=False, device="cpu")[0]
        cajas = resultado.boxes
        if cajas is None:
            continue
        for caja in cajas.xyxy.cpu().numpy().astype(int):
            x0, y0, x1, y1 = caja
            if (x1 - x0) < 30 or (y1 - y0) < 60:
                continue
            recortes.append(cv2.cvtColor(bgr[y0:y1, x0:x1], cv2.COLOR_BGR2RGB))

    if not recortes:
        raise SystemExit("No se recorto ninguna persona de las imagenes de ejemplo.")

    recortes.sort(key=lambda r: -r.shape[0] * r.shape[1])
    # Las imagenes de ejemplo no siempre dan tantas personas como etiquetas: se
    # completan volteando las que hay. El sexto solo hace de entrenador que cruza.
    i = 0
    while len(recortes) < len(ETIQUETAS):
        recortes.append(recortes[i][:, ::-1].copy())
        i += 1
    sprites = {}
    for etiqueta, recorte in zip(ETIQUETAS, recortes):
        alto = _alto_de(etiqueta)
        ancho = max(20, int(recorte.shape[1] * alto / recorte.shape[0]))
        sprites[etiqueta] = cv2.resize(recorte, (ancho, alto), interpolation=cv2.INTER_AREA)
    return sprites


def _quien(t: float) -> str | None:
    for inicio, fin, etiqueta in GUION:
        if inicio <= t < fin:
            return etiqueta
    return None


def generar(destino: Path, sprites: dict[str, np.ndarray]) -> None:
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

    for n in range(int(DURACION * FPS)):
        t = n / FPS
        cuadro = fondo.copy()
        etiqueta = _quien(t)
        if etiqueta is not None:
            sprite = sprites[etiqueta]
            alto_p, ancho_p = sprite.shape[:2]
            # El pelotero se mueve dentro del cajon: sin jitter, la mediana temporal
            # aprenderia su silueta como si fuera fondo.
            jx = int(rng.normal(0, 6))
            jy = int(rng.normal(0, 4))
            if etiqueta == "cruce":
                jx = int(-rw / 2 + ((t - 350.0) / 8.0) * rw)  # cruza de lado a lado
                jy = 0
            x0 = int(np.clip(rx + rw // 2 - ancho_p // 2 + jx, 0, ANCHO - ancho_p))
            y0 = int(np.clip(ry + rh - alto_p - 8 + jy, 0, ALTO - alto_p))
            cuadro[y0 : y0 + alto_p, x0 : x0 + ancho_p] = sprite
        proc.stdin.write(cuadro.tobytes())

    proc.stdin.close()
    if proc.wait() != 0:
        raise SystemExit("ffmpeg fallo generando el fixture")


def main() -> None:
    parser = argparse.ArgumentParser(description="Genera la jornada sintetica de prueba.")
    parser.add_argument("--personas", action="store_true",
                        help="usar recortes de personas reales (necesario para probar YOLO)")
    args = parser.parse_args()

    raiz = Path(__file__).resolve().parents[1]
    carpeta = raiz / "fixtures"
    carpeta.mkdir(exist_ok=True)

    if args.personas:
        clave, sprites = "personas", sprites_de_personas()
    else:
        clave, sprites = "sintetica", sprites_de_formas()

    video = carpeta / f"jornada_{clave}.mp4"
    generar(video, sprites)

    rx, ry, rw, rh = ROI
    (carpeta / f"perfil_{clave}.json").write_text(json.dumps({
        "x": rx, "y": ry, "ancho": rw, "alto": rh,
        "video_ancho": ANCHO, "video_alto": ALTO,
        "creado": "", "origen": video.name,
    }, indent=2), encoding="utf-8")
    (carpeta / f"jornada_{clave}.esperado.json").write_text(
        json.dumps({"duracion": DURACION, "turnos": ESPERADO}, indent=2, ensure_ascii=False),
        encoding="utf-8")

    print(f"{video}  ({video.stat().st_size / 1e6:.1f} MB, {DURACION:.0f} s, "
          f"{len(ESPERADO)} turnos esperados)")


if __name__ == "__main__":
    main()
