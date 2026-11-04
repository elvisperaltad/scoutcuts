import sys
import zipfile
from pathlib import Path

import pytest

from tools import build_portable_runtime as builder


def _archivo(ruta: Path, contenido: bytes = b"x") -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(contenido)
    return ruta


def _arbol_fake(tmp_path: Path):
    raiz = tmp_path / "proyecto"
    _archivo(raiz / "src" / "cortador" / "__init__.py", b"")
    _archivo(raiz / "src" / "cortador" / "app.py", b"def abrir(): pass\n")
    _archivo(raiz / "src" / "cortador" / "__pycache__" / "app.pyc")
    _archivo(raiz / "perfiles" / "qa.json", b"{}")
    _archivo(raiz / "LEEME_QA.txt", b"QA")

    paquetes = tmp_path / "site-packages"
    for nombre in ("numpy", "numpy.libs", "numpy-2.0.dist-info", "cv2",
                   "opencv_python-4.10.dist-info", "torch", "ultralytics"):
        _archivo(paquetes / nombre / "contenido.bin")

    base = tmp_path / "python-instalado"
    recursos = {
        nombre: _archivo(base / "DLLs" / nombre)
        for nombre in ("_tkinter.pyd", "tcl86t.dll", "tk86t.dll", "zlib1.dll")
    }
    recursos["tcl8.6"] = _archivo(base / "tcl" / "tcl8.6" / "init.tcl").parent
    recursos["tk8.6"] = _archivo(base / "tcl" / "tk8.6" / "tk.tcl").parent
    recursos["tkinter"] = _archivo(base / "Lib" / "tkinter" / "__init__.py", b"").parent

    embed = tmp_path / "python-embed.zip"
    mayor, menor = sys.version_info[:2]
    with zipfile.ZipFile(embed, "w") as archivo:
        archivo.writestr("python.exe", b"python")
        archivo.writestr("pythonw.exe", b"pythonw")
        archivo.writestr(f"python{mayor}{menor}.zip", b"stdlib")
        archivo.writestr(f"python{mayor}{menor}._pth", b"old")
    return raiz, paquetes, recursos, embed


def test_url_y_override_local(tmp_path):
    zip_local = tmp_path / "embed.zip"
    with zipfile.ZipFile(zip_local, "w") as archivo:
        archivo.writestr("python.exe", b"x")

    assert builder.url_python_embeddable((3, 13, 7)).endswith(
        "/3.13.7/python-3.13.7-embed-amd64.zip"
    )
    assert builder.resolver_python_embeddable(
        entorno={"CORTADOR_PYTHON_EMBED_ZIP": str(zip_local)}
    ) == zip_local.resolve()


def test_configurar_pth(tmp_path):
    pth = _archivo(tmp_path / "python312._pth", b"anterior")
    builder.configurar_pth(tmp_path, (3, 12))
    assert pth.read_text(encoding="utf-8").splitlines() == [
        "python312.zip", ".", "../packages", "import site"
    ]


def test_seleccion_excluye_dependencias_cnn(tmp_path):
    _, paquetes, _, _ = _arbol_fake(tmp_path)
    nombres = {ruta.name for ruta in builder.seleccionar_paquetes(paquetes)}
    assert nombres == {
        "numpy", "numpy.libs", "numpy-2.0.dist-info", "cv2",
        "opencv_python-4.10.dist-info",
    }
    assert "torch" not in nombres
    assert "ultralytics" not in nombres


def test_construccion_fake_y_zip_por_lista_positiva(tmp_path):
    raiz, paquetes, recursos, embed = _arbol_fake(tmp_path)
    carpeta = tmp_path / builder.NOMBRE
    destino_zip = tmp_path / f"{builder.NOMBRE}.zip"
    ffmpeg = _archivo(tmp_path / "ffmpeg.exe")
    ffprobe = _archivo(tmp_path / "ffprobe.exe")

    builder.construir(
        raiz=raiz, carpeta=carpeta, destino_zip=destino_zip,
        embed_zip=embed, paquetes=paquetes, tk=recursos,
        ffmpeg=ffmpeg, ffprobe=ffprobe,
    )

    assert (carpeta / "runtime" / "pythonw.exe").is_file()
    assert (carpeta / "runtime" / "tcl" / "tk8.6" / "tk.tcl").is_file()
    pth = next((carpeta / "runtime").glob("python*._pth"))
    assert "../packages" in pth.read_text(encoding="utf-8")
    assert not (carpeta / "packages" / "torch").exists()
    assert not list((carpeta / "packages" / "cortador").rglob("*.pyc"))
    compile((carpeta / "app_launcher.pyw").read_text(encoding="utf-8"),
            "app_launcher.pyw", "exec")
    inicio = (carpeta / "INICIAR_CORTADOR.bat").read_text(encoding="utf-8")
    assert "start \"\" \"%~dp0runtime\\pythonw.exe\"" in inicio
    assert "CORTADOR_FFMPEG=%~dp0bin\\ffmpeg.exe" in inicio
    diagnostico = (carpeta / "DIAGNOSTICO.bat").read_text(encoding="utf-8")
    assert "runtime\\python.exe" in diagnostico
    assert "import tkinter,numpy,cv2,cortador" in diagnostico

    _archivo(carpeta / ".env", b"SECRETO")
    _archivo(carpeta / "nota_privada.txt", b"SECRETO")
    _archivo(carpeta / "DatosQA" / "app.log", b"privado")
    _archivo(carpeta / "Resultados" / "video.mp4", b"video")
    builder.crear_zip(carpeta, destino_zip)
    with zipfile.ZipFile(destino_zip) as archivo:
        nombres = archivo.namelist()
    assert nombres
    assert all(nombre.startswith(builder.NOMBRE + "/") for nombre in nombres)
    assert not any(".env" in nombre or "nota_privada" in nombre or
                   "DatosQA" in nombre or "Resultados" in nombre for nombre in nombres)
    assert destino_zip.with_suffix(".zip.sha256").is_file()


def test_tk_falla_con_mensaje_claro(tmp_path):
    with pytest.raises(SystemExit, match="_tkinter.pyd"):
        builder.resolver_tk(tmp_path, tmp_path / "python.exe")
