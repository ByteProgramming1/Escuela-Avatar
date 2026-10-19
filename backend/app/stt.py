import asyncio
import io
import logging
import threading

import httpx

from .audio import wav_to_whisper_input
from .config import Settings

log = logging.getLogger("eci.stt")

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"


class Deepgram:
    """Transcripción pregrabada (el cliente envía el WAV completo al soltar la tecla)."""

    name = "deepgram"

    def __init__(self, settings: Settings, http: httpx.AsyncClient):
        self._key = settings.deepgram_api_key
        self._http = http
        self._params = {
            "model": settings.stt_model,
            "language": settings.stt_language,
            "smart_format": "true",
        }

    def available(self) -> bool:
        return bool(self._key)

    def signature(self) -> str:
        return f"deepgram:{self._params['model']}"

    async def warm(self) -> None:
        pass

    async def transcribe(self, wav: bytes) -> str:
        r = await self._http.post(
            DEEPGRAM_URL,
            params=self._params,
            content=wav,
            headers={"Authorization": f"Token {self._key}", "Content-Type": "audio/wav"},
        )
        r.raise_for_status()
        channels = r.json().get("results", {}).get("channels", [])
        if not channels or not channels[0].get("alternatives"):
            return ""
        return channels[0]["alternatives"][0].get("transcript", "").strip()


class LocalWhisper:
    """Whisper local (faster-whisper): gratis, sin clave y sin enviar el audio a ningún servidor.
    La primera vez descarga el modelo (~460 MB para `small`)."""

    name = "whisper"

    def __init__(self, settings: Settings):
        self._s = settings
        self._model = None
        self._load_lock = threading.Lock()
        self._run_lock = asyncio.Semaphore(1)  # es CPU: una transcripción a la vez

    def available(self) -> bool:
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return False
        return True

    def signature(self) -> str:
        return f"whisper:{self._s.whisper_model}"

    def _load(self):
        with self._load_lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                log.info("Cargando Whisper '%s' (la primera vez se descarga)…", self._s.whisper_model)
                self._model = WhisperModel(self._s.whisper_model, device="cpu", compute_type=self._s.whisper_compute_type)
                log.info("Whisper listo")
        return self._model

    async def warm(self) -> None:
        if self._s.whisper_preload:
            await asyncio.to_thread(self._load)

    def _run(self, wav: bytes) -> str:
        model = self._load()
        segments, _ = model.transcribe(
            wav_to_whisper_input(wav),
            language=self._s.stt_language,
            beam_size=1,  # más rápido; en frases cortas casi no pierde calidad
            vad_filter=True,  # sin voz → vacío, en vez de alucinar "gracias por ver el video"
            condition_on_previous_text=False,
            initial_prompt=self._s.whisper_prompt,  # vocabulario propio: nombres y siglas de la Escuela
        )
        # no_speech_prob alto + baja confianza = ruido que Whisper convirtió en texto
        kept = [s.text.strip() for s in segments if not (s.no_speech_prob > 0.6 and s.avg_logprob < -1.0)]
        return " ".join(t for t in kept if t).strip()

    async def transcribe(self, wav: bytes) -> str:
        async with self._run_lock:
            return await asyncio.to_thread(self._run, wav)
