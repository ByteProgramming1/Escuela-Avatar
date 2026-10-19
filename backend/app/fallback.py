"""Cadenas de proveedores con respaldo automático.

Orden en modo "auto": primero el de pago (si hay clave) y después el gratuito. Un proveedor que
falla (clave inválida, sin saldo, límite de tasa, caída) se salta durante `cooldown` segundos,
así que en un evento en vivo solo la primera pregunta paga el fallo."""
import asyncio
import logging
import time
from collections.abc import AsyncIterator

import anthropic
import httpx

from .config import Settings
from .gemini import Gemini
from .knowledge import Knowledge
from .llm import Claude
from .stt import Deepgram, LocalWhisper
from .clone_tts import LocalClone
from .fish_tts import FishSpeech
from .tts import EdgeTTS, ElevenLabs

log = logging.getLogger("eci.fallback")

TRANSIENT_STATUS = {500, 502, 503, 504, 529}  # 529 = "overloaded" de Anthropic


def is_transient(e: Exception) -> bool:
    """¿Merece la pena reintentar con el mismo proveedor? Solo caídas o sobrecargas momentáneas:
    una clave inválida, un límite de cuota o una petición mal formada fallarían igual otra vez."""
    status = getattr(e, "status_code", None) or getattr(e, "code", None)  # Anthropic / google-genai
    return (isinstance(status, int) and status in TRANSIENT_STATUS) or isinstance(e, (httpx.TransportError, TimeoutError, ConnectionError, anthropic.APIConnectionError))


class Chain:
    kind = "?"
    per_speaker = False  # el TTS depende del speaker (voz); STT y LLM no
    missing_help = ""

    def __init__(self, providers: list, cooldown: float):
        self.providers = providers
        self._cooldown = cooldown
        self._failed_until: dict[str, float] = {}
        self.degraded_at = 0.0  # última vez que hubo que saltarse un proveedor

    def _is_available(self, p, speaker: str | None) -> bool:
        return p.available(speaker) if self.per_speaker else p.available()

    def available_providers(self, speaker: str | None = None) -> list:
        return [p for p in self.providers if self._is_available(p, speaker)]

    def candidates(self, speaker: str | None = None) -> list:
        avail = self.available_providers(speaker)
        now = time.monotonic()
        ready = [p for p in avail if self._failed_until.get(p.name, 0.0) <= now]
        return ready or avail  # si todos están "castigados", se intenta igual

    def ready(self, speaker: str | None = None) -> bool:
        return bool(self.available_providers(speaker))

    def describe(self, speaker: str | None = None) -> str:
        return " → ".join(p.name for p in self.available_providers(speaker)) or "NINGUNO"

    def signature(self, speaker: str | None = None) -> str:
        avail = self.available_providers(speaker)
        if not avail:
            return "none"
        return avail[0].signature(speaker) if self.per_speaker else avail[0].signature()

    def degraded(self, since: float, speaker: str | None = None) -> bool:
        """¿Se usó (o se está usando) un respaldo desde `since`? Sirve para no dar por bueno un
        audio generado de emergencia. Sin otro proveedor detrás no hay "respaldo" que haya podido generarlo:
        un fallo ajeno (otra pregunta que no se pudo atender) no vuelve de emergencia lo que sí salió bien."""
        avail = self.available_providers(speaker)
        if len(avail) < 2:
            return False
        cooling = bool(avail) and self._failed_until.get(avail[0].name, 0.0) > time.monotonic()
        return cooling or self.degraded_at >= since

    def _fail(self, p, err: Exception) -> None:
        self._failed_until[p.name] = time.monotonic() + self._cooldown
        self.degraded_at = time.monotonic()
        log.warning("%s: %s falló (%s: %s); uso el siguiente", self.kind, p.name, type(err).__name__, str(err)[:200])

    def _unavailable(self, speaker: str | None) -> RuntimeError:
        return RuntimeError(f"No hay {self.kind} disponible{f' para {speaker}' if speaker else ''}. {self.missing_help}")


class STTChain(Chain):
    kind = "STT"
    missing_help = "Configura DEEPGRAM_API_KEY o instala faster-whisper."

    async def transcribe(self, wav: bytes) -> str:
        last: Exception | None = None
        for p in self.candidates():
            try:
                return await p.transcribe(wav)
            except Exception as e:
                last = e
                self._fail(p, e)
        raise last or self._unavailable(None)

    async def warm(self) -> None:
        for r in await asyncio.gather(*(p.warm() for p in self.available_providers()), return_exceptions=True):
            if isinstance(r, Exception):
                log.warning("STT: no se pudo precargar: %s", r)


