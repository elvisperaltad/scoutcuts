#!/usr/bin/env bash
# ScoutCuts — rotacion manual del token QA (SCOUTCUTS_TOKEN_QA).
#
# Por que existe (CONTINUAR_SERVIDOR.md, punto 3 pendiente): si el token
# Bearer estatico de la API HTTP se filtra (pegado por error en un chat, un
# log, un repositorio), hasta ahora habia que regenerarlo "a mano": editar
# el archivo, reiniciar el servicio, y confiar en no haberse equivocado.
# Este script automatiza esos pasos con una red de seguridad real: si el
# servicio no vuelve a responder 200 con el token nuevo, REVIERTE solo al
# token anterior en vez de dejar la API caida.
#
# Como el resto de scripts de este proyecto: nunca imprime el valor del
# token (ni el viejo ni el nuevo) en pantalla ni en el log de systemd.
#
# Uso en el servidor (como root):
#   bash despliegue/rotar-token-qa.sh
#
# Variables de entorno (para pruebas automatizadas; en produccion real se
# usan los defaults):
#   ENVF        ruta al archivo de variables (default /etc/cortador-control/app.env)
#   SERVICE     unidad systemd a reiniciar (default scoutcuts.service)
#   SALUD_URL   URL a probar tras el reinicio (default http://127.0.0.1:8010/salud)
set -euo pipefail

ENVF=${ENVF:-/etc/cortador-control/app.env}
SERVICE=${SERVICE:-scoutcuts.service}
SALUD_URL=${SALUD_URL:-http://127.0.0.1:8010/salud}

if [ ! -f "$ENVF" ]; then
  echo "No existe $ENVF; nada que rotar." >&2
  exit 1
fi

if ! grep -q '^SCOUTCUTS_TOKEN_QA=' "$ENVF"; then
  echo "$ENVF no tiene una linea SCOUTCUTS_TOKEN_QA=; nada que rotar." >&2
  exit 1
fi

SELLO="$(date -u +%Y%m%d%H%M%S)"
RESPALDO="${ENVF}.bak-${SELLO}"
cp -p "$ENVF" "$RESPALDO"
chmod 640 "$RESPALDO" 2>/dev/null || true

# No basta con `command -v python3`: en Windows puede existir como un stub
# roto de Microsoft Store que "existe" en el PATH pero falla al ejecutar
# (mensaje de instalacion en vez de Python real). Se prueba invocandolo de
# verdad, no solo su presencia.
PYTHON=""
for candidato in python3 python; do
  if "$candidato" -c 'import secrets' >/dev/null 2>&1; then
    PYTHON="$candidato"
    break
  fi
done
if [ -z "$PYTHON" ]; then
  echo "No se encontro un interprete Python funcional (python3/python)." >&2
  exit 1
fi
NUEVO=$("$PYTHON" -c 'import secrets;print(secrets.token_urlsafe(48))')

# Reemplaza solo la linea del token, preservando el resto del archivo tal
# cual (orden, comentarios, otras variables).
TMP="$(mktemp)"
awk -v nuevo="SCOUTCUTS_TOKEN_QA=$NUEVO" \
  '/^SCOUTCUTS_TOKEN_QA=/{print nuevo; next} {print}' "$ENVF" > "$TMP"
cat "$TMP" > "$ENVF"
rm -f "$TMP"
chmod 640 "$ENVF" 2>/dev/null || true

echo "==> Token rotado en $ENVF (el anterior quedo respaldado en $RESPALDO)."
echo "==> Reiniciando $SERVICE para que tome el token nuevo..."
systemctl restart "$SERVICE"
sleep 2

CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$SALUD_URL" 2>/dev/null || echo 000)
if [ "$CODE" != "200" ]; then
  echo "    $SALUD_URL respondio '$CODE' tras reiniciar (se esperaba 200)." >&2
  echo "    Revirtiendo al token anterior para no dejar la API caida..." >&2
  cp -p "$RESPALDO" "$ENVF"
  systemctl restart "$SERVICE" || true
  echo "    Token anterior restaurado. Revisa 'journalctl -u $SERVICE' antes de reintentar." >&2
  exit 1
fi

echo "Listo. El servicio responde 200 con el token nuevo."
echo "El token viejo sigue en $RESPALDO; borralo a mano cuando confirmes que todo sigue bien:"
echo "  rm $RESPALDO"
echo "Para usar el token nuevo (este script nunca lo imprime):"
echo "  TOKEN=\$(grep '^SCOUTCUTS_TOKEN_QA=' $ENVF | cut -d= -f2-); export TOKEN"
