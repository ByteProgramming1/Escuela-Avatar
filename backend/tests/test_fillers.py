"""Muletillas habladas: cuándo suenan, cuántas, en qué orden y qué pasa cuando algo falla.
Los tiempos son reales pero cortos (décimas de segundo) y las «duraciones» de los clips son inventadas para que la
cadena se pueda comprobar sin esperar segundos."""
import asyncio
import json
import time

import pytest

from app.assistant import APOLOGY_TEXT, REPROMPT_TEXT, Assistant
from app.config import Settings
from app.context import turn_context, wrap_question
from app.fillers import CONTINUE, OPENING, Clip, Fillers, load_texts
from app.knowledge import load_knowledge
from app.pipeline import History

from .fakes import FakeLLM, FakeSTT, FakeTTS, chains


def make(tmp_path, *, start=0.05, margin=0.1, max_chain=3, opening=1, cont=3, clip_seconds=0.3, speakers=("rectora",), **overrides):
    overrides.setdefault("interaction_log_enabled", False)
    settings = Settings(
        static_dir=tmp_path / "static", prime_cache_on_start=False, preload_presentation=False, filler_enabled=True,
        filler_start_seconds=start, filler_margin_seconds=margin, filler_max_chain=max_chain, **overrides,
    )
    stt, llm, tts = FakeSTT(), FakeLLM(), FakeTTS()
    fillers = Fillers(settings, texts={})
    for speaker in speakers:
        for i in range(opening):
            fillers.add(speaker, OPENING, Clip(f"apertura {i}", f"<A{i}>".encode(), clip_seconds))
        for i in range(cont):
            fillers.add(speaker, CONTINUE, Clip(f"continua {i}", f"<C{i}>".encode(), clip_seconds))
    assistant = Assistant(settings, load_knowledge(settings.knowledge_dir), *chains([stt], [llm], [tts]), fillers=fillers)
    return assistant, stt, llm, tts, settings


async def collect(assistant, speaker="rectora", **kwargs):
    """(trozos, instante de llegada de cada uno desde que se pidió)"""
    t0 = time.perf_counter()
    chunks, arrivals = [], []
    async for chunk in assistant.answer_audio_stream(b"wav", speaker, **kwargs):
        chunks.append(chunk)
        arrivals.append(time.perf_counter() - t0)
    return chunks, arrivals


def is_filler(chunk: bytes) -> bool:
    return chunk.startswith((b"<A", b"<C"))


# ── Cuándo y cuántas ──────────────────────────────────────────────────────────

async def test_first_filler_sounds_at_the_configured_second_then_the_answer_follows(tmp_path):
    assistant, _, llm, *_ = make(tmp_path, start=0.15)
    llm.delay = 0.3  # la respuesta tarda más que el plazo de la primera muletilla
    chunks, arrivals = await collect(assistant)
    assert chunks[0] == b"<A0>" and 0.14 < arrivals[0] < 0.25
    assert not any(is_filler(c) for c in chunks[1:]) and chunks[1].startswith(b"<fake-tts:rectora:")
    assert arrivals[1] > 0.3  # la respuesta real llegó cuando el LLM terminó de pensar, no antes


async def test_no_filler_when_the_answer_is_ready_before_the_deadline(tmp_path):
    assistant, *_ = make(tmp_path, start=0.5)
    report: dict = {}
    chunks, _ = await collect(assistant, report=report)
    assert not any(is_filler(c) for c in chunks) and report["timings"]["fillers"] == 0
    assert "filler_start" not in report["timings"]


async def test_chains_fillers_without_gaps_until_the_answer_is_ready(tmp_path):
    assistant, _, llm, *_ = make(tmp_path, start=0.05, margin=0.1, clip_seconds=0.3)
    llm.delay = 0.8
    report: dict = {}
    chunks, arrivals = await collect(assistant, report=report)
    fillers = [(c, t) for c, t in zip(chunks, arrivals) if is_filler(c)]
    assert [c[:2] for c, _ in fillers] == [b"<A", b"<C", b"<C"]  # una de apertura y dos de continuación (tope = 3)
    assert len({c for c, _ in fillers}) == 3  # no repite ninguna dentro de la cadena
    ends = 0.0  # cuándo acaba de sonar lo ya entregado, suponiendo que Unity reproduce en tiempo real
    for chunk, t in zip(chunks, arrivals):
        assert ends == 0.0 or t <= ends + 0.02, f"hueco de silencio de {t - ends:.2f}s antes de {chunk!r}"  # llega antes de que acabe lo anterior
        ends = max(ends, t) + (0.3 if is_filler(chunk) else 0.0)
    assert report["timings"]["fillers"] == 3 and report["fillers"] == [f"apertura 0", report["fillers"][1], report["fillers"][2]]
    assert report["timings"]["first_audio_total"] < 0.2 < report["timings"]["first_answer_audio_total"]


