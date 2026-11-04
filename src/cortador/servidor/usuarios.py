"""Sistema minimo de usuarios: login por Telegram ID + cuota mensual de videos.

El modelo de negocio cobra por videos al mes y por dispositivo, no por tokens
de IA: cada cuenta tiene una cuota mensual de videos que se resetea sola cada
mes calendario. El id interno es un uuid hex (igual que los trabajos en
`almacen.py`) para dejar espacio a futuros metodos de login (email/password,
etc.) sin tener que migrar nada: el telegram_id es solo una forma mas de
identificar a la cuenta, no la cuenta misma.

Cada usuario se guarda en su propia carpeta como un JSON atomico (escribir en
`.tmp` y `os.replace`, igual que `Almacen.guardar_estado`). Para encontrar un
usuario por su telegram_id sin recorrer todas las carpetas, se mantiene un
indice pequeno (telegram_id -> id interno) que tambien se escribe de forma
atomica para que nunca quede corrupto a medias si el proceso se cae.
"""

from __future__ import annotations

import json
import os
import secrets
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

CUOTA_POR_DEFECTO = 20

# Alfabeto sin 0/O/I/L/1: un scout lo teclea con el pulgar en el telefono,
# que esos caracteres se confundan entre si es el error mas comun al copiar
# un codigo a mano.
_ALFABETO_CODIGO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_LARGO_CODIGO = 8

MENSAJE_INACTIVO = (
    "Tu cuenta esta desactivada. Pide al administrador que la reactive para "
    "poder seguir subiendo videos."
)
MENSAJE_CUOTA_AGOTADA = (
    "Se agoto la cuota de videos de tu plan para este mes. Se renueva "
    "automaticamente al empezar el mes que viene; si necesitas mas, avisa al "
    "administrador."
)


class UsuarioYaExiste(ValueError):
    """Ya hay una cuenta registrada con ese telegram_id."""


class UsuarioNoRegistrado(LookupError):
    """No existe ninguna cuenta con ese identificador."""


class TelegramIdInvalido(ValueError):
    """El telegram_id no tiene la forma de un id real de Telegram.

    Un telegram_id real siempre es un entero positivo. Se valida ANTES de
    usarlo para construir cualquier ruta en disco: sin esto, un admin que
    teclea mal en `cortador usuarios crear --telegram-id` (o cualquier otro
    origen de datos no confiable) podria escapar de la carpeta de indice
    con algo como '../../lo-que-sea' (confirmado con una prueba que lo
    reproduce: sin esta validacion, se escribia un archivo fuera de la
    raiz esperada de usuarios).
    """


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _sello() -> str:
    return _ahora().isoformat(timespec="seconds")


def _mes_actual() -> str:
    """Mes calendario actual en formato 'YYYY-MM' (hora UTC)."""
    return _ahora().strftime("%Y-%m")


@dataclass
class Usuario:
    """Cuenta de un scout, tal como se guarda en disco."""

    id: str
    telegram_id: str = ""
    codigo_acceso: str = ""
    nombre: str = ""
    cuota_mensual: int = CUOTA_POR_DEFECTO
    usados_mes: int = 0
    mes_actual: str = field(default_factory=_mes_actual)
    activo: bool = True
    creado: str = field(default_factory=_sello)
    actualizado: str = field(default_factory=_sello)


