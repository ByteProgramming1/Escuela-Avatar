"""Muletillas habladas: frases de cortesía de ~4 s que suenan mientras la respuesta real todavía se prepara
(voz → texto → LLM → primera frase de voz puede tardar varios segundos y el silencio parece un fallo).

No dependen de lo que dijo la persona, así que se generan una sola vez con la voz de cada personaje (el mismo TTS
de siempre, gratis con el clon local) y se guardan en disco como las preguntas pregrabadas. Hay muchas y rotan:
cada (personaje, etapa) saca de una bolsa barajada y no repite hasta agotarla."""
import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass
from pathlib import Path

from .audio import load_audio, trim_silence, write_atomic
from .config import Settings
from .mp3 import MP3_BYTES_PER_SECOND, Mp3Stream
from .pipeline import once, speak

log = logging.getLogger("eci.fillers")

OPENING = "opening"  # la primera, en el segundo 2
CONTINUE = "continue"  # las siguientes, si la respuesta real aún no está lista cuando acaba la anterior
STAGES = (OPENING, CONTINUE)
CLIP_VERSION = "recortada-1"  # entra en la clave de disco: al cambiar cómo se procesan los clips, se regeneran todos
SAMPLE_RATE = 24_000
EDGE_PAD_SECONDS = 0.1  # lo que se deja de silencio a cada lado tras recortar


@dataclass(frozen=True)
class Clip:
    text: str
    audio: bytes
    seconds: float

    @classmethod
    def of(cls, text: str, audio: bytes) -> "Clip":
        return cls(text, audio, len(audio) / MP3_BYTES_PER_SECOND)


def tighten(audio: bytes, pad: float = EDGE_PAD_SECONDS) -> bytes:
    """Quita el silencio del principio y del final del MP3 que devolvió el TTS (suele traer 0,2-0,8 s a cada lado):
    así la duración es la del habla y la siguiente muletilla (o la respuesta) entra justo cuando acaba esta."""
    pcm = trim_silence(load_audio(audio, SAMPLE_RATE), SAMPLE_RATE, threshold_db=-42.0, pad=pad)
    mp3 = Mp3Stream(rate=SAMPLE_RATE)
    return mp3.feed(pcm) + mp3.finish()


def load_texts(path: Path) -> dict[str, dict[str, list[str]]]:
    """{speaker: {etapa: [textos]}} de fillers.json (las claves que empiezan por «_» son comentarios)."""
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        speaker: {stage: [t.strip() for t in texts if t.strip()] for stage, texts in stages.items() if stage in STAGES}
        for speaker, stages in raw.items()
        if not speaker.startswith("_") and isinstance(stages, dict)
    }


