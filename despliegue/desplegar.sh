#!/usr/bin/env bash
# ScoutCuts — despliegue. Lo ejecuta el dueño como root (ssh precios).
# scoutqa NO puede correrlo (sin sudo). No imprime secretos.
#
# Requisito previo (CONTINUAR_SERVIDOR.md): el codigo ya fue integrado en la
# estacion principal y la suite completa esta verde. Este script NO sustituye
# esa validacion: solo cablea y arranca el servicio.
#
# Uso:
#   SOURCE=/ruta/al/codigo/integrado  bash desplegar.sh
# donde SOURCE contiene src/, pyproject.toml, perfiles/, etc. (sin .venv/videos).
#
# Diseño de release versionada: cada corrida crea
# /opt/cortador-control/releases-app/<timestamp>, construye TODO ahi (venv
# incluido) y solo al final mueve el symlink /opt/cortador-control/app para
# que apunte a la release nueva. Así el servicio en marcha nunca ve una mezcla
# de código viejo y venv nuevo (o viceversa) mientras se despliega.

set -euo pipefail

BASE=/opt/cortador-control
RELEASES="$BASE/releases-app"
APP="$BASE/app"
DATOS="$BASE/datos"
# Carpeta del ZIP del instalador que entrega descargas.scoutcuts.com. Vive
# FUERA de las releases a proposito: el instalador se publica a mano (ver
# despliegue/publicar-instalador.sh) y no debe borrarse ni reemplazarse cada
# vez que se despliega codigo nuevo.
INSTALADORES="$BASE/instaladores"
ENVF=/etc/cortador-control/app.env
SRV=/etc/systemd/system/scoutcuts.service
SOURCE=${SOURCE:?Define SOURCE=/ruta/al/codigo/integrado y vuelve a correr}
UNIT_DRAFT=${UNIT_DRAFT:-"$(dirname "$0")/scoutcuts.service"}
NGINX_DRAFT=${NGINX_DRAFT:-"$(dirname "$0")/nginx-scoutcuts.conf"}

SELLO="$(date -u +%Y%m%d%H%M%S)"
RELEASE="$RELEASES/$SELLO"

echo "==> 1/12 Preparando release $SELLO (root:root, sin escritura para cortador)"
install -d -m 755 "$RELEASES"
install -d -o root -g root -m 755 "$RELEASE"
rsync -a \
  --exclude '.venv' --exclude '.git' --exclude 'dist' --exclude 'build' \
  --exclude 'DatosQA' --exclude '*.mp4' --exclude '*.mov' --exclude '*.m4v' \
  --exclude '*.avi' --exclude '__pycache__' \
  "$SOURCE"/ "$RELEASE"/
chown -R root:root "$RELEASE"
find "$RELEASE" -type d -exec chmod 755 {} +
find "$RELEASE" -type f -exec chmod 644 {} +

# perfiles/*.json esta en .gitignore a proposito (se regeneran en pruebas),
# pero eso ya causo un incidente real: SOURCE se pobló una vez sin ellos y
# todo video quedo "pendiente_revision" en silencio hasta que alguien se
# quejo (ver BITACORA.md). Abortar aqui en vez de desplegar sin perfiles.
if ! compgen -G "$RELEASE/perfiles/*.json" > /dev/null; then
  echo "    No hay ningun perfil de camara en $RELEASE/perfiles/*.json." >&2
  echo "    Sin un perfil compatible, TODO video cae en pendiente_revision." >&2
  echo "    Copia los perfiles actuales a SOURCE/perfiles/ y vuelve a correr." >&2
  exit 1
fi
echo "    Perfiles encontrados: $(ls "$RELEASE"/perfiles/*.json | wc -l)"

echo "==> 2/12 Creando venv e instalando .[servidor] (propiedad root, de solo lectura para cortador)"
python3 -m venv "$RELEASE/.venv"
"$RELEASE/.venv/bin/pip" install --upgrade pip >/dev/null
"$RELEASE/.venv/bin/pip" install -e "$RELEASE[servidor]"
chown -R root:root "$RELEASE/.venv"
# El venv debe poder EJECUTARSE por cortador pero no escribirse: 755/644 ya
# lo permite para "otros"; lo restringimos a root:cortador y 750/640 para
# que ningun otro usuario del sistema pueda leerlo.
chgrp -R cortador "$RELEASE" "$RELEASE/.venv"
find "$RELEASE" -type d -exec chmod 750 {} +
find "$RELEASE" -type f -exec chmod 640 {} +
find "$RELEASE/.venv/bin" -type f -exec chmod 750 {} +

