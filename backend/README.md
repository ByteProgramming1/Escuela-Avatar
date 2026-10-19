# Backend de voz de la ECI

Convierte la **voz de una pregunta** en una **respuesta hablada con la voz clonada** de la Rectora o de Oswaldo, y se la entrega a Unity mientras todavía se está generando.

```
Unity ──WAV──▶  Voz→texto  ──▶  LLM con el contexto de la ECI  ──▶  Texto→voz (clon)  ──MP3 en streaming──▶ Unity
               (Whisper local)  (Gemini gratis / Claude)           (Qwen3-TTS, local)
```

Todo puede correr **gratis y en local**. Lo único que necesita una clave es el LLM, y hay una gratuita (Gemini).

## Resumen en 5 pasos

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt   # 1. instalar
cp .env.example .env                                                     # 2. pon GEMINI_API_KEY en .env
.venv/bin/python -m scripts.prepare_voice RUTA/DEL/AUDIO_RECTORA.m4a rectora   # 3. voces (ver más abajo)
.venv/bin/python -m scripts.prepare_voice RUTA/DEL/AUDIO_OSWALDO.m4a oswaldo
.venv/bin/uvicorn app.main:app --port 5000                               # 4. arrancar
.venv/bin/python -m scripts.e2e_voice --url http://localhost:5000        # 5. probar de punta a punta
```

## Requisitos

| | |
|---|---|
| Equipo | Cualquiera (macOS, Windows o Linux). La **clonación local** usa MLX y solo funciona con un procesador Apple Silicon; en los demás equipos el resto del sistema funciona igual y se usa la voz genérica de respaldo. Las medidas de este documento son de un Apple M4 de 16 GB. |
| Python | 3.12 – 3.14 (probado con 3.14) |
| Disco | ~4 GB de modelos que se descargan solos la primera vez (Whisper 0,5 GB + clonación 2,3 GB) |
| Internet | Necesario para el LLM (Gemini) y para las voces genéricas de respaldo. Voz→texto y clonación son 100 % locales. |

## 1. Claves (`.env`)

Copia `.env.example` a `.env`. **Solo una clave es indispensable**: la del LLM.

| Clave | Para qué | Costo |
|---|---|---|
| `GEMINI_API_KEY` | LLM (la respuesta). Se crea en <https://aistudio.google.com/apikey> | Gratis (con límite de peticiones por minuto) |
| `ANTHROPIC_API_KEY` | LLM de pago, más capaz. Si está, se usa primero y Gemini queda de respaldo | Pago |
| `DEEPGRAM_API_KEY` | Voz→texto en la nube (más rápido que Whisper local). Opcional | Pago |
| `ELEVENLABS_API_KEY` + `VOICE_ID_RECTORA` / `VOICE_ID_OSWALDO` | Voz clonada en la nube. Opcional: sin ella se usa el clon local | Pago |

Cada etapa es una **cadena con respaldo automático**: se usa lo de pago si hay clave y, si falla (sin saldo, caída, límite), se pasa solo a lo gratuito.

| Etapa | Orden en modo `auto` |
|---|---|
| Voz → texto | Deepgram → **Whisper local** |
| LLM | Claude → **Gemini** |
| Texto → voz | ElevenLabs → **clon local (Qwen3-TTS)** → voz genérica (Salomé / Gonzalo) |

> Si tienes clave de ElevenLabs pero prefieres el clon local, pon `TTS_PROVIDER=clone`. Para forzar cualquier etapa: `STT_PROVIDER`, `LLM_PROVIDER`, `TTS_PROVIDER`.

## 2. ¿Dónde pongo el audio de la voz?

En la carpeta **`backend/voices/`**, un archivo por personaje, con el nombre del `speaker` que usa Unity:

```
backend/voices/rectora.wav     ← voz de la Rectora
backend/voices/oswaldo.wav     ← voz de Oswaldo
backend/voices/rectora.txt     ← lo que dice ese audio (opcional: se genera solo con Whisper)
backend/voices/oswaldo.txt
```

**La forma fácil**: deja tu grabación donde quieras (acepta wav, mp3, m4a, mp4, mov…) y ejecuta:

```bash
.venv/bin/python -m scripts.prepare_voice RUTA/DEL/AUDIO.m4a rectora
.venv/bin/python -m scripts.prepare_voice RUTA/DEL/AUDIO.m4a oswaldo
```

El script la limpia (quita silencios, iguala el volumen), la recorta a la mejor ventana de ≤ 12 s, **te avisa** si tiene poco audio, ruido o saturación, la transcribe con Whisper y deja `voices/<speaker>.wav` y `voices/<speaker>.txt`. **Lee el `.txt` mientras oyes el audio y corrígelo** si Whisper se equivocó (un nombre propio o una cifra mal escritos empeoran el clon).

**Qué audio da un buen clon** (esto pesa más que cualquier ajuste):

- 10 a 12 segundos de **una sola persona** hablando natural (con menos de 5 s sale peor; con más de 15 s no mejora).
- **Sin música, sin ruido de fondo, sin eco, sin otras voces.** Micrófono cerca, habitación silenciosa.
- Volumen normal, **sin saturar**.
- En **español y con el acento y el estilo** con que quieres que hable: el clon copia también el ritmo y el tono.
- Frases completas, sin cortes a mitad de palabra.

> Estos archivos son voces de personas reales. No se suben a git (`.gitignore`) y solo deben usarse **con el consentimiento de quien habla**. En el evento conviene avisar que los avatares usan voz y respuestas generadas por IA.

Mientras no haya `voices/rectora.wav`, la Rectora habla con la voz genérica de mujer (Salomé) y Oswaldo con la de hombre (Gonzalo), así que **el sistema funciona desde el primer momento**. En cuanto pongas el audio y reinicies, esa persona pasa a hablar con su voz clonada.

## 3. Arrancar

```bash
.venv/bin/uvicorn app.main:app --port 5000
```

Lo que debes ver en el log (la primera vez tarda unos minutos por la descarga de modelos):

```
stt            whisper
llm            gemini
tts[rectora]   clone → edge          ← "clone" = usa su voz clonada
tts[oswaldo]   clone → edge
Whisper listo
Modelo de clonación listo
Preguntas pregrabadas listas         ← espera a este mensaje antes de empezar el evento
```

`GET http://localhost:5000/health` muestra en cualquier momento qué proveedores están activos. Las preguntas pregrabadas (teclas 0–9) se generan una sola vez y quedan en disco: la primera vez tardan ~4 min en conjunto (20 audios), después el arranque es inmediato. Si cambias una voz, la base de conocimiento o un modelo, se regeneran solas: al pulsar la tecla suena de inmediato la versión anterior (aunque sea desactualizada o de emergencia) y la nueva se genera en segundo plano para la siguiente vez. Solo si no hay ningún audio en disco la tecla espera a que se genere.

