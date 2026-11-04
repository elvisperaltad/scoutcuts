/* ScoutCuts PWA — vanilla JS sin dependencias ni build: el servidor tiene un
 * solo nucleo, asi que servir esto es solo archivos estaticos via nginx. */
(function () {
  "use strict";

  var API_BASE = ""; // mismo origen: nginx reenvia /v1/* al backend.
  var CLAVE_CODIGO = "scoutcuts_codigo_acceso";

  var pantallaLogin = document.getElementById("pantalla-login");
  var pantallaApp = document.getElementById("pantalla-app");
  var inputCodigo = document.getElementById("codigo-acceso");
  var btnEntrar = document.getElementById("btn-entrar");
  var errorLogin = document.getElementById("error-login");
  var textoNombre = document.getElementById("texto-nombre");
  var textoCuota = document.getElementById("texto-cuota");
  var btnSalir = document.getElementById("salir");
  var zonaSubida = document.getElementById("zona-subida");
  var textoZonaSubida = document.getElementById("texto-zona-subida");
  var inputArchivo = document.getElementById("input-archivo");
  var btnSubir = document.getElementById("btn-subir");
  var errorSubida = document.getElementById("error-subida");
  var barraProgreso = document.getElementById("barra-progreso");
  var rellenoProgreso = document.getElementById("relleno-progreso");
  var listaTrabajos = document.getElementById("lista-trabajos");
  var listaVacia = document.getElementById("lista-vacia");
  var avisoActualizacion = document.getElementById("aviso-actualizacion");
  var btnActualizar = document.getElementById("btn-actualizar");

  var archivoElegido = null;
  var temporizadorActualizacion = null;
  var LIMITE_BYTES = 500 * 1024 * 1024; // debe coincidir con LIMITE_POR_DEFECTO (almacen.py)

  function codigoGuardado() {
    try {
      return window.localStorage.getItem(CLAVE_CODIGO) || "";
    } catch (err) {
      return "";
    }
  }

  function guardarCodigo(codigo) {
    try {
      window.localStorage.setItem(CLAVE_CODIGO, codigo);
    } catch (err) {
      /* Safari en modo privado puede negar localStorage; la sesion sigue
       * funcionando, solo que habra que volver a teclear el codigo. */
    }
  }

  function borrarCodigo() {
    try {
      window.localStorage.removeItem(CLAVE_CODIGO);
    } catch (err) { /* ver guardarCodigo */ }
  }

  function mostrarPantalla(pantalla) {
    [pantallaLogin, pantallaApp].forEach(function (p) {
      p.classList.toggle("activa", p === pantalla);
    });
  }

  function peticion(ruta, opciones) {
    opciones = opciones || {};
    var cabeceras = opciones.headers || {};
    var codigo = codigoGuardado();
    if (codigo && ruta !== "/v1/pwa/sesion") {
      cabeceras["Authorization"] = "Bearer " + codigo;
    }
    opciones.headers = cabeceras;
    return fetch(API_BASE + ruta, opciones).then(function (respuesta) {
      return respuesta.json().catch(function () {
        return {};
      }).then(function (cuerpo) {
        if (!respuesta.ok) {
          var err = new Error(cuerpo.mensaje || "Ocurrio un problema.");
          err.estado = respuesta.status;
          throw err;
        }
        return cuerpo;
      });
    });
  }

  function iniciarSesion(codigo) {
    errorLogin.textContent = "";
    btnEntrar.disabled = true;
    btnEntrar.textContent = "Entrando...";
    peticion("/v1/pwa/sesion", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ codigo_acceso: codigo }),
    }).then(function (cuenta) {
      guardarCodigo(codigo);
      mostrarCuenta(cuenta);
      mostrarPantalla(pantallaApp);
      cargarTrabajos();
      programarActualizacion();
    }).catch(function (err) {
      errorLogin.textContent = err.message || "Codigo incorrecto.";
    }).finally(function () {
      btnEntrar.disabled = false;
      btnEntrar.textContent = "Entrar";
    });
  }

  function mostrarCuenta(cuenta) {
    textoNombre.textContent = cuenta.nombre || "Scout";
    textoCuota.textContent =
      cuenta.usados_mes + " de " + cuenta.cuota_mensual + " videos este mes";
  }

  function salir() {
    borrarCodigo();
    if (temporizadorActualizacion) {
      clearInterval(temporizadorActualizacion);
      temporizadorActualizacion = null;
    }
    inputCodigo.value = "";
    listaTrabajos.innerHTML = "";
    mostrarPantalla(pantallaLogin);
  }

  function elegirArchivo(archivo) {
    errorSubida.textContent = "";
    if (archivo && archivo.size > LIMITE_BYTES) {
      archivoElegido = null;
      textoZonaSubida.textContent = "Toca para elegir un video, o arrástralo aquí";
      btnSubir.disabled = true;
      errorSubida.textContent =
        "Ese video pesa demasiado (maximo 500 MB). Elige un video mas corto o con menos calidad.";
      return;
    }
    archivoElegido = archivo || null;
    if (archivoElegido) {
      textoZonaSubida.textContent = archivoElegido.name;
      btnSubir.disabled = false;
    } else {
      textoZonaSubida.textContent = "Toca para elegir un video, o arrástralo aquí";
      btnSubir.disabled = true;
    }
  }

  function subirVideo() {
    if (!archivoElegido) return;
    errorSubida.textContent = "";
    btnSubir.disabled = true;
    barraProgreso.style.display = "block";
    rellenoProgreso.style.width = "0%";

    var formulario = new FormData();
    formulario.append("archivo", archivoElegido);

    var xhr = new XMLHttpRequest();
    xhr.open("POST", API_BASE + "/v1/pwa/trabajos");
    var codigo = codigoGuardado();
    if (codigo) xhr.setRequestHeader("Authorization", "Bearer " + codigo);
    xhr.upload.onprogress = function (evento) {
      if (evento.lengthComputable) {
        var porcentaje = Math.round((evento.loaded / evento.total) * 100);
        rellenoProgreso.style.width = porcentaje + "%";
      }
    };
    xhr.onload = function () {
      barraProgreso.style.display = "none";
      var cuerpo = {};
      try { cuerpo = JSON.parse(xhr.responseText); } catch (err) { /* vacio */ }
      if (xhr.status >= 200 && xhr.status < 300) {
        elegirArchivo(null);
        inputArchivo.value = "";
        cargarTrabajos();
        refrescarCuenta();
      } else {
        errorSubida.textContent = cuerpo.mensaje || "No se pudo subir el video.";
        if (xhr.status === 401) salir();
      }
      btnSubir.disabled = !archivoElegido;
    };
    xhr.onerror = function () {
      barraProgreso.style.display = "none";
      errorSubida.textContent = "No pudimos conectar con el servidor. Revisa tu conexion.";
      btnSubir.disabled = false;
    };
    xhr.send(formulario);
  }

  function refrescarCuenta() {
    peticion("/v1/pwa/sesion", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ codigo_acceso: codigoGuardado() }),
    }).then(mostrarCuenta).catch(function () { /* se reintenta en el siguiente ciclo */ });
  }

  var ETIQUETAS_ESTADO = {
    recibido: "Recibido",
    en_cola: "En cola",
    procesando: "Procesando",
    listo: "Listo",
    pendiente_revision: "En revision",
    error: "Error",
  };

  function pastillaClase(estado) {
    if (estado === "listo") return "listo";
    if (estado === "error") return "error";
    return "";
  }

  function cargarTrabajos() {
    peticion("/v1/pwa/trabajos").then(function (datos) {
      pintarTrabajos(datos.trabajos || []);
    }).catch(function (err) {
      if (err.estado === 401) salir();
    });
  }

  function pintarTrabajos(trabajos) {
    listaTrabajos.innerHTML = "";
    listaVacia.style.display = trabajos.length ? "none" : "block";
    trabajos.slice().reverse().forEach(function (trabajo) {
      var li = document.createElement("li");

      var izquierda = document.createElement("div");
      var nombre = document.createElement("div");
      nombre.className = "trabajo-nombre";
      nombre.textContent = trabajo.nombre || "Video";
      var mensaje = document.createElement("div");
      mensaje.className = "trabajo-mensaje";
      mensaje.textContent = trabajo.mensaje || "";
      izquierda.appendChild(nombre);
      izquierda.appendChild(mensaje);
      if (trabajo.resultado_disponible) {
        var enlace = document.createElement("a");
        enlace.className = "enlace-descarga";
        enlace.textContent = "Descargar montaje";
        enlace.href = "#";
        enlace.addEventListener("click", function (evento) {
          evento.preventDefault();
          descargarResultado(trabajo.id);
        });
        izquierda.appendChild(enlace);
      }

      var pastilla = document.createElement("span");
      pastilla.className = "estado-pastilla " + pastillaClase(trabajo.estado);
      pastilla.textContent = ETIQUETAS_ESTADO[trabajo.estado] || trabajo.estado;

      li.appendChild(izquierda);
      li.appendChild(pastilla);
      listaTrabajos.appendChild(li);
    });
  }

  function descargarResultado(id) {
    var codigo = codigoGuardado();
    fetch(API_BASE + "/v1/pwa/trabajos/" + id + "/resultado", {
      headers: { "Authorization": "Bearer " + codigo },
    }).then(function (respuesta) {
      if (!respuesta.ok) {
        return respuesta.json().then(function (cuerpo) {
          throw new Error(cuerpo.mensaje || "No se pudo descargar el video.");
        });
      }
      return respuesta.blob();
    }).then(function (blob) {
      var url = URL.createObjectURL(blob);
      var enlace = document.createElement("a");
      enlace.href = url;
      enlace.download = "montaje-" + id + ".mp4";
      document.body.appendChild(enlace);
      enlace.click();
      document.body.removeChild(enlace);
      URL.revokeObjectURL(url);
      cargarTrabajos();
    }).catch(function (err) {
      window.alert(err.message || "No se pudo descargar el video.");
    });
  }

  function programarActualizacion() {
    if (temporizadorActualizacion) clearInterval(temporizadorActualizacion);
    temporizadorActualizacion = setInterval(cargarTrabajos, 5000);
  }

  btnEntrar.addEventListener("click", function () {
    var codigo = inputCodigo.value.trim().toUpperCase();
    if (!codigo) {
      errorLogin.textContent = "Escribe tu codigo de acceso.";
      return;
    }
    iniciarSesion(codigo);
  });
  inputCodigo.addEventListener("keydown", function (evento) {
    if (evento.key === "Enter") btnEntrar.click();
  });
  btnSalir.addEventListener("click", salir);

  zonaSubida.addEventListener("click", function () {
    inputArchivo.click();
  });
  inputArchivo.addEventListener("change", function () {
    elegirArchivo(inputArchivo.files && inputArchivo.files[0]);
  });
  ["dragover", "dragenter"].forEach(function (evento) {
    zonaSubida.addEventListener(evento, function (e) {
      e.preventDefault();
      zonaSubida.classList.add("sobre-archivo");
    });
  });
  ["dragleave", "drop"].forEach(function (evento) {
    zonaSubida.addEventListener(evento, function (e) {
      e.preventDefault();
      zonaSubida.classList.remove("sobre-archivo");
    });
  });
  zonaSubida.addEventListener("drop", function (evento) {
    var archivos = evento.dataTransfer && evento.dataTransfer.files;
    if (archivos && archivos.length) elegirArchivo(archivos[0]);
  });
  btnSubir.addEventListener("click", subirVideo);

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js").then(function (registro) {
        // Si ya hay un SW esperando (se instalo mientras la pestaña estaba
        // cerrada), avisar de inmediato; si no, esperar a que aparezca uno.
        if (registro.waiting) {
          mostrarAvisoActualizacion(registro.waiting);
        }
        registro.addEventListener("updatefound", function () {
          var nuevo = registro.installing;
          if (!nuevo) return;
          nuevo.addEventListener("statechange", function () {
            if (nuevo.state === "installed" && navigator.serviceWorker.controller) {
              mostrarAvisoActualizacion(nuevo);
            }
          });
        });
      }).catch(function () {
        /* sin service worker la app sigue funcionando, solo que no instalable */
      });

      var recargando = false;
      navigator.serviceWorker.addEventListener("controllerchange", function () {
        // No recargar si hay una subida en curso: perderia el progreso sin
        // avisar. En ese caso se recarga sola en cuanto termine la subida.
        if (recargando) return;
        if (barraProgreso.style.display === "block") return;
        recargando = true;
        window.location.reload();
      });
    });
  }

  function mostrarAvisoActualizacion(workerNuevo) {
    if (!avisoActualizacion) return;
    avisoActualizacion.style.display = "flex";
    btnActualizar.onclick = function () {
      workerNuevo.postMessage({ tipo: "activar" });
    };
  }

  var codigoExistente = codigoGuardado();
  if (codigoExistente) {
    inputCodigo.value = codigoExistente;
    iniciarSesion(codigoExistente);
  }
})();