echo "==> 3/12 Variables en $ENVF (640 root:cortador; sin imprimir valores)"
install -d -o root -g root -m 755 /etc/cortador-control
touch "$ENVF"; chown root:cortador "$ENVF"; chmod 640 "$ENVF"
add_var() {  # add_var CLAVE VALOR  -> solo si la clave no existe aun
  local clave="$1" valor="$2"
  if ! grep -q "^${clave}=" "$ENVF"; then
    printf '%s=%s\n' "$clave" "$valor" >> "$ENVF"
    echo "    + $clave agregada"
  else
    echo "    = $clave ya existe (no la toco)"
  fi
}
# Token QA: largo y aleatorio, generado en el servidor, nunca por chat.
if ! grep -q '^SCOUTCUTS_TOKEN_QA=' "$ENVF"; then
  printf 'SCOUTCUTS_TOKEN_QA=%s\n' "$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')" >> "$ENVF"
  echo "    + SCOUTCUTS_TOKEN_QA generada (no se imprime)"
else
  echo "    = SCOUTCUTS_TOKEN_QA ya existe (no la toco)"
fi
add_var SCOUTCUTS_DATOS        "$DATOS"
add_var SCOUTCUTS_QA            "$DATOS/qa"
add_var SCOUTCUTS_PERFILES     "$APP/perfiles"
add_var SCOUTCUTS_ENTREGA_NGINX 1
# Token de entrenamiento: separado del token QA de produccion a proposito
# (ver CONTINUAR_SERVIDOR.md, punto 7). Si no se define, la zona
# /entrenamiento simplemente no registra sus rutas en la API (404), nunca
# rompe el arranque del servicio.
if ! grep -q '^SCOUTCUTS_TOKEN_ENTRENAMIENTO=' "$ENVF"; then
  printf 'SCOUTCUTS_TOKEN_ENTRENAMIENTO=%s\n' "$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')" >> "$ENVF"
  echo "    + SCOUTCUTS_TOKEN_ENTRENAMIENTO generada (no se imprime)"
else
  echo "    = SCOUTCUTS_TOKEN_ENTRENAMIENTO ya existe (no la toco)"
fi
add_var SCOUTCUTS_ENTRENAMIENTO "$DATOS/entrenamiento_qa"
# Carpeta del instalador. La API solo necesita comprobar que el ZIP existe
# antes de delegar el envio a nginx (X-Accel-Redirect); nunca lo abre.
add_var SCOUTCUTS_DESCARGAS    "$INSTALADORES"

echo "==> 4/12 Grupo de entrega y carpetas de datos"
getent group entrega >/dev/null || groupadd --system entrega
usermod -aG entrega cortador
usermod -aG entrega www-data
install -d -o cortador -g entrega -m 2750 "$DATOS"
install -d -o cortador -g entrega -m 2750 "$DATOS/trabajos"
install -d -o cortador -g cortador -m 750 "$DATOS/qa"
install -d -o cortador -g cortador -m 750 "$DATOS/entrenamiento_qa"
# TMPDIR del servicio (ver scoutcuts.service): particion real, nunca tmpfs,
# para que las partes de un multipart que Starlette desborda a disco no
# terminen en RAM. Debe existir antes de arrancar el servicio.
install -d -o cortador -g cortador -m 750 "$DATOS/tmp"
# 2750 = setgid: todo lo que cortador cree dentro hereda el grupo `entrega`,
# así nginx (www-data, miembro de `entrega`) puede atravesar y leer sin que
# el propio proceso de la API tenga que saberlo ni sin abrir a otros usuarios.
#
# Carpeta del instalador: dueño root (NO cortador). La API corre como
# cortador y lo único que hace con el ZIP es `is_file()`; con root:entrega
# 2750, cortador (miembro de `entrega`) puede atravesar la carpeta y mirar el
# archivo, www-data puede leerlo para enviarlo, y ni uno ni otro puede
# escribir ahí: el instalador solo entra por scp como root
# (publicar-instalador.sh). Así un fallo de la API nunca puede sustituir el
# ejecutable que descargan los clientes.
install -d -o root -g entrega -m 2750 "$INSTALADORES"

echo "==> 5/12 Activando la release (symlink atomico)"
ln -sfn "$RELEASE" "$APP.nuevo"
mv -T "$APP.nuevo" "$APP"

echo "==> 6/12 Instalando unidad systemd"
install -m 644 "$UNIT_DRAFT" "$SRV"
systemctl daemon-reload
systemd-analyze verify "$SRV"

echo "==> 7/12 Instalando timers auxiliares (purga de privacidad, monitoreo de salud, respaldo de entrenamiento)"
install -m 644 "$(dirname "$0")/scoutcuts-purga.service" /etc/systemd/system/scoutcuts-purga.service
install -m 644 "$(dirname "$0")/scoutcuts-purga.timer"   /etc/systemd/system/scoutcuts-purga.timer
install -m 644 "$(dirname "$0")/scoutcuts-monitor.service" /etc/systemd/system/scoutcuts-monitor.service
install -m 644 "$(dirname "$0")/scoutcuts-monitor.timer"   /etc/systemd/system/scoutcuts-monitor.timer
install -m 644 "$(dirname "$0")/scoutcuts-respaldo.service" /etc/systemd/system/scoutcuts-respaldo.service
install -m 644 "$(dirname "$0")/scoutcuts-respaldo.timer"   /etc/systemd/system/scoutcuts-respaldo.timer
systemctl daemon-reload
systemctl enable --now scoutcuts-purga.timer scoutcuts-monitor.timer scoutcuts-respaldo.timer