## 4. Conectar Unity

Nada que cambiar si el servidor corre en el mismo equipo que Unity (`serverUrl = http://localhost:5000`). En `VoiceAssistant`:

- `useStreaming` (activado): la respuesta empieza a sonar mientras se genera. Si Unity no puede reproducir el stream, descarga el archivo completo automáticamente.
- `streamPrebufferBytes` (7000 ≈ 1,2 s de audio): si oyes cortes, súbelo; si quieres que empiece antes, bájalo. Las muletillas (ver abajo) lo superan de golpe.
- Tecla **R** = «nueva familia»: llama a `POST /reset` para que la siguiente pregunta no herede la conversación anterior. En la consola de Unity, las líneas «⏱️» dicen a cuántos segundos de soltar la tecla llegó el audio y empezó a sonar.

Los audios de la intro (`IntroSequence`) quedan guardados en `static/`. Si los generaste con la voz genérica y luego pones las voces reales, **borra `static/intro_*.mp3`** (o marca `regenerateAudio`) para que se regeneren.

## 5. Comprobar que todo funciona

Ninguna de estas pruebas necesita clave de pago.

| Comando | Qué comprueba |
|---|---|
| `.venv/bin/python -m pytest -q` | 111 pruebas automáticas (sin red ni claves) |
| Abrir **http://localhost:5000/e2e** en el navegador | **Prueba de punta a punta con tu propia voz**, sin Unity (ver abajo) |
| `.venv/bin/python -m scripts.check_free_stack` | Que Whisper carga y que las voces genéricas suenan y se entienden |
| `.venv/bin/python -m scripts.check_clone` | **Eficiencia de la clonación** en tu equipo: velocidad, latencia y memoria, con un veredicto |
| `.venv/bin/python -m scripts.compare_clone` | Compara Qwen3-TTS con Fish Audio S2 a ciegas (ver 6c) |
| `.venv/bin/python -m scripts.check_fillers` | Genera las **muletillas** con la voz real y mide cuánto dura cada una (deben durar ~4 s) |
| `.venv/bin/python -m scripts.check_stt` | Compara Whisper `base` vs `small` con tus audios de `audios-test/`: velocidad, error y términos de la Escuela reconocidos |
| `.venv/bin/python -m scripts.e2e_voice` | **Prueba de punta a punta**: pregunta hablada → texto → respuesta → voz clonada |
| `.venv/bin/python -m scripts.e2e_voice --url http://localhost:5000` | Lo mismo contra el servidor ya arrancado, **como lo hace Unity** (HTTP real) |

