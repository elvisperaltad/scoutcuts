# Continuación del servidor ScoutCuts

Documento de relevo para otro Claude/agente. Estado verificado el 2026-11-04
(tarde) en el servidor, tras desplegar y probar la API de punta a punta.

## Regla principal

La API YA ESTÁ DESPLEGADA Y FUNCIONANDO en producción. `scoutcuts.service`
corre como `systemd`, nginx tiene TLS activo y hace proxy a `127.0.0.1:8010`.
`https://api.scoutcuts.com/salud` responde 200. Un video real subido con
token válido pasa por toda la cadena (subida -> cola -> detección -> montaje
-> descarga vía `X-Accel-Redirect` -> borrado del original) y fue verificado
con un video sintético real contra un perfil de cámara real.

No asumir que esto sigue "pendiente" solo porque documentos más viejos
(`SERVIDOR_CONTROL.md` en su versión original) lo describan como plan futuro.
Este archivo es la fuente de verdad más reciente.

No modificar ni borrar el trabajo local existente. El repositorio tiene
cambios sin commit y archivos sin seguimiento. No hacer `git reset`,
`git checkout`, `git clean`, commit o push sin autorización expresa del
propietario.

## Acceso y máquina

- Proyecto local: `C:/Dev/projects/cortador-turnos`.
- **Repositorio GitHub real (fuente de verdad del codigo junto con la estacion local):**
  `https://github.com/elvisperaltad/scoutcuts.git`, rama `main`. Privado. Ultimo commit
  verificado: `8f116cd` ("Gracia extendida de purga para videos pendientes de revision").
- Servidor: `144.202.57.21`.
- Alias SSH administrativo obligatorio: `ssh precios` (no conectar como `root@IP`).
- **Acceso root completo agregado 2026-11-04** para un segundo desarrollador de
  confianza, con la MISMA clave que ya tenia (`scoutcuts-20261103`, huella
  `SHA256:iDZfAVekqpKfK5bUX7RRRlSRNZcq6qJgFA2RI31qUko`) ahora tambien en
  `/root/.ssh/authorized_keys`. Detalle completo, que puede hacer y que reglas sigue:
  `ACCESO_DESARROLLADOR.md`.
- Acceso QA/desarrollo RESTRINGIDO (sigue activo en paralelo, para quien no deba tener
  nivel root): usuario `scoutqa`, grupos `scoutdocs` y `scoutdev`, sin
  sudo, sin secretos, sin acceso a producción y sin forwarding/túneles. Puede
  escribir únicamente en `/opt/cortador-control/dev/cortador-turnos` (un
  SNAPSHOT separado, no el código desplegado). Clave pública con comentario
  `scoutcuts-20261103`, huella `SHA256:iDZfAVekqpKfK5bUX7RRRlSRNZcq6qJgFA2RI31qUko`.
  Instrucciones en `/opt/cortador-control/docs/ACCESO_QA_SSH.md` y
  `DESARROLLO_REMOTO.md`. Verificado tras el despliegue: `scoutqa` sigue sin
  poder leer `/opt/cortador-control/datos` ni `/etc/cortador-control/app.env`.
- Host: `vultr`.
- SO: Ubuntu 26.04.1 LTS, kernel 7.0.0-38-generic.
- Capacidad: 1 CPU, 950 MiB RAM, 2.3 GiB swap, 23 GB de disco.
- Huella ED25519 confirmada contra Vultr: `SHA256:of5Zz14W154QfiUJPCnotumDXRRB45nvh5clLeQySkc`.
- Si cambia la huella sin reinstalación declarada, detenerse. No usar `StrictHostKeyChecking=no`.

## Seguridad ya aplicada