echo "==> 8/12 Arrancando (o reiniciando) el servicio con la release nueva"
systemctl enable scoutcuts.service
systemctl restart scoutcuts.service
sleep 2
systemctl --no-pager --full status scoutcuts.service | head -20

echo "==> 9/12 Prueba de salud local (loopback), bloqueante"
# Uvicorn no acepta conexiones en el instante en que systemd vuelve del
# restart del paso 8. En produccion tardo ~3 s y el unico curl que habia aqui
# (tras `sleep 2`) murio con exit 7 "connection refused": bajo set -e eso
# abortaba el despliegue entero antes de tocar nginx aunque el servicio habia
# arrancado sano. Se sondea /salud hasta SALUD_ESPERA segundos y se sale en
# cuanto conteste 200. El bucle solo observa: no reintenta nada ni reinicia el
# servicio (si de verdad no arranca, eso lo decide el operador con el journal).
SALUD_ESPERA=30
SALUD_URL=http://127.0.0.1:8010/salud
CODE=000
ESTADO="sin intento"
INICIO=$SECONDS
while :; do
  # `|| CURL_RC=$?` es lo que impide que un fallo transitorio de conexion
  # dispare set -e; curl igual escribe 000 en stdout cuando no logra conectar.
  CURL_RC=0
  CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$SALUD_URL") || CURL_RC=$?
  [ -n "$CODE" ] || CODE=000
  if [ "$CODE" = "200" ]; then
    break
  fi
  ESTADO="codigo $CODE (curl exit $CURL_RC)"
  if [ $((SECONDS - INICIO)) -ge "$SALUD_ESPERA" ]; then
    echo "    /salud local no llego a 200 en ${SALUD_ESPERA}s; ultimo intento: $ESTADO." >&2
    echo "    Abortando antes de tocar nginx. Revisa: journalctl -u scoutcuts.service -n 50" >&2
    exit 1
  fi
  sleep 1
done
echo "    /salud local = $CODE (listo tras $((SECONDS - INICIO))s de sondeo)"

echo "==> 10/12 Instalando nginx y recargando"
cp "$NGINX_DRAFT" /etc/nginx/sites-available/scoutcuts
nginx -t
systemctl reload nginx

echo "==> 11/12 Publicando los sitios estaticos (PWA y portada de descargas)"
if [ ! -d "$RELEASE/web" ]; then
  echo "    No hay carpeta web/ en la release; se deja /var/www/scoutcuts como estaba." >&2
else
  install -d -o root -g root -m 755 /var/www/scoutcuts
  rsync -a --delete \
    --exclude '.well-known' \
    "$RELEASE/web/" /var/www/scoutcuts/
  chown -R root:root /var/www/scoutcuts
  find /var/www/scoutcuts -type d -exec chmod 755 {} +
  find /var/www/scoutcuts -type f -exec chmod 644 {} +
  echo "    PWA publicada: $(find /var/www/scoutcuts -maxdepth 1 -type f | wc -l) archivos en la raiz"
fi
# Portada de descargas.scoutcuts.com: carpeta y vhost propios, separados de
# la PWA. Van en el mismo paso para no cambiar la numeracion de los 12 (y
# porque es la misma operacion: publicar HTML estatico desde la release).
# El --delete es seguro aqui porque este destino solo lo escribe este
# bloque; se excluye .well-known por si algun dia certbot usa este root.
if [ ! -d "$RELEASE/web-descargas" ]; then
  echo "    No hay carpeta web-descargas/ en la release; se deja /var/www/scoutcuts-descargas como estaba." >&2
else
  install -d -o root -g root -m 755 /var/www/scoutcuts-descargas
  rsync -a --delete \
    --exclude '.well-known' \
    "$RELEASE/web-descargas/" /var/www/scoutcuts-descargas/
  chown -R root:root /var/www/scoutcuts-descargas
  find /var/www/scoutcuts-descargas -type d -exec chmod 755 {} +
  find /var/www/scoutcuts-descargas -type f -exec chmod 644 {} +
  echo "    Portada de descargas publicada: $(find /var/www/scoutcuts-descargas -maxdepth 1 -type f | wc -l) archivos en la raiz"
fi
# Aviso (no error): el vhost de descargas ya responde, pero sin el ZIP la
# API contesta 503 con un mensaje para el cliente. Se publica aparte.
if [ ! -f "$INSTALADORES/CortadorTurnosQA-Portable.zip" ]; then
  echo "    Aviso: todavia no hay instalador en $INSTALADORES; la descarga respondera 'no disponible'." >&2
  echo "    Subelo desde tu equipo con: bash despliegue/publicar-instalador.sh" >&2
fi

echo "==> 12/12 Limpiando releases viejas (conserva las ultimas 5 + la activa)"
bash "$(dirname "$0")/limpiar-releases-viejas.sh" 5 || true

echo "Listo. Verifica desde fuera con: bash verificar-despliegue.sh"
echo "Releases anteriores en $RELEASES/ quedan para rollback manual (symlink)."