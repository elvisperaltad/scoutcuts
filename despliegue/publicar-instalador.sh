#!/usr/bin/env bash
# ScoutCuts — publicacion del instalador en el servidor de descargas.
#
# Se ejecuta EN TU EQUIPO (Windows con Git Bash, o Linux/mac), nunca en el
# servidor: el ZIP se construye aqui (tools/build_portable_runtime.py) y hay
# que subirlo. Lo unico que queda en el servidor es el ZIP verificado.
#
# Por que existe: el instalador pesa ~231 MiB y lo descargan clientes. Si se
# sube "a mano" con scp y la conexion se corta a la mitad, el archivo que
# queda en la carpeta de entrega es un ZIP truncado -- y cada cliente que lo
# baje se llevara un archivo roto sin que nadie se entere. Este script evita
# eso de tres formas:
#   1. Sube SIEMPRE a un nombre temporal (<nombre>.subiendo). El archivo
#      bueno que ya esta publicado no se toca hasta el ultimo segundo.
#   2. Verifica el SHA-256 EN EL SERVIDOR (no solo en local: lo que importa
#      es lo que llego, no lo que se mando).
#   3. Solo si el hash coincide hace el `mv` final, que al ser dentro de la
#      misma carpeta es atomico: ninguna descarga en curso ve un archivo a
#      medio escribir.
# Si el hash NO coincide, borra el temporal y deja el instalador anterior
# intacto.
#
# Uso tipico (desde la raiz del repositorio):
#   bash despliegue/publicar-instalador.sh
#
# Variables de entorno (todas con default razonable):
#   DESTINO         host ssh del servidor            (default precios)
#   DIR_REMOTO      carpeta de entrega en el servidor (default /opt/cortador-control/instaladores)
#   ZIP             ruta local del ZIP               (default dist/CortadorTurnosQA-Portable.zip)
#   SHA             ruta local del checksum          (default "$ZIP.sha256")
#   LIMPIAR_PARCIAL 1 = descarta el temporal remoto y sube desde cero
#
# Este script no maneja ni imprime ningun secreto: la autenticacion es la de
# tu ssh (clave/agente) y no se pasan tokens ni contrasenas por linea de
# comandos ni por el entorno remoto.
set -euo pipefail

DESTINO=${DESTINO:-precios}
DIR_REMOTO=${DIR_REMOTO:-/opt/cortador-control/instaladores}
# El nombre remoto NO es configurable por casualidad: tiene que ser igual a
# NOMBRE_INSTALADOR en src/cortador/servidor/api.py y al filename fijo del
# Content-Disposition en despliegue/nginx-scoutcuts.conf. Si cambia aqui y
# no alla, la descarga responde 503 ("no disponible").
NOMBRE=CortadorTurnosQA-Portable.zip
ZIP=${ZIP:-dist/$NOMBRE}
SHA=${SHA:-$ZIP.sha256}
SSH=${SSH:-ssh}
LIMPIAR_PARCIAL=${LIMPIAR_PARCIAL:-0}

TEMPORAL="$NOMBRE.subiendo"

# ---------------------------------------------------------------- 1/5 local
echo "==> 1/5 Comprobando el ZIP y su checksum en este equipo"
if [ ! -f "$ZIP" ]; then
  echo "    No existe el ZIP: $ZIP" >&2
  echo "    Construyelo primero (python tools/build_portable_runtime.py) o define ZIP=..." >&2
  exit 1
fi
if [ ! -s "$ZIP" ]; then
  echo "    El ZIP $ZIP esta vacio; no se publica nada." >&2
  exit 1
fi
if [ ! -f "$SHA" ]; then
  echo "    Falta el checksum: $SHA" >&2
  echo "    Sin el no hay forma de comprobar en el servidor que el ZIP llego entero." >&2
  echo "    Generalo con: sha256sum '$ZIP' > '$SHA'" >&2
  exit 1
fi

