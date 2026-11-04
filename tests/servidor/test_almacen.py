import io
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def _almacen(tmp_path, **opciones):
    from cortador.servidor.almacen import Almacen

    return Almacen(tmp_path / "datos", **opciones)


def _con_entrada(almacen, nombre="turno.mov", contenido=b"video"):
    trabajo = almacen.crear(nombre, len(contenido))
    almacen.guardar_entrada(trabajo, io.BytesIO(contenido))
    return trabajo


def test_crear_usa_identificador_opaco_y_no_el_nombre_del_usuario(tmp_path):
    from cortador.servidor import almacen as mod

    guardia = _almacen(tmp_path)
    trabajo = guardia.crear("Luis Abreu - turno 3.MOV", 2048)

    assert trabajo.estado == mod.RECIBIDO
    assert trabajo.id.isalnum() and len(trabajo.id) >= 16
    assert "luis" not in trabajo.id.lower() and "abreu" not in trabajo.id.lower()
    assert guardia.carpeta(trabajo.id).is_dir()
    assert guardia.carpeta(trabajo.id).name == trabajo.id
    # El nombre original se recuerda sólo para mostrárselo a quien subió el video.
    assert trabajo.nombre == "Luis Abreu - turno 3.MOV"
    assert guardia.ruta_entrada(trabajo).name == "entrada.mov"


def test_crear_descarta_la_ruta_que_venga_en_el_nombre(tmp_path):
    guardia = _almacen(tmp_path)
    trabajo = guardia.crear("C:/Users/Ana/Videos/turno.mp4", 10)

    assert trabajo.nombre == "turno.mp4"
    assert "Ana" not in guardia.carpeta(trabajo.id).name
    assert guardia.ruta_entrada(trabajo).parent == guardia.carpeta(trabajo.id)


def test_extensiones_permitidas_son_las_mismas_del_escritorio():
    from cortador import app
    from cortador.servidor import almacen

    assert set(almacen.EXTENSIONES_PERMITIDAS) == app._EXTENSIONES_VIDEO


def test_crear_rechaza_extension_ajena_con_mensaje_para_el_scout(tmp_path):
    from cortador.servidor import almacen as mod

    guardia = _almacen(tmp_path)
    with pytest.raises(mod.ArchivoNoAceptado) as fallo:
        guardia.crear("notas.pdf", 10)

    texto = str(fallo.value).lower()
    assert "video" in texto
    assert "mp4" in texto and "mov" in texto
    assert not guardia.trabajos.exists() or not list(guardia.trabajos.iterdir())


def test_crear_rechaza_lo_que_supera_el_limite_configurado(tmp_path):
    from cortador.servidor import almacen as mod

    guardia = _almacen(tmp_path, limite_bytes=1024)
    with pytest.raises(mod.ArchivoNoAceptado) as fallo:
        guardia.crear("turno.mp4", 2048)

    assert "grande" in str(fallo.value).lower()
    assert not guardia.trabajos.exists() or not list(guardia.trabajos.iterdir())


def test_limite_por_defecto_es_holgado_para_un_video_de_telefono(tmp_path):
    guardia = _almacen(tmp_path)

    assert guardia.limite_bytes >= 200 * 1024 * 1024
    assert guardia.crear("turno.mp4", 150 * 1024 * 1024).id


def test_guardar_entrada_escribe_el_video_y_anota_su_tamano(tmp_path):
    guardia = _almacen(tmp_path)
    trabajo = guardia.crear("turno.mp4", 0)

    escritos = guardia.guardar_entrada(trabajo, io.BytesIO(b"x" * 5000))

    assert escritos == 5000
    assert trabajo.tamano_bytes == 5000
    assert guardia.ruta_entrada(trabajo).read_bytes() == b"x" * 5000
    assert not list(guardia.carpeta(trabajo.id).glob("*.tmp"))


def test_guardar_entrada_corta_lo_demasiado_grande_sin_dejar_restos(tmp_path):
    from cortador.servidor import almacen as mod

    guardia = _almacen(tmp_path, limite_bytes=1024)
    trabajo = guardia.crear("turno.mp4", 0)

    with pytest.raises(mod.ArchivoNoAceptado) as fallo:
        guardia.guardar_entrada(trabajo, io.BytesIO(b"x" * 4096))

    assert "grande" in str(fallo.value).lower()
    assert not guardia.ruta_entrada(trabajo).exists()
    assert not list(guardia.carpeta(trabajo.id).glob("*.tmp"))


def test_guardar_estado_es_atomico_y_se_vuelve_a_leer(tmp_path, monkeypatch):
    from cortador.servidor import almacen as mod

    guardia = _almacen(tmp_path)
    trabajo = guardia.crear("turno.mov", 10)
    reemplazos = []
    real = os.replace
    monkeypatch.setattr(
        mod.os, "replace",
        lambda a, b: (reemplazos.append(Path(a)), real(a, b))[1],
    )

    trabajo.estado = mod.LISTO
    trabajo.mensaje = "Tu montaje está listo."
    trabajo.candidatos = 3
    guardia.guardar_estado(trabajo)

    assert reemplazos and reemplazos[-1].suffix == ".tmp"
    assert not reemplazos[-1].exists()
    recuperado = guardia.estado(trabajo.id)
    assert recuperado.id == trabajo.id
    assert recuperado.estado == mod.LISTO
    assert recuperado.mensaje == "Tu montaje está listo."
    assert recuperado.candidatos == 3
    assert recuperado.actualizado


