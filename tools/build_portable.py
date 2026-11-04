"""Construye la carpeta y ZIP portátiles. Requiere el extra ``portable``."""

from __future__ import annotations

import os
import hashlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
BUILD = RAIZ / "build" / "portable"
DIST = RAIZ / "dist"
CARPETA = DIST / "CortadorTurnosQA"
ZIP = DIST / "CortadorTurnosQA-portable.zip"


def _binario(variable: str, nombre: str) -> Path:
    valor = os.environ.get(variable)
    hallado = Path(valor) if valor else None
    if hallado is None or not hallado.is_file():
        ruta = shutil.which(nombre)
        hallado = Path(ruta) if ruta else None
    if hallado is None or not hallado.is_file():
        raise SystemExit(f"No se encontró {nombre}; define {variable} o añádelo al PATH.")
    return hallado.resolve()


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError as err:
        raise SystemExit("Falta PyInstaller. Instala el extra: pip install -e .[portable]") from err

    ffmpeg = _binario("CORTADOR_FFMPEG", "ffmpeg")
    ffprobe = _binario("CORTADOR_FFPROBE", "ffprobe")
    # Sólo se limpian artefactos propiedad de este script.
    shutil.rmtree(BUILD, ignore_errors=True)
    shutil.rmtree(CARPETA, ignore_errors=True)
    ZIP.unlink(missing_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    DIST.mkdir(parents=True, exist_ok=True)
    entorno = os.environ.copy()
    entorno.update(CORTADOR_BUILD_FFMPEG=str(ffmpeg), CORTADOR_BUILD_FFPROBE=str(ffprobe))
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm",
        "--workpath", str(BUILD), "--distpath", str(DIST),
        str(RAIZ / "CortadorTurnosQA.spec"),
    ], cwd=RAIZ, env=entorno, check=True)
    shutil.copy2(RAIZ / "LEEME_QA.txt", CARPETA / "LEEME_QA.txt")
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as archivo:
        for ruta in sorted(CARPETA.rglob("*")):
            if ruta.is_file():
                archivo.write(ruta, (Path(CARPETA.name) / ruta.relative_to(CARPETA)).as_posix())
    suma = hashlib.sha256(ZIP.read_bytes()).hexdigest()
    ZIP.with_suffix(ZIP.suffix + ".sha256").write_text(
        f"{suma}  {ZIP.name}\n", encoding="ascii"
    )
    print(f"Carpeta: {CARPETA}\nZIP: {ZIP}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
