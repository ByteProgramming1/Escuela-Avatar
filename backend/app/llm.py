import logging
from collections.abc import AsyncIterator

import anthropic

from .config import Settings
from .knowledge import Knowledge
from .personas import PERSONAS

log = logging.getLogger("eci.llm")

FALLBACK_BETA = "server-side-fallback-2026-07-01"
REFUSAL_TEXT = "Prefiero no responder eso. ¿Hay algo más de la Escuela en lo que pueda ayudarles?"


class Claude:
    """Respuesta en streaming. La base de conocimiento va en el primer bloque de `system`
    con cache_control, por lo que se paga una sola vez y se lee del caché en cada pregunta
    (menor latencia y costo). La persona va después del punto de caché, así que Rectora y
    Oswaldo comparten el mismo prefijo cacheado."""

    name = "anthropic"

    def __init__(self, settings: Settings, knowledge: Knowledge, client: anthropic.AsyncAnthropic | None = None):
        self._s = settings
        self._knowledge = knowledge
        self._injected = client is not None
        self._client = client or anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key or "missing")
        self._use_fallbacks = settings.llm_fallbacks

    def available(self) -> bool:
        return self._injected or bool(self._s.anthropic_api_key)

    def signature(self) -> str:
        return f"anthropic:{self._s.llm_model}:{self._s.llm_effort}"

    def _params(self, speaker: str, messages: list[dict]) -> dict:
        return {
            "model": self._s.llm_model,
            "max_tokens": self._s.llm_max_tokens,
            "system": [
                {
                    "type": "text",
                    "text": self._knowledge.system_text,
                    # 1 h: entre rondas de preguntas puede haber pausas largas
                    "cache_control": {"type": "ephemeral", "ttl": "1h"},
                },
                {"type": "text", "text": PERSONAS[speaker].prompt},
            ],
            "output_config": {"effort": self._s.llm_effort},
            "messages": messages,
        }

    def _stream(self, params: dict):
        if self._use_fallbacks:
            return self._client.beta.messages.stream(
                **params, betas=[FALLBACK_BETA], fallbacks="default"
            )
        return self._client.messages.stream(**params)

    async def stream_text(self, speaker: str, question: str, history: list[dict]) -> AsyncIterator[str]:
        params = self._params(speaker, [*history, {"role": "user", "content": question}])
        emitted = False
        while True:
            try:
                async with self._stream(params) as stream:
                    async for delta in stream.text_stream:
                        emitted = True
                        yield delta
                    final = await stream.get_final_message()
                break
            except anthropic.BadRequestError as e:
                # Cuenta sin acceso a la beta de fallbacks: seguir sin ella en vez de caer.
                if self._use_fallbacks and not emitted:
                    log.warning("Fallbacks rechazados (%s); continúo sin ellos", e)
                    self._use_fallbacks = False
                    continue
                raise

        u = final.usage
        log.info(
            "llm in=%s out=%s cache_read=%s cache_write=%s stop=%s",
            u.input_tokens, u.output_tokens,
            getattr(u, "cache_read_input_tokens", 0), getattr(u, "cache_creation_input_tokens", 0),
            final.stop_reason,
        )
        if final.stop_reason == "refusal" and not emitted:
            yield REFUSAL_TEXT

    async def prime(self) -> None:
        """Escribe el caché del prompt al arrancar para que la primera pregunta real no pague el prefill."""
        try:
            params = self._params("rectora", [{"role": "user", "content": "warmup"}])
            params["max_tokens"] = 0
            r = await self._client.messages.create(**params)
            u = r.usage
            log.info(
                "caché listo: write=%s read=%s tokens",
                getattr(u, "cache_creation_input_tokens", 0), getattr(u, "cache_read_input_tokens", 0),
            )
        except Exception as e:
            log.warning("No se pudo precalentar el caché: %s", e)
