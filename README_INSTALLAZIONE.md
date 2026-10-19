# Guida all'installazione (anche se non hai Python)

Questa guida è pensata per chi parte da zero. Il programma gira interamente sul tuo computer: nessun account, nessun invio di dati. Serve internet solo per l'installazione e per il primo download del modello.

**Cosa ti serve:** circa 3 GB di spazio libero (programma ≈ 0,3 GB, modello 0,5-1,6 GB), almeno 4 GB di RAM, e Windows 10/11, macOS o Linux.

---

## Windows

### 1. Installa Python (una sola volta)
1. Vai su <https://www.python.org/downloads/> e scarica **Python 3.12** (o 3.10 o superiore).
2. Avvia il file scaricato.
3. **Importante:** nella prima schermata spunta **«Add python.exe to PATH»**, poi premi **Install Now**.
4. Alla fine chiudi l'installer.

Per verificare, apri il menu Start, scrivi `cmd`, premi Invio e digita `python --version`. Deve comparire un numero di versione (3.10 o superiore). Se Windows apre invece il Microsoft Store, Python non è nel PATH: reinstalla spuntando la casella del punto 3.

### 2. Scarica il programma
1. Apri la pagina GitHub del progetto.
2. Premi il pulsante verde **Code → Download ZIP**.
3. Fai clic destro sul file ZIP → **Estrai tutto…** e scegli una cartella, ad esempio `C:\AudioToTranscript`.
   Non avviare i file direttamente dallo ZIP: va prima estratto.

### 3. Avvia
- Doppio clic su **`avvia.bat`** per l'interfaccia grafica.
- Doppio clic su **`avvia_live.bat`** per la trascrizione live nel browser.

Al **primo avvio** compare una finestra nera che crea l'ambiente e scarica le librerie: richiede qualche minuto, aspetta che finisca. Dagli avvii successivi parte subito.

Se Windows mostra «Il PC è stato protetto» (SmartScreen), premi **Ulteriori informazioni → Esegui comunque**: succede perché lo script non è firmato digitalmente.

---

## macOS

1. Installa Python da <https://www.python.org/downloads/macos/> (versione 3.10 o superiore) con il pacchetto `.pkg`.
   In alternativa, con Homebrew: `brew install python python-tk`.
2. Scarica lo ZIP da GitHub (**Code → Download ZIP**) e fai doppio clic per estrarlo.
3. Apri **Terminale**, scrivi `cd ` (con lo spazio finale), trascina dentro la cartella estratta e premi Invio.
4. Esegui:
   ```bash
   chmod +x avvia.sh
   ./avvia.sh          # interfaccia grafica
   ./avvia.sh live     # trascrizione live nel browser
   ```
Il primo avvio scarica le librerie e richiede qualche minuto.

---

## Linux (Debian/Ubuntu)

```bash
sudo apt update
sudo apt install python3 python3-venv python3-tk git
git clone https://github.com/maurus1988kk/ReverseVoice.git
cd ReverseVoice
./avvia.sh          # interfaccia grafica
./avvia.sh live     # trascrizione live nel browser
```

Se non hai `git`, scarica lo ZIP da GitHub ed estrailo. Su altre distribuzioni installa i pacchetti equivalenti (Python 3.10+, venv, Tkinter).

---

## Primo utilizzo

1. Nella GUI scegli il modello. Consiglio: **`small`** per il live o per PC lenti, **`medium`** per la qualità migliore in tempi ragionevoli.
2. Premi **Scegli file…**, poi **Avvia trascrizione**.
3. **La prima volta che usi un modello viene scaricato** (0,5-1,6 GB): la barra resta in attesa per qualche minuto. Dopo funziona anche offline.
4. Il file Markdown (`.md`) compare nella stessa cartella del file audio.

Per la modalità live si apre il browser su `http://127.0.0.1:8765`. Per catturare l'audio di una scheda usa Chrome o Edge.

---

## Facoltativo: ffmpeg

Serve solo per file audio/video che il programma non riesce a leggere («Impossibile decodificare il file»).
- **Windows:** apri `cmd` e digita `winget install ffmpeg`, poi riapri il programma.
- **macOS:** `brew install ffmpeg`
- **Linux:** `sudo apt install ffmpeg`

---

## Problemi comuni

| Problema | Soluzione |
|---|---|
| Compare «python non è riconosciuto…» | Python non è nel PATH: reinstallalo spuntando «Add python.exe to PATH». |
| Si apre il Microsoft Store | Come sopra, oppure disattiva gli alias in *Impostazioni → App → Impostazioni app avanzate → Alias di esecuzione app* (`python.exe`). |
| L'installazione delle librerie fallisce | Controlla la connessione, poi cancella la cartella `.venv` e rilancia `avvia.bat`. |
| «Impossibile scaricare il modello» | Serve internet al primo uso del modello. |
| La finestra si chiude subito | Apri `cmd` nella cartella del programma e lancia `avvia.bat` per leggere l'errore. |
| Su Linux la GUI non parte | Installa `python3-tk`, oppure usa `./avvia.sh live`. |
| La porta 8765 è occupata | Chiudi l'altra istanza del programma, oppure da terminale: `.venv/bin/python -m audiototranscript.live_server --port 8800` (Windows: `.venv\Scripts\python`). |

## Aggiornare o disinstallare

- **Aggiornare:** scarica il nuovo ZIP in una cartella nuova. Le tue trascrizioni non vengono toccate.
- **Disinstallare:** elimina la cartella del programma. Eventuali sessioni live sono in `Documenti`/home → `AudioToTranscript\sessioni`, e i modelli scaricati in `%USERPROFILE%\.cache\huggingface` (Linux/macOS: `~/.cache/huggingface`): cancellali se vuoi recuperare spazio.
