#!/usr/bin/env bash
# ScoutCuts — limpieza de releases viejas en /opt/cortador-control/releases-app.
#
# Por que existe: cada despliegue de desplegar.sh crea una release nueva de
# ~318 MB (codigo + venv completo) y NUNCA borraba ninguna (documentado a
# proposito en CONTINUAR_SERVIDOR.md como "guarda TODAS las releases" para
# permitir rollback manual). En un VPS de 23 GB de disco total, con varios
# despliegues por dia durante desarrollo activo, eso agota el disco en
# semanas sin que nadie lo note hasta que algo empiece a fallar por falta
# de espacio -- un riesgo real de sostenibilidad del servidor, no solo
# prolijidad.
#
# Que hace: conserva las ULTIMAS N releases (por nombre, que son timestamps
# ordenables: 20261104153146) y borra el resto. SIEMPRE conserva la release
# actualmente activa (el destino real del symlink $APP), incluso si por
# alguna razon quedara fuera de las ultimas N -- nunca se borra lo que esta
# sirviendo produccion en este momento, sin excepcion.
#
# Uso (normalmente invocado al final de desplegar.sh, no a mano):
#   bash limpiar-releases-viejas.sh [N]
# N por defecto: 5. Variables para pruebas: RELEASES, APP.
set -euo pipefail

CONSERVAR=${1:-5}
RELEASES=${RELEASES:-/opt/cortador-control/releases-app}
APP=${APP:-/opt/cortador-control/app}

if [ ! -d "$RELEASES" ]; then
  echo "No existe $RELEASES; nada que limpiar." >&2
  exit 0
fi

ACTIVA=""
if [ -L "$APP" ]; then
  ACTIVA="$(basename "$(readlink -f "$APP")")"
fi

# Orden lexicografico = orden cronologico porque el sello es YYYYMMDDHHMMSS.
mapfile -t TODAS < <(find "$RELEASES" -maxdepth 1 -mindepth 1 -type d -printf '%f\n' | sort)

TOTAL=${#TODAS[@]}
if [ "$TOTAL" -le "$CONSERVAR" ]; then
  echo "Hay $TOTAL release(s), <= $CONSERVAR a conservar. Nada que borrar."
  exit 0
fi

A_CONSERVAR=("${TODAS[@]: -$CONSERVAR}")
BORRADAS=0
for nombre in "${TODAS[@]}"; do
  conservar=0
  for c in "${A_CONSERVAR[@]}"; do
    [ "$nombre" = "$c" ] && conservar=1 && break
  done
  if [ "$nombre" = "$ACTIVA" ]; then
    conservar=1
  fi
  if [ "$conservar" -eq 0 ]; then
    echo "Borrando release vieja: $nombre"
    rm -rf "${RELEASES:?}/${nombre:?}"
    BORRADAS=$((BORRADAS + 1))
  fi
done

echo "Listo. $BORRADAS release(s) borrada(s); $((TOTAL - BORRADAS)) conservada(s)."
