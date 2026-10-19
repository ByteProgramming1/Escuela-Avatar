import pytest

SECRETS_AND_OVERRIDES = [
    "ANTHROPIC_API_KEY", "DEEPGRAM_API_KEY", "ELEVENLABS_API_KEY", "GEMINI_API_KEY",
    "VOICE_ID_RECTORA", "VOICE_ID_OSWALDO", "STT_PROVIDER", "LLM_PROVIDER", "TTS_PROVIDER",
    "LLM_MODEL", "LLM_EFFORT", "TTS_MODEL", "GEMINI_MODEL", "WHISPER_MODEL",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Los tests no deben depender de las claves ni de los ajustes del .env o del entorno del usuario."""
    for name in SECRETS_AND_OVERRIDES:
        monkeypatch.delenv(name, raising=False)
    # Los tests no escriben el registro de preguntas ni cambian el ritmo del audio con muletillas, salvo los que las piden.
    monkeypatch.setenv("FILLER_ENABLED", "false")
    monkeypatch.setenv("INTERACTION_LOG_ENABLED", "false")
    monkeypatch.setitem(__import__("app.config", fromlist=["Settings"]).Settings.model_config, "env_file", None)
