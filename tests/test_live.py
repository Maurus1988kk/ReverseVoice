import numpy as np
import pytest

from audiototranscript import live_core
from audiototranscript.live_core import MAX_BLOCK_S, SAMPLE_RATE, Segmenter, keep_segment

rng = np.random.default_rng(0)


def speech(s):
    return rng.normal(0, 0.1, int(s * SAMPLE_RATE)).astype(np.float32)


def silence(s):
    return rng.normal(0, 0.002, int(s * SAMPLE_RATE)).astype(np.float32)


def run(audio):
    seg = Segmenter()
    blocks = []
    for i in range(0, len(audio), 4096):
        blocks += seg.feed(audio[i:i + 4096])
    return seg, blocks


def test_segmenter_cuts_on_pauses():
    _, blocks = run(np.concatenate([speech(4), silence(1), speech(3), silence(1)]))
    assert len(blocks) == 2
    assert 4.0 <= len(blocks[0].audio) / SAMPLE_RATE <= 5.5
    assert blocks[1].start_sample > blocks[0].start_sample >= 0


def test_segmenter_caps_block_length():
    _, blocks = run(speech(25))
    assert blocks
    assert all(len(b.audio) / SAMPLE_RATE <= MAX_BLOCK_S + 0.5 for b in blocks)


def test_segmenter_ignores_silence():
    seg, blocks = run(silence(10))
    assert not blocks
    assert seg.buffered_seconds <= live_core.IDLE_MAX_S + 0.1
    assert abs(seg.fed_seconds - 10) < 1e-6


def test_segmenter_accepts_int16_and_partial_frames():
    seg = Segmenter()
    pcm = (speech(3) * 32768).astype(np.int16)
    got = []
    for i in range(0, len(pcm), 1000):
        got += seg.feed(pcm[i:i + 1000])
    got += seg.flush()
    assert len(got) == 1


def test_keep_segment():
    assert not keep_segment("", 0.0, 0.0)
    assert not keep_segment("Sottotitoli creati dalla comunità Amara.org", 0.0, 0.0)
    assert keep_segment("Buongiorno a tutti", 0.1, -0.2)


# --- server ---
pytest.importorskip("httpx")


def make_client(tmp_path, port=8765):
    from fastapi.testclient import TestClient

    from audiototranscript.live_server import create_app

    return TestClient(create_app(tmp_path, port))


def test_slugify():
    from audiototranscript.live_server import slugify

    assert slugify("Lezione n.1: È l'ora!") == "lezione-n-1-e-l-ora"
    assert slugify("../../etc/passwd") == "etc-passwd"
    assert slugify("a" * 100) == "a" * 40
    assert slugify("???") == ""


def test_index_served(tmp_path):
    r = make_client(tmp_path).get("/")
    assert r.status_code == 200 and "Trascrizione live" in r.text


def test_websocket_rejects_foreign_origin(tmp_path):
    from starlette.websockets import WebSocketDisconnect

    client = make_client(tmp_path)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={"origin": "http://evil.example"}):
            pass
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws"):  # senza Origin
            pass


def test_websocket_rejects_invalid_start_message(tmp_path):
    client = make_client(tmp_path)
    with client.websocket_connect("/ws", headers={"origin": "http://127.0.0.1:8765"}) as ws:
        ws.send_text('{"type": "boh"}')
        assert ws.receive_json()["type"] == "error"
