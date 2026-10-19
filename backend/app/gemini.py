import logging
from collections.abc import AsyncIterator

from google import genai
from google.genai import types

from .config import Settings
from .knowledge import Knowledge
from .llm import REFUSAL_TEXT
from .personas import PERSONAS

log = logging.getLogger("eci.gemini")


class Gemini:
    """LLM gratuito de respaldo (capa gratuita de Google AI Studio). Misma base de conocimiento y
    mismas reglas de voz que Claude. El caché de prompt es implícito, no hace falta configurarlo."""

    name = "gemini"

    def __init__(
        self,
        settings: Settings,
        knowledge: Knowledge,
        client: genai.Client | None = None,
        model: str | None = None,
        name: str | None = None,
    ):
        """`model` y `name` permiten una segunda instancia (otro modelo gratuito, con su propia cuota) en la misma
        cadena: la cadena castiga a los proveedores por `name`, así que cada instancia necesita el suyo."""
        self._s = settings
        self._knowledge = knowledge
        self._injected = client is not None
        self._client = client or (genai.Client(api_key=settings.gemini_api_key) if settings.gemini_api_key else None)
        self._model = model or settings.gemini_model
        if name:
            self.name = name

    def available(self) -> bool:
        return self._client is not None

    def signature(self) -> str:
        return f"gemini:{self._model}"

    async def prime(self) -> None:
        pass

    def _config(self, speaker: str) -> types.GenerateContentConfig:
        s = self._s
        thinking = types.ThinkingConfig(thinking_level=s.gemini_thinking_level) if s.gemini_thinking_level else None
        return types.GenerateContentConfig(
            system_instruction=f"{self._knowledge.system_text}\n\n{PERSONAS[speaker].prompt}",
            max_output_tokens=s.gemini_max_output_tokens,
            thinking_config=thinking,
        )

    @staticmethod
    def _contents(question: str, history: list[dict]) -> list[types.Content]:
        turns = [*history, {"role": "user", "content": question}]
        return [
            types.Content(role="user" if m["role"] == "user" else "model", parts=[types.Part(text=m["content"])])
            for m in turns
        ]

    async def stream_text(self, speaker: str, question: str, history: list[dict]) -> AsyncIterator[str]:
        stream = await self._client.aio.models.generate_content_stream(
            model=self._model,
            contents=self._contents(question, history),
            config=self._config(speaker),
        )
        emitted = False
        async for chunk in stream:
            text = chunk.text
            if text:
                emitted = True
                yield text
        if not emitted:  # bloqueo de seguridad o respuesta vacía
            log.warning("Gemini no devolvió texto")
            yield REFUSAL_TEXT
