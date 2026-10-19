import os
import struct
from pathlib import Path

import numpy as np

WHISPER_RATE = 16_000


def decode_wav(wav: bytes) -> tuple[np.ndarray, int]:
    """WAV PCM → (muestras float32 mono, frecuencia). Parser propio y tolerante: el WavUtility de
    Unity escribe cabeceras estándar de 16 bits, y así no dependemos de PyAV para decodificar."""
    if wav[:4] != b"RIFF" or wav[8:12] != b"WAVE":
        raise ValueError("No es un WAV")
    pos, fmt, data = 12, None, None
    while pos + 8 <= len(wav):
        cid, size = wav[pos : pos + 4], struct.unpack_from("<I", wav, pos + 4)[0]
        body = pos + 8
        if cid == b"fmt ":
            tag, channels, rate, _, _, bits = struct.unpack_from("<HHIIHH", wav, body)
            fmt = (tag, channels, rate, bits)
        elif cid == b"data":
            end = body + size if 0 < size <= len(wav) - body else len(wav)  # tamaño roto → hasta el final
            data = wav[body:end]
            break
        pos = body + size + (size & 1)
    if fmt is None or data is None:
        raise ValueError("WAV sin fmt/data")

    tag, channels, rate, bits = fmt
    if bits == 16:
        x = np.frombuffer(data[: len(data) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0
    elif bits == 32 and tag == 3:
        x = np.frombuffer(data[: len(data) // 4 * 4], dtype="<f4").astype(np.float32)
    elif bits == 8:
        x = (np.frombuffer(data, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise ValueError(f"WAV no soportado (formato {tag}, {bits} bits)")
    if channels > 1:
        x = x[: len(x) // channels * channels].reshape(-1, channels).mean(axis=1)
    return x, rate


def resample(x: np.ndarray, rate: int, target: int = WHISPER_RATE) -> np.ndarray:
    """Remuestreo con filtro paso-bajo (ventana sinc) para no meter aliasing al bajar de 44,1 kHz."""
    if rate == target or len(x) == 0:
        return x
    if rate > target:
        fc = 0.45 * target / rate  # frecuencia de corte normalizada
        t = np.arange(127) - 63
        h = np.sinc(2 * fc * t) * np.hamming(127)
        x = np.convolve(x, h / h.sum(), mode="same")
    n_out = int(len(x) * target / rate)
    return np.interp(np.arange(n_out) * rate / target, np.arange(len(x)), x).astype(np.float32)


def wav_to_whisper_input(wav: bytes) -> np.ndarray:
    x, rate = decode_wav(wav)
    return resample(x, rate)


def load_audio(path, rate: int = 24_000) -> np.ndarray:
    """Cualquier formato de audio o video (wav, mp3, m4a, flac, ogg, mp4…) → float32 mono a `rate` Hz.
    `path` puede ser una ruta o los bytes del archivo."""
    import io

    import av

    out: list[np.ndarray] = []
    source = io.BytesIO(path) if isinstance(path, (bytes, bytearray)) else str(path)
    with av.open(source) as container:
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="flt", layout="mono", rate=rate)
        for frame in container.decode(stream):
            out += [f.to_ndarray().reshape(-1) for f in resampler.resample(frame)]
        out += [f.to_ndarray().reshape(-1) for f in resampler.resample(None)]
    if not out:
        raise ValueError(f"{path}: no se pudo leer audio")
    return np.concatenate(out).astype(np.float32)


def trim_silence(x: np.ndarray, rate: int, threshold_db: float = -45.0, pad: float = 0.15) -> np.ndarray:
    """Recorta el silencio al principio y al final (deja un margen de `pad` segundos)."""
    win = max(1, int(0.02 * rate))
    n = len(x) // win
    if n == 0:
        return x
    db = 20 * np.log10(np.sqrt((x[: n * win].reshape(n, win) ** 2).mean(axis=1)) + 1e-9)
    loud = np.flatnonzero(db > threshold_db)
    if loud.size == 0:
        return x
    start = max(0, int(loud[0] * win - pad * rate))
    end = min(len(x), int((loud[-1] + 1) * win + pad * rate))
    return x[start:end]


def normalize_loudness(x: np.ndarray, target_rms: float = 0.1, peak: float = 0.95) -> np.ndarray:
    """Quita el DC, iguala el volumen (RMS) y evita saturar."""
    x = x - x.mean()
    rms = float(np.sqrt(np.mean(x**2))) + 1e-9
    x = x * (target_rms / rms)
    top = float(np.abs(x).max())
    return (x * (peak / top) if top > peak else x).astype(np.float32)


def to_wav_bytes(x: np.ndarray, rate: int) -> bytes:
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def write_atomic(path: Path, data: bytes) -> None:
    """Escribe en un temporal y renombra: Unity nunca descarga un MP3 a medio escribir."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
