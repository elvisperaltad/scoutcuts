"""Interfaz por linea de comandos (fase 1: sin pantalla de revision)."""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from . import agente as agente_mod
from . import compactar as compactar_mod
from . import defensa as defensa_mod
from . import defensa_ml as defensa_ml_mod
from . import eventos as eventos_mod
from . import ffmpeg
from .canal import analizar, cortar
from .marcas import Cuaderno, fundir
from .perfil import Perfil
from .reglas import Ajustes


def _ajustes_desde(args: argparse.Namespace) -> Ajustes:
    ajustes = Ajustes(
        gap_fusion=args.gap_fusion,
        min_duracion=args.min_duracion,
        colchon=args.colchon,
    )
    if args.umbral_cambio is not None:
        ajustes = replace(ajustes, umbral_cambio=args.umbral_cambio)
    return ajustes


def _tabla(segmentos) -> str:
    lineas = [f"{'#':>3}  {'inicio':>9}  {'fin':>9}  {'duracion':>9}  notas"]
    for i, s in enumerate(segmentos, start=1):
        lineas.append(
            f"{i:>3}  {_hms(s.inicio):>9}  {_hms(s.fin):>9}  {s.duracion:>8.1f}s  "
            + ", ".join(s.notas)
        )
    return "\n".join(lineas)


