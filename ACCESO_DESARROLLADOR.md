# Acceso de desarrollador con privilegios completos

Creado el 2026-11-04 (tarde). Este documento describe un nivel de acceso DISTINTO y MÁS
AMPLIO que el de `ACCESO_QA_SSH.md`. No lo reemplaza: las dos cuentas siguen activas en
paralelo, para dos roles distintos.

## Quién es esta persona

Un desarrollador de confianza, autorizado expresamente por el propietario del proyecto
(2026-11-04) para trabajar en el sistema real al mismo nivel que el propio propietario:
puede leer secretos, desplegar a producción y modificar el servidor directamente. Usa su
propia sesión de Claude Code, igual que se ha hecho en toda la historia de este proyecto.

Esto es una decisión consciente del propietario, no una plantilla de seguridad por
defecto. Si en el futuro se necesita dar acceso a alguien que NO deba tener este nivel de
confianza, usar el patrón restringido de `ACCESO_QA_SSH.md` (cuenta sin sudo, sin
secretos, limitada a un directorio aislado), no este.

## Qué cambió el 2026-11-04

La clave pública que ya existía para la cuenta `scoutqa` (comentario `scoutcuts-20261103`,
huella `SHA256:iDZfAVekqpKfK5bUX7RRRlSRNZcq6qJgFA2RI31qUko`) fue agregada TAMBIÉN a
`/root/.ssh/authorized_keys`, con el comentario `scoutcuts-20261103-dev-root` para
diferenciarla en el archivo. Es la MISMA clave privada que el desarrollador ya tenía; no
se generó una nueva. A partir de ahora esa clave privada abre dos puertas distintas:

- `ssh scoutqa@144.202.57.21` (o el alias restringido que tenga configurado): cuenta sin
  sudo, sin secretos, limitada a `/opt/cortador-control/dev/cortador-turnos`. Sigue viva
  por si alguna vez se necesita un acceso solo de lectura/diagnóstico.
- `ssh root@144.202.57.21` (o el alias `precios` si lo configura igual que el
  propietario): acceso administrativo COMPLETO. Sin restricciones. Esta es la vía que debe
  usar el desarrollador para trabajar de verdad.

`PermitRootLogin` en este servidor es `prohibit-password`: solo entra por llave, nunca por
contraseña, así que esto no abre una puerta nueva de fuerza bruta, pero SÍ significa que
cualquiera con esa clave privada ya tiene control total del servidor. El desarrollador
debe tratar su clave privada con el mismo cuidado que una contraseña de root, porque
ahora literalmente lo es.

## Qué puede hacer con este acceso

Todo lo que puede hacer el propietario desde `ssh precios`:

- Leer `/etc/cortador-control/app.env` (secretos reales).
- Desplegar con `despliegue/desplegar.sh`.
- Modificar `/opt/cortador-control/app` (producción real), no solo el snapshot de
  desarrollo.
- Reiniciar servicios, editar nginx, administrar PostgreSQL.
- Hacer commit y push al repositorio real.

Con ese poder vienen las MISMAS reglas que sigue el propietario, documentadas en
`CONTINUAR_SERVIDOR.md` (sección "Qué no hacer") y en `AGENTS.md` del repositorio local:
nunca imprimir o pegar secretos en el chat, nunca `git reset`/`checkout`/`clean` sin
avisar, nunca desplegar sin pasar primero la suite completa, nunca tocar el borrado
automático de videos (hay menores de edad involucrados), siempre verificar con
`verificar-despliegue.sh` después de desplegar.

## Repositorio: GitHub es ahora la fuente de verdad

Existe un repositorio remoto real, ya configurado y con dos commits empujados:

```
https://github.com/elvisperaltad/scoutcuts.git
```