async def test_a_ready_answer_cuts_the_chain_short(tmp_path):
    assistant, _, llm, *_ = make(tmp_path, start=0.05, margin=0.1, clip_seconds=0.3)
    llm.delay = 0.2  # llega mientras suena la primera muletilla
    report: dict = {}
    chunks, _ = await collect(assistant, report=report)
    assert sum(is_filler(c) for c in chunks) == 1 and report["timings"]["fillers"] == 1


async def test_does_not_chain_beyond_max_chain(tmp_path):
    assistant, _, llm, *_ = make(tmp_path, start=0.02, margin=0.02, max_chain=2, clip_seconds=0.05)
    llm.delay = 0.4
    chunks, _ = await collect(assistant)
    assert sum(is_filler(c) for c in chunks) == 2


async def test_the_saved_file_contains_the_fillers_and_the_answer_exactly_as_streamed(tmp_path):
    assistant, _, llm, *_ = make(tmp_path)
    llm.delay = 0.2
    target = tmp_path / "static" / "r.mp3"
    chunks, _ = await collect(assistant, save_to=target)
    assert target.read_bytes() == b"".join(chunks) and is_filler(chunks[0])


# ── Transcripción vacía ───────────────────────────────────────────────────────

async def test_empty_transcript_before_the_deadline_asks_to_repeat_without_a_filler(tmp_path):
    assistant, stt, llm, *_ = make(tmp_path, start=0.3)
    stt.text = ""
    report: dict = {}
    chunks, _ = await collect(assistant, report=report)
    assert len(chunks) == 1 and chunks[0].startswith(b"<fake-tts:rectora:") and llm.calls == []
    assert report["answer"] == REPROMPT_TEXT and report["timings"]["fillers"] == 0


async def test_slow_stt_returning_nothing_asks_to_repeat_after_the_filler_that_already_sounded(tmp_path):
    assistant, stt, llm, *_ = make(tmp_path, start=0.05, clip_seconds=0.5)
    stt.text, stt.delay = "", 0.2
    chunks, _ = await collect(assistant)
    assert is_filler(chunks[0]) and b"repetir" in chunks[-1] and llm.calls == []


async def test_filler_does_not_wait_for_a_slow_stt(tmp_path):
    assistant, stt, llm, *_ = make(tmp_path, start=0.05, clip_seconds=0.5)
    stt.delay = 0.3
    chunks, arrivals = await collect(assistant)
    assert is_filler(chunks[0]) and arrivals[0] < 0.2 and llm.calls  # sonó antes de que el STT acabara y luego hubo respuesta


# ── Fallos ────────────────────────────────────────────────────────────────────

async def test_llm_failure_after_a_filler_is_apologised_aloud_instead_of_silence(tmp_path):
    assistant, _, llm, *_ = make(tmp_path, start=0.05, clip_seconds=0.5)
    llm.delay, llm.fail_before = 0.15, True
    report: dict = {}
    chunks, _ = await collect(assistant, report=report)
    assert is_filler(chunks[0]) and b"problema" in b"".join(chunks[1:])  # tras la muletilla suena la disculpa (el TTS la parte en frases)
    assert report["answer"] == APOLOGY_TEXT and "error" in report
    assert assistant.history.messages() == []  # una disculpa no entra en la conversación


async def test_llm_failure_before_any_sound_is_a_normal_error(tmp_path):
    assistant, _, llm, *_ = make(tmp_path, start=0.5)
    llm.fail_before = True
    with pytest.raises(RuntimeError, match="caído"):
        await collect(assistant)


async def test_without_fillers_for_the_speaker_the_stream_is_the_plain_answer(tmp_path):
    assistant, *_ = make(tmp_path, speakers=("oswaldo",))
    chunks, _ = await collect(assistant, speaker="rectora")  # la Rectora no tiene muletillas
    assert not any(is_filler(c) for c in chunks)


async def test_closing_the_stream_early_cancels_the_background_work(tmp_path):
    assistant, _, llm, *_ = make(tmp_path, start=0.02, clip_seconds=1.0)
    llm.delay = 5.0
    agen = assistant.answer_audio_stream(b"wav", "rectora")
    assert is_filler(await anext(agen))
    await agen.aclose()
    assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]


# ── Rotación y archivos ───────────────────────────────────────────────────────