Las pruebas `check_clone` y `e2e_voice` aceptan `--demo-voices` para correr sin tus grabaciones (usan voces sintéticas de referencia) y `--speaker rectora|oswaldo`. `e2e_voice` acepta además `--audio mi_pregunta.m4a` o `--question "…"`.

`e2e_voice` verifica y marca ✅/⚠️: que lo que **se oye** coincide con el texto de la respuesta (lo transcribe de vuelta con Whisper), que el **timbre** se parece al de la referencia, cuánto tarda en sonar el **primer audio**, que no habría **cortes** al reproducir en streaming (simula el colchón de Unity) y cuánta **memoria** usa todo junto.

**La página `/e2e`** (`web/e2e.html`, la sirve el propio servidor) es para probar con tus preguntas y tu voz: eliges quién responde, grabas con el micrófono (**Espacio** graba y envía, **Esc** descarta) o subes un archivo de audio, y ves **lo que entendió el STT**, el texto de la respuesta, la voz sonando en streaming como en Unity (`/audio/stream`; el modo "Completo" usa `/audio`) y los tiempos medidos en el navegador y en el servidor. Marca con un icono verde (correcto) o naranja (aviso) la latencia (primer audio < 4 s) y los cortes (con el mismo colchón que Unity). «Reenviar esta pregunta» repite el mismo audio con otro personaje u otro modo; «Olvidar conversación» llama a `/reset`. Hay que abrirla como `http://localhost:5000/e2e` (el micrófono del navegador solo funciona en `localhost` o HTTPS). Deja sus archivos como `static/web_e2e_<personaje>.mp3` y `.json`, sin pisar los de Unity.

> Estas pruebas miden inteligibilidad, tiempos y tono, **no lo parecida que suena la voz a oídos humanos**. Eso solo se juzga escuchando: abre `static/check_clone_*.mp3` y `static/e2e_*.mp3` con tus voces reales.

## 6. Eficiencia medida (equipo de referencia: Apple M4, 16 GB)

**Por qué Qwen3-TTS y no F5-TTS.** Se probaron los candidatos con las mismas frases en español y la misma referencia. *RTF* = tiempo de generar ÷ duración del audio (menos de 1 = más rápido que hablar; para conversar se necesita bastante menos).

