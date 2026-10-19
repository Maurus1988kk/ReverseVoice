"""Tkinter front end: runs the transcription in a separate process."""
import multiprocessing
import os
import queue as queue_mod
import shutil
import socket
import subprocess
import sys
import tempfile
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from audiototranscript.transcriber import DEFAULT_MODEL, MEDIA_FILETYPES, MODELS

CTX = multiprocessing.get_context("spawn")
MAX_NAME_CHARS = 38
LIVE_PORT = 8765
LIVE_URL = f"http://127.0.0.1:{LIVE_PORT}/"


def worker_main(path, model_name, tmp_dir, queue):
    try:
        if sys.platform == "win32":
            import ctypes
            k = ctypes.windll.kernel32
            k.SetPriorityClass(k.GetCurrentProcess(), 0x00004000)
        else:
            os.nice(10)
    except Exception:
        pass
    try:
        from audiototranscript import transcriber

        def status_cb(text, busy=False):
            queue.put({"type": "status", "text": text, "busy": busy})

        def progress_cb(value):
            queue.put({"type": "progress", "value": value})

        out = transcriber.transcribe_file(
            path, model_name, progress_cb, status_cb, tmp_dir=tmp_dir
        )
        queue.put({"type": "done", "path": str(out)})
    except Exception as exc:
        queue.put({"type": "error", "text": (str(exc) or type(exc).__name__)[:200]})


