"""API web de ScoutCuts: subir un video, consultar su estado y descargar el montaje.

No reimplementa nada del motor: delega en `almacen` (disco), `cola` (un solo
carril) y `procesador` (puente con el motor de corte). Todo lo que ve el scout
sale en espanol y sin rutas, trazas, hostname ni nombres de usuario.
"""

from __future__ import annotations

import logging
import os
import secrets
import shutil
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from fastapi import Depends, FastAPI, File, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel
from starlette.exceptions import HTTPException as HTTPExceptionStarlette

from . import almacen as alm
from . import procesador as procesador_mod
from .almacen import ArchivoNoAceptado, Almacen, TrabajoDesconocido, Trabajo
from .cola import Cola
from .usuarios import Usuario, Usuarios

LARGO_MINIMO_TOKEN = 16

ORIGENES_PERMITIDOS = ("https://scoutcuts.com", "https://www.scoutcuts.com")

MENSAJE_SIN_TOKEN = "No tienes acceso. Vuelve a identificarte con tu token."
MENSAJE_SIN_CODIGO = "No pudimos identificarte. Inicia sesion de nuevo con tu codigo de acceso."
MENSAJE_SIN_VIDEO = "No subiste ningun video. Elige un video y vuelve a intentarlo."
MENSAJE_OTRA_SUBIDA_EN_CURSO = (
    "Ya estamos recibiendo otro video en este momento. Espera un minuto y "
    "vuelve a intentarlo."
)
MENSAJE_ANALIZANDO = "Estamos analizando tu video."
MENSAJE_ESPERA_DESCARGA = "Todavia estamos analizando tu video. Vuelve en un momento."
MENSAJE_NO_ENCONTRADO = "No encontramos ese trabajo."
MENSAJE_INTERNO = "Tuvimos un problema al procesar tu solicitud. Intentalo de nuevo."

_LOGGER = logging.getLogger("cortador.servidor.api")


class FaltaConfiguracion(RuntimeError):
    """Falta una variable obligatoria; el servicio no debe arrancar sin ella."""


class ErrorHTTP(Exception):
    """Error con un mensaje pensado para el scout y un codigo HTTP concreto."""

    def __init__(self, estado: int, mensaje: str) -> None:
        super().__init__(mensaje)
        self.estado = estado
        self.mensaje = mensaje


class PeticionSesionPwa(BaseModel):
    """Cuerpo de `/v1/pwa/sesion`: el unico dato que manda el login web."""

    codigo_acceso: str


@dataclass
class Config:
    """Configuracion del servicio, toda desde el entorno en produccion."""

    token: str
    raiz: Path
    accel: bool = False
    max_edad_horas: float = 24.0
    max_edad_revision_horas: float = 168.0
    qa_base: Path | None = None
    perfiles: Path | None = None
    limite_bytes: int = alm.LIMITE_POR_DEFECTO
    telegram_token: str | None = None
    usuarios_base: Path | None = None

    def __post_init__(self) -> None:
        self.raiz = Path(self.raiz)
        if self.qa_base is not None:
            self.qa_base = Path(self.qa_base)
        if self.perfiles is not None:
            self.perfiles = Path(self.perfiles)
        if self.usuarios_base is not None:
            self.usuarios_base = Path(self.usuarios_base)

    @property
    def usuarios_raiz(self) -> Path:
        """Carpeta de usuarios: la configurada, o una subcarpeta razonable de `raiz`."""
        return self.usuarios_base if self.usuarios_base is not None else self.raiz / "usuarios"

    @classmethod
    def desde_entorno(cls, entorno: dict | None = None) -> "Config":
        entorno = os.environ if entorno is None else entorno
        token = (entorno.get("SCOUTCUTS_TOKEN_QA") or "").strip()
        if len(token) < LARGO_MINIMO_TOKEN:
            raise FaltaConfiguracion(
                "Falta SCOUTCUTS_TOKEN_QA o es demasiado corto; debe ser una "
                f"cadena larga y secreta de al menos {LARGO_MINIMO_TOKEN} caracteres."
            )
        raiz = entorno.get("SCOUTCUTS_DATOS")
        if not raiz:
            raise FaltaConfiguracion("Falta SCOUTCUTS_DATOS (carpeta de trabajos).")
        qa = entorno.get("SCOUTCUTS_QA")
        perfiles = entorno.get("SCOUTCUTS_PERFILES")
        accel = str(entorno.get("SCOUTCUTS_ENTREGA_NGINX", "")).strip().lower() in (
            "1", "true", "si", "yes", "on",
        )
        # El token del bot es opcional: sin el, la API HTTP sigue funcionando
        # igual, solo que sin el bot de Telegram activo. Nunca se imprime ni
        # se loguea en ningun punto del codigo.
        telegram_token = (entorno.get("SCOUTCUTS_TELEGRAM_BOT_TOKEN") or "").strip() or None
        # Misma variable que lee `cortador usuarios ...` (ver cli.py): si el
        # administrador la fija una sola vez, la CLI de administracion y el
        # bot leen y escriben exactamente las mismas cuentas. Sin ella, cae
        # al default razonable `SCOUTCUTS_DATOS/usuarios` (ver usuarios_raiz).
        usuarios_env = entorno.get("SCOUTCUTS_USUARIOS")
        max_edad_revision = entorno.get("SCOUTCUTS_MAX_EDAD_REVISION_HORAS")
        return cls(
            token=token,
            raiz=Path(raiz),
            accel=accel,
            qa_base=Path(qa) if qa else None,
            perfiles=Path(perfiles) if perfiles else None,
            telegram_token=telegram_token,
            usuarios_base=Path(usuarios_env) if usuarios_env else None,
            max_edad_revision_horas=(
                float(max_edad_revision) if max_edad_revision else 168.0
            ),
        )


