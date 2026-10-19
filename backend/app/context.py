"""Contexto de cada turno: datos que el modelo no puede saber (hora, quién habló antes, si ya sonó una muletilla).

Va ANTES de la pregunta, en el mensaje del usuario, nunca en el bloque `system` con caché: así el prefijo
cacheado (reglas + base de conocimiento) no cambia entre preguntas y la caché de Claude/Gemini se sigue aprovechando.
`extra` deja un sitio para más señales (p. ej. cuántas personas hay frente al avatar si algún día se añade una cámara)."""
from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("America/Bogota")
# Nombres propios en vez de `locale`: no dependen de cómo esté configurado el sistema.
DAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
WHO = {"rectora": "la Rectora", "oswaldo": "el Vicerrector Académico, Oswaldo"}


def spoken_time(now: datetime) -> str:
    now = now.astimezone(TIMEZONE)
    part = "de la madrugada" if now.hour < 6 else "de la mañana" if now.hour < 12 else "de la tarde" if now.hour < 19 else "de la noche"
    hour12 = now.hour % 12 or 12
    return f"{DAYS[now.weekday()]} {now.day} de {MONTHS[now.month - 1]} de {now.year}, {hour12}:{now.minute:02d} {part}"


def turn_context(
    now: datetime,
    speaker: str,
    last_speaker: str | None = None,
    filler_played: bool = False,
    extra: Sequence[str] = (),
) -> str:
    lines = [f"Hora local en Bogotá: {spoken_time(now)}. Úsala solo si la pregunta lo requiere (por ejemplo, qué sigue en la agenda)."]
    if filler_played:
        lines.append(
            "Mientras preparabas esta respuesta ya sonó una muletilla de cortesía. No saludes, no elogies la pregunta "
            "ni uses otra muletilla: empieza directamente con el contenido."
        )
    if last_speaker and last_speaker != speaker:
        lines.append(f"La respuesta anterior la dio {WHO.get(last_speaker, last_speaker)}; ahora respondes tú. No repitas lo que ya se dijo.")
    lines.extend(extra)
    return "\n".join(lines)


def wrap_question(context: str, transcript: str) -> str:
    """Mensaje del usuario para el LLM. El contexto lo pone el sistema (no la persona): no se menciona en voz alta."""
    return f"<contexto_del_sistema>\n{context}\n</contexto_del_sistema>\n\n<pregunta_de_la_persona>\n{transcript}\n</pregunta_de_la_persona>"
