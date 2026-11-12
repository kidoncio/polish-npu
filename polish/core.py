"""Hardware-independent Polish logic: request guard, paste decision, on-demand model.

Standard library only.
"""
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")

DEFAULT_TERMINALS = frozenset({
    "konsole", "yakuake", "kitty", "alacritty", "foot", "wezterm", "ghostty", "gnome-terminal-server",
    "console", "xterm", "tilix", "terminator", "ptyxis",
})


@dataclass(frozen=True)
class Window:
    id: str   # KWin internalId: tells two windows of the same app apart
    cls: str  # resourceClass, e.g. "org.kde.konsole"


def is_terminal(cls: str, terminals: frozenset[str] = DEFAULT_TERMINALS) -> bool:
    """Terminals by class or its last dotted segment ("com.mitchellh.ghostty" → "ghostty")."""
    cls = cls.lower()
    return cls in terminals or cls.rsplit(".", 1)[-1] in terminals


def decide_paste(before: Window | None, after: Window | None, terminal: bool, keys_ok: bool) -> str:
    """"paste" only into the very window the text came from; otherwise leave it on the clipboard."""
    if terminal or not keys_ok or before is None or after != before:
        return "clipboard"
    return "paste"


class Busy:
    """One request at a time: a press while working is ignored."""

    def __init__(self):
        self._lock = threading.Lock()
        self._busy = False

    def try_start(self) -> bool:
        with self._lock:
            if self._busy:
                return False
            self._busy = True
            return True

    def finish(self) -> None:
        with self._lock:
            self._busy = False


class ModelHolder(Generic[T]):
    """Loads the model on first use and drops it after `idle_seconds` without use."""

    def __init__(self, loader: Callable[[], T], idle_seconds: float, clock: Callable[[], float]):
        self._loader = loader
        self._idle = idle_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._model: T | None = None
        self._last_use = 0.0

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def get(self) -> T:
        with self._lock:
            if self._model is None:
                self._model = self._loader()
            self._last_use = self._clock()
            return self._model

    def maybe_unload(self) -> bool:
        with self._lock:
            if self._model is None or self._clock() - self._last_use < self._idle:
                return False
            self._model = None
            return True
