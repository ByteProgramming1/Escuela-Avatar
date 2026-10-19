"""Prueba extremo a extremo: VOZ de una pregunta → texto → respuesta → VOZ CLONADA.

    .venv/bin/python -m scripts.e2e_voice [--speaker rectora|oswaldo] [--audio pregunta.wav | --question "texto"] [--demo-voices]
    .venv/bin/python -m scripts.e2e_voice --url http://localhost:5000      # contra el servidor ya arrancado, como Unity

Recorre el mismo código que usa Unity (`/audio/stream`): Whisper/Deepgram, LLM, clonación y MP3 en streaming.
Sin clave de LLM usa una respuesta simulada (se avisa); con GEMINI_API_KEY o ANTHROPIC_API_KEY usa el LLM real.

Comprueba: que lo que se oye es lo que decía el texto, que el timbre se parece a la referencia, cuánto tarda en
sonar el primer audio, si habría cortes al reproducir en streaming, y cuánta memoria usa."""
import argparse
import asyncio
import sys
import tempfile
import time
from pathlib import Path

import httpx
import numpy as np

from app.audio import load_audio, to_wav_bytes
from app.config import Settings
from app.fallback import LLMChain
from app.main import build_assistant
from app.personas import PERSONAS
from app.stt import LocalWhisper

from ._util import demo_voice, footprint_mb

PREBUFFER_BYTES = 7_000  # igual que VoiceAssistant.streamPrebufferBytes en Unity
MP3_BYTES_PER_SECOND = 48_000 / 8
DEMO_REFERENCE = "Buenos días a todos y bienvenidos a la Escuela Colombiana de Ingeniería Julio Garavito. Es un honor recibirlos hoy en este encuentro."
SIMULATED = ("La matrícula depende de los ingresos familiares y de la pensión del colegio. Para las ingenierías va desde alrededor de ocho "
             "millones hasta casi diecisiete millones de pesos por semestre. Además existen becas, descuentos por hermanos y crédito directo "
             "de la Escuela. En la feria financiera de hoy pueden resolver todas sus dudas con la Oficina de Apoyo Financiero.")


class SimulatedLLM:
    """Hace de LLM cuando no hay claves: suelta la respuesta al ritmo de un modelo real (~60 palabras/s... ~25 por s)."""

    name = "simulado"

    def available(self): return True
    def signature(self): return "simulado"
    async def prime(self): pass

    async def stream_text(self, speaker, question, history):
        await asyncio.sleep(0.45)  # tiempo hasta el primer token
        words = SIMULATED.split(" ")
        for i in range(0, len(words), 3):
            yield " ".join(words[i : i + 3]) + " "
            await asyncio.sleep(0.12)


def f0_median(x: np.ndarray, sr: int) -> float:
    n, hop = int(0.04 * sr), int(0.02 * sr)
    lo, hi = int(sr / 400), int(sr / 70)
    gate = 0.1 * np.sqrt(np.mean(x**2)) + 1e-6
    vals = []
    for s in range(0, len(x) - n, hop):
        f = x[s : s + n] - x[s : s + n].mean()
        if np.sqrt(np.mean(f**2)) < gate:
            continue
        ac = np.correlate(f, f, "full")[n - 1 :]
        ac /= ac[0] + 1e-9
        k = lo + int(np.argmax(ac[lo:hi]))
        if ac[k] > 0.45:
            vals.append(sr / k)
    return float(np.median(vals)) if vals else float("nan")


NUMBER_WORDS = set(
    "cero un uno una dos tres cuatro cinco seis siete ocho nueve diez once doce trece catorce quince dieciseis diecisiete dieciocho "
    "diecinueve veinte veintiun veintiuno veintidos veintitres veinticuatro veinticinco veintiseis veintisiete veintiocho veintinueve "
    "treinta cuarenta cincuenta sesenta setenta ochenta noventa cien ciento doscientos trescientos cuatrocientos quinientos seiscientos "
    "setecientos ochocientos novecientos mil millon millones primero primera segundo tercero".split()
)


