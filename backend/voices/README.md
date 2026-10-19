# Voces de referencia (para clonar)

Aquí va **un audio de cada personaje**, con el nombre del `speaker` que usa Unity:

```
voices/rectora.wav      ← voz de la Rectora
voices/oswaldo.wav      ← voz de Oswaldo
voices/rectora.txt      ← lo que dice el audio, palabra por palabra (opcional: se genera sola con Whisper)
voices/oswaldo.txt
```

Lo más fácil es dejar que el script lo prepare por ti (acepta wav, mp3, m4a, mp4, mov…):

```bash
.venv/bin/python -m scripts.prepare_voice RUTA/DEL/AUDIO_RECTORA.m4a rectora
.venv/bin/python -m scripts.prepare_voice RUTA/DEL/AUDIO_OSWALDO.m4a oswaldo
```

Qué audio sirve (la calidad del clon depende casi por completo de esto):

- **10 a 12 segundos** de una sola persona hablando con naturalidad (menos de 5 s clona peor; más de 15 s no mejora).
- **Sin música, sin ruido de fondo, sin eco** y sin otras voces. Un micrófono cercano en una habitación silenciosa.
- **Volumen normal, sin saturar** (que no suene "roto").
- **Español, con el acento y el estilo con que quieres que hable** (el clon imita también el ritmo y la emoción).
- Frases completas, sin cortes a mitad de palabra.

Estos archivos son voces de personas reales: **no se versionan en git** (están en `.gitignore`) y solo deben
usarse con el consentimiento de quien habla.
