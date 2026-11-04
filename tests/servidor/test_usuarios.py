"""Pruebas del sistema minimo de usuarios (login por Telegram ID + cuota)."""

import pytest


def _usuarios(tmp_path):
    from cortador.servidor.usuarios import Usuarios

    return Usuarios(tmp_path / "usuarios")


def test_crear_usuario_y_encontrarlo_por_telegram_id(tmp_path):
    usuarios = _usuarios(tmp_path)

    creado = usuarios.crear("12345", "Ana Scout", cuota_mensual=30)

    assert creado.telegram_id == "12345"
    assert creado.nombre == "Ana Scout"
    assert creado.cuota_mensual == 30
    assert creado.usados_mes == 0
    assert creado.activo is True
    assert creado.id  # id interno opaco, para futuros metodos de login

    encontrado = usuarios.por_telegram_id("12345")
    assert encontrado is not None
    assert encontrado.id == creado.id
    assert encontrado.nombre == "Ana Scout"


def test_crear_con_telegram_id_duplicado_lanza_usuario_ya_existe(tmp_path):
    from cortador.servidor.usuarios import UsuarioYaExiste

    usuarios = _usuarios(tmp_path)
    usuarios.crear("12345", "Ana Scout")

    with pytest.raises(UsuarioYaExiste):
        usuarios.crear("12345", "Otro Nombre")


def test_por_telegram_id_desconocido_devuelve_none(tmp_path):
    usuarios = _usuarios(tmp_path)

    assert usuarios.por_telegram_id("no-existe") is None


def test_crear_con_telegram_id_con_path_traversal_lanza_error_y_no_escribe_nada(tmp_path):
    """El telegram_id real de Telegram siempre es un entero positivo. Un
    admin que teclea mal (o algo que inyecta datos) no debe poder escapar
    de la carpeta de indice con rutas como '../../lo-que-sea'."""
    from cortador.servidor.usuarios import TelegramIdInvalido

    usuarios = _usuarios(tmp_path)
    fuera_de_la_raiz = tmp_path / "fuera.json"

    with pytest.raises(TelegramIdInvalido):
        usuarios.crear("../../fuera", "Intento malicioso")

    assert not fuera_de_la_raiz.exists()
    assert not (tmp_path / "usuarios").exists()


@pytest.mark.parametrize("telegram_id", ["12.5", "12 345", "abc", "-5", "1/2", "\u00b212"])
def test_crear_con_telegram_id_no_numerico_lanza_error(tmp_path, telegram_id):
    from cortador.servidor.usuarios import TelegramIdInvalido

    usuarios = _usuarios(tmp_path)

    with pytest.raises(TelegramIdInvalido):
        usuarios.crear(telegram_id, "Nombre")


def test_crear_sin_telegram_id_es_valido_para_cuenta_solo_web(tmp_path):
    """Un scout que solo usa la PWA, sin Telegram, debe poder registrarse
    igual: telegram_id vacio ya no es un error, solo significa 'sin Telegram'."""
    usuarios = _usuarios(tmp_path)

    creado = usuarios.crear("", "Carlos Web", cuota_mensual=10)

    assert creado.telegram_id == ""
    assert creado.nombre == "Carlos Web"
    assert usuarios.por_telegram_id("") is None  # nunca se indexa un id vacio


def test_crear_siempre_asigna_un_codigo_de_acceso_unico(tmp_path):
    """El codigo de acceso es la credencial que el scout teclea en la PWA.
    Se genera siempre, con o sin telegram_id, porque cualquier cuenta debe
    poder entrar por la web."""
    usuarios = _usuarios(tmp_path)

    creado = usuarios.crear("12345", "Ana Scout")

    assert creado.codigo_acceso
    assert len(creado.codigo_acceso) >= 8
    # sin caracteres ambiguos para teclear en un telefono (0/O, 1/I/L)
    assert not set(creado.codigo_acceso) & set("0OIL1")

    encontrado = usuarios.por_codigo_acceso(creado.codigo_acceso)
    assert encontrado is not None
    assert encontrado.id == creado.id


def test_dos_cuentas_tienen_codigos_de_acceso_distintos(tmp_path):
    usuarios = _usuarios(tmp_path)

    uno = usuarios.crear("111", "Uno")
    dos = usuarios.crear("222", "Dos")

    assert uno.codigo_acceso != dos.codigo_acceso