- SSH solo por llave, `PasswordAuthentication no`, `fail2ban` con cárcel `sshd`.
- UFW: solo 22, 80 y 443 públicos.
- PostgreSQL solo en loopback.
- Usuario de servicio `cortador`, sin shell interactivo.
- `scoutcuts.service` corre como `cortador` (no root), con `ProtectSystem=strict`,
  `ProtectHome=true`, `PrivateTmp=true`, `NoNewPrivileges=true` y
  `ReadWritePaths=/opt/cortador-control/datos` como única ruta de escritura.
- El código y el entorno virtual del servicio son propiedad de `root`
  (de solo lectura/ejecución para `cortador`): el proceso que procesa video
  subido por desconocidos no puede modificar su propio ejecutable.
- Token de autenticación del endpoint (`SCOUTCUTS_TOKEN_QA`) comparado con
  `secrets.compare_digest`, nunca con `!=`.
- La autenticación de `POST /v1/trabajos` corre en un middleware ASGI ANTES
  de que FastAPI lea el cuerpo multipart: una subida sin token se rechaza sin
  que el servidor reciba un solo byte del archivo.
- Un `threading.Lock` en la API rechaza con 503 cualquier segunda subida
  mientras la primera sigue escribiendo a disco (el servidor tiene 1 núcleo;
  dos subidas simultáneas solo arriesgan la memoria, no las terminan antes).

Verificación rápida:

```bash
ssh precios 'sshd -T | grep -E "^(permitrootlogin|passwordauthentication|pubkeyauthentication)"; ufw status; systemctl is-active ssh nginx postgresql fail2ban scoutcuts'
```

## Dominio y TLS

- Dominio `scoutcuts.com` en GoDaddy, DNS A en `@`/`api`/`descargas` -> `144.202.57.21`.
- Certificado Let's Encrypt ECDSA para los cuatro nombres, vence 2027-02-01,
  renovación automática verificada.
- `https://scoutcuts.com/` responde 200 (página temporal).
- `https://api.scoutcuts.com/salud` responde 200 (API real, no 502).
- `https://descargas.scoutcuts.com/` sigue en 502: ese servicio (entrega de
  instaladores) todavía no se implementó; es el estado esperado.

Archivos remotos: `/etc/nginx/sites-available/scoutcuts`,
`/etc/nginx/snippets/scoutcuts-tls.conf`, `/etc/letsencrypt/live/scoutcuts.com/`.

Copias versionadas locales: `despliegue/nginx-scoutcuts.conf` (incluye ahora
el bloque `/protegido/` de `api.scoutcuts.com` apuntando a
`/opt/cortador-control/datos/trabajos/`), `despliegue/nginx-scoutcuts-tls.conf`.

Antes de recargar: `ssh precios 'nginx -t && systemctl reload nginx'`.

## PostgreSQL y secretos

- PostgreSQL 18.6, base `cortador_control`, rol `cortador` (sin uso real
  todavía: la API actual no usa base de datos, solo filesystem).
- Secretos en `/etc/cortador-control/app.env`, propiedad `root:cortador`, `640`.
- Variables activas: `SCOUTCUTS_TOKEN_QA` (generado en el servidor, nunca por
  chat), `SCOUTCUTS_DATOS`, `SCOUTCUTS_QA`, `SCOUTCUTS_PERFILES`,
  `SCOUTCUTS_ENTREGA_NGINX=1`.
- Nunca leer, copiar, imprimir o incluir el valor de ninguna variable de este
  archivo en documentación, logs, comandos enviados al chat o repositorio.

## Estructura de directorios en el servidor

- `/opt/cortador-control/app` -> symlink a la release activa en
  `/opt/cortador-control/releases-app/<timestamp>/` (código + venv,
  propiedad `root`, de solo lectura para `cortador`).
