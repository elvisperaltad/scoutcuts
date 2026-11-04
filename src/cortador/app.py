"""Aplicación de escritorio para operar los flujos existentes de forma local.

Tkinter se importa únicamente en :func:`abrir`, de modo que importar este módulo y
usar el resto del CLI no requiere una pantalla disponible.
"""

from __future__ import annotations

import math
import os
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import agente, compactar, defensa, eventos, ffmpeg, marcas, qa, revision
from .perfil import Perfil

Registrar = Callable[[str], None]


@dataclass(frozen=True)
class ResultadoTarea:
    estado: str
    codigo: int
    detalle: str


@dataclass(frozen=True)
class VideoCarpeta:
    video: Path
    tipo: str | None
    decisiones: Path | None
    mensaje: str


@dataclass(frozen=True)
class DescubrimientoCarpeta:
    carpeta: Path
    videos: tuple[VideoCarpeta, ...]


_DERIVADOS = ("compacto", "resultado", "_clip", "-clip", "_turno", "-turno")
_EXTENSIONES_VIDEO = {".mp4", ".mov", ".m4v", ".avi"}


def _archivo_ci(carpeta: Path, nombre: str) -> Path | None:
    buscado = nombre.casefold()
    return next((p for p in carpeta.iterdir()
                 if p.is_file() and p.name.casefold() == buscado), None)


def descubrir_carpeta_jugador(carpeta: str | Path) -> DescubrimientoCarpeta:
    """Encuentra fuentes y decisiones revisadas sin pedir archivos internos al usuario."""
    raiz = Path(str(carpeta).strip())
    if not raiz.exists():
        raise ValueError("La carpeta indicada no existe.")
    if not raiz.is_dir():
        raise ValueError("La ruta indicada no es una carpeta.")

    fuentes = sorted(
        (p for p in raiz.iterdir()
         if p.is_file() and p.suffix.casefold() in _EXTENSIONES_VIDEO
         and not any(token in p.stem.casefold() for token in _DERIVADOS)),
        key=lambda p: p.name.casefold(),
    )
    videos: list[VideoCarpeta] = []
    archivos = tuple(p for p in raiz.iterdir() if p.is_file())
    for video in fuentes:
        bateo = _archivo_ci(raiz, f"{video.stem}.marcas.json")
        if bateo is not None:
            try:
                cuaderno = marcas.Cuaderno.cargar(bateo)
                if marcas.fundir(cuaderno):
                    videos.append(VideoCarpeta(
                        video, "bateo", bateo, "Bateo listo para procesar."
                    ))
                    continue
            except (OSError, ValueError, TypeError):
                pass

        preferido = _archivo_ci(raiz, f"{video.stem}_defensa_6.json")
        candidatos = ([preferido] if preferido else [])
        if not preferido:
            candidatos = [
                p for p in archivos
                if p.suffix.casefold() == ".json"
                and p.name.casefold().startswith(video.stem.casefold())
                and p.name.casefold() != f"{video.stem}.marcas.json".casefold()
            ]
        validos = []
        for candidato in candidatos:
            try:
                defensa.cargar(candidato, video)
                validos.append(candidato)
            except (OSError, ValueError, TypeError):
                continue
        if len(validos) == 1:
            videos.append(VideoCarpeta(
                video, "defensa", validos[0], "Defensa lista para procesar."
            ))
        else:
            videos.append(VideoCarpeta(
                video, None, None,
                "Requiere revisión antes de poder generar el resultado."
            ))
    return DescubrimientoCarpeta(raiz, tuple(videos))


def perfil_compatible(video: Path, carpeta_perfiles: Path, *,
                      obtener_info: Callable = ffmpeg.info,
                      cargar_perfil: Callable = Perfil.cargar):
    """Obtiene el único perfil cuya resolución coincide con la del video."""
    info = obtener_info(str(video))
    compatibles = []
    if carpeta_perfiles.is_dir():
        for ruta in carpeta_perfiles.glob("*.json"):
            try:
                perfil = cargar_perfil(ruta)
            except (OSError, ValueError, TypeError):
                continue
            if (perfil.video_ancho, perfil.video_alto) == (info.ancho, info.alto):
                compatibles.append(perfil)
    return info, compatibles[0] if len(compatibles) == 1 else None, len(compatibles)


