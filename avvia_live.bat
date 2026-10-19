@echo off
rem Avvia il server della trascrizione live (al primo avvio crea .venv e installa le dipendenze).
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creo l'ambiente virtuale...
    python -m venv .venv || goto :errore
)

".venv\Scripts\python.exe" -c "import audiototranscript, faster_whisper, fastapi, uvicorn" 2>nul || (
    echo Installo le dipendenze...
    ".venv\Scripts\python.exe" -m pip install -e . || goto :errore
)

echo Trascrizione live su http://127.0.0.1:8765  (chiudi questa finestra per fermare il server)
".venv\Scripts\python.exe" -m audiototranscript.live_server %*
if errorlevel 1 pause
exit /b 0

:errore
echo.
echo Errore durante la preparazione. Serve Python 3.10 o superiore nel PATH (https://www.python.org/downloads/).
pause
exit /b 1
