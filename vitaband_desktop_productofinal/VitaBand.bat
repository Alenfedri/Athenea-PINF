@echo off
setlocal
cd /d "%~dp0"
title VitaBand
if exist ".venv\Scripts\pythonw.exe" goto ejecutar

where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% --version >nul 2>nul
if errorlevel 1 (
  echo No se encuentra Python 3.10 o superior.
  echo Instalalo desde https://www.python.org/downloads/ marcando "Add python.exe to PATH" y vuelve a abrir este archivo.
  pause
  exit /b 1
)
echo Primera vez: preparando VitaBand ^(1-3 minutos, necesita internet^)...
%PY% -m venv .venv || goto error
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto error

:ejecutar
start "" ".venv\Scripts\pythonw.exe" main.py
exit /b 0

:error
echo.
echo Algo ha fallado en la instalacion. Revisa tu conexion y vuelve a abrir este archivo.
if exist ".venv" rmdir /s /q ".venv"
pause
exit /b 1
