"""Pruebas del script bash `despliegue/rotar-token-qa.sh`.

Verifica el comportamiento real: rota el token preservando el resto del
archivo, respalda el valor anterior, y REVIERTE automaticamente si el
servicio no vuelve a responder 200 con el token nuevo -- la red de
seguridad que justifica automatizar esto en vez de dejarlo "a mano".

`systemctl` no existe en esta maquina de pruebas (ni en CI sin systemd), asi
que se sustituye por un script `systemctl` falso que los tests colocan al
principio del PATH; el script real nunca necesita saber que es falso.
"""

from __future__ import annotations

import http.server
import os
import stat
import subprocess
import sys
import threading
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
SCRIPT = RAIZ / "despliegue" / "rotar-token-qa.sh"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" and not Path("/usr/bin/bash").exists()
    and not Path("C:/Program Files/Git/bin/bash.exe").exists(),
    reason="hace falta bash para correr este script",
)


class _ServidorSalud(http.server.BaseHTTPRequestHandler):
    codigo_respuesta: int = 200

    def do_GET(self):  # noqa: N802
        self.send_response(type(self).codigo_respuesta)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *_args):
        pass


def _bash() -> str:
    candidato = Path("C:/Program Files/Git/bin/bash.exe")
    return str(candidato) if candidato.exists() else "bash"


def _levantar_servidor_salud(codigo: int):
    _ServidorSalud.codigo_respuesta = codigo
    servidor = http.server.HTTPServer(("127.0.0.1", 0), _ServidorSalud)
    puerto = servidor.server_address[1]
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    return servidor, hilo, puerto


def _instalar_systemctl_falso(tmp_path: Path) -> Path:
    """Crea un `systemctl` falso (no-op exitoso) y devuelve su carpeta."""
    bin_dir = tmp_path / "bin_falso"
    bin_dir.mkdir()
    shim = bin_dir / "systemctl"
    shim.write_text("#!/usr/bin/env bash\nexit 0\n")
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    return bin_dir


def _correr_rotacion(tmp_path, *, envf: Path, salud_url: str):
    bin_falso = _instalar_systemctl_falso(tmp_path)
    entorno = dict(os.environ)
    entorno["PATH"] = f"{bin_falso}{os.pathsep}{entorno.get('PATH', '')}"
    entorno["ENVF"] = str(envf)
    entorno["SERVICE"] = "scoutcuts-de-prueba.service"
    entorno["SALUD_URL"] = salud_url
    return subprocess.run(
        [_bash(), str(SCRIPT)],
        env=entorno, capture_output=True, text=True, timeout=30,
    )


def _crear_app_env(tmp_path: Path, token_actual: str) -> Path:
    envf = tmp_path / "app.env"
    envf.write_text(
        f"SCOUTCUTS_TOKEN_QA={token_actual}\n"
        "SCOUTCUTS_DATOS=/opt/cortador-control/datos\n"
        "SCOUTCUTS_ENTREGA_NGINX=1\n"
    )
    return envf


def test_rota_el_token_y_preserva_el_resto_del_archivo(tmp_path):
    envf = _crear_app_env(tmp_path, "token-viejo-de-prueba")
    servidor, hilo, puerto = _levantar_servidor_salud(200)
    try:
        resultado = _correr_rotacion(
            tmp_path, envf=envf, salud_url=f"http://127.0.0.1:{puerto}/salud",
        )
    finally:
        servidor.shutdown()
        hilo.join(timeout=5)

    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    contenido = envf.read_text()
    assert "token-viejo-de-prueba" not in contenido
    assert "SCOUTCUTS_DATOS=/opt/cortador-control/datos" in contenido
    assert "SCOUTCUTS_ENTREGA_NGINX=1" in contenido
    # El valor nuevo nunca aparece en la salida del script.
    nueva_linea = [l for l in contenido.splitlines() if l.startswith("SCOUTCUTS_TOKEN_QA=")][0]
    nuevo_token = nueva_linea.split("=", 1)[1]
    assert nuevo_token not in resultado.stdout
    assert nuevo_token not in resultado.stderr


def test_respalda_el_token_anterior_en_un_archivo_bak(tmp_path):
    envf = _crear_app_env(tmp_path, "token-a-respaldar")
    servidor, hilo, puerto = _levantar_servidor_salud(200)
    try:
        resultado = _correr_rotacion(
            tmp_path, envf=envf, salud_url=f"http://127.0.0.1:{puerto}/salud",
        )
    finally:
        servidor.shutdown()
        hilo.join(timeout=5)

    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    respaldos = list(tmp_path.glob("app.env.bak-*"))
    assert len(respaldos) == 1
    assert "token-a-respaldar" in respaldos[0].read_text()


def test_si_el_servicio_no_vuelve_a_responder_200_revierte_al_token_anterior(tmp_path):
    envf = _crear_app_env(tmp_path, "token-que-debe-sobrevivir")
    servidor, hilo, puerto = _levantar_servidor_salud(503)
    try:
        resultado = _correr_rotacion(
            tmp_path, envf=envf, salud_url=f"http://127.0.0.1:{puerto}/salud",
        )
    finally:
        servidor.shutdown()
        hilo.join(timeout=5)

    assert resultado.returncode == 1, resultado.stdout + resultado.stderr
    assert "token-que-debe-sobrevivir" in envf.read_text(), (
        "el script debio revertir al token anterior cuando /salud no "
        f"volvio a responder 200 (salida: {resultado.stdout}\n{resultado.stderr})"
    )


def test_sin_archivo_de_variables_falla_sin_tocar_nada(tmp_path):
    envf = tmp_path / "no-existe.env"
    resultado = _correr_rotacion(
        tmp_path, envf=envf, salud_url="http://127.0.0.1:1/salud",
    )
    assert resultado.returncode == 1
    assert not envf.exists()
