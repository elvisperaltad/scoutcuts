"""Prueba del script bash `despliegue/verificar-despliegue.sh`.

El script manda peticiones autenticadas de verdad contra la API en
produccion; para poder probarlo sin tocar el servidor real, se levanta un
servidor HTTP falso en localhost que registra que header de Authorization
recibio cada peticion, y se apunta el script a el con la variable de
entorno API (igual que ya se puede apuntar TOKEN; antes de esta prueba
`API` estaba fijo en el script, asi que no habia forma de probarlo sin
tocar produccion real).

Protege contra la regresion que ya tuvo este script una vez (ver
BITACORA.md: "El script de verificacion no verificaba nada"): mandar un
token literal o vacio en vez del real, lo que hace que CUALQUIER
despliegue sano reporte 401 en las rutas autenticadas y el script
termine en "NO verificado" sin que nada este realmente roto -- panico
falso en cada despliegue futuro si alguien vuelve a tocar la linea de
AUTH sin darse cuenta.
"""

import http.server
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
SCRIPT = RAIZ / "despliegue" / "verificar-despliegue.sh"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" and not Path("/usr/bin/bash").exists()
    and not Path("C:/Program Files/Git/bin/bash.exe").exists(),
    reason="hace falta bash para correr este script",
)


class _CapturaAuth(http.server.BaseHTTPRequestHandler):
    """Responde 200 a todo y guarda el ultimo header Authorization recibido."""

    encabezados_recibidos: list[str] = []

    def _responder(self):
        self._registro().append(self.headers.get("Authorization", ""))
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def _registro(self):
        return type(self).encabezados_recibidos

    def do_GET(self):  # noqa: N802 (nombre impuesto por BaseHTTPRequestHandler)
        self._responder()

    def do_POST(self):  # noqa: N802
        self._responder()

    def do_OPTIONS(self):  # noqa: N802
        self._responder()

    def log_message(self, *_args):
        pass  # silencioso: no ensuciar la salida de pytest


def _bash() -> str:
    candidato = Path("C:/Program Files/Git/bin/bash.exe")
    return str(candidato) if candidato.exists() else "bash"


def test_el_script_manda_el_token_real_no_el_literal_asteriscos():
    _CapturaAuth.encabezados_recibidos = []
    servidor = http.server.HTTPServer(("127.0.0.1", 0), _CapturaAuth)
    puerto = servidor.server_address[1]
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    try:
        entorno = dict(os.environ)
        entorno["API"] = f"http://127.0.0.1:{puerto}"
        entorno["TOKEN"] = "token-de-prueba-no-es-un-secreto-real"
        resultado = subprocess.run(
            [_bash(), str(SCRIPT)],
            env=entorno, capture_output=True, text=True, timeout=30,
        )
    finally:
        servidor.shutdown()
        hilo.join(timeout=5)

    vistos = _CapturaAuth.encabezados_recibidos
    assert vistos, (
        "el servidor falso no recibio ninguna peticion; revisar que el "
        f"script use $API (salida: {resultado.stdout}\n{resultado.stderr})"
    )
    con_auth = [h for h in vistos if h]
    assert con_auth, (
        "ninguna peticion llevo header Authorization; se esperaba al menos "
        f"la de 'id inexistente -> 404' (salida: {resultado.stdout})"
    )
    assert all(h == "Bearer token-de-prueba-no-es-un-secreto-real" for h in con_auth), (
        f"el script mando un header distinto al token real: {con_auth}"
    )
