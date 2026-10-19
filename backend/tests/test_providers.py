"""Proveedores gratuitos: Gemini, Whisper local, edge-tts y la decodificación de WAV."""
import io
import struct
import wave
from types import SimpleNamespace

import numpy as np
import pytest

from app import tts as tts_module
from app.audio import decode_wav, resample, wav_to_whisper_input
from app.config import Settings
from app.gemini import Gemini
from app.knowledge import load_knowledge
from app.llm import REFUSAL_TEXT
from app.stt import LocalWhisper
from app.tts import EdgeTTS


def make_wav(samples: np.ndarray, rate=44100, channels=1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes((samples * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def tone(seconds, rate=44100, hz=440):
    return 0.5 * np.sin(2 * np.pi * hz * np.arange(int(seconds * rate)) / rate).astype(np.float32)


# ── WAV ──────────────────────────────────────────────────────────────────────

def test_decode_wav_roundtrip_and_resample_to_16k():
    x, rate = decode_wav(make_wav(tone(1.0)))
    assert rate == 44100 and len(x) == 44100 and abs(x.max() - 0.5) < 0.01
    y = wav_to_whisper_input(make_wav(tone(1.0)))
    assert y.dtype == np.float32 and len(y) == 16000 and abs(y.max() - 0.5) < 0.05  # la señal se conserva


def test_decode_wav_tolerates_broken_data_size_and_stereo():
    wav = bytearray(make_wav(tone(0.5), channels=1))
    struct.pack_into("<I", wav, 40, 0xFFFFFFFF)  # tamaño del chunk data inválido
    assert len(decode_wav(bytes(wav))[0]) == 22050
    stereo, _ = decode_wav(make_wav(np.repeat(tone(0.1), 2), channels=2))
    assert len(stereo) == 4410


def test_resample_filters_out_frequencies_above_nyquist():
    loud_ultrasound = resample(tone(1.0, hz=15000), 44100)  # 15 kHz no cabe en 16 kHz de muestreo
    assert np.abs(loud_ultrasound[500:-500]).max() < 0.05


def test_decode_rejects_non_wav():
    with pytest.raises(ValueError):
        decode_wav(b"ID3\x04not a wav file at all")


# ── Whisper local ────────────────────────────────────────────────────────────

class FakeWhisperModel:
    def __init__(self, segments):
        self.segments, self.kwargs, self.audio = segments, None, None

    def transcribe(self, audio, **kwargs):
        self.audio, self.kwargs = audio, kwargs
        return iter(self.segments), SimpleNamespace(duration=1.0)


async def test_whisper_transcribes_with_spanish_vocabulary_and_drops_noise():
    seg = lambda text, nsp=0.0, lp=-0.2: SimpleNamespace(text=text, no_speech_prob=nsp, avg_logprob=lp)
    model = FakeWhisperModel([seg(" ¿Cuánto cuesta"), seg(" la matrícula?"), seg(" Gracias por ver el video", nsp=0.9, lp=-1.5)])
    w = LocalWhisper(Settings())
    w._model = model
    assert await w.transcribe(make_wav(tone(0.5))) == "¿Cuánto cuesta la matrícula?"
    assert model.kwargs["language"] == "es" and model.kwargs["vad_filter"] is True and model.kwargs["beam_size"] == 1
    assert "ICETEX" in model.kwargs["initial_prompt"]
    assert model.audio.dtype == np.float32 and len(model.audio) == 8000  # llega ya a 16 kHz


# ── edge-tts ─────────────────────────────────────────────────────────────────

class FakeCommunicate:
    created, fail_first = [], 0

    def __init__(self, text, voice):
        FakeCommunicate.created.append((text, voice))

    async def stream(self):
        if FakeCommunicate.fail_first > 0:
            FakeCommunicate.fail_first -= 1
            raise ConnectionError("websocket cerrado")
        yield {"type": "WordBoundary", "offset": 0}
        yield {"type": "audio", "data": b"AAA"}
        yield {"type": "audio", "data": b"BBB"}


async def test_edge_uses_a_female_voice_for_rectora_and_a_male_voice_for_oswaldo(monkeypatch):
    import edge_tts

    monkeypatch.setattr(edge_tts, "Communicate", FakeCommunicate)
    FakeCommunicate.created, FakeCommunicate.fail_first = [], 0
    edge = EdgeTTS(Settings())
    assert await edge.synthesize("Hola", "rectora") == b"AAABBB"
    await edge.synthesize("Buenos días", "oswaldo")
    assert [v for _, v in FakeCommunicate.created] == ["es-CO-SalomeNeural", "es-CO-GonzaloNeural"]
    assert edge.available("rectora") and edge.signature("oswaldo") == "edge:es-CO-GonzaloNeural"


async def test_edge_retries_a_flaky_connection(monkeypatch):
    import edge_tts

    monkeypatch.setattr(edge_tts, "Communicate", FakeCommunicate)
    FakeCommunicate.created, FakeCommunicate.fail_first = [], 2
    assert await EdgeTTS(Settings()).synthesize("Hola", "rectora") == b"AAABBB"
    assert len(FakeCommunicate.created) == 3


# ── Gemini ───────────────────────────────────────────────────────────────────

class FakeGenaiClient:
    def __init__(self, pieces):
        self.calls = []
        outer = self

        class Models:
            async def generate_content_stream(self, *, model, contents, config):
                outer.calls.append(SimpleNamespace(model=model, contents=contents, config=config))

                async def gen():
                    for p in pieces:
                        yield SimpleNamespace(text=p)

                return gen()

        self.aio = SimpleNamespace(models=Models())


async def test_gemini_sends_knowledge_persona_and_history_and_streams_text():
    s = Settings(gemini_api_key="k", gemini_thinking_level="minimal")
    client = FakeGenaiClient(["Hola. ", "Con gusto."])
    g = Gemini(s, load_knowledge(s.knowledge_dir), client=client)
    history = [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"}]
    out = [d async for d in g.stream_text("oswaldo", "q2", history)]
    assert out == ["Hola. ", "Con gusto."]
    call = client.calls[0]
    assert call.model == "gemini-3.5-flash-lite"
    assert [(c.role, c.parts[0].text) for c in call.contents] == [("user", "q1"), ("model", "a1"), ("user", "q2")]
    si = call.config.system_instruction
    assert "BASE_DE_CONOCIMIENTO" in si and "Oswaldo Castillo Navetty" in si and "Myriam Astrid" in si.split("TU PERSONAJE")[0]
    assert str(call.config.thinking_config.thinking_level).lower().endswith("minimal")
    assert call.config.max_output_tokens == 1024


async def test_gemini_empty_response_becomes_a_spoken_apology():
    s = Settings(gemini_api_key="k")
    g = Gemini(s, load_knowledge(s.knowledge_dir), client=FakeGenaiClient([None, ""]))
    assert [d async for d in g.stream_text("rectora", "q", [])] == [REFUSAL_TEXT]


def test_gemini_is_unavailable_without_a_key():
    s = Settings()
    assert not Gemini(s, load_knowledge(s.knowledge_dir)).available()
    assert Gemini(Settings(gemini_api_key="k"), load_knowledge(s.knowledge_dir)).available()


def test_elevenlabs_request_uses_matching_format_and_voice(monkeypatch):
    import asyncio

    import httpx

    sent = {}

    def handler(request):
        sent["url"], sent["body"], sent["headers"] = str(request.url), request.content, request.headers
        return httpx.Response(200, content=b"MP3")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            el = tts_module.ElevenLabs(Settings(elevenlabs_api_key="k", voice_id_rectora="VID"), http)
            assert el.available("rectora") and not el.available("oswaldo")  # sin VOICE_ID no hay clon
            return await el.synthesize("Hola", "rectora", previous_text="Antes.")

    assert asyncio.run(run()) == b"MP3"
    assert "/v1/text-to-speech/VID" in sent["url"] and "output_format=mp3_24000_48" in sent["url"]
    assert sent["headers"]["xi-api-key"] == "k"
    body = __import__("json").loads(sent["body"])
    assert body["model_id"] == "eleven_flash_v2_5" and body["language_code"] == "es" and body["previous_text"] == "Antes."


async def test_gemini_real_sdk_request_shape_over_mocked_http():
    """Cliente real de google-genai contra un transporte simulado: valida URL, clave, roles y el parseo del SSE."""
    import json

    import httpx2 as httpx
    from google import genai
    from google.genai import types

    seen = {}

    def handler(request):
        seen.update(url=str(request.url), key=request.headers.get("x-goog-api-key"), body=json.loads(request.content))
        event = lambda text: "data: " + json.dumps({"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}}]}) + "\r\n\r\n"
        return httpx.Response(200, content=(event("Hola. ") + event("Con gusto.")).encode(), headers={"content-type": "text/event-stream"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = genai.Client(api_key="KEY", http_options=types.HttpOptions(httpx_async_client=http))
    s = Settings(gemini_api_key="KEY")
    g = Gemini(s, load_knowledge(s.knowledge_dir), client=client)
    out = [d async for d in g.stream_text("rectora", "¿Cuánto cuesta?", [{"role": "user", "content": "hola"}, {"role": "assistant", "content": "buenas"}])]
    assert out == ["Hola. ", "Con gusto."]
    assert "gemini-3.5-flash-lite:streamGenerateContent" in seen["url"] and seen["key"] == "KEY"
    assert [c["role"] for c in seen["body"]["contents"]] == ["user", "model", "user"]
    assert "BASE_DE_CONOCIMIENTO" in seen["body"]["systemInstruction"]["parts"][0]["text"]
