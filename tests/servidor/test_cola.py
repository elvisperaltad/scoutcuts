import io
import threading
import time


def _almacen(tmp_path):
    from cortador.servidor.almacen import Almacen

    return Almacen(tmp_path / "datos")


def _trabajo(guardia, nombre):
    trabajo = guardia.crear(nombre, 5)
    guardia.guardar_entrada(trabajo, io.BytesIO(b"video"))
    return trabajo


def _cola(guardia, procesar):
    from cortador.servidor.cola import Cola

    cola = Cola(guardia, procesar)
    return cola


def test_procesa_de_uno_en_uno_y_en_orden_de_llegada(tmp_path):
    guardia = _almacen(tmp_path)
    cerrojo = threading.Lock()
    activos, pico, orden = [], [], []

    def procesar(trabajo, almacen):
        with cerrojo:
            activos.append(trabajo.id)
            pico.append(len(activos))
        time.sleep(0.02)
        with cerrojo:
            activos.remove(trabajo.id)
            orden.append(trabajo.id)

    cola = _cola(guardia, procesar)
    try:
        esperados = [_trabajo(guardia, f"turno{i}.mp4").id for i in range(4)]
        for identificador in esperados:
            cola.encolar(guardia.estado(identificador))
        assert cola.esperar(10) is True
    finally:
        cola.detener(5)

    assert max(pico) == 1          # un solo núcleo: nunca dos a la vez
    assert orden == esperados


def test_posicion_dice_cuantos_trabajos_hay_delante(tmp_path):
    guardia = _almacen(tmp_path)
    empezo = threading.Event()
    suelta = threading.Event()

    def procesar(trabajo, almacen):
        empezo.set()
        assert suelta.wait(10)

    cola = _cola(guardia, procesar)
    try:
        primero, segundo, tercero = (_trabajo(guardia, f"t{i}.mp4") for i in range(3))
        cola.encolar(primero)
        assert empezo.wait(10)
        cola.encolar(segundo)
        cola.encolar(tercero)

        assert cola.posicion(primero.id) == 0
        assert cola.posicion(segundo.id) == 1
        assert cola.posicion(tercero.id) == 2
        assert cola.posicion("f" * 32) is None
        assert guardia.estado(primero.id).estado == "procesando"
        assert guardia.estado(tercero.id).estado == "en_cola"

        suelta.set()
        assert cola.esperar(10) is True
    finally:
        suelta.set()
        cola.detener(5)

    assert cola.posicion(primero.id) is None


def test_un_fallo_marca_error_depurado_y_sigue_con_el_siguiente(tmp_path):
    from cortador.servidor import almacen as mod

    guardia = _almacen(tmp_path)
    procesados = []

    def procesar(trabajo, almacen):
        if trabajo.nombre == "falla.mp4":
            raise RuntimeError("fallo simulado al abrir C:/Users/Ana/Videos/falla.mp4")
        procesados.append(trabajo.nombre)
        trabajo.estado = mod.LISTO
        trabajo.mensaje = "Tu montaje está listo."
        almacen.guardar_estado(trabajo)

    cola = _cola(guardia, procesar)
    try:
        falla = _trabajo(guardia, "falla.mp4")
        sirve = _trabajo(guardia, "sirve.mp4")
        cola.encolar(falla)
        cola.encolar(sirve)
        assert cola.esperar(10) is True
    finally:
        cola.detener(5)

    roto = guardia.estado(falla.id)
    assert roto.estado == mod.ERROR
    assert roto.mensaje and "Traceback" not in roto.mensaje
    for secreto in ("C:/Users", "C:\\Users", "Ana"):
        assert secreto not in roto.mensaje
        assert secreto not in roto.detalle
    assert "fallo simulado" in roto.detalle       # la causa queda para el equipo
    assert procesados == ["sirve.mp4"]
    assert guardia.estado(sirve.id).estado == mod.LISTO


def test_encolar_devuelve_la_posicion_y_deja_el_trabajo_en_cola(tmp_path):
    from cortador.servidor import almacen as mod

    guardia = _almacen(tmp_path)
    suelta = threading.Event()
    empezo = threading.Event()

    def procesar(trabajo, almacen):
        empezo.set()
        assert suelta.wait(10)

    cola = _cola(guardia, procesar)
    try:
        primero = _trabajo(guardia, "a.mp4")
        assert cola.encolar(primero) == 0
        assert empezo.wait(10)
        segundo = _trabajo(guardia, "b.mp4")
        assert cola.encolar(segundo) == 1
        assert guardia.estado(segundo.id).estado == mod.EN_COLA
    finally:
        suelta.set()
        cola.detener(5)