- `/opt/cortador-control/releases-app/` guarda las ultimas 5 releases
  desplegadas MAS la activa, nunca mas (ver `limpiar-releases-viejas.sh`,
  2026-11-04: antes guardaba TODAS sin limite, ~318MB cada una, y agoto
  2.2GB solo en un dia de desarrollo activo con despliegues frecuentes
  en un disco de 23GB -- se corrigio antes de que se convirtiera en un
  incidente real). Rollback manual a una de esas 5: cambiar el symlink
  `app` y `systemctl restart scoutcuts`. Para volver a una release MAS
  vieja que las 5 conservadas, hay que re-desplegar desde el commit de
  git correspondiente (ya no existe la carpeta).
- `/opt/cortador-control/datos/trabajos/<id>/` — carpeta por trabajo subido,
  propiedad `cortador:entrega`, modo `2750` (setgid: todo lo que se cree
  adentro hereda el grupo `entrega` automáticamente).
- `/opt/cortador-control/datos/qa/` — evidencia QA (`CorridaQA`), propiedad
  `cortador:cortador`, `750` (no necesita ser legible por nginx).
- `/opt/cortador-control/dev/cortador-turnos/` — snapshot SEPARADO donde
  trabaja `scoutqa` con su propio Claude; nunca es lo que está desplegado.
- `/opt/cortador-control/integrado/` — copia de trabajo usada para esta
  integración; puede borrarse o resincronizarse en el futuro, no es
  autoritativa (la fuente de verdad es siempre la estación local
  `C:/Dev/projects/cortador-turnos` + lo que hay en `releases-app/`).

Grupo de sistema `entrega` = `{cortador, www-data}`, creado específicamente
para que nginx pueda atravesar y leer `datos/trabajos/<id>/resultado.mp4` sin
exponer nada a otros usuarios del sistema. Antes de este grupo, `www-data`
no tenía permiso de atravesar esas carpetas y el `X-Accel-Redirect` fallaba
con 403 — se reprodujo y confirmó el fallo antes de corregirlo.

## Cómo desplegar una nueva versión

```bash
# 1. Sincronizar el código probado (sin .venv/.git/videos) a /opt/cortador-control/integrado
#    (o la carpeta que se use como SOURCE), por ejemplo con rsync o scp+tar.
# 2. En el servidor, como root:
cd /opt/cortador-control/integrado   # o donde esté el código a desplegar
SOURCE=/opt/cortador-control/integrado bash despliegue/desplegar.sh
# 3. Verificar de punta a punta:
TOKEN=$(grep '^SCOUTCUTS_TOKEN_QA=' /etc/cortador-control/app.env | cut -d= -f2-)
export TOKEN
bash despliegue/verificar-despliegue.sh
```

`desplegar.sh` construye TODO (código + venv) en una release nueva en
`/opt/cortador-control/releases-app/<timestamp>/` como `root`, y solo al
final mueve el symlink `app` de forma atómica y reinicia el servicio. Nunca
escribe directamente sobre la release en uso. Si `/salud` local no responde
200 después de reiniciar, el script se detiene con `exit 1` ANTES de tocar
nginx — no deja el sitio público apuntando a un backend roto.

`verificar-despliegue.sh` ya NO es informativo: acumula fallos reales y
termina con `exit 1` si algo no es lo esperado, e incluye un E2E real
(sube un video sintético de prueba, espera que la cola lo procese, intenta
descargarlo). Nunca lo tomes como éxito solo porque imprimió números; revisa
la última línea (`Despliegue verificado` vs `Despliegue NO verificado`).

IMPORTANTE: los perfiles de cámara (`perfiles/*.json`) están en `.gitignore`
a propósito y NO viajan con `rsync`/`tar` del repo. Si faltan en la release
nueva, todo video queda `pendiente_revision` sin importar que el resto
funcione. Cópialos a mano a `<release>/perfiles/` (propiedad `root:cortador`,
`640`) o automatiza esa copia en una variante futura de `desplegar.sh`.

## Pruebas (estado real, verificado el 2026-11-03)

- Local (Windows, `.venv`): **189 passed**, incluye el E2E real con
  `Video/carlos/VIDEO-2026-09-08-18-36-39.mov`.
