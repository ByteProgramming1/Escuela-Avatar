import asyncio

import pytest

from app.pipeline import History, SentenceChunker, Spoken, once, speak, speak_stream, stream_of


def chunks(text_parts):
    c = SentenceChunker()
    out = []
    for p in text_parts:
        out += c.feed(p)
    if (tail := c.flush()) is not None:
        out.append(tail)
    return out


def test_first_chunk_is_short_and_later_ones_are_grouped():
    text = "La Escuela fue fundada en mil novecientos setenta y dos. Es privada. Tiene dieciséis carreras profesionales. Está en Bogotá. Y mucho más."
    out = chunks([text])
    assert out[0] == "La Escuela fue fundada en mil novecientos setenta y dos."
    assert " ".join(out) == text  # no se pierde ni se duplica nada
    assert out[1].startswith("Es privada. Tiene")  # frases cortas se agrupan


def test_streaming_in_small_pieces_gives_same_result_as_whole():
    text = "Claro que sí. Nuestras carreras son dieciséis y todas son presenciales. ¿Quieren conocer los laboratorios? Los esperamos."
    pieces = [text[i : i + 5] for i in range(0, len(text), 5)]
    assert chunks(pieces) == chunks([text])


def test_abbreviation_does_not_split():
    out = chunks(["Hable con el Ing. Castillo para más información sobre el programa. Gracias."])
    assert out[0].startswith("Hable con el Ing. Castillo")


def test_waits_for_whitespace_after_period():
    c = SentenceChunker()
    assert c.feed("Esto es una frase suficientemente larga para salir.") == []
    assert c.feed(" Sigue") == ["Esto es una frase suficientemente larga para salir."]


async def test_speak_joins_audio_in_order_even_if_later_chunks_finish_first():
    delays = {"A": 0.15, "B": 0.0}
    seen_previous = []

    async def synth(text, speaker, previous):
        seen_previous.append(previous)
        await asyncio.sleep(delays[text[0]])
        return f"[{text}]".encode()

    async def stream():
        yield "A" + "a" * 45 + ". "
        yield "B" + "b" * 85 + ". "

    r = await speak(stream(), "rectora", stream_of(synth))
    assert r.audio.startswith(b"[Aaaa") and r.audio.endswith(b"b.]")
    assert seen_previous[0] is None and seen_previous[1].startswith("Aaaa")
    assert r.text.startswith("Aaaa") and set(r.timings) == {"llm_first_token", "llm_total", "first_audio", "tts_tail", "speak_total"}


async def test_speak_stream_yields_first_chunk_before_the_llm_finishes():
    seen = []

    async def synth(text, speaker, previous):
        return text.encode()

    async def slow_llm():
        yield "Primera frase bastante larga para salir sola. "
        await asyncio.sleep(0.3)  # el LLM sigue "pensando"
        yield "Segunda frase que tarda mucho más en llegar desde el modelo de lenguaje. "

    out = Spoken()
    t0 = asyncio.get_running_loop().time()
    async for chunk in speak_stream(slow_llm(), "rectora", stream_of(synth), out):
        seen.append((asyncio.get_running_loop().time() - t0, chunk))
    assert seen[0][1].startswith(b"Primera") and seen[0][0] < 0.2 and seen[1][0] >= 0.3
    assert out.timings["first_audio"] < out.timings["llm_total"] and out.text.startswith("Primera")


async def test_speak_stops_everything_when_a_chunk_fails():
    cancelled = []

    async def synth(text, speaker, previous):
        if text.startswith("buena"):
            return b"ok"
        if text.startswith("mala"):
            await asyncio.sleep(0.1)
            raise ValueError("boom")
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            cancelled.append(text)
            raise

    async def stream():
        yield "buena " * 8 + ". "
        await asyncio.sleep(0.02)
        yield "mala " * 20 + ". "
        await asyncio.sleep(0.02)
        yield "otra " * 20 + ". "
        await asyncio.sleep(5)  # el LLM nunca termina: también debe cancelarse

    with pytest.raises(ValueError):
        await speak(stream(), "rectora", stream_of(synth))
    assert [c[:4] for c in cancelled] == ["otra"]


async def test_closing_the_stream_early_cancels_background_work():
    cancelled = []

    async def synth(text, speaker, previous):
        try:
            await asyncio.sleep(0.01 if text.startswith("uno") else 5)
        except asyncio.CancelledError:
            cancelled.append(text[:3])
            raise
        return b"x"

    async def stream():
        yield "uno " * 12 + ". "
        yield "dos " * 25 + ". "
        await asyncio.sleep(5)

    gen = speak_stream(stream(), "rectora", stream_of(synth), Spoken())
    assert await anext(gen) == b"x"  # cliente recibe el primer trozo y se desconecta
    await gen.aclose()
    assert cancelled == ["dos"]


async def test_speak_single_short_text():
    async def synth(text, speaker, previous):
        return text.encode()

    r = await speak(once("Hola."), "rectora", stream_of(synth))
    assert r.audio == b"Hola." and r.text == "Hola."


def test_history_keeps_recent_turns_and_expires(monkeypatch):
    h = History(max_turns=2, ttl_seconds=10)
    t = [100.0]
    monkeypatch.setattr("app.pipeline.time.monotonic", lambda: t[0])
    h.add("q1", "a1"); h.add("q2", "a2"); h.add("q3", "a3")
    assert [m["content"] for m in h.messages()] == ["q2", "a2", "q3", "a3"]
    t[0] += 11
    assert h.messages() == []


async def test_speak_stream_forwards_sub_chunks_as_they_are_produced_and_keeps_sentence_order():
    """Un TTS en streaming (como el clon local) entrega varios trozos por frase; no se mezclan entre frases."""
    gate = asyncio.Event()

    async def synth(text, speaker, previous):
        for i in range(3):
            if text.startswith("uno") and i == 2:
                await gate.wait()  # el último trozo de la primera frase tarda
            yield f"{text[:3]}{i}|".encode()
            await asyncio.sleep(0)

    async def stream():
        yield "uno " * 12 + ". "
        yield "dos " * 25 + ". "

    seen = []
    async for chunk in speak_stream(stream(), "rectora", synth, Spoken()):
        seen.append(chunk)
        if chunk == b"uno1|":
            gate.set()  # la 2.ª frase ya generó sus trozos, pero NO puede colarse antes de terminar la 1.ª
    assert seen == [b"uno0|", b"uno1|", b"uno2|", b"dos0|", b"dos1|", b"dos2|"]


def test_first_chunk_starts_at_a_comma_when_the_first_sentence_is_long():
    text = ("Para el año dos mil veintisiete, el valor del semestre en nuestra Escuela oscila entre siete y dieciséis millones de pesos, "
            "según el programa y los ingresos de su familia. Además tenemos becas.")
    out = chunks([text])
    assert out[0] == "Para el año dos mil veintisiete, el valor del semestre en nuestra Escuela oscila entre siete y dieciséis millones de pesos,"
    assert " ".join(out) == text  # nada se pierde
    pieces = [text[i : i + 7] for i in range(0, len(text), 7)]
    assert chunks(pieces) == out  # igual llegando de a poco
    # una coma temprana NO corta (sonaría entrecortado)
    assert chunks(["Sí, claro, con mucho gusto les explico todo el proceso de admisión de la Escuela."])[0].startswith("Sí, claro, con mucho gusto")
