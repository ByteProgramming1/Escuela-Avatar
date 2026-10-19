import asyncio
import json
import logging
from contextlib import asynccontextmanager

import anthropic
import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from google.genai import errors as genai_errors
from pydantic import BaseModel

from .assistant import SAFE_FILENAME, Assistant, write_atomic
from .config import ROOT, Settings
from .fallback import build_chains
from .knowledge import load_knowledge
from .personas import PERSONAS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("eci")


class PresentationIn(BaseModel):
    question: int
    speaker: str = "rectora"


class TtsIn(BaseModel):
    text: str
    speaker: str = "rectora"
    filename: str


def build_assistant(settings: Settings, http: httpx.AsyncClient) -> Assistant:
    knowledge = load_knowledge(settings.knowledge_dir)
    stt, llm, tts = build_chains(settings, knowledge, http)
    return Assistant(settings, knowledge, stt, llm, tts)


def create_app(assistant: Assistant | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.static_dir.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        http = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0))
        app.state.assistant = assistant or build_assistant(settings, http)
        for stage, chain in app.state.assistant.describe().items():
            log.info("%-14s %s", stage, chain)
        if not app.state.assistant.llm.ready():
            log.warning("SIN LLM: pon GEMINI_API_KEY (gratis, https://aistudio.google.com/apikey) o ANTHROPIC_API_KEY en backend/.env")
        warm = asyncio.create_task(app.state.assistant.warm_up())
        yield
        warm.cancel()
        await http.aclose()

    app = FastAPI(title="ECI voice backend", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")

    def check_speaker(speaker: str) -> str:
        if speaker not in PERSONAS:
            raise HTTPException(400, f"speaker desconocido: {speaker!r}. Opciones: {sorted(PERSONAS)}")
        return speaker

    def check_filename(name: str) -> str:
        if not SAFE_FILENAME.match(name):
            raise HTTPException(400, "filename inválido: solo letras, números, _ y - terminando en .mp3")
        return name

    @app.exception_handler(httpx.HTTPStatusError)
    async def provider_http_error(_, e: httpx.HTTPStatusError):
        host = e.request.url.host
        log.error("Proveedor %s respondió %s: %s", host, e.response.status_code, e.response.text[:300])
        return JSONResponse({"detail": f"{host} respondió {e.response.status_code}"}, status_code=502)

    @app.exception_handler(anthropic.APIError)
    async def claude_error(_, e: anthropic.APIError):
        log.error("Anthropic: %s", e)
        return JSONResponse({"detail": f"Claude: {e}"}, status_code=502)

    @app.exception_handler(genai_errors.APIError)
    async def gemini_error(_, e: genai_errors.APIError):
        log.error("Gemini: %s", e)
        return JSONResponse({"detail": f"Gemini: {e}"}, status_code=502)

    @app.exception_handler(RuntimeError)
    async def config_error(_, e: RuntimeError):
        log.error("%s", e)
        return JSONResponse({"detail": str(e)}, status_code=503)

    @app.get("/health")
    async def health():
        a = app.state.assistant
        return {"ok": True, "knowledge_version": a.knowledge.version, "speakers": sorted(PERSONAS), "providers": a.describe()}

    @app.get("/e2e", include_in_schema=False)
    async def e2e_page():
        """Página para probar de punta a punta con el micrófono del navegador (backend/web/e2e.html).
        Se sirve desde aquí: así comparte origen con la API y `localhost` cuenta como contexto seguro para el micrófono."""
        return FileResponse(ROOT / "web" / "e2e.html", headers={"Cache-Control": "no-store"})

    @app.post("/audio")
    async def audio(
        audio: UploadFile = File(...),
        speaker: str = Form("rectora"),
        response_file: str | None = Form(None),
    ):
        """Audio del usuario → texto → respuesta → voz clonada. Deja el MP3 en /static/<response_file>."""
        speaker = check_speaker(speaker)
        filename = check_filename(response_file or f"response_{speaker}.mp3")
        reply = await app.state.assistant.answer_audio(await audio.read(), speaker)
        write_atomic(settings.static_dir / filename, reply.audio)
        return {"result": reply.text, "transcript": reply.transcript, "file": filename, "speaker": speaker, "timings": reply.timings}

    @app.post("/audio/stream")
    async def audio_stream(
        audio: UploadFile = File(...),
        speaker: str = Form("rectora"),
        response_file: str | None = Form(None),
    ):
        """Como /audio, pero responde con el MP3 en streaming: el primer audio llega mientras el LLM
        todavía escribe. Al terminar también deja el archivo completo en /static/<response_file>."""
        speaker = check_speaker(speaker)
        filename = check_filename(response_file or f"response_{speaker}.mp3")
        report: dict = {}
        agen = app.state.assistant.answer_audio_stream(await audio.read(), speaker, settings.static_dir / filename, report)
        try:
            first = await anext(agen)  # los errores previos al primer audio salen como HTTP normal
        except StopAsyncIteration:
            raise HTTPException(502, "La respuesta no produjo audio")

        async def body():
            try:
                yield first
                async for chunk in agen:
                    yield chunk
                # Lo que el stream no puede llevar (qué entendió el STT, el texto y los tiempos) queda junto al MP3,
                # listo antes de que termine la respuesta. Unity lo ignora; lo lee la página /e2e.
                write_atomic(settings.static_dir / (filename[:-4] + ".json"), json.dumps(report, ensure_ascii=False).encode())
            finally:
                await agen.aclose()

        return StreamingResponse(body(), media_type="audio/mpeg", headers={"Cache-Control": "no-store"})

    @app.post("/presentation")
    async def presentation(body: PresentationIn):
        """Pregunta pregrabada N (1-10): respuesta generada una vez y servida desde disco."""
        speaker = check_speaker(body.speaker)
        try:
            file, text = await app.state.assistant.presentation(body.question, speaker)
        except KeyError:
            raise HTTPException(404, f"No existe la pregunta {body.question} en questions.json")
        return {"result": text, "file": file, "question": body.question, "speaker": speaker}

    @app.post("/tts")
    async def tts(body: TtsIn):
        """Texto → voz clonada, sin LLM (guion de la intro)."""
        speaker = check_speaker(body.speaker)
        filename = check_filename(body.filename)
        if not body.text.strip():
            raise HTTPException(400, "text vacío")
        write_atomic(settings.static_dir / filename, await app.state.assistant.say(body.text, speaker))
        return {"result": "ok", "file": filename, "speaker": speaker}

    @app.post("/reset")
    async def reset():
        """Olvida el contexto de la conversación (útil al cambiar de persona en el evento)."""
        app.state.assistant.history.clear()
        return {"result": "ok"}

    return app


app = create_app()