# Lectura robusta del hash esperado. El archivo .sha256 puede venir de
# sitios muy distintos y todos "funcionan" para un humano pero no para un
# `cut -d' ' -f1` ingenuo:
#   - sha256sum de Git Bash:  "<hash>  dist/x.zip"  (dos espacios)
#   - modo binario:           "<hash> *dist\x.zip"  (asterisco, backslashes)
#   - redirigido con `>` desde PowerShell: el MISMO texto pero codificado en
#     UTF-16LE, es decir con un byte 0x00 entre cada caracter y un BOM
#     delante. Un grep normal ahi no encuentra absolutamente nada.
#   - editado en Notepad: CRLF al final de la linea.
# Por eso se limpian NUL/CR/BOM y luego se extrae SOLO el hash (64 hex),
# ignorando el nombre de archivo que venga detras (puede ser otro: lo que
# se compara es el contenido, no como se llamaba al generarlo).
leer_hash_esperado() {
  local archivo="$1" limpio hash
  # Se borran NUL y CR (UTF-16 y CRLF) y los bytes de los dos BOM posibles
  # (EF BB BF de UTF-8, FF FE de UTF-16LE). Borrarlos "a lo bruto" es seguro
  # en un archivo que solo deberia contener hex, espacios y un nombre.
  limpio=$(tr -d '\000\r\357\273\277\377\376' < "$archivo" | sed -e 's/^[[:space:]]*//')
  # Primero anclado al inicio de linea (formato sha256sum real). El ancla
  # evita confundir el hash con un nombre de archivo que pareciera hex.
  # LC_ALL=C: en un archivo que venia en UTF-16 pueden quedar bytes que no
  # son UTF-8 valido, y grep en una locale UTF-8 se niega a casar esas lineas.
  hash=$(printf '%s\n' "$limpio" | LC_ALL=C grep -oiE '^[0-9a-f]{64}' | head -n 1 || true)
  if [ -z "$hash" ]; then
    # Formatos raros (p.ej. la tabla de Get-FileHash, que pone el hash en la
    # segunda columna): se acepta el primer bloque de 64 hex suelto, siempre
    # que no sea parte de una cadena hex mas larga.
    hash=$(printf '%s\n' "$limpio" |
             LC_ALL=C grep -oiE '(^|[^0-9a-fA-F])[0-9a-f]{64}([^0-9a-fA-F]|$)' |
             LC_ALL=C grep -oiE '[0-9a-f]{64}' | head -n 1 || true)
  fi
  printf '%s' "$hash" | tr '[:upper:]' '[:lower:]'
}

