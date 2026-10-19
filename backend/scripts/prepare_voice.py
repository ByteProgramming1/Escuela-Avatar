"""Prepara la voz de referencia de un personaje: la limpia, la recorta y la transcribe.

    .venv/bin/python -m scripts.prepare_voice AUDIO SPEAKER [--seconds 12] [--no-transcribe]

    AUDIO    cualquier audio o video con la voz (wav, mp3, m4a, mp4, mov…)
    SPEAKER  rectora | oswaldo   →   escribe voices/<speaker>.wav y voices/<speaker>.txt
"""
import argparse
import asyncio
import sys
import wave

import numpy as np

from app.audio import load_audio, normalize_loudness, to_wav_bytes, trim_silence
from app.config import Settings
from app.personas import PERSONAS
from app.stt import LocalWhisper

RATE = 24_000
FRAME = int(0.02 * RATE)


def frame_db(x: np.ndarray) -> np.ndarray:
    n = len(x) // FRAME
    return 20 * np.log10(np.sqrt((x[: n * FRAME].reshape(n, FRAME) ** 2).mean(axis=1)) + 1e-9)


def analyze(x: np.ndarray) -> dict:
    db = frame_db(x)
    noise, speech = float(np.percentile(db, 10)), float(np.percentile(db, 90))
    return {
        "seconds": len(x) / RATE,
        "peak": float(np.abs(x).max()),
        "clipping_pct": float((np.abs(x) > 0.99).mean() * 100),
        "snr_db": speech - noise,  # diferencia entre lo que suena fuerte (voz) y el piso de ruido
    }


def best_window(x: np.ndarray, seconds: float) -> np.ndarray:
    """Si el audio es más largo que `seconds`, elige la ventana con más voz, empezando justo después de una pausa
    y terminando en otra, para no cortar palabras."""
    size = int(seconds * RATE)
    if len(x) <= size:
        return x
    db = frame_db(x)
    voiced = db > (np.percentile(db, 10) + 12)
    quiet = ~voiced
    runs, start = [], None
    for i, q in enumerate(quiet):  # centros de las pausas de al menos 200 ms
        if q and start is None:
            start = i
        elif not q and start is not None:
            if i - start >= 10:
                runs.append((start + i) // 2)
            start = None
    cuts = [0] + [r * FRAME for r in runs]
    best, best_score = (0, size), -1.0
    for s in cuts:
        e = min(len(x), s + size)
        if e - s < size * 0.6:
            continue
        end_cuts = [r * FRAME for r in runs if s + size * 0.6 <= r * FRAME <= e]
        e = end_cuts[-1] if end_cuts else e
        score = float(voiced[s // FRAME : e // FRAME].mean()) * (e - s)
        if score > best_score:
            best, best_score = (s, e), score
    return x[best[0] : best[1]]


def verdict(a: dict) -> list[str]:
    msgs = []
    if a["seconds"] < 5:
        msgs.append(f"⚠️  Solo hay {a['seconds']:.1f} s de voz: con menos de 5 s el clon sale peor. Usa 10-12 s.")
    if a["clipping_pct"] > 0.5:
        msgs.append(f"⚠️  El audio está saturado ({a['clipping_pct']:.1f}% de muestras al máximo): se oirá 'roto'. Regrábalo más bajo.")
    if a["snr_db"] < 25:
        msgs.append(f"⚠️  Mucho ruido de fondo (relación voz/ruido ≈ {a['snr_db']:.0f} dB; lo ideal es > 30). El clon imitará también el ruido.")
    return msgs or ["✅ Buena calidad para clonar."]


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio")
    ap.add_argument("speaker", choices=sorted(PERSONAS))
    ap.add_argument("--seconds", type=float, default=12.0, help="duración máxima de la referencia (por defecto 12)")
    ap.add_argument("--no-transcribe", action="store_true", help="no transcribir; escribe tú voices/<speaker>.txt")
    args = ap.parse_args()

    settings = Settings()
    x = trim_silence(load_audio(args.audio, RATE), RATE)
    before = analyze(x)
    x = normalize_loudness(best_window(x, args.seconds))
    after = analyze(x)
    print(f"Entrada : {before['seconds']:.1f} s (sin silencios)   →   referencia: {after['seconds']:.1f} s")
    for m in verdict(before):
        print(m)

    settings.voices_dir.mkdir(parents=True, exist_ok=True)
    wav_path = settings.voices_dir / f"{args.speaker}.wav"
    wav_path.write_bytes(to_wav_bytes(x, RATE))
    for old in settings.voices_dir.glob(f"{args.speaker}.*"):  # evitar que quede otro formato con prioridad
        if old.suffix not in (".wav", ".txt"):
            old.unlink()
    print(f"Guardada: {wav_path}")

    txt_path = wav_path.with_suffix(".txt")
    if args.no_transcribe:
        print(f"Escribe ahora en {txt_path} lo que dice el audio, palabra por palabra.")
        return 0
    print("Transcribiendo con Whisper…")
    text = await LocalWhisper(settings).transcribe(to_wav_bytes(x, RATE))
    if not text:
        print("❌ No se entendió ninguna voz en el audio. Revisa el archivo.")
        return 1
    txt_path.write_text(text, encoding="utf-8")
    print(f"Guardada: {txt_path}\n\n  «{text}»\n\n👉 Léela mientras oyes el audio y corrige {txt_path.name} si Whisper se equivocó")
    print("   (un nombre propio o una cifra mal escritos empeoran el clon).")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
