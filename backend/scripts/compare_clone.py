"""Compara qué modelo clona mejor tu voz: Qwen3-TTS (el actual, `clone`) contra Fish Audio S2 Pro (`fish`).

    .venv/bin/python -m scripts.compare_clone                       # los dos, con las voces de voices/
    .venv/bin/python -m scripts.compare_clone --providers fish      # solo uno
    .venv/bin/python -m scripts.compare_clone --quick               # 2 frases y un personaje

Usa las MISMAS frases y la MISMA referencia (voices/<personaje>.wav + .txt) con cada modelo, uno detrás de otro (nunca
dos a la vez: Fish de 8 bits ocupa ~8 GB, así que CIERRA el servidor y Unity antes, o irás a swap).

Mide por modelo: velocidad (tiempo al primer audio, RTF), memoria, si se entiende (Whisper lee lo que dijo) y el tono
medio frente a la referencia. NO mide el parecido del timbre (no hay un indicador fiable sin un modelo de verificación de
hablante) ni da veredicto: quién suena más parecido solo lo decide el oído. Por eso escribe `static/compare/index.html`: la referencia y, para cada
frase, dos reproductores A/B en orden aleatorio (a ciegas); el botón «Revelar» dice qué modelo era cuál."""
import argparse
import asyncio
import gc
import json
import random
import statistics
import sys
import time
from html import escape
from pathlib import Path

import numpy as np

from app.audio import load_audio, to_wav_bytes
from app.clone_tts import LocalClone
from app.config import Settings
from app.fish_tts import FishSpeech
from app.personas import PERSONAS
from app.stt import LocalWhisper

from ._util import footprint_mb
from .e2e_voice import f0_median, word_error_rate

PHRASES = [
    "Buenos días, bienvenidos al Encuentro de Padres de la Escuela Colombiana de Ingeniería.",
    "El Encuentro de Padres es el veinticuatro de octubre, de siete de la mañana a doce del mediodía.",
    "La matrícula depende de los ingresos familiares y de la pensión del colegio, y va desde alrededor de ocho millones hasta casi diecisiete millones de pesos por semestre.",
    "¿Qué carrera es la mejor para mi hijo? Con muchísimo gusto se lo explico, y además pueden visitar los laboratorios hoy mismo.",
]
PROVIDERS = {"clone": ("Qwen3-TTS", LocalClone), "fish": ("Fish Audio S2", FishSpeech)}
RATE = 24_000


async def run_provider(key: str, args, settings: Settings, whisper: LocalWhisper, out: Path, speakers: list[str], phrases: list[str]) -> dict:
    label, cls = PROVIDERS[key]
    provider = cls(settings, whisper.transcribe)
    if not provider.supported_platform():
        print(f"❌ {label}: hace falta un Mac con Apple Silicon y mlx-audio")
        return {}
    speakers = [s for s in speakers if provider.available(s)]
    if not speakers:
        print(f"❌ {label}: no hay referencia en {settings.voices_dir}/<personaje>.wav")
        return {}

    print(f"\n━━ {label} ━━")
    t = time.perf_counter()
    await provider.warm()  # carga el modelo y hace una frase de prueba por personaje (descarga el modelo la primera vez)
    load = time.perf_counter() - t
    print(f"   carga + calentamiento: {load:.1f} s · memoria {footprint_mb() / 1024:.1f} GB")

    results: dict = {"label": label, "load_s": load, "clips": []}
    for speaker in speakers:
        ref_path = provider.reference_file(speaker)
        ref_pcm = load_audio(ref_path, RATE)
        f0_ref = f0_median(ref_pcm, RATE)
        for i, text in enumerate(phrases):
            started = time.perf_counter()
            first, data = None, bytearray()
            async for chunk in provider.synthesize_stream(text, speaker):
                first = first or time.perf_counter() - started
                data += chunk
            total = time.perf_counter() - started
            path = out / f"{key}_{speaker}_{i + 1}.mp3"
            path.write_bytes(bytes(data))
            pcm = load_audio(path, RATE)
            seconds = len(pcm) / RATE
            heard = await whisper.transcribe(to_wav_bytes(load_audio(path, 16_000), 16_000))
            clip = {
                "speaker": speaker, "n": i + 1, "file": path.name, "first_s": first or 0.0, "total_s": total, "audio_s": seconds,
                "rtf": total / max(seconds, 0.01), "wer": word_error_rate(text, heard),
                "f0_err": abs(f0_median(pcm, RATE) - f0_ref) / f0_ref if f0_ref else float("nan"),
                "heard": heard,
            }
            results["clips"].append(clip)
            print(f"   {speaker:8} #{i + 1}: {seconds:5.1f} s de audio · 1er trozo {clip['first_s']:.2f} s · RTF {clip['rtf']:.2f} · "
                  f"error {clip['wer'] * 100:3.0f}% · tono ±{clip['f0_err'] * 100:3.0f}%")
    results["peak_gb"] = footprint_mb() / 1024
    print(f"   memoria máxima del proceso: {results['peak_gb']:.1f} GB")

    # Liberar el modelo antes de cargar el siguiente (en 16 GB no caben los dos a la vez)
    provider._pool.shutdown(wait=True)
    del provider
    gc.collect()
    try:
        import mlx.core as mx

        mx.clear_cache()
    except Exception:
        pass
    return results