class LLMChain(Chain):
    kind = "LLM"
    missing_help = "Pon ANTHROPIC_API_KEY o GEMINI_API_KEY (gratis en https://aistudio.google.com/apikey) en backend/.env."

    def __init__(self, providers: list, cooldown: float, retries: int = 0, retry_delay: float = 0.6):
        super().__init__(providers, cooldown)
        self._retries = retries
        self._retry_delay = retry_delay

    async def stream_text(self, speaker: str, question: str, history: list[dict]) -> AsyncIterator[str]:
        last: Exception | None = None
        candidates = self.candidates()
        for i, p in enumerate(candidates):
            # Solo el último proveedor se reintenta: si hay otro detrás, se pasa a él sin esperar.
            retries_left = self._retries if i == len(candidates) - 1 else 0
            delay = self._retry_delay
            while True:
                emitted = False
                try:
                    async for delta in p.stream_text(speaker, question, history):
                        emitted = True
                        yield delta
                    return
                except Exception as e:
                    if emitted:  # a media respuesta no se puede cambiar de modelo
                        raise
                    if retries_left > 0 and is_transient(e):
                        retries_left -= 1
                        log.warning("LLM: %s no respondió (%s: %s); reintento en %.1fs", p.name, type(e).__name__, str(e)[:120], delay)
                        await asyncio.sleep(delay)
                        delay *= 2
                        continue
                    last = e
                    self._fail(p, e)
                    break
        raise last or self._unavailable(None)

    async def prime(self) -> None:
        await asyncio.gather(*(p.prime() for p in self.available_providers()), return_exceptions=True)


class TTSChain(Chain):
    kind = "TTS"
    per_speaker = True
    missing_help = "Configura ElevenLabs (clave + VOICE_ID_<NOMBRE>) o instala edge-tts."

    async def synthesize(self, text: str, speaker: str, previous_text: str | None = None) -> bytes:
        last: Exception | None = None
        for p in self.candidates(speaker):
            try:
                return await p.synthesize(text, speaker, previous_text)
            except Exception as e:
                last = e
                self._fail(p, e)
        raise last or self._unavailable(speaker)

    async def synthesize_stream(self, text: str, speaker: str, previous_text: str | None = None) -> AsyncIterator[bytes]:
        """Como synthesize, pero entrega el audio por trozos si el proveedor lo permite. Solo se cambia de
        proveedor si el que falló aún no había entregado nada de esta frase."""
        last: Exception | None = None
        for p in self.candidates(speaker):
            emitted = False
            try:
                if hasattr(p, "synthesize_stream"):
                    async for data in p.synthesize_stream(text, speaker, previous_text):
                        emitted = True
                        yield data
                else:
                    data = await p.synthesize(text, speaker, previous_text)
                    emitted = True
                    yield data
                return
            except Exception as e:
                if emitted:
                    raise
                last = e
                self._fail(p, e)
        raise last or self._unavailable(speaker)

    async def warm(self) -> None:
        for r in await asyncio.gather(*(p.warm() for p in self.providers if hasattr(p, "warm")), return_exceptions=True):
            if isinstance(r, Exception):
                log.warning("TTS: no se pudo precargar: %s", r)


def _pick(choice: str, order: list[str], registry: dict) -> list:
    return [registry[n] for n in (order if choice == "auto" else [choice])]


def build_chains(settings: Settings, knowledge: Knowledge, http: httpx.AsyncClient) -> tuple[STTChain, LLMChain, TTSChain]:
    cd = settings.provider_cooldown_seconds
    whisper = LocalWhisper(settings)  # lo comparten el STT de respaldo y la transcripción de la voz de referencia
    stt = STTChain(_pick(settings.stt_provider, ["deepgram", "whisper"], {"deepgram": Deepgram(settings, http), "whisper": whisper}), cd)
    gemini = Gemini(settings, knowledge)
    llm_registry = {"anthropic": Claude(settings, knowledge), "gemini": gemini}
    llm_order = ["anthropic", "gemini"]
    if settings.gemini_fallback_model and settings.gemini_fallback_model != settings.gemini_model:
        # Misma clave y cliente, otro modelo: la cuota gratuita de Gemini es por modelo, así que si el
        # primero se queda sin cuota (429) o está saturado (503) el segundo sigue contestando.
        llm_registry["gemini_fallback"] = Gemini(settings, knowledge, client=gemini._client, model=settings.gemini_fallback_model, name="gemini_fallback")
        llm_order.append("gemini_fallback")
    llm = LLMChain(_pick(settings.llm_provider, llm_order, llm_registry), cd, settings.llm_retries, settings.llm_retry_delay)
    tts_registry = {
        "elevenlabs": ElevenLabs(settings, http),
        "clone": LocalClone(settings, whisper.transcribe),
        "fish": FishSpeech(settings, whisper.transcribe),
        "edge": EdgeTTS(settings),
    }
    # TTS_PROVIDER=fish: Fish S2 y, solo si falla, la voz genérica (que no carga ningún modelo). No se añade el clon Qwen
    # como respaldo: `warm()` cargaría los dos modelos a la vez y en 16 GB no caben junto a Unity.
    tts_providers = [tts_registry["fish"], tts_registry["edge"]] if settings.tts_provider == "fish" else _pick(settings.tts_provider, ["elevenlabs", "clone", "edge"], tts_registry)
    tts = TTSChain(tts_providers, cd)
    return stt, llm, tts