def _hms(t: float) -> str:
    h, resto = divmod(int(t), 3600)
    m, s = divmod(resto, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def cmd_calibrar(args: argparse.Namespace) -> int:
    """Dibuja el ROI del cajon sobre un fotograma y lo guarda como perfil de camara."""
    import cv2
    import numpy as np

    info = ffmpeg.info(args.video)
    instante = args.instante if args.instante is not None else info.duracion / 2



    proc = subprocess.run(
        [ffmpeg.ruta_ffmpeg(), "-v", "error", "-ss", f"{instante:.3f}", "-i", args.video,
         "-frames:v", "1", "-f", "image2pipe", "-vcodec", "rawvideo", "-pix_fmt", "bgr24", "-"],
        capture_output=True,
    )
    fotograma = np.frombuffer(proc.stdout, dtype=np.uint8)
    if fotograma.size < info.ancho * info.alto * 3:
        print("No se pudo extraer el fotograma de calibracion.", file=sys.stderr)
        return 1
    fotograma = fotograma[: info.ancho * info.alto * 3].reshape(info.alto, info.ancho, 3).copy()

    print("Arrastra el rectangulo sobre los DOS cajones y el plato. ENTER para confirmar.")
    x, y, ancho, alto = cv2.selectROI("Calibrar cajon de bateo", fotograma, showCrosshair=False)
    cv2.destroyAllWindows()
    if ancho == 0 or alto == 0:
        print("Calibracion cancelada.", file=sys.stderr)
        return 1

    perfil = Perfil(x=int(x), y=int(y), ancho=int(ancho), alto=int(alto),
                    video_ancho=info.ancho, video_alto=info.alto, origen=Path(args.video).name)
    perfil.guardar(args.perfil)
    print(f"Perfil guardado en {args.perfil}: {perfil.crop}")
    return 0


def cmd_analizar(args: argparse.Namespace) -> int:
    perfil = Perfil.cargar(args.perfil)
    resultado = analizar(args.video, perfil, _ajustes_desde(args), args.detector,
                         args.modo_identidad, registrar=print)
    print()
    print(_tabla(resultado.segmentos))
    return 0


def cmd_cortar(args: argparse.Namespace) -> int:
    perfil = Perfil.cargar(args.perfil)
    resultado = cortar(args.video, perfil, args.salida, _ajustes_desde(args), args.detector,
                       args.modo_identidad, registrar=print)
    print()
    print(_tabla(resultado.segmentos))
    print(f"\n{len(resultado.clips)} clips en {args.salida}")
    return 0


def _ruta_marcas(args: argparse.Namespace) -> Path:
    if args.marcas:
        return Path(args.marcas)
    return Path(args.video).with_suffix(".marcas.json")


def _tabla_marcas(cuaderno: Cuaderno) -> str:
    lineas = [f"{'#':>3}  {'inicio':>8}  {'fin':>8}  {'pico':>7}  estado"]
    for i, m in enumerate(cuaderno.marcas, start=1):
        lineas.append(
            f"{i:>3}  {m.inicio:>7.2f}s  {m.fin:>7.2f}s  {m.fuerza:>7.2f}  {m.estado}"
        )
    return "\n".join(lineas)


def _cuaderno_para(args: argparse.Namespace) -> tuple[Cuaderno, Path]:
    """El cuaderno guardado si existe; si no, uno nuevo con los candidatos detectados."""
    destino = _ruta_marcas(args)
    if destino.exists() and not getattr(args, "rehacer", False):
        cuaderno = Cuaderno.cargar(destino)
        print(f"Cuaderno existente: {destino}  ({cuaderno.resumen()})")
        return cuaderno, destino

    perfil = Perfil.cargar(args.perfil)
    candidatos = eventos_mod.detectar(args.video, perfil, args.sigmas)
    if not candidatos:
        raise RuntimeError(
            "No se detecto ningun candidato. Baja --sigmas o revisa que el ROI "
            "del perfil cubra el cajon en este video."
        )
    cuaderno = Cuaderno.desde_candidatos(
        args.video, candidatos, args.antes, args.despues, perfil=str(args.perfil)
    )
    print(f"{len(candidatos)} candidatos detectados.")
    return cuaderno, destino


def cmd_eventos(args: argparse.Namespace) -> int:
    """Lista los candidatos de swing sin abrir ninguna ventana."""
    cuaderno, destino = _cuaderno_para(args)
    print()
    print(_tabla_marcas(cuaderno))
    if args.guardar:
        cuaderno.guardar(destino)
        print(f"\nCuaderno en {destino}")
    return 0


def cmd_marcar(args: argparse.Namespace) -> int:
    """Abre la pantalla de marcado sobre los candidatos del turno."""
    from .revision import marcar

    cuaderno, destino = _cuaderno_para(args)
    cuaderno = marcar(cuaderno, destino)
    print(cuaderno.resumen())
    print(f"Cuaderno en {destino}")
    return 0


def cmd_compactar(args: argparse.Namespace) -> int:
    """Exporta el turno con solo los swings marcados como validos."""
    destino_marcas = _ruta_marcas(args)
    if not destino_marcas.exists():
        print(f"No hay marcas en {destino_marcas}. Pasa antes 'cortador marcar'.",
              file=sys.stderr)
        return 1

    cuaderno = Cuaderno.cargar(destino_marcas)
    tramos = fundir(cuaderno, args.separacion)
    if not tramos:
        print("Ninguna marca esta como valida: no hay nada que exportar.", file=sys.stderr)
        return 1

    original = ffmpeg.info(args.video).duracion
    util = compactar_mod.duracion_total(tramos)
    salida = compactar_mod.exportar(args.video, tramos, args.salida)

    print(f"{len(tramos)} tramos, {util:.1f}s de {original:.1f}s "
          f"({100 * util / original:.0f} %)")
    print(f"Escrito en {salida}")
    return 0


def cmd_defensa(args: argparse.Namespace) -> int:
    """Exporta seis repeticiones defensivas elegidas en un manifiesto humano."""
    manifiesto = defensa_mod.cargar(args.marcas, args.video)
    tramos = defensa_mod.tramos_exportables(
        manifiesto, antes_extra=args.antes_extra, despues_tiro=args.despues_tiro
    )
    salida = compactar_mod.exportar(args.video, tramos, args.salida)
    print(f"6 repeticiones defensivas revisadas, {compactar_mod.duracion_total(tramos):.1f}s")
    print(f"Escrito en {salida}")

    if not args.sin_entrenar:
        try:
            _, modelo = defensa_ml_mod.actualizar_desde_manifiesto(args.video, manifiesto)
        except Exception as err:  # el entrenamiento nunca debe tumbar la entrega
            print(f"Aviso: no se pudo actualizar el modelo de defensa ({err}).",
                  file=sys.stderr)
        else:
            total = modelo.total_ejemplos if modelo else 0
            estado = "calibrado" if modelo else "esperando ejemplos de las 3 categorias"
            print(f"Modelo de defensa: {estado} ({total} ejemplos acumulados en total)")
    return 0


def cmd_agente(args: argparse.Namespace) -> int:
    """Guía y reanuda el procesamiento local de una jornada.

    Devuelve 0 si la jornada quedó completa y 2 si espera una revisión humana.
    """
    resultado = agente_mod.ejecutar(
        args.video,
        args.perfil,
        args.trabajo,
        interactivo=args.interactivo,
        detector=args.detector,
        identidad=args.modo_identidad,
        sigmas=args.sigmas,
        antes=args.antes,
        despues=args.despues,
        separacion=args.separacion,
        ajustes=_ajustes_desde(args),
    )
    return 2 if resultado == agente_mod.PAUSA_HUMANA else 0


def cmd_app(args: argparse.Namespace) -> int:
    """Abre la aplicación de escritorio; Tkinter se carga solo aquí."""
    from .app import abrir

    abrir()
    return 0


def _raiz_usuarios(args: argparse.Namespace) -> Path:
    """La carpeta de usuarios: --raiz, o si falta, SCOUTCUTS_USUARIOS."""
    import os

    if args.raiz:
        return Path(args.raiz)
    entorno = os.environ.get("SCOUTCUTS_USUARIOS")
    if entorno:
        return Path(entorno)
    print(
        "error: falta --raiz (o la variable de entorno SCOUTCUTS_USUARIOS)",
        file=sys.stderr,
    )
    raise SystemExit(1)


def cmd_usuarios_crear(args: argparse.Namespace) -> int:
    """Registra una cuenta nueva (admin): `cortador usuarios crear`."""
    from .servidor.usuarios import TelegramIdInvalido, UsuarioYaExiste, Usuarios

    usuarios = Usuarios(_raiz_usuarios(args))
    try:
        usuario = usuarios.crear(args.telegram_id, args.nombre, cuota_mensual=args.cuota)
    except (UsuarioYaExiste, TelegramIdInvalido) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    partes = [f"Cuenta creada: {usuario.nombre}"]
    if usuario.telegram_id:
        partes.append(f"telegram_id={usuario.telegram_id}")
    partes.append(f"id={usuario.id}")
    partes.append(f"cuota_mensual={usuario.cuota_mensual}")
    print(", ".join(partes))
    print(f"Codigo de acceso para la PWA (entregalo al scout, no lo compartas "
          f"por otros canales): {usuario.codigo_acceso}")
    return 0


def cmd_usuarios_listar(args: argparse.Namespace) -> int:
    """Lista todas las cuentas registradas: `cortador usuarios listar`."""
    from .servidor.usuarios import Usuarios

    usuarios = Usuarios(_raiz_usuarios(args))
    listado = usuarios.listar()
    if not listado:
        print("No hay cuentas registradas todavia.")
        return 0
    for usuario in listado:
        estado = "activo" if usuario.activo else "desactivado"
        print(
            f"{usuario.id}  telegram_id={usuario.telegram_id or '(sin telegram)'}  "
            f"{usuario.nombre}  {estado}  "
            f"{usuario.usados_mes}/{usuario.cuota_mensual} videos este mes"
        )
    return 0


def _cambiar_estado_usuario(args: argparse.Namespace, activar: bool) -> int:
    from .servidor.usuarios import Usuarios

    usuarios = Usuarios(_raiz_usuarios(args))
    coincidencias = [u for u in usuarios.listar() if u.id == args.id]
    if not coincidencias:
        print(f"error: no encontramos ninguna cuenta con id {args.id!r}", file=sys.stderr)
        return 1
    usuario = coincidencias[0]
    if activar:
        usuarios.activar(usuario)
        print(f"Cuenta activada: {usuario.nombre} ({usuario.id})")
    else:
        usuarios.desactivar(usuario)
        print(f"Cuenta desactivada: {usuario.nombre} ({usuario.id})")
    return 0


def cmd_usuarios_activar(args: argparse.Namespace) -> int:
    return _cambiar_estado_usuario(args, activar=True)


def cmd_usuarios_desactivar(args: argparse.Namespace) -> int:
    return _cambiar_estado_usuario(args, activar=False)


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cortador",
        description="Parte una jornada de academia en un mp4 por turno al bate.",
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    p_app = sub.add_parser("app", help="abrir la aplicación de escritorio")
    p_app.set_defaults(func=cmd_app)

    def comunes(p: argparse.ArgumentParser) -> None:
        p.add_argument("video")
        p.add_argument("--perfil", required=True, help="JSON del perfil de camara (ROI)")

    def parametros(p: argparse.ArgumentParser) -> None:
        p.add_argument("--gap-fusion", type=float, default=Ajustes.gap_fusion, dest="gap_fusion",
                       help="segundos de ausencia que aun se fusionan si vuelve el mismo pelotero")
        p.add_argument("--min-duracion", type=float, default=Ajustes.min_duracion, dest="min_duracion",
                       help="descarta lo que dure menos (gente cruzando el cuadro)")
        p.add_argument("--detector", choices=("color", "yolo"), default="color",
                       help="presencia. color: OpenCV puro. yolo: YOLOv8n, mejor si el fondo cambia")
        p.add_argument("--identidad", choices=("color", "cnn"), default="color", dest="modo_identidad",
                       help="apariencia. color: histograma. cnn: ResNet-18, separa personas parecidas")
        p.add_argument("--umbral-cambio", type=float, default=None, dest="umbral_cambio",
                       help="distancia de apariencia a partir de la cual son dos peloteros")
        p.add_argument("--colchon", type=float, default=Ajustes.colchon,
                       help="segundos de margen a cada lado del turno")

    p_cal = sub.add_parser("calibrar", help="dibujar el ROI del cajon (una vez por camara)")
    p_cal.add_argument("video")
    p_cal.add_argument("--perfil", required=True)
    p_cal.add_argument("--instante", type=float, default=None, help="segundo del fotograma a usar")
    p_cal.set_defaults(func=cmd_calibrar)

    p_ana = sub.add_parser("analizar", help="detectar turnos sin exportar nada")
    comunes(p_ana)
    parametros(p_ana)
    p_ana.set_defaults(func=cmd_analizar)

    p_cor = sub.add_parser("cortar", help="detectar turnos y exportar un mp4 por turno")
    comunes(p_cor)
    parametros(p_cor)
    p_cor.add_argument("--salida", required=True, help="carpeta donde dejar los clips")
    p_cor.set_defaults(func=cmd_cortar)

    def marcado(p: argparse.ArgumentParser) -> None:
        p.add_argument("--marcas", default=None,
                       help="JSON del cuaderno (por defecto, junto al video)")

    def deteccion(p: argparse.ArgumentParser, incluir_rehacer: bool = True) -> None:
        p.add_argument("--sigmas", type=float, default=eventos_mod.SIGMAS,
                       help="cuanto ha de destacar la actividad para ser candidato")
        p.add_argument("--antes", type=float, default=eventos_mod.ANTES,
                       help="segundos de tramo antes del pico")
        p.add_argument("--despues", type=float, default=eventos_mod.DESPUES,
                       help="segundos de tramo despues del pico")
        if incluir_rehacer:
            p.add_argument("--rehacer", action="store_true",
                           help="volver a detectar aunque ya exista el cuaderno")

    p_eve = sub.add_parser("eventos", help="listar los candidatos de swing de un turno")
    comunes(p_eve)
    marcado(p_eve)
    deteccion(p_eve)
    p_eve.add_argument("--guardar", action="store_true", help="escribir el cuaderno")
    p_eve.set_defaults(func=cmd_eventos)

    p_mar = sub.add_parser("marcar", help="decidir a mano que swing vale (hubo pelota)")
    comunes(p_mar)
    marcado(p_mar)
    deteccion(p_mar)
    p_mar.set_defaults(func=cmd_marcar)

    p_com = sub.add_parser("compactar", help="exportar el turno sin los tiempos muertos")
    p_com.add_argument("video")
    marcado(p_com)
    p_com.add_argument("--salida", required=True, help="mp4 de destino")
    p_com.add_argument("--separacion", type=float, default=0.5,
                       help="segundos por debajo de los cuales dos swings salen pegados")
    p_com.set_defaults(func=cmd_compactar)

    p_def = sub.add_parser(
        "defensa", help="exportar 2 repeticiones revisadas por cada direccion defensiva"
    )
    p_def.add_argument("video")
    p_def.add_argument("--marcas", required=True, help="manifiesto JSON v1 revisado")
    p_def.add_argument("--salida", required=True, help="mp4 de destino")
    p_def.add_argument("--antes-extra", type=float, default=defensa_mod.ANTES_EXTRA,
                       help="margen antes de la preparacion marcada")
    p_def.add_argument("--despues-tiro", type=float, default=defensa_mod.DESPUES_TIRO,
                       help="margen corto despues del tiro")
    p_def.add_argument("--sin-entrenar", action="store_true",
                       help="no actualizar el modelo de defensa con este manifiesto")
    p_def.set_defaults(func=cmd_defensa)

    p_age = sub.add_parser(
        "agente",
        help="guiar y reanudar todo el flujo local de una jornada",
    )
    comunes(p_age)
    parametros(p_age)
    deteccion(p_age, incluir_rehacer=False)
    p_age.add_argument(
        "--trabajo", default="trabajo-agente",
        help="carpeta durable de estado, turnos, marcas y compactos",
    )
    p_age.add_argument(
        "--separacion", type=float, default=0.5,
        help="segundos por debajo de los cuales dos swings salen pegados",
    )
    p_age.add_argument(
        "--no-interactivo", action="store_false", dest="interactivo",
        help="avanzar solo pasos seguros y detenerse antes de abrir la revisión",
    )
    p_age.set_defaults(func=cmd_agente, interactivo=True)

    p_usu = sub.add_parser(
        "usuarios", help="administrar cuentas de scouts (login por Telegram ID + cuota)",
    )
    sub_usu = p_usu.add_subparsers(dest="subcomando", required=True)

    def _raiz_arg(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--raiz", default=None,
            help="carpeta de usuarios (si falta, usa SCOUTCUTS_USUARIOS)",
        )

    p_usu_crear = sub_usu.add_parser("crear", help="registrar una cuenta nueva")
    _raiz_arg(p_usu_crear)
    p_usu_crear.add_argument(
        "--telegram-id", default="", dest="telegram_id",
        help="opcional: vacio para una cuenta solo-web (login por codigo de acceso)")
    p_usu_crear.add_argument("--nombre", required=True)
    p_usu_crear.add_argument(
        "--cuota", type=int, default=20, help="videos permitidos por mes (default: 20)")
    p_usu_crear.set_defaults(func=cmd_usuarios_crear)

    p_usu_listar = sub_usu.add_parser("listar", help="listar todas las cuentas")
    _raiz_arg(p_usu_listar)
    p_usu_listar.set_defaults(func=cmd_usuarios_listar)

    p_usu_activar = sub_usu.add_parser("activar", help="reactivar una cuenta desactivada")
    _raiz_arg(p_usu_activar)
    p_usu_activar.add_argument("--id", required=True, help="id interno de la cuenta")
    p_usu_activar.set_defaults(func=cmd_usuarios_activar)

    p_usu_desactivar = sub_usu.add_parser("desactivar", help="desactivar una cuenta")
    _raiz_arg(p_usu_desactivar)
    p_usu_desactivar.add_argument("--id", required=True, help="id interno de la cuenta")
    p_usu_desactivar.set_defaults(func=cmd_usuarios_desactivar)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ffmpeg.FfmpegNoEncontrado, RuntimeError, ValueError, OSError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
