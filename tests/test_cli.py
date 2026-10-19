from audiototranscript import cli


def test_collect_inputs_files_dirs_and_duplicates(tmp_path, capsys):
    (tmp_path / "sub").mkdir()
    a = tmp_path / "a.mp3"
    b = tmp_path / "sub" / "b.WAV"
    for f in (a, b, tmp_path / "note.txt"):
        f.write_bytes(b"x")
    found = cli.collect_inputs([str(tmp_path), str(a), str(tmp_path / "manca.mp3")])
    assert sorted(p.name for p in found) == ["a.mp3", "b.WAV"]
    assert "non trovato" in capsys.readouterr().err


def test_parse_args_defaults():
    args = cli.parse_args(["x.mp3"])
    assert args.model == "medium" and args.language == "it" and not args.force


def test_main_without_inputs_returns_error(tmp_path, capsys):
    assert cli.main([str(tmp_path)]) == 1
    assert "Nessun file" in capsys.readouterr().err


def test_main_missing_glossary(tmp_path, capsys):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x")
    assert cli.main([str(audio), "--glossary", str(tmp_path / "no.txt")]) == 1
    assert "glossario" in capsys.readouterr().err
