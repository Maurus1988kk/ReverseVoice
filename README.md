# AudioToTranscript

Trascrive file audio/video in Markdown, **interamente in locale** (nessun dato lascia il tuo computer), con [faster-whisper](https://github.com/SYSTRAN/faster-whisper) su CPU. Tre modi d'uso:

- **Interfaccia grafica** (Tkinter): scegli un file e un modello, premi «Avvia».
- **Riga di comando**: file singoli o intere cartelle.
- **Modalità live**: trascrive in tempo quasi reale microfono e/o audio di una scheda del browser, su `http://127.0.0.1:8765`.

## Requisiti

- Python **3.10 o superiore** (Windows, macOS, Linux). Su Linux per la GUI serve anche `python3-tk`.
- Circa 4 GB di RAM liberi per `medium`; 2 GB bastano per `small`.
- Connessione a internet solo al primo uso di ciascun modello (download di 0,5-1,6 GB); poi funziona offline.
- `ffmpeg` (opzionale): serve solo come fallback per formati che la decodifica interna non legge.

## Installazione

> Non hai Python o non sei pratico di terminale? Segui la [guida passo-passo](README_INSTALLAZIONE.md).

```bash
git clone https://github.com/maurus1988kk/ReverseVoice.git
cd ReverseVoice
```

**Metodo rapido** — i launcher creano l'ambiente virtuale e installano tutto al primo avvio:

| | GUI | Modalità live |
|---|---|---|
| Windows | doppio clic su `avvia.bat` | doppio clic su `avvia_live.bat` |
| macOS / Linux | `./avvia.sh` | `./avvia.sh live` |

**Metodo manuale** (consigliato in un ambiente virtuale):

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install .
```

Installa i comandi `audiototranscript`, `audiototranscript-gui` e `audiototranscript-live`. Con [pipx](https://pipx.pypa.io): `pipx install .`

## Riga di comando

```bash
# Singolo file, modello di default (medium), lingua italiana
audiototranscript registrazione.mp4

# Cartella intera, modello più veloce, glossario personalizzato
audiototranscript ./interviste --model large-v3-turbo --glossary examples/glossary.txt

# Test rapido sui primi 2 minuti, output in un'altra cartella
audiototranscript video.mkv --max-seconds 120 --out-dir ./output
```

Il Markdown viene salvato accanto al file (o in `--out-dir`). I file già trascritti vengono saltati, salvo `--force`. Tutte le opzioni: `audiototranscript --help`. Funziona anche come `python -m audiototranscript`.

Il **glossario** è un file di testo con i termini tecnici da riconoscere correttamente (vedi `examples/glossary.txt`, max 800 caratteri).

## Interfaccia grafica

```bash
audiototranscript-gui     # oppure avvia.bat / ./avvia.sh
```

Il lavoro gira in un processo separato e annullabile; il Markdown è salvato nella cartella del file audio. Dalla finestra si può avviare anche la modalità live.

## Modalità live

```bash
audiototranscript-live    # oppure avvia_live.bat / ./avvia.sh live
```

Opzioni: `--port`, `--no-browser`, `--output-dir`. Il server ascolta **solo su 127.0.0.1** e rifiuta connessioni WebSocket da altre origini.

- **Sorgenti**: microfono, scheda del browser, oppure entrambi mixati. Per la scheda usa Chrome/Edge: nel selettore scegli una scheda e spunta «Condividi anche l'audio della scheda» (su Windows puoi condividere anche lo schermo intero con l'audio di sistema). Firefox supporta solo il microfono.
- Con «Entrambi» usa le cuffie, altrimenti il microfono riprende l'audio della lezione.
- Per il tempo reale usa `small`; `medium` può restare indietro (compare un avviso).
- Le sessioni sono salvate in `~/AudioToTranscript/sessioni/<data>_<titolo>/` (cambiabile con `--output-dir`) con `trascrizione.md` e `audio.wav`. Per una resa migliore puoi rielaborare `audio.wav` con `medium` o `large-v3-turbo`.
- **Ripristino dopo un crash**: se resta `audio.pcm`, convertilo con `ffmpeg -f s16le -ar 16000 -ac 1 -i audio.pcm audio.wav`; se resta `trascrizione.md.part`, contiene il testo già trascritto.

## Risoluzione dei problemi

| Problema | Soluzione |
|---|---|
| `python` non trovato | Installa Python 3.10+ e, su Windows, spunta «Add Python to PATH». |
| «Impossibile scaricare il modello» | Controlla la connessione: serve solo al primo uso del modello. |
| «Impossibile decodificare il file» | Installa `ffmpeg` e aggiungilo al PATH. |
| La GUI non parte su Linux | `sudo apt install python3-tk`, oppure usa la modalità live o la CLI. |
| Porta 8765 occupata | `audiototranscript-live --port 8800`. |
| Microfono/scheda non rilevati | Concedi il permesso al browser; per l'audio di scheda usa Chrome/Edge. |
| Trascrizione troppo lenta | Usa il modello `small` o riduci `--threads` se il PC è usato per altro. |

## Sviluppo

```bash
pip install -e ".[dev]"
pytest          # i test non scaricano modelli
ruff check .
```

## Licenza

[MIT](LICENSE)
