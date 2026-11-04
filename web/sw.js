/* Service worker minimo: solo cachea el cascaron estatico (HTML/JS/CSS/
 * iconos) para que la app abra rapido y sea instalable. Nunca intercepta
 * /v1/* (login, subida, estado, descarga de video): esas peticiones
 * siempre deben ir a la red, en vivo, nunca servirse desde cache.
 *
 * NO se llama a skipWaiting() automaticamente: un SW nuevo se queda
 * "esperando" hasta que app.js mande el mensaje "activar" (el scout pulso
 * el aviso de actualizacion). Activar sin avisar podria recargar la pagina
 * a mitad de una subida de video sin que el scout lo decidiera. */
var CACHE = "scoutcuts-v2";
var ARCHIVOS_CASCARON = ["/", "/app.js", "/manifest.json"];

self.addEventListener("install", function (evento) {
  evento.waitUntil(
    caches.open(CACHE).then(function (cache) {
      return cache.addAll(ARCHIVOS_CASCARON);
    })
  );
});

self.addEventListener("message", function (evento) {
  if (evento.data && evento.data.tipo === "activar") {
    self.skipWaiting();
  }
});

self.addEventListener("activate", function (evento) {
  evento.waitUntil(
    caches.keys().then(function (nombres) {
      return Promise.all(
        nombres
          .filter(function (nombre) { return nombre !== CACHE; })
          .map(function (nombre) { return caches.delete(nombre); })
      );
    }).then(function () {
      return self.clients.claim();
    })
  );
});

self.addEventListener("fetch", function (evento) {
  var url = new URL(evento.request.url);
  if (url.pathname.indexOf("/v1/") === 0) {
    return; // deja pasar a la red sin intervenir
  }
  if (evento.request.method !== "GET") {
    return;
  }
  evento.respondWith(
    caches.match(evento.request).then(function (respuestaCache) {
      return respuestaCache || fetch(evento.request);
    })
  );
});
