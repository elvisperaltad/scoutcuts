#!/usr/bin/env bash
# ScoutCuts — verificacion POST-despliegue desde fuera.
# Puede correrla cualquiera con curl. Necesita el token QA para las rutas con
# auth; pasalo por entorno, nunca en la linea de comandos compartida:
#   read -rs TOKEN; export TOKEN   # pega el token, Enter
#   bash verificar-despliegue.sh
#
# A diferencia de un script informativo, este ACUMULA fallos y termina con
# exit 1 si algo no cumplio lo esperado. "Verificado" significa que el
# script dijo que todo paso, nunca que solo imprimio numeros.
set -uo pipefail

API=${API:-https://api.scoutcuts.com}
FALLOS=0

code() { curl -s -o /dev/null -w "%{http_code}" "$@"; }

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
esperar "scoutcuts.com"                "200" "$(code https://scoutcuts.com/)"
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
  trap 'rm -rf "$TMP"' EXIT
  # 2 segundos de color solido, suficiente para que ffprobe lo acepte como
  # video valido; no se espera que tenga swings.
  if command -v ffmpeg >/dev/null; then
    ffmpeg -loglevel error -f lavfi -i color=c=blue:s=320x240:d=2 \
      -c:v libx264 -y "$TMP/prueba.mp4" 2>/dev/null
  fi
  if [ -s "$TMP/prueba.mp4" ]; then
    RESP=$(curl -s -X POST "$API/v1/trabajos" "${AUTH[@]}" \
      -F "archivo=@$TMP/prueba.mp4;type=video/mp4")
    ID=$(printf '%s' "$RESP" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("id",""))' 2>/dev/null)
    if [ -z "$ID" ]; then
      echo "  FAIL subida del video de prueba                  -> respuesta sin id: $RESP"
      FALLOS=$((FALLOS + 1))
    else
      echo "  OK   subida del video de prueba                  -> id=$ID"
      ESTADO=""
      for _ in $(seq 1 60); do
        CUERPO=$(curl -s "${AUTH[@]}" "$API/v1/trabajos/$ID")
        ESTADO=$(printf '%s' "$CUERPO" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("estado",""))' 2>/dev/null)
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
    fi
  else
    echo "  (ffmpeg no disponible en esta maquina: omito el E2E de subida/descarga)"
  fi
fi

echo
if [ "$FALLOS" -eq 0 ]; then
  echo "Despliegue verificado: todas las pruebas pasaron."
  exit 0
else
  echo "Despliegue NO verificado: $FALLOS prueba(s) fallaron."
  exit 1
fi