- Servidor (venv temporal de verificación, Linux): **172 passed, 17 skipped**
  (saltos legítimos: sin torch, sin fixtures de video real en ese venv
  temporal — no son fallos de la API).
- E2E manual contra producción real (`https://api.scoutcuts.com`): subida con
  token -> `en_cola` -> `listo` -> descarga con `Content-Length` correcto,
  MP4 válido, `entrada.mp4` borrado tras la descarga.

## Decisiones de producto ya tomadas

- La experiencia móvil es una web instalable/PWA (ya construida y desplegada
  en `scoutcuts.com`, 2026-11-04), no dos apps nativas.
- El teléfono sube, consulta progreso, revisa y descarga; el servidor procesa.
- El escritorio portátil se conserva para QA sin internet.
- La VPS procesa un trabajo a la vez (1 núcleo): hay cola de un solo carril
  en `cola.py` Y un lock de una sola subida activa en `api.py`.
- Los originales se borran después de entregar el resultado y por vencimiento
  (`almacen.purgar`).
- CDN/Object Storage se pospone.

## Lo que falta (no implementado todavía)

1. **`descargas.scoutcuts.com`** — entrega de instaladores con validación de
   licencia; sigue en 502 a propósito.
2. **Login/sesiones por usuario — IMPLEMENTADO LOCALMENTE (2026-11-03,
   tarde), SIN DESPLEGAR TODAVÍA.** `src/cortador/servidor/usuarios.py`
   (cuentas JSON atómicas, cuota mensual por `telegram_id`) +
   `src/cortador/servidor/bot_telegram.py` (bot de Telegram que recibe el
   video, lo mete en la MISMA `Almacen`/`Cola` que la API HTTP, y entrega el
   resultado por el mismo chat). Administración por CLI:
   `cortador usuarios crear/listar/activar/desactivar`. Documentado en
   `TELEGRAM_BOT.md`. 240 pruebas locales pasan. El `SCOUTCUTS_TOKEN_QA`
   Bearer estático sigue existiendo para la API HTTP; el bot es un canal
   paralelo con su propio login por `telegram_id`, no un reemplazo del
   token. Decisión explícita: sin LLM local (el VPS tiene 950 MiB de RAM,
   no alcanza); el bot entiende solo `/start`, `/estado` y recepción de
   video — ver sección "Por qué NO usa LLM" en `TELEGRAM_BOT.md`.
   Límites reales de la API de Telegram en modo nube (verificados con
   pruebas que fuerzan el límite, no solo implementados): `getFile` no
   baja más de 20 MB (`LIMITE_DESCARGA_BYTES`, validado ANTES de intentar
   la descarga) y `sendVideo` no sube más de 50 MB (`LIMITE_SUBIDA_BYTES`,
   validado antes de intentar el envío); en ambos casos el scout recibe un
   mensaje claro pidiendo ayuda al administrador en vez de que el bot
   falle en silencio. Para videos de cientos de MB habría que migrar a un
   Local Bot API Server propio (hasta 2 GB) — no es necesario para esta
   primera versión, documentado como extensión futura en `TELEGRAM_BOT.md`.
   PENDIENTE antes de activar en producción real: (a) crear el bot con
   @BotFather y generar `SCOUTCUTS_TELEGRAM_BOT_TOKEN`; (b) decidir y fijar
   `SCOUTCUTS_USUARIOS` en `/etc/cortador-control/app.env` (si no se fija,
   cae al default `SCOUTCUTS_DATOS/usuarios`, razonable pero debe ser una
   decisión consciente); (c) `pip install -e .[telegram]` en el venv del
   servicio; (d) registrar manualmente a los primeros scouts con
   `cortador usuarios crear` ANTES de anunciarles el bot (nadie se
   auto-registra); (e) desplegar con `desplegar.sh` normal (no requiere
   cambios en nginx ni en systemd: el bot corre dentro del mismo proceso
   `scoutcuts.service`, en un hilo daemon aparte).
