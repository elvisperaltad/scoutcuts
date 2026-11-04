/* Service worker minimo: solo cachea el cascaron estatico (HTML/JS/CSS/
 * iconos) para que la app abra rapido y sea instalable. Nunca intercepta
 * /v1/* (login, subida, estado, descarga de video): esas peticiones
 * siempre deben ir a la red, en vivo, nunca servirse desde cache. */
var CACHE = "scoutcuts-v1";
var ARCHIVOS_CASCARON = ["/", "/app.js", "/manifest.json"];

self.addEventListener("install", function (evento) {
  evento.waitUntil(
    caches.open(CACHE).then(function (cache) {
      return cache.addAll(ARCHIVOS_CASCARON);
    })
  );
});

self.addEventListener("activate", function (evento) {
  evento.waitUntil(
    caches.keys().then(function (nombres) {
      return Promise.all(
        nombres
          .filter(function (nombre) { return nombre !== CACHE; })
          .map(function (nombre) { return caches.delete(nombre); })
      );
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
