"""Desktop plumbing: clipboard (wl-clipboard), key injection (ydotool) and the
focused window (a KWin script that reports back over D-Bus).
"""
import asyncio
import fcntl
import os
import subprocess
import sys
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


def restore_type(saved: dict[str, bytes]) -> str:
    """The one type worth restoring: an image, then files, then plain text, then anything.
    Private types (chromium/*, application/x-kde-*, x-openoffice…) only make sense
    next to the text they accompany, so they come last."""
    for prefix in ("image/", "text/uri-list", _PLAIN, "text/plain"):
        for t in saved:
            if t.startswith(prefix):
                return t
    return next(iter(saved))


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
        """wl-copy offers one type, so restore the most useful one (see restore_type)."""
        if not saved:
            subprocess.run(["wl-copy", "--clear"], timeout=5)
            return
        kind = restore_type(saved)
        if kind == _PLAIN:
            _copy(saved[kind])  # plain text, offered under every text alias
        else:
            _copy(saved[kind], "--type", kind)

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


def pressed_keys(state: bytes) -> list[int]:
    """Key codes set in an EVIOCGKEY bitmask."""
    return [i for i in range(len(state) * 8) if state[i // 8] >> (i % 8) & 1]


KEY_A = 30


def keyboard_devices(sysfs: Path = Path("/sys/class/input")) -> list[str]:
    """Real keyboards (they have KEY_A), not ydotoold's virtual device."""
    found = []
    for dev in sorted(sysfs.glob("event*")):
        try:
            name = (dev / "device" / "name").read_text().strip()
            words = (dev / "device" / "capabilities" / "key").read_text().split()
        except OSError:
            continue
        lowest = int(words[-1], 16) if words else 0  # sysfs lists the highest word first
        if "ydotoold" not in name and lowest >> KEY_A & 1:
            found.append(f"/dev/input/{dev.name}")
    return found


def _eviocgkey(length: int) -> int:
    return (2 << 30) | (length << 16) | (ord("E") << 8) | 0x18  # _IOR('E', 0x18, len)


def any_key_down(devices: list[str]) -> bool | None:
    """True if a key is held on any readable keyboard; None if none is readable."""
    readable = False
    for path in devices:
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            continue
        try:
            buf = bytearray(96)
            fcntl.ioctl(fd, _eviocgkey(len(buf)), buf)
            readable = True
            if pressed_keys(bytes(buf)):
                return True
        except OSError:
            pass
        finally:
            os.close(fd)
    return False if readable else None


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
        # A daemon killed without cleanup leaves its ydotoold (and virtual keyboard) behind.
        subprocess.run(["pkill", "-f", f"ydotoold --socket-path={self.socket}"], stderr=subprocess.DEVNULL)
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

    def wait_released(self, timeout: float = 3.0) -> bool:
        """Wait until the user lets go of every key (the shortcut fires on press).

        Injecting while Copilot+P is still down would turn Ctrl+C into
        Ctrl+Shift+Meta+C, and faking the modifiers' release makes the held P
        reach the app. Only the key state is read (EVIOCGKEY), never keystrokes.
        """
        devices = keyboard_devices()
        deadline = time.monotonic() + timeout
        while True:
            down = any_key_down(devices)
            if not down:
                return down is False
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.02)

    def _press(self, code: int) -> None:
        seq = self.combo(code)
        if not self.wait_released():
            # Key state unreadable, or still held after the timeout: force the modifiers up.
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


BUS_NAME = "io.github.kidoncio.Polish"  # the D-Bus interface the KWin script calls
SCRIPT_NAME = "polish-focus"


def _script(destination: str) -> str:
    """KWin script reporting the focused window to `destination` (our unique bus name,
    so several connections never steal each other's replies)."""
    return ("const w = workspace.activeWindow;\n"
            f'callDBus("{destination}", "/", "{BUS_NAME}", "Report", '
            'w ? w.internalId.toString() : "", w ? String(w.resourceClass) : "");\n')


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
        self._runtime = runtime_dir
        self._bus: MessageBus | None = None
        self._reporter = _Reporter()

    async def connect(self) -> None:
        self._bus = await MessageBus().connect()
        self._bus.export("/", self._reporter)
        tag = self._bus.unique_name.lstrip(":").replace(".", "_")
        self._name = f"{SCRIPT_NAME}-{tag}"
        self._script = self._runtime / f"{self._name}.js"
        self._script.write_text(_script(self._bus.unique_name))

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
            await self._kwin("/Scripting", "org.kde.kwin.Scripting", "unloadScript", "s", [self._name])
            (sid,) = await self._kwin("/Scripting", "org.kde.kwin.Scripting", "loadScript", "ss",
                                      [str(self._script), self._name])
            await self._kwin(f"/Scripting/Script{sid}", "org.kde.kwin.Script", "run")
            return await asyncio.wait_for(fut, 1.0)
        except (asyncio.TimeoutError, RuntimeError) as e:
            print(f"focused window unknown: {e!r}", file=sys.stderr, flush=True)
            return None
        finally:
            self._reporter.pending = None

    async def close(self) -> None:
        if self._bus:
            self._bus.disconnect()
            self._bus = None
            self._script.unlink(missing_ok=True)
