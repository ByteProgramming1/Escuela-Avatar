import asyncio
import re
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field

# Abreviaturas cuyo punto NO termina una frase
ABBREVIATIONS = {"dr", "dra", "ing", "sr", "sra", "srta", "lic", "prof"}
# El primer fragmento es corto para que el audio empiece pronto, pero no tanto como para que se
# acabe de reproducir antes de que llegue el segundo (en streaming eso se oiría como un corte).
FIRST_CHUNK_MIN = 40
NEXT_CHUNK_MIN = 80  # los siguientes se agrupan: menos llamadas y mejor entonación
FIRST_CLAUSE_MIN = 70  # si la primera frase es larga, el primer fragmento puede cerrarse en una coma

_BOUNDARY = re.compile(r"[.!?…]+[\"')\]]*\s+|\n+")
_CLAUSE = re.compile(r"[,;:]\s+")


class SentenceChunker:
    """Parte el texto que llega por streaming en fragmentos de frases completas."""

    def __init__(self) -> None:
        self._buf = ""
        self._emitted = 0

    def feed(self, text: str) -> list[str]:
        self._buf += text
        out: list[str] = []
        pos = 0
        if self._emitted == 0:  # la primera frase del LLM suele ser larga: arrancar el audio en la primera coma útil
            first_end = _BOUNDARY.search(self._buf)
            for m in _CLAUSE.finditer(self._buf):
                if len(self._buf[: m.end()].strip()) >= FIRST_CLAUSE_MIN and (first_end is None or m.end() <= first_end.start()):
                    out.append(self._buf[: m.end()].strip())
                    self._emitted += 1
                    pos = m.end()
                    break
        for m in _BOUNDARY.finditer(self._buf, pos):
            candidate = self._buf[pos : m.end()]
            if self._is_abbreviation(candidate):
                continue
            if len(candidate.strip()) >= self._min_len():
                out.append(candidate.strip())
                self._emitted += 1
                pos = m.end()
        self._buf = self._buf[pos:]
        return out

    def flush(self) -> str | None:
        rest, self._buf = self._buf.strip(), ""
        return rest or None

    def _min_len(self) -> int:
        return FIRST_CHUNK_MIN if self._emitted == 0 else NEXT_CHUNK_MIN

    @staticmethod
    def _is_abbreviation(candidate: str) -> bool:
        words = candidate.rstrip().rstrip(".").split()
        return bool(words) and candidate.rstrip().endswith(".") and words[-1].lower() in ABBREVIATIONS


@dataclass
class Spoken:
    text: str = ""
    audio: bytes = b""
    timings: dict[str, float] = field(default_factory=dict)
    first_sentence_at: float | None = None  # time.perf_counter() en que la primera frase entró al TTS: el audio está a punto de salir


SynthFn = Callable[[str, str, str | None], Awaitable[bytes]]  # (texto, speaker, texto_previo) -> mp3
SynthStream = Callable[[str, str, str | None], AsyncIterator[bytes]]  # ... -> trozos de mp3 a medida que salen


def stream_of(synthesize: SynthFn) -> SynthStream:
    """Adapta un TTS que devuelve el MP3 entero al contrato de streaming (un único trozo)."""

    async def run(text: str, speaker: str, previous: str | None) -> AsyncIterator[bytes]:
        yield await synthesize(text, speaker, previous)

    return run


