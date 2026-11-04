"""Pruebas del script bash `despliegue/limpiar-releases-viejas.sh`.

Verifica el comportamiento real: conserva las ultimas N releases por orden
cronologico (el nombre ES el timestamp), borra el resto, y NUNCA borra la
release actualmente activa (destino del symlink), incluso si quedara fuera
de las ultimas N por cualquier motivo.

Nota sobre Windows sin privilegio elevado: las dos pruebas que dependen de
un symlink real (`test_conserva_...` y `test_nunca_borra_la_activa...`) se
SALTAN explicitamente en una maquina Windows sin "Developer Mode" ni
SeCreateSymbolicLinkPrivilege, porque ahi `ln -s` dentro de MSYS devuelve
exit 0 pero crea una carpeta normal vacia en vez de un symlink real, sin
reportar ningun error -- confirmado invocandolo directamente e inspeccionando
el resultado con `[ -L ... ]`. Saltar es honesto; fingir que paso seria
validar un escenario que nunca ocurrio. El comportamiento critico (nunca
borrar la release activa aunque sea la mas vieja) SI fue verificado de
forma real, con symlinks nativos, corriendo el script dos veces contra el
servidor Linux de produccion en una carpeta de prueba aislada
(`/tmp/prueba_limpieza*`, borrada despues): con la activa como la mas
vieja de 7, conservo las ultimas 5 cronologicas MAS la activa (borro solo
1 de 7); con la activa entre las ultimas 5, conservo exactamente esas 5
(borro 2 de 7). Ver BITACORA.md, entrada de rotacion de releases, 2026-11-04.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
SCRIPT = RAIZ / "despliegue" / "limpiar-releases-viejas.sh"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" and not Path("/usr/bin/bash").exists()
    and not Path("C:/Program Files/Git/bin/bash.exe").exists(),
    reason="hace falta bash para correr este script",
)


def _bash() -> str:
    candidato = Path("C:/Program Files/Git/bin/bash.exe")
    return str(candidato) if candidato.exists() else "bash"


def _crear_releases(tmp_path: Path, nombres: list[str]) -> Path:
    releases = tmp_path / "releases-app"
    releases.mkdir()
    for nombre in nombres:
        (releases / nombre).mkdir()
        (releases / nombre / "marca.txt").write_text(nombre)
    return releases


def _crear_symlink(enlace: Path, destino: Path) -> None:
    """Crea un symlink real sin requerir privilegios de administrador en
    Windows: `os.symlink`/`Path.symlink_to` fallan ahi sin elevacion, pero
    `ln -s` dentro de Git Bash (el mismo bash que ya usamos para correr el
    script) si puede -- EXCEPTO en una maquina sin "Developer Mode" ni el
    privilegio SeCreateSymbolicLinkPrivilege, donde ni siquiera `ln -s`
    puede. En ese caso la prueba se salta con un motivo explicito: no es
    un comportamiento de Windows que se este fingiendo (serian necesarios
    symlinks reales para que el script, igual que `desplegar.sh` en el
    servidor real via `ln -sfn`, pueda distinguir la release activa), sino
    una capacidad del sistema operativo ausente en este entorno concreto.
    """
    resultado = subprocess.run(
        [_bash(), "-c", 'ln -s "$1" "$2"', "--", str(destino), str(enlace)],
        capture_output=True, text=True,
    )
    # MSYS puede devolver exit 0 y crear una carpeta normal (vacia) en vez
    # de un symlink real cuando falta el privilegio de Windows para
    # symlinks -- sin reportar ningun error. Por eso no basta con mirar el
    # returncode: hay que verificar con `[ -L ... ]` que de verdad quedo un
    # symlink, o la prueba estaria validando un escenario que no ocurrio.
    es_symlink = subprocess.run(
        [_bash(), "-c", f'[ -L "{enlace}" ]'],
    ).returncode == 0
    if resultado.returncode != 0 or not es_symlink:
        pytest.skip(
            "esta maquina no puede crear symlinks reales sin privilegio "
            f"elevado (ln -s devolvio {resultado.returncode}, es_symlink="
            f"{es_symlink}, stderr: {resultado.stderr.strip()})"
        )


def _correr(releases: Path, app_symlink: Path | None, conservar: int = 5):
    args = [_bash(), str(SCRIPT), str(conservar)]
    entorno = {"RELEASES": str(releases)}
    if app_symlink is not None:
        entorno["APP"] = str(app_symlink)
    import os
    entorno_completo = dict(os.environ)
    entorno_completo.update(entorno)
    return subprocess.run(
        args, env=entorno_completo, capture_output=True, text=True, timeout=30,
    )


def test_conserva_solo_las_ultimas_n_por_orden_cronologico(tmp_path):
    nombres = [f"2026110{d}000000" for d in range(1, 8)]  # 7 releases
    releases = _crear_releases(tmp_path, nombres)
    app = tmp_path / "app"
    _crear_symlink(app, releases / nombres[-1])

    resultado = _correr(releases, app, conservar=5)

    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    restantes = sorted(p.name for p in releases.iterdir())
    assert restantes == nombres[-5:]


def test_nunca_borra_la_release_actualmente_activa_aunque_sea_vieja(tmp_path):
    nombres = [f"2026110{d}000000" for d in range(1, 8)]
    releases = _crear_releases(tmp_path, nombres)
    app = tmp_path / "app"
    # La activa es la MAS VIEJA, fuera de las ultimas 5 por cronologia.
    _crear_symlink(app, releases / nombres[0])

    resultado = _correr(releases, app, conservar=5)

    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    restantes = {p.name for p in releases.iterdir()}
    assert nombres[0] in restantes, (
        "la release activa se borro aunque era la mas vieja: "
        f"restantes={restantes}"
    )
    # Las ultimas 5 cronologicas tambien deben seguir.
    assert set(nombres[-5:]).issubset(restantes)


def test_menos_releases_que_el_limite_no_borra_nada(tmp_path):
    nombres = ["20261101000000", "20261102000000"]
    releases = _crear_releases(tmp_path, nombres)

    resultado = _correr(releases, None, conservar=5)

    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    restantes = sorted(p.name for p in releases.iterdir())
    assert restantes == nombres


def test_carpeta_de_releases_inexistente_no_falla(tmp_path):
    releases = tmp_path / "no-existe"

    resultado = _correr(releases, None, conservar=5)

    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
