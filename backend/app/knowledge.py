import hashlib
from dataclasses import dataclass
from pathlib import Path

from .personas import GENERAL_RULES


@dataclass(frozen=True)
class Knowledge:
    system_text: str  # reglas + base de conocimiento: el bloque estable que se cachea
    version: str  # hash del contenido; invalida audios pregrabados cuando cambia el .md


def load_knowledge(directory: Path) -> Knowledge:
    """Concatena todos los .md de `directory`. La base cabe entera en el prompt, así que
    no hay búsqueda vectorial: cero latencia de recuperación y el modelo ve todo el contexto."""
    files = sorted(directory.glob("*.md"))
    if not files:
        raise FileNotFoundError(f"No hay archivos .md en {directory}")
    body = "\n\n".join(f.read_text(encoding="utf-8").strip() for f in files)
    system_text = f"{GENERAL_RULES}\n<BASE_DE_CONOCIMIENTO>\n{body}\n</BASE_DE_CONOCIMIENTO>"
    version = hashlib.sha1(system_text.encode()).hexdigest()[:10]
    return Knowledge(system_text=system_text, version=version)
