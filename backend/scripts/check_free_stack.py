"""Comprueba en TU máquina el camino gratuito: qué proveedores quedan activos, que Whisper carga,
que las voces genéricas (mujer/hombre) suenan y que Whisper entiende lo que dicen.

    .venv/bin/python -m scripts.check_free_stack          # desde backend/
"""
import asyncio
import shutil
import subprocess
import time

from app.config import Settings
from app.fallback import build_chains
from app.knowledge import load_knowledge
from app.stt import LocalWhisper
from app.tts import EdgeTTS

PHRASE = "Hola, bienvenidos a la Escuela Colombiana de Ingeniería Julio Garavito."


async def main() -> None:
    s = Settings()
    stt, llm, tts = build_chains(s, load_knowledge(s.knowledge_dir), http=None)
    print(f"STT  : {stt.describe()}\nLLM  : {llm.describe()}" + ("" if llm.ready() else "   <- pon GEMINI_API_KEY (gratis) o ANTHROPIC_API_KEY en .env"))
    for sp in ("rectora", "oswaldo"):
        print(f"TTS  : {sp:8} {tts.describe(sp)}")

    whisper, edge = LocalWhisper(s), EdgeTTS(s)
    t = time.time(); await whisper.warm(); print(f"\nWhisper '{s.whisper_model}' cargado en {time.time() - t:.1f}s")
    s.static_dir.mkdir(exist_ok=True)
    for sp in ("rectora", "oswaldo"):
        t = time.time(); mp3 = await edge.synthesize(PHRASE, sp)
        out = s.static_dir / f"check_{sp}.mp3"; out.write_bytes(mp3)
        line = f"{sp:8} voz {s.__getattribute__('edge_voice_' + sp)}: {len(mp3)} bytes en {time.time() - t:.1f}s -> {out}"
        if shutil.which("ffmpeg"):
            wav = out.with_suffix(".wav")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(out), "-ar", "44100", "-ac", "1", str(wav)], check=True)
            t = time.time(); heard = await whisper.transcribe(wav.read_bytes()); wav.unlink()
            line += f"\n         Whisper entendió ({time.time() - t:.1f}s): {heard!r}"
        print(line)
    print("\nEscucha static/check_*.mp3 para comprobar las voces.")


if __name__ == "__main__":
    asyncio.run(main())
