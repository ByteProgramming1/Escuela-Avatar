import time

import httpx
import pytest

from app.config import Settings
from app.fallback import build_chains, is_transient
from app.knowledge import load_knowledge

from .fakes import FakeLLM, FakeSTT, FakeTTS, Overloaded, chains


async def collect(llm_chain, speaker="rectora"):
    return "".join([d async for d in llm_chain.stream_text(speaker, "hola", [])])


async def test_llm_falls_over_to_the_next_provider_and_skips_the_failed_one_afterwards():
    primary, backup = FakeLLM("principal"), FakeLLM("respaldo")
    primary.fail_before = True
    _, llm, _ = chains(llms=[primary, backup])
    assert "Responde rectora" in await collect(llm)
    await collect(llm)
    assert len(primary.calls) == 1 and len(backup.calls) == 2  # el segundo intento ya no toca al caído
    assert llm.signature() == "principal"  # la firma es la del principal aunque esté en cooldown
    assert llm.degraded(since=0)


async def test_llm_does_not_switch_models_mid_answer():
    primary, backup = FakeLLM("principal"), FakeLLM("respaldo")
    primary.fail_after = True
    _, llm, _ = chains(llms=[primary, backup])
    with pytest.raises(RuntimeError, match="a medias"):
        await collect(llm)
    assert backup.calls == []


async def test_if_every_provider_is_cooling_down_it_still_tries():
    only = FakeLLM("unico")
    only.fail_before = True
    _, llm, _ = chains(llms=[only])
    for _ in range(2):
        with pytest.raises(RuntimeError, match="unico caído"):
            await collect(llm)
    assert len(only.calls) == 2


async def test_llm_retries_a_503_on_the_last_provider_without_marking_it_as_failed():
    only = FakeLLM("unico")
    only.overloaded_times = 2
    _, llm, _ = chains(llms=[only], retries=2)
    started = time.monotonic()
    assert "Responde rectora" in await collect(llm)
    assert len(only.calls) == 3
    assert not llm.degraded(since=started)  # se recuperó solo: el audio resultante es de calidad normal


async def test_llm_gives_up_after_the_retries_and_then_cools_down():
    only = FakeLLM("unico")
    only.overloaded_times = 5
    _, llm, _ = chains(llms=[only], retries=2)
    started = time.monotonic()
    with pytest.raises(Overloaded):
        await collect(llm)
    assert len(only.calls) == 3
    assert "unico" in llm._failed_until  # entra en cooldown
    assert not llm.degraded(since=started)  # pero con un solo proveedor no hay "respaldo": nada es de emergencia


async def test_a_failure_elsewhere_does_not_taint_answers_from_the_only_provider():
    only = FakeLLM("unico")
    _, llm, _ = chains(llms=[only])
    started = time.monotonic()
    llm._fail(only, RuntimeError("otra pregunta falló"))  # lo que dejaría una petición concurrente que sí falló
    assert not llm.degraded(since=started)


async def test_llm_does_not_retry_errors_that_would_fail_again():
    only = FakeLLM("unico")
    only.fail_before = True  # RuntimeError genérico: clave inválida, cuota, petición mal formada...
    _, llm, _ = chains(llms=[only], retries=2)
    with pytest.raises(RuntimeError, match="unico caído"):
        await collect(llm)
    assert len(only.calls) == 1


async def test_llm_with_a_backup_switches_at_once_instead_of_waiting_for_retries():
    primary, backup = FakeLLM("principal"), FakeLLM("respaldo")
    primary.overloaded_times = 5
    _, llm, _ = chains(llms=[primary, backup], retries=2)
    assert "Responde rectora" in await collect(llm)
    assert len(primary.calls) == 1 and len(backup.calls) == 1


async def test_llm_does_not_retry_once_the_answer_has_started():
    only = FakeLLM("unico")
    only.fail_after = True
    _, llm, _ = chains(llms=[only], retries=2)
    with pytest.raises(RuntimeError, match="a medias"):
        await collect(llm)
    assert len(only.calls) == 1


def test_which_errors_count_as_transient():
    assert is_transient(Overloaded("x"))
    assert is_transient(httpx.ConnectTimeout("x")) and is_transient(TimeoutError()) and is_transient(ConnectionError())
    assert not is_transient(RuntimeError("clave inválida"))

    class Quota(RuntimeError):
        code = 429  # límite de cuota: reintentar enseguida no lo arregla

    assert not is_transient(Quota("x"))


async def test_stt_failover():
    bad, good = FakeSTT("x"), FakeSTT("hola mundo")
    bad.fail = True
    bad.name, good.name = "malo", "bueno"
    stt, *_ = chains(stt=[bad, good])
    assert await stt.transcribe(b"") == "hola mundo"
    assert stt.describe() == "malo → bueno"


