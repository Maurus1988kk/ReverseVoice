#!/usr/bin/env sh
# Avvia l'interfaccia grafica (macOS/Linux). Al primo avvio crea .venv e installa le dipendenze.
# Uso: ./avvia.sh          -> interfaccia grafica
#      ./avvia.sh live     -> server della trascrizione live (opzioni extra dopo "live")
set -e
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
    echo "Python 3.10+ non trovato. Installalo (https://www.python.org/downloads/) e riprova." >&2
    exit 1
fi

if [ ! -x .venv/bin/python ]; then
    echo "Creo l'ambiente virtuale..."
    "$PY" -m venv .venv
fi

if ! .venv/bin/python -c "import audiototranscript, faster_whisper, fastapi" 2>/dev/null; then
    echo "Installo le dipendenze..."
    .venv/bin/python -m pip install -e .
fi

if [ "${1:-}" = "live" ]; then
    shift
    echo "Trascrizione live su http://127.0.0.1:8765  (Ctrl+C per fermare)"
    exec .venv/bin/python -m audiototranscript.live_server "$@"
fi

if ! .venv/bin/python -c "import tkinter" 2>/dev/null; then
    echo "Tkinter non disponibile: installa il pacchetto python3-tk (Linux) o python-tk (Homebrew)." >&2
    echo "In alternativa usa la modalità live: ./avvia.sh live" >&2
    exit 1
fi
exec .venv/bin/python -m audiototranscript.gui
