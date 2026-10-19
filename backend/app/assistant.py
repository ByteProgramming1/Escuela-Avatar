import asyncio
import contextlib
import hashlib
import json
import logging
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .audio import write_atomic
from .config import Settings
from .context import TIMEZONE, turn_context, wrap_question
from .fillers import CONTINUE, OPENING, Fillers
from .knowledge import Knowledge
from .personas import PERSONAS
from .pipeline import History, Spoken, once, speak, speak_stream
from .priority import background, live

log = logging.getLogger("eci.assistant")

SAFE_FILENAME = re.compile(r"^[A-Za-z0-9_\-]{1,80}\.mp3$")
REPROMPT_TEXT = "Perdón, no alcancé a escucharlo bien. ¿Podría repetir la pregunta?"
APOLOGY_TEXT = "Perdón, tuve un problema técnico para responderle. ¿Podría repetir la pregunta en un momento?"
DERIVED_WORDS = ("admisiones", "pbx", "escuelaing", "línea nacional")  # una respuesta que deriva a estos canales suele ser un hueco del conocimiento


@dataclass
class Reply:
    transcript: str
    text: str
    audio: bytes
    timings: dict[str, float]


class Assistant:
    """Orquesta voz → texto → respuesta → voz. `stt`, `llm` y `tts` son cadenas de proveedores
    (ver fallback.py), pero cualquier objeto con la misma interfaz sirve (los tests usan falsos)."""

    def __init__(self, settings: Settings, knowledge: Knowledge, stt, llm, tts, fillers: Fillers | None = None):
        self.settings = settings
        self.knowledge = knowledge
        self.stt, self.llm, self.tts = stt, llm, tts
        self.history = History(settings.history_turns, settings.history_ttl_seconds)
        self.questions = self._load_questions(settings.questions_file)
        self.fillers = fillers if fillers is not None else Fillers(settings)
        self._reprompt: dict[str, bytes] = {}
        self._apology: dict[str, bytes] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._refreshing: set[str] = set()  # preguntas que se están regenerando en segundo plano
        self._refresh_not_before: dict[str, float] = {}
        self._refresh_slot = asyncio.Semaphore(1)  # una regeneración en segundo plano a la vez: no inundar al LLM ni a la GPU
        self._tasks: set[asyncio.Task] = set()  # referencias fuertes: asyncio solo guarda débiles

    @staticmethod
    def _load_questions(path: Path) -> dict[int, str]:
        if not path.exists():
            return {}
        return {int(k): v for k, v in json.loads(path.read_text(encoding="utf-8")).items()}

    def describe(self) -> dict[str, str]:
        """Qué proveedores están activos, en orden de uso (para /health y el log de arranque)."""
        out = {"stt": self.stt.describe(), "llm": self.llm.describe()}
        out.update({f"tts[{sp}]": self.tts.describe(sp) for sp in PERSONAS})
        return out

    # ── Voz → texto → respuesta → voz ─────────────────────────────────────────

    async def _listen(self, wav: bytes, speaker: str) -> tuple[str, float]:
        t0 = time.perf_counter()
        transcript = await self.stt.transcribe(wav)
        took = time.perf_counter() - t0
        log.info("[%s] stt %.2fs: %r", speaker, took, transcript)
        return transcript, took

    async def _reprompt_audio(self, speaker: str) -> bytes:
        if speaker not in self._reprompt:
            self._reprompt[speaker] = (await speak(once(REPROMPT_TEXT), speaker, self.tts.synthesize_stream)).audio
        return self._reprompt[speaker]

    def _reply_stream(self, speaker: str, transcript: str, filler_played: bool = False) -> AsyncIterator[str]:
        """La pregunta lleva delante el contexto del turno (hora, quién habló antes, muletilla): va en el mensaje del
        usuario y no en el bloque cacheado, así la caché de reglas + conocimiento no cambia entre preguntas."""
        context = turn_context(datetime.now(TIMEZONE), speaker, self.history.last_speaker, filler_played)
        return self.llm.stream_text(speaker, wrap_question(context, transcript), self.history.messages())

    async def _apology_audio(self, speaker: str) -> bytes:
        """Disculpa hablada para cuando falla el LLM después de haber empezado a sonar. Vacía si tampoco hay TTS."""
        if speaker not in self._apology:
            try:
                self._apology[speaker] = (await speak(once(APOLOGY_TEXT), speaker, self.tts.synthesize_stream)).audio
            except Exception as e:
                log.warning("No se pudo generar la disculpa de %s: %s", speaker, e)
                return b""
        return self._apology[speaker]

    def _log_interaction(self, speaker: str, transcript: str, answer: str, timings: dict, error: str | None = None) -> None:
        """Una línea por pregunta en logs/questions.jsonl; marca `derived` si la respuesta mandó a Admisiones/PBX (hueco del conocimiento)."""
        if not self.settings.interaction_log_enabled:
            return
        try:
            line = {
                "at": datetime.now(TIMEZONE).isoformat(timespec="seconds"),
                "speaker": speaker,
                "question": transcript,
                "answer": answer,
                "derived": any(w in answer.lower() for w in DERIVED_WORDS),
                "timings": timings,
                **({"error": error} if error else {}),
            }
            path = self.settings.interaction_log_file
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
        except Exception as e:  # el registro nunca debe impedir que se conteste
            log.warning("No se pudo registrar la pregunta: %s", e)

    async def answer_audio(self, wav: bytes, speaker: str) -> Reply:
        with live():  # mientras alguien espera, el trabajo de segundo plano no ocupa la GPU
            return await self._answer_audio(wav, speaker)

    async def _answer_audio(self, wav: bytes, speaker: str) -> Reply:
        t0 = time.perf_counter()
        transcript, t_stt = await self._listen(wav, speaker)
        if len(transcript) < 3:  # silencio o ruido: pedir que repita, hablado
            return Reply(transcript, REPROMPT_TEXT, await self._reprompt_audio(speaker), {"stt": round(t_stt, 2)})

        spoken = await speak(self._reply_stream(speaker, transcript), speaker, self.tts.synthesize_stream)
        self.history.add(transcript, spoken.text, speaker)
        timings = {"stt": round(t_stt, 2), **spoken.timings, "total": round(time.perf_counter() - t0, 2)}
        log.info("[%s] %s", speaker, timings)
        self._log_interaction(speaker, transcript, spoken.text, timings)
        return Reply(transcript, spoken.text, spoken.audio, timings)

    async def answer_audio_stream(
        self, wav: bytes, speaker: str, save_to: Path | None = None, report: dict | None = None
    ) -> AsyncIterator[bytes]:
        """Igual que answer_audio pero entrega el MP3 por trozos en cuanto cada frase está lista.
        Si se completa, también deja el archivo entero en `save_to` (respaldo para el cliente).
        Si se pasa `report`, se rellena con transcripción, respuesta y tiempos.
        Con muletillas disponibles para el personaje, a los `filler_start_seconds` empieza a sonar una mientras la
        respuesta se prepara (y otra si hace falta); sin ellas, el audio es solo la respuesta."""
        inner = (
            self._stream_with_fillers(wav, speaker, save_to, report)
            if self.fillers.ready(speaker)
            else self._stream_plain(wav, speaker, save_to, report)
        )
        try:
            with live():  # mientras alguien espera, el trabajo de segundo plano no ocupa la GPU
                async for chunk in inner:
                    yield chunk
        finally:
            await inner.aclose()  # cancela el trabajo en segundo plano si el cliente se desconecta

    async def _stream_plain(self, wav: bytes, speaker: str, save_to: Path | None, report: dict | None) -> AsyncIterator[bytes]:
        t0 = time.perf_counter()
        transcript, t_stt = await self._listen(wav, speaker)
        if len(transcript) < 3:
            audio = await self._reprompt_audio(speaker)
            if save_to:
                write_atomic(save_to, audio)
            if report is not None:
                report.update(transcript=transcript, answer=REPROMPT_TEXT, timings={"stt": round(t_stt, 2)}, bytes=len(audio))
            yield audio
            return

        out, buf = Spoken(), bytearray()
        async for chunk in speak_stream(self._reply_stream(speaker, transcript), speaker, self.tts.synthesize_stream, out):
            buf += chunk
            yield chunk
        # Solo se llega aquí si el cliente recibió todo (si se desconecta, el generador se cierra antes)
        self.history.add(transcript, out.text, speaker)
        if save_to:
            write_atomic(save_to, bytes(buf))
        timings = {"stt": round(t_stt, 2), **out.timings, "total": round(time.perf_counter() - t0, 2)}
        timings["first_audio_total"] = round(t_stt + out.timings["first_audio"], 2)  # desde que llega el audio hasta que suena
        if report is not None:
            report.update(transcript=transcript, answer=out.text, timings=timings, bytes=len(buf))
        log.info("[%s] stream %s", speaker, timings)
        self._log_interaction(speaker, transcript, out.text, timings)

    async def _stream_with_fillers(self, wav: bytes, speaker: str, save_to: Path | None, report: dict | None) -> AsyncIterator[bytes]:
        """Planificador de muletillas. El reloj corre desde que llega el audio. La primera sale a los `filler_start_seconds`
        (no depende de lo que dijo la persona, así que no espera al STT); cada una de las siguientes se entrega
        `filler_margin_seconds` antes de que acabe la anterior (estimado por bytes), para que nunca haya un hueco,
        y solo si el primer trozo de la respuesta real todavía no está listo."""
        s = self.settings
        t0 = time.perf_counter()
        stt = asyncio.ensure_future(self._listen(wav, speaker))
        out, buf = Spoken(), bytearray()
        gen = first = None  # el pipeline de la respuesta real y la tarea que espera su primer trozo
        transcript, t_stt = None, 0.0
        played: list[str] = []
        heard_until = t0  # cuándo acaba de sonar lo ya enviado
        next_at = t0 + s.filler_start_seconds  # cuándo toca decidir la siguiente muletilla
        t_first_sound = t_first_answer = None

        def start_answer() -> None:
            nonlocal gen, first
            # filler_played=True: el LLM debe empezar directo, sin saludo ni elogio de la pregunta
            gen = speak_stream(self._reply_stream(speaker, transcript, filler_played=True), speaker, self.tts.synthesize_stream, out)
            first = asyncio.ensure_future(anext(gen))

        try:
            while True:
                if transcript is None and stt.done():
                    transcript, t_stt = stt.result()
                    if len(transcript) >= 3:
                        start_answer()
                if first is not None and first.done():
                    break  # ya hay audio real: se corta la cadena de muletillas
                if transcript is not None and len(transcript) < 3:
                    break
                now = time.perf_counter()
                # La respuesta ya está en el TTS desde hace poco: sonará enseguida. Una muletilla de ~4 s soltada ahora la
                # haría esperar hasta que acabe, así que se aguarda un momento más (solo la de apertura, y con tope).
                imminent_until = out.first_sentence_at + s.filler_imminent_seconds if (out.first_sentence_at and not played) else 0.0
                if now >= next_at and now < imminent_until:
                    await asyncio.wait([first], timeout=imminent_until - now, return_when=asyncio.FIRST_COMPLETED)
                    continue
                if now >= next_at:
                    clip = self.fillers.next(speaker, OPENING if not played else CONTINUE) if len(played) < s.filler_max_chain else None
                    if clip is None:
                        break  # sin más muletillas: se espera la respuesta tal cual
                    if t_first_sound is None:
                        t_first_sound = now - t0
                    played.append(clip.text)
                    buf += clip.audio
                    heard_until = max(heard_until, now) + clip.seconds
                    next_at = heard_until - s.filler_margin_seconds
                    yield clip.audio
                    continue
                waiting = [t for t in (stt if transcript is None else None, first) if t is not None and not t.done()]
                await asyncio.wait(waiting, timeout=next_at - now, return_when=asyncio.FIRST_COMPLETED)

            if transcript is None:
                transcript, t_stt = await stt
            if len(transcript) < 3:  # silencio o ruido (o el STT acabó cuando ya sonaba una muletilla): pedir que repita
                audio = await self._reprompt_audio(speaker)
                buf += audio
                if save_to:
                    write_atomic(save_to, bytes(buf))
                if report is not None:
                    timings = {"stt": round(t_stt, 2), "fillers": len(played)}
                    report.update(transcript=transcript, answer=REPROMPT_TEXT, timings=timings, bytes=len(buf), fillers=played)
                yield audio
                return
            if gen is None:
                start_answer()

            chunk = await first
            t_first_answer = time.perf_counter() - t0
            buf += chunk
            yield chunk
            async for chunk in gen:
                buf += chunk
                yield chunk
        except Exception as e:
            if not played:  # todavía no ha sonado nada: error HTTP normal, como sin muletillas
                raise
            log.exception("[%s] falló la respuesta después de las muletillas", speaker)
            apology = await self._apology_audio(speaker)
            if apology:
                buf += apology
                if save_to:
                    write_atomic(save_to, bytes(buf))
                if report is not None:
                    report.update(transcript=transcript or "", answer=APOLOGY_TEXT, timings={"fillers": len(played)}, bytes=len(buf), error=str(e)[:200])
                self._log_interaction(speaker, transcript or "", APOLOGY_TEXT, {"fillers": len(played)}, error=str(e)[:200])
                yield apology
            return
        finally:
            pending = [t for t in (stt, first) if t is not None]
            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            if gen is not None:
                await gen.aclose()

        # Solo se llega aquí si el cliente recibió todo (si se desconecta, el generador se cierra antes)
        self.history.add(transcript, out.text, speaker)
        if save_to:
            write_atomic(save_to, bytes(buf))
        first_sound = t_first_sound if t_first_sound is not None else t_first_answer
        timings = {"stt": round(t_stt, 2), **out.timings, "total": round(time.perf_counter() - t0, 2), "fillers": len(played)}
        timings["first_audio_total"] = round(first_sound, 2)  # primer sonido, sea muletilla o respuesta
        timings["first_answer_audio_total"] = round(t_first_answer, 2)  # primer audio de la respuesta de verdad
        if t_first_sound is not None:
            timings["filler_start"] = round(t_first_sound, 2)
        if report is not None:
            report.update(transcript=transcript, answer=out.text, timings=timings, bytes=len(buf), fillers=played)
        log.info("[%s] stream %s", speaker, timings)
        self._log_interaction(speaker, transcript, out.text, timings)

    async def say(self, text: str, speaker: str) -> bytes:
        """Texto → voz sin pasar por el LLM (frases de la intro)."""
        return (await speak(once(text), speaker, self.tts.synthesize_stream)).audio

    # ── Preguntas pregrabadas (teclas 0-9) ────────────────────────────────────

    def _presentation_key(self, n: int, speaker: str) -> str:
        raw = "|".join([self.knowledge.version, speaker, self.questions[n], self.llm.signature(), self.tts.signature(speaker)])
        return hashlib.sha1(raw.encode()).hexdigest()[:12]

    def _read_presentation(self, n: int, speaker: str) -> tuple[str, str, bool] | None:
        """(archivo, texto, vigente) de lo que haya en disco, o None si no hay nada utilizable."""
        name = f"presentation_{speaker}_q{n}"
        mp3 = self.settings.static_dir / f"{name}.mp3"
        meta = self.settings.static_dir / f"{name}.json"
        if not (mp3.exists() and meta.exists()):
            return None
        try:
            cached = json.loads(meta.read_text(encoding="utf-8"))
            return mp3.name, cached["answer"], cached.get("key") == self._presentation_key(n, speaker)
        except (ValueError, KeyError):  # metadatos corruptos: es como si no hubiera nada
            log.warning("Metadatos de %s ilegibles; se vuelve a generar", name)
            return None

    async def presentation(self, n: int, speaker: str) -> tuple[str, str]:
        """Devuelve (archivo, texto) al instante para las teclas 0-9 de Unity. Si en disco hay una respuesta
        desactualizada o hecha de emergencia se sirve igual (mejor eso que un silencio de 20 s) y se regenera
        en segundo plano; solo si no hay nada se espera a generarla."""
        if n not in self.questions:
            raise KeyError(n)
        cached = self._read_presentation(n, speaker)
        if cached is None:
            with live():  # alguien está esperando este audio: que lo de segundo plano no se le adelante
                return await self.generate_presentation(n, speaker)
        file, answer, current = cached
        if not current:
            self._refresh_in_background(n, speaker)
        return file, answer

    def _refresh_in_background(self, n: int, speaker: str) -> None:
        name = f"presentation_{speaker}_q{n}"
        now = time.monotonic()
        if name in self._refreshing or self._refresh_not_before.get(name, 0.0) > now:
            return
        # Con el proveedor principal caído solo saldría otro audio de emergencia: se espera a que se recupere.
        if self.llm.degraded(now) or self.tts.degraded(now, speaker):
            return
        self._refreshing.add(name)

        async def run() -> None:
            try:
                async with self._refresh_slot:
                    log.info("Regenerando en segundo plano %s (estaba desactualizada o era de emergencia)", name)
                    with background():
                        await self.generate_presentation(n, speaker)
            except Exception as e:
                log.warning("No se pudo regenerar %s: %s", name, e)
            finally:
                self._refreshing.discard(name)
                self._refresh_not_before[name] = time.monotonic() + self.settings.presentation_refresh_seconds

        task = asyncio.create_task(run())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def generate_presentation(self, n: int, speaker: str) -> tuple[str, str]:
        """Genera la respuesta (esperando a que esté completa) salvo que ya haya una vigente. Se guarda en
        disco y solo cambia si cambia la pregunta, el contexto, la voz o los modelos (p. ej. al poner claves de pago)."""
        name = f"presentation_{speaker}_q{n}"
        mp3 = self.settings.static_dir / f"{name}.mp3"
        meta = self.settings.static_dir / f"{name}.json"
        key = self._presentation_key(n, speaker)

        async with self._locks.setdefault(name, asyncio.Lock()):
            cached = self._read_presentation(n, speaker)
            if cached and cached[2]:
                return cached[0], cached[1]
            started = time.monotonic()
            spoken = await speak(self.llm.stream_text(speaker, self.questions[n], []), speaker, self.tts.synthesize_stream)
            # Si hubo que saltarse al proveedor principal, este audio es de emergencia: se sirve pero
            # no se da por bueno, para que en cuanto el principal vuelva se regenere.
            degraded = self.llm.degraded(started) or self.tts.degraded(started, speaker)
            write_atomic(mp3, spoken.audio)
            meta.write_text(
                json.dumps({"key": key + ("!degraded" if degraded else ""), "question": self.questions[n], "answer": spoken.text}, ensure_ascii=False),
                encoding="utf-8",
            )
            log.info("[%s] pregunta %s lista %s%s", speaker, n, spoken.timings, " (con respaldo)" if degraded else "")
            return mp3.name, spoken.text

    # ── Arranque ──────────────────────────────────────────────────────────────

    async def warm_up(self) -> None:
        jobs = [self.stt.warm(), self.tts.warm()]
        if self.settings.prime_cache_on_start:
            jobs.append(self.llm.prime())
        await asyncio.gather(*jobs, return_exceptions=True)

        # Muletillas y frases de emergencia antes que las preguntas pregrabadas: son lo primero que se oye en vivo.
        with background():
            try:
                await self.fillers.warm(self.tts)
            except Exception as e:
                log.warning("No se pudieron preparar las muletillas: %s", e)
            if self.settings.preload_presentation:  # mismo interruptor que las pregrabadas: es audio que se prepara al arrancar
                for sp in PERSONAS:
                    if self.tts.ready(sp):
                        with contextlib.suppress(Exception):
                            await self._reprompt_audio(sp)
                        await self._apology_audio(sp)

        if self.settings.preload_presentation and self.llm.ready():
            sem = asyncio.Semaphore(2)

            async def one(n: int, speaker: str) -> None:
                async with sem:
                    try:
                        with background():
                            await self.generate_presentation(n, speaker)
                    except Exception as e:
                        log.warning("Precarga pregunta %s/%s falló: %s", speaker, n, e)

            await asyncio.gather(*(one(n, sp) for sp in PERSONAS if self.tts.ready(sp) for n in self.questions))
            log.info("Preguntas pregrabadas listas")