ESPERADO=$(leer_hash_esperado "$SHA")
if [ ${#ESPERADO} -ne 64 ]; then
  echo "    No pude leer un SHA-256 valido (64 caracteres hex) de $SHA." >&2
  echo "    Regeneralo con: sha256sum '$ZIP' > '$SHA'" >&2
  exit 1
fi
echo "    Checksum esperado leido de $SHA (SHA-256, 64 hex)."

# Comprobacion local previa: si el .sha256 no corresponde a ESTE ZIP, mejor
# enterarse ahora que despues de subir 231 MiB.
HASH_LOCAL=""
if command -v sha256sum >/dev/null 2>&1; then
  HASH_LOCAL=$(sha256sum "$ZIP" | cut -d' ' -f1)
elif command -v shasum >/dev/null 2>&1; then
  HASH_LOCAL=$(shasum -a 256 "$ZIP" | cut -d' ' -f1)
elif command -v openssl >/dev/null 2>&1; then
  HASH_LOCAL=$(openssl dgst -sha256 "$ZIP" | awk '{print $NF}')
fi
HASH_LOCAL=$(printf '%s' "$HASH_LOCAL" | tr '[:upper:]' '[:lower:]')
if [ -z "$HASH_LOCAL" ]; then
  echo "    Aviso: sin sha256sum/shasum/openssl en este equipo, no puedo comprobar"
  echo "    el ZIP local. La verificacion en el servidor se hace igual."
elif [ "$HASH_LOCAL" != "$ESPERADO" ]; then
  echo "    El ZIP local NO coincide con su .sha256." >&2
  echo "    Reconstruye el ZIP o regenera el checksum antes de publicar." >&2
  exit 1
else
  echo "    ZIP local coincide con su checksum."
fi

TAM=$(wc -c < "$ZIP" | tr -d '[:space:]')
echo "    Archivo: $ZIP ($TAM bytes)"

# ------------------------------------------------------------- 2/5 servidor
# Toda orden remota se manda por stdin a `bash -s`, con los valores pasados
# como variables de entorno ya citadas con printf %q: nunca se pega una ruta
# dentro de una cadena de shell remota.
remoto() {
  "$SSH" "$DESTINO" \
    "DIR=$(printf '%q' "$DIR_REMOTO") \
     NOMBRE=$(printf '%q' "$NOMBRE") \
     TEMPORAL=$(printf '%q' "$TEMPORAL") \
     ESPERADO=$(printf '%q' "$ESPERADO") \
     TAM=$(printf '%q' "$TAM") \
     bash -s"
}

echo "==> 2/5 Comprobando el servidor ($DESTINO:$DIR_REMOTO)"
remoto <<'REMOTO'
set -euo pipefail
if [ ! -d "$DIR" ]; then
  echo "    No existe $DIR en el servidor." >&2
  echo "    Corre antes el despliegue (crea la carpeta root:entrega 2750)." >&2
  exit 1
fi
if [ ! -w "$DIR" ]; then
  echo "    Sin permiso de escritura en $DIR (hace falta entrar como root)." >&2
  exit 1
fi
if ! getent group entrega >/dev/null; then
  echo "    Falta el grupo 'entrega' en el servidor; corre el despliegue primero." >&2
  exit 1
fi
if ! command -v sha256sum >/dev/null 2>&1; then
  echo "    El servidor no tiene sha256sum: no puedo verificar la subida ahi." >&2
  exit 1
fi
# Espacio libre: descontando lo que ya haya subido de un intento anterior y
# con un 10% de margen (mas 1 GiB de aire). Nunca empezar una subida que va
# a llenar el disco de 23 GB del servidor.
parcial=0
if [ -f "$DIR/$TEMPORAL" ]; then
  parcial=$(stat -c %s "$DIR/$TEMPORAL" 2>/dev/null || echo 0)
fi
falta=$(( TAM - parcial ))
if [ "$falta" -lt 0 ]; then
  falta=0
fi
libre_kb=$(df -Pk "$DIR" 2>/dev/null | awk 'NR==2{print $4}')
case "$libre_kb" in
  ''|*[!0-9]*) libre_kb="" ;;   # df raro: mejor no inventarse un numero
esac
if [ -n "$libre_kb" ] && [ $(( libre_kb * 1024 )) -lt $(( falta + falta / 10 + 1073741824 )) ]; then
  echo "    Poco espacio libre en el disco del servidor para subir el instalador." >&2
  echo "    Libera espacio y vuelve a intentarlo (el intento parcial se conserva)." >&2
  exit 1
fi
if [ "$parcial" -gt 0 ]; then
  echo "    Hay una subida a medias de $parcial bytes; se intentara reanudar."
fi
if [ -f "$DIR/$NOMBRE" ]; then
  echo "    Ya hay un instalador publicado; no se toca hasta verificar el nuevo."
fi
REMOTO

if [ "$LIMPIAR_PARCIAL" = "1" ]; then
  echo "    LIMPIAR_PARCIAL=1: descartando el temporal remoto y subiendo desde cero."
  remoto <<'REMOTO'
set -euo pipefail
rm -f "$DIR/$TEMPORAL"
REMOTO
fi

# ---------------------------------------------------------------- 3/5 subir
echo "==> 3/5 Subiendo a $DIR_REMOTO/$TEMPORAL (el archivo publicado sigue intacto)"
# rsync si esta en los dos lados: reanuda una subida cortada en vez de
# empezar los 231 MiB otra vez. --inplace + --append-verify escriben sobre
# el temporal y comprueban que la parte que ya estaba coincide; si no
# coincide, rsync la reenvia. scp no sabe reanudar, asi que es el plan B.
USAR_RSYNC=0
# El </dev/null es importante: sin el, ssh se comeria el stdin del script.
if command -v rsync >/dev/null 2>&1 &&
   "$SSH" "$DESTINO" 'command -v rsync' >/dev/null 2>&1 </dev/null; then
  USAR_RSYNC=1
fi

if [ "$USAR_RSYNC" = "1" ]; then
  OPC_RSYNC=(-h --partial --inplace --progress)
  # --append-verify no existe en rsync muy viejos: solo se pasa si el rsync
  # local lo anuncia, para no morir con "unknown option". Se mira la ayuda en
  # una variable y no con un pipe a grep -q porque con `pipefail` ese pipe
  # devuelve error cuando grep corta a rsync (SIGPIPE) aunque si hubiera match.
  AYUDA_RSYNC=$(rsync --help 2>&1 || true)
  case "$AYUDA_RSYNC" in
    *--append-verify*) OPC_RSYNC+=(--append-verify) ;;
    *) echo "    (rsync sin --append-verify: la subida no reanuda, se reenvia completa)" ;;
  esac
  rsync "${OPC_RSYNC[@]}" -e "$SSH" "$ZIP" "$DESTINO:$DIR_REMOTO/$TEMPORAL"