def test_por_codigo_acceso_desconocido_devuelve_none(tmp_path):
    usuarios = _usuarios(tmp_path)

    assert usuarios.por_codigo_acceso("NOEXISTE") is None


def test_usuario_inactivo_no_puede_subir_con_mensaje_claro(tmp_path):
    usuarios = _usuarios(tmp_path)
    usuario = usuarios.crear("12345", "Ana Scout")
    usuarios.desactivar(usuario)
    usuario = usuarios.por_telegram_id("12345")

    puede, motivo = usuarios.puede_subir(usuario)

    assert puede is False
    assert motivo
    assert "activa" in motivo.lower() or "desactiv" in motivo.lower()


def test_usuario_activo_con_cuota_agotada_no_puede_subir(tmp_path):
    usuarios = _usuarios(tmp_path)
    usuario = usuarios.crear("12345", "Ana Scout", cuota_mensual=1)
    usuarios.registrar_uso(usuario)
    usuario = usuarios.por_telegram_id("12345")

    puede, motivo = usuarios.puede_subir(usuario)

    assert puede is False
    assert "cuota" in motivo.lower()
    assert "agot" in motivo.lower() or "limite" in motivo.lower() or "límite" in motivo.lower()
    # sin tecnicismos: nada de nombres de variables ni jerga de programador
    assert "usados_mes" not in motivo
    assert "cuota_mensual" not in motivo


def test_usuario_activo_con_cuota_disponible_puede_subir(tmp_path):
    usuarios = _usuarios(tmp_path)
    usuario = usuarios.crear("12345", "Ana Scout", cuota_mensual=20)

    puede, motivo = usuarios.puede_subir(usuario)

    assert puede is True
    assert motivo == ""


def test_cambio_de_mes_calendario_resetea_la_cuota_automaticamente(tmp_path, monkeypatch):
    from cortador.servidor import usuarios as mod

    usuarios = _usuarios(tmp_path)
    usuario = usuarios.crear("12345", "Ana Scout", cuota_mensual=1)
    usuarios.registrar_uso(usuario)
    usuario = usuarios.por_telegram_id("12345")
    # agotada en el mes actual
    puede, _ = usuarios.puede_subir(usuario)
    assert puede is False

    # simulamos que ya es el mes que viene
    siguiente_mes = _mes_siguiente(usuario.mes_actual)
    monkeypatch.setattr(mod, "_mes_actual", lambda: siguiente_mes)

    usuario = usuarios.por_telegram_id("12345")
    puede, motivo = usuarios.puede_subir(usuario)

    assert puede is True
    assert motivo == ""
    # el reseteo quedo persistido, no solo en memoria
    recargado = usuarios.por_telegram_id("12345")
    assert recargado.usados_mes == 0
    assert recargado.mes_actual == siguiente_mes


def _mes_siguiente(mes_actual: str) -> str:
    anio, mes = (int(parte) for parte in mes_actual.split("-"))
    if mes == 12:
        return f"{anio + 1}-01"
    return f"{anio}-{mes + 1:02d}"


def test_registrar_uso_incrementa_y_persiste_en_disco(tmp_path):
    from cortador.servidor.usuarios import Usuarios

    usuarios = _usuarios(tmp_path)
    usuario = usuarios.crear("12345", "Ana Scout", cuota_mensual=20)

    usuarios.registrar_uso(usuario)
    usuarios.registrar_uso(usuario)

    # segunda instancia distinta apuntando a la misma raiz: debe leer lo mismo
    otra_instancia = Usuarios(tmp_path / "usuarios")
    releido = otra_instancia.por_telegram_id("12345")
    assert releido.usados_mes == 2


def test_activar_reactiva_un_usuario_desactivado(tmp_path):
    usuarios = _usuarios(tmp_path)
    usuario = usuarios.crear("12345", "Ana Scout")
    usuarios.desactivar(usuario)
    usuario = usuarios.por_telegram_id("12345")
    assert usuario.activo is False

    usuarios.activar(usuario)
    usuario = usuarios.por_telegram_id("12345")
    assert usuario.activo is True


def test_listar_devuelve_todos_los_usuarios(tmp_path):
    usuarios = _usuarios(tmp_path)
    usuarios.crear("111", "Uno")
    usuarios.crear("222", "Dos")

    listado = usuarios.listar()

    assert len(listado) == 2
    nombres = sorted(u.nombre for u in listado)
    assert nombres == ["Dos", "Uno"]
