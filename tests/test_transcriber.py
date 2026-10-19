from types import SimpleNamespace

import pytest

from audiototranscript import transcriber
from audiototranscript.transcriber import MAX_PARAGRAPH_CHARS, ParagraphBuilder, fmt_hms


def noop_status(text, busy=False):
    pass


class FakeModel:
    """Imita WhisperModel.transcribe senza scaricare modelli."""

    def __init__(self, segments, duration=10.0):
        self.segments = [SimpleNamespace(start=a, end=b, text=t) for a, b, t in segments]
        self.duration = duration
        self.kwargs = None

    def transcribe(self, audio, **kwargs):
        self.kwargs = kwargs
        return iter(self.segments), SimpleNamespace(duration=self.duration)


def test_fmt_hms():
    assert fmt_hms(3725.9) == "01:02:05"
    assert fmt_hms(-5) == "00:00:00"


def test_paragraph_joins_close_segments():
    b = ParagraphBuilder()
    assert b.add(0, 1, "Ciao") == []
    assert b.add(1.5, 2, "mondo") == []
    assert b.flush() == [(0, "Ciao mondo")]


def test_paragraph_splits_on_pause():
    b = ParagraphBuilder()
    b.add(0, 1, "uno")
    assert b.add(4, 5, "due") == [(0, "uno")]
    assert b.flush() == [(4, "due")]


def test_paragraph_skips_consecutive_duplicates():
    b = ParagraphBuilder()
    b.add(0, 1, "uno")
    assert b.add(1, 2, " UNO ") == []
    assert b.flush() == [(0, "uno")]


def test_paragraph_splits_on_length():
    b = ParagraphBuilder()
    b.add(0, 1, "a" * (MAX_PARAGRAPH_CHARS - 5))
    assert len(b.add(1, 2, "b" * 10)) == 1
    assert b.flush() == [(1, "b" * 10)]


def test_paragraph_flush_and_current():
    b = ParagraphBuilder()
    assert b.current() is None
    b.add(2, 3, "aperto")
    assert b.current() == (2, "aperto")
    assert b.flush() == [(2, "aperto")]
    assert b.current() is None and b.flush() == []


def test_unique_output_path(tmp_path):
    audio = tmp_path / "x.mp3"
    assert transcriber.unique_output_path(audio) == tmp_path / "x.md"
    (tmp_path / "x.md").write_text("")
    assert transcriber.unique_output_path(audio) == tmp_path / "x_2.md"
    (tmp_path / "x_2.md").write_text("")
    assert transcriber.unique_output_path(audio) == tmp_path / "x_3.md"


def test_load_glossary(tmp_path):
    assert transcriber.load_glossary(None) is None
    f = tmp_path / "g.txt"
    f.write_text("  \n", encoding="utf-8")
    assert transcriber.load_glossary(f) is None
    f.write_text("a" * 1000, encoding="utf-8")
    assert len(transcriber.load_glossary(f)) == 800


def test_transcribe_file_writes_markdown(tmp_path):
    audio = tmp_path / "lezione.wav"
    audio.write_bytes(b"x")
    model = FakeModel([(0, 2, "Buongiorno"), (2.5, 4, "a tutti"), (9, 10, "Fine")])
    progress = []
    out = transcriber.transcribe_file(
        audio, "small", progress.append, noop_status, model=model, glossary="Kubernetes"
    )
    assert out == tmp_path / "lezione.md"
    text = out.read_text(encoding="utf-8")
    assert "# Trascrizione: lezione" in text
    assert "**[00:00:00]** Buongiorno a tutti" in text
    assert "**[00:00:09]** Fine" in text
    assert progress[-1] == 100
    assert model.kwargs["initial_prompt"] == "Kubernetes"
    assert not (tmp_path / "lezione.md.part").exists()


def test_transcribe_file_out_dir_and_existing(tmp_path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    out_dir = tmp_path / "out"

    def run(on_exists):
        return transcriber.transcribe_file(
            audio, "small", lambda p: None, noop_status,
            model=FakeModel([(0, 1, "ciao")]), out_dir=out_dir, on_exists=on_exists,
        )

    first = run("skip")
    assert first == out_dir / "a.md"
    assert run("skip") is None
    assert run("rename") == out_dir / "a_2.md"
    assert run("overwrite") == out_dir / "a.md"


def test_transcribe_file_max_seconds(tmp_path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    model = FakeModel([(0, 5, "primo"), (30, 35, "secondo"), (60, 65, "terzo")], duration=70)
    out = transcriber.transcribe_file(
        audio, "small", lambda p: None, noop_status, model=model, max_seconds=30
    )
    text = out.read_text(encoding="utf-8")
    assert "primo" in text and "secondo" in text and "terzo" not in text


def test_transcribe_file_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        transcriber.transcribe_file(tmp_path / "nope.wav", "small", lambda p: None, noop_status)


def test_transcribe_file_invalid_on_exists(tmp_path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    with pytest.raises(ValueError):
        transcriber.transcribe_file(audio, "small", lambda p: None, noop_status, on_exists="boh")