async def speak_stream(text_stream: AsyncIterator[str], speaker: str, synth: SynthStream, out: Spoken) -> AsyncIterator[bytes]:
    """Consume el texto del LLM y lanza el TTS de cada fragmento en cuanto está completo, sin esperar
    al resto de la respuesta. Entrega el audio en orden, trozo a trozo, apenas está listo (un TTS en
    streaming empieza a sonar antes de terminar la frase). Al terminar, `out` trae texto y tiempos."""
    t0 = time.perf_counter()
    jobs: asyncio.Queue = asyncio.Queue()  # una cola de audio por frase, en orden; None = fin; Exception = error del LLM
    tasks: list[asyncio.Task] = []
    marks: dict[str, float] = {}

    async def synth_sentence(sentence: str, previous: str | None, audio: asyncio.Queue) -> None:
        try:
            async for data in synth(sentence, speaker, previous):
                audio.put_nowait(data)
            audio.put_nowait(None)
        except Exception as e:
            audio.put_nowait(e)

    async def produce() -> None:
        chunker = SentenceChunker()
        parts: list[str] = []
        spoken_tail = ""

        def submit(sentence: str) -> None:
            nonlocal spoken_tail
            if out.first_sentence_at is None:
                out.first_sentence_at = time.perf_counter()
            audio: asyncio.Queue = asyncio.Queue()
            tasks.append(asyncio.create_task(synth_sentence(sentence, spoken_tail or None, audio)))
            jobs.put_nowait(audio)
            spoken_tail = f"{spoken_tail} {sentence}".strip()[-300:]

        try:
            async for delta in text_stream:
                marks.setdefault("llm_first_token", time.perf_counter() - t0)
                parts.append(delta)
                for sentence in chunker.feed(delta):
                    submit(sentence)
            if (tail := chunker.flush()) is not None:
                submit(tail)
            marks["llm_total"] = time.perf_counter() - t0
            out.text = "".join(parts).strip()
            jobs.put_nowait(None)
        except Exception as e:  # CancelledError no se captura: es la señal de cierre
            jobs.put_nowait(e)

    producer = asyncio.create_task(produce())
    audio_bytes = 0
    try:
        while (audio := await jobs.get()) is not None:
            if isinstance(audio, Exception):
                raise audio
            while (data := await audio.get()) is not None:
                if isinstance(data, Exception):
                    raise data
                if not audio_bytes:
                    marks["first_audio"] = time.perf_counter() - t0
                audio_bytes += len(data)
                yield data
        if not audio_bytes:
            raise RuntimeError("La respuesta no produjo audio")
        total = time.perf_counter() - t0
        out.timings = {
            "llm_first_token": round(marks.get("llm_first_token", 0.0), 2),
            "llm_total": round(marks.get("llm_total", 0.0), 2),
            "first_audio": round(marks.get("first_audio", 0.0), 2),
            "tts_tail": round(total - marks.get("llm_total", total), 2),
            "speak_total": round(total, 2),
        }
    finally:
        producer.cancel()
        for t in tasks:
            t.cancel()
        await asyncio.gather(producer, *tasks, return_exceptions=True)


async def speak(text_stream: AsyncIterator[str], speaker: str, synth: SynthStream) -> Spoken:
    """Igual que speak_stream pero devuelve el audio completo (para guardar en un archivo)."""
    out = Spoken()
    out.audio = b"".join([c async for c in speak_stream(text_stream, speaker, synth, out)])
    return out


async def once(text: str) -> AsyncIterator[str]:
    yield text


class History:
    """Memoria corta para preguntas de seguimiento. Se olvida sola tras un rato sin
    actividad, para que la pregunta de otra persona no herede el contexto de la anterior."""

    def __init__(self, max_turns: int, ttl_seconds: float):
        self._turns: deque[tuple[str, str, str | None]] = deque(maxlen=max_turns)  # (pregunta, respuesta, quién respondió)
        self._ttl = ttl_seconds
        self._last = 0.0

    def _expire(self) -> None:
        if self._turns and time.monotonic() - self._last > self._ttl:
            self._turns.clear()

    def messages(self) -> list[dict]:
        self._expire()
        out: list[dict] = []
        for user, assistant, _ in self._turns:
            out += [{"role": "user", "content": user}, {"role": "assistant", "content": assistant}]
        return out

    @property
    def last_speaker(self) -> str | None:
        """Quién dio la última respuesta que sigue en memoria (None si no hay o ya se olvidó)."""
        self._expire()
        return self._turns[-1][2] if self._turns else None

    def add(self, user: str, assistant: str, speaker: str | None = None) -> None:
        self._turns.append((user, assistant, speaker))
        self._last = time.monotonic()

    def clear(self) -> None:
        self._turns.clear()