3. **Rotación/revocación del token QA — IMPLEMENTADO (2026-11-04).**
   `despliegue/rotar-token-qa.sh` genera un token nuevo, respalda el
   anterior (`app.env.bak-<timestamp>`), reemplaza SOLO la linea
   `SCOUTCUTS_TOKEN_QA=` (preserva el resto del archivo intacto), reinicia
   el servicio, y prueba `/salud`. Si no vuelve a responder 200, REVIERTE
   automaticamente al token anterior y restaura el servicio, en vez de
   dejar la API caida por un error en la rotacion. Nunca imprime ningun
   valor de token en pantalla ni en logs. Uso en el servidor, como root:
   `bash despliegue/rotar-token-qa.sh`. 4 pruebas nuevas
   (`tests/despliegue/test_rotar_token_qa.py`) contra un `systemctl` falso
   inyectado por PATH (no existe systemd en la maquina de pruebas) y un
   servidor HTTP falso para `/salud`. Pendiente real, no de codigo: avisar
   a quien tenga el token QA actual (si alguien externo lo usa) de que
   cambio, porque el viejo deja de servir de inmediato.
4. **Monitoreo/alertas — IMPLEMENTADO (2026-11-04).** `despliegue/monitor-salud.sh`
   revisa cada 5 minutos (`scoutcuts-monitor.timer`) tres cosas en orden:
   `scoutcuts.service` activo, `nginx` activo, y la ruta PUBLICA real
   `https://api.scoutcuts.com/salud` responde 200 (no loopback: asi
   tambien detecta DNS/TLS roto, que loopback nunca veria). Alerta por
   Telegram SOLO en la transicion de estado (ok->fallo, fallo->ok), nunca
   en cada corrida, para no inundar el chat del admin; el estado anterior
   se guarda en `SCOUTCUTS_DATOS/monitor_estado` (texto plano). Sin fallo
   no hay alerta ni ruido. 4 pruebas nuevas (`tests/despliegue/
   test_monitor_salud.py`), todas contra un servidor HTTP falso real, no
   mocks de systemctl. `desplegar.sh` ahora instala y habilita este timer
   y el de purga automaticamente (antes `scoutcuts-purga` se instalaba a
   mano, fuera del pipeline — ya no).
   **PENDIENTE para que la alerta llegue de verdad, no solo quede en
   journalctl:** (a) el mismo bot de Telegram del punto 2 debe existir
   (crear con @BotFather, `SCOUTCUTS_TELEGRAM_BOT_TOKEN`); (b) fijar
   `SCOUTCUTS_TELEGRAM_ADMIN_ID` en `/etc/cortador-control/app.env` con el
   `chat_id` de Telegram del propietario (NO el de un scout), obtenible
   escribiendole a `@userinfobot`. Sin esas dos variables, el monitoreo
   sigue corriendo y deja registro en `journalctl -u scoutcuts-monitor`,
   pero nadie se entera por chat hasta que entre a revisar el log a mano.
5. ~~**PWA real** del lado del cliente (la API ya soporta el flujo completo).~~
   **HECHA Y DESPLEGADA (2026-11-04).** `web/` (HTML/CSS/JS vanilla, sin build):
   login por `codigo_acceso` (nuevo campo en `Usuario`, generado siempre al
   crear la cuenta; `telegram_id` ahora es opcional), subida con progreso,
   lista de trabajos con auto-refresco, descarga, instalable (manifest +
   service worker que solo cachea el cascarón estático). Endpoints nuevos
   `/v1/pwa/*` en `api.py`. nginx sirve `web/` como root de `scoutcuts.com` y
   reenvía `/v1/pwa/*` + `/salud` al mismo backend bajo el mismo origen (sin
   CORS). `desplegar.sh` publica `web/` en `/var/www/scoutcuts` en cada
   despliegue. Verificado con navegador real contra `https://scoutcuts.com`
   (login, subida, cuota, logout, manifest y service worker activos de
   verdad). Pendiente real: que un QA externo la pruebe desde su propio
   teléfono y devuelva evidencia — eso no se puede verificar sin un QA humano.
