"""Prioridad de la GPU: lo que una persona espera oír en vivo pasa antes que el trabajo de segundo plano.

El clon de voz genera UNA frase a la vez (MLX está atado a un hilo) y antes esa cola era de llegada: si el servidor
estaba regenerando las preguntas pregrabadas (al cambiar el conocimiento son 20 audios, varios minutos de GPU), la
primera frase de una pregunta en vivo esperaba detrás de todas las frases ya encoladas (se midieron 26 s hasta el
primer audio de la respuesta). Ahora:
  · las peticiones en vivo se atienden antes que las de segundo plano;
  · mientras haya una conversación en curso (`live()`), el trabajo de segundo plano no empieza frases nuevas;
  · lo que ya está generándose no se interrumpe, así que una petición en vivo espera, como mucho, a una frase."""
import asyncio
import contextlib
import contextvars
import heapq
import itertools
import weakref
from collections.abc import AsyncIterator, Iterator

BACKGROUND = contextvars.ContextVar("tts_background", default=False)
_live = 0
_gates: "weakref.WeakSet[PriorityGate]" = weakref.WeakSet()


@contextlib.contextmanager
def background() -> Iterator[None]:
    """Todo el TTS que se pida dentro de este bloque (incluidas las tareas que cree) es de segundo plano."""
    token = BACKGROUND.set(True)
    try:
        yield
    finally:
        BACKGROUND.reset(token)


@contextlib.contextmanager
def live() -> Iterator[None]:
    """Hay una persona esperando una respuesta: el trabajo de segundo plano se pone en pausa hasta que acabe."""
    global _live
    _live += 1
    try:
        yield
    finally:
        _live -= 1
        for gate in list(_gates):
            gate.wake()


def live_count() -> int:
    return _live


class PriorityGate:
    """Exclusión mutua con dos prioridades (en vivo antes que segundo plano; en orden de llegada dentro de cada una)."""

    def __init__(self) -> None:
        self._busy = False
        self._waiters: list[tuple[int, int, asyncio.Future]] = []
        self._seq = itertools.count()
        _gates.add(self)

    def wake(self) -> None:
        if self._busy:
            return
        while self._waiters:
            priority, _, fut = self._waiters[0]
            if fut.done():  # cancelado mientras esperaba
                heapq.heappop(self._waiters)
                continue
            if priority == 1 and _live:  # solo quedan de segundo plano y hay una conversación en curso: esperan
                return
            heapq.heappop(self._waiters)
            self._busy = True
            fut.set_result(None)
            return

    async def _acquire(self, is_background: bool) -> None:
        fut = asyncio.get_running_loop().create_future()
        heapq.heappush(self._waiters, (1 if is_background else 0, next(self._seq), fut))
        self.wake()
        try:
            await fut
        except asyncio.CancelledError:
            if fut.done() and not fut.cancelled():  # ya nos lo habían concedido: devolverlo
                self._release()
            raise

    def _release(self) -> None:
        self._busy = False
        self.wake()

    @contextlib.asynccontextmanager
    async def slot(self, is_background: bool | None = None) -> AsyncIterator[None]:
        """`async with gate.slot():` — por defecto, la prioridad la marca `background()` en el contexto actual."""
        await self._acquire(BACKGROUND.get() if is_background is None else is_background)
        try:
            yield
        finally:
            self._release()
