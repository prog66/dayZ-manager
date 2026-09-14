@echo off
title DayZ Manager Builder
setlocal
pushd "%~dp0"

echo ==========================
echo Compilation non destructive
echo ==========================

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo ERREUR : environnement .venv absent.
    echo Installe d'abord les dependances avec :
    echo "%~dp0.venv\Scripts\python.exe" -m pip install -r requirements.txt
    popd
    exit /b 1
)

"%PYTHON%" -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo ERREUR : PyInstaller absent de .venv.
    echo Lance : "%PYTHON%" -m pip install -r requirements.txt
    popd
    exit /b 1
)

"%PYTHON%" tools\verify_environment.py --lock requirements-lock.txt
if errorlevel 1 (
    echo ERREUR : environnement de build non verrouille.
    popd
    exit /b 1
)

set "STAGE_DIST=%~dp0dist\staging"
set "STAGE_BUILD=%~dp0build\staging"
if not exist "%STAGE_DIST%" mkdir "%STAGE_DIST%"
if not exist "%STAGE_BUILD%" mkdir "%STAGE_BUILD%"

echo.
echo ==========================
echo Compilation
echo ==========================

set PYTHONHASHSEED=0
"%PYTHON%" -m PyInstaller ^
--noconfirm ^
--clean ^
--windowed ^
--noupx ^
--name DayZManager ^
--distpath "%STAGE_DIST%" ^
--workpath "%STAGE_BUILD%" ^
--specpath "%STAGE_BUILD%" ^
--icon="%~dp0DayZManager.ico" ^
--collect-all PyQt6 ^
--collect-all paramiko ^
main.py

if errorlevel 1 (
    echo.
    echo ECHEC DE COMPILATION
    popd
    exit /b 1
)

"%PYTHON%" tools\release_manifest.py --artifact "%STAGE_DIST%\DayZManager\DayZManager.exe"
if errorlevel 1 (
    echo ERREUR : manifeste de release impossible.
    popd
    exit /b 1
)

set "STAGE_ARCHIVE=%STAGE_DIST%\DayZManager-windows-amd64.zip"
"%PYTHON%" tools\package_release.py --source "%STAGE_DIST%\DayZManager" --output "%STAGE_ARCHIVE%"
if errorlevel 1 (
    echo ERREUR : archive de release impossible.
    popd
    exit /b 1
)

"%PYTHON%" tools\smoke_test_exe.py "%STAGE_DIST%\DayZManager\DayZManager.exe"
if errorlevel 1 (
    echo ERREUR : smoke test de l'executable impossible.
    popd
    exit /b 1
)

echo.
echo ==========================
echo TERMINE
echo ==========================
echo Executable :
echo dist\staging\DayZManager\DayZManager.exe
echo Archive GitHub :
echo dist\staging\DayZManager-windows-amd64.zip

popd
endlocal
