"""Construye la edición QA con el runtime embeddable oficial de Python.

No usa PyInstaller. El resultado conserva ``pythonw.exe`` tal como lo distribuye
Python.org y añade únicamente las dependencias que necesita Cortador.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import site
import sys
import sysconfig
import urllib.request
import zipfile
from pathlib import Path


RAIZ = Path(__file__).resolve().parents[1]
DIST = RAIZ / "dist"
NOMBRE = "CortadorTurnosQA-Portable"
CARPETA = DIST / NOMBRE
ZIP = DIST / f"{NOMBRE}.zip"
CACHE = RAIZ / "build" / "portable-runtime-cache"


def url_python_embeddable(version: tuple[int, int, int] | None = None) -> str:
    version = version or sys.version_info[:3]
    texto = ".".join(map(str, version))
    return f"https://www.python.org/ftp/python/{texto}/python-{texto}-embed-amd64.zip"


def resolver_python_embeddable(
    *, cache: Path = CACHE, entorno: dict[str, str] | None = None,
    version: tuple[int, int, int] | None = None,
) -> Path:
    entorno = os.environ if entorno is None else entorno
    local = entorno.get("CORTADOR_PYTHON_EMBED_ZIP")
    if local:
        ruta = Path(local).expanduser().resolve()
        if not ruta.is_file() or not zipfile.is_zipfile(ruta):
            raise SystemExit(f"CORTADOR_PYTHON_EMBED_ZIP no es un ZIP válido: {ruta}")
        return ruta

    url = url_python_embeddable(version)
    destino = cache / url.rsplit("/", 1)[-1]
    if not destino.is_file():
        cache.mkdir(parents=True, exist_ok=True)
        temporal = destino.with_suffix(".zip.part")
        try:
            urllib.request.urlretrieve(url, temporal)
            if not zipfile.is_zipfile(temporal):
                raise RuntimeError("la descarga no es un ZIP válido")
            temporal.replace(destino)
        except Exception as err:
            temporal.unlink(missing_ok=True)
            raise SystemExit(f"No se pudo descargar el runtime oficial desde {url}: {err}") from err
    return destino


def _extraer_zip(origen: Path, destino: Path) -> None:
    destino.mkdir(parents=True, exist_ok=True)
    base = destino.resolve()
    with zipfile.ZipFile(origen) as archivo:
        for miembro in archivo.infolist():
            salida = (destino / miembro.filename).resolve()
            if salida != base and base not in salida.parents:
                raise SystemExit(f"Ruta insegura en ZIP embeddable: {miembro.filename}")
        archivo.extractall(destino)


def configurar_pth(runtime: Path, version: tuple[int, int] | None = None) -> Path:
    version = version or sys.version_info[:2]
    nombre = f"python{version[0]}{version[1]}._pth"
    ruta = runtime / nombre
    if not ruta.exists():
        candidatos = list(runtime.glob("python*._pth"))
        if len(candidatos) == 1:
            ruta = candidatos[0]
        else:
            raise SystemExit(f"El runtime no contiene {nombre}")
    ruta.write_text(
        f"python{version[0]}{version[1]}.zip\n.\n../packages\nimport site\n",
        encoding="utf-8", newline="\n",
    )
    return ruta


def seleccionar_paquetes(site_packages: Path) -> list[Path]:
    """Devuelve sólo NumPy/OpenCV y sus metadatos, nunca dependencias opcionales."""
    permitidos: list[Path] = []
    for nombre in ("numpy", "numpy.libs", "cv2"):
        ruta = site_packages / nombre
        if not ruta.exists():
            raise SystemExit(f"Falta {nombre} en el entorno actual: {site_packages}")
        permitidos.append(ruta)
    for patron, etiqueta in (("numpy-*.dist-info", "numpy dist-info"),
                             ("opencv*.dist-info", "opencv dist-info")):
        hallados = sorted(site_packages.glob(patron))
        if not hallados:
            raise SystemExit(f"Falta {etiqueta} en el entorno actual: {site_packages}")
        permitidos.extend(hallados)
    return permitidos


def site_packages_actual() -> Path:
    candidatos = [Path(p) for p in site.getsitepackages()]
    puro = Path(sysconfig.get_paths()["purelib"])
    for candidato in [puro, *candidatos]:
        if (candidato / "numpy").exists() and (candidato / "cv2").exists():
            return candidato
    raise SystemExit("El intérprete que ejecuta el builder no tiene numpy y cv2 instalados.")


def _copiar_arbol(origen: Path, destino: Path) -> None:
    carpetas_excluidas = {
        "__pycache__", ".pytest_cache", "test", "tests", "cache", "caches",
        "secret", "secrets",
    }

    def ignorar(_directorio: str, nombres: list[str]) -> set[str]:
        return {
            nombre for nombre in nombres
            if nombre.casefold() in carpetas_excluidas
            or nombre.casefold() == ".env"
            or nombre.casefold().endswith((".pyc", ".pyo"))
        }

    shutil.copytree(
        origen, destino, ignore=ignorar,
    )


def copiar_paquetes(site_packages: Path, src_cortador: Path, destino: Path) -> None:
    destino.mkdir(parents=True, exist_ok=True)
    for origen in seleccionar_paquetes(site_packages):
        salida = destino / origen.name
        if origen.is_dir():
            _copiar_arbol(origen, salida)
        else:
            shutil.copy2(origen, salida)
    _copiar_arbol(src_cortador, destino / "cortador")


def resolver_tk(base_prefix: Path | None = None, ejecutable: Path | None = None) -> dict[str, Path]:
    base = Path(sys.base_prefix if base_prefix is None else base_prefix)
    exe = Path(sys.executable if ejecutable is None else ejecutable)
    directorios = [base / "DLLs", exe.parent / "DLLs", exe.parent]

    def archivo(nombre: str) -> Path:
        for directorio in directorios:
            candidato = directorio / nombre
            if candidato.is_file():
                return candidato
        raise SystemExit(f"Falta {nombre} en la instalación de Python usada por el builder.")

    recursos = {
        nombre: archivo(nombre)
        for nombre in ("_tkinter.pyd", "tcl86t.dll", "tk86t.dll", "zlib1.dll")
    }
    for relativo, clave in ((Path("tcl") / "tcl8.6", "tcl8.6"),
                            (Path("tcl") / "tk8.6", "tk8.6")):
        ruta = base / relativo
        if not ruta.is_dir():
            raise SystemExit(f"Falta {ruta}; se necesita una instalación de Python con Tk 8.6.")
        recursos[clave] = ruta
    tkinter = base / "Lib" / "tkinter"
    if not tkinter.is_dir():
        raise SystemExit(f"Falta {tkinter}; se necesita el paquete estándar tkinter.")
    recursos["tkinter"] = tkinter
    return recursos


def copiar_tk(runtime: Path, recursos: dict[str, Path]) -> None:
    for nombre in ("_tkinter.pyd", "tcl86t.dll", "tk86t.dll", "zlib1.dll"):
        shutil.copy2(recursos[nombre], runtime / nombre)
    _copiar_arbol(recursos["tcl8.6"], runtime / "tcl" / "tcl8.6")
    _copiar_arbol(recursos["tk8.6"], runtime / "tcl" / "tk8.6")
    _copiar_arbol(recursos["tkinter"], runtime.parent / "packages" / "tkinter")


def resolver_binario(variable: str, nombre: str, entorno: dict[str, str] | None = None) -> Path:
    entorno = os.environ if entorno is None else entorno
    valor = entorno.get(variable)
    hallado = Path(valor) if valor else None
    if hallado is None or not hallado.is_file():
        ruta = shutil.which(nombre)
        hallado = Path(ruta) if ruta else None
    if hallado is None or not hallado.is_file():
        raise SystemExit(f"No se encontró {nombre}; define {variable} o añádelo al PATH.")
    return hallado.resolve()


def crear_launchers(destino: Path) -> None:
    (destino / "app_launcher.pyw").write_text(
        """from pathlib import Path