def revisar_bateo_nuevo(video: Path, perfil, sidecar: Path, *,
                        detectar: Callable = eventos.detectar,
                        revisar: Callable = revision.marcar,
                        registrar: Registrar = print):
    """Detecta candidatos, los guarda y conduce su revisión interactiva."""
    candidatos = detectar(str(video), perfil)
    cuaderno = marcas.Cuaderno.desde_candidatos(
        str(video), candidatos, eventos.ANTES, eventos.DESPUES,
        perfil=getattr(perfil, "origen", "") or "perfil compatible",
    )
    cuaderno.guardar(sidecar)
    if not candidatos:
        return cuaderno
    registrar("Se abrirá la revisión: V conserva, N descarta y Q termina")
    cuaderno = revisar(cuaderno, sidecar)
    cuaderno.guardar(sidecar)
    return cuaderno


def tarea_carpeta_jugador(carpeta: str | Path, *, registrar: Registrar = print,
                           cargar_bateo: Callable = marcas.Cuaderno.cargar,
                           cargar_defensa: Callable = defensa.cargar,
                           exportar: Callable = compactar.exportar,
                           perfiles: str | Path | None = None,
                           obtener_info: Callable = ffmpeg.info,
                           cargar_perfil: Callable = Perfil.cargar,
                           detectar: Callable = eventos.detectar,
                           revisar: Callable = revision.marcar,
                           qa_base: str | Path | None = None) -> ResultadoTarea:
    """Procesa decisiones existentes y guía la revisión de bateos nuevos."""
    evidencia = qa.CorridaQA(carpeta, base=qa_base)

    def informar(mensaje, nivel="INFO", excepcion=None):
        registrar(mensaje)
        qa.registrar_log(nivel, mensaje, base=evidencia.base, excepcion=excepcion)

    try:
        hallazgo = descubrir_carpeta_jugador(carpeta)
    except Exception as err:
        informar(f"ERROR: {err}", "ERROR", err)
        evidencia.finalizar("error", str(err))
        raise
    encontrados = len(hallazgo.videos)
    if not encontrados:
        err = ValueError("No se encontraron videos fuente en la carpeta seleccionada.")
        informar(f"ERROR: {err}", "ERROR", err)
        evidencia.finalizar("error", str(err))
        raise err
    listos = sum(item.tipo is not None for item in hallazgo.videos)
    pendientes = 0
    generados = errores = 0
    salida = hallazgo.carpeta / "Resultados"
    carpeta_perfiles = (Path(perfiles) if perfiles is not None
                        else qa.recursos("perfiles"))

    for item in hallazgo.videos:
        try:
            info_qa = obtener_info(str(item.video))
        except Exception:
            info_qa = None
        evidencia.agregar_video(item.video, tipo=item.tipo, info=info_qa)

    for item in hallazgo.videos:
        if item.tipo is None:
            try:
                info, perfil, cantidad = perfil_compatible(
                    item.video, carpeta_perfiles, obtener_info=obtener_info,
                    cargar_perfil=cargar_perfil,
                )
                if perfil is None:
                    evidencia.actualizar_video(item.video.name, metadatos={
                        "ancho": info.ancho, "alto": info.alto, "fps": info.fps,
                        "duracion": info.duracion, "codec": info.codec,
                    }, pendientes=1)
                    pendientes += 1
                    causa = ("no hay una configuración" if cantidad == 0
                             else "hay más de una configuración")
                    informar(
                        f"{item.video.name}: pendiente; {causa} de cámara compatible "
                        f"con {info.ancho}x{info.alto}."
                    )
                    continue
                sidecar = hallazgo.carpeta / f"{item.video.stem}.marcas.json"
                cuaderno = revisar_bateo_nuevo(
                    item.video, perfil, sidecar, detectar=detectar,
                    revisar=revisar, registrar=informar,
                )
                tramos = marcas.fundir(cuaderno)
                decisiones = [
                    {"inicio": m.inicio, "fin": m.fin, "instante": m.instante,
                     "estado": m.estado, "nota": m.nota} for m in cuaderno.marcas
                ]
                evidencia.actualizar_video(
                    item.video.name, tipo="bateo", perfil=getattr(perfil, "origen", "") or
                    "perfil compatible", metadatos={"ancho": info.ancho, "alto": info.alto,
                    "fps": info.fps, "duracion": info.duracion, "codec": info.codec},
                    candidatos=[{"instante": m.instante, "fuerza": m.fuerza}
                                for m in cuaderno.marcas], decisiones=decisiones,
                    validos=len(cuaderno.validas), pendientes=len(cuaderno.pendientes),
                )
                evidencia.copiar_etiqueta(sidecar, item.video)
                if not tramos:
                    pendientes += 1
                    informar(
                        f"{item.video.name}: revisión terminada sin jugadas conservadas; "
                        "queda pendiente."
                    )
                    continue
                destino = salida / f"{item.video.stem}_bateo.mp4"
                exportar(str(item.video), tramos, str(destino))
                generados += 1
                listos += 1
                evidencia.actualizar_video(item.video.name, salida=destino)
                informar(f"{item.video.name}: resultado generado en Resultados.")
            except Exception as err:
                errores += 1
                evidencia.actualizar_video(item.video.name, error=str(err))
                informar(f"{item.video.name}: ERROR: {err}", "ERROR", err)
            continue
        informar(f"{item.video.name}: procesando {item.tipo}...")
        try:
            if item.tipo == "bateo":
                cuaderno = cargar_bateo(item.decisiones)
                tramos = marcas.fundir(cuaderno)
                evidencia.actualizar_video(
                    item.video.name,
                    candidatos=[{"instante": m.instante, "fuerza": m.fuerza}
                                for m in cuaderno.marcas],
                    decisiones=[{"inicio": m.inicio, "fin": m.fin, "instante": m.instante,
                                 "estado": m.estado, "nota": m.nota} for m in cuaderno.marcas],
                    validos=len(cuaderno.validas), pendientes=len(cuaderno.pendientes),
                )
                if not tramos:
                    raise ValueError("no hay jugadas aprobadas")
            else:
                manifiesto = cargar_defensa(item.decisiones, item.video)
                tramos = defensa.tramos_exportables(manifiesto)
                evidencia.actualizar_video(
                    item.video.name, validos=len(manifiesto.seleccionadas), pendientes=0,
                    decisiones=[{"inicio": r.inicio, "fin": r.tiro, "instante": r.tiro,
                                 "estado": r.estado, "nota": r.categoria}
                                for r in manifiesto.repeticiones],
                )
            evidencia.copiar_etiqueta(item.decisiones, item.video)
            destino = salida / f"{item.video.stem}_{item.tipo}.mp4"
            exportar(str(item.video), tramos, str(destino))
            generados += 1
            evidencia.actualizar_video(item.video.name, salida=destino)
            informar(f"{item.video.name}: resultado generado en Resultados.")
        except Exception as err:
            errores += 1
            evidencia.actualizar_video(item.video.name, error=str(err))
            informar(f"{item.video.name}: ERROR: {err}", "ERROR", err)

    detalle = (f"Encontrados: {encontrados} · Listos: {listos} · "
               f"Generados: {generados} · Pendientes: {pendientes} · Errores: {errores}")
    if not listos:
        detalle += ". Ningún video está listo; requieren revisión previa."
    informar(detalle)
    estado = "completado" if not errores else "con errores"
    evidencia.finalizar(estado, detalle)
    return ResultadoTarea(estado, 1 if errores else (2 if not listos else 0), detalle)


