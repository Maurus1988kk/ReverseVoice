"""Local web server for live transcription (127.0.0.1 only)."""
import argparse
import asyncio
import json
import multiprocessing
import os
import queue as queue_mod
import re
import subprocess
import sys
import threading
import unicodedata
import wave
import webbrowser
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from audiototranscript import transcriber

CTX = multiprocessing.get_context("spawn")
STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_OUTPUT_DIR = Path.home() / "AudioToTranscript" / "sessioni"
DEFAULT_PORT = 8765
MAX_FRAME_BYTES = 1_000_000
STOP_TIMEOUT_S = 300
BYTES_PER_SECOND = 32000  # 16 kHz * int16 mono


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9-]+", "-", text.lower()).strip("-")[:40].strip("-")


def pcm_to_wav(pcm_path: Path, wav_path: Path) -> None:
    with open(pcm_path, "rb") as src, wave.open(str(wav_path), "wb") as dst:
        dst.setnchannels(1)
        dst.setsampwidth(2)
        dst.setframerate(16000)
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            dst.writeframes(chunk)
    pcm_path.unlink()


def open_in_file_manager(folder: str) -> None:
    if sys.platform == "win32":
        os.startfile(folder)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", folder])
    else:
        subprocess.Popen(["xdg-open", folder])


def create_app(output_root: Path, port: int) -> FastAPI:
    app = FastAPI()
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    state = {"active": False, "last_dir": None}
    allowed_origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    @app.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.post("/open-folder")
    async def open_folder():
        folder = state["last_dir"]
        if not folder or not Path(folder).is_dir():
            return {"ok": False}
        try:
            open_in_file_manager(folder)
            return {"ok": True}
        except Exception:
            return {"ok": False}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        if ws.headers.get("origin") not in allowed_origins:
            await ws.close(code=1008)
            return
        await ws.accept()
        if state["active"]:
            await safe_send(ws, {"type": "error", "text": "Una sessione è già in corso"})
            await safe_close(ws)
            return
        state["active"] = True
        try:
            await run_session(ws, output_root, state)
        finally:
            state["active"] = False

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


async def safe_send(ws, msg) -> None:
    try:
        await ws.send_json(msg)
    except Exception:
        pass


async def safe_close(ws) -> None:
    try:
        await ws.close()
    except Exception:
        pass


