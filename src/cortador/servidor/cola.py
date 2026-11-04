"""Cola de trabajos de un solo carril.

El servidor tiene un unico nucleo: procesar dos videos a la vez no los termina
antes, solo hace que ambos tarden mas y arriesga quedarse sin memoria. Por eso
hay un hilo trabajador y una fila en orden de llegada.
"""

from __future__ import annotations

import queue
import threading
from typing import Callable

from . import almacen as alm
from .almacen import Almacen, Trabajo

Procesar = Callable[[Trabajo, Almacen], None]

MENSAJE_ERROR = (
    "No pudimos procesar este video. Vuelve a intentarlo y, si sigue fallando, "
    "avisanos indicando el nombre del archivo."
)


AlTerminar = Callable[[Trabajo], None]


class Cola:
    """Fila de trabajos atendida por un unico hilo."""

    def __init__(self, almacen: Almacen, procesar: Procesar, *,
                al_terminar: AlTerminar | None = None) -> None:
        self.almacen = almacen
        self._procesar = procesar
        self._al_terminar = al_terminar
        self._pendientes: queue.Queue[str | None] = queue.Queue()
        self._orden: list[str] = []
        self._cerrojo = threading.Lock()
        self._libre = threading.Event()
        self._libre.set()
        self._hilo: threading.Thread | None = None
        self._detenida = False

    def iniciar(self) -> None:
        """Arranca el hilo trabajador si aun no corre."""
        with self._cerrojo:
            if self._detenida or (self._hilo and self._hilo.is_alive()):
                return
            self._hilo = threading.Thread(
                target=self._trabajar, name="scoutcuts-cola", daemon=True)
            self._hilo.start()

    def conectar_al_terminar(self, al_terminar: AlTerminar | None) -> None:
        """Fija (o reemplaza) el callback de fin de trabajo tras construir la cola.

        Util cuando quien recibe el aviso (p. ej. el bot de Telegram) solo
        tiene su event loop listo despues de arrancar su propio hilo, que a
        su vez necesita esta misma Cola ya construida.
        """
        self._al_terminar = al_terminar

    def encolar(self, trabajo: Trabajo) -> int:
        """Pone el trabajo en la fila y devuelve cuantos tiene delante."""
        trabajo.estado = alm.EN_COLA
        trabajo.mensaje = "Tu video esta en la fila."
        self.almacen.guardar_estado(trabajo)
        with self._cerrojo:
            self._libre.clear()
            self._orden.append(trabajo.id)
            posicion = len(self._orden) - 1
        self._pendientes.put(trabajo.id)
        self.iniciar()
        return posicion

    def posicion(self, identificador: str) -> int | None:
        """Lugar en la fila; 0 es el que se esta procesando ahora."""
        with self._cerrojo:
            try:
                return self._orden.index(identificador)
            except ValueError:
                return None

    def esperar(self, timeout: float | None = None) -> bool:
        """Espera a que no quede nada en la fila."""
        return self._libre.wait(timeout)

    def detener(self, timeout: float | None = None) -> bool:
        """Pide al hilo que termine y espera a que salga."""
        with self._cerrojo:
            self._detenida = True
            hilo = self._hilo
        self._pendientes.put(None)
        if hilo is None:
            return True
        hilo.join(timeout)
        return not hilo.is_alive()

    def _trabajar(self) -> None:
        while True:
            identificador = self._pendientes.get()
            try:
                if identificador is None:
                    return
                self._atender(identificador)
                self._avisar_terminado(identificador)
            finally:
                self._pendientes.task_done()
                self._soltar(identificador)

    def _atender(self, identificador: str) -> None:
        try:
            trabajo = self.almacen.estado(identificador)
        except alm.TrabajoDesconocido:
            return
        trabajo.estado = alm.PROCESANDO
        trabajo.mensaje = "Estamos revisando tu video."
        self.almacen.guardar_estado(trabajo)
        try:
            self._procesar(trabajo, self.almacen)
        except Exception as err:  # un video roto no debe tumbar la fila
            self._marcar_error(identificador, err)

    def _marcar_error(self, identificador: str, err: BaseException) -> None:
        try:
            trabajo = self.almacen.estado(identificador)
        except alm.TrabajoDesconocido:
            return
        trabajo.estado = alm.ERROR
        trabajo.mensaje = MENSAJE_ERROR
        trabajo.detalle = alm.depurar_texto(f"{type(err).__name__}: {err}")
        self.almacen.guardar_estado(trabajo)

    def _avisar_terminado(self, identificador: str) -> None:
        """Llama a `al_terminar` con el trabajo recien releido de disco.

        Un fallo del callback (por ejemplo, el bot de Telegram sin red) nunca
        debe tumbar el hilo trabajador ni afectar al siguiente trabajo.
        """
        if self._al_terminar is None:
            return
        try:
            trabajo = self.almacen.estado(identificador)
        except alm.TrabajoDesconocido:
            return
        try:
            self._al_terminar(trabajo)
        except Exception:  # noqa: BLE001 - un fallo aqui no debe tumbar la cola
            pass

    def _soltar(self, identificador: str | None) -> None:
        with self._cerrojo:
            if identificador is not None and identificador in self._orden:
                self._orden.remove(identificador)
            if not self._orden:
                self._libre.set()
