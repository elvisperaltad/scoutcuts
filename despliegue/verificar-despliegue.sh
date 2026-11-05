#!/usr/bin/env bash
# ScoutCuts — verificacion POST-despliegue desde fuera.
# Puede correrla cualquiera con curl. Necesita el token QA para las rutas con
# auth; pasalo por entorno, nunca en la linea de comandos compartida:
#   read -rs TOKEN; export TOKEN   # pega el token, Enter
#   bash verificar-despliegue.sh
#
# Los destinos tambien salen del entorno: API (la API) y SITIO (las paginas
# que sirve nginx), con produccion como valor por omision.
#
# A diferencia de un script informativo, este ACUMULA fallos y termina con
# exit 1 si algo no cumplio lo esperado. "Verificado" significa que el
# script dijo que todo paso, nunca que solo imprimio numeros.
set -uo pipefail

API=${API:-https://api.scoutcuts.com}
# El sitio (paginas servidas por nginx) y la API son dos origenes distintos y
# se configuran por separado: asi se puede apuntar la verificacion a un
# entorno de prueba sin tocar el otro.
SITIO=${SITIO:-https://scoutcuts.com}
FALLOS=0

code() { curl -s -o /dev/null -w "%{http_code}" "$@"; }

# Interprete para los parseos JSON, elegido una sola vez. No alcanza con
# `command -v`: en Windows suele haber un `python3` que esta en el PATH pero
# falla al ejecutarse (el stub de la Store), mientras el `python` de al lado
# es un 3.12 sano. Con el stub los parseos devolvian vacio en silencio y el
# E2E moria antes de llegar al borrado, asi que aqui se prueba EJECUTANDO
# cada candidato y comprobando que su salida llegue de vuelta.
PY_JSON=""
for _candidato in python3 python; do
  if [ "$("$_candidato" -c 'import json;print("ok")' 2>/dev/null)" = "ok" ]; then
    PY_JSON="$_candidato"
    break
  fi
done
if [ -z "$PY_JSON" ]; then
  echo "(sin python3/python utilizable: los parseos JSON van a quedar vacios)"
fi

json() {  # json PROGRAMA  -- lee JSON por stdin, imprime lo que pida PROGRAMA
  # Sin interprete valido no imprime nada: el llamador ve vacio y decide,
  # igual que cuando la respuesta no trae el campo.
  [ -n "$PY_JSON" ] || return 0
  "$PY_JSON" -c "$1" 2>/dev/null
}

esperar() {  # esperar DESCRIPCION ESPERADO OBTENIDO
  local desc="$1" esperado="$2" obtenido="$3"
  if [ "$esperado" = "$obtenido" ]; then
    printf '  OK   %-45s -> %s\n' "$desc" "$obtenido"
  else
    printf '  FAIL %-45s -> %s (se esperaba %s)\n' "$desc" "$obtenido" "$esperado"
    FALLOS=$((FALLOS + 1))
  fi
}

echo "== Sitio y API, sin autenticar =="
esperar "pagina raiz del sitio"        "200" "$(code "$SITIO/")"
esperar "api/salud (sin token)"        "200" "$(code "$API/salud")"
esperar "api POST /v1/trabajos s/token" "401" "$(code -X POST "$API/v1/trabajos")"

if [ -z "${TOKEN:-}" ]; then
  echo
  echo "TOKEN no definido: omito las pruebas autenticadas (subida, cola, descarga)."
  echo "Sin esas pruebas el despliegue NO queda verificado de punta a punta."
  FALLOS=$((FALLOS + 1))
else
  AUTH=(-H "Authorization: Bearer $TOKEN")

  echo
  echo "== Con token =="
  esperar "id inexistente -> 404" "404" \
    "$(code "${AUTH[@]}" "$API/v1/trabajos/00000000000000000000000000000000")"

  ORIGEN_MALO=$(curl -s -o /dev/null -D - -X OPTIONS "$API/v1/trabajos" \
      -H 'Origin: https://malicioso.net' \
      -H 'Access-Control-Request-Method: POST' | tr -d '\r' | \
      awk -F': ' 'tolower($1)=="access-control-allow-origin"{print $2}')
  if [ -z "$ORIGEN_MALO" ]; then
    echo "  OK   CORS preflight origen malo                   -> vacio"
  else
    echo "  FAIL CORS preflight origen malo                   -> $ORIGEN_MALO (se esperaba vacio)"
    FALLOS=$((FALLOS + 1))
  fi

  echo
  echo "== E2E real: subir un video minimo, esperar, descargar =="
  TMP=$(mktemp -d)
  limpiar() {
    # Red de seguridad, no el camino normal: el borrado que de verdad se
    # verifica es el `esperar` de mas abajo. Esta corre cuando el script se
    # va por una salida que no pasa por ahi (timeout de la cola, error,
    # Ctrl-C) y solo si quedo una sonda viva. Best-effort a proposito: no
    # suma fallos ni imprime nada -- ni el codigo ni, por supuesto, el
    # token, que viaja en el header real igual que en el resto del script.
    # Un 409 aqui (trabajo todavia en la cola) es aceptable: la sonda nacio
    # marcada `verificacion`, asi que la purga se la lleva a las 24h y no
    # con la gracia de 7 dias del material de un scout. Con --max-time para
    # que una API colgada no deje el script (ni el Ctrl-C) esperando: es
    # best-effort, y si no alcanza queda la purga de las 24h.
    if [ -n "${ID:-}" ]; then
      curl -s --max-time 10 -o /dev/null -X DELETE "${AUTH[@]}" \
        "$API/v1/trabajos/$ID" || true
      ID=""
    fi
    if [ -n "${TMP:-}" ]; then
      rm -rf "$TMP"
      TMP=""
    fi
  }
  # INT/TERM/HUP aparte de EXIT: bash no corre el trap EXIT cuando lo mata una
  # senal sin trap propio. HUP incluido porque se corre por ssh, donde cerrar
  # la sesion es la forma mas comun de matarlo. `limpiar` es idempotente
  # (vacia ID y TMP), asi que el EXIT que dispara este `exit` no repite el
  # borrado.
  trap limpiar EXIT
  trap 'limpiar; exit 130' INT TERM HUP
  # 2 segundos de color solido, suficiente para que ffprobe lo acepte como
  # video valido; no se espera que tenga swings.
  if command -v ffmpeg >/dev/null; then
    ffmpeg -loglevel error -f lavfi -i color=c=blue:s=320x240:d=2 \
      -c:v libx264 -y "$TMP/prueba.mp4" 2>/dev/null
  fi
  if [ -s "$TMP/prueba.mp4" ]; then
    # En Git Bash el curl que corre es el nativo de Windows y no entiende las
    # rutas POSIX de mktemp -d; con la conversion de MSYS desactivada el -F
    # falla al abrir el archivo. cygpath -w da la ruta que ese curl si abre.
    # En Linux no existe cygpath y la ruta queda tal cual.
    SONDA="$TMP/prueba.mp4"
    if command -v cygpath >/dev/null 2>&1; then
      SONDA=$(cygpath -w "$SONDA")
    fi
    # `verificacion=1` marca la sonda como material desechable: es el unico
    # material que la API acepta borrar por id (ver DELETE /v1/trabajos/{id}),
    # y el unico que la purga trata con la gracia corta de 24h.
    RESP=$(curl -s -X POST "$API/v1/trabajos?verificacion=1" "${AUTH[@]}" \
      -F "archivo=@$SONDA;type=video/mp4")
    ID=$(printf '%s' "$RESP" | json 'import sys,json;print(json.load(sys.stdin).get("id",""))')
    if [ -z "$ID" ]; then
      echo "  FAIL subida del video de prueba                  -> respuesta sin id: $RESP"
      FALLOS=$((FALLOS + 1))
    else
      echo "  OK   subida del video de prueba                  -> id=$ID"
      ESTADO=""
      for _ in $(seq 1 60); do
        CUERPO=$(curl -s "${AUTH[@]}" "$API/v1/trabajos/$ID")
        ESTADO=$(printf '%s' "$CUERPO" | json 'import sys,json;print(json.load(sys.stdin).get("estado",""))')
        [ "$ESTADO" = "listo" ] || [ "$ESTADO" = "error" ] || [ "$ESTADO" = "pendiente_revision" ] && break
        sleep 2
      done
      if [ "$ESTADO" = "listo" ] || [ "$ESTADO" = "pendiente_revision" ]; then
        echo "  OK   la cola termino el trabajo                  -> estado=$ESTADO"
        CODE_DESC=$(code "${AUTH[@]}" "$API/v1/trabajos/$ID/resultado")
        if [ "$ESTADO" = "listo" ]; then
          esperar "descarga del montaje"  "200" "$CODE_DESC"
        else
          echo "  INFO sin perfil de camara para 320x240, no se prueba la descarga (esperado en este video sintetico)"
        fi
      else
        echo "  FAIL la cola no termino a tiempo                 -> ultimo estado=$ESTADO"
        FALLOS=$((FALLOS + 1))
      fi
      # Ya fuera de la cola (en cualquiera de los tres estados terminales, el
      # de error incluido) la API acepta el borrado; antes responde 409. Esto
      # va con `esperar` y no con el trap: si la sonda no se puede borrar, el
      # despliegue NO queda verificado -- un borrado roto significa que cada
      # verificacion futura deja basura permanente en el disco de produccion.
      case "$ESTADO" in
        listo|pendiente_revision|error)
          CODE_BORRADO=$(code -X DELETE "${AUTH[@]}" "$API/v1/trabajos/$ID")
          esperar "borrado de la sonda de verificacion" "204" "$CODE_BORRADO"
          # Borrada de verdad: el trap ya no tiene nada que intentar.
          [ "$CODE_BORRADO" = "204" ] && ID=""
          ;;
      esac
    fi
  else
    echo "  (ffmpeg no disponible en esta maquina: omito el E2E de subida/descarga)"
  fi
fi

echo
if command -v systemctl >/dev/null 2>&1; then
  echo "== Timers auxiliares (solo si se corre dentro del servidor) =="
  for timer in scoutcuts-purga.timer scoutcuts-monitor.timer scoutcuts-respaldo.timer; do
    esperar "$timer activo" "active" "$(systemctl is-active "$timer" 2>/dev/null || echo inactive)"
  done
fi

echo
echo "== Zona de entrenamiento QA ($SITIO/entrenamiento) =="
esperar "pagina de entrenamiento"        "200" "$(code "$SITIO/entrenamiento/")"
esperar "entrenamiento sin token"        "401" "$(code "$API/v1/entrenamiento/disciplinas")"
esperar "entrenamiento con token QA (produccion, debe rechazar)" "401" \
  "$(code -H "Authorization: Bearer ${TOKEN:-}" "$API/v1/entrenamiento/disciplinas")"

if [ -z "${TOKEN_ENTRENAMIENTO:-}" ]; then
  echo
  echo "TOKEN_ENTRENAMIENTO no definido: omito las pruebas autenticadas de la zona de entrenamiento."
  echo "(no es TOKEN: son credenciales distintas y deliberadamente aisladas, ver CONTINUAR_SERVIDOR.md)"
else
  RESP_DISC=$(curl -s -H "Authorization: Bearer $TOKEN_ENTRENAMIENTO" "$API/v1/entrenamiento/disciplinas")
  N_DISC=$(printf '%s' "$RESP_DISC" | json 'import sys,json
try:
    print(len(json.load(sys.stdin).get("disciplinas", [])))
except Exception:
    print(0)')
  # Sin interprete el parseo sale vacio; aqui eso vale 0, asi la comparacion
  # numerica de abajo no recibe una cadena vacia.
  N_DISC=${N_DISC:-0}
  if [ "${N_DISC:-0}" -ge 4 ]; then
    echo "  OK   disciplinas registradas con token valido     -> $N_DISC"
  else
    echo "  FAIL disciplinas registradas con token valido     -> $N_DISC (se esperaban al menos 4)"
    FALLOS=$((FALLOS + 1))
  fi
  esperar "entrenamiento con token de produccion (debe rechazar)" "401" \
    "$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer ${TOKEN:-}" "$API/v1/entrenamiento/disciplinas")"
fi

echo
if [ "$FALLOS" -eq 0 ]; then
  echo "Despliegue verificado: todas las pruebas pasaron."
  exit 0
else
  echo "Despliegue NO verificado: $FALLOS prueba(s) fallaron."
  exit 1
fi
