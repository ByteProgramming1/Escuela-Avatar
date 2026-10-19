import os
import resource
import subprocess


def footprint_mb() -> float:
    """Memoria real del proceso según macOS (incluye la GPU, que en Apple Silicon es memoria unificada)."""
    try:
        out = subprocess.run(["footprint", "-p", str(os.getpid())], capture_output=True, text=True, timeout=20).stdout
        for line in out.splitlines():
            if "Footprint:" in line:
                value, unit = line.split("Footprint:")[1].split()[:2]
                return float(value) * {"KB": 1 / 1024, "MB": 1, "GB": 1024}[unit]
    except Exception:
        pass
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6  # respaldo: pico de RSS (bytes en macOS)


async def demo_voice(path, voice: str, text: str) -> None:
    """Voz sintética de referencia (edge-tts) para probar el flujo sin una grabación real."""
    import edge_tts

    audio = bytearray()
    async for part in edge_tts.Communicate(text, voice).stream():
        if part["type"] == "audio":
            audio += part["data"]
    path.write_bytes(bytes(audio))