def shorten(name, limit=MAX_NAME_CHARS):
    if len(name) <= limit:
        return name
    keep = limit - 3
    head = keep - keep // 2
    return name[:head] + "..." + name[len(name) - keep // 2:]


class App:
    def __init__(self, root):
        self.root = root
        self.file = None
        self.last_dir = None
        self.proc = None
        self.queue = None
        self.tmp_dir = None
        self.result = None
        self.running = False
        self.live_proc = None
        self.live_tries = 0

        root.title("Trascrittore audio")
        root.geometry("480x270")
        root.resizable(False, False)
        if sys.platform.startswith("linux") and "clam" in ttk.Style().theme_names():
            ttk.Style().theme_use("clam")

        frm = ttk.Frame(root, padding=14)
        frm.grid(sticky="nsew")
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="Modello:").grid(row=0, column=0, sticky="w", pady=4)
        self.model_var = tk.StringVar(value=DEFAULT_MODEL)
        # pulsanti radio al posto del menu a tendina: su alcuni PC Windows il popup del
        # Combobox faceva sparire la finestra
        models_frm = ttk.Frame(frm)
        models_frm.grid(row=0, column=1, sticky="w", pady=4)
        self.model_buttons = [
            ttk.Radiobutton(models_frm, text=name, value=name, variable=self.model_var)
            for name in MODELS
        ]
        for btn in self.model_buttons:
            btn.pack(side="left", padx=(0, 10))

        self.file_btn = ttk.Button(frm, text="Scegli file...", command=self.choose_file)
        self.file_btn.grid(row=1, column=0, sticky="w", pady=4)
        self.file_lbl = ttk.Label(frm, text="Nessun file selezionato")
        self.file_lbl.grid(row=1, column=1, sticky="w", padx=8, pady=4)

        self.start_btn = ttk.Button(frm, text="Avvia trascrizione", command=self.start,
                                    state="disabled")
        self.start_btn.grid(row=2, column=0, columnspan=3, sticky="ew", pady=8)

        self.bar = ttk.Progressbar(frm, mode="determinate", maximum=100, length=360)
        self.bar.grid(row=3, column=0, columnspan=2, sticky="ew")
        self.pct_lbl = ttk.Label(frm, text="0%", width=5, anchor="e")
        self.pct_lbl.grid(row=3, column=2, sticky="e")

        self.status_lbl = ttk.Label(frm, text="Pronto", wraplength=440)
        self.status_lbl.grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 0))

        self.open_btn = ttk.Button(frm, text="Apri cartella", command=self.open_folder)
        self.open_btn.grid(row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.open_btn.grid_remove()

        self.live_btn = ttk.Button(frm, text="Modalità live (browser)", command=self.start_live)
        self.live_btn.grid(row=6, column=0, columnspan=3, sticky="w", pady=(6, 0))

        root.protocol("WM_DELETE_WINDOW", self.on_close)

    def choose_file(self):
        path = filedialog.askopenfilename(
            filetypes=[("Audio/Video", MEDIA_FILETYPES), ("Tutti i file", "*.*")],
            initialdir=self.last_dir,
        )
        if not path:
            return
        self.file = Path(path)
        self.last_dir = str(self.file.parent)
        self.file_lbl.config(text=shorten(self.file.name))
        self.start_btn.config(state="normal")

    def start(self):
        if self.running:
            self.cancel()
            return
        if not self.file:
            return
        self.running = True
        self.result = None
        self.open_btn.grid_remove()
        for btn in self.model_buttons:
            btn.config(state="disabled")
        self.file_btn.config(state="disabled")
        self.start_btn.config(text="Annulla")
        self.on_progress(0)
        self.tmp_dir = tempfile.mkdtemp(prefix="transcriber_")
        self.queue = CTX.Queue()
        self.proc = CTX.Process(
            target=worker_main,
            args=(str(self.file), self.model_var.get(), self.tmp_dir, self.queue),
            daemon=True,
        )
        self.proc.start()
        self.root.after(200, self.poll_queue)

    def cancel(self):
        if self.proc is not None:
            self.proc.terminate()
            self.proc.join(timeout=3)
        if self.file:
            try:
                self.file.with_name(self.file.stem + ".md.part").unlink()
            except OSError:
                pass
        self.cleanup_tmp()
        self.reset_controls()
        self.bar.stop()
        self.bar.config(mode="determinate")
        self.on_progress(0)
        self.status_lbl.config(text="Annullato")

    def poll_queue(self):
        if not self.running:
            return
        finished = False
        while True:
            try:
                msg = self.queue.get_nowait()
            except queue_mod.Empty:
                break
            kind = msg["type"]
            if kind == "status":
                self.on_status(msg["text"], msg["busy"])
            elif kind == "progress":
                self.on_progress(msg["value"])
            elif kind == "done":
                self.on_done(msg["path"])
                finished = True
            elif kind == "error":
                self.on_error(msg["text"])
                finished = True
        if finished:
            return
        if not self.proc.is_alive():
            # drain once more: the final message may have arrived after the last get
            try:
                msg = self.queue.get(timeout=0.3)
                self.queue.put(msg)
                self.root.after(0, self.poll_queue)
                return
            except queue_mod.Empty:
                pass
            self.on_error("il processo di trascrizione si è interrotto (memoria insufficiente?)")
            return
        self.root.after(200, self.poll_queue)

    def on_status(self, text, busy):
        self.status_lbl.config(text=text)
        if busy:
            if str(self.bar["mode"]) != "indeterminate":
                self.bar.config(mode="indeterminate")
            self.bar.start(12)

    def on_progress(self, value):
        if str(self.bar["mode"]) == "indeterminate":
            self.bar.stop()
            self.bar.config(mode="determinate")
        self.bar["value"] = value
        self.pct_lbl.config(text=f"{value}%")

    def on_done(self, path):
        self.result = path
        self.cleanup_tmp()
        self.reset_controls()
        self.on_progress(100)
        self.status_lbl.config(text=f"Completato: {path}")
        self.open_btn.grid()

    def on_error(self, text):
        self.cleanup_tmp()
        self.reset_controls()
        self.bar.stop()
        self.bar.config(mode="determinate")
        self.status_lbl.config(text=f"Errore: {text}")

    def cleanup_tmp(self):
        if self.tmp_dir:
            shutil.rmtree(self.tmp_dir, ignore_errors=True)
            self.tmp_dir = None

    def reset_controls(self):
        self.running = False
        if self.proc is not None and self.proc.is_alive():
            self.proc.join(timeout=1)
        self.proc = None
        for btn in self.model_buttons:
            btn.config(state="normal")
        self.file_btn.config(state="normal")
        self.start_btn.config(text="Avvia trascrizione",
                              state="normal" if self.file else "disabled")

    def open_folder(self):
        if not self.result:
            return
        folder = str(Path(self.result).parent)
        if sys.platform == "win32":
            os.startfile(folder)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])

    def start_live(self):
        if self.live_proc is not None and self.live_proc.poll() is None:
            webbrowser.open(LIVE_URL)
            return
        python = sys.executable
        if python.lower().endswith("pythonw.exe"):  # serve una console per vedere gli errori
            python = python[:-len("pythonw.exe")] + "python.exe"
        root_dir = str(Path(__file__).resolve().parent.parent)  # per l'uso senza installazione
        module = "audiototranscript.live_server"
        try:
            if sys.platform == "win32":
                # visible console; on a crash the window stays open (pause) to show the error
                cmd = (f'cmd /c "title Server live & "{python}" -m {module} --no-browser '
                       f'& if errorlevel 1 pause"')
                self.live_proc = subprocess.Popen(
                    cmd, cwd=root_dir, creationflags=subprocess.CREATE_NEW_CONSOLE
                )
            else:
                self.live_proc = subprocess.Popen(
                    [python, "-m", module, "--no-browser"], cwd=root_dir
                )
        except OSError as exc:
            messagebox.showerror("Trascrittore audio",
                                 f"Impossibile avviare la modalità live: {exc}")
            return
        self.live_tries = 0
        self.root.after(500, self.check_live)

    def check_live(self):
        # open the browser as soon as the server accepts connections
        if self.live_proc is None or self.live_proc.poll() is not None:
            return
        try:
            socket.create_connection(("127.0.0.1", LIVE_PORT), timeout=0.3).close()
        except OSError:
            self.live_tries += 1
            if self.live_tries < 60:
                self.root.after(500, self.check_live)
            return
        webbrowser.open(LIVE_URL)

    def stop_live(self):
        if self.live_proc is not None and self.live_proc.poll() is None:
            if sys.platform == "win32":
                # kill the whole tree (cmd + python + its worker process)
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.live_proc.pid)],
                               capture_output=True)
            else:
                self.live_proc.terminate()

    def on_close(self):
        if self.live_proc is not None and self.live_proc.poll() is None:
            if not messagebox.askyesno(
                "Trascrittore audio",
                "Il server della modalità live è attivo. Chiudendo la finestra verrà fermato "
                "(una sessione live in corso andrebbe persa). Vuoi chiudere?",
            ):
                return
        if self.running:
            if not messagebox.askyesno(
                "Trascrittore audio",
                "Una trascrizione è in corso. Vuoi annullarla e chiudere?",
            ):
                return
            self.cancel()
        self.stop_live()
        self.root.destroy()


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