| Modelo | RTF | Memoria | ¿Se entiende? | Veredicto |
|---|---|---|---|---|
| F5-TTS español, PyTorch/MPS (32 pasos) | 2,6 – 4,8 | 4,0 GB | sí | ✗ demasiado lento |
| F5-TTS español, PyTorch/MPS (16 pasos) | 1,3 – 2,6 | 4,0 GB | sí | ✗ sigue más lento que hablar |
| F5-TTS español, MLX (conversión propia) | 2,7 – 4,7 | 2,7 GB | **no** (106 % de error) | ✗ |
| Chatterbox multilingüe, MLX | 1,3 – 1,5 | 5,0 GB | sí | ✗ más lento que hablar |
| **Qwen3-TTS 0,6B 4-bit, streaming** | **0,32 – 0,35** | **2,6 GB** | sí | ✓ opción ligera |
| **Qwen3-TTS 1,7B 4-bit, streaming** | **0,41 – 0,47** | **3,1 GB** | sí | ✓ **por defecto** |

F5-TTS hace ~64 pasadas de un modelo de 336 M parámetros sobre una secuencia larga (referencia + texto): en el equipo de referencia (M4 base) eso no llega al tiempo real. Además su checkpoint en español es **CC-BY-NC** (no comercial). Qwen3-TTS es autoregresivo y emite audio a medida que lo genera, y su licencia es **Apache 2.0**.

El **modo streaming** también importa para la memoria: el mismo modelo usa 2,6 GB en streaming y 9,3 GB si genera el audio de una vez.

**Con el sistema completo** (`scripts.e2e_voice --url …`, Whisper small + Gemini + clon 1,7B, voz masculina y femenina):

| Medida | Resultado |
|---|---|
| Primer audio tras soltar la tecla | **2,9 – 3,6 s** (objetivo < 4 s) |
| Reparto del tiempo | Voz→texto ≈ 1,0 s · primer token del LLM ≈ 0,9–1,9 s · primer audio clonado ≈ 0,6 s |
| Cortes al reproducir en streaming | **0** (margen mínimo de audio ya descargado: 2,4 s) |
| Memoria de todo el proceso | **3,8 – 4,0 GB** |
| Archivo de respaldo en `/static` | idéntico al stream |

Las respuestas largas empiezan a sonar sin esperar a que termine el LLM, y cada frase se genera más rápido de lo que se reproduce.

**Cómo ganar más velocidad si la necesitas:** `WHISPER_MODEL=base` (voz→texto ≈ 2× más rápido, algo menos preciso), `CLONE_MODEL=mlx-community/Qwen3-TTS-12Hz-0.6B-Base-4bit`, o un LLM más rápido. Con Unity abierto la GPU se comparte: genera el audio y renderiza los avatares a la vez, así que prueba con la escena real.

## 6b. Muletillas: que no haya silencio mientras se prepara la respuesta

Entre soltar la tecla y oír la respuesta pasan varios segundos (voz→texto, LLM, primera frase de voz; con Unity abierto la GPU y la CPU se comparten y puede llegar a 9–12 s). Para que el silencio no parezca un fallo, el servidor mete **muletillas habladas** en el mismo stream de audio:

