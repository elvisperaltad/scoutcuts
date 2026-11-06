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

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel
from starlette.exceptions import HTTPException as HTTPExceptionStarlette

from . import almacen as alm
from . import procesador as procesador_mod
from .almacen import ArchivoNoAceptado, Almacen, TrabajoDesconocido, Trabajo
from .. import disciplinas as disciplinas_mod
from .cola import Cola
from .entrenamiento import (
    ArchivoDePracticaNoAceptado,
    DisciplinaDesconocida,
    VideoDePracticaNoEncontrado,
    ZonaEntrenamiento,
)
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
MENSAJE_BORRADO_EN_CURSO = (
    "Ese video todavia esta en la fila o en proceso. Espera a que termine "
    "y vuelve a intentarlo."
)
MENSAJE_NO_ENCONTRADO = "No encontramos ese trabajo."
MENSAJE_INTERNO = "Tuvimos un problema al procesar tu solicitud. Intentalo de nuevo."

# Nombre fijo del instalador portable que entrega descargas.scoutcuts.com. Es
# una constante del codigo, nunca un dato que venga de la peticion: asi la
# ruta en disco y la ruta interna de nginx no pueden salirse de su carpeta.
NOMBRE_INSTALADOR = "CortadorTurnosQA-Portable.zip"
MENSAJE_INSTALADOR_NO_DISPONIBLE = (
    "La descarga no esta disponible en este momento. Intentalo mas tarde o "
    "escribenos para que te ayudemos."
)

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
    token_entrenamiento: str | None = None
    entrenamiento_base: Path | None = None
    max_edad_entrenamiento_horas: float = 24.0
    descargas_base: Path | None = None

    def __post_init__(self) -> None:
        self.raiz = Path(self.raiz)
        if self.qa_base is not None:
            self.qa_base = Path(self.qa_base)
        if self.perfiles is not None:
            self.perfiles = Path(self.perfiles)
        if self.usuarios_base is not None:
            self.usuarios_base = Path(self.usuarios_base)
        if self.entrenamiento_base is not None:
            self.entrenamiento_base = Path(self.entrenamiento_base)
        if self.descargas_base is not None:
            self.descargas_base = Path(self.descargas_base)

    @property
    def usuarios_raiz(self) -> Path:
        """Carpeta de usuarios: la configurada, o una subcarpeta razonable de `raiz`."""
        return self.usuarios_base if self.usuarios_base is not None else self.raiz / "usuarios"

    @property
    def entrenamiento_raiz(self) -> Path:
        """Carpeta de la zona de entrenamiento QA: aislada de `raiz` (produccion)."""
        return (
            self.entrenamiento_base if self.entrenamiento_base is not None
            else self.raiz / "entrenamiento_qa"
        )

    @property
    def descargas_raiz(self) -> Path:
        """Carpeta con los instaladores que entrega nginx (solo lectura)."""
        return (
            self.descargas_base if self.descargas_base is not None
            else self.raiz / "descargas"
        )

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
        # Token separado del token QA de produccion: la zona de entrenamiento
        # (scoutcuts.com/entrenamiento) es un sandbox distinto, nunca debe
        # compartir credencial con la subida de videos reales de clientes.
        # Opcional: sin el, los endpoints de entrenamiento simplemente no se
        # registran (ver crear_app), la API de produccion sigue igual.
        token_entrenamiento = (
            entorno.get("SCOUTCUTS_TOKEN_ENTRENAMIENTO") or ""
        ).strip() or None
        entrenamiento_env = entorno.get("SCOUTCUTS_ENTRENAMIENTO")
        max_edad_entrenamiento = entorno.get("SCOUTCUTS_MAX_EDAD_ENTRENAMIENTO_HORAS")
        # Carpeta donde el administrador deja el ZIP del instalador. Sin la
        # variable cae al default `SCOUTCUTS_DATOS/descargas` (ver
        # descargas_raiz): nunca una ruta absoluta escrita en el codigo.
        descargas_env = entorno.get("SCOUTCUTS_DESCARGAS")
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
            token_entrenamiento=token_entrenamiento,
            entrenamiento_base=Path(entrenamiento_env) if entrenamiento_env else None,
            max_edad_entrenamiento_horas=(
                float(max_edad_entrenamiento) if max_edad_entrenamiento else 24.0
            ),
            descargas_base=Path(descargas_env) if descargas_env else None,
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
    # Zona de entrenamiento QA: solo se activa con su propio token (separado
    # del token de produccion). Tiene su propio cerrojo interno, aislado del
    # de subidas de produccion (nunca compiten por el mismo candado).
    # Atiende las cuatro disciplinas (defensa, bateo, pitcheo, catcher) con
    # un dataset/modelo por disciplina DENTRO de entrenamiento_raiz, nunca
    # los defaults del proyecto (modelos/dataset_defensa.json es el modelo
    # real que alimenta `cortador defensa`; mezclarlos dejaria que
    # practicas de QA contaminen el modelo de produccion real).
    zona_entrenamiento = (
        ZonaEntrenamiento(config.entrenamiento_raiz) if config.token_entrenamiento else None
    )

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
              verificacion: bool = False,
              _token: None = Depends(requiere_token)):
        # `verificacion` solo lo usa el E2E de despliegue (ver DELETE mas
        # abajo): marca la sonda como material desechable, sin la gracia
        # extendida de purgar() y borrable despues por su propio id. La PWA
        # no lo expone: un video de un scout nunca debe nacer con esta marca.
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
                trabajo = almacen.crear(archivo.filename, verificacion=verificacion)
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

    @app.delete("/v1/trabajos/{identificador}")
    def borrar(identificador: str, _token: None = Depends(requiere_token)):
        """Borra una sonda del E2E de despliegue, y solo una sonda.

        El token QA es el mismo con el que se suben videos de clientes, asi
        que este endpoint no puede ser un borrado generico: solo acepta
        trabajos nacidos con `verificacion=1`. Para cualquier otro id
        (inexistente, invalido o un trabajo real de un scout) responde el
        mismo 404 opaco, sin confirmar si el id existe.
        """
        trabajo = _buscar(identificador)
        if not trabajo.verificacion:
            raise ErrorHTTP(404, MENSAJE_NO_ENCONTRADO)
        # Nunca se borra mientras el trabajador puede estar escribiendo en la
        # carpeta: rmtree por debajo del hilo de la cola dejaria el trabajo a
        # medias y volveria a crear archivos en una carpeta ya borrada.
        if cola.posicion(identificador) is not None or trabajo.estado in (
                alm.RECIBIDO, alm.EN_COLA, alm.PROCESANDO):
            raise ErrorHTTP(409, MENSAJE_BORRADO_EN_CURSO)
        # Idempotente solo ante una carpeta que ya no esta (un DELETE repetido,
        # o la purga que se le adelanto): eso ya es el 204 que el cliente pide.
        # Cualquier otro error de disco -- permisos, IO -- se deja subir como
        # 500: un borrado que no borra no puede responder "borrado".
        try:
            shutil.rmtree(almacen.carpeta(identificador))
        except FileNotFoundError:
            pass
        return Response(status_code=204)

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

    # --- Entrega protegida del instalador (descargas.scoutcuts.com) ---
    #
    # El ZIP pesa cientos de MiB y el servidor tiene un solo nucleo: Python
    # solo autoriza y delega el envio a nginx con X-Accel-Redirect, nunca
    # abre ni lee el archivo. El codigo de acceso viaja siempre en el cuerpo
    # de un POST: en la URL quedaria en los logs de nginx, en el historial
    # del navegador y en la cabecera Referer de cualquier enlace posterior.

    def _pagina_descargas(mensaje: str = "", estado: int = 200) -> HTMLResponse:
        aviso = f"<p>{mensaje}</p>" if mensaje else ""
        return HTMLResponse(status_code=estado, content=(
            "<!doctype html>"
            '<html lang="es">'
            "<head>"
            '<meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            "<title>Descargar ScoutCuts</title>"
            "</head>"
            "<body>"
            "<h1>Descargar ScoutCuts</h1>"
            "<p>Escribe tu codigo de acceso para bajar el programa. "
            "Es el mismo codigo con el que entras a subir tus videos.</p>"
            f"{aviso}"
            '<form method="post" action="/v1/descargas/instalador">'
            '<label for="codigo_acceso">Tu codigo de acceso</label>'
            '<input id="codigo_acceso" name="codigo_acceso" type="text" '
            'autocomplete="off" required>'
            '<button type="submit">Descargar</button>'
            "</form>"
            "<p>Si no tienes codigo o no te funciona, escribenos y te ayudamos.</p>"
            "</body>"
            "</html>"
        ))

    @app.get("/v1/descargas", response_class=HTMLResponse)
    def descargas_pagina():
        return _pagina_descargas()

    @app.post("/v1/descargas/instalador")
    def descargas_instalador(codigo_acceso: str = Form(default="")):
        usuario = usuarios.por_codigo_acceso(codigo_acceso.strip())
        if usuario is None or not usuario.activo:
            # Misma respuesta exacta para un codigo inventado y para uno real
            # pero desactivado: quien prueba codigos al azar no debe poder
            # deducir cual de los dos acerto.
            return _pagina_descargas(MENSAJE_SIN_CODIGO, estado=401)
        # Bajar el instalador no procesa ningun video: no se registra uso ni
        # se consulta la cuota mensual del scout.
        ruta = config.descargas_raiz / NOMBRE_INSTALADOR
        if not ruta.is_file():
            # El scout no tiene por que enterarse de rutas ni de que falta un
            # archivo en el servidor; para el es que la descarga no esta lista.
            _LOGGER.error("El instalador no esta disponible para la entrega.")
            return _pagina_descargas(MENSAJE_INSTALADOR_NO_DISPONIBLE, estado=503)
        return Response(status_code=200, content=b"", headers={
            "X-Accel-Redirect": f"/protegido/{NOMBRE_INSTALADOR}",
            "Content-Disposition": f'attachment; filename="{NOMBRE_INSTALADOR}"',
            "Content-Type": "application/zip",
        })

    # --- Zona de entrenamiento QA (scoutcuts.com/entrenamiento) ---
    #
    # Sandbox aislado de la produccion real: otra carpeta en disco
    # (config.entrenamiento_raiz, nunca config.raiz), otro token
    # (SCOUTCUTS_TOKEN_ENTRENAMIENTO, nunca SCOUTCUTS_TOKEN_QA), y nunca
    # toca el Almacen/Cola de clientes reales. Solo se registra si el
    # administrador configuro el token de entrenamiento; sin el, estas
    # rutas no existen (404), igual que si nunca se hubiera escrito este
    # bloque -- la produccion real queda exactamente igual.
    #
    # Atiende las cuatro disciplinas registradas en `disciplinas.py`
    # (defensa, bateo, pitcheo, catcher): la disciplina va en la URL, nunca
    # en el cuerpo, para que quede fijada desde el momento de la subida.
    if zona_entrenamiento is not None:
        def requiere_token_entrenamiento(request: Request) -> None:
            cabecera = request.headers.get("authorization", "")
            esquema, _, valor = cabecera.partition(" ")
            if esquema.lower() != "bearer" or not secrets.compare_digest(
                    valor.strip(), config.token_entrenamiento or ""):
                raise ErrorHTTP(401, MENSAJE_SIN_TOKEN)

        @app.get("/v1/entrenamiento/disciplinas")
        def entrenamiento_disciplinas(_token: None = Depends(requiere_token_entrenamiento)):
            return {
                "disciplinas": [
                    {
                        "id": disciplina,
                        "nombre": disciplinas_mod.nombre_disciplina(disciplina),
                        "categorias": [
                            {"id": c, "nombre": disciplinas_mod.nombre_categoria(c)}
                            for c in disciplinas_mod.categorias(disciplina)
                        ],
                    }
                    for disciplina in disciplinas_mod.DISCIPLINAS
                ]
            }

        @app.get("/v1/entrenamiento/modelo")
        def entrenamiento_estado(_token: None = Depends(requiere_token_entrenamiento)):
            return zona_entrenamiento.estado_todas_las_disciplinas()

        @app.get("/v1/entrenamiento/modelo/{disciplina}")
        def entrenamiento_estado_disciplina(
            disciplina: str, _token: None = Depends(requiere_token_entrenamiento),
        ):
            try:
                return zona_entrenamiento.estado_modelo(disciplina)
            except DisciplinaDesconocida as err:
                raise ErrorHTTP(404, str(err))

        @app.post("/v1/entrenamiento/{disciplina}/videos")
        def entrenamiento_subir(
            disciplina: str,
            archivo: UploadFile | None = File(default=None),
            _token: None = Depends(requiere_token_entrenamiento),
        ):
            list(zona_entrenamiento.limpiar_vencidos(config.max_edad_entrenamiento_horas))
            if archivo is None or not archivo.filename:
                raise ErrorHTTP(400, MENSAJE_SIN_VIDEO)
            try:
                video = zona_entrenamiento.subir(disciplina, archivo.filename, archivo.file)
            except DisciplinaDesconocida as err:
                raise ErrorHTTP(404, str(err))
            except ArchivoDePracticaNoAceptado as err:
                raise ErrorHTTP(415, str(err))
            return JSONResponse(status_code=201, content={
                "id": video.id, "nombre": video.nombre, "disciplina": video.disciplina,
            })

        @app.post("/v1/entrenamiento/videos/{identificador}/entrenar")
        def entrenamiento_entrenar(
            identificador: str,
            cuerpo: dict,
            _token: None = Depends(requiere_token_entrenamiento),
        ):
            try:
                resultado = zona_entrenamiento.entrenar_con_manifiesto(
                    identificador,
                    cuerpo.get("repeticiones"),
                    str(cuerpo.get("video") or ""),
                )
            except VideoDePracticaNoEncontrado as err:
                raise ErrorHTTP(404, str(err))
            except (ValueError, DisciplinaDesconocida) as err:
                raise ErrorHTTP(400, str(err))
            return {
                "ejemplos_agregados": resultado.ejemplos_agregados,
                "total_ejemplos_dataset": resultado.total_ejemplos_dataset,
                "modelo_calibrado": resultado.modelo_calibrado,
                "categorias_cubiertas": resultado.categorias_cubiertas,
                "categorias_faltantes": resultado.categorias_faltantes,
                "evaluacion": resultado.evaluacion,
            }

    return app
