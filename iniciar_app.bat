@echo off
setlocal
set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo ERROR: No se encontro el entorno virtual en .venv.
  echo Preparelo siguiendo la seccion Entorno de README.md.
  pause
  exit /b 1
)
cd /d "%~dp0"
"%PYTHON%" -m cortador app
if errorlevel 1 (
  echo.
  echo La aplicacion termino con un error. Revise el mensaje anterior.
  pause
)
endlocal