class Fillers:
    def __init__(self, settings: Settings, texts: dict[str, dict[str, list[str]]] | None = None):
        self._s = settings
        self._texts = texts if texts is not None else (load_texts(settings.fillers_file) if settings.filler_enabled else {})
        self._clips: dict[tuple[str, str], list[Clip]] = {}
        self._bags: dict[tuple[str, str], list[Clip]] = {}
        self._last: dict[tuple[str, str], Clip] = {}
        self._rng = random.Random()

    # ── Uso ────────────────────────────────────────────────────────────────────

    def has_texts(self) -> bool:
        return any(texts for stages in self._texts.values() for texts in stages.values())

    def ready(self, speaker: str) -> bool:
        """¿Hay al menos una muletilla de apertura para este personaje? Si no, la respuesta sale como siempre."""
        return self._s.filler_enabled and bool(self._clips.get((speaker, OPENING)))

    def add(self, speaker: str, stage: str, clip: Clip) -> None:
        self._clips.setdefault((speaker, stage), []).append(clip)

    def count(self, speaker: str, stage: str) -> int:
        return len(self._clips.get((speaker, stage), []))

    def next(self, speaker: str, stage: str) -> Clip | None:
        """Siguiente muletilla de la bolsa barajada: no repite hasta agotarla, y al rebarajar evita empezar con la última."""
        key = (speaker, stage)
        clips = self._clips.get(key)
        if not clips:
            return None
        bag = self._bags.get(key)
        if not bag:
            bag = clips[:]
            self._rng.shuffle(bag)
            last = self._last.get(key)
            if len(bag) > 1 and bag[-1] == last:  # se saca del final: que la última usada no salga la primera
                bag[0], bag[-1] = bag[-1], bag[0]
            self._bags[key] = bag
        clip = bag.pop()
        self._last[key] = clip
        return clip

    # ── Generación ─────────────────────────────────────────────────────────────

    def _stem(self, speaker: str, stage: str, index: int) -> str:
        return f"filler_{speaker}_{stage}{index:02d}"

    def _key(self, tts, speaker: str, text: str) -> str:
        return hashlib.sha1(f"{CLIP_VERSION}|{text}|{tts.signature(speaker)}".encode()).hexdigest()[:12]

    def _check_length(self, speaker: str, stage: str, clip: Clip) -> None:
        if not (self._s.filler_min_seconds <= clip.seconds <= self._s.filler_max_seconds):
            log.warning(
                "Muletilla de %s/%s dura %.1fs (objetivo %.1f–%.1fs): ajusta su texto en fillers.json: «%s»",
                speaker, stage, clip.seconds, self._s.filler_min_seconds, self._s.filler_max_seconds, clip.text,
            )

    async def warm(self, tts) -> None:
        """Carga de disco (o genera) cada muletilla de los personajes que tienen voz. Se intercalan los personajes y las
        etapas para que haya al menos una de apertura de cada uno cuanto antes."""
        if not self._s.filler_enabled:
            return
        jobs: list[tuple[str, str, int, str]] = []
        longest = max((len(texts) for stages in self._texts.values() for texts in stages.values()), default=0)
        for index in range(longest):
            for speaker, stages in self._texts.items():
                for stage in STAGES:
                    if index < len(stages.get(stage, [])):
                        jobs.append((speaker, stage, index, stages[stage][index]))

        generated = 0
        for speaker, stage, index, text in jobs:
            if not tts.ready(speaker):
                continue
            stem = self._stem(speaker, stage, index)
            mp3, meta = self._s.static_dir / f"{stem}.mp3", self._s.static_dir / f"{stem}.json"
            key = self._key(tts, speaker, text)
            clip = self._read(mp3, meta, key, text)
            if clip is None:
                try:
                    started = time.monotonic()
                    audio = (await speak(once(text), speaker, tts.synthesize_stream)).audio
                except Exception as e:
                    log.warning("No se pudo generar la muletilla %s: %s", stem, e)
                    continue
                try:
                    audio = tighten(audio)
                except Exception as e:  # sin recortar sigue sirviendo: solo dura un poco más
                    log.warning("No se pudo recortar el silencio de %s: %s", stem, e)
                clip = Clip.of(text, audio)
                # Hecha con una voz de emergencia: se usa ahora, pero no se guarda, para regenerarla con la voz buena en el próximo arranque.
                if not tts.degraded(started, speaker):
                    write_atomic(mp3, audio)
                    write_atomic(meta, json.dumps({"key": key, "text": text}, ensure_ascii=False).encode())
                generated += 1
            self._check_length(speaker, stage, clip)
            self.add(speaker, stage, clip)
        total = sum(len(v) for v in self._clips.values())
        log.info("Muletillas listas: %s (%s nuevas)", total, generated)

    @staticmethod
    def _read(mp3: Path, meta: Path, key: str, text: str) -> Clip | None:
        if not (mp3.exists() and meta.exists()):
            return None
        try:
            if json.loads(meta.read_text(encoding="utf-8")).get("key") != key:
                return None
            return Clip.of(text, mp3.read_bytes())
        except (ValueError, OSError):
            return None

    def describe(self) -> dict[str, dict[str, list[tuple[str, float]]]]:
        """Para scripts/check_fillers.py: texto y duración de cada muletilla cargada."""
        out: dict[str, dict[str, list[tuple[str, float]]]] = {}
        for (speaker, stage), clips in self._clips.items():
            out.setdefault(speaker, {})[stage] = [(c.text, c.seconds) for c in clips]
        return out
