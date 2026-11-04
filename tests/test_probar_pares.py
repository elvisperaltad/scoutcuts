"""El barrido conjunto: la calibracion se decide contra todos los pares, no contra uno.

Lo que se prueba aqui es la trampa que este script existe para evitar. Con un solo turno
cualquier parametro se puede ajustar hasta que parezca perfecto; el numero que sale no
dice si el motor es bueno, dice cuanto se ajusto a ese turno. En cuanto hay dos pares que
piden cosas distintas, el barrido tiene que buscar el termino medio.
"""

from __future__ import annotations

import numpy as np

from probar_pares import Par, barrer


def _par(nombre, referencia, instantes):
    dentro = [i for i in instantes if any(a <= i <= b for a, b in referencia)]
    return Par(nombre, referencia, instantes, dentro, duracion=100.0)


def test_los_tramos_salen_del_instante_y_se_funden():
    par = _par("x", [(0.0, 10.0)], [2.0, 3.0, 8.0])
    assert par.tramos(antes=1.0, despues=1.0) == [(1.0, 4.0), (7.0, 9.0)]


def test_solo_dentro_descarta_los_candidatos_fuera_de_la_referencia():
    par = _par("x", [(0.0, 5.0)], [2.0, 50.0])
    assert par.tramos(1.0, 1.0, solo_dentro=True) == [(1.0, 3.0)]
    assert len(par.tramos(1.0, 1.0, solo_dentro=False)) == 2


def test_un_solo_par_encuentra_su_ventana_exacta():
    """Referencia de 4 s con el pico en el centro: la ventana buena es 2,0 / 2,0."""
    par = _par("x", [(8.0, 12.0)], [10.0])
    antes, despues, f1, _ = barrer([par])
    assert f1 > 0.95
    assert (antes, despues) == (2.0, 2.0)


def test_dos_pares_que_piden_ventanas_distintas_no_se_pueden_contentar_los_dos():
    """Uno quiere ventana corta y el otro larga: el mejor conjunto es peor que ambos.

    Es justo lo que un solo par no puede enseniar. Y ojo, el termino medio no tiene por
    que ganar: el F1 medio no es concavo, y aqui las dos ventanas extremas empatan por
    encima de la intermedia. Por eso el script imprime la malla entera y no solo el
    maximo -- el maximo solo puede estar en un empate.
    """
    corto = _par("corto", [(9.0, 11.0)], [10.0])      # su optimo en solitario: 1,0
    largo = _par("largo", [(7.0, 13.0)], [10.0])      # su optimo en solitario: 3,0
    _, _, f1_juntos, _ = barrer([corto, largo])

    assert barrer([corto])[2] > 0.99                  # cada uno por separado, perfecto
    assert barrer([largo])[2] > 0.99
    assert f1_juntos < 0.8                            # juntos, no


def test_el_f1_se_promedia_por_par_y_no_por_segundos():
    """Un turno largo no debe decidir la calibracion de los cortos por pesar mas."""
    corto = _par("corto", [(9.5, 10.5)], [10.0])
    largo = _par("largo", [(0.0, 60.0)], [10.0])
    _, _, f1, malla = barrer([corto, largo])
    # El par largo no llega ni al 10 % de cobertura con ninguna ventana del barrido,
    # asi que el medio no puede acercarse a 1 aunque el corto salga perfecto.
    assert f1 < 0.7
    assert malla.shape[0] == malla.shape[1]


def test_la_malla_recorre_todas_las_combinaciones():
    par = _par("x", [(8.0, 12.0)], [10.0])
    _, _, _, malla = barrer([par])
    assert np.all(malla >= 0.0) and np.all(malla <= 1.0)
    assert malla.max() > malla.min()       # el parametro importa
