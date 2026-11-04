"""Cuanto se parece lo que produce el motor a lo que el scout entrego a mano.

Hasta ahora la unica forma de saber si un cambio mejoraba o empeoraba era mirar los
clips. Con un par (crudo, montaje) alineado por `alinear.py` hay una referencia, y con
ella la pregunta tiene numero: de los segundos que el scout conservo, cuantos salen; y
de los que salen, cuantos el habria tirado.

Se mide en segundos y no en swings a proposito: al scout le sobra medio segundo de
tiempo muerto igual que le falta medio segundo de swing, y contar aciertos por swing
esconde las dos cosas.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _solape(a: tuple[float, float], b: tuple[float, float]) -> float:
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def _duracion(tramos: list[tuple[float, float]]) -> float:
    return sum(f - i for i, f in tramos)


def _cargar_referencia(ruta: str) -> tuple[list[tuple[float, float]], float]:
    datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    return [(t["inicio"], t["fin"]) for t in datos["tramos"]], datos.get("duracion", 0.0)


def _cargar_propuesta(ruta: str) -> list[tuple[float, float]]:
    """Los tramos que el motor propone: de un cuaderno de marcas o de una referencia."""
    datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    if "marcas" in datos:
        from cortador.marcas import Cuaderno
        return fundir_simple([(m["inicio"], m["fin"]) for m in datos["marcas"]
                              if m["estado"] == "valido"])
    return fundir_simple([(t["inicio"], t["fin"]) for t in datos["tramos"]])


def fundir_simple(tramos: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Ordena y une los que se tocan, para no contar dos veces el mismo segundo."""
    tramos = sorted(tramos)
    if not tramos:
        return []
    unidos = [list(tramos[0])]
    for inicio, fin in tramos[1:]:
        if inicio <= unidos[-1][1]:
            unidos[-1][1] = max(unidos[-1][1], fin)
        else:
            unidos.append([inicio, fin])
    return [(a, b) for a, b in unidos]


def comparar(propuesta: list[tuple[float, float]],
             referencia: list[tuple[float, float]]) -> dict:
    """Precision, cobertura y F1 medidos en segundos."""
    acertados = sum(_solape(p, r) for p in propuesta for r in referencia)
    dura_prop, dura_ref = _duracion(propuesta), _duracion(referencia)
    precision = acertados / dura_prop if dura_prop else 0.0
    cobertura = acertados / dura_ref if dura_ref else 0.0
    f1 = 2 * precision * cobertura / (precision + cobertura) if precision + cobertura else 0.0
    return {
        "acertados": acertados,
        "sobran": dura_prop - acertados,
        "faltan": dura_ref - acertados,
        "precision": precision,
        "cobertura": cobertura,
        "f1": f1,
    }


def por_tramo(propuesta: list[tuple[float, float]],
              referencia: list[tuple[float, float]]) -> list[tuple[tuple[float, float], float]]:
    """Que fraccion de cada tramo de referencia cubre la propuesta."""
    salida = []
    for r in referencia:
        cubierto = sum(_solape(p, r) for p in propuesta)
        salida.append((r, cubierto / (r[1] - r[0]) if r[1] > r[0] else 0.0))
    return salida


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("propuesta", help="cuaderno de marcas, o JSON de tramos")
    p.add_argument("referencia", help="JSON de alinear.py")
    args = p.parse_args()

    referencia, duracion = _cargar_referencia(args.referencia)
    propuesta = _cargar_propuesta(args.propuesta)
    m = comparar(propuesta, referencia)

    print(f"\n  propuesta  {Path(args.propuesta).name}")
    print(f"  referencia {Path(args.referencia).name}\n")
    print(f"  el motor propone   {_duracion(propuesta):6.1f}s en {len(propuesta)} tramos")
    print(f"  el scout conservo  {_duracion(referencia):6.1f}s en {len(referencia)} tramos"
          f"   (de {duracion:.1f}s)\n")
    print(f"  aciertan           {m['acertados']:6.1f}s")
    print(f"  sobran             {m['sobran']:6.1f}s   el scout los habria tirado")
    print(f"  faltan             {m['faltan']:6.1f}s   el los conservo y no salen\n")
    print(f"  precision {m['precision']:.0%}   cobertura {m['cobertura']:.0%}   "
          f"F1 {m['f1']:.0%}\n")

    print("  tramo a tramo, cuanto se recupera de lo que el scout conservo:")
    for (inicio, fin), fraccion in por_tramo(propuesta, referencia):
        barra = "#" * round(fraccion * 20)
        print(f"   {inicio:6.2f}-{fin:6.2f}  {fraccion:4.0%}  {barra}")
    print()


if __name__ == "__main__":
    main()
