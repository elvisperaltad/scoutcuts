"""Montaje de la API para las pruebas, con salto limpio si falta el extra `servidor`."""

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pytest

TOKEN = "token-de-pruebas-del-qa"


def _primero(*nombres):
    for nombre in nombres:
        try:
            return importlib.import_module(nombre)
        except ImportError:
            continue
    return None


@dataclass
class Servicio:
    cliente: Any
    almacen: Any
    cola: Any
    config: Any
    datos: Path
    cabeceras: dict


@pytest.fixture
def servicio(tmp_path) -> Callable[..., Servicio]:
    """Devuelve una fábrica de servicios ya autenticables con `TOKEN`."""
    pytest.importorskip("fastapi", reason="falta el extra `servidor` (pip install -e .[servidor])")
    pytest.importorskip("httpx", reason="el cliente de pruebas de FastAPI necesita httpx")
    if _primero("python_multipart", "multipart") is None:
        pytest.skip("las subidas necesitan python-multipart")

    from fastapi.testclient import TestClient

    from cortador.servidor import api as api_mod
    from cortador.servidor import procesador as procesador_mod
    from cortador.servidor.almacen import Almacen
    from cortador.servidor.cola import Cola

    colas = []

    def construir(procesar=None, *, raiz=None, limite_bytes=None, accel=False,
                  max_edad_horas=24.0, qa_base=None, errores_crudos=True,
                  perfiles=None) -> Servicio:
        datos = Path(raiz) if raiz else tmp_path / "datos"
        opciones = {} if limite_bytes is None else {"limite_bytes": limite_bytes}
        config = api_mod.Config(
            token=TOKEN, raiz=datos, accel=accel, max_edad_horas=max_edad_horas,
            qa_base=Path(qa_base) if qa_base else tmp_path / "qa", **opciones,
        )
        almacen = Almacen(datos, limite_bytes=config.limite_bytes)
        if procesar is None:
            def procesar(trabajo, guardia):
                return procesador_mod.procesar(
                    trabajo, guardia, perfiles=perfiles, qa_base=config.qa_base)
        cola = Cola(almacen, procesar)
        colas.append(cola)
        aplicacion = api_mod.crear_app(config, almacen=almacen, cola=cola)
        cliente = TestClient(aplicacion, raise_server_exceptions=errores_crudos)
        return Servicio(cliente, almacen, cola, config, datos,
                        {"Authorization": f"Bearer {TOKEN}"})

    yield construir

    for cola in colas:
        cola.detener(5)