def test_rotation_uses_every_filler_before_repeating_and_never_starts_with_the_last_one(tmp_path):
    fillers = Fillers(Settings(filler_enabled=True), texts={})
    for i in range(5):
        fillers.add("rectora", OPENING, Clip(f"t{i}", b"x", 4.0))
    last = None
    for _ in range(20):
        round_ = [fillers.next("rectora", OPENING).text for _ in range(5)]
        assert sorted(round_) == [f"t{i}" for i in range(5)]
        assert round_[0] != last
        last = round_[-1]
    assert fillers.next("rectora", CONTINUE) is None and fillers.next("oswaldo", OPENING) is None


async def test_warm_generates_once_reuses_the_files_and_regenerates_a_changed_text(tmp_path):
    settings = Settings(static_dir=tmp_path, filler_enabled=True, filler_min_seconds=0, filler_max_seconds=99)
    texts = {"rectora": {OPENING: ["Hola uno", "Hola dos"], CONTINUE: ["Sigo aquí"]}}
    tts = chains(tts_list=[FakeTTS()])[2]
    first = Fillers(settings, texts)
    await first.warm(tts)
    assert first.count("rectora", OPENING) == 2 and first.count("rectora", CONTINUE) == 1 and first.ready("rectora")
    assert not first.ready("oswaldo")
    calls = len(tts.providers[0].calls)
    assert calls == 3 and (tmp_path / "filler_rectora_opening00.mp3").exists()

    again = Fillers(settings, texts)
    await again.warm(tts)
    assert len(tts.providers[0].calls) == calls and again.count("rectora", OPENING) == 2  # todo salió de disco

    texts["rectora"][OPENING][1] = "Hola tres"
    changed = Fillers(settings, texts)
    await changed.warm(tts)
    assert len(tts.providers[0].calls) == calls + 1  # solo se regeneró la que cambió


def test_texts_file_ignores_comments_and_unknown_stages(tmp_path):
    path = tmp_path / "f.json"
    path.write_text(json.dumps({"_ayuda": "x", "rectora": {"opening": [" a ", ""], "otra": ["z"]}}), encoding="utf-8")
    assert load_texts(path) == {"rectora": {"opening": ["a"]}}
    assert load_texts(tmp_path / "no-existe.json") == {}


def test_the_shipped_fillers_file_has_many_phrases_per_speaker_and_stage():
    texts = load_texts(Settings().fillers_file)
    for speaker in ("rectora", "oswaldo"):
        assert len(texts[speaker][OPENING]) >= 14 and len(texts[speaker][CONTINUE]) >= 10
        for stage in (OPENING, CONTINUE):
            assert len(set(texts[speaker][stage])) == len(texts[speaker][stage])  # sin repetidas
            assert all("?" not in t and "¿" not in t for t in texts[speaker][stage])  # una muletilla no pregunta


# ── Contexto del turno ────────────────────────────────────────────────────────

async def test_live_questions_carry_the_turn_context_but_history_and_presentations_stay_plain(tmp_path):
    assistant, _, llm, *_ = make(tmp_path, speakers=())
    await assistant.answer_audio(b"wav", "rectora")
    await assistant.answer_audio(b"wav", "oswaldo")
    first, second = llm.calls[0][1], llm.calls[1][1]
    assert "<pregunta_de_la_persona>\n¿Cuánto cuesta la matrícula?\n</pregunta_de_la_persona>" in first
    assert "Hora local en Bogotá" in first and "La respuesta anterior la dio" not in first
    assert "La respuesta anterior la dio la Rectora" in second
    assert llm.calls[1][2][0] == {"role": "user", "content": "¿Cuánto cuesta la matrícula?"}  # el historial guarda la transcripción sola

    await assistant.generate_presentation(3, "rectora")
    assert llm.calls[-1][1] == assistant.questions[3] and "contexto" not in llm.calls[-1][1]


def test_turn_context_mentions_only_what_applies():
    from datetime import datetime

    from app.context import TIMEZONE

    now = datetime(2026, 10, 24, 15, 5, tzinfo=TIMEZONE)
    plain = turn_context(now, "rectora")
    assert "sábado 24 de octubre de 2026, 3:05 de la tarde" in plain and "muletilla" not in plain and "anterior" not in plain
    full = turn_context(now, "oswaldo", last_speaker="rectora", filler_played=True, extra=["Hay 3 personas frente a ti."])
    assert "muletilla" in full and "la Rectora" in full and full.endswith("Hay 3 personas frente a ti.")
    assert wrap_question("c", "hola") == "<contexto_del_sistema>\nc\n</contexto_del_sistema>\n\n<pregunta_de_la_persona>\nhola\n</pregunta_de_la_persona>"


