@echo off
rem Avvia l'interfaccia grafica (al primo avvio crea .venv e installa le dipendenze).
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creo l'ambiente virtuale...
    python -m venv .venv || goto :errore
)

".venv\Scripts\python.exe" -c "import audiototranscript, faster_whisper" 2>nul || (
    echo Installo le dipendenze...
    ".venv\Scripts\python.exe" -m pip install -e . || goto :errore
)

".venv\Scripts\python.exe" -c "import tkinter, audiototranscript.gui" || goto :errore_gui
start "" ".venv\Scripts\pythonw.exe" -m audiototranscript.gui
exit /b 0

:errore
echo.
echo Errore durante la preparazione. Serve Python 3.10 o superiore nel PATH (https://www.python.org/downloads/).
pause
exit /b 1

:errore_gui
echo.
echo Impossibile avviare l'interfaccia grafica (vedi l'errore sopra).
echo Prova la modalita live con avvia_live.bat oppure installa Python con Tcl/Tk (https://www.python.org/downloads/).
pause
exit /b 1
