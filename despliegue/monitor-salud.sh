#!/usr/bin/env bash
# ScoutCuts — monitoreo periodico de salud, con alerta por Telegram al admin.
#
# Por que existe: scoutcuts.service tiene Restart=on-failure, asi que systemd
# lo reinicia solo ante un crash. El problema real es el "Restart loop"
# silencioso (el proceso cae, systemd lo levanta, vuelve a caer, y asi
# indefinidamente) o un fallo de nginx/TLS/DNS que systemd ni ve porque el
# proceso de la API sigue "activo" aunque nadie pueda llegar a el desde
# fuera. Sin este timer, nadie se entera hasta que un scout avisa que la
# web no carga.
#
# Que revisa, en orden de lo mas al interior a lo mas externo (asi el
# mensaje de alerta ya dice donde esta el problema sin tener que adivinar):
#   1. systemctl is-active scoutcuts   (el proceso)
#   2. systemctl is-active nginx       (el proxy/TLS)
#   3. curl a $API_SALUD (por defecto https://api.scoutcuts.com/salud,
#      la ruta PUBLICA real, no loopback: as{i tambien detecta un DNS o
#      certificado roto, que loopback nunca veria)
#
# Alerta solo en la TRANSICION de estado (ok -> fallo, o fallo -> ok), nunca
# en cada corrida: con el timer cada 5 minutos, alertar en cada tick
# inundaria el chat del admin y entrenaria a ignorar los avisos. El estado
# anterior se guarda en un archivo de texto plano (ok/fallo), no en una base
# de datos: es deliberadamente simple para un VPS de 1 nucleo.
#
# Variables de entorno (todas con default razonable salvo el token):
#   API_SALUD                 URL de /salud a probar (default produccion real)
#   ESTADO_ARCHIVO             donde guardar el ultimo estado conocido
#   SCOUTCUTS_TELEGRAM_BOT_TOKEN  reusa el MISMO bot del canal de scouts
#   SCOUTCUTS_TELEGRAM_ADMIN_ID   chat_id del administrador (NO es un scout)
#
# Sin token o sin admin id configurados, el script sigue funcionando: deja
# constancia del fallo en el log de systemd (journalctl -u scoutcuts-monitor)
# con prioridad "err", para que al menos quede un rastro revisable a mano.
set -uo pipefail

API_SALUD=${API_SALUD:-https://api.scoutcuts.com/salud}
ESTADO_ARCHIVO=${ESTADO_ARCHIVO:-/opt/cortador-control/datos/monitor_estado}
TOKEN=${SCOUTCUTS_TELEGRAM_BOT_TOKEN:-}
ADMIN_ID=${SCOUTCUTS_TELEGRAM_ADMIN_ID:-}

avisar() {  # avisar TEXTO
  local texto="$1"
  logger -t scoutcuts-monitor -p user.err "$texto" 2>/dev/null || true
  echo "$texto" >&2
  if [ -n "$TOKEN" ] && [ -n "$ADMIN_ID" ]; then
    curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
      --data-urlencode "chat_id=${ADMIN_ID}" \
      --data-urlencode "text=$texto" \
      -o /dev/null || logger -t scoutcuts-monitor -p user.err \
        "no se pudo enviar la alerta por Telegram (revisar token/admin_id)"
  fi
}

diagnostico() {
  local detalle=""
  if command -v systemctl >/dev/null 2>&1; then
    if [ "$(systemctl is-active scoutcuts 2>/dev/null)" != "active" ]; then
      detalle="${detalle}scoutcuts.service no esta activo. "
    fi
    if [ "$(systemctl is-active nginx 2>/dev/null)" != "active" ]; then
      detalle="${detalle}nginx no esta activo. "
    fi
  fi
  local code
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "$API_SALUD" 2>/dev/null)
  if [ "$code" != "200" ]; then
    detalle="${detalle}$API_SALUD respondio '$code' (se esperaba 200). "
  fi
  printf '%s' "$detalle"
}

DETALLE=$(diagnostico)
ESTADO_ANTERIOR="desconocido"
[ -f "$ESTADO_ARCHIVO" ] && ESTADO_ANTERIOR=$(cat "$ESTADO_ARCHIVO")

if [ -n "$DETALLE" ]; then
  if [ "$ESTADO_ANTERIOR" != "fallo" ]; then
    avisar "ScoutCuts: problema detectado. $DETALLE Revisar con: ssh precios 'systemctl status scoutcuts nginx'"
  fi
  echo "fallo" > "$ESTADO_ARCHIVO"
  exit 1
else
  if [ "$ESTADO_ANTERIOR" = "fallo" ]; then
    avisar "ScoutCuts: recuperado. Todo responde con normalidad de nuevo."
  fi
  echo "ok" > "$ESTADO_ARCHIVO"
fi
