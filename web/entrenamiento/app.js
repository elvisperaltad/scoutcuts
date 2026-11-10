/* ScoutCuts — zona de entrenamiento publica (scoutcuts.com/entrenamiento).
 *
 * PAGINA ABIERTA A PROPOSITO: se entra solo con el enlace. Aqui no hay
 * login, token ni codigo, y este archivo NUNCA debe guardar credenciales
 * ni mandar una cabecera Authorization -- la zona es un sandbox aislado en
 * el servidor (otra carpeta en disco, otro dataset por disciplina, el video
 * se borra al entrenar; ver cortador.servidor.entrenamiento). La API de
 * produccion/PWA sigue pidiendo credencial y no se toca desde aqui.
 *
 * Lo unico que se recuerda entre visitas es la disciplina elegida: una
 * preferencia de interfaz, no un dato de nadie.
 *
 * Atiende las disciplinas entrenables que anuncie el servidor
 * (/v1/entrenamiento/disciplinas): categorias, rotulos, limite de tamano y
 * extensiones aceptadas vienen de ahi, nunca hardcodeados aqui -- asi una
 * disciplina nueva no requiere tocar este archivo.
 *
 * Vanilla JS sin dependencias, igual que el resto del sitio.
 */
(function () {
  "use strict";

  var API_BASE = "";
  var CLAVE_DISCIPLINA = "scoutcuts_disciplina_entrenamiento";
  var EXTENSIONES_POR_DEFECTO = [".mp4", ".mov", ".m4v", ".avi"];

  var selectorDisciplina = document.getElementById("selector-disciplina");
  var errorDisciplinas = document.getElementById("error-disciplinas");
  var filaReintentar = document.getElementById("fila-reintentar-disciplinas");
  var btnReintentarDisciplinas = document.getElementById("btn-reintentar-disciplinas");
  var resumenModelo = document.getElementById("resumen-modelo");

  var zonaSubida = document.getElementById("zona-subida");
  var textoZonaSubida = document.getElementById("texto-zona-subida");
  var ayudaSubida = document.getElementById("ayuda-subida");
  var inputArchivo = document.getElementById("input-archivo");
  var barraSubida = document.getElementById("barra-subida");
  var rellenoSubida = document.getElementById("relleno-subida");
  var errorSubida = document.getElementById("error-subida");
  var avisoSubida = document.getElementById("aviso-subida");

  var tarjetaMarcado = document.getElementById("tarjeta-marcado");
  var videoPractica = document.getElementById("video-practica");
  var btnReproducir = document.getElementById("btn-reproducir");
  var btnRetroceder = document.getElementById("btn-retroceder");
  var marcaInicio = document.getElementById("marca-inicio");
  var marcaFinal = document.getElementById("marca-final");
  var valorInicio = document.getElementById("valor-inicio");
  var valorFinal = document.getElementById("valor-final");
  var btnMarcarInicio = document.getElementById("btn-marcar-inicio");
  var btnMarcarFinal = document.getElementById("btn-marcar-final");
  var contenedorCategorias = document.getElementById("categorias");
  var errorRepeticion = document.getElementById("error-repeticion");
  var btnAgregarRepeticion = document.getElementById("btn-agregar-repeticion");

  var tarjetaLista = document.getElementById("tarjeta-lista");
  var listaRepeticiones = document.getElementById("lista-repeticiones");
  var repeticionesVacio = document.getElementById("repeticiones-vacio");
  var btnEntrenar = document.getElementById("btn-entrenar");

  var tarjetaFeedback = document.getElementById("tarjeta-feedback");
  var listaFeedback = document.getElementById("lista-feedback");
  var btnOtroVideo = document.getElementById("btn-otro-video");

  var disciplinas = [];           // [{id, nombre, categorias: [{id, nombre}]}]
  var disciplinaActual = null;    // id de la disciplina elegida
  var nombresCategoria = {};      // id -> nombre legible, de la disciplina actual
  var extensiones = EXTENSIONES_POR_DEFECTO;
  var limiteBytes = 0;            // 0 = el servidor no lo dijo, no lo inventamos
  var textoFormatos = "";         // "Formatos aceptados: ... Tamaño máximo: ..."

  var videoActualId = null;
  var videoActualNombre = null;
  var urlObjetoActual = null;     // object URL del video en el reproductor
  var subidaEnCurso = false;
  var entrenandoAhora = false;
  var inicioMarcado = null;
  var finalMarcado = null;
  var categoriaElegida = null;
  var repeticiones = [];

  // --- Preferencia de interfaz (nunca credenciales) ---
  function disciplinaGuardada() {
    try { return window.localStorage.getItem(CLAVE_DISCIPLINA) || ""; }
    catch (err) { return ""; }
  }
  function guardarDisciplina(id) {
    try { window.localStorage.setItem(CLAVE_DISCIPLINA, id); }
    catch (err) { /* modo privado o almacenamiento lleno: no es grave */ }
  }

  // --- Helpers de red ---
  //
  // Sin cabecera Authorization en ninguna peticion: la zona es publica.
  function peticion(ruta, opciones) {
    return fetch(API_BASE + ruta, opciones || {}).then(function (respuesta) {
      return respuesta.json().catch(function () { return {}; }).then(function (cuerpo) {
        if (!respuesta.ok) {
          var err = new Error(cuerpo.mensaje || cuerpo.detail || "Ocurrió un problema.");
          err.estado = respuesta.status;
          throw err;
        }
        return cuerpo;
      });
    });
  }

  function formatoSegundos(valor) {
    if (valor === null || valor === undefined) return "sin marcar";
    return valor.toFixed(1) + "s";
  }

  function formatoTamano(bytes) {
    if (!bytes) return "";
    return Math.round(bytes / (1024 * 1024)) + " MB";
  }

  function disciplina(id) {
    for (var i = 0; i < disciplinas.length; i++) {
      if (disciplinas[i].id === id) return disciplinas[i];
    }
    return null;
  }

  function mostrar(elemento, visible) {
    elemento.hidden = !visible;
  }

  // --- Carga inicial: que disciplinas existen, con que categorias ---
  function cargarDisciplinas() {
    errorDisciplinas.textContent = "";
    mostrar(filaReintentar, false);
    selectorDisciplina.disabled = true;
    return peticion("/v1/entrenamiento/disciplinas").then(function (respuesta) {
      disciplinas = (respuesta && respuesta.disciplinas) || [];
      if (Array.isArray(respuesta && respuesta.extensiones) && respuesta.extensiones.length) {
        extensiones = respuesta.extensiones;
      }
      limiteBytes = Number(respuesta && respuesta.limite_bytes) || 0;
      describirLimites();
      if (!disciplinas.length) {
        // Lista vacia: no es un crash, pero no hay nada que entrenar.
        fallaDisciplinas("Por ahora no hay ninguna disciplina disponible para entrenar.");
        return;
      }
      selectorDisciplina.innerHTML = "";
      disciplinas.forEach(function (d) {
        var opcion = document.createElement("option");
        opcion.value = d.id;
        opcion.textContent = d.nombre;
        selectorDisciplina.appendChild(opcion);
      });
      selectorDisciplina.disabled = false;
      var preferida = disciplinaGuardada();
      aplicarDisciplina(disciplina(preferida) ? preferida : disciplinas[0].id);
    }).catch(function () {
      fallaDisciplinas("No se pudo cargar la lista de disciplinas. Revisa tu conexión.");
    });
  }

  function fallaDisciplinas(mensaje) {
    disciplinas = [];
    disciplinaActual = null;
    selectorDisciplina.innerHTML = "";
    selectorDisciplina.disabled = true;
    errorDisciplinas.textContent = mensaje;
    mostrar(filaReintentar, true);
    resumenModelo.textContent = "Sin disciplina elegida todavía.";
    // Sin disciplina no se puede subir nada: no dejamos un paso 2 que
    // falle con un error incomprensible al tocarlo.
    inputArchivo.disabled = true;
    textoZonaSubida.textContent = "Primero elige una disciplina (paso 1)";
  }

  function describirLimites() {
    var lista = extensiones.map(function (e) {
      return String(e).replace(".", "").toUpperCase();
    }).join(", ");
    textoFormatos = "Formatos aceptados: " + lista + ".";
    if (limiteBytes) textoFormatos += " Tamaño máximo: " + formatoTamano(limiteBytes) + ".";
    ayudaSubida.textContent = textoFormatos +
      " El video se borra del servidor en cuanto entrenas con él.";
    // El `accept` sale de lo que el servidor dice que acepta, no de una
    // lista escrita a mano aqui que se pueda quedar desfasada. Se le suma
    // `video/*` a proposito: varios selectores de Android no entienden una
    // lista de extensiones y abren la galeria VACIA, que fue justo uno de
    // los problemas que reporto el QA. Si el archivo elegido no tiene una
    // extension aceptada, la comprobacion de `subir()` lo dice al instante.
    inputArchivo.setAttribute("accept", ["video/*"].concat(extensiones).join(","));
  }

  function aplicarDisciplina(id) {
    disciplinaActual = id;
    guardarDisciplina(id);
    selectorDisciplina.value = id;
    inputArchivo.disabled = false;
    var actual = disciplina(id);
    nombresCategoria = {};
    contenedorCategorias.innerHTML = "";
    (actual ? actual.categorias : []).forEach(function (c) {
      nombresCategoria[c.id] = c.nombre;
      var boton = document.createElement("button");
      boton.type = "button";
      boton.setAttribute("data-categoria", c.id);
      boton.setAttribute("aria-pressed", "false");
      boton.textContent = c.nombre;
      boton.addEventListener("click", function () { elegirCategoria(c.id); });
      contenedorCategorias.appendChild(boton);
    });
    cargarEstadoModelo();
    descartarVideo("Toca aquí para elegir un video");
  }

  // Cambiar de disciplina con un video ya subido dejaria las categorias
  // mezcladas (las del video son las de la disciplina con la que se subio).
  // Se avisa y se limpia el marcado, en vez de dejar una pantalla con
  // botones de otra disciplina.
  selectorDisciplina.addEventListener("change", function () {
    var elegida = selectorDisciplina.value;
    if (elegida === disciplinaActual) return;
    if (subidaEnCurso || entrenandoAhora) {
      selectorDisciplina.value = disciplinaActual;
      errorDisciplinas.textContent =
        "Espera a que termine lo que está en curso antes de cambiar de disciplina.";
      return;
    }
    if (videoActualId) {
      var seguir = window.confirm(
        "Cambiar de disciplina descarta el video que subiste y las repeticiones " +
        "que marcaste. ¿Seguir?");
      if (!seguir) {
        selectorDisciplina.value = disciplinaActual;
        return;
      }
    }
    errorDisciplinas.textContent = "";
    aplicarDisciplina(elegida);
  });

  btnReintentarDisciplinas.addEventListener("click", cargarDisciplinas);

  function cargarEstadoModelo() {
    if (!disciplinaActual) return;
    resumenModelo.textContent = "Cargando...";
    peticion("/v1/entrenamiento/modelo/" + encodeURIComponent(disciplinaActual))
      .then(function (estado) {
        var html = "Ha visto <b>" + estado.total_ejemplos + "</b> repetición(es) en total.<br>";
        html += (estado.categorias || []).map(function (c) {
          var n = (estado.ejemplos_por_categoria || {})[c] || 0;
          var clase = n > 0 ? "pastilla-categoria cubierta" : "pastilla-categoria";
          return '<span class="' + clase + '">' + (nombresCategoria[c] || c) + ": " + n + "</span>";
        }).join(" ");
        html += "<br>" + (estado.modelo_calibrado
          ? "El modelo ya puede dar una opinión."
          : "Todavía le faltan ejemplos para poder opinar con confianza.");
        resumenModelo.innerHTML = html;
      }).catch(function () {
        resumenModelo.textContent = "No se pudo consultar el estado del modelo.";
      });
  }

  // --- Ciclo de vida del video en el reproductor ---
  //
  // Cada object URL se revoca en cuanto deja de usarse: sin esto, subir
  // varios videos seguidos deja el archivo entero retenido en memoria por
  // cada uno (en un celular eso termina en una pestana muerta).
  function soltarUrlObjeto() {
    if (!urlObjetoActual) return;
    try { URL.revokeObjectURL(urlObjetoActual); } catch (err) { /* ya revocado */ }
    urlObjetoActual = null;
  }

  function mostrarVideoLocal(archivo) {
    soltarUrlObjeto();
    urlObjetoActual = URL.createObjectURL(archivo);
    videoPractica.src = urlObjetoActual;
  }

  function descartarVideo(textoZona) {
    videoActualId = null;
    videoActualNombre = null;
    videoPractica.pause();
    videoPractica.removeAttribute("src");
    videoPractica.load();
    soltarUrlObjeto();
    reiniciarMarcado();
    mostrar(tarjetaMarcado, false);
    mostrar(tarjetaLista, false);
    mostrar(tarjetaFeedback, false);
    errorSubida.textContent = "";
    avisoSubida.textContent = "";
    mostrar(barraSubida, false);
    textoZonaSubida.textContent = textoZona;
  }

  window.addEventListener("pagehide", soltarUrlObjeto);

  function reiniciarMarcado() {
    inicioMarcado = null;
    finalMarcado = null;
    repeticiones = [];
    limpiarMarcasYCategoria();
    actualizarListaRepeticiones();
  }

  function limpiarMarcasYCategoria() {
    inicioMarcado = null;
    finalMarcado = null;
    categoriaElegida = null;
    valorInicio.textContent = "sin marcar";
    valorFinal.textContent = "sin marcar";
    marcaInicio.classList.remove("puesta");
    marcaFinal.classList.remove("puesta");
    Array.prototype.forEach.call(contenedorCategorias.children, function (b) {
      b.classList.remove("elegida");
      b.setAttribute("aria-pressed", "false");
    });
    actualizarBotonAgregar();
  }

  function elegirCategoria(id) {
    categoriaElegida = id;
    Array.prototype.forEach.call(contenedorCategorias.children, function (b) {
      var esta = b.getAttribute("data-categoria") === id;
      b.classList.toggle("elegida", esta);
      b.setAttribute("aria-pressed", esta ? "true" : "false");
    });
    actualizarBotonAgregar();
  }

  function actualizarBotonAgregar() {
    btnAgregarRepeticion.disabled =
      !(inicioMarcado !== null && finalMarcado !== null && categoriaElegida);
  }

  function actualizarListaRepeticiones() {
    listaRepeticiones.innerHTML = "";
    mostrar(repeticionesVacio, repeticiones.length === 0);
    btnEntrenar.disabled = repeticiones.length === 0 || entrenandoAhora;
    repeticiones.forEach(function (r, indice) {
      var li = document.createElement("li");
      var texto = document.createElement("span");
      texto.textContent = (nombresCategoria[r.categoria] || r.categoria) + " · " +
        formatoSegundos(r.inicio) + " → " + formatoSegundos(r.tiro);
      var quitar = document.createElement("button");
      quitar.type = "button";
      quitar.className = "quitar";
      quitar.textContent = "Quitar";
      quitar.addEventListener("click", function () {
        repeticiones.splice(indice, 1);
        actualizarListaRepeticiones();
      });
      li.appendChild(texto);
      li.appendChild(quitar);
      listaRepeticiones.appendChild(li);
    });
  }

  // --- Subida de video ---
  zonaSubida.addEventListener("click", function () {
    if (subidaEnCurso || inputArchivo.disabled) return;
    inputArchivo.click();
  });
  zonaSubida.addEventListener("keydown", function (evento) {
    if (evento.key !== "Enter" && evento.key !== " ") return;
    evento.preventDefault();
    if (subidaEnCurso || inputArchivo.disabled) return;
    inputArchivo.click();
  });

  ["dragover", "dragenter"].forEach(function (nombre) {
    zonaSubida.addEventListener(nombre, function (evento) {
      evento.preventDefault();
      zonaSubida.classList.add("sobre-archivo");
    });
  });
  ["dragleave", "drop"].forEach(function (nombre) {
    zonaSubida.addEventListener(nombre, function () {
      zonaSubida.classList.remove("sobre-archivo");
    });
  });
  zonaSubida.addEventListener("drop", function (evento) {
    evento.preventDefault();
    if (subidaEnCurso || inputArchivo.disabled) return;
    var archivos = evento.dataTransfer && evento.dataTransfer.files;
    if (archivos && archivos.length) subir(archivos[0]);
  });

  inputArchivo.addEventListener("change", function () {
    var archivo = inputArchivo.files[0];
    inputArchivo.value = "";  // asi elegir el MISMO archivo otra vez vuelve a disparar
    if (archivo) subir(archivo);
  });

  function extensionDe(nombre) {
    var punto = String(nombre || "").lastIndexOf(".");
    return punto < 0 ? "" : String(nombre).slice(punto).toLowerCase();
  }

  function subir(archivo) {
    if (subidaEnCurso) return;            // doble subida: ni se intenta
    if (!disciplinaActual) {
      errorSubida.textContent = "Primero elige una disciplina en el paso 1.";
      return;
    }
    errorSubida.textContent = "";
    avisoSubida.textContent = "";

    // Dos comprobaciones locales antes de gastar la subida, con el mismo
    // criterio que el servidor (que vuelve a comprobarlas de todos modos).
    if (extensiones.indexOf(extensionDe(archivo.name)) < 0) {
      errorSubida.textContent = "Ese archivo no es un video compatible. " + textoFormatos;
      return;
    }
    if (limiteBytes && archivo.size > limiteBytes) {
      errorSubida.textContent = "Ese video pesa " + formatoTamano(archivo.size) +
        " y el máximo es " + formatoTamano(limiteBytes) + ". Recorta un trozo más corto.";
      return;
    }

    // Subir otro video descarta el anterior. Si habia repeticiones marcadas
    // sin entrenar, se pregunta antes: perder ese trabajo en silencio es
    // justo lo que mas desanima a quien esta marcando a mano.
    if (videoActualId && repeticiones.length) {
      var seguir = window.confirm(
        "Vas a reemplazar el video actual y perder las " + repeticiones.length +
        " repetición(es) que marcaste sin entrenar. ¿Seguir?");
      if (!seguir) return;
    }

    // El video anterior (si habia) se descarta ANTES de empezar: nada de
    // quedarse con dos reproductores ni con dos object URLs vivos.
    descartarVideo("Subiendo " + archivo.name + "...");
    subidaEnCurso = true;
    zonaSubida.classList.add("ocupada");
    selectorDisciplina.disabled = true;
    mostrar(barraSubida, true);
    rellenoSubida.style.width = "0%";

    // XHR y no fetch: es la unica forma de tener progreso real de subida.
    var datos = new FormData();
    datos.append("archivo", archivo);
    var xhr = new XMLHttpRequest();
    xhr.open("POST", API_BASE + "/v1/entrenamiento/" +
      encodeURIComponent(disciplinaActual) + "/videos");

    xhr.upload.addEventListener("progress", function (evento) {
      if (!evento.lengthComputable) return;
      var porcentaje = Math.round((evento.loaded / evento.total) * 100);
      rellenoSubida.style.width = porcentaje + "%";
      textoZonaSubida.textContent = "Subiendo " + archivo.name + "... " + porcentaje + "%";
    });

    xhr.addEventListener("load", function () {
      var cuerpo = {};
      try { cuerpo = JSON.parse(xhr.responseText || "{}"); } catch (err) { cuerpo = {}; }
      if (xhr.status === 201) {
        terminarSubida();
        videoActualId = cuerpo.id;
        videoActualNombre = cuerpo.nombre;
        textoZonaSubida.textContent = "Toca aquí para elegir otro video";
        avisoSubida.textContent = "Video subido. Ahora marca las repeticiones (paso 3).";
        mostrarVideoLocal(archivo);
        reiniciarMarcado();
        mostrar(tarjetaMarcado, true);
        mostrar(tarjetaLista, true);
        tarjetaMarcado.scrollIntoView({ behavior: "smooth", block: "start" });
      } else {
        fallaSubida(cuerpo.mensaje || cuerpo.detail ||
          "No se pudo subir el video (error " + xhr.status + "). Vuelve a intentarlo.");
      }
    });
    xhr.addEventListener("error", function () {
      fallaSubida("Se cortó la conexión mientras subía el video. Vuelve a intentarlo.");
    });
    xhr.addEventListener("abort", function () {
      fallaSubida("La subida se canceló.");
    });
    xhr.send(datos);
  }

  function terminarSubida() {
    subidaEnCurso = false;
    zonaSubida.classList.remove("ocupada");
    selectorDisciplina.disabled = disciplinas.length === 0;
    mostrar(barraSubida, false);
  }

  function fallaSubida(mensaje) {
    terminarSubida();
    textoZonaSubida.textContent = "Toca aquí para elegir un video";
    errorSubida.textContent = mensaje;
  }

  // --- Marcado de repeticiones ---
  btnReproducir.addEventListener("click", function () {
    if (videoPractica.paused) videoPractica.play();
    else videoPractica.pause();
  });
  function rotuloReproducir() {
    btnReproducir.textContent = videoPractica.paused ? "Reproducir" : "Pausar";
  }
  videoPractica.addEventListener("play", rotuloReproducir);
  videoPractica.addEventListener("pause", rotuloReproducir);
  videoPractica.addEventListener("ended", rotuloReproducir);

  btnRetroceder.addEventListener("click", function () {
    videoPractica.currentTime = Math.max(0, videoPractica.currentTime - 2);
  });

  btnMarcarInicio.addEventListener("click", function () {
    errorRepeticion.textContent = "";
    inicioMarcado = videoPractica.currentTime;
    valorInicio.textContent = formatoSegundos(inicioMarcado);
    marcaInicio.classList.add("puesta");
    actualizarBotonAgregar();
  });

  btnMarcarFinal.addEventListener("click", function () {
    errorRepeticion.textContent = "";
    finalMarcado = videoPractica.currentTime;
    valorFinal.textContent = formatoSegundos(finalMarcado);
    marcaFinal.classList.add("puesta");
    actualizarBotonAgregar();
  });

  btnAgregarRepeticion.addEventListener("click", function () {
    errorRepeticion.textContent = "";
    if (finalMarcado <= inicioMarcado) {
      errorRepeticion.textContent =
        "El final debe quedar después del inicio. Vuelve a marcarlos.";
      return;
    }
    // `tiro` es el nombre del campo en el contrato de la API (el mismo
    // manifiesto que usa el motor); en pantalla se le dice "final" porque
    // no todas las disciplinas tienen un tiro.
    repeticiones.push({
      categoria: categoriaElegida, inicio: inicioMarcado, tiro: finalMarcado,
      estado: "completa", seleccionada: true,
    });
    limpiarMarcasYCategoria();
    actualizarListaRepeticiones();
    tarjetaLista.scrollIntoView({ behavior: "smooth", block: "nearest" });
  });

  // --- Entrenar y mostrar feedback ---
  btnEntrenar.addEventListener("click", function () {
    if (entrenandoAhora || !videoActualId) return;
    entrenandoAhora = true;
    btnEntrenar.disabled = true;
    btnEntrenar.textContent = "Entrenando...";
    errorRepeticion.textContent = "";
    peticion("/v1/entrenamiento/videos/" + encodeURIComponent(videoActualId) + "/entrenar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video: videoActualNombre, repeticiones: repeticiones }),
    }).then(function (resultado) {
      mostrarFeedback(resultado);
      // El servidor ya borro el video: dejar el reproductor y la lista en
      // pantalla solo invitaria a entrenar otra vez con un id muerto.
      descartarVideo("Toca aquí para elegir otro video");
      mostrar(tarjetaFeedback, true);
      tarjetaFeedback.scrollIntoView({ behavior: "smooth", block: "start" });
      cargarEstadoModelo();
    }).catch(function (err) {
      errorRepeticion.textContent = err.message;
    }).finally(function () {
      entrenandoAhora = false;
      btnEntrenar.textContent = "Entrenar con estas repeticiones";
      actualizarListaRepeticiones();
    });
  });

  function nivelConfianza(confianza) {
    if (confianza === null || confianza === undefined) return "";
    if (confianza >= 0.6) return "con bastante seguridad";
    if (confianza >= 0.35) return "sin mucha seguridad";
    return "con muy poca seguridad, prácticamente adivinando";
  }

  function mostrarFeedback(resultado) {
    listaFeedback.innerHTML = "";
    (resultado.evaluacion || []).forEach(function (fila) {
      var div = document.createElement("div");
      var marcada = nombresCategoria[fila.categoria_marcada] || fila.categoria_marcada;
      if (fila.categoria_predicha === null) {
        div.className = "feedback-repeticion";
        div.innerHTML = '<div class="titulo">Repetición marcada: ' + marcada + "</div>" +
          '<div class="detalle">El modelo todavía no tenía suficientes ejemplos para opinar sobre esta repetición; de todos modos ya aprendió de ella.</div>';
      } else if (fila.coincide) {
        div.className = "feedback-repeticion acierto";
        div.innerHTML = '<div class="titulo">✓ El modelo coincidió: ' + marcada + "</div>" +
          '<div class="detalle">Lo reconoció ' + nivelConfianza(fila.confianza) + ".</div>";
      } else {
        var predicha = nombresCategoria[fila.categoria_predicha] || fila.categoria_predicha;
        div.className = "feedback-repeticion diferente";
        div.innerHTML = '<div class="titulo">El modelo no coincidió</div>' +
          '<div class="detalle">Tú marcaste <b>' + marcada + "</b>, pero el modelo creyó que era <b>" +
          predicha + "</b> (" + nivelConfianza(fila.confianza) + "). Ya aprendió de tu corrección.</div>";
      }
      listaFeedback.appendChild(div);
    });
    var resumen = document.createElement("div");
    resumen.className = "resumen-modelo";
    resumen.style.marginTop = "10px";
    resumen.innerHTML = "El modelo ya aprendió de <b>" + resultado.ejemplos_agregados +
      "</b> repetición(es) más. En total ha visto <b>" + resultado.total_ejemplos_dataset +
      "</b>. El video de práctica ya se borró del servidor.";
    listaFeedback.appendChild(resumen);
  }

  btnOtroVideo.addEventListener("click", function () {
    descartarVideo("Toca aquí para elegir un video");
    zonaSubida.scrollIntoView({ behavior: "smooth", block: "center" });
  });

  // Arranque: sin login, directo a la app.
  describirLimites();
  rotuloReproducir();
  cargarDisciplinas();
})();
