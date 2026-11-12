"""Desktop plumbing: clipboard (wl-clipboard), key injection (ydotool) and the
focused window (a KWin script that reports back over D-Bus).
"""
import asyncio
import os
import subprocess
import time
from pathlib import Path

from dbus_fast import Message, MessageType
from dbus_fast.aio import MessageBus
from dbus_fast.service import ServiceInterface, method

from polish.core import Window

# Put on the clipboard before an injected Ctrl+C, so "nothing was copied" is
# detectable. (An empty clipboard would not do: Klipper refills it.)
SENTINEL = "⁣polish-nothing-copied⁣"

# X11 aliases that wl-paste lists next to the real MIME types.
_ALIASES = {"UTF8_STRING", "COMPOUND_TEXT", "TEXT", "STRING", "text/plain"}
_PLAIN = "text/plain;charset=utf-8"


def _paste(*args: str, timeout: float = 5) -> bytes | None:
    try:
        r = subprocess.run(["wl-paste", "--no-newline", *args], capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:  # the offering app never answered
        return None
    return r.stdout if r.returncode == 0 else None


def _copy(data: bytes, *args: str) -> None:
    subprocess.run(["wl-copy", *args], input=data, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   timeout=5, check=True)


class Clipboard:
    def save(self) -> dict[str, bytes]:
        listed = _paste("--list-types")
        if not listed:
            return {}
        # Only real MIME types: X11 targets such as SAVE_TARGETS never answer.
        types = [t for t in listed.decode().splitlines() if "/" in t and t not in _ALIASES]
        saved = {}
        for t in types[:12]:
            data = _paste("--type", t, timeout=1)
            if data is not None:
                saved[t] = data
        return saved

    def restore(self, saved: dict[str, bytes]) -> None:
        """wl-copy offers one type, so restore the most specific one: a non-text type
        (an image, files) if there is one, otherwise the plain text."""
        if not saved:
            subprocess.run(["wl-copy", "--clear"], timeout=5)
            return
        others = [t for t in saved if not t.startswith("text/")]
        if others:
            _copy(saved[others[0]], "--type", others[0])
        elif _PLAIN in saved:
            _copy(saved[_PLAIN])
        else:
            first = next(iter(saved))
            _copy(saved[first], "--type", first)

    def clear(self) -> None:
        self.set_text(SENTINEL)

    def get_text(self) -> str:
        data = _paste("--type", "text")
        return data.decode("utf-8", "replace") if data is not None else ""

    def set_text(self, text: str) -> None:
        _copy(text.encode())

    def primary_text(self) -> str:
        data = _paste("--primary", "--type", "text")
        return data.decode("utf-8", "replace") if data is not None else ""

    def wait_text(self, timeout: float = 0.5) -> str:
        """The clipboard text once something other than the sentinel is there, else ""."""
        deadline = time.monotonic() + timeout
        while True:
            text = self.get_text()
            if text and text != SENTINEL:
                return text
            if time.monotonic() >= deadline:
                return ""
            time.sleep(0.03)


# Linux input keycodes.
KEY_LEFTCTRL, KEY_C, KEY_V = 29, 46, 47
# Released before every combo: the Copilot key (Meta+Shift+F23) may still be held.
_HELD = [125, 126, 42, 54, 56, 193]  # LEFTMETA RIGHTMETA LEFTSHIFT RIGHTSHIFT LEFTALT F23


class Keys:
    def __init__(self, runtime_dir: Path):
        self.socket = runtime_dir / "polish-ydotool.sock"
        self.ok = False
        self._proc: subprocess.Popen | None = None

    def start(self) -> bool:
        if not os.access("/dev/uinput", os.W_OK):
            return False
        self.socket.unlink(missing_ok=True)
        self._proc = subprocess.Popen(
            ["ydotoold", f"--socket-path={self.socket}", "--socket-perm=0600"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 3
        while not self.socket.exists() and self._proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        self.ok = self.socket.exists() and self._proc.poll() is None
        return self.ok

    @staticmethod
    def combo(code: int) -> list[str]:
        """`ydotool key` arguments for Ctrl+<code>, after releasing held modifiers."""
        return [f"{k}:0" for k in _HELD] + [f"{KEY_LEFTCTRL}:1", f"{code}:1", f"{code}:0", f"{KEY_LEFTCTRL}:0"]

    def _key(self, args: list[str]) -> None:
        env = dict(os.environ, YDOTOOL_SOCKET=str(self.socket))
        subprocess.run(["ydotool", "key", "--key-delay", "10", *args], env=env, check=True, timeout=5,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _press(self, code: int) -> None:
        seq = self.combo(code)
        self._key(seq[:len(_HELD)])
        time.sleep(0.1)  # let the compositor see the modifiers go up
        self._key(seq[len(_HELD):])

    def copy(self) -> None:
        self._press(KEY_C)

    def paste(self) -> None:
        self._press(KEY_V)

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
        self.socket.unlink(missing_ok=True)


BUS_NAME = "io.github.kidoncio.Polish"
SCRIPT_NAME = "polish-focus"
_SCRIPT = (
    "const w = workspace.activeWindow;\n"
    f'callDBus("{BUS_NAME}", "/", "{BUS_NAME}", "Report", '
    'w ? w.internalId.toString() : "", w ? String(w.resourceClass) : "");\n'
)


class _Reporter(ServiceInterface):
    def __init__(self):
        super().__init__(BUS_NAME)
        self.pending: asyncio.Future | None = None

    @method()
    def Report(self, wid: "s", cls: "s"):  # noqa: F821 (D-Bus signature annotations)
        if self.pending and not self.pending.done():
            self.pending.set_result(Window(wid, cls) if wid else None)


class Focus:
    """The focused window, asked from KWin with a one-shot script."""

    def __init__(self, runtime_dir: Path | None = None):
        runtime_dir = runtime_dir or Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
        self._script = runtime_dir / f"{SCRIPT_NAME}.js"
        self._bus: MessageBus | None = None
        self._reporter = _Reporter()

    async def connect(self) -> None:
        self._script.write_text(_SCRIPT)
        self._bus = await MessageBus().connect()
        self._bus.export("/", self._reporter)
        await self._bus.request_name(BUS_NAME)

    async def _kwin(self, path: str, iface: str, member: str, sig: str = "", body: list | None = None):
        reply = await self._bus.call(Message(destination="org.kde.KWin", path=path, interface=iface,
                                             member=member, signature=sig, body=body or []))
        if reply.message_type == MessageType.ERROR:
            raise RuntimeError(f"KWin {member}: {reply.error_name}")
        return reply.body

    async def active(self) -> Window | None:
        loop = asyncio.get_running_loop()
        self._reporter.pending = fut = loop.create_future()
        try:
            await self._kwin("/Scripting", "org.kde.kwin.Scripting", "unloadScript", "s", [SCRIPT_NAME])
            (sid,) = await self._kwin("/Scripting", "org.kde.kwin.Scripting", "loadScript", "ss",
                                      [str(self._script), SCRIPT_NAME])
            await self._kwin(f"/Scripting/Script{sid}", "org.kde.kwin.Script", "run")
            return await asyncio.wait_for(fut, 1.0)
        except (asyncio.TimeoutError, RuntimeError):
            return None
        finally:
            self._reporter.pending = None

    async def close(self) -> None:
        if self._bus:
            self._bus.disconnect()
            self._bus = None
