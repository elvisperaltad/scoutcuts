# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

raiz = Path(SPECPATH)
ffmpeg = os.environ["CORTADOR_BUILD_FFMPEG"]
ffprobe = os.environ["CORTADOR_BUILD_FFPROBE"]

a = Analysis(
    [str(raiz / "tools" / "portable_entry.py")],
    pathex=[str(raiz / "src")],
    binaries=[(ffmpeg, "."), (ffprobe, ".")],
    datas=[(str(raiz / "perfiles" / "*.json"), "perfiles"),
           (str(raiz / "LEEME_QA.txt"), ".")],
    hiddenimports=[],
    excludes=[
        "torch", "torchvision", "ultralytics", "matplotlib", "PIL",
        "polars", "pandas", "scipy", "yaml", "psutil",
    ],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="CortadorTurnosQA",
          console=False, debug=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
               name="CortadorTurnosQA")