def _ruta_requerida(valor: str | Path, nombre: str) -> str:
    ruta = str(valor).strip()
    if not ruta:
        raise ValueError(f"Falta seleccionar {nombre}.")
    return ruta


def tarea_bateo(video: str | Path, perfil: str | Path, trabajo: str | Path, *,
                 interactivo: bool, registrar: Registrar = print,
                 ejecutar: Callable = agente.ejecutar) -> ResultadoTarea:
    """Ejecuta el agente y traduce su estado al código que usa el CLI."""
    video = _ruta_requerida(video, "el video")
    perfil = _ruta_requerida(perfil, "el perfil JSON")
    trabajo = _ruta_requerida(trabajo, "la carpeta de trabajo")
    registrar("Iniciando flujo de bateo...")
    estado = ejecutar(video, perfil, trabajo, interactivo=interactivo,
                      registrar=registrar, preguntar=lambda _: "s")
    codigo = 2 if estado == agente.PAUSA_HUMANA else 0
    if codigo == 2:
        detalle = "Pausa para revisión humana; el trabajo quedó guardado."
    else:
        detalle = "Proceso de bateo completado."
    registrar(f"{detalle} Código de salida: {codigo}.")
    return ResultadoTarea(estado=estado, codigo=codigo, detalle=detalle)


