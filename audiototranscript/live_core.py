"""Live transcription core: audio segmenter, segment filters, worker process.

No fastapi/uvicorn imports here. numpy and faster-whisper are used lazily/only here.
"""
import os
import sys
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000
FRAME_MS = 30
MIN_BLOCK_S = 2.5        # lunghezza minima di un blocco prima di tagliare su una pausa
MAX_BLOCK_S = 20.0       # lunghezza massima di un blocco (sotto la finestra di 30 s di Whisper)
SILENCE_CUT_S = 0.6      # silenzio continuo che autorizza il taglio
LEAD_IN_S = 0.3          # silenzio da conservare prima dell'inizio del parlato
TRAIL_KEEP_S = 0.25      # silenzio da conservare in coda a un blocco
IDLE_MAX_S = 1.0         # in assenza di parlato, il buffer non supera questa lunghezza
MIN_FLUSH_S = 0.5        # al flush finale, scarta blocchi più corti di così
ENERGY_FLOOR = 0.008     # soglia minima di energia (RMS normalizzato 0..1)
NOISE_PERCENTILE = 20
NOISE_WINDOW_S = 10.0
THRESH_MULT = 2.5
SPEECH_START_FRAMES = 3  # frame voiced consecutivi per considerare iniziato il parlato
MAX_SEGMENT_NO_SPEECH_PROB = 0.6
MIN_SEGMENT_AVG_LOGPROB = -1.0
HALLUCINATION_MAX_LEN = 80
HALLUCINATION_SUBSTRINGS = ("amara.org", "sottotitoli e revisione", "sottotitoli creati",
                            "grazie per la visione", "iscriviti al canale")

FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000


def _frames(seconds: float) -> int:
    return max(1, int(round(seconds * 1000 / FRAME_MS)))


@dataclass
class Block:
    start_sample: int
    audio: np.ndarray


class Segmenter:
    """Energy-based splitter: turns a PCM stream into speech blocks."""

    def __init__(self):
        self._rem = np.zeros(0, dtype=np.float32)
        self._total = 0
        self._buf_start = 0
        self._frames: list[np.ndarray] = []
        self._rms: list[float] = []
        self._voiced: list[bool] = []
        self._run = 0      # trailing consecutive voiced frames
        self._sil = 0      # trailing consecutive unvoiced frames
        self._speech = False
        self._frame_idx = 0
        self._noise_hist: deque = deque()  # (frame_idx, rms) of unvoiced frames

    @property
    def fed_seconds(self) -> float:
        return self._total / SAMPLE_RATE

    @property
    def buffered_seconds(self) -> float:
        return len(self._frames) * FRAME_MS / 1000

    def feed(self, pcm: np.ndarray) -> list[Block]:
        pcm = np.asarray(pcm)
        if pcm.dtype == np.int16:
            pcm = pcm.astype(np.float32) / 32768.0
        else:
            pcm = pcm.astype(np.float32, copy=False)
        self._total += len(pcm)
        data = np.concatenate((self._rem, pcm)) if len(self._rem) else pcm
        n = len(data) // FRAME_SAMPLES
        blocks = []
        for i in range(n):
            blocks.extend(self._push(data[i * FRAME_SAMPLES:(i + 1) * FRAME_SAMPLES]))
        self._rem = data[n * FRAME_SAMPLES:].copy()
        return blocks

    def flush(self) -> list[Block]:
        blocks = []
        if self._speech and self.buffered_seconds >= MIN_FLUSH_S:
            blocks.append(self._emit_all())
        self._reset_buffer(len(self._frames))
        self._rem = np.zeros(0, dtype=np.float32)
        return blocks

    # --- internals ---

    def _noise_floor(self) -> float:
        limit = self._frame_idx - _frames(NOISE_WINDOW_S)
        while self._noise_hist and self._noise_hist[0][0] < limit:
            self._noise_hist.popleft()
        if not self._noise_hist:
            return 0.0
        return float(np.percentile([r for _, r in self._noise_hist], NOISE_PERCENTILE))

    def _push(self, frame: np.ndarray) -> list[Block]:
        rms = float(np.sqrt(np.mean(frame * frame)))
        voiced = rms > max(ENERGY_FLOOR, THRESH_MULT * self._noise_floor())
        if not voiced:
            # only non-speech frames feed the noise estimate
            self._noise_hist.append((self._frame_idx, rms))
        self._frame_idx += 1
        self._frames.append(frame)
        self._rms.append(rms)
        self._voiced.append(voiced)
        if voiced:
            self._run += 1
            self._sil = 0
        else:
            self._run = 0
            self._sil += 1
        if not self._speech and self._run >= SPEECH_START_FRAMES:
            self._speech = True

        if not self._speech:
            keep = min(_frames(IDLE_MAX_S), _frames(LEAD_IN_S) + self._run)
            extra = len(self._frames) - keep
            if extra > 0:
                self._drop_front(extra)
            return []

        n = len(self._frames)
        if self._sil >= _frames(SILENCE_CUT_S) and n >= _frames(MIN_BLOCK_S):
            return [self._emit_all()]
        if n >= _frames(MAX_BLOCK_S):
            return [self._cut_at_minimum()]
        return []

    def _drop_front(self, k: int) -> None:
        del self._frames[:k], self._rms[:k], self._voiced[:k]
        self._buf_start += k * FRAME_SAMPLES

    def _reset_buffer(self, consumed: int) -> None:
        self._buf_start += consumed * FRAME_SAMPLES
        self._frames, self._rms, self._voiced = [], [], []
        self._run = self._sil = 0
        self._speech = False

    def _emit_all(self) -> Block:
        n = len(self._frames)
        end = n - max(0, self._sil - _frames(TRAIL_KEEP_S))
        block = Block(self._buf_start, np.concatenate(self._frames[:end]))
        self._reset_buffer(n)
        return block

    def _cut_at_minimum(self) -> Block:
        n = len(self._frames)
        lo = max(0, n - _frames(4.0))
        hi = max(lo + 1, n - _frames(0.1))
        idx = lo + int(np.argmin(self._rms[lo:hi]))
        end = idx + 1
        block = Block(self._buf_start, np.concatenate(self._frames[:end]))
        self._drop_front(end)
        # recompute speech/run/sil state for the remainder
        self._run = self._sil = 0
        self._speech = False
        for v in self._voiced:
            if v:
                self._run += 1
                self._sil = 0
                if self._run >= SPEECH_START_FRAMES:
                    self._speech = True
            else:
                self._run = 0
                self._sil += 1
        return block


