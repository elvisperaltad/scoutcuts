# Acceso SSH del QA a ScoutCuts

Creado el 2026-11-03 para que el QA pueda consultar el servidor con su propio Claude sin compartir la cuenta root ni ninguna clave privada.

## Cuenta creada

- Usuario remoto: `scoutqa`.
- Servidor: `144.202.57.21`.
- Clave pública autorizada: comentario `scoutcuts-20261103`.
- Huella de la clave del QA: `SHA256:iDZfAVekqpKfK5bUX7RRRlSRNZcq6qJgFA2RI31qUko`.
- Huella ED25519 del servidor: `SHA256:of5Zz14W154QfiUJPCnotumDXRRB45nvh5clLeQySkc`.

El QA conserva la clave privada. No debe entregársela a nadie, pegarla en un chat, subirla a Git ni copiarla al servidor.

## Privilegios

La cuenta es deliberadamente limitada y pertenece únicamente al grupo de lectura `scoutdocs`:

- Puede abrir una sesión SSH y leer la documentación de ScoutCuts.
- No tiene `sudo`.
- No puede leer `/etc/cortador-control/app.env` ni las credenciales de PostgreSQL.
- No puede escribir en `/opt/cortador-control/app`.
- Sí puede desarrollar en la copia aislada `/opt/cortador-control/dev/cortador-turnos`; ese árbol no es producción.
- No puede hacer port forwarding, agent forwarding, X11 forwarding ni túneles.
- No puede entrar con contraseña.

Esta cuenta es para consultar estado, recopilar diagnósticos no secretos y permitir que Claude entienda el proyecto. No sirve para desplegar ni modificar producción. Cualquier cambio debe prepararse y probarse en el repositorio de desarrollo, y luego aplicarse mediante la cuenta administrativa autorizada.

## Configuración en la computadora del QA

En `~/.ssh/config` debe añadir un bloque como este, cambiando `IdentityFile` por la ubicación real de SU clave privada:

```sshconfig
Host scoutcuts
    HostName 144.202.57.21
    User scoutqa
    IdentityFile ~/.ssh/id_ed25519_scoutcuts
    IdentitiesOnly yes
    ServerAliveInterval 60
    ServerAliveCountMax 3
```

En Windows, el archivo normalmente es:

`C:\Users\SU_USUARIO\.ssh\config`

La clave privada correspondiente debe estar en la ruta indicada por `IdentityFile`. La línea pública autorizada en el servidor es:

`ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBS4x3/c+arllNZ6Z1aSwLsVyZT3BNud1oLjstSrGYlO scoutcuts-20261103`

## Primera conexión

Ejecutar:

```bash
ssh scoutcuts
```

La primera vez SSH mostrará la huella del servidor. Aceptarla únicamente si coincide exactamente con:

`SHA256:of5Zz14W154QfiUJPCnotumDXRRB45nvh5clLeQySkc`

Después de entrar:

```bash
sed -n '1,220p' /opt/cortador-control/CLAUDE.md
```

## Mensaje para darle a Claude

```text
Conéctate por SSH usando el alias scoutcuts. Antes de hacer cualquier cosa, lee completo /opt/cortador-control/CLAUDE.md, /opt/cortador-control/docs/DESARROLLO_REMOTO.md y los demás documentos de /opt/cortador-control/docs/. Trabaja únicamente en /opt/cortador-control/dev/cortador-turnos. Esta cuenta no tiene sudo ni acceso a secretos o producción. No intentes evadir las restricciones, no leas /etc/cortador-control/app.env, no borres archivos y no afirmes que la API está desplegada. api.scoutcuts.com y descargas.scoutcuts.com responden 502 porque el servicio todavía no existe. Preserva el árbol Git sucio, termina la API con TDD y entrega diff y resultados; no despliegues, no hagas commit ni push sin autorización.
```

## Diagnóstico inicial seguro

Claude puede ejecutar:

```bash
hostname
id
systemctl is-active nginx postgresql fail2ban ssh
curl -I https://scoutcuts.com/
ss -ltn
sed -n '1,220p' /opt/cortador-control/CLAUDE.md
```

No debe intentar leer archivos de `/etc/cortador-control/` ni conectarse directamente a PostgreSQL.

## Revocación

Para retirar el acceso sin afectar a otros usuarios:

```bash
rm -f /home/scoutqa/.ssh/authorized_keys
passwd -l scoutqa
```

Para restaurarlo se debe volver a instalar la clave pública validada con permisos 600.