import sys
import traceback

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / "packages"))
try:
    from cortador.app import abrir
    abrir()
except BaseException:
    try:
        datos = BASE / "DatosQA"
        datos.mkdir(exist_ok=True)
        with (datos / "app.log").open("a", encoding="utf-8") as log:
            log.write("ERROR: fallo al iniciar la aplicación\\n")
            traceback.print_exc(file=log)
    except Exception:
        pass
""", encoding="utf-8", newline="\n",
    )
    (destino / "INICIAR_CORTADOR.bat").write_text(
        '@echo off\r\nset "CORTADOR_FFMPEG=%~dp0bin\\ffmpeg.exe"\r\n'
        'set "CORTADOR_FFPROBE=%~dp0bin\\ffprobe.exe"\r\n'
        'set "TCL_LIBRARY=%~dp0runtime\\tcl\\tcl8.6"\r\n'
        'set "TK_LIBRARY=%~dp0runtime\\tcl\\tk8.6"\r\n'
        'start "" "%~dp0runtime\\pythonw.exe" "%~dp0app_launcher.pyw"\r\n',
        encoding="utf-8", newline="",
    )
    (destino / "DIAGNOSTICO.bat").write_text(
        '@echo off\r\nsetlocal\r\nset "CORTADOR_FFMPEG=%~dp0bin\\ffmpeg.exe"\r\n'
        'set "CORTADOR_FFPROBE=%~dp0bin\\ffprobe.exe"\r\n'
        'set "TCL_LIBRARY=%~dp0runtime\\tcl\\tcl8.6"\r\n'
        'set "TK_LIBRARY=%~dp0runtime\\tcl\\tk8.6"\r\n'
        '"%~dp0runtime\\python.exe" -c "import os,sys; sys.path.insert(0,os.path.join(os.path.dirname(sys.executable),\'..\',\'packages\')); import tkinter,numpy,cv2,cortador; assert os.path.isfile(os.environ[\'CORTADOR_FFMPEG\']); assert os.path.isfile(os.environ[\'CORTADOR_FFPROBE\']); print(\'OK: tkinter, numpy, cv2, cortador, FFmpeg y FFprobe\')"\r\n'
        'if errorlevel 1 echo ERROR: el diagnostico fallo. Copie todo este texto al equipo tecnico.\r\n'
        'pause\r\n', encoding="utf-8", newline="",
    )


def crear_zip(carpeta: Path, destino_zip: Path) -> Path:
    """Empaqueta sólo archivos de la carpeta preparada, bajo una raíz única."""
    archivos_raiz = {
        "app_launcher.pyw", "iniciar_cortador.bat", "diagnostico.bat", "leeme_qa.txt",
    }
    directorios_raiz = {"runtime", "packages", "bin", "perfiles"}
    prohibidos = {
        "datosqa", ".env", "video", "videos", "resultados", "salida",
        "test", "tests", "cache", "caches", "secret", "secrets", "__pycache__",
    }
    extensiones_video = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
    destino_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destino_zip, "w", zipfile.ZIP_DEFLATED) as archivo:
        for ruta in sorted(carpeta.rglob("*")):
            relativo = ruta.relative_to(carpeta)
            raiz_permitida = (
                len(relativo.parts) == 1 and relativo.name.casefold() in archivos_raiz
            ) or relativo.parts[0].casefold() in directorios_raiz
            es_prohibido = (
                any(parte.casefold() in prohibidos for parte in relativo.parts)
                or ruta.suffix.casefold() in extensiones_video
            )
            if ruta.is_file() and raiz_permitida and not es_prohibido:
                archivo.write(ruta, (Path(carpeta.name) / relativo).as_posix())
    suma = hashlib.sha256(destino_zip.read_bytes()).hexdigest()
    checksum = destino_zip.with_suffix(destino_zip.suffix + ".sha256")
    checksum.write_text(f"{suma}  {destino_zip.name}\n", encoding="ascii")
    return checksum


def construir(
    *, raiz: Path = RAIZ, carpeta: Path = CARPETA, destino_zip: Path = ZIP,
    embed_zip: Path | None = None, paquetes: Path | None = None,
    tk: dict[str, Path] | None = None, ffmpeg: Path | None = None,
    ffprobe: Path | None = None,
) -> None:
    shutil.rmtree(carpeta, ignore_errors=True)
    destino_zip.unlink(missing_ok=True)
    destino_zip.with_suffix(destino_zip.suffix + ".sha256").unlink(missing_ok=True)
    runtime = carpeta / "runtime"
    _extraer_zip(embed_zip or resolver_python_embeddable(), runtime)
    configurar_pth(runtime)
    copiar_tk(runtime, tk or resolver_tk())
    copiar_paquetes(paquetes or site_packages_actual(), raiz / "src" / "cortador", carpeta / "packages")
    binarios = carpeta / "bin"
    binarios.mkdir(parents=True)
    shutil.copy2(ffmpeg or resolver_binario("CORTADOR_FFMPEG", "ffmpeg"), binarios / "ffmpeg.exe")
    shutil.copy2(ffprobe or resolver_binario("CORTADOR_FFPROBE", "ffprobe"), binarios / "ffprobe.exe")
    perfiles = carpeta / "perfiles"
    perfiles.mkdir()
    for perfil in sorted((raiz / "perfiles").glob("*.json")):
        shutil.copy2(perfil, perfiles / perfil.name)
    shutil.copy2(raiz / "LEEME_QA.txt", carpeta / "LEEME_QA.txt")
    crear_launchers(carpeta)
    crear_zip(carpeta, destino_zip)


def main() -> int:
    if os.name != "nt":
        raise SystemExit("Este builder sólo funciona en Windows.")
    construir()
    print(f"Carpeta: {CARPETA}\nZIP: {ZIP}\nChecksum: {ZIP}.sha256")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
