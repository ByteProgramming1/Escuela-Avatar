"""Fish Audio S2 (proveedor alternativo de clonación): referencia a 44,1 kHz, salida remuestreada a 24 kHz sin clics
entre trozos y MP3 igual que el resto de proveedores. El modelo MLX se simula."""
import io
from types import SimpleNamespace

import av
import numpy as np
import pytest

from app.audio import to_wav_bytes
from app.config import Settings
from app.fallback import build_chains
from app.fish_tts import FishSpeech
from app.knowledge import load_knowledge

pytest.importorskip("mlx.core")

FISH_RATE = 44_100


def sine(seconds, hz=220.0, start=0.0, rate=FISH_RATE):
    t = start + np.arange(int(seconds * rate)) / rate
    return (0.4 * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def decode(mp3: bytes) -> np.ndarray:
    out = []
    with av.open(io.BytesIO(mp3)) as c:
        resampler = av.AudioResampler(format="flt", layout="mono", rate=24_000)
        for frame in c.decode(c.streams.audio[0]):
            out += [f.to_ndarray().reshape(-1) for f in resampler.resample(frame)]
    return np.concatenate(out)


class FakeFish:
    sample_rate = FISH_RATE

    def __init__(self, rate=FISH_RATE):
        self.sample_rate, self.calls = rate, []

    def generate(self, **kw):
        self.calls.append(kw)
        # 4 trozos de 0,5 s de una misma senoide continua (como los trozos de un stream real) y uno final vacío
        for i in range(4):
            yield SimpleNamespace(audio=sine(0.5, start=i * 0.5), sample_rate=self.sample_rate, is_final_chunk=False)
        yield SimpleNamespace(audio=np.zeros(0, np.float32), sample_rate=self.sample_rate, is_final_chunk=True)


@pytest.fixture
def fish(tmp_path, monkeypatch):
    voices = tmp_path / "voices"
    voices.mkdir()
    (voices / "rectora.wav").write_bytes(to_wav_bytes(sine(12.0, 180.0, rate=24_000), 24_000))
    (voices / "rectora.txt").write_text("Texto exacto de la referencia.", encoding="utf-8")
    monkeypatch.setattr(FishSpeech, "supported_platform", staticmethod(lambda: True))
    provider = FishSpeech(Settings(voices_dir=voices, fish_model="fake/fish", fish_ref_max_seconds=8.0))
    model = FakeFish()
    provider._model = model
    return provider, model


async def synth(provider, text="Hola, esto es una prueba."):
    return b"".join([c async for c in provider.synthesize_stream(text, "rectora")])


async def test_reference_is_44k_capped_and_sent_with_its_text_and_fish_settings(fish):
    provider, model = fish
    await synth(provider)
    call = model.calls[0]
    assert call["ref_text"] == "Texto exacto de la referencia." and call["stream"] is True
    assert call["streaming_interval"] == 0.5 and call["temperature"] == 0.7
    assert "lang_code" not in call  # Fish detecta el idioma
    ref = np.array(call["ref_audio"])
    assert 7.5 < len(ref) / FISH_RATE <= 8.0  # 44,1 kHz y recortada a FISH_REF_MAX_SECONDS


async def test_output_is_the_same_24k_mp3_as_other_providers_with_the_right_duration(fish):
    provider, _ = fish
    data = await synth(provider)
    assert data[0] == 0xFF and not data.startswith(b"ID3") and b"Xing" not in data[:300]
    pcm = decode(data)
    assert 1.9 < len(pcm) / 24_000 < 2.2  # 4 × 0,5 s
    assert abs(len(data) / 6000 - len(pcm) / 24_000) < 0.15  # MP3 CBR de 48 kbps (6000 B/s), como el resto


async def test_resampling_keeps_state_between_chunks_so_there_are_no_clicks(fish):
    provider, _ = fish
    pcm = decode(await synth(provider))
    body = pcm[2400:-2400]  # sin los bordes del codificador
    steps = np.abs(np.diff(body))
    max_slope = 0.4 * 2 * np.pi * 220 / 24_000 * 1.6  # la senoide pura no puede saltar más que esto entre muestras (con margen del MP3)
    assert steps.max() < max_slope, f"salto de {steps.max():.3f} entre muestras: hay un clic en la unión de trozos"
    freq = np.argmax(np.abs(np.fft.rfft(body[:24_000]))) * 24_000 / 24_000
    assert 215 < freq < 225  # el resultado sigue siendo la senoide de 220 Hz (no cambió de tono al remuestrear)


async def test_signature_changes_with_model_temperature_and_reference(fish, tmp_path):
    provider, _ = fish
    a = provider.signature("rectora")
    assert a.startswith("fish:fake/fish:t0.7:")
    other = FishSpeech(Settings(voices_dir=provider._s.voices_dir, fish_model="otro", fish_temperature=0.5))
    assert other.signature("rectora") != a
    (provider._s.voices_dir / "rectora.wav").write_bytes(to_wav_bytes(sine(11.0, 150.0, rate=24_000), 24_000))
    assert provider.signature("rectora") != a  # cambiar la voz regenera el audio guardado


async def test_wrong_model_sample_rate_is_reported_clearly(fish):
    provider, _ = fish
    provider._model = FakeFish(rate=24_000)
    provider._model.sample_rate = 24_000
    # _ensure_model solo comprueba al cargar; aquí se simula la carga real
    provider._model = None
    import app.fish_tts as module

    class Loader:
        @staticmethod
        def load_model(name):
            return FakeFish(rate=24_000)

    import sys

    sys.modules["mlx_audio.tts.utils"], previous = Loader, sys.modules.get("mlx_audio.tts.utils")
    try:
        with pytest.raises(RuntimeError, match="44100|ref_rate"):
            module.FishSpeech._ensure_model(provider)
    finally:
        sys.modules["mlx_audio.tts.utils"] = previous


def test_tts_provider_fish_builds_fish_then_the_generic_voice_and_never_loads_two_models(tmp_path):
    kb = load_knowledge(Settings().knowledge_dir)
    _, _, tts = build_chains(Settings(_env_file=None, tts_provider="fish", voices_dir=tmp_path / "sin-voces"), kb, http=None)
    assert [p.name for p in tts.providers] == ["fish", "edge"]
    _, _, auto = build_chains(Settings(_env_file=None, voices_dir=tmp_path / "sin-voces"), kb, http=None)
    assert [p.name for p in auto.providers] == ["elevenlabs", "clone", "edge"]  # el valor por defecto no cambia