def tarea_defensa(video: str | Path, manifiesto: str | Path, salida: str | Path,
                  antes_extra: float | str = defensa.ANTES_EXTRA,
                  despues_tiro: float | str = defensa.DESPUES_TIRO, *,
                  registrar: Registrar = print,
                  cargar: Callable = defensa.cargar,
                  exportar: Callable = compactar.exportar) -> ResultadoTarea:
    """Valida el manifiesto defensivo y exporta sus seis repeticiones."""
    video = _ruta_requerida(video, "el video")
    manifiesto = _ruta_requerida(manifiesto, "el manifiesto JSON")
    salida = _ruta_requerida(salida, "el MP4 de salida")
    try:
        antes_extra = float(antes_extra)
        despues_tiro = float(despues_tiro)
    except (TypeError, ValueError) as err:
        raise ValueError("Los márgenes deben ser números.") from err
    if (not math.isfinite(antes_extra) or not math.isfinite(despues_tiro)
            or antes_extra < 0 or despues_tiro < 0):
        raise ValueError("Cada margen debe ser un número mayor o igual a cero.")

    registrar("Validando el manifiesto de defensa...")
    datos = cargar(manifiesto, video)
    tramos = defensa.tramos_exportables(
        datos, antes_extra=antes_extra, despues_tiro=despues_tiro
    )
    registrar("Exportando 6 repeticiones defensivas revisadas...")
    destino = exportar(video, tramos, salida)
    detalle = f"6 repeticiones exportadas en {destino}."
    registrar(f"{detalle} Código de salida: 0.")
    return ResultadoTarea(estado="completado", codigo=0, detalle=detalle)


class WorkerUnico:
    """Un hilo de trabajo y una cola de eventos, independientes de Tkinter."""

    def __init__(self) -> None:
        self.eventos: queue.Queue[tuple[str, object]] = queue.Queue()
        self._cerrojo = threading.Lock()
        self._ocupado = False
        self._hilo: threading.Thread | None = None

    @property
    def ocupado(self) -> bool:
        with self._cerrojo:
            return self._ocupado

    def iniciar(self, tarea: Callable[[Registrar], object]) -> bool:
        with self._cerrojo:
            if self._ocupado:
                return False
            self._ocupado = True
        self._hilo = threading.Thread(target=self._ejecutar, args=(tarea,), daemon=True)
        self._hilo.start()
        return True

    def _ejecutar(self, tarea: Callable[[Registrar], object]) -> None:
        try:
            resultado = tarea(lambda mensaje: self.eventos.put(("log", str(mensaje))))
            self.eventos.put(("ok", resultado))
        except Exception as err:  # la UI presenta cualquier fallo del motor
            self.eventos.put(("error", err))
        finally:
            with self._cerrojo:
                self._ocupado = False

    def esperar(self, timeout: float | None = None) -> None:
        if self._hilo is not None:
            self._hilo.join(timeout)