Rama `main`. Último commit verificado: `8f116cd` ("Gracia extendida de purga para videos
pendientes de revision").

El repositorio es PRIVADO (`curl` sin autenticación da 404). Antes de que el desarrollador
pueda clonarlo o hacer push, EL PROPIETARIO debe invitarlo como colaborador desde:

```
https://github.com/elvisperaltad/scoutcuts/settings/access
```

(Añadir colaborador con su usuario o email de GitHub, rol "Write" o "Admin" según cuánta
confianza se le dé sobre la configuración del repo, no solo sobre el código.)

Hasta que esa invitación se envíe y se acepte, el desarrollador puede seguir trabajando
igual en el snapshot aislado `/opt/cortador-control/dev/cortador-turnos` (ver
`DESARROLLO_REMOTO.md`), pero con acceso root ya no tiene sentido limitarse a eso: lo
natural es clonar el repo real, trabajar sobre él, y que su propio `git push` llegue
directo a GitHub sin pasar por parches manuales.

## Flujo de trabajo recomendado para este desarrollador

```bash
ssh root@144.202.57.21
cd /opt/cortador-control
git clone https://github.com/elvisperaltad/scoutcuts.git mi-copia-trabajo
cd mi-copia-trabajo
# leer antes de tocar nada:
sed -n '1,120p' CONTINUAR_SERVIDOR.md
sed -n '1,60p' BITACORA.md
```

Para desplegar sus propios cambios una vez probados:

```bash
cd mi-copia-trabajo
python -m pytest -q          # o el runner equivalente en Linux
SOURCE=/opt/cortador-control/mi-copia-trabajo bash despliegue/desplegar.sh
bash despliegue/verificar-despliegue.sh
```

Después, hacer `git push` desde su copia para que el cambio quede en GitHub y el
propietario lo vea reflejado al hacer `git pull` en `C:/Dev/projects/cortador-turnos`.

## Mensaje para dárselo al desarrollador

```text
Ya tienes acceso completo de administrador al servidor con la misma llave SSH que ya
tenías (la de scoutcuts-20261103): conéctate con `ssh root@144.202.57.21`. Antes de tocar
nada, lee completo /opt/cortador-control/CLAUDE.md (que es una copia sincronizada de
CONTINUAR_SERVIDOR.md) y las entradas más recientes de /opt/cortador-control/docs/BITACORA.md.

El código real vive en https://github.com/elvisperaltad/scoutcuts.git (rama main); te voy
a invitar como colaborador desde GitHub, avísame si no te llega la invitación. Hasta que
te llegue, puedes seguir trabajando en /opt/cortador-control/dev/cortador-turnos como ya
venías haciendo.

Con este acceso puedes ver secretos reales y desplegar directo a producción: por favor
nunca pegues ningún valor de /etc/cortador-control/app.env en un chat, nunca hagas
`git reset`/`checkout`/`clean` sin avisarme antes, corre siempre la suite completa de
pruebas antes de desplegar, y usa despliegue/verificar-despliegue.sh después de cada
despliegue para confirmar que quedó bien. El sistema maneja video de menores de edad:
nunca desactives ni cambies el borrado automático sin que lo hablemos primero.
```

## Prompt para pegarle a su IA (Claude Code) ya conectado por SSH

Esto es distinto del mensaje anterior: aquel es lo que el propietario le dice AL
DESARROLLADOR por chat; esto es lo que el desarrollador pega dentro de su sesión de
Claude Code una vez que ya hizo `ssh root@144.202.57.21`, para que la IA arranque
orientada en vez de explorar a ciegas.

```text
Estás conectado por SSH como root a 144.202.57.21, el servidor de producción de
ScoutCuts. Antes de tocar nada, lee completos estos tres archivos en este orden:
/opt/cortador-control/CLAUDE.md, /opt/cortador-control/docs/ACCESO_DESARROLLADOR.md
y las últimas 100 líneas de /opt/cortador-control/docs/BITACORA.md (es un log
cronológico, lo más reciente va al principio).

El código real vive en https://github.com/elvisperaltad/scoutcuts.git, rama main.
Clónalo en /opt/cortador-control/ bajo un nombre propio (no "integrado" ni "app",
esos nombres ya están en uso por el pipeline de despliegue) y trabaja ahí, nunca
edites directamente /opt/cortador-control/app (es la release activa, el symlink que
usa systemd) ni el snapshot /opt/cortador-control/dev/cortador-turnos (es del otro
desarrollador QA, en un sandbox aislado).

Tienes acceso root real: puedes leer /etc/cortador-control/app.env, desplegar con
despliegue/desplegar.sh y reiniciar servicios. Con ese poder van estas reglas, sin
excepción: nunca imprimas, repitas ni pegues en el chat ningún valor de
app.env; nunca hagas git reset, git checkout, git clean ni reescribas historia sin
preguntar primero; corre toda la suite de pruebas (python -m pytest -q) en VERDE
antes de cualquier despliegue; después de desplegar corre siempre
despliegue/verificar-despliegue.sh y no declares éxito si termina en "Despliegue NO
verificado"; nunca toques ni desactives el borrado automático de video en
almacen.py (hay menores de edad en el material, no es negociable); haz commit y
push a GitHub de tu propio trabajo probado, con mensajes que expliquen el porqué,
no solo el qué.

Dime primero qué tarea concreta vas a abordar y espera confirmación antes de
desplegar nada a producción.
```

