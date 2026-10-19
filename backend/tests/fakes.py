"""Proveedores falsos con la misma interfaz que los reales, metidos en cadenas reales."""
import asyncio

from app.fallback import LLMChain, STTChain, TTSChain


class Overloaded(RuntimeError):
    """Como el 503 de Gemini ("high demand"): los SDK reales traen el código HTTP en `.code` / `.status_code`."""

    code = 503


class FakeSTT:
    name = "fake-stt"

    def __init__(self, text="¿Cuánto cuesta la matrícula?"):
        self.text, self.calls, self.fail = text, 0, False
        self.delay = 0.0  # segundos que tarda en transcribir

    def available(self):
        return True

    def signature(self):
        return "fake-stt"

    async def warm(self):
        pass

    async def transcribe(self, wav):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("stt caído")
        return self.text


class FakeLLM:
    name = "fake-llm"

    def __init__(self, name="fake-llm"):
        self.name, self.calls, self.fail_before, self.fail_after = name, [], False, False
        self.overloaded_times = 0  # las primeras N llamadas fallan con un 503 antes del primer token
        self.delay = 0.0  # segundos hasta el primer token

    def available(self):
        return True

    def signature(self):
        return self.name

    async def prime(self):
        pass

    async def stream_text(self, speaker, question, history):
        self.calls.append((speaker, question, history))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.overloaded_times > 0:
            self.overloaded_times -= 1
            raise Overloaded(f"{self.name} sobrecargado")
        if self.fail_before:
            raise RuntimeError(f"{self.name} caído")
        for i, part in enumerate(["La matrícula depende de los ingresos familiares. ", f"Responde {speaker} con mucho gusto y detalle. ", "Con gusto les cuento más. "]):
            await asyncio.sleep(0)
            yield part
            if self.fail_after and i == 0:
                raise RuntimeError(f"{self.name} se cayó a medias")


class FakeTTS:
    def __init__(self, name="fake-tts", speakers=("rectora", "oswaldo")):
        self.name, self.speakers, self.calls, self.fail = name, speakers, [], False

    def available(self, speaker):
        return speaker in self.speakers

    def signature(self, speaker):
        return f"{self.name}:{speaker}"

    async def synthesize(self, text, speaker, previous_text=None):
        self.calls.append((text, speaker))
        if self.fail:
            raise RuntimeError(f"{self.name} caído")
        return f"<{self.name}:{speaker}:{text}>".encode()


def chains(stt=None, llms=None, tts_list=None, cooldown=60, retries=0):
    return (
        STTChain([FakeSTT()] if stt is None else stt, cooldown),
        LLMChain([FakeLLM()] if llms is None else llms, cooldown, retries, retry_delay=0),
        TTSChain([FakeTTS()] if tts_list is None else tts_list, cooldown),
    )
