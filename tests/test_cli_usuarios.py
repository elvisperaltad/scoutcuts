"""Pruebas del subcomando `cortador usuarios`: administracion sin FastAPI.

Este subcomando solo depende de `cortador.servidor.usuarios` (nunca de
fastapi/uvicorn/httpx): un administrador debe poder registrar scouts aunque
el extra `[servidor]` no este instalado en su maquina.
"""

from cortador import cli


def test_usuarios_crear_registra_una_cuenta_nueva(tmp_path, capsys):
    raiz = tmp_path / "usuarios"

    codigo = cli.main([
        "usuarios", "crear", "--raiz", str(raiz),
        "--telegram-id", "12345", "--nombre", "Ana Scout", "--cuota", "30",
    ])

    assert codigo == 0
    salida = capsys.readouterr().out
    assert "Ana Scout" in salida
    assert "12345" in salida
    assert "Codigo de acceso" in salida

    from cortador.servidor.usuarios import Usuarios

    usuario = Usuarios(raiz).por_telegram_id("12345")
    assert usuario is not None
    assert usuario.cuota_mensual == 30


def test_usuarios_crear_sin_telegram_id_registra_cuenta_solo_web(tmp_path, capsys):
    """El admin registra un scout que solo usara la PWA, sin bot de Telegram:
    --telegram-id es opcional y el codigo de acceso impreso es la unica
    credencial que necesita entregarle."""
    raiz = tmp_path / "usuarios"

    codigo = cli.main([
        "usuarios", "crear", "--raiz", str(raiz), "--nombre", "Carlos Web",
    ])

    assert codigo == 0
    salida = capsys.readouterr().out
    assert "Carlos Web" in salida
    assert "Codigo de acceso" in salida
    assert "telegram_id=" not in salida

    from cortador.servidor.usuarios import Usuarios

    cuentas = Usuarios(raiz).listar()
    assert len(cuentas) == 1
    assert cuentas[0].telegram_id == ""
    assert cuentas[0].codigo_acceso


def test_usuarios_crear_duplicado_informa_el_error_sin_tumbar_con_traza(tmp_path, capsys):
    raiz = tmp_path / "usuarios"
    cli.main(["usuarios", "crear", "--raiz", str(raiz),
             "--telegram-id", "12345", "--nombre", "Ana"])

    codigo = cli.main(["usuarios", "crear", "--raiz", str(raiz),
                       "--telegram-id", "12345", "--nombre", "Otro"])

    assert codigo == 1
    error = capsys.readouterr().err
    assert "ya existe" in error.lower() or "12345" in error


def test_usuarios_crear_con_telegram_id_invalido_informa_el_error_sin_tumbar_con_traza(
        tmp_path, capsys):
    """Un admin que teclea mal --telegram-id no debe ver un traceback de
    Python ni, peor, dejar la CLI a medio escribir algo fuera de --raiz."""
    raiz = tmp_path / "usuarios"

    codigo = cli.main(["usuarios", "crear", "--raiz", str(raiz),
                       "--telegram-id", "no-es-un-id", "--nombre", "Ana"])

    assert codigo == 1
    error = capsys.readouterr().err
    assert "no-es-un-id" in error
    assert not raiz.exists()


def test_usuarios_listar_muestra_todas_las_cuentas(tmp_path, capsys):
    raiz = tmp_path / "usuarios"
    cli.main(["usuarios", "crear", "--raiz", str(raiz),
             "--telegram-id", "111", "--nombre", "Uno"])
    cli.main(["usuarios", "crear", "--raiz", str(raiz),
             "--telegram-id", "222", "--nombre", "Dos"])
    capsys.readouterr()

    codigo = cli.main(["usuarios", "listar", "--raiz", str(raiz)])

    assert codigo == 0
    salida = capsys.readouterr().out
    assert "Uno" in salida and "111" in salida
    assert "Dos" in salida and "222" in salida


def test_usuarios_desactivar_y_activar_cambian_el_estado(tmp_path, capsys):
    raiz = tmp_path / "usuarios"
    cli.main(["usuarios", "crear", "--raiz", str(raiz),
             "--telegram-id", "111", "--nombre", "Uno"])
    capsys.readouterr()

    from cortador.servidor.usuarios import Usuarios

    usuario_id = Usuarios(raiz).por_telegram_id("111").id

    codigo = cli.main(["usuarios", "desactivar", "--raiz", str(raiz), "--id", usuario_id])
    assert codigo == 0
    assert Usuarios(raiz).por_telegram_id("111").activo is False

    codigo = cli.main(["usuarios", "activar", "--raiz", str(raiz), "--id", usuario_id])
    assert codigo == 0
    assert Usuarios(raiz).por_telegram_id("111").activo is True


def test_usuarios_raiz_se_puede_tomar_de_la_variable_de_entorno(tmp_path, monkeypatch, capsys):
    raiz = tmp_path / "usuarios_env"
    monkeypatch.setenv("SCOUTCUTS_USUARIOS", str(raiz))

    codigo = cli.main(["usuarios", "crear",
                       "--telegram-id", "999", "--nombre", "Desde Entorno"])

    assert codigo == 0
    from cortador.servidor.usuarios import Usuarios

    assert Usuarios(raiz).por_telegram_id("999") is not None
