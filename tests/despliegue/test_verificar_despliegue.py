"""Prueba del script bash `despliegue/verificar-despliegue.sh`.

El script manda peticiones autenticadas de verdad contra la API en
produccion; para poder probarlo sin tocar el servidor real, se levanta un
servidor HTTP falso en localhost que registra metodo, ruta y header de
Authorization de cada peticion, y se apunta el script a el con las
variables de entorno API y SITIO (igual que ya se puede apuntar TOKEN;
antes de esta prueba `API` estaba fijo en el script, asi que no habia
forma de probarlo sin tocar produccion real). Con las dos apuntadas al
servidor falso la prueba es hermetica: no sale de localhost.

Protege contra la regresion que ya tuvo este script una vez (ver
BITACORA.md: "El script de verificacion no verificaba nada"): mandar un
token literal o vacio en vez del real, lo que hace que CUALQUIER
despliegue sano reporte 401 en las rutas autenticadas y el script
termine en "NO verificado" sin que nada este realmente roto -- panico
falso en cada despliegue futuro si alguien vuelve a tocar la linea de
AUTH sin darse cuenta.

El servidor falso imita ademas el camino E2E completo de la API real
(POST 201 -> GET estado -> DELETE 204), para poder exigir las dos piezas
que hacen que ese E2E sea seguro de correr contra el servidor en vivo:
que la sonda se suba marcada con `verificacion=1` (unico material que la
API acepta borrar por id, ver `test_api.py::
test_borrar_solo_elimina_las_sondas_de_verificacion`) y que el script la
borre al terminar. Sin las dos, la sonda termina en `pendiente_revision`
sin marca, asi que la purga le da la gracia larga de ese estado y no se
la lleva hasta los 7 dias (ver `Almacen.purgar`): cada despliegue deja
una semana de basura mezclada con el material real que un humano tiene
que revisar, y alguien la tiene que borrar a mano en el momento.

La conducta se comprueba ejecutando el script de verdad contra este
servidor falso: ninguna assertion mira el texto del script.
"""

import http.server
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
SCRIPT = RAIZ / "despliegue" / "verificar-despliegue.sh"

TOKEN_FALSO = "token-de-prueba-no-es-un-secreto-real"
AUTH_ESPERADA = f"Bearer {TOKEN_FALSO}"
# Id fijo con la forma real que devuelve la API (`uuid.uuid4().hex`): 32
# caracteres hexadecimales en minuscula.
ID_SONDA = "7e2b4c9a1d6f48039a5b1c2d3e4f5061"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" and not Path("/usr/bin/bash").exists()
    and not Path("C:/Program Files/Git/bin/bash.exe").exists(),
    reason="hace falta bash para correr este script",
)