def word_error_rate(reference: str, heard: str) -> float:
    """Error de palabras entre el texto del LLM y lo que Whisper oye en el audio. Se excluyen las cifras: el LLM las
    escribe con letras ('dieciséis millones') y Whisper con dígitos ('16.782.500'), y eso no es un error de la voz."""
    import re
    import unicodedata

    def norm(s: str) -> list[str]:
        s = "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c))
        return re.sub(r"[^a-z0-9 ]", " ", s).split()

    r = [w for w in norm(reference) if w not in NUMBER_WORDS]
    h = [w for w in norm(heard) if not any(c.isdigit() for c in w)]
    d = np.zeros((len(r) + 1, len(h) + 1), int)
    d[:, 0], d[0, :] = range(len(r) + 1), range(len(h) + 1)
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + (r[i - 1] != h[j - 1]))
    return d[-1, -1] / max(1, len(r))


def playback_gaps(arrivals: list[tuple[float, int]]) -> tuple[int, float]:
    """Simula a Unity: empieza a sonar al juntar PREBUFFER_BYTES y consume el audio en tiempo real.
    Devuelve (cuántas veces se queda sin audio, segundos de silencio acumulados, margen mínimo en segundos)."""
    got, started, buffer_end, gaps, silence, slack = 0, None, 0.0, 0, 0.0, float("inf")
    for t, size in arrivals:
        got += size
        dur = size / MP3_BYTES_PER_SECOND
        if started is None:
            buffer_end = max(buffer_end, t) + dur
            if got >= PREBUFFER_BYTES:
                started = t
                buffer_end = t + got / MP3_BYTES_PER_SECOND
        elif t > buffer_end:
            gaps, silence, slack = gaps + 1, silence + (t - buffer_end), 0.0
            buffer_end = t + dur
        else:
            slack = min(slack, buffer_end - t)  # cuánto audio ya descargado quedaba por sonar al llegar este trozo
            buffer_end += dur
    return gaps, silence, slack


def latency_check(tm: dict, filler_start: float) -> tuple[str, bool]:
    """Con muletillas el primer sonido debe llegar en el segundo configurado; sin ellas, en menos de 4 s."""
    first = tm["first_audio_total"]
    if tm.get("fillers"):
        return (f"muletilla  suena a los {first:.1f} s de soltar la tecla (objetivo: {filler_start:.1f} s)", abs(first - filler_start) < 0.6)
    return (f"latencia   suena a los {first:.1f} s de soltar la tecla (objetivo < 4 s)", first < 4.0)


def answer_check(tm: dict) -> tuple[str, bool]:
    answer = tm.get("first_answer_audio_total", tm["first_audio_total"])
    return (f"respuesta  el primer audio de la respuesta real llega a los {answer:.1f} s (objetivo < 6 s)", answer < 6.0)


async def question_wav(args, tmp: Path) -> bytes:
    if args.audio:
        print(f"Pregunta (audio): {args.audio}")
        return to_wav_bytes(load_audio(args.audio, 44_100), 44_100)  # como el WAV de Unity
    mp3 = tmp / "pregunta.mp3"
    await demo_voice(mp3, "es-MX-DaliaNeural", args.question)
    print(f"Pregunta (voz sintética): «{args.question}»")
    return to_wav_bytes(load_audio(mp3, 44_100), 44_100)