def test_estado_no_acepta_identificadores_inventados_ni_rutas(tmp_path):
    from cortador.servidor import almacen as mod

    guardia = _almacen(tmp_path)
    guardia.crear("turno.mp4", 10)

    for identificador in ("", "no-existe", "../../secreto", "..", "a" * 64):
        with pytest.raises(mod.TrabajoDesconocido):
            guardia.estado(identificador)


def test_estados_cubren_todo_el_recorrido_del_trabajo():
    from cortador.servidor import almacen as mod

    assert set(mod.ESTADOS) == {
        mod.RECIBIDO, mod.EN_COLA, mod.PROCESANDO,
        mod.LISTO, mod.PENDIENTE_REVISION, mod.ERROR,
    }


def test_marcar_descargado_borra_siempre_el_video_de_entrada(tmp_path):
    from cortador.servidor import almacen as mod

    guardia = _almacen(tmp_path)
    trabajo = _con_entrada(guardia)
    guardia.ruta_resultado(trabajo).write_bytes(b"montaje")
    trabajo.estado = mod.LISTO
    guardia.guardar_estado(trabajo)

    guardia.marcar_descargado(trabajo)

    assert not guardia.ruta_entrada(trabajo).exists()
    assert guardia.ruta_resultado(trabajo).exists()
    assert guardia.estado(trabajo.id).descargado is True


def _envejecer(guardia, trabajo, horas):
    trabajo.creado = (datetime.now(timezone.utc) - timedelta(hours=horas)).isoformat(
        timespec="seconds")
    guardia.guardar_estado(trabajo)


def test_purgar_borra_lo_vencido_y_la_entrada_ya_entregada(tmp_path):
    from cortador.servidor import almacen as mod

    guardia = _almacen(tmp_path)
    vencido = _con_entrada(guardia, "vencido.mp4")
    _envejecer(guardia, vencido, 48)

    entregado = _con_entrada(guardia, "entregado.mp4")
    guardia.ruta_resultado(entregado).write_bytes(b"montaje")
    entregado.estado = mod.LISTO
    entregado.descargado = True
    guardia.guardar_estado(entregado)

    reciente = _con_entrada(guardia, "reciente.mp4")

    borrados = guardia.purgar(24)

    assert list(borrados) == [vencido.id]
    assert not guardia.carpeta(vencido.id).exists()
    assert not guardia.ruta_entrada(entregado).exists()
    assert guardia.ruta_resultado(entregado).exists()
    assert guardia.ruta_entrada(reciente).exists()


def test_purgar_limpia_carpetas_sin_estado_legible_cuando_vencen(tmp_path):
    guardia = _almacen(tmp_path)
    trabajo = _con_entrada(guardia, "roto.mp4")
    ruta_estado = guardia.carpeta(trabajo.id) / "estado.json"
    ruta_estado.write_text("{ esto no es json", encoding="utf-8")
    antiguo = (datetime.now(timezone.utc) - timedelta(hours=72)).timestamp()
    os.utime(ruta_estado, (antiguo, antiguo))
    os.utime(guardia.carpeta(trabajo.id), (antiguo, antiguo))

    assert list(guardia.purgar(24)) == [trabajo.id]
    assert not guardia.carpeta(trabajo.id).exists()


def test_purgar_sin_nada_que_borrar_no_falla(tmp_path):
    guardia = _almacen(tmp_path)

    assert list(guardia.purgar(24)) == []


def test_depurar_texto_quita_rutas_y_nombres_de_usuario():
    from cortador.servidor.almacen import depurar_texto

    limpio = depurar_texto("falló C:/Users/Ana/Videos/turno.mov al abrir")

    assert "C:/Users" not in limpio
    assert "Ana" not in limpio
    assert "turno.mov" in limpio


def test_crear_sin_propietario_deja_el_campo_vacio_por_compatibilidad(tmp_path):
    guardia = _almacen(tmp_path)

    trabajo = guardia.crear("turno.mp4", 10)

    assert trabajo.propietario == ""


def test_crear_con_propietario_lo_guarda_y_persiste(tmp_path):
    guardia = _almacen(tmp_path)

    trabajo = guardia.crear("turno.mp4", 10, propietario="123456")

    assert trabajo.propietario == "123456"
    releido = guardia.estado(trabajo.id)
    assert releido.propietario == "123456"


def test_trabajos_de_devuelve_solo_los_de_ese_propietario(tmp_path):
    guardia = _almacen(tmp_path)
    de_ana = guardia.crear("a.mp4", 10, propietario="111")
    _ = guardia.crear("b.mp4", 10, propietario="222")
    otro_de_ana = guardia.crear("c.mp4", 10, propietario="111")
    sin_dueno = guardia.crear("d.mp4", 10)

    resultado = guardia.trabajos_de("111")

    ids = {t.id for t in resultado}
    assert ids == {de_ana.id, otro_de_ana.id}
    assert sin_dueno.id not in ids
