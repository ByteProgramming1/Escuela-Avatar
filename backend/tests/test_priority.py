"""La GPU del clon de voz es de una frase a la vez. Lo que se oye en vivo debe pasar antes que el trabajo de
segundo plano (regenerar las preguntas pregrabadas): sin esto, una pregunta real esperó 26 s detrás de ellas."""
import asyncio
import time

from app.assistant import Assistant
from app.config import Settings
from app.knowledge import load_knowledge
from app.priority import PriorityGate, background, live, live_count

from .fakes import FakeLLM, FakeSTT, chains


async def hold(gate, order, name, seconds=0.0, is_background=None):
    async with gate.slot(is_background):
        order.append(name)
        await asyncio.sleep(seconds)


async def test_live_requests_go_before_background_ones_that_arrived_first():
    gate, order = PriorityGate(), []
    first = asyncio.create_task(hold(gate, order, "en uso", 0.05, True))
    await asyncio.sleep(0.01)
    tasks = [asyncio.create_task(hold(gate, order, f"fondo{i}", 0.0, True)) for i in range(3)]
    await asyncio.sleep(0.01)
    tasks.append(asyncio.create_task(hold(gate, order, "vivo", 0.0, False)))
    await asyncio.gather(first, *tasks)
    assert order == ["en uso", "vivo", "fondo0", "fondo1", "fondo2"]  # lo que ya corría no se interrumpe; después, lo vivo primero


async def test_order_of_arrival_is_kept_within_the_same_priority():
    gate, order = PriorityGate(), []
    tasks = [asyncio.create_task(hold(gate, order, i, 0.01, False)) for i in range(4)]
    await asyncio.gather(*tasks)
    assert order == [0, 1, 2, 3]


async def test_background_work_does_not_start_while_a_conversation_is_live_and_resumes_after():
    gate, order = PriorityGate(), []
    with live():
        assert live_count() == 1
        task = asyncio.create_task(hold(gate, order, "fondo", 0.0, True))
        await asyncio.sleep(0.05)
        assert order == []  # hay alguien esperando respuesta: el trabajo de fondo espera
        await hold(gate, order, "vivo", 0.0, False)  # lo vivo sí pasa
    await asyncio.wait_for(task, 1.0)
    assert order == ["vivo", "fondo"] and live_count() == 0


async def test_a_cancelled_waiter_does_not_block_the_gate():
    gate, order = PriorityGate(), []
    first = asyncio.create_task(hold(gate, order, "uno", 0.05))
    await asyncio.sleep(0.01)
    doomed = asyncio.create_task(hold(gate, order, "cancelado"))
    await asyncio.sleep(0.01)
    doomed.cancel()
    last = asyncio.create_task(hold(gate, order, "ultimo"))
    await asyncio.wait_for(asyncio.gather(first, last), 1.0)
    assert order == ["uno", "ultimo"]


async def test_background_context_marks_every_task_created_inside_it():
    gate, order = PriorityGate(), []
    with live():
        with background():
            task = asyncio.create_task(hold(gate, order, "fondo"))  # sin prioridad explícita: la toma del contexto
        await asyncio.sleep(0.05)
        assert order == []
        await hold(gate, order, "vivo")
    await asyncio.wait_for(task, 1.0)
    assert order == ["vivo", "fondo"]


class GpuTTS:
    """TTS falso que usa la misma cola que el clon: cada frase tarda 0,05 s en «la GPU»."""

    name = "gpu-tts"

    def __init__(self):
        self.gate, self.log = PriorityGate(), []

    def available(self, speaker):
        return True

    def signature(self, speaker):
        return "gpu-tts"

    async def synthesize_stream(self, text, speaker, previous_text=None):
        async with self.gate.slot():
            await asyncio.sleep(0.05)
            self.log.append(text)
            yield f"<{text}>".encode()


async def test_a_live_question_is_not_stuck_behind_a_backlog_of_presentations(tmp_path):
    settings = Settings(static_dir=tmp_path, prime_cache_on_start=False, preload_presentation=False, filler_enabled=False, interaction_log_enabled=False)
    tts = GpuTTS()
    from app.fallback import LLMChain, STTChain, TTSChain

    assistant = Assistant(settings, load_knowledge(settings.knowledge_dir), STTChain([FakeSTT()], 60), LLMChain([FakeLLM()], 60), TTSChain([tts], 60))

    async def regenerate(n):
        with background():
            await assistant.generate_presentation(n, "rectora")

    backlog = [asyncio.create_task(regenerate(n)) for n in range(1, 9)]  # varias frases cada una = mucha cola de GPU
    await asyncio.sleep(0.12)
    t0 = time.perf_counter()
    first = None
    async for chunk in assistant.answer_audio_stream(b"wav", "rectora"):
        first = first or time.perf_counter() - t0
    assert first < 0.3, f"la primera frase en vivo esperó {first:.2f}s detrás del trabajo de fondo"  # sin prioridad serían ≥ 0,6 s
    assert live_count() == 0
    await asyncio.gather(*backlog)  # el trabajo de fondo termina cuando se libera la conversación
    assert all((tmp_path / f"presentation_rectora_q{n}.mp3").exists() for n in range(1, 9))
