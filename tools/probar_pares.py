"""La prueba entera sobre uno o varios pares (crudo, montaje), en un comando.

Cuando llegue material nuevo hay que hacer siempre lo mismo: sacar de cada montaje los
tramos que el scout conservo, ver que candidatos propone el motor, puntuar, y -- lo que
de verdad importa -- comprobar si la calibracion actual sigue siendo la buena cuando se
mide contra TODOS los pares a la vez y no contra uno.

Hacerlo a mano son seis comandos por par y es facil olvidar el ultimo, que es justo el
que puede tumbar una conclusion anterior. Por eso esto.

    python tools/probar_pares.py --perfil perfiles/camara.json \
        Video/turno1_crudo.mp4 Video/turno1_montaje.mp4 \
        Video/turno2_crudo.mp4 Video/turno2_montaje.mp4

Los pares van en orden: crudo, montaje, crudo, montaje. Las referencias quedan en
`fixtures/` y se versionan; son JSON de unos kilobytes, no video.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "tools"))

import alinear  # noqa: E402
from evaluar import comparar, fundir_simple, por_tramo  # noqa: E402
from cortador import eventos  # noqa: E402
from cortador.perfil import Perfil  # noqa: E402
BARRIDO = np.round(np.arange(0.6, 3.01, 0.2), 1)   # redondeado: si no, 1,4 es 1,3999...


@dataclass
class Par:
    """Un turno con su montaje: la referencia y lo que el motor propone para el."""

    nombre: str
    referencia: list[tuple[float, float]]
    instantes: list[float]      # todos los candidatos
    dentro: list[float]         # los que caen en un tramo que el scout conservo
    duracion: float

    def tramos(self, antes: float, despues: float, solo_dentro: bool = True):
        origen = self.dentro if solo_dentro else self.instantes
        return fundir_simple([(max(0.0, i - antes), i + despues) for i in origen])


def preparar(ruta_crudo: str, ruta_montaje: str, perfil: Perfil,
             sigmas: float, guardar: Path | None) -> Par:
    nombre = Path(ruta_crudo).stem
    tramos, duracion, _ = alinear.alinear(ruta_crudo, ruta_montaje)
    referencia = [(t.inicio, t.fin) for t in tramos]

    if guardar:
        guardar.write_text(json.dumps({
            "crudo": ruta_crudo, "montaje": ruta_montaje,
            "duracion": round(duracion, 2),
            "tramos": [{"inicio": t.inicio, "fin": t.fin, "correlacion": t.correlacion}
                       for t in tramos],
        }, indent=2, ensure_ascii=False), encoding="utf-8")

    candidatos = eventos.detectar(ruta_crudo, perfil, sigmas=sigmas)
    instantes = [c.instante for c in candidatos]
    dentro = [i for i in instantes if any(a <= i <= b for a, b in referencia)]
    return Par(nombre, referencia, instantes, dentro, duracion)


def barrer(pares: list[Par]) -> tuple[float, float, float, np.ndarray]:
    """El mejor (antes, despues) medido sobre todos los pares juntos.

    Se promedia el F1 de cada par en vez de juntar todos los tramos en una bolsa: asi un
    turno largo no decide la calibracion de los cortos por pesar mas segundos.
    """
    malla = np.zeros((len(BARRIDO), len(BARRIDO)))
    for fa, antes in enumerate(BARRIDO):
        for fd, despues in enumerate(BARRIDO):
            malla[fa, fd] = float(np.mean([
                comparar(p.tramos(antes, despues), p.referencia)["f1"] for p in pares]))
    fa, fd = np.unravel_index(malla.argmax(), malla.shape)
    return float(BARRIDO[fa]), float(BARRIDO[fd]), float(malla[fa, fd]), malla


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("videos", nargs="+", help="crudo montaje [crudo montaje ...]")
    p.add_argument("--perfil", required=True, help="el ROI del cajon de esa camara")
    p.add_argument("--sigmas", type=float, default=eventos.SIGMAS)
    p.add_argument("--sin-guardar", action="store_true",
                   help="no escribir las referencias en fixtures/")
    args = p.parse_args()

    if len(args.videos) % 2:
        p.error("los videos van por parejas: crudo montaje crudo montaje ...")

    perfil = Perfil.cargar(args.perfil)
    pares: list[Par] = []
    for crudo, montaje in zip(args.videos[::2], args.videos[1::2]):
        destino = None if args.sin_guardar else (
            RAIZ / "fixtures" / f"referencia_{Path(crudo).stem}.json")
        print(f"  alineando {Path(crudo).name} ...", flush=True)
        pares.append(preparar(crudo, montaje, perfil, args.sigmas, destino))

    antes, despues = eventos.ANTES, eventos.DESPUES

    print(f"\n  CON LA CALIBRACION ACTUAL (antes {antes}, despues {despues})\n")
    print(f"  {'turno':<28} {'ref':>6} {'techo':>6}  prec   cob    F1")
    for par in pares:
        m = comparar(par.tramos(antes, despues), par.referencia)
        techo = comparar(par.tramos(antes, despues, solo_dentro=False), par.referencia)
        segundos = sum(f - i for i, f in par.referencia)
        print(f"  {par.nombre[:28]:<28} {segundos:5.1f}s {techo['cobertura']:5.0%}  "
              f"{m['precision']:4.0%}  {m['cobertura']:4.0%}  {m['f1']:4.0%}")
    medio = float(np.mean([comparar(p.tramos(antes, despues), p.referencia)["f1"]
                           for p in pares]))
    print(f"  {'':<28} {'':>6} {'':>6}              F1 medio {medio:4.0%}")

    mejor_antes, mejor_despues, mejor_f1, malla = barrer(pares)
    print(f"\n  BARRIDO SOBRE LOS {len(pares)} PARES A LA VEZ\n")
    print("        " + "  ".join(f"{d:4.1f}" for d in BARRIDO[::2]) + "   <- despues")
    for fa, a in enumerate(BARRIDO):
        if fa % 2:
            continue
        print(f"  {a:4.1f}  " + "  ".join(f"{v:4.0%}" for v in malla[fa, ::2]))

    print(f"\n  mejor: antes {mejor_antes:.1f}, despues {mejor_despues:.1f} -> F1 {mejor_f1:.0%}")
    if (round(mejor_antes, 1), round(mejor_despues, 1)) == (antes, despues):
        print("  La calibracion actual sigue siendo la buena.")
    else:
        print(f"  La calibracion actual ({antes}, {despues}) da {medio:.0%}: "
              f"{mejor_f1 - medio:+.0%}.")
        print("  Usa esta diferencia como diagnostico; no cambies automaticamente ANTES y")
        print("  DESPUES. Los margenes de entrega los confirma el cliente. Si los cambias,")
        print("  anota en BITACORA.md contra cuantos pares se midieron y quien lo valido.")

    if len(pares) == 1:
        print("\n  AVISO: un solo par. Un numero sacado de un unico turno no dice si el")
        print("  motor es bueno, dice como de bien se ajusto a ese turno.")

    print("\n  tramo a tramo, lo que se recupera de cada referencia:")
    for par in pares:
        print(f"   {par.nombre}")
        for (inicio, fin), fraccion in por_tramo(par.tramos(antes, despues), par.referencia):
            print(f"     {inicio:6.2f}-{fin:6.2f}  {fraccion:4.0%}  {'#' * round(fraccion * 20)}")
    print()


if __name__ == "__main__":
    main()