def _cola_por_defecto(config: Config, almacen: Almacen) -> Cola:
    def procesar(trabajo: Trabajo, guardia: Almacen) -> None:
        procesador_mod.procesar(
            trabajo, guardia, perfiles=config.perfiles, qa_base=config.qa_base)

    return Cola(almacen, procesar)


def _mensaje_estado(trabajo: Trabajo, posicion: int | None) -> str:
    """Mensaje para el scout, calculado segun el estado y la posicion en la fila."""
    if trabajo.estado == alm.PROCESANDO:
        return MENSAJE_ANALIZANDO
    if trabajo.estado == alm.EN_COLA:
        if posicion and posicion >= 1:
            plural = "videos" if posicion > 1 else "video"
            return (
                f"Hay {posicion} {plural} delante del tuyo. "
                "Te avisamos en cuanto empecemos con el tuyo."
            )
        return MENSAJE_ANALIZANDO
    return trabajo.mensaje


def crear_app(config: Config | None = None, *,
              almacen: Almacen | None = None,
              cola: Cola | None = None,
              entorno: dict | None = None) -> FastAPI:
    """Construye la aplicacion FastAPI. Falla cerrado si falta configuracion."""
    if config is None:
        config = Config.desde_entorno(entorno)
    if almacen is None:
        almacen = Almacen(config.raiz, limite_bytes=config.limite_bytes)
    if cola is None:
        cola = _cola_por_defecto(config, almacen)
    # Se construye siempre, aunque el bot no este activo: deja la puerta
    # abierta a que la propia API HTTP consulte cuotas en el futuro.
    usuarios = Usuarios(config.usuarios_raiz)
    cerrojo_subida = threading.Lock()
    estado_bot: dict = {"control": None}

    @asynccontextmanager
    async def _ciclo_de_vida(_app: FastAPI):
        # Sin token configurado, el bot simplemente no arranca; la API HTTP
        # funciona exactamente igual. Un fallo al arrancar el bot (token
        # invalido, libreria no instalada, sin red) se registra en el logger
        # estandar y NUNCA debe impedir que /salud siga respondiendo 200: por
        # eso todo este bloque esta blindado con un `except Exception` amplio.
        if config.telegram_token:
            try:
                from .bot_telegram import iniciar_bot_en_segundo_plano

                estado_bot["control"] = iniciar_bot_en_segundo_plano(
                    config.telegram_token, almacen, cola, usuarios)
            except Exception as err:  # noqa: BLE001 - el bot nunca debe tumbar la API HTTP
                # Sin `_LOGGER.exception`: ese traceback podria repetir el
                # token crudo si el fallo ocurre durante la construccion del
                # Application (antes de que exista el hilo protegido de
                # `bot_telegram._correr`). Nunca se loguea el valor del token.
                mensaje = f"{type(err).__name__}: {err}"
                if config.telegram_token:
                    mensaje = mensaje.replace(config.telegram_token, "***")
                _LOGGER.error(
                    "No se pudo arrancar el bot de Telegram; la API HTTP sigue activa. %s",
                    mensaje,
                )
        yield
        control = estado_bot.get("control")
        if control is not None:
            control.detener(10)

    app = FastAPI(
        title="ScoutCuts", docs_url=None, redoc_url=None, openapi_url=None,
        lifespan=_ciclo_de_vida,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(ORIGENES_PERMITIDOS),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ErrorHTTP)
    async def _manejar_error_http(_request: Request, exc: ErrorHTTP):
        return JSONResponse(status_code=exc.estado, content={"mensaje": exc.mensaje})

    @app.exception_handler(Exception)
    async def _manejar_error(_request: Request, _exc: Exception):
        return JSONResponse(status_code=500, content={"mensaje": MENSAJE_INTERNO})

    @app.exception_handler(HTTPExceptionStarlette)
    async def _manejar_ruta(_request: Request, exc: HTTPExceptionStarlette):
        # Rutas no encontradas (p. ej. tras normalizar "../") no deben filtrar
        # el {"detail": ...} por defecto; respondemos en espanol y sin pistas.
        if exc.status_code == 404:
            return JSONResponse(status_code=404, content={"mensaje": MENSAJE_NO_ENCONTRADO})
        return JSONResponse(status_code=exc.status_code, content={"mensaje": MENSAJE_INTERNO})

    def requiere_token(request: Request) -> None:
        cabecera = request.headers.get("authorization", "")
        esquema, _, valor = cabecera.partition(" ")
        if esquema.lower() != "bearer" or not secrets.compare_digest(
                valor.strip(), config.token):
            raise ErrorHTTP(401, MENSAJE_SIN_TOKEN)

    def requiere_sesion_pwa(request: Request) -> Usuario:
        """Autentica a un scout de la PWA por su codigo de acceso.

        A diferencia de `requiere_token` (un unico secreto compartido para
        todo el QA), cada scout tiene su propio codigo, asi que no hay un
        valor fijo contra el que comparar con `compare_digest`: la busqueda
        en disco (`por_codigo_acceso`) ya es la unica forma de validarlo, y
        el nombre de archivo del indice solo se construye con caracteres del
        alfabeto cerrado de `_generar_codigo_acceso`, sin riesgo de path
        traversal por mas que el valor venga de la red sin validar antes.
        """
        cabecera = request.headers.get("authorization", "")
        esquema, _, valor = cabecera.partition(" ")
        if esquema.lower() != "bearer" or not valor.strip():
            raise ErrorHTTP(401, MENSAJE_SIN_CODIGO)
        usuario = usuarios.por_codigo_acceso(valor.strip())
        if usuario is None or not usuario.activo:
            raise ErrorHTTP(401, MENSAJE_SIN_CODIGO)
        return usuario

    @app.middleware("http")
    async def _autenticar_antes_de_leer_el_cuerpo(request: Request, call_next):
        # FastAPI resuelve el UploadFile (y por tanto lee todo el multipart)
        # como parte de los parametros de la ruta, antes de que el Depends
        # de autenticacion se ejecute. Sin este middleware, un cliente sin
        # token podria hacer que el servidor reciba hasta el limite completo
        # antes de rechazarlo. El middleware corre antes del enrutado, asi
        # que corta la conexion sin leer un solo byte del cuerpo.
        if request.method == "POST" and request.url.path == "/v1/trabajos":
            try:
                requiere_token(request)
            except ErrorHTTP as err:
                return JSONResponse(status_code=err.estado, content={"mensaje": err.mensaje})
        if request.method == "POST" and request.url.path == "/v1/pwa/trabajos":
            try:
                requiere_sesion_pwa(request)
            except ErrorHTTP as err:
                return JSONResponse(status_code=err.estado, content={"mensaje": err.mensaje})
        return await call_next(request)

    def _buscar(identificador: str) -> Trabajo:
        try:
            return almacen.estado(identificador)
        except TrabajoDesconocido:
            raise ErrorHTTP(404, MENSAJE_NO_ENCONTRADO)

    @app.get("/salud")
    def salud():
        return {"estado": "ok"}

    @app.post("/v1/trabajos")
    def subir(archivo: UploadFile | None = File(default=None),
              _token: None = Depends(requiere_token)):
        if not cerrojo_subida.acquire(blocking=False):
            raise ErrorHTTP(503, MENSAJE_OTRA_SUBIDA_EN_CURSO)
        try:
            list(almacen.purgar(
                config.max_edad_horas,
                max_edad_revision_horas=config.max_edad_revision_horas,
            ))
            if archivo is None or not archivo.filename:
                raise ErrorHTTP(400, MENSAJE_SIN_VIDEO)
            try:
                trabajo = almacen.crear(archivo.filename)
            except ArchivoNoAceptado as err:
                raise ErrorHTTP(415, str(err))
            try:
                almacen.guardar_entrada(trabajo, archivo.file)
            except ArchivoNoAceptado as err:
                shutil.rmtree(almacen.carpeta(trabajo.id), ignore_errors=True)
                raise ErrorHTTP(413, str(err))
        finally:
            cerrojo_subida.release()
        cola.encolar(trabajo)
        return JSONResponse(status_code=201, content={
            "id": trabajo.id,
            "estado": trabajo.estado,
            "mensaje": trabajo.mensaje,
        })

    @app.get("/v1/trabajos/{identificador}")
    def consultar(identificador: str, _token: None = Depends(requiere_token)):
        trabajo = _buscar(identificador)
        posicion = cola.posicion(identificador)
        disponible = (
            trabajo.estado == alm.LISTO
            and almacen.ruta_resultado(trabajo).exists()
        )
        return {
            "id": trabajo.id,
            "nombre": trabajo.nombre,
            "estado": trabajo.estado,
            "mensaje": _mensaje_estado(trabajo, posicion),
            "posicion": posicion,
            "resultado_disponible": disponible,
        }

    @app.get("/v1/trabajos/{identificador}/resultado")
    def descargar(identificador: str, _token: None = Depends(requiere_token)):
        trabajo = _buscar(identificador)
        if trabajo.estado in (alm.RECIBIDO, alm.EN_COLA, alm.PROCESANDO):
            raise ErrorHTTP(409, MENSAJE_ESPERA_DESCARGA)
        if trabajo.estado in (alm.PENDIENTE_REVISION, alm.ERROR):
            raise ErrorHTTP(409, trabajo.mensaje or MENSAJE_ESPERA_DESCARGA)
        ruta = almacen.ruta_resultado(trabajo)
        if not ruta.exists():
            raise ErrorHTTP(404, trabajo.mensaje or "No encontramos swings en este video.")
        almacen.marcar_descargado(trabajo)
        disposicion = f'attachment; filename="montaje-{identificador}.mp4"'
        if config.accel:
            interna = f"/protegido/{identificador}/resultado.mp4"
            return Response(status_code=200, content=b"", headers={
                "X-Accel-Redirect": interna,
                "Content-Disposition": disposicion,
            })
        return FileResponse(
            str(ruta), media_type="video/mp4",
            filename=f"montaje-{identificador}.mp4")

    @app.post("/v1/pwa/sesion")
    def pwa_sesion(datos: PeticionSesionPwa):
        usuario = usuarios.por_codigo_acceso((datos.codigo_acceso or "").strip())
        if usuario is None or not usuario.activo:
            raise ErrorHTTP(401, MENSAJE_SIN_CODIGO)
        return {
            "nombre": usuario.nombre,
            "cuota_mensual": usuario.cuota_mensual,
            "usados_mes": usuario.usados_mes,
        }

    @app.post("/v1/pwa/trabajos")
    def pwa_subir(archivo: UploadFile | None = File(default=None),
                  usuario: Usuario = Depends(requiere_sesion_pwa)):
        puede, motivo = usuarios.puede_subir(usuario)
        if not puede:
            raise ErrorHTTP(409, motivo)
        if not cerrojo_subida.acquire(blocking=False):
            raise ErrorHTTP(503, MENSAJE_OTRA_SUBIDA_EN_CURSO)
        try:
            list(almacen.purgar(
                config.max_edad_horas,
                max_edad_revision_horas=config.max_edad_revision_horas,
            ))
            if archivo is None or not archivo.filename:
                raise ErrorHTTP(400, MENSAJE_SIN_VIDEO)
            try:
                trabajo = almacen.crear(
                    archivo.filename, propietario=usuario.id)
            except ArchivoNoAceptado as err:
                raise ErrorHTTP(415, str(err))
            try:
                almacen.guardar_entrada(trabajo, archivo.file)
            except ArchivoNoAceptado as err:
                shutil.rmtree(almacen.carpeta(trabajo.id), ignore_errors=True)
                raise ErrorHTTP(413, str(err))
        finally:
            cerrojo_subida.release()
        usuarios.registrar_uso(usuario)
        cola.encolar(trabajo)
        return JSONResponse(status_code=201, content={
            "id": trabajo.id,
            "estado": trabajo.estado,
            "mensaje": trabajo.mensaje,
        })

    def _buscar_propio(identificador: str, usuario: Usuario) -> Trabajo:
        trabajo = _buscar(identificador)
        if trabajo.propietario != usuario.id:
            # Mismo mensaje y codigo que "no existe": un scout no debe poder
            # distinguir "no es tuyo" de "no existe" sondeando ids ajenos.
            raise ErrorHTTP(404, MENSAJE_NO_ENCONTRADO)
        return trabajo

    @app.get("/v1/pwa/trabajos")
    def pwa_listar(usuario: Usuario = Depends(requiere_sesion_pwa)):
        propios = almacen.trabajos_de(usuario.id)
        return {"trabajos": [
            {
                "id": trabajo.id,
                "nombre": trabajo.nombre,
                "estado": trabajo.estado,
                "mensaje": _mensaje_estado(trabajo, cola.posicion(trabajo.id)),
                "resultado_disponible": (
                    trabajo.estado == alm.LISTO
                    and almacen.ruta_resultado(trabajo).exists()
                ),
            }
            for trabajo in propios
        ]}

    @app.get("/v1/pwa/trabajos/{identificador}")
    def pwa_consultar(identificador: str,
                      usuario: Usuario = Depends(requiere_sesion_pwa)):
        trabajo = _buscar_propio(identificador, usuario)
        posicion = cola.posicion(identificador)
        disponible = (
            trabajo.estado == alm.LISTO
            and almacen.ruta_resultado(trabajo).exists()
        )
        return {
            "id": trabajo.id,
            "nombre": trabajo.nombre,
            "estado": trabajo.estado,
            "mensaje": _mensaje_estado(trabajo, posicion),
            "posicion": posicion,
            "resultado_disponible": disponible,
        }

    @app.get("/v1/pwa/trabajos/{identificador}/resultado")
    def pwa_descargar(identificador: str,
                      usuario: Usuario = Depends(requiere_sesion_pwa)):
        trabajo = _buscar_propio(identificador, usuario)
        if trabajo.estado in (alm.RECIBIDO, alm.EN_COLA, alm.PROCESANDO):
            raise ErrorHTTP(409, MENSAJE_ESPERA_DESCARGA)
        if trabajo.estado in (alm.PENDIENTE_REVISION, alm.ERROR):
            raise ErrorHTTP(409, trabajo.mensaje or MENSAJE_ESPERA_DESCARGA)
        ruta = almacen.ruta_resultado(trabajo)
        if not ruta.exists():
            raise ErrorHTTP(404, trabajo.mensaje or "No encontramos swings en este video.")
        almacen.marcar_descargado(trabajo)
        disposicion = f'attachment; filename="montaje-{identificador}.mp4"'
        if config.accel:
            interna = f"/protegido/{identificador}/resultado.mp4"
            return Response(status_code=200, content=b"", headers={
                "X-Accel-Redirect": interna,
                "Content-Disposition": disposicion,
            })
        return FileResponse(
            str(ruta), media_type="video/mp4",
            filename=f"montaje-{identificador}.mp4")

    return app
