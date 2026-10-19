"""Clonación de voz con Fish Audio S2 Pro (MLX), como alternativa a Qwen3-TTS para comparar cuál clona mejor.

Reutiliza todo lo de `LocalClone` (referencia en voices/<speaker>.wav + .txt, un único hilo dedicado para MLX, cola con
prioridad, MP3 incremental de 24 kHz / 48 kbps). Cambia el modelo y dos detalles:
  · Fish trabaja a 44,1 kHz (referencia y salida), así que su audio se remuestrea a 24 kHz con un remuestreador CON ESTADO
    (swresample) antes del MP3: remuestrear cada trozo por separado dejaría un clic en cada unión;
  · no tiene `lang_code`: detecta el idioma del texto."""
import logging
import time

import av
import numpy as np

from .clone_tts import SAMPLE_RATE, LocalClone
from .mp3 import Mp3Stream

log = logging.getLogger("eci.fish")


class FishSpeech(LocalClone):
    name = "fish"
    ref_rate = 44_100  # config.sample_rate de S2 Pro; se comprueba al cargar el modelo

    def ref_max_seconds(self) -> float:
        return self._s.fish_ref_max_seconds

    def signature(self, speaker: str) -> str:
        ref = self.reference_file(speaker)
        stamp = f"{ref.stat().st_size}-{ref.stat().st_mtime_ns}" if ref else "none"
        return f"fish:{self._s.fish_model}:t{self._s.fish_temperature}:{stamp}"

    def _ensure_model(self):
        if self._model is None:
            from mlx_audio.tts.utils import load_model

            t0 = time.perf_counter()
            log.info("Cargando Fish Audio S2 %s (la primera vez se descarga: ~7 GB)…", self._s.fish_model)
            self._model = load_model(self._s.fish_model)
            rate = int(self._model.sample_rate)
            if rate != self.ref_rate:
                raise RuntimeError(f"Fish trabaja a {rate} Hz y la referencia se prepara a {self.ref_rate} Hz: ajusta FishSpeech.ref_rate")
            log.info("Fish Audio S2 listo en %.1fs", time.perf_counter() - t0)
        return self._model

    @staticmethod
    def _frames(resampler: "av.AudioResampler", pcm: np.ndarray | None, rate: int) -> np.ndarray:
        """Pasa un trozo a 24 kHz conservando el estado del filtro entre trozos (`pcm=None` = vaciar lo pendiente)."""
        if pcm is None:
            frames = resampler.resample(None)
        else:
            frame = av.AudioFrame.from_ndarray(pcm[None, :], format="flt", layout="mono")
            frame.sample_rate = rate
            frames = resampler.resample(frame)
        out = [f.to_ndarray().reshape(-1) for f in frames]
        return np.concatenate(out).astype(np.float32) if out else np.zeros(0, np.float32)

    def _generate(self, text: str, ref_audio, ref_text: str, emit, cancel) -> None:
        try:
            import mlx.core as mx

            model = self._ensure_model()
            rate = int(model.sample_rate)
            encoder = Mp3Stream(SAMPLE_RATE)
            resampler = av.AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)
            for result in model.generate(
                text=text,
                ref_audio=mx.array(ref_audio),
                ref_text=ref_text,
                stream=True,
                streaming_interval=self._s.fish_stream_interval,
                temperature=self._s.fish_temperature,
                verbose=False,
            ):
                if cancel.is_set():
                    return
                pcm = np.array(result.audio).reshape(-1).astype(np.float32)
                if pcm.size == 0:  # el último trozo puede venir vacío
                    continue
                data = encoder.feed(self._frames(resampler, pcm, rate))
                if data:
                    emit(data)
            rest = self._frames(resampler, None, rate)
            data = encoder.feed(rest) if rest.size else b""
            if data := data + encoder.finish():
                emit(data)
            emit(None)
        except Exception as e:
            emit(e)
