import asyncio
import logging
import platform
import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from .audio import load_audio, normalize_loudness, to_wav_bytes, trim_silence
from .config import Settings
from .mp3 import Mp3Stream
from .personas import PERSONAS
from .priority import PriorityGate

log = logging.getLogger("eci.clone")

SAMPLE_RATE = 24_000
AUDIO_EXTENSIONS = (".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac", ".mp4", ".mov")
WARMUP_TEXT = "Hola, bienvenidos."


class LocalClone:
    """Clonación de voz local y gratuita: Qwen3-TTS (Apache 2.0) sobre MLX. Imita la voz del audio
    de referencia de cada personaje (`voices/<speaker>.wav`) y entrega el MP3 en streaming: el primer
    audio sale ~0,5 s después de recibir la frase, y genera más rápido que el tiempo real.

    MLX asocia los cálculos al hilo que los crea, así que el modelo se carga y se usa siempre desde
    UN solo hilo dedicado; el resto del servidor (asyncio) solo recibe los trozos por una cola."""

    name = "clone"
    ref_rate = SAMPLE_RATE  # frecuencia a la que el modelo espera el audio de referencia

    def __init__(self, settings: Settings, transcribe: Callable[[bytes], Awaitable[str]] | None = None):
        self._s = settings
        self._transcribe = transcribe  # para obtener el texto del audio de referencia si falta el .txt
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clone")
        self._model = None  # solo se toca desde el hilo dedicado
        self._refs: dict[str, tuple[tuple, np.ndarray, str]] = {}
        self._ref_locks: dict[str, asyncio.Lock] = {}
        self._gen_lock = PriorityGate()  # una frase a la vez en la GPU; lo que se oye en vivo pasa antes que el trabajo de segundo plano

    # ── Disponibilidad ────────────────────────────────────────────────────────

    @staticmethod
    def supported_platform() -> bool:
        if platform.system() != "Darwin" or platform.machine() != "arm64":
            return False
        try:
            import mlx_audio  # noqa: F401
        except ImportError:
            return False
        return True

    def reference_file(self, speaker: str) -> Path | None:
        for ext in AUDIO_EXTENSIONS:
            path = self._s.voices_dir / f"{speaker}{ext}"
            if path.exists():
                return path
        return None

    def available(self, speaker: str) -> bool:
        return self.supported_platform() and self.reference_file(speaker) is not None

    def signature(self, speaker: str) -> str:
        ref = self.reference_file(speaker)
        stamp = f"{ref.stat().st_size}-{ref.stat().st_mtime_ns}" if ref else "none"
        return f"clone:{self._s.clone_model}:{stamp}"

    # ── Referencia de voz ─────────────────────────────────────────────────────

    def ref_max_seconds(self) -> float:
        return self._s.clone_ref_max_seconds

    def _prepare_audio(self, path: Path) -> np.ndarray:
        x = normalize_loudness(trim_silence(load_audio(path, self.ref_rate), self.ref_rate))
        return x[: int(self.ref_max_seconds() * self.ref_rate)]

    async def _reference(self, speaker: str) -> tuple[np.ndarray, str]:
        """Audio de referencia ya limpio + su transcripción (se calcula una vez y se guarda en el .txt)."""
        path = self.reference_file(speaker)
        if path is None:
            raise RuntimeError(f"Falta el audio de referencia de '{speaker}': ponlo en {self._s.voices_dir}/{speaker}.wav")
        key = (path.stat().st_size, path.stat().st_mtime_ns)
        async with self._ref_locks.setdefault(speaker, asyncio.Lock()):
            cached = self._refs.get(speaker)
            if cached and cached[0] == key:
                return cached[1], cached[2]
            audio = await asyncio.to_thread(self._prepare_audio, path)
            txt = path.with_suffix(".txt")
            if txt.exists() and txt.read_text(encoding="utf-8").strip():
                text = txt.read_text(encoding="utf-8").strip()
            else:
                if self._transcribe is None:
                    raise RuntimeError(f"Falta {txt.name} (la transcripción exacta del audio de referencia)")
                log.info("[%s] transcribiendo el audio de referencia con Whisper…", speaker)
                text = await self._transcribe(to_wav_bytes(audio, self.ref_rate))
                if not text:
                    raise RuntimeError(f"No pude transcribir {path.name}: ¿tiene voz clara? Escribe el texto en {txt.name}")
                txt.write_text(text, encoding="utf-8")
                log.info("[%s] transcripción guardada en %s: %r", speaker, txt.name, text)
            self._refs[speaker] = (key, audio, text)
            return audio, text

    # ── Generación (hilo dedicado) ────────────────────────────────────────────

    def _ensure_model(self):
        if self._model is None:
            from mlx_audio.tts.utils import load_model

            t0 = time.perf_counter()
            log.info("Cargando modelo de clonación %s (la primera vez se descarga)…", self._s.clone_model)
            self._model = load_model(self._s.clone_model)
            log.info("Modelo de clonación listo en %.1fs", time.perf_counter() - t0)
        return self._model

    def _generate(self, text: str, ref_audio, ref_text: str, emit: Callable[[object], None], cancel: threading.Event) -> None:
        try:
            import mlx.core as mx

            model = self._ensure_model()
            encoder = Mp3Stream(SAMPLE_RATE)
            for result in model.generate(
                text=text,
                ref_audio=mx.array(ref_audio),
                ref_text=ref_text,
                lang_code="spanish",
                stream=True,
                streaming_interval=self._s.clone_stream_interval,
                verbose=False,
            ):
                if cancel.is_set():
                    return
                data = encoder.feed(np.array(result.audio).reshape(-1).astype(np.float32))
                if data:
                    emit(data)
            if tail := encoder.finish():
                emit(tail)
            emit(None)
        except Exception as e:
            emit(e)

    async def synthesize_stream(self, text: str, speaker: str, previous_text: str | None = None) -> AsyncIterator[bytes]:
        ref_audio, ref_text = await self._reference(speaker)
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        cancel = threading.Event()
        queued = time.perf_counter()
        sent_bytes, first = 0, None
        async with self._gen_lock.slot():
            started = time.perf_counter()  # desde aquí corre el modelo; antes solo esperaba su turno
            loop.run_in_executor(
                self._pool, self._generate, text, ref_audio, ref_text, lambda item: loop.call_soon_threadsafe(queue.put_nowait, item), cancel
            )
            try:
                while (item := await queue.get()) is not None:
                    if isinstance(item, Exception):
                        raise item
                    first = first or time.perf_counter() - started
                    sent_bytes += len(item)
                    yield item
            finally:
                cancel.set()  # si el cliente se fue, el hilo se detiene en el siguiente trozo
        seconds = sent_bytes * 8 / 48_000  # MP3 a 48 kbps
        total = time.perf_counter() - started
        log.info("[%s] clon: %d chars → %.1fs de audio, espera %.2fs, primer trozo %.2fs, total %.2fs (RTF %.2f)",
                 speaker, len(text), seconds, started - queued, first or 0, total, total / max(seconds, 0.01))

    # ── Arranque ──────────────────────────────────────────────────────────────

    async def warm(self) -> None:
        """Carga el modelo y hace una frase de prueba por personaje, para que la primera pregunta real
        no pague la descarga, la compilación de los kernels ni la transcripción de la referencia."""
        if not self.supported_platform():
            return
        speakers = [sp for sp in PERSONAS if self.reference_file(sp)]
        if not speakers:
            return
        await asyncio.get_running_loop().run_in_executor(self._pool, self._ensure_model)
        for speaker in speakers:
            async for _ in self.synthesize_stream(WARMUP_TEXT, speaker):
                pass
