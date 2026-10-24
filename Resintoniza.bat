@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title Resintoniza

set "PY=.venv\Scripts\python.exe"
set "PYW=.venv\Scripts\pythonw.exe"

if "%~1"=="" goto menu
set "OPCION=%~1"
goto ejecutar

:menu
echo.
echo  ==========================================
echo   Resintoniza - television y radio en directo
echo  ==========================================
echo   1. Crear el entorno virtual e instalar dependencias
echo   2. Preparar la carpeta data (descargar libmpv si falta)
echo   3. Ejecutar desde el codigo fuente
echo   4. Ejecutar las pruebas
echo   5. Compilar con cx_Freeze (carpeta build\Resintoniza)
echo   6. Todo: entorno, data, pruebas y compilacion
echo   7. Salir
echo.
set /p "OPCION=Elige una opcion (1-7): "

:ejecutar
if "%OPCION%"=="1" goto entorno
if "%OPCION%"=="2" goto datos
if "%OPCION%"=="3" goto ejecutar_codigo
if "%OPCION%"=="4" goto pruebas
if "%OPCION%"=="5" goto compilar
if "%OPCION%"=="6" goto todo
if "%OPCION%"=="7" goto fin
if /i "%OPCION%"=="entorno" goto entorno
if /i "%OPCION%"=="datos" goto datos
if /i "%OPCION%"=="ejecutar" goto ejecutar_codigo
if /i "%OPCION%"=="pruebas" goto pruebas
if /i "%OPCION%"=="compilar" goto compilar
if /i "%OPCION%"=="todo" goto todo
echo Opcion no valida.
goto menu

:entorno
echo.
echo [1/2] Creando el entorno virtual con Python 3.13 de 64 bits...
if not exist "%PY%" (
    py -3.13 -m venv .venv
    if errorlevel 1 (
        echo ERROR: no se pudo crear el entorno. Instala Python 3.13 de 64 bits desde python.org con el lanzador "py".
        goto error
    )
)
echo [2/2] Instalando dependencias (wxPython, python-mpv, voz, navegador accesible y cx_Freeze)...
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r requirements-dev.txt
if errorlevel 1 (
    echo ERROR: no se pudieron instalar las dependencias. Comprueba la conexion a Internet.
    goto error
)
echo Entorno preparado.
if "%~1"=="" goto menu
goto fin

:datos
echo.
if not exist "%PY%" call :necesita_entorno
echo Preparando la carpeta data (libmpv, unos 31 MB de descarga si falta; con "datos forzar" se baja la ultima version)...
if /i "%~2"=="forzar" (
    "%PY%" main.py --preparar --forzar
) else (
    "%PY%" main.py --preparar
)
if errorlevel 1 (
    echo ERROR: no se pudo preparar la carpeta data.
    goto error
)
if "%~1"=="" goto menu
goto fin

:ejecutar_codigo
if not exist "%PY%" call :necesita_entorno
echo Abriendo Resintoniza desde el codigo...
start "" "%PYW%" main.py
if "%~1"=="" goto menu
goto fin

:pruebas
if not exist "%PY%" call :necesita_entorno
"%PY%" -m unittest discover -s tests -v
if errorlevel 1 (
    echo ERROR: han fallado las pruebas.
    goto error
)
"%PY%" main.py --comprobar
if "%~1"=="" goto menu
goto fin

:compilar
echo.
if not exist "%PY%" call :necesita_entorno
if not exist "data\mpv\libmpv-2.dll" (
    echo Falta data\mpv\libmpv-2.dll: se descarga primero.
    "%PY%" main.py --preparar
    if errorlevel 1 goto error
)
echo Compilando con cx_Freeze. La carpeta data se copia limpia (solo el reproductor)...
if exist build\Resintoniza rmdir /s /q build\Resintoniza
"%PY%" setup_cx.py build_exe
if errorlevel 1 (
    echo ERROR: la compilacion ha fallado.
    goto error
)
echo.
echo Compilacion terminada: build\Resintoniza\Resintoniza.exe
echo Copia la carpeta build\Resintoniza completa para llevarla a otro equipo.
if "%~1"=="" goto menu
goto fin

:todo
call "%~f0" entorno
if errorlevel 1 goto error
call "%~f0" datos
if errorlevel 1 goto error
call "%~f0" pruebas
if errorlevel 1 goto error
call "%~f0" compilar
if errorlevel 1 goto error
if "%~1"=="" goto menu
goto fin

:necesita_entorno
echo El entorno virtual no existe: se crea ahora.
call "%~f0" entorno
if errorlevel 1 goto error
exit /b 0

:error
echo.
if "%~1"=="" pause
exit /b 1

:fin
endlocal
exit /b 0
