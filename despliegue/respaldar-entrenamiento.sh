#!/usr/bin/env bash
# ScoutCuts — respaldo diario de los datasets/modelos entrenados por el QA.
#
# Por que existe: el modelo de defensa (modelos/dataset_defensa.json,
# modelo_defensa.json) vive en el repositorio de git y llega a cada release
# via rsync, asi que ya esta respaldado ahi. Los datasets que el QA entrena
# EN VIVO para bateo/pitcheo/catcher (ver cortador.servidor.entrenamiento)
# son distintos: se generan solo en este servidor, dentro de
# $SCOUTCUTS_ENTRENAMIENTO/modelos/, y nunca se copian a ningun otro lado.
# Sin este respaldo, un disco danado o un "rm -rf" por error borraria meses
# de trabajo de entrenamiento sin ninguna forma de recuperarlo.
#
# Que copia: solo los *.json de modelos/ (numeros, nunca video -- la carpeta
# de videos de practica NUNCA se toca ni se incluye aqui, siguen borrandose
# segun la regla de privacidad de siempre). Son archivos minusculos (unos
# pocos KB cada uno), asi que conservar varias copias no pesa nada en un
# disco de 23 GB.
#
# Guarda las ultimas N copias con fecha (una carpeta por dia que corrio) y
# borra las mas viejas -- proteccion contra borrado accidental o corrupcion,
# no contra la perdida total del disco (para eso haria falta copiar fuera
# del servidor, que no esta planteado todavia).
set -uo pipefail

RAIZ=${SCOUTCUTS_ENTRENAMIENTO:-}
CONSERVAR=${SCOUTCUTS_RESPALDOS_A_CONSERVAR:-30}

if [ -z "$RAIZ" ]; then
  logger -t scoutcuts-respaldo -p user.info "SCOUTCUTS_ENTRENAMIENTO no definida: no hay zona de entrenamiento que respaldar." 2>/dev/null
  exit 0
fi

ORIGEN="$RAIZ/modelos"
if [ ! -d "$ORIGEN" ] || [ -z "$(find "$ORIGEN" -maxdepth 1 -name '*.json' -print -quit 2>/dev/null)" ]; then
  logger -t scoutcuts-respaldo -p user.info "Nada que respaldar todavia en $ORIGEN." 2>/dev/null
  exit 0
fi

DESTINO_BASE="$RAIZ/respaldos"
SELLO="$(date -u +%Y%m%d%H%M%S)"
DESTINO="$DESTINO_BASE/$SELLO"

mkdir -p "$DESTINO"
if ! cp "$ORIGEN"/*.json "$DESTINO"/ 2>/dev/null; then
  logger -t scoutcuts-respaldo -p user.err "Fallo copiando $ORIGEN a $DESTINO." 2>/dev/null
  rmdir "$DESTINO" 2>/dev/null
  exit 1
fi

N_ARCHIVOS=$(find "$DESTINO" -maxdepth 1 -name '*.json' | wc -l)
logger -t scoutcuts-respaldo -p user.info "Respaldados $N_ARCHIVOS archivo(s) en $DESTINO." 2>/dev/null

# Conserva solo las ultimas $CONSERVAR carpetas de respaldo (orden por
# nombre = orden cronologico, gracias al sello YYYYMMDDHHMMSS).
if [ -d "$DESTINO_BASE" ]; then
  ls -1 "$DESTINO_BASE" | sort -r | tail -n "+$((CONSERVAR + 1))" | while read -r vieja; do
    rm -rf "$DESTINO_BASE/$vieja"
    logger -t scoutcuts-respaldo -p user.info "Respaldo viejo borrado: $vieja." 2>/dev/null
  done
fi
