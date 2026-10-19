from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    # ── Claves. Las de pago son opcionales: sin ellas se usan los proveedores gratuitos ──
    anthropic_api_key: str = ""
    deepgram_api_key: str = ""
    elevenlabs_api_key: str = ""
    gemini_api_key: str = ""  # gratis en https://aistudio.google.com/apikey

    # Un VOICE_ID_<NOMBRE> de ElevenLabs por speaker (ver personas.py)
    voice_id_rectora: str = ""
    voice_id_oswaldo: str = ""

    # ── Qué proveedor usar. "auto" = el de pago si hay clave y, si falla o no hay, el gratuito ──
    stt_provider: Literal["auto", "deepgram", "whisper"] = "auto"
    llm_provider: Literal["auto", "anthropic", "gemini"] = "auto"
    tts_provider: Literal["auto", "elevenlabs", "clone", "fish", "edge"] = "auto"
    provider_cooldown_seconds: float = 120.0  # un proveedor que falla se salta este tiempo

    # ── STT ──
    stt_model: str = "nova-3"  # Deepgram
    stt_language: str = "es"
    whisper_model: str = "small"  # gratis y local: tiny | base | small | medium | large-v3
    whisper_compute_type: str = "int8"
    whisper_preload: bool = True  # descarga/carga el modelo al arrancar (evita esperar al fallar Deepgram)
    whisper_prompt: str = (
        "Escuela Colombiana de Ingeniería Julio Garavito, ECI, ICETEX, Saber Pro, "
        "admisiones, matrícula, becas, Ingeniería de Inteligencia Artificial."
    )

    # ── LLM ──
    # effort bajo = menos razonamiento antes de hablar (TTFT). Opciones: low|medium|high|xhigh|max
    llm_model: str = "claude-opus-5-5"
    llm_effort: str = "low"
    llm_max_tokens: int = 700
    llm_fallbacks: bool = True
    # Si el último proveedor falla por sobrecarga (503...) antes de dar el primer token, se reintenta con él
    # mismo. La espera se duplica en cada reintento. Con otro proveedor detrás se pasa a él sin esperar.
    llm_retries: int = 2
    llm_retry_delay: float = 0.6
    gemini_model: str = "gemini-3.5-flash-lite"  # revisa en AI Studio cuáles tienen capa gratuita
    # Segundo modelo gratuito de respaldo: la cuota de la capa gratuita es por modelo, así que si el primero
    # responde 429/503 el segundo sigue atendiendo. Vacío = sin respaldo.
    gemini_fallback_model: str = ""
    gemini_thinking_level: str = ""  # "", minimal | low | medium | high ("" = el del modelo)
    gemini_max_output_tokens: int = 1024  # en Gemini incluye los tokens de razonamiento
    # Turnos previos que ve el modelo para preguntas de seguimiento, y cuánto tiempo se recuerdan
    history_turns: int = 6
    history_ttl_seconds: float = 120.0

    # ── TTS ──
    tts_model: str = "eleven_flash_v2_5"
    # 24 kHz / 48 kbps = el mismo formato que edge-tts, así el cambio de proveedor no se nota
    elevenlabs_output_format: str = "mp3_24000_48"
    tts_concurrency: int = 3  # llamadas simultáneas a ElevenLabs (límite del plan)
    tts_stability: float = 0.5
    tts_similarity: float = 0.8
    # Clonación de voz local y gratuita (Qwen3-TTS sobre MLX, solo Mac con Apple Silicon). Necesita un
    # audio de referencia por personaje en voices_dir: voices/rectora.wav, voices/oswaldo.wav (ver README)
    voices_dir: Path = ROOT / "voices"
    clone_model: str = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-4bit"  # ligero: ...-0.6B-Base-4bit
    clone_stream_interval: float = 1.0  # segundos de audio por trozo (menos = empieza antes, más sobrecarga)
    clone_ref_max_seconds: float = 12.0  # más referencia no mejora y alarga el arranque de cada frase
    # Fish Audio S2 Pro (MLX), clonación alternativa para comparar: TTS_PROVIDER=fish. Más grande que Qwen3-TTS
    # (5 000 M de parámetros; la versión de 8 bits pesa 6,7 GB): comprueba velocidad y memoria con scripts.compare_clone.
    # Licencia «Fish Audio Research»: gratis para investigación y uso no comercial; el comercial pide acuerdo con Fish Audio.
    fish_model: str = "mlx-community/fish-audio-s2-pro-8bit"
    fish_stream_interval: float = 0.5  # segundos de audio por trozo (menos = empieza antes)
    fish_temperature: float = 0.7  # menos = más estable y parecido a la referencia; más = más expresivo
    fish_ref_max_seconds: float = 20.0  # Fish rinde mejor con 10-30 s de referencia
    # Voces genéricas gratuitas (Microsoft Edge): mujer para la Rectora, hombre para Oswaldo
    edge_voice_rectora: str = "es-CO-SalomeNeural"
    edge_voice_oswaldo: str = "es-CO-GonzaloNeural"

    # ── Muletillas: frases de cortesía pregrabadas que suenan mientras la respuesta real todavía se prepara ──
    filler_enabled: bool = True
    fillers_file: Path = ROOT / "fillers.json"
    filler_start_seconds: float = 4.0  # la primera suena si pasan más de estos segundos sin respuesta, contando desde que llega el audio
    filler_imminent_seconds: float = 1.5  # si la primera frase de la respuesta lleva menos de esto en el TTS, la muletilla de apertura espera: el audio real está por salir
    filler_max_chain: int = 3  # tope de muletillas seguidas si la respuesta sigue sin estar lista (≈ 4 s cada una)
    filler_margin_seconds: float = 0.6  # la siguiente se entrega este margen antes de que acabe la anterior: sin huecos
    filler_min_seconds: float = 3.5  # una muletilla fuera de [min, max] se avisa en el log para ajustar su texto
    filler_max_seconds: float = 4.5
    interaction_log_enabled: bool = True  # una línea JSON por pregunta atendida: sirve para ver qué falta en la base de conocimiento
    interaction_log_file: Path = ROOT / "logs" / "questions.jsonl"

    # ── Arranque ──
    prime_cache_on_start: bool = True
    preload_presentation: bool = True
    # Las teclas 0-9 responden al instante con lo que haya en disco y, si está desactualizado o es de emergencia,
    # lo regeneran en segundo plano. Mínimo entre dos regeneraciones de la misma pregunta (no martillear al LLM).
    presentation_refresh_seconds: float = 60.0

    static_dir: Path = ROOT / "static"
    knowledge_dir: Path = ROOT / "knowledge"
    questions_file: Path = ROOT / "questions.json"
