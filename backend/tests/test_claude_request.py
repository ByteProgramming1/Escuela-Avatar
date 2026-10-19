"""Ejecuta el cliente real de la SDK de Anthropic contra un transporte simulado para
comprobar el request que realmente se envía (caché, effort, fallbacks) y el parseo del stream."""
import json

import anthropic
import httpx2 as httpx  # la SDK de Anthropic 1.x usa httpx2

from app.config import Settings
from app.knowledge import load_knowledge
from app.llm import Claude


def sse(*events):
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def message_stream(text_parts, stop="end_turn"):
    events = [
        {"type": "message_start", "message": {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5", "content": [], "stop_reason": None, "usage": {"input_tokens": 10, "output_tokens": 0, "cache_read_input_tokens": 5000}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    ]
    events += [{"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": t}} for t in text_parts]
    events += [
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": stop}, "usage": {"output_tokens": 7}},
        {"type": "message_stop"},
    ]
    return httpx.Response(200, content=sse(*events), headers={"content-type": "text/event-stream"})


def make(handler):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = anthropic.AsyncAnthropic(api_key="k", http_client=http, max_retries=0)
    settings = Settings()
    return Claude(settings, load_knowledge(settings.knowledge_dir), client=client)


async def collect(claude, speaker="rectora"):
    return "".join([d async for d in claude.stream_text(speaker, "¿Cuánto cuesta?", [])])


async def test_request_shape_and_streaming():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["headers"] = request.headers
        return message_stream(["Hola ", "mundo."])

    text = await collect(make(handler))
    body, headers = seen["body"], seen["headers"]
    assert text == "Hola mundo."
    assert body["model"] == "claude-opus-5-5" and body["stream"] is True
    assert body["output_config"] == {"effort": "low"}
    assert body["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in headers["anthropic-beta"]
    kb, persona = body["system"]
    assert kb["cache_control"] == {"type": "ephemeral", "ttl": "1h"} and "BASE_DE_CONOCIMIENTO" in kb["text"]
    assert "cache_control" not in persona and "Myriam Astrid Angarita" in persona["text"]
    assert body["messages"] == [{"role": "user", "content": "¿Cuánto cuesta?"}]


async def test_both_speakers_share_the_cached_prefix():
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return message_stream(["ok."])

    claude = make(handler)
    await collect(claude, "rectora"); await collect(claude, "oswaldo")
    assert bodies[0]["system"][0] == bodies[1]["system"][0]
    assert bodies[0]["system"][1] != bodies[1]["system"][1]


async def test_retries_without_fallbacks_if_beta_is_rejected():
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append("fallbacks" in body)
        if "fallbacks" in body:
            return httpx.Response(400, json={"type": "error", "error": {"type": "invalid_request_error", "message": "unknown beta"}})
        return message_stream(["Sin fallbacks."])

    claude = make(handler)
    assert await collect(claude) == "Sin fallbacks."
    assert await collect(claude) == "Sin fallbacks."
    assert calls == [True, False, False]  # tras el primer rechazo ya no lo vuelve a intentar


async def test_refusal_without_text_gets_a_spoken_apology():
    claude = make(lambda r: message_stream([], stop="refusal"))
    assert "Prefiero no responder" in await collect(claude)