def _abrir_flujo_carpeta() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    raiz = tk.Tk()
    raiz.title("Cortador de turnos")
    raiz.geometry("820x560")
    raiz.minsize(640, 460)
    raiz.columnconfigure(0, weight=1)
    raiz.rowconfigure(1, weight=1)
    worker = WorkerUnico()
    carpeta = tk.StringVar()
    estado = tk.StringVar(value="Listo")

    cabecera = ttk.Frame(raiz, padding=18)
    cabecera.grid(row=0, column=0, sticky="ew")
    cabecera.columnconfigure(1, weight=1)
    ttk.Label(cabecera, text="Procesar videos del jugador",
              font=("TkDefaultFont", 16, "bold")).grid(
                  row=0, column=0, columnspan=3, sticky="w")
    ttk.Label(cabecera,
              text="Selecciona o pega la carpeta del jugador y pulsa Procesar carpeta.",
              wraplength=760).grid(row=1, column=0, columnspan=3,
                                   sticky="w", pady=(5, 16))
    ttk.Label(cabecera, text="Carpeta del jugador").grid(row=2, column=0, sticky="w")
    ttk.Entry(cabecera, textvariable=carpeta).grid(
        row=2, column=1, sticky="ew", padx=10)

    def examinar():
        elegida = filedialog.askdirectory()
        if elegida:
            carpeta.set(elegida)

    boton_examinar = ttk.Button(cabecera, text="Examinar…", command=examinar)
    boton_examinar.grid(row=2, column=2)
    cuerpo = ttk.Frame(raiz, padding=(18, 0, 18, 18))
    cuerpo.grid(row=1, column=0, sticky="nsew")
    cuerpo.columnconfigure(0, weight=1)
    cuerpo.rowconfigure(4, weight=1)
    boton_procesar = ttk.Button(cuerpo, text="Procesar carpeta")
    boton_procesar.grid(row=0, column=0, sticky="ew", ipady=10, pady=(4, 12))
    acciones = ttk.Frame(cuerpo)
    acciones.grid(row=1, column=0, sticky="ew", pady=(0, 8))
    acciones.columnconfigure((0, 1), weight=1)

    def crear_paquete():
        sugerido = f"PaqueteQA-{qa._ahora().strftime('%Y%m%dT%H%M%SZ')}.zip"
        destino = filedialog.asksaveasfilename(
            title="Guardar paquete de QA", defaultextension=".zip",
            initialfile=sugerido, filetypes=[("Archivo ZIP", "*.zip")])
        try:
            creado = qa.crear_paquete_qa(destino or None)
            messagebox.showinfo("Paquete creado", f"Se creó el paquete en:\n{creado}")
        except Exception as err:
            qa.registrar_log("ERROR", "No se pudo crear el paquete", excepcion=err)
            messagebox.showerror("No se pudo crear", str(err))

    def abrir_datos():
        destino = qa.directorio_datos()
        destino.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(destino)  # type: ignore[attr-defined]
        except Exception as err:
            messagebox.showerror("No se pudo abrir", str(err))

    ttk.Button(acciones, text="Crear paquete para enviar", command=crear_paquete).grid(
        row=0, column=0, sticky="ew", padx=(0, 5))
    ttk.Button(acciones, text="Abrir carpeta de datos", command=abrir_datos).grid(
        row=0, column=1, sticky="ew", padx=(5, 0))
    ttk.Label(cuerpo, textvariable=estado).grid(row=2, column=0, sticky="w", pady=(0, 8))
    ttk.Label(cuerpo, text="Actividad").grid(row=3, column=0, sticky="w")
    log = tk.Text(cuerpo, height=14, wrap="word", state="disabled")
    log.grid(row=4, column=0, sticky="nsew")
    barra = ttk.Scrollbar(cuerpo, orient="vertical", command=log.yview)
    barra.grid(row=4, column=1, sticky="ns")
    log.configure(yscrollcommand=barra.set)

    def registrar(mensaje):
        log.configure(state="normal")
        log.insert("end", str(mensaje) + "\n")
        log.see("end")
        log.configure(state="disabled")

    def habilitar(valor):
        nuevo = "normal" if valor else "disabled"
        boton_procesar.configure(state=nuevo)
        boton_examinar.configure(state=nuevo)

    def iniciar_carpeta():
        ruta = carpeta.get()  # StringVar se captura antes de entrar al worker.
        if worker.iniciar(lambda reg: tarea_carpeta_jugador(ruta, registrar=reg)):
            habilitar(False)
            estado.set("Procesando…")
            registrar("—")
        else:
            messagebox.showwarning("Trabajo en curso", "Espera a que termine el trabajo actual.")

    boton_procesar.configure(command=iniciar_carpeta)

    def vaciar_eventos():
        try:
            while True:
                tipo, dato = worker.eventos.get_nowait()
                if tipo == "log":
                    registrar(dato)
                elif tipo == "ok":
                    habilitar(True)
                    estado.set(dato.detalle)
                else:
                    habilitar(True)
                    estado.set("No se pudo completar")
                    registrar(f"ERROR: {dato}")
                    messagebox.showerror("No se pudo completar", str(dato))
        except queue.Empty:
            pass
        raiz.after(100, vaciar_eventos)

    def cerrar():
        if worker.ocupado:
            messagebox.showwarning(
                "Trabajo en curso", "Espera a que termine el trabajo antes de cerrar."
            )
            return
        raiz.destroy()

    raiz.protocol("WM_DELETE_WINDOW", cerrar)
    raiz.after(100, vaciar_eventos)
    raiz.mainloop()


def abrir() -> None:
    """Crea la ventana principal y mantiene el bucle de Tkinter."""
    return _abrir_flujo_carpeta()