6. **Timer de purga periódica — YA INSTALADO Y PROBADO en el servidor**
   (`scoutcuts-purga.timer`/`.service`, corre a las 04:00 UTC +/- 10 min).
   Antes solo se purgaba al llegar una subida nueva; con tráfico bajo, un
   video podía quedar mucho más de `max_edad_horas` sin que nadie lo
   notara — riesgo de privacidad real (menores de edad involucrados).
   Verificado con `systemctl start scoutcuts-purga.service` manual (exit 0,
   `status=0/SUCCESS` en `journalctl`). **2026-11-04 (tarde): `Almacen.purgar()`
   gano `max_edad_revision_horas` (default 168h/7 dias, env
   `SCOUTCUTS_MAX_EDAD_REVISION_HORAS`), que da gracia extendida SOLO a
   trabajos en `PENDIENTE_REVISION` antes de que la purga de privacidad los
   borre. Motivo: un video de defensa/pitcheo/catcher subido por la PWA cae
   hoy en ese estado (ver punto 7) y se borraria en 24h sin que nadie lo
   revisara.**
7. **Deteccion automatica de defensa — MODELO PEQUENO INCREMENTAL, conectado
   a su propia zona web de entrenamiento (2026-11-04/05), AUN SIN DESPLEGAR
   AL SERVIDOR.**
   `src/cortador/defensa_ml.py`: cada vez que una persona marca un video con
   `cortador defensa` (manifiesto `.defensa.json` -> 6 repeticiones), el
   comando extrae 3 numeros por repeticion (duracion, fuerza del pico de
   movimiento, hacia que lado del encuadre) y los SUMA a un dataset
   acumulado en `modelos/dataset_defensa.json` (nunca el video ni un
   fotograma -- se puede borrar el video de inmediato despues sin perder
   nada que el modelo necesite, compatible con la regla de borrado
   automatico por menores de edad). Con al menos 1 ejemplo de las 3
   categorias (adelante/derecha/izquierda) calibra `modelo_defensa.json`
   (medias y desviaciones por categoria, sin redes neuronales ni
   dependencias pesadas: con 1-2 videos de dato, algo mas complejo
   memorizaria ruido en vez de aprender un patron). El modelo mejora con
   cada entrega nueva porque el dataset se acumula, nunca se reemplaza.
   Para apagarlo en una entrega puntual: `cortador defensa ... --sin-entrenar`.
   Si el entrenamiento falla por cualquier razon, la exportacion del video
   al cliente sigue funcionando igual -- nunca se bloquea una entrega por
   un fallo de aprendizaje.
   **Medicion real y honesta, no un numero inventado:** calibrado con el
   UNICO video marcado que existe (`Video/Luis Abreu/S1440022.MP4`, 6
   repeticiones), el modelo clasifica bien "derecha" e "izquierda" (4/4)
   pero confunde "adelante" con "izquierda" en 2/4 casos -- y en esos 2
   errores la confianza que devuelve es baja (0.20 y 0.39) contra 0.55-0.76
   en los aciertos, que es el comportamiento buscado: dudar cuando duda, en
   vez de inventar una categoria segura que no lo es. Con 1 video no hay
   patron generalizable todavia; mejorara solo con mas videos marcados.
   21 pruebas (`tests/test_defensa_ml.py`, `tests/servidor/test_entrenamiento.py`,
   `tests/servidor/test_api_entrenamiento.py`), incluyendo pipelines
   completos contra video real sintetico (OpenCV genera un video con
   movimiento real, se extraen caracteristicas, se calibra, y se clasifica
   un video nunca visto por el modelo) y un flujo HTTP de punta a punta
   (subir -> marcar -> entrenar -> feedback -> borrado del video). Mas 2
   pruebas en `tests/test_defensa.py` para la integracion con el comando CLI.
   **NUEVO: zona web de entrenamiento `scoutcuts.com/entrenamiento`**
   (pedido explicito del usuario: "subelo a la web para que el QA pruebe y
   lo entrene... y que el modelo le envie los feedbacks ahi mismo"). Flujo:
   el QA sube un video de practica, lo marca jugada por jugada en el propio
   navegador (sin exponer JSON ni rutas), cada marca se entrena al instante
   y el QA ve de inmediato si el modelo coincidio o no con su categoria y
   con cuanta confianza -- el video se borra automaticamente en el mismo
   momento en que se entrena, nunca despues.
   Aislamiento total de produccion real, por diseno (preferencia explicita
   del usuario de separar sandbox de integracion real): token propio
   `SCOUTCUTS_TOKEN_ENTRENAMIENTO` (nunca el `SCOUTCUTS_TOKEN_QA` de
   produccion -- probado que uno no abre al otro), carpeta propia
   `SCOUTCUTS_ENTRENAMIENTO` (default `datos/entrenamiento_qa`, nunca
   `datos/trabajos`), y dataset/modelo propios dentro de esa carpeta
   (nunca `modelos/dataset_defensa.json` de produccion -- mezclarlos
   contaminaria el modelo real con practicas de QA). Nuevo modulo
   `src/cortador/servidor/entrenamiento.py` (`ZonaEntrenamiento`): sube,
   valida, entrena con UNA repeticion a la vez (a diferencia del manifiesto
   de entrega al cliente, que exige el paquete 2+2+2 completo), evalua la
   propia jugada que se acaba de aprender para dar feedback honesto, borra
   el video, y limpia videos de practica huerfanos tras 24h si el QA nunca
   completo el marcado. Endpoints nuevos en `api.py`:
   `GET /v1/entrenamiento/modelo`, `POST /v1/entrenamiento/videos`,
   `POST /v1/entrenamiento/videos/{id}/entrenar` -- solo se registran si
   `SCOUTCUTS_TOKEN_ENTRENAMIENTO` esta configurado; sin el, estas rutas no
   existen (404), la produccion real queda exactamente igual. Frontend
   nuevo `web/entrenamiento/` (HTML/JS vanilla, mismo estilo que la PWA):
   login por codigo, reproductor de video con botones "marcar inicio"/
   "marcar tiro", categoria, lista de jugadas marcadas, boton de entrenar,
   y tarjeta de feedback en lenguaje simple ("el modelo coincidio" / "el
   modelo creyo que era X, ya aprendio de tu correccion") -- nunca JSON
   crudo, nunca confianza numerica sin traducir. `nginx-scoutcuts.conf`
   reenvia `/v1/entrenamiento/*` al mismo backend bajo el mismo origen que
   `scoutcuts.com`; `desplegar.sh` genera `SCOUTCUTS_TOKEN_ENTRENAMIENTO`
   la primera vez (igual que el token QA) y crea
   `$DATOS/entrenamiento_qa`.
   PENDIENTE REAL: nada de esto se ha desplegado al servidor todavia (todo
   probado localmente, 311 pruebas en verde); falta publicar
   `web/entrenamiento/index.html` como ruta real en el servidor (el script
   de despliegue ya publica toda la carpeta `web/`, asi que
   `scoutcuts.com/entrenamiento/` deberia funcionar en el siguiente
   despliegue sin cambios adicionales, pero no se ha verificado en vivo);
   no esta conectado al bot de Telegram (no hace falta, es flujo web);
   pitcheo/catcher siguen fuera por falta de ejemplos marcados (ver punto
   8); no se ha medido la huella real de memoria del backend con la zona de
   entrenamiento activa en el VPS de 950MB.
8. **Pitcheo y catcher — SIGUE SIN EXISTIR.** Ni categorias definidas, ni
   reglas de que cuenta como jugada completa, ni un solo ejemplo marcado:
   el enfoque de arriba (extraer numeros, nunca guardar el video) se podria
   aplicar igual aqui en cuanto haya 1 ejemplo marcado de cada categoria,
   pero no hay ninguno. En el servidor solo existen 3 perfiles de camara
   manuales ligados a un video especifico (`academia_video1.json`,
   `axel_img_0682.json`, `luis_abreu_s1440015.json`).
   Antes de construir nada de esto hace falta que el cliente defina:
   cuantos clips por entrega, que cuenta como jugada completa, desde que
   angulo de camara se grabara cada una. Sin eso, cualquier deteccion
   automatica que se escriba estaria adivinando el
   criterio del cliente.

## Documentos relacionados

En el proyecto local y copiados al servidor bajo `/opt/cortador-control/docs/`:

- `SERVIDOR_CONTROL.md`: reducido a un puntero hacia este documento (se
  decidió mantener un solo documento de relevo sincronizado en vez de dos
  que podían desincronizarse).
- `ACCESO_DESARROLLADOR.md`: **NUEVO (2026-11-04).** Acceso root completo al
  servidor para un segundo desarrollador de confianza, con GitHub como
  fuente de verdad del codigo. Distinto del acceso restringido de abajo.
- `TELEGRAM_BOT.md`: cómo registrar scouts, configurar el token del bot,
  límites reales de Telegram (20 MB descarga / 50 MB subida) y por qué esta
  versión no usa un LLM local.
- `ACCESO_QA_SSH.md`: usuario restringido del QA.
- `DESARROLLO_REMOTO.md`: snapshot Git editable para el QA, separado de producción.
- `ACCESO_MOVIL.md`: decisión PWA/servidor y benchmarks.
- `ENTREGA_QA.md`, `ANALISIS_QA.md`, `README.md`, `SIGUIENTE.md`, `PROBAR.md`, `BITACORA.md`.
- `src/cortador/defensa_ml.py`, `modelos/dataset_defensa.json`,
  `modelos/modelo_defensa.json`: modelo pequeno incremental de defensa
  (ver punto 7 de "Lo que falta"). Versionados en git por decision
  explicita del usuario: son JSON sin ningun dato de video.
- `despliegue/nginx-scoutcuts.conf` (incluye `limit_req_zone`/`limit_conn_zone`
  por IP en `/v1/trabajos`), `despliegue/nginx-scoutcuts-tls.conf`,
  `despliegue/scoutcuts.service` (fija `TMPDIR` a disco real, no a tmpfs),
  `despliegue/desplegar.sh`, `despliegue/verificar-despliegue.sh`,
  `despliegue/scoutcuts-purga.service`, `despliegue/scoutcuts-purga.timer`,
  `despliegue/scoutcuts-monitor.service`, `despliegue/scoutcuts-monitor.timer`,
  `despliegue/monitor-salud.sh`, `despliegue/rotar-token-qa.sh`,
  `despliegue/limpiar-releases-viejas.sh`.

## Qué no hacer

- No leer o mostrar secretos de `/etc/cortador-control/app.env`.
- No abrir PostgreSQL a internet.
- No abrir 8010 en UFW; nginx es el único punto público.
- No ejecutar la API como root.
- No usar varias colas/trabajadores en esta VPS de un núcleo.
- No conservar videos indefinidamente.
- No llamar "validado" a un candidato que no revisó una persona.
- No confundir `/opt/cortador-control/dev/cortador-turnos` (sandbox del QA)
  con `/opt/cortador-control/app` (producción real): son árboles distintos
  a propósito.
- No borrar cambios locales ni asumir que Git contiene todo.
- No hacer commit o push sin permiso del propietario.