- **Si pasan más de 4 s** sin respuesta (`FILLER_START_SECONDS`, contando desde que llega el audio) suena una muletilla de apertura, aunque el voz→texto aún no haya terminado: no depende de lo que dijiste. Si la respuesta llega antes, no suena ninguna. Y si la primera frase de la respuesta ya lleva menos de 1,5 s en el TTS (`FILLER_IMMINENT_SECONDS`), se espera un poco más: el audio real está por salir y una muletilla de ~4 s lo haría esperar hasta que acabe.
- Cada una dura **~4 s**. Si cuando está por acabar la respuesta todavía no está lista, se encadena otra de «continuación» (máximo 3 seguidas = `FILLER_MAX_CHAIN`, cubren hasta ~16 s). Se entregan con 0,6 s de antelación (`FILLER_MARGIN_SECONDS`), así que no hay huecos entre una y otra.
- Hay **muchas y rotan**: 14–15 de apertura y 10 de continuación **por personaje**, en `fillers.json` (editable: sin datos de la Escuela, sin saludos, sin preguntas). Se sacan de una bolsa barajada: no se repiten hasta agotarla.
- Se generan **una sola vez** con la voz de cada personaje (el clon local, gratis) al arrancar el servidor, antes de las preguntas pregrabadas (~2 min la primera vez), y quedan en `static/filler_*.mp3`. Si cambias un texto o la voz, solo se regenera lo que cambió. `python -m scripts.check_fillers` mide cuánto dura cada una y avisa de las que se salen de 3,5–4,5 s: cada voz tiene su ritmo (la Rectora ≈ 0,45 s por palabra, Oswaldo ≈ 0,33 s), así que se ajusta el largo del texto.
- **La GPU tiene prioridad para lo que se oye en vivo** (`app/priority.py`). El clon genera una frase a la vez; antes la cola era por orden de llegada, así que mientras el servidor regeneraba las preguntas pregrabadas (tras cambiar `knowledge/eci.md` son 20 audios, varios minutos) una pregunta en vivo esperaba detrás: se midieron **26 s** hasta el primer audio de la respuesta. Ahora lo en vivo pasa antes y el trabajo de fondo (precarga, regeneración, muletillas del arranque) no empieza frases nuevas mientras haya una conversación en curso. Con la regeneración corriendo, el mismo audio de prueba llegó a los 4,1 s. Lo que ya se está generando no se interrumpe, así que una pregunta espera, como mucho, a una frase.
- El LLM recibe, delante de cada pregunta y fuera de la caché, un bloque de contexto (hora de Bogotá, quién respondió antes, «ya sonó una muletilla: empieza directo»). Si el LLM falla después de que sonó una muletilla, suena una disculpa en vez de silencio.
- El archivo de respaldo `static/response_*.mp3` incluye las muletillas, igual que el stream. `FILLER_ENABLED=false` las apaga.
- `logs/questions.jsonl` guarda una línea por pregunta (transcripción, respuesta, tiempos). `derived: true` marca las respuestas que mandaron a Admisiones/PBX: son los huecos de `knowledge/eci.md`.

Los tiempos de cada pregunta (log del servidor y `static/<archivo>.json`) traen `first_audio_total` (primer sonido, normalmente la muletilla), `first_answer_audio_total` (primer audio de la respuesta de verdad), `filler_start` y `fillers`.

## 6c. Probar Fish Audio S2 (otro modelo de clonación)

Alternativa a Qwen3-TTS para ver si la voz se parece más a la referencia. **Está implementada y probada con un modelo simulado, pero todavía no se ha medido con el modelo real** (la descarga de 6,7 GB no terminó), así que no hay números de velocidad ni de calidad.

- **Qué es**: Fish Audio S2 Pro (marzo de 2026), ~5 000 M de parámetros; clona con 10–30 s de referencia y entiende español. La versión de 8 bits para MLX es `mlx-community/fish-audio-s2-pro-8bit` (6,7 GB: `model.safetensors` 4,8 GB + `codec.safetensors` 1,9 GB). Hace falta espacio libre en disco para los 6,7 GB del modelo y ~8 GB de memoria cargado.
- **Licencia**: *Fish Audio Research License*: gratis para investigación y uso no comercial; el uso comercial requiere un acuerdo escrito con Fish Audio (business@fish.audio). Revísalo antes de usarlo en un producto.
- **Riesgo de velocidad**: es ~3 veces más grande que Qwen3-TTS 1,7B. En el equipo de referencia (M4 base, ≈ 120 GB/s) leer 4–5 GB de pesos por cada trozo de audio puede dejarlo cerca del tiempo real o por debajo (RTF ≈ 1). Es una estimación, no una medición: `compare_clone` lo dice.

**1) Comparar a ciegas** (cierra antes el servidor y Unity: los dos modelos no caben a la vez junto a ellos en 16 GB):

```
.venv/bin/python -m scripts.compare_clone            # Qwen3-TTS vs Fish, mismas frases y misma referencia
.venv/bin/python -m scripts.compare_clone --quick    # 2 frases y un personaje
# abre static/compare/index.html en el navegador: la referencia y A/B en orden aleatorio; «Revelar» dice cuál es cuál
```

Mide velocidad (primer trozo, RTF), memoria, si se entiende (Whisper) y el tono medio frente a la referencia. **No mide el parecido del timbre** (probé el espectro medio y no distinguía ni a la Rectora de Oswaldo): eso lo decide tu oído con la página A/B.