async def run_session(ws: WebSocket, output_root: Path, state: dict) -> None:
    # --- first message: start ---
    try:
        first = json.loads(await ws.receive_text())
        if first.get("type") != "start":
            raise ValueError
    except Exception:
        await safe_send(ws, {"type": "error", "text": "Messaggio di avvio non valido"})
        await safe_close(ws)
        return

    model = first.get("model") if first.get("model") in transcriber.MODELS else "small"
    source = first.get("source") if first.get("source") in ("mic", "tab", "both") else "mic"
    title = str(first.get("title") or "")[:80].strip()
    glossary = str(first.get("glossary") or "")[:600]
    language = str(first.get("language") or transcriber.DEFAULT_LANGUAGE)[:8]

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    slug = slugify(title)
    session_dir = output_root / (f"{stamp}_{slug}" if slug else stamp)
    session_dir.mkdir(parents=True, exist_ok=True)
    state["last_dir"] = str(session_dir)
    pcm_path = session_dir / "audio.pcm"
    wav_path = session_dir / "audio.wav"
    pcm_file = open(pcm_path, "wb")

    from audiototranscript import live_core

    in_q = CTX.Queue()
    out_q = CTX.Queue()
    cfg = {"model": model, "language": language, "glossary": glossary,
           "session_dir": str(session_dir), "title": title, "source": source}
    proc = CTX.Process(target=live_core.worker_main, args=(in_q, out_q, cfg), daemon=True)
    proc.start()

    loop = asyncio.get_running_loop()
    aq: asyncio.Queue = asyncio.Queue()
    reader_stop = threading.Event()

    def reader():
        # bridge: multiprocessing queue -> asyncio queue
        while not reader_stop.is_set():
            try:
                msg = out_q.get(timeout=0.5)
            except queue_mod.Empty:
                if not proc.is_alive():
                    try:
                        msg = out_q.get(timeout=0.5)
                    except queue_mod.Empty:
                        msg = {"type": "error",
                               "text": "il processo di trascrizione si è interrotto"}
                else:
                    continue
            except Exception:
                return
            loop.call_soon_threadsafe(aq.put_nowait, msg)
            if msg.get("type") in ("stopped", "error"):
                return

    threading.Thread(target=reader, daemon=True).start()

    fed = {"seconds": 0.0}
    received = {"bytes": 0}
    done_evt = asyncio.Event()
    result: dict = {}

    async def forwarder():
        while True:
            msg = await aq.get()
            kind = msg.get("type")
            if kind == "clock":
                fed["seconds"] = msg.get("fed", 0.0)
            elif kind in ("stopped", "error"):
                result.update(msg)
                if kind == "error":
                    await safe_send(ws, msg)
                done_evt.set()
                return
            else:
                await safe_send(ws, msg)

    async def lag_task():
        while True:
            await asyncio.sleep(1)
            lag = max(0.0, received["bytes"] / BYTES_PER_SECOND - fed["seconds"])
            await safe_send(ws, {"type": "lag", "seconds": round(lag, 1)})

    async def receiver():
        # returns on stop or unexpected disconnect
        while True:
            data = await ws.receive()
            if data["type"] == "websocket.disconnect":
                return
            raw = data.get("bytes")
            if raw is not None:
                if len(raw) > MAX_FRAME_BYTES:
                    continue
                raw = raw[:len(raw) // 2 * 2]
                if raw:
                    pcm_file.write(raw)
                    received["bytes"] += len(raw)
                    in_q.put(raw)
            elif data.get("text"):
                try:
                    if json.loads(data["text"]).get("type") == "stop":
                        return
                except ValueError:
                    pass

    fwd_task = asyncio.create_task(forwarder())
    lag_t = asyncio.create_task(lag_task())
    recv_task = asyncio.create_task(receiver())
    done_waiter = asyncio.create_task(done_evt.wait())

    try:
        await asyncio.wait({recv_task, done_waiter}, return_when=asyncio.FIRST_COMPLETED)
        if not done_evt.is_set():
            # stop requested (or connection lost): let the worker finish the backlog
            in_q.put(None)
            await safe_send(ws, {"type": "status", "text": "Elaboro l'audio rimasto...",
                                 "busy": True})
            try:
                await asyncio.wait_for(done_evt.wait(), STOP_TIMEOUT_S)
            except asyncio.TimeoutError:
                proc.terminate()
                result.update({"type": "error", "text": "Timeout nell'elaborazione finale"})
                await safe_send(ws, result)
        recv_task.cancel()
        lag_t.cancel()
        pcm_file.close()

        converted = False
        try:
            await asyncio.to_thread(pcm_to_wav, pcm_path, wav_path)
            converted = True
        except Exception:
            pass
        if result.get("type") == "stopped":
            await safe_send(ws, {"type": "saved", "dir": str(session_dir),
                                 "md": result.get("path", ""),
                                 "wav": str(wav_path) if converted else ""})
    finally:
        for t in (fwd_task, lag_t, recv_task, done_waiter):
            t.cancel()
        reader_stop.set()
        if not pcm_file.closed:
            pcm_file.close()
        await asyncio.to_thread(proc.join, 5)
        if proc.is_alive():
            proc.terminate()
        for q in (in_q, out_q):
            try:
                q.close()
                q.cancel_join_thread()
            except Exception:
                pass
        await safe_close(ws)


def main() -> None:
    parser = argparse.ArgumentParser(description="Trascrizione live su localhost")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR),
                        help="Cartella delle sessioni (default: %(default)s)")
    args = parser.parse_args()

    app = create_app(Path(args.output_dir), args.port)
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, args=(f"http://127.0.0.1:{args.port}/",)).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
