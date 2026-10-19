"""Genera (o carga de disco) todas las muletillas de fillers.json con el TTS real y mide cuánto dura cada una.
Cada muletilla debe durar ~4 s (FILLER_MIN_SECONDS–FILLER_MAX_SECONDS); las que no, hay que acortarlas o alargarlas
en fillers.json (unas diez a trece palabras). Los clips quedan en static/ y el servidor los reutiliza.

    .venv/bin/python -m scripts.check_fillers          # desde backend/
"""
import asyncio
import logging
import statistics
import sys
import time

from app.config import Settings
from app.fallback import build_chains
from app.fillers import STAGES, Fillers
from app.knowledge import load_knowledge


async def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    s = Settings()
    _, _, tts = build_chains(s, load_knowledge(s.knowledge_dir), http=None)
    fillers = Fillers(s)
    if not fillers.has_texts():
        print(f"❌ No hay textos en {s.fillers_file} (o FILLER_ENABLED=false)")
        return 1
    for speaker in ("rectora", "oswaldo"):
        print(f"TTS {speaker:8} {tts.describe(speaker)}")
    t0 = time.time()
    await tts.warm()
    await fillers.warm(tts)
    print(f"\nListas en {time.time() - t0:.0f} s (lo que ya estaba en disco no se vuelve a generar)\n")

    bad = 0
    for speaker, stages in sorted(fillers.describe().items()):
        for stage in STAGES:
            clips = stages.get(stage, [])
            if not clips:
                continue
            secs = [d for _, d in clips]
            print(f"{speaker:8} {stage:9} {len(clips):2} muletillas · {min(secs):.1f}–{max(secs):.1f} s (media {statistics.mean(secs):.1f} s)")
            for text, d in clips:
                if not (s.filler_min_seconds <= d <= s.filler_max_seconds):
                    bad += 1
                    print(f"    ⚠️  {d:.1f} s  «{text}»")
    print("\n" + ("✅ Todas duran lo previsto." if not bad else f"⚠️  {bad} fuera de {s.filler_min_seconds:.1f}–{s.filler_max_seconds:.1f} s: ajusta su texto en fillers.json y vuelve a correr esto."))
    print("Escucha static/filler_*.mp3 para comprobar que suenan naturales.")
    return 0 if not bad else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
