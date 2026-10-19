"""Clonación local: codificador MP3 incremental y proveedor LocalClone con un modelo MLX simulado."""
import asyncio
import io
import threading
from types import SimpleNamespace

import av
import numpy as np
import pytest

from app.audio import to_wav_bytes
from app.config import Settings
from app.clone_tts import SAMPLE_RATE, LocalClone
from app.mp3 import Mp3Stream

pytest.importorskip("mlx.core")  # el proveedor convierte la referencia a mx.array


def tone(seconds, hz=220):
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    return (0.4 * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def mp3_duration(data: bytes) -> float:
    with av.open(io.BytesIO(data)) as c:
        return float(c.duration) / 1_000_000


# ── MP3 incremental ──────────────────────────────────────────────────────────

def test_mp3_stream_is_incremental_plain_and_decodable():
    enc, chunks = Mp3Stream(), []
    for s in range(0, SAMPLE_RATE * 3, int(0.96 * SAMPLE_RATE)):
        chunks.append(enc.feed(tone(3)[s : s + int(0.96 * SAMPLE_RATE)]))
    chunks.append(enc.finish())
    data = b"".join(chunks)
    assert len(chunks[0]) > 0  # el primer trozo ya se puede enviar
    assert not data.startswith(b"ID3") and b"Xing" not in data[:300] and b"Info" not in data[:300]
    assert data[0] == 0xFF  # empieza directamente en un frame MP3
    assert 2.95 < mp3_duration(data) < 3.2


def test_concatenated_mp3_sentences_keep_total_duration():
    parts = []
    for _ in range(3):
        e = Mp3Stream()
        parts.append(e.feed(tone(1.0)) + e.finish())
    assert 3.0 < mp3_duration(b"".join(parts)) < 3.3


# ── LocalClone ───────────────────────────────────────────────────────────────

class FakeModel:
    def __init__(self, chunks_per_call=3):
        self.calls, self.threads, self.n = [], set(), chunks_per_call
        self.produced = 0

    def generate(self, **kw):
        self.threads.add(threading.get_ident())
        self.calls.append(kw)
        for _ in range(self.n):
            self.produced += 1
            yield SimpleNamespace(audio=tone(0.96), sample_rate=SAMPLE_RATE)


@pytest.fixture
def clone(tmp_path, monkeypatch):
    voices = tmp_path / "voices"
    voices.mkdir()
    (voices / "rectora.wav").write_bytes(to_wav_bytes(tone(6.0, hz=180), SAMPLE_RATE))
    (voices / "rectora.txt").write_text("Texto exacto de la referencia.", encoding="utf-8")
    transcripts = []

    async def transcribe(wav: bytes) -> str:
        transcripts.append(wav)
        return "Esto lo transcribió Whisper."

    monkeypatch.setattr(LocalClone, "supported_platform", staticmethod(lambda: True))
    c = LocalClone(Settings(voices_dir=voices), transcribe)
    model = FakeModel()
    ensure_threads = []

    def ensure():
        ensure_threads.append(threading.get_ident())
        return model

    monkeypatch.setattr(c, "_ensure_model", ensure)
    return c, model, voices, transcripts, ensure_threads


async def collect(c, text="Hola a todos los presentes.", speaker="rectora"):
    return [d async for d in c.synthesize_stream(text, speaker)]


async def test_streams_mp3_chunks_with_reference_text_and_spanish(clone):
    c, model, _, transcripts, _ = clone
    chunks = await collect(c)
    assert len(chunks) >= 3 and 2.8 < mp3_duration(b"".join(chunks)) < 3.1
    kw = model.calls[0]
    assert kw["text"] == "Hola a todos los presentes." and kw["lang_code"] == "spanish" and kw["stream"] is True
    assert kw["ref_text"] == "Texto exacto de la referencia." and transcripts == []  # el .txt manda; no hace falta Whisper
    assert float(kw["ref_audio"].shape[0]) / SAMPLE_RATE <= 12.0 and abs(float(np.sqrt((np.array(kw["ref_audio"]) ** 2).mean())) - 0.1) < 0.01


async def test_model_is_always_used_from_one_dedicated_thread(clone):
    c, model, *_ , ensure_threads = clone
    await asyncio.gather(collect(c, "uno"), collect(c, "dos"), collect(c, "tres"))
    assert len(model.threads) == 1 and set(ensure_threads) == model.threads  # MLX exige el mismo hilo
    assert threading.get_ident() not in model.threads  # y no es el del servidor asyncio


async def test_concurrent_sentences_do_not_interleave(clone):
    c, model, *_ = clone
    results = await asyncio.gather(*(collect(c, f"frase {i}") for i in range(3)))
    assert [call["text"] for call in model.calls] == ["frase 0", "frase 1", "frase 2"]  # en orden de llegada
    assert all(len(r) >= 3 for r in results)


async def test_missing_transcript_is_made_with_whisper_once_and_saved(clone):
    c, _, voices, transcripts, _ = clone
    (voices / "rectora.txt").unlink()
    await collect(c); await collect(c)
    assert len(transcripts) == 1 and (voices / "rectora.txt").read_text(encoding="utf-8") == "Esto lo transcribió Whisper."


async def test_changing_the_reference_file_is_picked_up(clone):
    c, model, voices, *_ = clone
    sig1 = c.signature("rectora")
    await collect(c)
    (voices / "rectora.txt").write_text("Otro texto.", encoding="utf-8")
    (voices / "rectora.wav").write_bytes(to_wav_bytes(tone(7.0, hz=150), SAMPLE_RATE))
    assert c.signature("rectora") != sig1  # invalida las preguntas pregrabadas con la voz vieja
    await collect(c)
    assert model.calls[1]["ref_text"] == "Otro texto."


async def test_closing_the_stream_stops_generation(clone):
    c, model, *_ = clone
    model.n = 40
    gen = c.synthesize_stream("frase muy larga", "rectora")
    await anext(gen)
    await gen.aclose()
    await asyncio.sleep(0.5)
    assert model.produced < 40


def test_available_needs_platform_and_a_reference_file(clone, monkeypatch):
    c, _, voices, *_ = clone
    assert c.available("rectora") and not c.available("oswaldo")  # solo hay voz de la Rectora
    (voices / "oswaldo.m4a").write_bytes(b"x")
    assert c.available("oswaldo")  # acepta otros formatos
    monkeypatch.setattr(LocalClone, "supported_platform", staticmethod(lambda: False))
    assert not c.available("rectora")


async def test_no_reference_gives_actionable_error(clone):
    c, *_ = clone
    with pytest.raises(RuntimeError, match="voices/oswaldo.wav"):
        await collect(c, speaker="oswaldo")


# ── Preparación de la voz de referencia ──────────────────────────────────────

def test_prepare_voice_picks_a_voiced_window_between_pauses_and_warns():
    from scripts.prepare_voice import RATE, analyze, best_window, verdict

    rng = np.random.default_rng(0)
    word = tone(1.2, hz=200) * 0.4
    pause = (rng.normal(size=int(0.5 * RATE)) * 0.0005).astype(np.float32)
    long_audio = np.concatenate([np.concatenate([word, pause]) for _ in range(25)])  # ≈ 42 s
    window = best_window(long_audio, 12.0)
    assert 7.0 < len(window) / RATE <= 12.0
    assert not any("Solo hay" in m for m in verdict(analyze(window)))
    short = analyze(tone(3.0))
    assert any("Solo hay 3.0 s" in m for m in verdict(short))
    noisy = analyze((tone(10.0) * 0.1 + rng.normal(size=10 * RATE).astype(np.float32) * 0.05))
    assert any("ruido" in m for m in verdict(noisy))
    clipped = analyze(np.clip(tone(10.0) * 5, -1, 1))
    assert any("saturado" in m for m in verdict(clipped))
