/* ScoutCuts — zona de entrenamiento QA (scoutcuts.com/entrenamiento).
 *
 * Aislada de la PWA de produccion: token distinto, clave de localStorage
 * distinta, y el backend guarda los videos de practica en una carpeta
 * separada de los trabajos reales (ver cortador.servidor.entrenamiento).
 * Vanilla JS sin dependencias, igual que el resto del sitio.
 *
 * Atiende las cuatro disciplinas entrenables (defensa, bateo, pitcheo,
 * catcher) desde la misma pantalla: el QA elige cual entrenar con un
 * selector, y las categorias/rotulos vienen del servidor
 * (/v1/entrenamiento/disciplinas), nunca hardcodeadas aqui -- asi una
 * disciplina nueva no requiere tocar este archivo.
 */
(function () {
  "use strict";

  var API_BASE = "";
  var CLAVE_CODIGO = "scoutcuts_codigo_entrenamiento";
  var CLAVE_DISCIPLINA = "scoutcuts_disciplina_entrenamiento";

  var pantallaLogin = document.getElementById("pantalla-login");
  var pantallaApp = document.getElementById("pantalla-app");
  var inputCodigo = document.getElementById("codigo-entrenamiento");
  var btnEntrar = document.getElementById("btn-entrar");
  var errorLogin = document.getElementById("error-login");
  var btnSalir = document.getElementById("salir-entrenamiento");

  var selectorDisciplina = document.getElementById("selector-disciplina");
  var resumenModelo = document.getElementById("resumen-modelo");
  var zonaSubida = document.getElementById("zona-subida");
  var textoZonaSubida = document.getElementById("texto-zona-subida");
  var inputArchivo = document.getElementById("input-archivo");
  var errorSubida = document.getElementById("error-subida");

  var tarjetaMarcado = document.getElementById("tarjeta-marcado");
  var videoPractica = document.getElementById("video-practica");
  var valorInicio = document.getElementById("valor-inicio");
  var valorTiro = document.getElementById("valor-tiro");
  var btnMarcarInicio = document.getElementById("btn-marcar-inicio");
  var btnMarcarTiro = document.getElementById("btn-marcar-tiro");
  var contenedorCategorias = document.getElementById("categorias");
  var errorJugada = document.getElementById("error-jugada");
  var btnAgregarJugada = document.getElementById("btn-agregar-jugada");
  var listaJugadas = document.getElementById("lista-jugadas");
  var jugadasVacio = document.getElementById("jugadas-vacio");
  var btnEntrenar = document.getElementById("btn-entrenar");

  var tarjetaFeedback = document.getElementById("tarjeta-feedback");
  var listaFeedback = document.getElementById("lista-feedback");
  var btnOtroVideo = document.getElementById("btn-otro-video");

  var disciplinas = [];           // [{id, nombre, categorias: [{id, nombre}]}]
  var disciplinaActual = null;    // id de la disciplina elegida
  var nombresCategoria = {};      // id -> nombre legible, de la disciplina actual

  var videoActualId = null;
  var videoActualNombre = null;
  var inicioMarcado = null;
  var tiroMarcado = null;
  var categoriaElegida = null;
  var jugadas = [];

  function codigoGuardado() {
    try { return window.localStorage.getItem(CLAVE_CODIGO) || ""; }
    catch (err) { return ""; }
  }
  function guardarCodigo(codigo) {
    try { window.localStorage.setItem(CLAVE_CODIGO, codigo); } catch (err) { /* ver PWA */ }
  }
  function borrarCodigo() {
    try { window.localStorage.removeItem(CLAVE_CODIGO); } catch (err) { /* ver PWA */ }
  }
  function disciplinaGuardada() {
    try { return window.localStorage.getItem(CLAVE_DISCIPLINA) || ""; }
    catch (err) { return ""; }
  }
  function guardarDisciplina(id) {
    try { window.localStorage.setItem(CLAVE_DISCIPLINA, id); } catch (err) { /* ver PWA */ }
  }

  function mostrarPantalla(pantalla) {
    [pantallaLogin, pantallaApp].forEach(function (p) {
      p.classList.toggle("activa", p === pantalla);
    });
  }

  function peticion(ruta, opciones) {
    opciones = opciones || {};
    var cabeceras = opciones.headers || {};
    cabeceras["Authorization"] = "Bearer " + codigoGuardado();
    opciones.headers = cabeceras;
    return fetch(API_BASE + ruta, opciones).then(function (respuesta) {
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

  function disciplina(id) {
    for (var i = 0; i < disciplinas.length; i++) {
      if (disciplinas[i].id === id) return disciplinas[i];
    }
    return null;
  }

  // --- Carga inicial: que disciplinas existen, con que categorias ---
  function cargarDisciplinas() {
    return peticion("/v1/entrenamiento/disciplinas").then(function (respuesta) {
      disciplinas = respuesta.disciplinas;
      selectorDisciplina.innerHTML = "";
      disciplinas.forEach(function (d) {
        var opcion = document.createElement("option");
        opcion.value = d.id;
        opcion.textContent = d.nombre;
        selectorDisciplina.appendChild(opcion);
      });
      var preferida = disciplinaGuardada();
      disciplinaActual = disciplina(preferida) ? preferida : disciplinas[0].id;
      selectorDisciplina.value = disciplinaActual;
      aplicarDisciplina(disciplinaActual);
    }).catch(function () {
      resumenModelo.textContent = "No se pudo cargar la lista de disciplinas.";
    });
  }

  function aplicarDisciplina(id) {
    disciplinaActual = id;
    guardarDisciplina(id);
    var actual = disciplina(id);
    nombresCategoria = {};
    contenedorCategorias.innerHTML = "";
    (actual ? actual.categorias : []).forEach(function (c) {
      nombresCategoria[c.id] = c.nombre;
      var boton = document.createElement("button");
      boton.setAttribute("data-categoria", c.id);
      boton.textContent = c.nombre;
      boton.addEventListener("click", function () {
        categoriaElegida = boton.getAttribute("data-categoria");
        Array.prototype.forEach.call(contenedorCategorias.children, function (b) {
          b.classList.toggle("elegida", b === boton);
        });
        actualizarBotonAgregar();
      });
      contenedorCategorias.appendChild(boton);
    });
    cargarEstadoModelo();
    // Cambiar de disciplina a mitad de un video sin entrenar causaria
    // confusion (las categorias ya no corresponden); se oculta el marcado
    // en vez de dejarlo con botones de la disciplina anterior.
    tarjetaMarcado.style.display = "none";
    tarjetaFeedback.style.display = "none";
    videoActualId = null;
    videoActualNombre = null;
    textoZonaSubida.textContent = "Toca para elegir un video";
  }

  selectorDisciplina.addEventListener("change", function () {
    aplicarDisciplina(selectorDisciplina.value);
  });

  function cargarEstadoModelo() {
    peticion("/v1/entrenamiento/modelo/" + disciplinaActual).then(function (estado) {
      var html = "Ha visto <b>" + estado.total_ejemplos + "</b> jugada(s) en total.<br>";
      html += estado.categorias.map(function (c) {
        var n = estado.ejemplos_por_categoria[c] || 0;
        var clase = n > 0 ? "pastilla-categoria cubierta" : "pastilla-categoria";
        return '<span class="' + clase + '">' + (nombresCategoria[c] || c) + ": " + n + "</span>";
      }).join(" ");
      html += "<br>" + (estado.modelo_calibrado
        ? "El modelo ya puede dar una opinión."
        : "Todavía le faltan ejemplos para poder opinar con confianza.");
      resumenModelo.innerHTML = html;
    }).catch(function (err) {
      resumenModelo.textContent = "No se pudo consultar el estado del modelo.";
    });
  }

  function reiniciarMarcado() {
    inicioMarcado = null;
    tiroMarcado = null;
    categoriaElegida = null;
    jugadas = [];
    valorInicio.textContent = "sin marcar";
    valorTiro.textContent = "sin marcar";
    Array.prototype.forEach.call(contenedorCategorias.children, function (b) {
      b.classList.remove("elegida");
    });
    actualizarListaJugadas();
    actualizarBotonAgregar();
  }

  function actualizarBotonAgregar() {
    btnAgregarJugada.disabled = !(inicioMarcado !== null && tiroMarcado !== null && categoriaElegida);
  }

  function actualizarListaJugadas() {
    listaJugadas.innerHTML = "";
    jugadasVacio.style.display = jugadas.length === 0 ? "block" : "none";
    btnEntrenar.disabled = jugadas.length === 0;
    jugadas.forEach(function (j, indice) {
      var li = document.createElement("li");
      var texto = document.createElement("span");
      texto.textContent = (nombresCategoria[j.categoria] || j.categoria) + " · " +
        formatoSegundos(j.inicio) + " → " + formatoSegundos(j.tiro);
      var quitar = document.createElement("button");
      quitar.className = "jugada-quitar";
      quitar.textContent = "Quitar";
      quitar.addEventListener("click", function () {
        jugadas.splice(indice, 1);
        actualizarListaJugadas();
      });
      li.appendChild(texto);
      li.appendChild(quitar);
      listaJugadas.appendChild(li);
    });
  }

  // --- Login ---
  btnEntrar.addEventListener("click", function () {
    var codigo = inputCodigo.value.trim();
    if (!codigo) {
      errorLogin.textContent = "Escribe el código de acceso.";
      return;
    }
    guardarCodigo(codigo);
    errorLogin.textContent = "";
    mostrarPantalla(pantallaApp);
    cargarDisciplinas();
  });

  btnSalir.addEventListener("click", function () {
    borrarCodigo();
    inputCodigo.value = "";
    mostrarPantalla(pantallaLogin);
  });

  if (codigoGuardado()) {
    mostrarPantalla(pantallaApp);
    cargarDisciplinas();
  }

  // --- Subida de video ---
  zonaSubida.addEventListener("click", function () { inputArchivo.click(); });

  inputArchivo.addEventListener("change", function () {
    var archivo = inputArchivo.files[0];
    if (!archivo) return;
    errorSubida.textContent = "";
    textoZonaSubida.textContent = "Subiendo " + archivo.name + "...";
    var datosForma = new FormData();
    datosForma.append("archivo", archivo);
    peticion("/v1/entrenamiento/" + disciplinaActual + "/videos", { method: "POST", body: datosForma })
      .then(function (respuesta) {
        videoActualId = respuesta.id;
        videoActualNombre = respuesta.nombre;
        textoZonaSubida.textContent = "Toca para elegir otro video";
        videoPractica.src = URL.createObjectURL(archivo);
        reiniciarMarcado();
        tarjetaFeedback.style.display = "none";
        tarjetaMarcado.style.display = "block";
        tarjetaMarcado.scrollIntoView({ behavior: "smooth" });
      })
      .catch(function (err) {
        textoZonaSubida.textContent = "Toca para elegir un video";
        errorSubida.textContent = err.message;
      })
      .finally(function () { inputArchivo.value = ""; });
  });

  // --- Marcado de jugadas ---
  btnMarcarInicio.addEventListener("click", function () {
    inicioMarcado = videoPractica.currentTime;
    valorInicio.textContent = formatoSegundos(inicioMarcado);
    actualizarBotonAgregar();
  });

  btnMarcarTiro.addEventListener("click", function () {
    tiroMarcado = videoPractica.currentTime;
    valorTiro.textContent = formatoSegundos(tiroMarcado);
    actualizarBotonAgregar();
  });

  btnAgregarJugada.addEventListener("click", function () {
    errorJugada.textContent = "";
    if (tiroMarcado <= inicioMarcado) {
      errorJugada.textContent = "El tiro debe marcarse después del inicio.";
      return;
    }
    jugadas.push({
      categoria: categoriaElegida, inicio: inicioMarcado, tiro: tiroMarcado,
      estado: "completa", seleccionada: true,
    });
    inicioMarcado = null;
    tiroMarcado = null;
    categoriaElegida = null;
    valorInicio.textContent = "sin marcar";
    valorTiro.textContent = "sin marcar";
    Array.prototype.forEach.call(contenedorCategorias.children, function (b) {
      b.classList.remove("elegida");
    });
    actualizarBotonAgregar();
    actualizarListaJugadas();
  });

  // --- Entrenar y mostrar feedback ---
  btnEntrenar.addEventListener("click", function () {
    btnEntrenar.disabled = true;
    btnEntrenar.textContent = "Entrenando...";
    peticion("/v1/entrenamiento/videos/" + videoActualId + "/entrenar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video: videoActualNombre, repeticiones: jugadas }),
    }).then(function (resultado) {
      mostrarFeedback(resultado);
      tarjetaMarcado.style.display = "none";
      tarjetaFeedback.style.display = "block";
      tarjetaFeedback.scrollIntoView({ behavior: "smooth" });
      cargarEstadoModelo();
    }).catch(function (err) {
      errorJugada.textContent = err.message;
    }).finally(function () {
      btnEntrenar.disabled = false;
      btnEntrenar.textContent = "Entrenar al modelo con estas jugadas";
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
    resultado.evaluacion.forEach(function (fila) {
      var div = document.createElement("div");
      var marcada = nombresCategoria[fila.categoria_marcada] || fila.categoria_marcada;
      if (fila.categoria_predicha === null) {
        div.className = "feedback-jugada";
        div.innerHTML = '<div class="titulo">Jugada marcada: ' + marcada + "</div>" +
          '<div class="detalle">El modelo todavía no tenía suficientes ejemplos para opinar sobre esta jugada; de todos modos ya aprendió de ella.</div>';
      } else if (fila.coincide) {
        div.className = "feedback-jugada acierto";
        div.innerHTML = '<div class="titulo">✓ El modelo coincidió: ' + marcada + "</div>" +
          '<div class="detalle">Lo reconoció ' + nivelConfianza(fila.confianza) + ".</div>";
      } else {
        var predicha = nombresCategoria[fila.categoria_predicha] || fila.categoria_predicha;
        div.className = "feedback-jugada diferente";
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
      "</b> jugada(s) más. En total ha visto <b>" + resultado.total_ejemplos_dataset + "</b>.";
    listaFeedback.appendChild(resumen);
  }

  btnOtroVideo.addEventListener("click", function () {
    tarjetaFeedback.style.display = "none";
    tarjetaMarcado.style.display = "none";
    videoActualId = null;
    videoActualNombre = null;
  });
})();