**2) Usarlo de verdad**: `TTS_PROVIDER=fish` en `.env` (la cadena queda `fish → voz genérica`; el clon Qwen no se carga). Las muletillas y las preguntas pregrabadas se regeneran solas con la voz nueva (cambia la firma). Para no pisar las de Qwen usa otra carpeta: `STATIC_DIR=static_fish .venv/bin/uvicorn app.main:app --port 5000`.

Ajustes: `FISH_MODEL`, `FISH_TEMPERATURE` (0,7; menos = más estable y más parecido a la referencia), `FISH_STREAM_INTERVAL` (0,5 s por trozo) y `FISH_REF_MAX_SECONDS` (20; Qwen usa como máximo 12). Fish prefiere referencias de 10–30 s: la de Oswaldo dura 8,5 s y la de la Rectora 10,9 s; con `prepare_voice --seconds 20` puedes dejar una más larga (Qwen la recorta a 12 s).

## 7. Cómo funciona por dentro

- **Sin RAG vectorial.** Todo `knowledge/*.md` (≈ 5 000 tokens) va en el prompt, con caché en Claude: cero latencia de búsqueda y el modelo ve todo. Para cambiar lo que saben los avatares edita `knowledge/eci.md`.
- **Frase a frase.** El texto del LLM se parte en frases mientras llega; cada una va al TTS enseguida y el audio sale en orden (`app/pipeline.py`). La primera frase puede cortarse en una coma para arrancar antes.
- **Clon local** (`app/clone_tts.py`): Qwen3-TTS sobre MLX, un solo hilo dedicado (MLX lo exige), una frase a la vez en la GPU, MP3 incremental de 24 kHz / 48 kbps (el mismo formato que las voces de respaldo, así un cambio de proveedor no se nota).
- **Respaldo automático** (`app/fallback.py`): un proveedor que falla se salta 2 minutos; un LLM nunca cambia de modelo a mitad de una respuesta. Los audios pregrabados hechos con un respaldo se sirven pero se regeneran cuando vuelve el principal.
- **Endpoints**: `POST /audio/stream` (Unity), `POST /audio`, `POST /presentation` (teclas 0–9), `POST /tts` (intro), `POST /reset`, `GET /health`, `GET /static/…`.

## 8. Ajustes útiles (`.env`)

| Variable | Por defecto | Para qué |
|---|---|---|
| `CLONE_MODEL` | `…Qwen3-TTS-12Hz-1.7B-Base-4bit` | Modelo de clonación (`…0.6B-Base-4bit` = más ligero) |
| `WHISPER_MODEL` | `small` | `medium`/`large-v3` más preciso; `base` solo si el STT es el cuello de botella (comprueba antes con `scripts.check_stt`: con tus audios de prueba falló bastante) |
| `LLM_MODEL` / `LLM_EFFORT` | `claude-opus-5-5` / `low` | Solo si usas Claude |
| `TTS_PROVIDER` / `FISH_MODEL` / `FISH_TEMPERATURE` | `auto` / `mlx-community/fish-audio-s2-pro-8bit` / `0.7` | `fish` = clonar con Fish Audio S2 en vez de Qwen3-TTS (ver 6c) |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Revisa en AI Studio qué modelos tienen capa gratuita |
| `GEMINI_THINKING_LEVEL` | vacío | Medido con `gemini-3.5-flash-lite` (5 preguntas): vacío ≈ `minimal` ≈ 0,85 s al primer token; `low` empeora (≈ 2,6 s). No hace falta tocarlo con este modelo |
| `GEMINI_FALLBACK_MODEL` | vacío | Segundo modelo gratuito si el primero da 429/503 (la cuota gratis es por modelo) |
| `FILLER_ENABLED` / `FILLER_START_SECONDS` / `FILLER_MAX_CHAIN` / `FILLER_IMMINENT_SECONDS` | `true` / `4.0` / `3` / `1.5` | Muletillas habladas mientras se prepara la respuesta (ver 6b) |
| `LLM_RETRIES` / `LLM_RETRY_DELAY` | `2` / `0.6` | Reintentos (espera que se duplica) si el último LLM falla por sobrecarga (503…) antes del primer token |
| `PRESENTATION_REFRESH_SECONDS` | `60` | Mínimo entre dos regeneraciones en segundo plano de una misma pregunta pregrabada |
| `PRELOAD_PRESENTATION` | `true` | Generar al arrancar las preguntas 1–10 |
| `EDGE_VOICE_RECTORA` / `_OSWALDO` | Salomé / Gonzalo (es-CO) | Voces genéricas de respaldo |