class Usuarios:
    """Carpeta raiz con un subdirectorio por usuario y un indice por telegram_id."""

    def __init__(self, raiz: str | Path) -> None:
        self.raiz = Path(raiz)

    @property
    def _carpeta_usuarios(self) -> Path:
        return self.raiz / "cuentas"

    @property
    def _carpeta_indice(self) -> Path:
        return self.raiz / "indice_telegram"

    def _carpeta(self, identificador: str) -> Path:
        return self._carpeta_usuarios / identificador

    def _ruta_estado(self, identificador: str) -> Path:
        return self._carpeta(identificador) / "usuario.json"

    def _ruta_indice(self, telegram_id: str) -> Path:
        # El telegram_id ya es numerico en la practica, pero por si acaso se
        # usa otro medio de login en el futuro, lo guardamos tal cual venga.
        return self._carpeta_indice / f"{telegram_id}.json"

    @property
    def _carpeta_indice_codigo(self) -> Path:
        return self.raiz / "indice_codigo"

    def _ruta_indice_codigo(self, codigo_acceso: str) -> Path:
        return self._carpeta_indice_codigo / f"{codigo_acceso}.json"

    def _generar_codigo_acceso(self) -> str:
        """Codigo unico de `_LARGO_CODIGO` caracteres; reintenta en la rara
        colision (el espacio es grande: 29**8, no hace falta mas que esto)."""
        for _ in range(50):
            candidato = "".join(secrets.choice(_ALFABETO_CODIGO) for _ in range(_LARGO_CODIGO))
            if not self._ruta_indice_codigo(candidato).exists():
                return candidato
        raise RuntimeError("No se pudo generar un codigo de acceso unico.")

    @staticmethod
    def _escribir_atomico(destino: Path, datos: dict) -> None:
        """Escribe JSON en `.tmp` y hace `os.replace`: nunca queda a medias."""
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporal = destino.with_suffix(destino.suffix + ".tmp")
        try:
            with temporal.open("w", encoding="utf-8") as archivo:
                json.dump(datos, archivo, indent=2, ensure_ascii=False)
                archivo.flush()
                os.fsync(archivo.fileno())
            os.replace(temporal, destino)
        finally:
            temporal.unlink(missing_ok=True)

    def _guardar(self, usuario: Usuario) -> Usuario:
        usuario.actualizado = _sello()
        self._escribir_atomico(self._ruta_estado(usuario.id), asdict(usuario))
        return usuario

    def _leer(self, identificador: str) -> Usuario:
        ruta = self._ruta_estado(identificador)
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            raise UsuarioNoRegistrado(
                "No encontramos esa cuenta.") from err
        conocidos = {campo for campo in Usuario.__dataclass_fields__}
        return Usuario(**{k: v for k, v in datos.items() if k in conocidos})

    def crear(self, telegram_id: str, nombre: str,
             cuota_mensual: int = CUOTA_POR_DEFECTO) -> Usuario:
        """Registra una cuenta nueva; falla si el telegram_id ya esta en uso.

        `telegram_id` es opcional (cadena vacia): un scout que solo usa la
        PWA web nunca escribe al bot de Telegram. Siempre se genera un
        `codigo_acceso` unico, con o sin telegram_id, porque es la unica
        credencial que la web conoce.
        """
        telegram_id = str(telegram_id or "").strip()
        if telegram_id and not (telegram_id.isascii() and telegram_id.isdigit()):
            raise TelegramIdInvalido(
                f"telegram_id invalido: {telegram_id!r} (debe ser un entero "
                "positivo, tal como lo entrega la API de Telegram, o cadena "
                "vacia para una cuenta solo-web)")
        if telegram_id and self.por_telegram_id(telegram_id) is not None:
            raise UsuarioYaExiste(
                f"Ya existe una cuenta registrada con el telegram_id {telegram_id!r}.")
        codigo_acceso = self._generar_codigo_acceso()
        usuario = Usuario(
            id=uuid.uuid4().hex,
            telegram_id=telegram_id,
            codigo_acceso=codigo_acceso,
            nombre=str(nombre or "").strip(),
            cuota_mensual=int(cuota_mensual),
        )
        self._guardar(usuario)
        if telegram_id:
            self._escribir_atomico(
                self._ruta_indice(telegram_id), {"id": usuario.id})
        self._escribir_atomico(
            self._ruta_indice_codigo(codigo_acceso), {"id": usuario.id})
        return usuario

    def por_telegram_id(self, telegram_id: str) -> Usuario | None:
        """Busca la cuenta asociada a ese telegram_id; None si no existe."""
        ruta = self._ruta_indice(str(telegram_id or ""))
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        try:
            return self._leer(datos["id"])
        except (UsuarioNoRegistrado, KeyError):
            return None

    def por_codigo_acceso(self, codigo_acceso: str) -> Usuario | None:
        """Busca la cuenta por su codigo de acceso web; None si no existe."""
        ruta = self._ruta_indice_codigo(str(codigo_acceso or ""))
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        try:
            return self._leer(datos["id"])
        except (UsuarioNoRegistrado, KeyError):
            return None

    def _actualizar_mes_si_cambio(self, usuario: Usuario) -> Usuario:
        """Resetea la cuota al entrar un mes calendario nuevo, de forma persistida."""
        mes = _mes_actual()
        if usuario.mes_actual != mes:
            usuario.mes_actual = mes
            usuario.usados_mes = 0
            self._guardar(usuario)
        return usuario

    def puede_subir(self, usuario: Usuario) -> tuple[bool, str]:
        """Si puede subir un video ahora mismo, y por que no si no puede."""
        usuario = self._actualizar_mes_si_cambio(usuario)
        if not usuario.activo:
            return False, MENSAJE_INACTIVO
        if usuario.usados_mes >= usuario.cuota_mensual:
            return False, MENSAJE_CUOTA_AGOTADA
        return True, ""

    def registrar_uso(self, usuario: Usuario) -> Usuario:
        """Suma un video usado al mes actual y lo persiste."""
        usuario = self._actualizar_mes_si_cambio(usuario)
        usuario.usados_mes += 1
        return self._guardar(usuario)

    def desactivar(self, usuario: Usuario) -> Usuario:
        usuario.activo = False
        return self._guardar(usuario)

    def activar(self, usuario: Usuario) -> Usuario:
        usuario.activo = True
        return self._guardar(usuario)

    def listar(self) -> list[Usuario]:
        """Todas las cuentas registradas, en ningun orden particular."""
        if not self._carpeta_usuarios.is_dir():
            return []
        resultado = []
        for carpeta in sorted(self._carpeta_usuarios.iterdir()):
            if not carpeta.is_dir():
                continue
            try:
                resultado.append(self._leer(carpeta.name))
            except UsuarioNoRegistrado:
                continue
        return resultado
