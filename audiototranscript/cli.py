"""Riga di comando: trascrive file o cartelle di audio/video in Markdown."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from audiototranscript import __version__, transcriber

AUDIO_EXTENSIONS = {ext.lstrip("*") for ext in transcriber.MEDIA_FILETYPES}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="audiototranscript",
        description="Trascrive file audio/video in Markdown usando faster-whisper (CPU).",
    )
    parser.add_argument("inputs", nargs="+", metavar="INPUT", help="File o cartelle da elaborare")
    parser.add_argument("--model", default=transcriber.DEFAULT_MODEL,
                        help="Modello faster-whisper (default: %(default)s)")
    parser.add_argument("--language", default=transcriber.DEFAULT_LANGUAGE,
                        help="Lingua audio (default: %(default)s)")
    parser.add_argument("--out-dir", default=None,
                        help="Cartella di output (default: stessa del file di input)")
    parser.add_argument("--glossary", default=None,
                        help="File di testo con glossario per initial_prompt")
    parser.add_argument("--pause", type=float, default=transcriber.PAUSE_SECONDS,
                        help="Pausa in secondi che separa due paragrafi (default: %(default)s)")
    parser.add_argument("--beam-size", type=int, default=1, help="Beam size (default: %(default)s)")
    parser.add_argument("--threads", type=int, default=transcriber.default_threads(),
                        help="Thread CPU (default: metà dei core: %(default)s)")
    parser.add_argument("--max-seconds", type=float, default=None,
                        help="Ferma dopo N secondi di audio (per test rapidi)")
    parser.add_argument("--force", action="store_true",
                        help="Rielabora anche se il .md di output esiste già")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def collect_inputs(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            files.extend(sorted(f for f in p.rglob("*")
                                if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS))
        elif p.is_file():
            files.append(p)
        else:
            print(f"Avviso: percorso non trovato, ignorato: {p}", file=sys.stderr)

    seen: set[Path] = set()
    unique: list[Path] = []
    for f in files:
        resolved = f.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(f)
    return unique


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    files = collect_inputs(args.inputs)
    if not files:
        print("Nessun file da elaborare.", file=sys.stderr)
        return 1
    try:
        glossary = transcriber.load_glossary(args.glossary)
    except OSError as exc:
        print(f"Impossibile leggere il glossario: {exc}", file=sys.stderr)
        return 1

    last_report = [0.0]

    def status_cb(text, busy=False):
        print(text, file=sys.stderr)

    def progress_cb(pct):
        now = time.monotonic()
        if pct >= 100 or now - last_report[0] >= 10:
            last_report[0] = now
            print(f"  {pct:3d}%", file=sys.stderr)

    try:
        print(f"Carico modello {args.model} (int8, CPU, {args.threads} thread)...", file=sys.stderr)
        model = transcriber.load_model(args.model, status_cb, args.threads)
    except Exception as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1

    had_error = False
    for src in files:
        print(f"\n=== {src} ===", file=sys.stderr)
        try:
            out = transcriber.transcribe_file(
                src, args.model, progress_cb, status_cb, language=args.language,
                model=model, out_dir=args.out_dir, glossary=glossary, pause=args.pause,
                beam_size=args.beam_size, max_seconds=args.max_seconds,
                on_exists="overwrite" if args.force else "skip",
            )
            if out:
                print(f"Completato: {out}", file=sys.stderr)
        except KeyboardInterrupt:
            print("\nInterrotto dall'utente. File .md.part lasciato sul disco.", file=sys.stderr)
            return 130
        except Exception as exc:
            had_error = True
            print(f"Errore su {src}: {exc}", file=sys.stderr)
    return 1 if had_error else 0


if __name__ == "__main__":
    sys.exit(main())