async def test_tts_picks_provider_per_speaker():
    pago, gratis = FakeTTS("pago", speakers=("oswaldo",)), FakeTTS("gratis")
    *_, tts = chains(tts_list=[pago, gratis])
    assert await tts.synthesize("hola", "oswaldo") == b"<pago:oswaldo:hola>"
    assert await tts.synthesize("hola", "rectora") == b"<gratis:rectora:hola>"  # sin voz de pago para ella
    assert tts.describe("oswaldo") == "pago → gratis" and tts.describe("rectora") == "gratis"
    pago.fail = True
    assert await tts.synthesize("otra", "oswaldo") == b"<gratis:oswaldo:otra>"


async def test_no_providers_gives_actionable_error():
    _, llm, tts = chains(llms=[], tts_list=[])
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        await collect(llm)
    with pytest.raises(RuntimeError, match="No hay TTS disponible para rectora"):
        await tts.synthesize("x", "rectora")
    assert not llm.ready()


def test_auto_mode_orders_paid_first_and_free_second(tmp_path):
    kb = load_knowledge(Settings().knowledge_dir)

    def desc(**kw):
        stt, llm, tts = build_chains(Settings(_env_file=None, voices_dir=tmp_path / "sin-voces", **kw), kb, http=None)
        return stt.describe(), llm.describe(), tts.describe("rectora"), tts.describe("oswaldo")

    # sin ninguna clave: Whisper y voz genérica siempre disponibles; LLM solo si hay clave de Gemini
    assert desc() == ("whisper", "NINGUNO", "edge", "edge")
    assert desc(gemini_api_key="g")[1] == "gemini"
    # con claves de pago: de pago primero, gratis como respaldo
    full = desc(deepgram_api_key="d", anthropic_api_key="a", gemini_api_key="g", elevenlabs_api_key="e", voice_id_rectora="v")
    assert full == ("deepgram → whisper", "anthropic → gemini", "elevenlabs → edge", "edge")  # Oswaldo sin voz clonada → genérica
    # forzar un proveedor concreto desactiva los demás
    forced = desc(deepgram_api_key="d", stt_provider="whisper", tts_provider="edge", llm_provider="gemini", gemini_api_key="g")
    assert forced == ("whisper", "gemini", "edge", "edge")
    # un segundo modelo gratuito de Gemini (cuota propia) queda detrás del primero, solo si se pide y es otro modelo
    second = desc(gemini_api_key="g", gemini_fallback_model="otro-modelo")
    assert second[1] == "gemini → gemini_fallback"
    assert desc(gemini_api_key="g", gemini_fallback_model="gemini-3.5-flash-lite")[1] == "gemini"  # el mismo modelo no se duplica
    assert desc(anthropic_api_key="a", gemini_api_key="g", gemini_fallback_model="otro-modelo")[1] == "anthropic → gemini → gemini_fallback"


def test_second_gemini_model_has_its_own_name_signature_and_model():
    from app.gemini import Gemini

    s = Settings(gemini_api_key="k", gemini_fallback_model="otro-modelo")
    kb = load_knowledge(s.knowledge_dir)
    first = Gemini(s, kb)
    second = Gemini(s, kb, client=first._client, model=s.gemini_fallback_model, name="gemini_fallback")
    assert (first.name, second.name) == ("gemini", "gemini_fallback")  # la cadena castiga a cada proveedor por su nombre
    assert first.signature() != second.signature() and second.signature().endswith("otro-modelo")


async def test_tts_stream_fails_over_only_before_the_first_chunk():
    class Streaming:
        def __init__(self, name, fail_at):
            self.name, self.fail_at = name, fail_at

        def available(self, speaker):
            return True

        def signature(self, speaker):
            return self.name

        async def synthesize_stream(self, text, speaker, previous_text=None):
            for i in range(3):
                if i == self.fail_at:
                    raise RuntimeError(f"{self.name} falló en el trozo {i}")
                yield f"{self.name}{i}".encode()

    async def collect_(chain):
        return [c async for c in chain.synthesize_stream("hola", "rectora")]

    *_, tts = chains(tts_list=[Streaming("a", fail_at=0), Streaming("b", fail_at=99)])
    assert await collect_(tts) == [b"b0", b"b1", b"b2"]  # falló antes de emitir → pasa al siguiente

    *_, tts = chains(tts_list=[Streaming("a", fail_at=2), Streaming("b", fail_at=99)])
    with pytest.raises(RuntimeError, match="trozo 2"):
        await collect_(tts)  # ya había emitido: no se mezclan dos voces en una frase