class _ApiFalsa(http.server.BaseHTTPRequestHandler):
    """API de mentira, minima pero suficiente para el E2E del script.

    Registra `(metodo, ruta, authorization)` de cada peticion y responde
    como la API real en lo que el script necesita para avanzar: 401 al
    POST sin token, 201 con `ID_SONDA` al POST autenticado, estado
    `pendiente_revision` al GET de esa sonda, 204 al DELETE de esa sonda,
    200 en la zona de entrenamiento con o sin token (es publica, ver mas
    abajo) y 404 opaco para cualquier otro id.

    Hace tambien de sitio (nginx): responde 200 a `/` y
    `/entrenamiento/`, las dos paginas que el script pide por $SITIO. Son
    rutas distintas de las de la API, pero servirlas aqui es lo que deja
    la prueba hermetica: apuntando $SITIO a este servidor, el script no
    toca la internet real en ninguna linea.
    """

    peticiones: list[tuple[str, str, str]] = []

    # -- utilidades -----------------------------------------------------
    def _registrar(self):
        type(self).peticiones.append(
            (self.command, self.path, self.headers.get("Authorization", "")))

    def _tragar_cuerpo(self):
        """Consume el multipart de la subida; si no, curl ve la conexion cortada."""
        largo = int(self.headers.get("Content-Length") or 0)
        if largo:
            self.rfile.read(largo)
        elif "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            while True:
                tamano = int(self.rfile.readline().split(b";")[0] or b"0", 16)
                self.rfile.read(tamano + 2)  # el chunk y su CRLF
                if tamano == 0:
                    break

    def _responder(self, codigo: int, cuerpo: dict | None = None):
        datos = b"" if cuerpo is None else json.dumps(cuerpo).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        if datos:
            self.wfile.write(datos)

    def _autenticado(self) -> bool:
        return bool(self.headers.get("Authorization"))

    def _ruta(self) -> str:
        return self.path.split("?", 1)[0]

    # -- rutas ----------------------------------------------------------
    def do_GET(self):  # noqa: N802 (nombre impuesto por BaseHTTPRequestHandler)
        self._registrar()
        ruta = self._ruta()
        if ruta in ("/", "/entrenamiento/"):
            # Paginas del sitio, no de la API: sin token, como las sirve
            # nginx en produccion.
            self._responder(200, {"pagina": ruta})
        elif ruta == "/salud":
            self._responder(200, {"estado": "ok"})
        elif ruta == "/v1/entrenamiento/disciplinas":
            # Antes que el chequeo de auth generico: la zona de
            # entrenamiento es PUBLICA, asi que la API real responde 200
            # aqui tanto sin cabecera como con el token de produccion. El
            # script exige justo esos 200 (y las 4 disciplinas) porque son
            # la prueba de que el QA entra solo con el enlace.
            self._responder(200, {"disciplinas": [
                {"id": d, "nombre": d, "categorias": []}
                for d in ("defensa", "bateo", "pitcheo", "catcher")
            ]})
        elif ruta == "/v1/entrenamiento/modelo":
            self._responder(200, {})
        elif not self._autenticado():
            self._responder(401, {"detail": "Falta el token."})
        elif ruta == f"/v1/trabajos/{ID_SONDA}":
            self._responder(200, {
                "id": ID_SONDA,
                "nombre": "sonda.mp4",
                "estado": "pendiente_revision",
                "mensaje": "Revisa el video: no encontramos swings.",
                "posicion": None,
                "resultado_disponible": False,
            })
        elif ruta == f"/v1/trabajos/{ID_SONDA}/resultado":
            # Como la API real: en pendiente_revision no hay montaje que bajar.
            self._responder(409, {"detail": "Revisa el video: no encontramos swings."})
        else:
            self._responder(404, {"detail": "No encontramos ese video."})

    def do_POST(self):  # noqa: N802
        self._registrar()
        self._tragar_cuerpo()
        if not self._autenticado():
            self._responder(401, {"detail": "Falta el token."})
        elif self._ruta() == "/v1/trabajos":
            self._responder(201, {
                "id": ID_SONDA,
                "estado": "recibido",
                "mensaje": "Video recibido.",
            })
        else:
            self._responder(404, {"detail": "No encontramos ese video."})

    def do_DELETE(self):  # noqa: N802
        self._registrar()
        if not self._autenticado():
            self._responder(401, {"detail": "Falta el token."})
        elif self._ruta() == f"/v1/trabajos/{ID_SONDA}":
            self._responder(204)
        else:
            self._responder(404, {"detail": "No encontramos ese video."})

    def do_OPTIONS(self):  # noqa: N802
        # Sin cabeceras CORS: igual que la API real ante un Origin ajeno.
        self._registrar()
        self._responder(200, {})

    def log_message(self, *_args):
        pass  # silencioso: no ensuciar la salida de pytest


def _bash() -> str:
    candidato = Path("C:/Program Files/Git/bin/bash.exe")
    return str(candidato) if candidato.exists() else "bash"


def _ffmpeg_de_mentira(carpeta: Path) -> None:
    """Deja en `carpeta` un `ffmpeg` que solo crea el archivo de salida.

    El script genera la sonda con `ffmpeg ... -y "$TMP/prueba.mp4"` y
    despues exige que el archivo no este vacio (`[ -s ... ]`). Nadie mira
    el contenido -- ni el script ni el servidor falso -- asi que basta un
    shell script que escriba un byte en su ultimo argumento: la prueba
    queda determinista en cualquier maquina, con o sin ffmpeg instalado,
    y sin depender de que un ffmpeg.exe nativo entienda las rutas POSIX
    que devuelve `mktemp -d`.
    """
    falso = carpeta / "ffmpeg"  # sin extension: asi lo busca el script
    falso.write_bytes(
        b"#!/bin/sh\n"
        b'for salida in "$@"; do :; done\n'  # la salida es el ultimo argumento
        b'printf x > "$salida"\n'
        b"exit 0\n"
    )
    falso.chmod(0o755)