def test_history_remembers_who_answered_and_forgets_with_the_rest(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    h = History(6, ttl_seconds=60)
    assert h.last_speaker is None
    h.add("p", "r", "oswaldo")
    assert h.last_speaker == "oswaldo"
    now[0] += 61
    assert h.last_speaker is None and h.messages() == []


async def test_every_answer_is_logged_and_gaps_in_the_knowledge_are_flagged(tmp_path):
    log = tmp_path / "logs" / "q.jsonl"
    assistant, _, llm, *_ = make(tmp_path, speakers=(), interaction_log_enabled=True, interaction_log_file=log)
    await assistant.answer_audio(b"wav", "rectora")

    class Derives(FakeLLM):
        async def stream_text(self, speaker, question, history):
            yield "Para ese dato escriba a Admisiones o llame al PBX. "

    assistant.llm.providers[:] = [Derives()]
    await collect(assistant, speaker="rectora")  # por el camino del stream también se registra
    lines = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [line["derived"] for line in lines] == [False, True]
    assert lines[0]["question"].startswith("¿Cuánto") and lines[0]["speaker"] == "rectora" and "total" in lines[0]["timings"]


def test_tighten_removes_the_silence_the_tts_leaves_at_both_ends():
    import numpy as np

    from app.audio import load_audio
    from app.fillers import tighten
    from app.mp3 import Mp3Stream

    t = np.arange(24_000) / 24_000
    speech = (0.3 * np.sin(2 * np.pi * 180 * t)).astype(np.float32)  # 1 s de «habla»
    pcm = np.concatenate([np.zeros(12_000, np.float32), speech, np.zeros(19_200, np.float32)])  # 0,5 s antes y 0,8 s después
    mp3 = Mp3Stream()
    padded = mp3.feed(pcm) + mp3.finish()
    assert 2.2 < len(load_audio(padded, 24_000)) / 24_000 < 2.4

    tight = tighten(padded)
    seconds = len(load_audio(tight, 24_000)) / 24_000
    assert 1.1 < seconds < 1.4  # ≈ 1 s de habla + 0,1 s de margen a cada lado
    assert tight[:2] != b"ID" and abs(len(tight) / 6000 - seconds) < 0.1  # sigue siendo MP3 CBR de 48 kbps, sin cabeceras ID3


# ── Respuesta a punto de sonar ────────────────────────────────────────────────

class SlowTTS(FakeTTS):
    """Cada frase tarda `delay` en salir (como el clon bajo carga)."""

    def __init__(self, delay):
        super().__init__("slow-tts")
        self.delay = delay

    async def synthesize_stream(self, text, speaker, previous_text=None):
        await asyncio.sleep(self.delay)
        yield await self.synthesize(text, speaker, previous_text)


def make_with_slow_tts(tmp_path, tts_delay, llm_delay, **kw):
    assistant, stt, llm, _, settings = make(tmp_path, **kw)
    llm.delay = llm_delay
    assistant.tts.providers[:] = [SlowTTS(tts_delay)]
    return assistant


async def test_the_opening_filler_waits_a_moment_when_the_answer_is_already_in_the_tts(tmp_path):
    # La primera frase entra al TTS a los 0,1 s y tarda 0,25 s: sonaría a los 0,35 s. La muletilla tocaba a los 0,2 s.
    assistant = make_with_slow_tts(tmp_path, tts_delay=0.25, llm_delay=0.1, start=0.2, clip_seconds=1.0, filler_imminent_seconds=0.5)
    chunks, arrivals = await collect(assistant)
    assert not any(is_filler(c) for c in chunks) and arrivals[0] < 0.5  # la respuesta pasó sin que una muletilla de 1 s la hiciera esperar


async def test_the_filler_is_not_held_back_when_the_tts_is_slow(tmp_path):
    # Lleva 0,5 s en el TTS y todavía tardará: pasada la ventana de espera suena la muletilla.
    assistant = make_with_slow_tts(tmp_path, tts_delay=1.2, llm_delay=0.1, start=0.2, clip_seconds=1.5, filler_imminent_seconds=0.4)
    chunks, arrivals = await collect(assistant)
    assert is_filler(chunks[0]) and 0.45 < arrivals[0] < 0.75  # 0,1 s (frase en el TTS) + 0,4 s de espera = ~0,5 s


async def test_no_deferral_when_the_tts_has_not_started_yet(tmp_path):
    assistant = make_with_slow_tts(tmp_path, tts_delay=0.1, llm_delay=0.6, start=0.2, clip_seconds=1.0, filler_imminent_seconds=0.5)
    chunks, arrivals = await collect(assistant)
    assert is_filler(chunks[0]) and 0.18 < arrivals[0] < 0.35  # el LLM aún no ha escrito nada: nada que esperar
