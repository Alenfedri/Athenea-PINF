@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call VitaBand.bat
".venv\Scripts\python.exe" -m pip install pyinstaller ^|^| goto error
".venv\Scripts\python.exe" -m PyInstaller --clean --noconfirm VitaBand.spec ^|^| goto error
echo.
echo Listo: dist\VitaBand\VitaBand.exe (copia la carpeta VitaBand entera)
pause
exit /b 0
:error
echo Fallo al construir el ejecutable.
pause
exit /b 1