## 9. Problemas frecuentes

| Síntoma | Causa y solución |
|---|---|
| `tts[rectora]   edge` en el log (no dice `clone`) | Falta `voices/rectora.wav`, o el equipo no tiene procesador Apple Silicon, o falta `mlx-audio`. Revisa con `scripts.check_clone`. |
| `SIN LLM: pon GEMINI_API_KEY…` | No hay clave de LLM en `backend/.env`. |
| La voz clonada suena distinta o "sucia" | Casi siempre es la referencia: ruido, eco, música o menos de 5 s. Regraba y repite `prepare_voice`; revisa el `.txt`. |
| Se corta el audio en Unity | Sube `streamPrebufferBytes`, o desactiva `useStreaming` para descargar el archivo completo. |
| La primera pregunta tarda mucho | El modelo aún se está descargando/cargando: espera "Modelo de clonación listo" en el log. |
| Respuesta lenta mientras corre Unity (9–12 s) | La GPU y la CPU se comparten. Mira el log: `stt`, `llm_first_token` y `first_answer_audio_total` dicen qué etapa domina, y en la consola de Unity las líneas «⏱️». STT lento (`small` tarda ≈ 1,1–1,2 s por pregunta de 12 s; `base` en `scripts.check_stt` entendió mal tus dos audios de prueba — 57 % de palabras distintas —, así que déjalo como último recurso); LLM lento (con `gemini-3.5-flash-lite` suele tardar ≈ 0,9 s al primer token; si ves más, mira 429/503 y los reintentos en el log); voz lenta → `CLONE_MODEL=…0.6B-Base-4bit` y `CLONE_STREAM_INTERVAL=0.5`. Mientras tanto, las muletillas rellenan el silencio. Si el servidor acaba de regenerar las pregrabadas (cambió `eci.md`), esas pasan a segundo plano y no deberían retrasar las preguntas en vivo; el log del clon muestra `espera Xs` por frase. |
| `429` de Gemini | Límite de la capa gratuita (peticiones por minuto). Espera o pon `ANTHROPIC_API_KEY`. |
| Tras añadir las voces, la intro sigue con voz genérica | Borra `static/intro_*.mp3`. |
| `localhost:5000` da `403 Forbidden` u otro error raro (p. ej. cabecera `Server: AirTunes`) | Otro programa está escuchando en el puerto 5000 y contesta en vez de tu servidor (que escucha solo en `127.0.0.1`, mientras `localhost` puede resolver primero a `::1`). En macOS suele ser el «Receptor de AirPlay». Rápido: abre `http://127.0.0.1:5000/e2e` y pon `serverUrl = http://127.0.0.1:5000` en Unity (en `VoiceAssistant` e `IntroSequence`). Definitivo: cierra ese programa (en macOS: Ajustes del Sistema → General → AirDrop y Handoff → Receptor de AirPlay), o arranca uvicorn en otro puerto y cambia `serverUrl`. |

## 10. Licencias y uso responsable

- **Qwen3-TTS** (clonación): Apache 2.0. **Whisper** (faster-whisper): MIT. **edge-tts**: servicio no oficial de Microsoft, puede cambiar o dejar de funcionar; solo es respaldo.
- No se usa F5-TTS en español porque su checkpoint es CC-BY-NC (no comercial).
- Clonar la voz de una persona real requiere su **consentimiento**. Los avatares se presentan como IA si se les pregunta (está en las reglas del personaje).