def test_detener_no_se_queda_colgada_sin_trabajos(tmp_path):
    guardia = _almacen(tmp_path)
    cola = _cola(guardia, lambda trabajo, almacen: None)
    cola.iniciar()

    assert cola.esperar(5) is True
    assert cola.detener(5) is True


def _cola_con_al_terminar(guardia, procesar, al_terminar):
    from cortador.servidor.cola import Cola

    return Cola(guardia, procesar, al_terminar=al_terminar)


def test_al_terminar_recibe_el_trabajo_listo_releido_de_disco(tmp_path):
    from cortador.servidor import almacen as mod

    guardia = _almacen(tmp_path)
    llamadas = []

    def procesar(trabajo, almacen):
        trabajo.estado = mod.LISTO
        trabajo.mensaje = "Tu montaje esta listo."
        almacen.guardar_estado(trabajo)

    cola = _cola_con_al_terminar(guardia, procesar, llamadas.append)
    try:
        trabajo = _trabajo(guardia, "a.mp4")
        cola.encolar(trabajo)
        assert cola.esperar(10) is True
    finally:
        cola.detener(5)

    assert len(llamadas) == 1
    assert llamadas[0].id == trabajo.id
    assert llamadas[0].estado == mod.LISTO
    assert llamadas[0].mensaje == "Tu montaje esta listo."


def test_al_terminar_recibe_el_trabajo_en_error_cuando_el_procesador_falla(tmp_path):
    from cortador.servidor import almacen as mod

    guardia = _almacen(tmp_path)
    llamadas = []

    def procesar(trabajo, almacen):
        raise RuntimeError("fallo simulado")

    cola = _cola_con_al_terminar(guardia, procesar, llamadas.append)
    try:
        trabajo = _trabajo(guardia, "b.mp4")
        cola.encolar(trabajo)
        assert cola.esperar(10) is True
    finally:
        cola.detener(5)

    assert len(llamadas) == 1
    assert llamadas[0].id == trabajo.id
    assert llamadas[0].estado == mod.ERROR


def test_al_terminar_que_lanza_no_tumba_el_hilo_ni_afecta_al_siguiente(tmp_path):
    from cortador.servidor import almacen as mod

    guardia = _almacen(tmp_path)
    llamadas = []

    def procesar(trabajo, almacen):
        trabajo.estado = mod.LISTO
        trabajo.mensaje = "listo"
        almacen.guardar_estado(trabajo)

    def al_terminar(trabajo):
        llamadas.append(trabajo.id)
        raise RuntimeError("el callback explota, no debe tumbar la cola")

    cola = _cola_con_al_terminar(guardia, procesar, al_terminar)
    try:
        primero = _trabajo(guardia, "a.mp4")
        segundo = _trabajo(guardia, "b.mp4")
        cola.encolar(primero)
        cola.encolar(segundo)
        assert cola.esperar(10) is True
    finally:
        cola.detener(5)

    assert llamadas == [primero.id, segundo.id]
    assert guardia.estado(primero.id).estado == mod.LISTO
    assert guardia.estado(segundo.id).estado == mod.LISTO


def test_conectar_al_terminar_se_puede_fijar_despues_de_construir_la_cola(tmp_path):
    """El bot de Telegram solo tiene su event loop listo despues de arrancar
    su propio hilo; por eso `al_terminar` debe poderse conectar mas tarde,
    no solo en el constructor."""
    from cortador.servidor import almacen as mod

    guardia = _almacen(tmp_path)
    llamadas = []

    def procesar(trabajo, almacen):
        trabajo.estado = mod.LISTO
        trabajo.mensaje = "listo"
        almacen.guardar_estado(trabajo)

    cola = _cola(guardia, procesar)
    cola.conectar_al_terminar(llamadas.append)
    try:
        trabajo = _trabajo(guardia, "a.mp4")
        cola.encolar(trabajo)
        assert cola.esperar(10) is True
    finally:
        cola.detener(5)

    assert len(llamadas) == 1
    assert llamadas[0].id == trabajo.id
