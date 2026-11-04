import sys
from pathlib import Path


def test_ffmpeg_prefiere_binarios_empaquetados(tmp_path, monkeypatch):
    from cortador import ffmpeg

    (tmp_path / "ffmpeg.exe").write_bytes(b"")
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "ffprobe.exe").write_bytes(b"")
    monkeypatch.delenv("CORTADOR_FFMPEG", raising=False)
    monkeypatch.delenv("CORTADOR_FFPROBE", raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(ffmpeg.shutil, "which", lambda _: "C:/PATH/no-usar.exe")

    assert Path(ffmpeg.ruta_ffmpeg()) == tmp_path / "ffmpeg.exe"
    assert Path(ffmpeg.ruta_ffprobe()) == tmp_path / "bin" / "ffprobe.exe"


def test_recursos_empaquetados(tmp_path, monkeypatch):
    from cortador import qa

    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert qa.recursos("perfiles") == tmp_path / "perfiles"
