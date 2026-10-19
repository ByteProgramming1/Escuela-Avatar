"""Mide si la clonación de voz es EFICIENTE en tu máquina: velocidad, latencia al primer audio y memoria.

    .venv/bin/python -m scripts.check_clone [--demo-voices] [--model REPO]

Usa las voces de voices/ (o voces de prueba con --demo-voices). Escribe los resultados en static/check_clone_*.mp3
para que los escuches."""
import argparse
import asyncio
import sys
import tempfile
import time
from pathlib import Path

from app.clone_tts import LocalClone
from app.config import Settings
from app.personas import PERSONAS
from app.stt import LocalWhisper

from ._util import demo_voice, footprint_mb

SENTENCES = [
    "El Encuentro de Padres es el veinticuatro de octubre.",
    "La matrícula depende de los ingresos familiares y de la pensión del colegio, y va desde alrededor de ocho millones hasta casi diecisiete millones de pesos.",
    "Nuestra Escuela cuenta con dieciséis carreras profesionales, entre ellas Ingeniería de Inteligencia Artificial, que es pionera en Colombia, y Negocios Digitales con énfasis en Ciencia de Datos.",
]
DEMO = {"rectora": ("es-CO-SalomeNeural", "Buenos días a todos y bienvenidos a la Escuela Colombiana de Ingeniería Julio Garavito. Es un honor recibirlos hoy en este encuentro."),
        "oswaldo": ("es-CO-GonzaloNeural", "Buenos días a todos y bienvenidos a la Escuela Colombiana de Ingeniería Julio Garavito. Es un honor recibirlos hoy en este encuentro.")}
LIMITS = {"rtf": 0.8, "first_chunk": 1.0, "memory_gb": 5.0}  # por debajo de esto, la voz se oye fluida y cabe con Unity abierto


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo-voices", action="store_true", help="usa voces sintéticas de prueba en vez de voices/")
    ap.add_argument("--model", help="repositorio del modelo (por defecto, el de CLONE_MODEL)")
    args = ap.parse_args()

    settings = Settings()
    if args.model:
        settings.clone_model = args.model
    if args.demo_voices:
        settings.voices_dir = Path(tempfile.mkdtemp(prefix="voces_demo_"))
        for sp, (voice, text) in DEMO.items():
            await demo_voice(settings.voices_dir / f"{sp}.mp3", voice, text)
            (settings.voices_dir / f"{sp}.txt").write_text(text, encoding="utf-8")
        print(f"Voces de prueba (sintéticas) en {settings.voices_dir}")

    clone = LocalClone(settings, LocalWhisper(settings).transcribe)
    speakers = [sp for sp in PERSONAS if clone.available(sp)]
    if not speakers:
        print(f"❌ No hay clonación disponible: {'esta máquina no es un Mac con Apple Silicon o falta mlx-audio' if not clone.supported_platform() else f'pon voices/rectora.wav y voices/oswaldo.wav (ver voices/README.md) o usa --demo-voices'}")
        return 1

    print(f"Modelo  : {settings.clone_model}\nVoces   : {', '.join(speakers)}\n")
    t = time.time(); await clone.warm(); print(f"Carga + calentamiento: {time.time() - t:.1f} s   (memoria {footprint_mb() / 1024:.2f} GB)\n")

    settings.static_dir.mkdir(exist_ok=True)
    worst = {"rtf": 0.0, "first_chunk": 0.0}
    print(f"{'voz':8} {'frase':>5} {'audio':>7} {'1er trozo':>10} {'total':>7} {'RTF':>6}")
    for sp in speakers:
        for i, text in enumerate(SENTENCES):
            t0 = time.perf_counter(); first, data = None, bytearray()
            async for chunk in clone.synthesize_stream(text, sp):
                first = first or time.perf_counter() - t0
                data += chunk
            total = time.perf_counter() - t0
            audio = len(data) * 8 / 48_000
            (settings.static_dir / f"check_clone_{sp}_{i}.mp3").write_bytes(bytes(data))
            rtf = total / audio
            worst["rtf"], worst["first_chunk"] = max(worst["rtf"], rtf), max(worst["first_chunk"], first)
            print(f"{sp:8} {i + 1:>5} {audio:6.1f}s {first:9.2f}s {total:6.1f}s {rtf:6.2f}")

    mem = footprint_mb() / 1024
    print(f"\nMemoria del proceso: {mem:.2f} GB")
    checks = [
        (f"velocidad   RTF máx {worst['rtf']:.2f}  (< {LIMITS['rtf']}: genera más rápido que el tiempo real)", worst["rtf"] < LIMITS["rtf"]),
        (f"latencia    1er trozo máx {worst['first_chunk']:.2f} s  (< {LIMITS['first_chunk']} s)", worst["first_chunk"] < LIMITS["first_chunk"]),
        (f"memoria     {mem:.2f} GB  (< {LIMITS['memory_gb']} GB para convivir con Unity y el navegador)", mem < LIMITS["memory_gb"]),
    ]
    for label, ok in checks:
        print(("✅ " if ok else "⚠️  ") + label)
    print("\nEscucha static/check_clone_*.mp3" + (" (ojo: con --demo-voices la referencia es sintética)" if args.demo_voices else ""))
    return 0 if all(ok for _, ok in checks) else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
