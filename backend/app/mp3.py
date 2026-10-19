import io

import av
import numpy as np

MP3_BYTES_PER_SECOND = 48_000 // 8  # CBR de 48 kbps: los bytes de un MP3 de este servidor se convierten en segundos de audio


class Mp3Stream:
    """Codificador MP3 incremental: va recibiendo audio PCM (float mono) y devuelve los bytes MP3
    que ya se pueden enviar. Sin cabeceras ID3/Xing para que varios MP3 se puedan concatenar, y con
    el mismo formato que edge-tts y ElevenLabs (24 kHz, 48 kbps, mono)."""

    def __init__(self, rate: int = 24_000, bitrate: int = 48_000):
        self._buf = io.BytesIO()
        self._container = av.open(self._buf, "w", format="mp3", options={"write_xing": "0", "id3v2_version": "0"})
        self._stream = self._container.add_stream("mp3", rate=rate, layout="mono")
        self._stream.bit_rate = bitrate
        self._rate, self._pts, self._sent = rate, 0, 0

    def _drain(self) -> bytes:
        data = self._buf.getvalue()
        out, self._sent = data[self._sent :], len(data)
        return out

    def feed(self, pcm: np.ndarray) -> bytes:
        samples = (np.clip(pcm, -1.0, 1.0) * 32767).astype(np.int16)[None, :]
        frame = av.AudioFrame.from_ndarray(samples, format="s16", layout="mono")
        frame.sample_rate, frame.pts = self._rate, self._pts
        self._pts += samples.shape[1]
        for packet in self._stream.encode(frame):
            self._container.mux(packet)
        return self._drain()

    def finish(self) -> bytes:
        for packet in self._stream.encode(None):
            self._container.mux(packet)
        self._container.close()
        return self._drain()