def keep_segment(text: str, no_speech_prob: float, avg_logprob: float) -> bool:
    text = (text or "").strip()
    if not text:
        return False
    if no_speech_prob > MAX_SEGMENT_NO_SPEECH_PROB and avg_logprob < MIN_SEGMENT_AVG_LOGPROB:
        return False
    low = text.lower()
    if len(text) <= HALLUCINATION_MAX_LEN and any(s in low for s in HALLUCINATION_SUBSTRINGS):
        return False
    return True


SOURCE_LABELS = {
    "mic": "microfono",
    "tab": "scheda del browser",
    "both": "microfono + scheda",
}


def worker_main(in_q, out_q, cfg):
    part = None
    try:
        try:
            if sys.platform == "win32":
                import ctypes
                k = ctypes.windll.kernel32
                k.SetPriorityClass(k.GetCurrentProcess(), 0x00004000)
            else:
                os.nice(10)
        except Exception:
            pass

        from audiototranscript import transcriber

        def status_cb(text, busy=False):
            out_q.put({"type": "status", "text": text, "busy": busy})

        model = transcriber.load_model(cfg["model"], status_cb)
        out_q.put({"type": "ready"})

        session_dir = Path(cfg["session_dir"])
        part_path = session_dir / "trascrizione.md.part"
        part = open(part_path, "w", encoding="utf-8")
        seg = Segmenter()
        builder = transcriber.ParagraphBuilder()
        prompt = (cfg.get("glossary") or "")[:600] or None

        def emit_paragraphs(paragraphs):
            for start, text in paragraphs:
                part.write(f"**[{transcriber.fmt_hms(start)}]** {text}\n\n")
                part.flush()
                out_q.put({"type": "paragraph", "start": start, "text": text})

        def handle_block(block):
            segments, _ = model.transcribe(
                block.audio, language=cfg["language"], beam_size=1,
                vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
                condition_on_previous_text=False,
                initial_prompt=prompt,
                word_timestamps=False,
            )
            offset = block.start_sample / SAMPLE_RATE
            for s in segments:
                if not keep_segment(s.text, s.no_speech_prob, s.avg_logprob):
                    continue
                emit_paragraphs(builder.add(offset + s.start, offset + s.end, s.text))
            cur = builder.current()
            out_q.put({"type": "current",
                       "start": cur[0] if cur else None,
                       "text": cur[1] if cur else ""})

        last_clock = 0.0
        while True:
            item = in_q.get()
            if item is None:
                break
            for block in seg.feed(np.frombuffer(item, dtype="<i2")):
                handle_block(block)
            now = time.monotonic()
            if now - last_clock >= 1.0:
                last_clock = now
                out_q.put({"type": "clock", "fed": seg.fed_seconds})

        for block in seg.flush():
            handle_block(block)
        emit_paragraphs(builder.flush())
        out_q.put({"type": "current", "start": None, "text": ""})
        part.close()
        part = None

        body = part_path.read_text(encoding="utf-8")
        now = datetime.now()
        title = cfg.get("title") or now.strftime("%Y-%m-%d %H:%M")
        header = (
            f"# Trascrizione live: {title}\n\n"
            f"- **Sorgente**: {SOURCE_LABELS.get(cfg.get('source'), cfg.get('source'))}\n"
            f"- **Modello**: {cfg['model']} (int8, CPU, live)\n"
            f"- **Lingua**: {cfg['language']}\n"
            f"- **Durata registrazione**: {transcriber.fmt_hms(seg.fed_seconds)}\n"
            f"- **Data**: {now.strftime('%Y-%m-%d %H:%M')}\n"
            "- **Audio**: audio.wav\n\n"
            "---\n\n"
        )
        md = session_dir / "trascrizione.md"
        md.write_text(header + body, encoding="utf-8")
        part_path.unlink()
        out_q.put({"type": "stopped", "path": str(md)})
    except Exception as exc:
        if part is not None:
            try:
                part.close()
            except Exception:
                pass
        out_q.put({"type": "error", "text": (str(exc) or type(exc).__name__)[:200]})
