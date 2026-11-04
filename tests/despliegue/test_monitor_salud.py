"""Pruebas del script bash `despliegue/monitor-salud.sh`.

Verifica el comportamiento real del script (no solo que "compile"): que
detecta un fallo real contra una ruta de salud falsa, que alerta por
Telegram SOLO en la transicion de estado (no en cada corrida) y que se
recupera limpiamente cuando el servicio vuelve a responder 200.

Como `systemctl is-active scoutcuts/nginx` no tiene sentido fuera de un
servidor systemd real, las pruebas fuerzan el fallo/exito unicamente a
traves de `API_SALUD` (apuntado a un servidor HTTP falso en localhost) y
dejan que la deteccion de systemctl falle o pase segun el entorno de
pruebas; por eso se valida el mensaje de alerta por contenido relevante
("api/salud" o similar), no por igualdad exacta con todo el texto.
"""

from __future__ import annotations

import http.server
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
SCRIPT = RAIZ / "despliegue" / "monitor-salud.sh"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" and not Path("/usr/bin/bash").exists()
    and not Path("C:/Program Files/Git/bin/bash.exe").exists(),
    reason="hace falta bash para correr este script",
)


class _ServidorFalso(http.server.BaseHTTPRequestHandler):
    """Responde con el codigo HTTP fijado en la clase y registra cada request."""

    codigo_respuesta: int = 200
    peticiones: list[str] = []

    def do_GET(self):  # noqa: N802
        type(self).peticiones.append(self.path)
        self.send_response(type(self).codigo_respuesta)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def do_POST(self):  # noqa: N802
        type(self).peticiones.append(self.path)
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *_args):
        pass


def _bash() -> str:
    candidato = Path("C:/Program Files/Git/bin/bash.exe")
    return str(candidato) if candidato.exists() else "bash"


def _levantar_servidor_falso(codigo: int):
    _ServidorFalso.codigo_respuesta = codigo
    _ServidorFalso.peticiones = []
    servidor = http.server.HTTPServer(("127.0.0.1", 0), _ServidorFalso)
    puerto = servidor.server_address[1]
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    return servidor, hilo, puerto


def _correr_monitor(tmp_path, *, salud_url: str, token: str = "", admin_id: str = ""):
    entorno = dict(os.environ)
    entorno["API_SALUD"] = salud_url
    entorno["ESTADO_ARCHIVO"] = str(tmp_path / "monitor_estado")
    entorno["SCOUTCUTS_TELEGRAM_BOT_TOKEN"] = token
    entorno["SCOUTCUTS_TELEGRAM_ADMIN_ID"] = admin_id
    return subprocess.run(
        [_bash(), str(SCRIPT)],
        env=entorno, capture_output=True, text=True, timeout=30,
    )


def test_todo_sano_termina_en_0_y_no_alerta(tmp_path):
    servidor, hilo, puerto = _levantar_servidor_falso(200)
    try:
        resultado = _correr_monitor(
            tmp_path, salud_url=f"http://127.0.0.1:{puerto}/salud",
        )
    finally:
        servidor.shutdown()
        hilo.join(timeout=5)

    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    estado = (tmp_path / "monitor_estado").read_text().strip()
    assert estado == "ok"


def test_fallo_real_se_detecta_y_el_estado_queda_en_fallo(tmp_path):
    servidor, hilo, puerto = _levantar_servidor_falso(503)
    try:
        resultado = _correr_monitor(
            tmp_path, salud_url=f"http://127.0.0.1:{puerto}/salud",
        )
    finally:
        servidor.shutdown()
        hilo.join(timeout=5)

    assert resultado.returncode == 1, resultado.stdout + resultado.stderr
    estado = (tmp_path / "monitor_estado").read_text().strip()
    assert estado == "fallo"
    assert "503" in (resultado.stdout + resultado.stderr)


def test_alerta_solo_en_la_transicion_no_en_cada_corrida(tmp_path):
    """Dos fallos seguidos deben generar solo UNA alerta real; la segunda
    corrida, con el estado ya en 'fallo', no debe volver a disparar la
    deteccion inicial (el guard de transicion vive en el propio script,
    antes de intentar avisar por Telegram)."""
    servidor, hilo, puerto = _levantar_servidor_falso(503)
    try:
        entorno = dict(os.environ)
        entorno["API_SALUD"] = f"http://127.0.0.1:{puerto}/salud"
        entorno["ESTADO_ARCHIVO"] = str(tmp_path / "monitor_estado")
        # Sin token/admin_id: el script no intenta llamar a la API real de
        # Telegram, pero el guard de transicion (que es lo que esta prueba
        # verifica) funciona igual, por logs locales.
        r1 = subprocess.run(
            [_bash(), str(SCRIPT)], env=entorno,
            capture_output=True, text=True, timeout=30,
        )
        r2 = subprocess.run(
            [_bash(), str(SCRIPT)], env=entorno,
            capture_output=True, text=True, timeout=30,
        )
    finally:
        servidor.shutdown()
        hilo.join(timeout=5)

    assert r1.returncode == 1, r1.stdout + r1.stderr
    assert r2.returncode == 1, r2.stdout + r2.stderr
    # La primera corrida SI anuncia el problema detectado.
    assert "problema detectado" in (r1.stdout + r1.stderr)
    # La segunda, con el estado ya en "fallo", NO debe repetir el aviso de
    # deteccion: es exactamente el guard que evita inundar al admin.
    assert "problema detectado" not in (r2.stdout + r2.stderr)
    estado = (tmp_path / "monitor_estado").read_text().strip()
    assert estado == "fallo"


def test_recuperacion_cambia_el_estado_a_ok(tmp_path):
    (tmp_path / "monitor_estado").write_text("fallo")
    servidor, hilo, puerto = _levantar_servidor_falso(200)
    try:
        resultado = _correr_monitor(
            tmp_path, salud_url=f"http://127.0.0.1:{puerto}/salud",
        )
    finally:
        servidor.shutdown()
        hilo.join(timeout=5)

    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    estado = (tmp_path / "monitor_estado").read_text().strip()
    assert estado == "ok"
