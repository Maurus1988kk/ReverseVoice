"""Transcription logic (no GUI, faster-whisper imported lazily)."""
from __future__ import annotations

import datetime
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

MODELS = ("small", "medium", "large-v3-turbo")
DEFAULT_MODEL = "medium"
DEFAULT_LANGUAGE = "it"
PAUSE_SECONDS = 2.0        # pausa che apre un nuovo paragrafo
MAX_PARAGRAPH_CHARS = 700  # lunghezza oltre la quale si apre un nuovo paragrafo
MEDIA_FILETYPES = ["*.mp4", "*.m4a", "*.mp3", "*.wav", "*.mkv", "*.webm", "*.ogg", "*.flac"]


def fmt_hms(seconds: float) -> str:
    total = int(max(0, seconds))
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def unique_output_path(audio_path: Path) -> Path:
    audio_path = Path(audio_path)
    out = audio_path.with_name(audio_path.stem + ".md")
    n = 2
    while out.exists():
        out = audio_path.with_name(f"{audio_path.stem}_{n}.md")
        n += 1
    return out


class ParagraphBuilder:
    def __init__(self, pause=PAUSE_SECONDS, max_chars=MAX_PARAGRAPH_CHARS):
        self.pause = pause
        self.max_chars = max_chars
        self._start = 0.0
        self._text = ""
        self._last_end = 0.0
        self._last_text = None

    def add(self, start: float, end: float, text: str) -> list[tuple[float, str]]:
        text = text.strip()
        if not text or (self._last_text is not None and text.lower() == self._last_text):
            return []
        self._last_text = text.lower()
        done = []
        if self._text and (
            start - self._last_end > self.pause
            or len(self._text) + 1 + len(text) > self.max_chars
        ):
            done.append((self._start, self._text))
            self._text = ""
        if self._text:
            self._text += " " + text
        else:
            self._start = start
            self._text = text
        self._last_end = end
        return done

    def current(self) -> tuple[float, str] | None:
        return (self._start, self._text) if self._text else None

    def flush(self) -> list[tuple[float, str]]:
        done = [(self._start, self._text)] if self._text else []
        self._text = ""
        self._last_text = None
        self._last_end = 0.0
        self._start = 0.0
        return done


def ensure_model(model_name: str, status_cb) -> str:
    from faster_whisper.utils import download_model

    try:
        return download_model(model_name, local_files_only=True)
    except Exception:
        pass
    status_cb("Download del modello (solo la prima volta)...", busy=True)
    try:
        return download_model(model_name)
    except Exception as exc:
        raise RuntimeError("Impossibile scaricare il modello: controlla la connessione") from exc


def default_threads() -> int:
    return max(1, (os.cpu_count() or 2) // 2)


def load_model(model_name: str, status_cb, threads: int | None = None):
    from faster_whisper import WhisperModel

    path = ensure_model(model_name, status_cb)
    status_cb("Caricamento modello...", busy=True)
    return WhisperModel(
        path,
        device="cpu",
        compute_type="int8",
        cpu_threads=threads or default_threads(),
    )


def _transcribe(model, audio, language, beam_size=1, prompt=None):
    return model.transcribe(
        audio,
        language=language,
        beam_size=beam_size,
        initial_prompt=prompt,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=False,
        word_timestamps=False,
    )


def load_glossary(path) -> str | None:
    """Testo del glossario per initial_prompt (max 800 caratteri), o None."""
    if not path:
        return None
    return Path(path).read_text(encoding="utf-8").strip()[:800] or None


def transcribe_file(path, model_name, progress_cb, status_cb,
                    language=DEFAULT_LANGUAGE, tmp_dir=None, *, model=None,
                    out_dir=None, glossary=None, pause=PAUSE_SECONDS, beam_size=1,
                    threads=None, max_seconds=None, on_exists="rename") -> Path | None:
    """Trascrive un file in Markdown e restituisce il percorso del .md.

    on_exists: "rename" (aggiunge _2, _3...), "skip" (restituisce None) o "overwrite".
    `model` permette di riusare un modello già caricato (es. per più file).
    """
    t0 = time.monotonic()
    audio = Path(path)
    if not audio.is_file() or not os.access(audio, os.R_OK):
        raise FileNotFoundError(f"File non trovato o non leggibile: {audio}")
    if on_exists not in ("rename", "skip", "overwrite"):
        raise ValueError(f"on_exists non valido: {on_exists}")

    out_dir = Path(out_dir) if out_dir else audio.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{audio.stem}.md"
    if out.exists():
        if on_exists == "skip":
            status_cb(f"Salto (esiste già): {out}", busy=False)
            return None
        if on_exists == "rename":
            out = unique_output_path(out_dir / audio.name)

    if model is None:
        model = load_model(model_name, status_cb, threads)
    status_cb("Trascrizione in corso...", busy=False)

    own_tmp = None
    part = out_dir / f"{audio.stem}.md.part"
    try:
        try:
            segments, info = _transcribe(model, str(audio), language, beam_size, glossary)
        except Exception as exc:
            if not shutil.which("ffmpeg"):
                raise RuntimeError(
                    f"Impossibile decodificare il file ({exc}). "
                    "Installa ffmpeg per i formati difficili."
                ) from exc
            if tmp_dir is None:
                own_tmp = tmp_dir = tempfile.mkdtemp(prefix="transcriber_")
            wav_path = str(Path(tmp_dir) / "audio.wav")
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(audio), "-vn", "-ac", "1", "-ar", "16000", wav_path],
                check=True, capture_output=True,
            )
            segments, info = _transcribe(model, wav_path, language, beam_size, glossary)

        builder = ParagraphBuilder(pause=pause)
        last_pct = -1
        with open(part, "w", encoding="utf-8") as f:
            def write(paragraphs):
                for start, text in paragraphs:
                    f.write(f"**[{fmt_hms(start)}]** {text}\n\n")
                    f.flush()

            for seg in segments:
                if info.duration > 0:
                    pct = min(100, int(seg.end / info.duration * 100))
                    if pct != last_pct:
                        last_pct = pct
                        progress_cb(pct)
                write(builder.add(seg.start, seg.end, seg.text))
                if max_seconds is not None and seg.end >= max_seconds:
                    break
            write(builder.flush())
        progress_cb(100)

        body = part.read_text(encoding="utf-8")
        header = (
            f"# Trascrizione: {audio.stem}\n\n"
            f"- **File**: {audio.name}\n"
            f"- **Modello**: {model_name} (int8, CPU)\n"
            f"- **Lingua**: {language}\n"
            f"- **Durata audio**: {fmt_hms(info.duration)}\n"
            f"- **Tempo di elaborazione**: {fmt_hms(time.monotonic() - t0)}\n"
            f"- **Data**: {datetime.date.today().isoformat()}\n\n"
            "---\n\n"
        )
        out.write_text(header + body, encoding="utf-8")
        part.unlink()
        return out
    finally:
        if own_tmp:
            shutil.rmtree(own_tmp, ignore_errors=True)
