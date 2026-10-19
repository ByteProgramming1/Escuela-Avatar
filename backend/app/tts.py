import asyncio
import logging

import httpx

from .config import Settings
from .personas import voice_id

log = logging.getLogger("eci.tts")

ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
RETRYABLE = {429, 500, 502, 503, 504}


class ElevenLabs:
    """Clon de voz (de pago). Devuelve MP3: los fragmentos MP3 se pueden concatenar byte a byte,
    lo que permite sintetizar frase por frase en paralelo."""

    name = "elevenlabs"

    def __init__(self, settings: Settings, http: httpx.AsyncClient):
        self._s = settings
        self._http = http
        self._voice_settings = {
            "stability": settings.tts_stability,
            "similarity_boost": settings.tts_similarity,
            "use_speaker_boost": True,
        }
        self._sem = asyncio.Semaphore(settings.tts_concurrency)

    def available(self, speaker: str) -> bool:
        return bool(self._s.elevenlabs_api_key and voice_id(self._s, speaker))

    def signature(self, speaker: str) -> str:
        return f"elevenlabs:{self._s.tts_model}:{voice_id(self._s, speaker)}:{self._s.elevenlabs_output_format}"

    async def synthesize(self, text: str, speaker: str, previous_text: str | None = None) -> bytes:
        body: dict = {"text": text, "model_id": self._s.tts_model, "voice_settings": self._voice_settings}
        if previous_text:
            body["previous_text"] = previous_text  # continuidad de entonación entre fragmentos
        if "v2_5" in self._s.tts_model:
            body["language_code"] = "es"  # no lo aceptan todos los modelos (p. ej. multilingual_v2)

        async with self._sem:
            for attempt in range(3):
                r = await self._http.post(
                    ELEVENLABS_URL.format(voice_id=voice_id(self._s, speaker)),
                    params={"output_format": self._s.elevenlabs_output_format},
                    json=body,
                    headers={"xi-api-key": self._s.elevenlabs_api_key},
                )
                if r.status_code in RETRYABLE and attempt < 2:
                    await asyncio.sleep(0.4 * (attempt + 1))
                    continue
                r.raise_for_status()
                return r.content
        raise AssertionError("unreachable")


class EdgeTTS:
    """Voz genérica gratuita, sin clave (voces neuronales de Microsoft Edge): mujer para la Rectora y
    hombre para Oswaldo. Es un servicio no oficial y requiere internet. MP3 de 24 kHz / 48 kbps."""

    name = "edge"

    def __init__(self, settings: Settings):
        self._s = settings

    def _voice(self, speaker: str) -> str:
        return getattr(self._s, f"edge_voice_{speaker}", "")

    def available(self, speaker: str) -> bool:
        try:
            import edge_tts  # noqa: F401
        except ImportError:
            return False
        return bool(self._voice(speaker))

    def signature(self, speaker: str) -> str:
        return f"edge:{self._voice(speaker)}"

    async def synthesize(self, text: str, speaker: str, previous_text: str | None = None) -> bytes:
        import edge_tts

        last: Exception | None = None
        for attempt in range(3):
            try:
                audio = bytearray()
                async for part in edge_tts.Communicate(text, self._voice(speaker)).stream():
                    if part["type"] == "audio":
                        audio += part["data"]
                if audio:
                    return bytes(audio)
                last = RuntimeError("edge-tts no devolvió audio")
            except Exception as e:  # websocket intermitente: reintentar
                last = e
            await asyncio.sleep(0.3 * (attempt + 1))
        raise RuntimeError(f"edge-tts falló: {last}")
