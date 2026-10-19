"""Compara modelos de Whisper en TU máquina: cuánto tarda cada uno en transcribir tus audios y cuánto se parece su
texto al del modelo de referencia (el más grande de la lista). Sirve para decidir si `WHISPER_MODEL=base` (más rápido)
sigue entendiendo bien los nombres y siglas de la Escuela, o si hay que quedarse con `small`.

    .venv/bin/python -m scripts.check_stt                                   # base vs small con audios-test/*
    .venv/bin/python -m scripts.check_stt --models tiny base small medium --audio mi_pregunta.m4a
"""
import argparse
import asyncio
import statistics
import time
from pathlib import Path

from app.audio import load_audio, to_wav_bytes
from app.config import ROOT, Settings
from app.stt import LocalWhisper

from .e2e_voice import word_error_rate

AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac", ".mp4", ".mov"}
DOMAIN_TERMS = ["eci", "escuela", "garavito", "icetex", "saber", "matrícula", "admisiones", "becas", "acreditación", "ingeniería", "rectora", "vicerrector"]


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", nargs="+", default=["base", "small"], help="de menor a mayor; el último hace de referencia")
    ap.add_argument("--audio", nargs="+", help="audios de prueba (por defecto, los de backend/audios-test)")
    ap.add_argument("--runs", type=int, default=3, help="repeticiones por audio para sacar la mediana")
    args = ap.parse_args()
    audios = [Path(a) for a in args.audio] if args.audio else sorted(p for p in (ROOT / "audios-test").glob("*") if p.suffix.lower() in AUDIO_SUFFIXES)
    if not audios:
        raise SystemExit("No hay audios: pasa --audio o pon grabaciones en backend/audios-test/")
    wavs = {a: to_wav_bytes(load_audio(a, 44_100), 44_100) for a in audios}  # como el WAV de Unity (44,1 kHz)

    results: dict[str, dict[Path, tuple[float, str]]] = {}
    for model in args.models:
        stt = LocalWhisper(Settings(whisper_model=model))
        t = time.perf_counter()
        await stt.warm()
        print(f"\n── {model}: cargado en {time.perf_counter() - t:.1f} s")
        results[model] = {}
        for a in audios:
            await stt.transcribe(wavs[a])  # la primera pasada calienta
            times, text = [], ""
            for _ in range(args.runs):
                t = time.perf_counter()
                text = await stt.transcribe(wavs[a])
                times.append(time.perf_counter() - t)
            results[model][a] = (statistics.median(times), text)
            print(f"   {a.name:28} {len(wavs[a]) / 88_200:5.1f} s de audio → {results[model][a][0]:.2f} s   «{text[:90]}»")

    ref = args.models[-1]
    print(f"\nResumen (referencia = {ref}; error = palabras distintas respecto a la referencia)")
    for model in args.models:
        secs = [results[model][a][0] for a in audios]
        wer = [word_error_rate(results[ref][a][1], results[model][a][1]) for a in audios]
        terms = sum(d in results[model][a][1].lower() for a in audios for d in DOMAIN_TERMS)
        print(f"   {model:10} mediana {statistics.median(secs):.2f} s · error {statistics.mean(wer) * 100:4.0f}% · términos de la Escuela reconocidos: {terms}")
    print("\nSi un modelo más pequeño es claramente más rápido y el error y los términos reconocidos casi no cambian, ponlo en .env (WHISPER_MODEL=…).")


if __name__ == "__main__":
    asyncio.run(main())
