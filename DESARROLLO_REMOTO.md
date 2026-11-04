# Desarrollo remoto de ScoutCuts

Estado creado el 2026-11-03 para que el QA pueda continuar el desarrollo con Claude desde otra computadora sin tocar producción.

## Repositorio de desarrollo en el servidor

`/opt/cortador-control/dev/cortador-turnos`

Este directorio es una copia exacta del árbol de trabajo local:

`C:/Dev/projects/cortador-turnos`

La copia incluye `.git`, archivos rastreados, modificaciones sin commit y archivos nuevos no ignorados. No incluye videos, `.venv`, builds, `dist`, `DatosQA`, `.env`, paquetes QA ni otros archivos ignorados.

## Advertencias importantes

- Este repositorio NO es producción.
- La aplicación productiva futura vivirá en `/opt/cortador-control/app` y seguirá inaccesible para `scoutqa`.
- No existe remoto Git configurado en el repositorio original. No hay GitHub/GitLab desde donde clonarlo ni al cual hacer push.
- Los cambios hechos en el servidor no regresan automáticamente a la computadora de desarrollo.
- El árbol llegó sucio, con trabajo existente sin commit. No ejecutar `git reset`, `git checkout`, `git clean` ni reescribir historia.
- No hacer commit o push sin autorización expresa del propietario.
- No copiar videos de menores al repositorio.
- No copiar `/etc/cortador-control/app.env` ni ningún secreto.

## Acceso

El usuario `scoutqa` puede leer y escribir únicamente en este repositorio de desarrollo mediante el grupo `scoutdev`. No tiene sudo, no pertenece al grupo de producción `cortador`, no puede leer secretos y no puede editar `/opt/cortador-control/app`.

Después de conectar:

```bash
cd /opt/cortador-control/dev/cortador-turnos
git status --short --branch
sed -n '1,260p' CONTINUAR_SERVIDOR.md
```

## Entorno Python

El entorno virtual del servidor está en:

`/opt/cortador-control/dev/cortador-turnos/.venv`

Se creó con Python 3.14.4 y tiene instalado el paquete editable, NumPy, OpenCV y pytest. FastAPI todavía no está instalado porque primero debe declararse correctamente el extra `servidor` en `pyproject.toml`.

Activar con:

```bash
source .venv/bin/activate
```

Pruebas:

```bash
python -m pytest -q
python -m pytest -q tests/servidor/
```

El estado de referencia es:

- Suite local de Windows: 162 pruebas aprobadas y 25 saltadas.
- Suite ejecutada dentro del snapshot remoto: 146 aprobadas y 41 saltadas en 2.09 s.
- La diferencia corresponde a pruebas específicas de Windows, la ausencia de videos reales y las pruebas web todavía sin dependencias/API.
- Las pruebas base de `almacen`, `cola` y `procesador` sí pasan en Linux.
- Los saltos de la API corresponden a que falta `src/cortador/servidor/api.py` y falta declarar/instalar el extra `servidor`.
- El manifiesto `/opt/cortador-control/docs/SNAPSHOT_LOCAL_20261103.sha256` verificó 80 de 80 archivos contra el árbol local al copiarlo.

El servidor no contiene los videos reales del proyecto; las pruebas E2E que dependen de ellos deben saltarse. No subir material de menores sin autorización y una política de retención explícita.

## Primer encargo para Claude

```text
Trabaja únicamente en /opt/cortador-control/dev/cortador-turnos. Lee completos CONTINUAR_SERVIDOR.md, SERVIDOR_CONTROL.md, ACCESO_MOVIL.md y las pruebas de tests/servidor/. No toques /opt/cortador-control/app ni /etc/cortador-control. Preserva todos los cambios locales existentes. Termina src/cortador/servidor/api.py con TDD, declara el extra servidor en pyproject.toml, instala las dependencias dentro de .venv y ejecuta todas las pruebas. No despliegues, no hagas commit ni push y no afirmes éxito mientras test_api.py siga saltado. Al terminar entrega git diff, resultados reales y bloqueos.
```

## Cómo devolver cambios a la estación principal

Hasta que exista un remoto Git, devolver un parche sin binarios ni secretos:

```bash
git diff --binary > /home/scoutqa/scoutcuts-cambios.patch
git status --short > /home/scoutqa/scoutcuts-estado.txt
```

Los archivos nuevos no rastreados no aparecen en `git diff`; deben enumerarse con:

```bash
git ls-files --others --exclude-standard
```

La opción más segura antes de integrar es que el administrador cree un archivo comprimido solo con el código nuevo y el parche, lo descargue, revise y aplique en `C:/Dev/projects/cortador-turnos`.

No desplegar directamente desde el repositorio de desarrollo. El despliegue se hace únicamente después de integrar los cambios en la estación principal, ejecutar la suite completa y verificar el E2E real.

## Sincronización futura

Como no hay remoto Git, cualquier resincronización debe ser explícita. Antes de reemplazar el snapshot del servidor:

1. Confirmar que el QA no tiene cambios pendientes.
2. Exportar su parche y sus archivos nuevos.
3. Respaldar el repositorio remoto.
4. Transferir la nueva copia desde `C:/Dev/projects/cortador-turnos`.
5. Verificar hashes y ejecutar pruebas.

Nunca sobrescribir silenciosamente el trabajo del QA.