def test_el_script_manda_el_token_real_no_el_literal_asteriscos(tmp_path):
    _ffmpeg_de_mentira(tmp_path)

    _ApiFalsa.peticiones = []
    servidor = http.server.HTTPServer(("127.0.0.1", 0), _ApiFalsa)
    puerto = servidor.server_address[1]
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    try:
        entorno = dict(os.environ)
        # Fuera las de produccion que pueda traer el entorno de quien corre
        # la prueba: si esta maquina tiene exportado el TOKEN real (es lo
        # normal en la de despliegue), heredarlo mandaria la credencial de
        # verdad al servidor falso de localhost. Se borran todas y despues se
        # fijan solo las de prueba, asi el script no puede leer otra cosa.
        for variable in ("TOKEN", "API", "SITIO"):
            entorno.pop(variable, None)
        entorno["API"] = f"http://127.0.0.1:{puerto}"
        entorno["SITIO"] = f"http://127.0.0.1:{puerto}"
        entorno["TOKEN"] = TOKEN_FALSO
        # El ffmpeg de mentira va primero en el PATH para que el
        # `command -v ffmpeg` del script lo encuentre antes que cualquier
        # ffmpeg real de la maquina. Ruta en forma POSIX y separador del
        # sistema: asi bash la entiende tanto en Linux como en Git Bash,
        # que traduce el PATH heredado de Windows al arrancar.
        entorno["PATH"] = tmp_path.as_posix() + os.pathsep + entorno.get("PATH", "")
        resultado = subprocess.run(
            [_bash(), str(SCRIPT)],
            env=entorno, capture_output=True, text=True, timeout=120,
        )
    finally:
        servidor.shutdown()
        hilo.join(timeout=5)

    salida = resultado.stdout + resultado.stderr
    vistos = _ApiFalsa.peticiones
    assert vistos, (
        "el servidor falso no recibio ninguna peticion; revisar que el "
        f"script use $API (salida: {salida})"
    )

    # Proposito original: todo header de auth lleva el token real.
    con_auth = [auth for _, _, auth in vistos if auth]
    assert con_auth, (
        "ninguna peticion llevo header Authorization; se esperaba al menos "
        f"la de 'id inexistente -> 404' (salida: {salida})"
    )
    assert all(auth == AUTH_ESPERADA for auth in con_auth), (
        f"el script mando un header distinto al token real: {con_auth}"
    )

    # (a) La sonda se sube marcada como material desechable.
    subidas = [
        ruta for metodo, ruta, auth in vistos
        if metodo == "POST" and ruta.split("?", 1)[0] == "/v1/trabajos" and auth
    ]
    assert subidas, (
        "el script no subio ningun video autenticado a /v1/trabajos; el E2E "
        f"no llego a correr (salida: {salida})"
    )
    assert any("verificacion=1" in ruta for ruta in subidas), (
        "el script subio la sonda sin la query `verificacion=1`, asi que la "
        "API la trata como video de un scout y nunca la va a poder borrar: "
        f"{subidas}"
    )

    # (b) Y la borra al terminar, por su propio id.
    borrados = [
        ruta.split("?", 1)[0] for metodo, ruta, _ in vistos if metodo == "DELETE"
    ]
    assert f"/v1/trabajos/{ID_SONDA}" in borrados, (
        "el script no borro la sonda que acababa de crear; cada verificacion "
        f"deja basura en produccion (DELETEs vistos: {borrados}; salida: {salida})"
    )

    # (c) Y, contra un despliegue sano, el script tiene que CONCLUIR que lo
    # esta. Mirar solo las peticiones deja pasar un `esperar` que falla sin
    # que ninguna assertion de arriba lo note: el script suma FALLOS, sale
    # con 1 y la prueba sigue verde. Esto exige que el veredicto -- lo unico
    # que lee quien corre el script -- coincida con el servidor sano que
    # imita `_ApiFalsa`. Con $SITIO apuntado tambien al servidor falso, el
    # veredicto sale entero de este proceso: ninguna linea del script
    # depende de la internet real, asi que un fallo aqui es del script.
    assert resultado.returncode == 0, (
        f"el script dijo 'NO verificado' (codigo {resultado.returncode}) contra "
        f"un servidor que responde como el de produccion sano; salida:\n{salida}"
    )