async def main_http(args) -> int:
    """Como Unity: sube el WAV a /audio/stream y mide cuándo llega cada trozo de MP3."""
    tmp = Path(tempfile.mkdtemp(prefix="e2e_"))
    wav = await question_wav(args, tmp)
    out_name = f"e2e_http_{args.speaker}.mp3"
    arrivals: list[tuple[float, int]] = []
    data = bytearray()
    async with httpx.AsyncClient(base_url=args.url, timeout=120) as http:
        print("Servidor:", (await http.get("/health")).json()["providers"])
        t0 = time.perf_counter()
        async with http.stream("POST", "/audio/stream", files={"audio": ("input.wav", wav, "audio/wav")},
                               data={"speaker": args.speaker, "response_file": out_name}) as r:
            if r.status_code != 200:
                print(f"❌ HTTP {r.status_code}: {(await r.aread()).decode()[:300]}")
                return 1
            headers_at = time.perf_counter() - t0
            async for chunk in r.aiter_bytes():
                arrivals.append((time.perf_counter() - t0, len(chunk)))
                data += chunk
        total = time.perf_counter() - t0
        saved = (await http.get(f"/static/{out_name}")).content
        report = (await http.get(f"/static/{out_name[:-4]}.json")).json()  # transcripción, respuesta y tiempos que el stream no lleva
    out = Path(tempfile.gettempdir()) / out_name
    out.write_bytes(bytes(data))
    settings = Settings()
    heard = await LocalWhisper(settings).transcribe(to_wav_bytes(load_audio(out, 16_000), 16_000))
    gaps, silence, slack = playback_gaps(arrivals)
    first = arrivals[0][0]
    print(f"\nLo que se oye en el audio: «{heard[:200]}{'…' if len(heard) > 200 else ''}»")
    print(f"Audio: {len(data) / MP3_BYTES_PER_SECOND:.1f} s en {len(arrivals)} trozos → {out}")
    print(f"Tiempos: cabeceras {headers_at:.2f}s | PRIMER AUDIO {first:.2f}s | último trozo {arrivals[-1][0]:.2f}s | total {total:.2f}s")
    tm = report.get("timings", {})
    if tm:
        print("Servidor: " + " | ".join(f"{k} {v}" for k, v in tm.items()))
    if report.get("fillers"):
        print(f"Muletillas ({len(report['fillers'])}): " + " | ".join(f"«{t}»" for t in report["fillers"]))
    checks = [
        ("completo   el archivo guardado en /static es idéntico al stream (respaldo de Unity)", saved == bytes(data)),
        ("contenido  Whisper entiende la respuesta", len(heard.split()) > 5),
        latency_check({**tm, "first_audio_total": first}, Settings().filler_start_seconds),
        *([answer_check(tm)] if "first_answer_audio_total" in tm else []),
        (f"fluidez    {gaps} cortes y {silence:.1f} s de silencio; margen mínimo {slack:.1f} s (colchón de {PREBUFFER_BYTES} bytes)", gaps == 0 and slack > 0.3),
    ]
    print()
    for label, ok in checks:
        print(("✅ " if ok else "⚠️  ") + label)
    return 0 if all(ok for _, ok in checks) else 2


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--speaker", default="rectora", choices=sorted(PERSONAS))
    ap.add_argument("--audio", help="audio de la pregunta (wav, mp3, m4a…); si no, se sintetiza --question")
    ap.add_argument("--question", default="¿Cuánto cuesta la matrícula y qué opciones de financiación hay?")
    ap.add_argument("--demo-voices", action="store_true", help="voces de referencia sintéticas de prueba (si no tienes voices/*.wav)")
    ap.add_argument("--url", help="probar un servidor en marcha por HTTP (POST /audio/stream) en vez de ejecutar el código en este proceso")
    args = ap.parse_args()
    if args.url:
        return await main_http(args)

    settings = Settings(preload_presentation=False)
    tmp = Path(tempfile.mkdtemp(prefix="e2e_"))
    if args.demo_voices:
        settings.voices_dir = tmp / "voices"
        settings.voices_dir.mkdir()
        for sp, voice in {"rectora": "es-CO-SalomeNeural", "oswaldo": "es-CO-GonzaloNeural"}.items():
            await demo_voice(settings.voices_dir / f"{sp}.mp3", voice, DEMO_REFERENCE)
            (settings.voices_dir / f"{sp}.txt").write_text(DEMO_REFERENCE, encoding="utf-8")
        print("⚠️  Voces de referencia SINTÉTICAS de prueba (para validar el flujo; con voces reales el timbre será el de la persona)")

    async with httpx.AsyncClient(timeout=30) as http:
        assistant = build_assistant(settings, http)
        print("Proveedores:", {k: v for k, v in assistant.describe().items()})
        if not assistant.tts.describe(args.speaker).startswith("clone") and "clone" not in assistant.tts.describe(args.speaker):
            print(f"❌ No hay voz clonada para '{args.speaker}'. Pon voices/{args.speaker}.wav (ver voices/README.md) o usa --demo-voices.")
            return 1
        if not assistant.llm.ready():
            assistant.llm = LLMChain([SimulatedLLM()], 60)
            print("⚠️  LLM SIMULADO (no hay GEMINI_API_KEY ni ANTHROPIC_API_KEY): la respuesta es un texto fijo")

        t = time.time(); await assistant.warm_up(); print(f"Calentamiento (cargar modelos): {time.time() - t:.1f} s\n")

        wav = await question_wav(args, tmp)

        report: dict = {}
        arrivals: list[tuple[float, int]] = []
        out_mp3 = settings.static_dir / f"e2e_{args.speaker}.mp3"
        settings.static_dir.mkdir(exist_ok=True)
        t0 = time.perf_counter()
        async for chunk in assistant.answer_audio_stream(wav, args.speaker, out_mp3, report):
            arrivals.append((time.perf_counter() - t0, len(chunk)))
        peak_mem = footprint_mb() / 1024

        # ── Verificación: ¿se oye lo que se escribió, con el timbre de la referencia? ─────────
        whisper = LocalWhisper(settings)
        heard_audio = load_audio(out_mp3, 16_000)
        heard = await whisper.transcribe(to_wav_bytes(heard_audio, 16_000))
        spoken_text = " ".join([*report.get("fillers", []), report["answer"]])  # el audio lleva las muletillas delante
        wer = word_error_rate(spoken_text, heard)
        clone = next(p for p in assistant.tts.providers if p.name == "clone")
        ref_file = clone.reference_file(args.speaker)
        f0_ref = f0_median(load_audio(ref_file, 24_000), 24_000) if ref_file else float("nan")
        f0_out = f0_median(load_audio(out_mp3, 24_000), 24_000)
        audio_s = len(heard_audio) / 16_000
        tm = report["timings"]
        gaps, silence, slack = playback_gaps(arrivals)

    print(f"\nTranscripción de la pregunta (STT): «{report['transcript']}»")
    print(f"Respuesta del LLM              : «{report['answer'][:160]}{'…' if len(report['answer']) > 160 else ''}»")
    print(f"Lo que se oye en el audio      : «{heard[:160]}{'…' if len(heard) > 160 else ''}»")
    print(f"\nAudio: {audio_s:.1f} s en {len(arrivals)} trozos → {out_mp3}")
    print(f"Tiempos: STT {tm['stt']:.2f}s | LLM 1er token {tm['llm_first_token']:.2f}s | LLM completo {tm['llm_total']:.2f}s | "
          f"PRIMER SONIDO {tm['first_audio_total']:.2f}s | PRIMER AUDIO DE LA RESPUESTA {tm.get('first_answer_audio_total', tm['first_audio_total']):.2f}s | total {tm['total']:.2f}s")
    if report.get("fillers"):
        print(f"Muletillas ({len(report['fillers'])}): " + " | ".join(f"«{t}»" for t in report["fillers"]))
    checks = [
        (f"fidelidad  lo que se oye coincide con el texto (error {wer * 100:.0f}% de palabras, sin contar cifras)", wer < 0.15),
        (f"timbre     tono medio {f0_out:.0f} Hz vs {f0_ref:.0f} Hz de la referencia" + (" (indicativo)" if args.demo_voices else ""),
         np.isnan(f0_ref) or abs(f0_out - f0_ref) / f0_ref < 0.15),
        latency_check(tm, settings.filler_start_seconds),
        answer_check(tm),
        (f"fluidez    {gaps} cortes y {silence:.1f} s de silencio en streaming; margen mínimo {slack:.1f} s (simula el colchón de {PREBUFFER_BYTES} bytes de Unity)", gaps == 0 and slack > 0.3),
        (f"memoria    {peak_mem:.2f} GB en total (STT + clon + servidor; objetivo < 6 GB)", peak_mem < 6.0),
    ]
    print()
    for label, ok in checks:
        print(("✅ " if ok else "⚠️  ") + label)
    return 0 if all(ok for _, ok in checks) else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