else
  echo "    (sin rsync en ambos lados: se usa scp, que no puede reanudar)"
  scp -p "$ZIP" "$DESTINO:$DIR_REMOTO/$TEMPORAL"
fi

# ------------------------------------------------------------ 4/5 verificar
echo "==> 4/5 Verificando el SHA-256 en el servidor y publicando"
# El temporal solo se convierte en el archivo bueno si su hash coincide.
# Si no coincide se borra (metadatos parciales fuera) y el instalador
# anterior se queda publicado tal cual estaba.
remoto <<'REMOTO'
set -euo pipefail
cd "$DIR"
if [ ! -f "$TEMPORAL" ]; then
  echo "    No encuentro $DIR/$TEMPORAL tras la subida." >&2
  exit 1
fi
real=$(sha256sum "$TEMPORAL" | cut -d' ' -f1 | tr '[:upper:]' '[:lower:]')
if [ "$real" != "$ESPERADO" ]; then
  rm -f "$TEMPORAL"
  echo "    El archivo que llego NO coincide con el checksum esperado." >&2
  echo "    Se borro la subida incompleta; el instalador publicado no se toco." >&2
  echo "    Vuelve a correr el script (o con LIMPIAR_PARCIAL=1 si insiste)." >&2
  exit 1
fi
# Dueno root (ni la API ni nadie que no sea root puede reemplazarlo) y lectura
# solo para el grupo `entrega`, al que pertenece www-data: nginx lo envia,
# cortador solo puede comprobar que existe, el resto del sistema no lo ve.
chown root:entrega "$TEMPORAL"
chmod 640 "$TEMPORAL"
# Dentro de la misma carpeta, mv es un rename atomico: quien esta
# descargando en este momento sigue con el archivo viejo hasta terminar, y
# la siguiente peticion ya recibe el nuevo. Nunca existe un instante con un
# ZIP a medias publicado.
mv -f "$TEMPORAL" "$NOMBRE"
echo "    Publicado: $DIR/$NOMBRE ($(stat -c %s "$NOMBRE") bytes, $(stat -c '%U:%G %a' "$NOMBRE"))"
REMOTO

# ----------------------------------------------------------- 5/5 recordatorio
echo "==> 5/5 Listo"
echo "    Comprueba la portada:  https://descargas.scoutcuts.com/"
echo "    Y una descarga real con un codigo de acceso de prueba (el POST del"
echo "    formulario; el codigo nunca va en la URL). En esa prueba fijate en"
echo "    que el archivo llegue llamandose $NOMBRE:"
echo "    el nombre lo pone nginx en el bloque interno /protegido/."