def summary(all_results: dict) -> None:
    print("\n━━ Resumen (medias) ━━")
    print(f"{'modelo':16} {'carga':>7} {'1er audio':>10} {'RTF':>6} {'memoria':>8} {'error':>7} {'tono':>7}")
    for r in all_results.values():
        c = r["clips"]
        mean = lambda k: statistics.mean(x[k] for x in c)  # noqa: E731
        print(f"{r['label']:16} {r['load_s']:6.1f}s {mean('first_s'):9.2f}s {mean('rtf'):6.2f} {r['peak_gb']:7.1f}G {mean('wer') * 100:6.0f}% ±{mean('f0_err') * 100:5.0f}%")
    print("\nLímites para usarlo en vivo con Unity abierto: RTF < 0,8, primer audio < 1 s, memoria < 5 GB (ver check_clone).")
    print("error = palabras que Whisper no reconoce de la frase (menos es mejor) · tono = diferencia del tono medio respecto a la referencia (menos es mejor)")
    print("El parecido del TIMBRE no se mide a propósito: sin un modelo de verificación de hablante no hay un indicador fiable (probé el espectro medio y no separaba ni a la Rectora de Oswaldo).")


def write_page(out: Path, all_results: dict, speakers: list[str], phrases: list[str], seed: int) -> Path:
    rng = random.Random(seed)
    rows, answers = [], {}
    keys = list(all_results)
    for speaker in speakers:
        if not any(c["speaker"] == speaker for r in all_results.values() for c in r["clips"]):
            continue
        rows.append(f"<h2>{escape(PERSONAS[speaker].key.capitalize())}</h2>")
        rows.append(f'<p>Referencia: <audio controls src="ref_{speaker}.wav"></audio></p>')
        for i, text in enumerate(phrases):
            files = {k: next((c["file"] for c in all_results[k]["clips"] if c["speaker"] == speaker and c["n"] == i + 1), None) for k in keys}
            files = {k: f for k, f in files.items() if f}
            if len(files) < 2:
                rows.append(f"<p><b>{i + 1}.</b> {escape(text)}</p>" + "".join(f'<p>{PROVIDERS[k][0]}: <audio controls src="{f}"></audio></p>' for k, f in files.items()))
                continue
            order = list(files)
            rng.shuffle(order)
            ident = f"{speaker}-{i + 1}"
            answers[ident] = {"A": PROVIDERS[order[0]][0], "B": PROVIDERS[order[1]][0]}
            rows.append(
                f"<div class='clip'><p><b>{i + 1}.</b> {escape(text)}</p>"
                f"<p>A <audio controls src='{files[order[0]]}'></audio> &nbsp; B <audio controls src='{files[order[1]]}'></audio></p>"
                f"<p class='ans' id='ans-{ident}'></p></div>"
            )
    html = f"""<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Comparación de voces clonadas</title>
<style>body{{font:16px system-ui;max-width:860px;margin:2rem auto;padding:0 16px}}.clip{{border-top:1px solid #8884;padding:.5rem 0}}button{{font:inherit;padding:.5rem 1rem}}.ans{{color:#c60;font-weight:600}}</style>
<h1>¿Qué voz se parece más a la referencia?</h1>
<p>Escucha primero la referencia y luego A y B de cada frase (el orden es aleatorio). Anota cuál prefieres y pulsa «Revelar».</p>
{''.join(rows)}
<p><button onclick="reveal()">Revelar cuál es cuál</button></p>
<script>const A={json.dumps(answers)};function reveal(){{for(const[k,v]of Object.entries(A)){{const e=document.getElementById('ans-'+k);if(e)e.textContent='A = '+v.A+' · B = '+v.B}}}}</script></html>"""
    page = out / "index.html"
    page.write_text(html, encoding="utf-8")
    return page


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--providers", nargs="+", choices=sorted(PROVIDERS), default=["clone", "fish"])
    ap.add_argument("--speakers", nargs="+", choices=sorted(PERSONAS), default=sorted(PERSONAS))
    ap.add_argument("--quick", action="store_true", help="2 frases y un solo personaje")
    ap.add_argument("--seed", type=int, default=7, help="semilla del orden A/B")
    args = ap.parse_args()

    settings = Settings()
    out = settings.static_dir / "compare"
    out.mkdir(parents=True, exist_ok=True)
    phrases = PHRASES[:2] if args.quick else PHRASES
    speakers = args.speakers[:1] if args.quick else args.speakers
    for speaker in speakers:  # la referencia, para escucharla en la página
        for ext in (".wav", ".mp3", ".m4a", ".flac"):
            ref = settings.voices_dir / f"{speaker}{ext}"
            if ref.exists():
                (out / f"ref_{speaker}.wav").write_bytes(to_wav_bytes(load_audio(ref, RATE), RATE))
                break

    whisper = LocalWhisper(settings)
    await whisper.warm()
    results = {}
    for key in args.providers:
        r = await run_provider(key, args, settings, whisper, out, speakers, phrases)
        if r:
            results[key] = r
    if not results:
        return 1
    summary(results)
    page = write_page(out, results, speakers, phrases, args.seed)
    (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print(f"\n👂 Escucha a ciegas: open {page}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
