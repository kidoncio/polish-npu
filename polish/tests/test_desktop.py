"""Desktop helpers. The Wayland and KWin tests run only inside a real session."""
import asyncio
import os
import shutil
import subprocess

import pytest

from polish.desktop import SENTINEL, Clipboard, Focus, Keys, keyboard_devices, pressed_keys

needs_wayland = pytest.mark.skipif(
    not os.environ.get("WAYLAND_DISPLAY") or not shutil.which("wl-copy"), reason="needs a Wayland session")


def _kwin_on_bus() -> bool:
    if not shutil.which("gdbus"):
        return False
    r = subprocess.run(["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus", "--object-path",
                        "/org/freedesktop/DBus", "--method", "org.freedesktop.DBus.NameHasOwner", "org.kde.KWin"],
                       capture_output=True, text=True)
    return "true" in r.stdout


needs_kwin = pytest.mark.skipif(not _kwin_on_bus(), reason="needs KDE Plasma (KWin on the session bus)")

RELEASES = ["125:0", "126:0", "42:0", "54:0", "56:0", "193:0"]


def test_combo_releases_held_modifiers_first():  # Copilot still holds Meta+Shift+F23
    assert Keys.combo(46) == RELEASES + ["29:1", "46:1", "46:0", "29:0"]  # Ctrl+C
    assert Keys.combo(47)[-4:] == ["29:1", "47:1", "47:0", "29:0"]  # Ctrl+V


def test_pressed_keys_reads_the_evdev_bitmask():
    buf = bytearray(96)
    for code in (25, 42, 125):  # P, LEFTSHIFT, LEFTMETA
        buf[code // 8] |= 1 << (code % 8)
    assert pressed_keys(bytes(buf)) == [25, 42, 125]
    assert pressed_keys(bytes(96)) == []


def _fake_input(root, name, devname, keys_hex):
    d = root / name / "device"
    (d / "capabilities").mkdir(parents=True)
    (d / "name").write_text(devname + "\n")
    (d / "capabilities" / "key").write_text(keys_hex + "\n")


def test_keyboard_devices_skips_non_keyboards_and_ydotoold(tmp_path):
    full = "ffffffffffffffff ffffffffffffffff"   # has KEY_A (bit 30)
    _fake_input(tmp_path, "event2", "AT Translated Set 2 keyboard", full)
    _fake_input(tmp_path, "event0", "Power Button", "10000000000000 0")   # KEY_POWER only
    _fake_input(tmp_path, "event25", "ydotoold virtual device", full)
    assert keyboard_devices(tmp_path) == ["/dev/input/event2"]


@pytest.fixture
def user_clipboard():
    """Leave the developer's clipboard as it was."""
    c = Clipboard()
    saved = c.save()
    yield c
    c.restore(saved)


@needs_wayland
def test_clipboard_text_roundtrip(user_clipboard):
    c = user_clipboard
    c.set_text("antes")
    saved = c.save()
    c.set_text("temporário")
    assert c.get_text() == "temporário"
    c.restore(saved)
    assert c.get_text() == "antes"


@needs_wayland
def test_clipboard_roundtrip_keeps_an_image(user_clipboard):
    c = user_clipboard
    png = bytes.fromhex("89504e470d0a1a0a") + b"fake"
    c.restore({"image/png": png})
    saved = c.save()
    c.set_text("temporary")
    c.restore(saved)
    assert c.save()["image/png"] == png


@needs_wayland
def test_clipboard_rich_text_restores_its_plain_text(user_clipboard):
    c = user_clipboard
    c.restore({"text/html": b"<b>rich</b>", "text/plain;charset=utf-8": b"rich"})
    saved = c.save()
    c.set_text("temporary")
    c.restore(saved)
    assert c.get_text() == "rich"


@needs_wayland
def test_wait_text_ignores_the_sentinel(user_clipboard):
    c = user_clipboard
    c.set_text(SENTINEL)
    assert c.wait_text(timeout=0.2) == ""
    c.set_text("copiado")
    assert c.wait_text(timeout=0.2) == "copiado"


@needs_kwin
def test_focus_reports_the_focused_window():  # run from a terminal window
    async def go():
        f = Focus()
        await f.connect()
        try:
            return await f.active()
        finally:
            await f.close()
    w = asyncio.run(go())
    assert w is not None and w.id.startswith("{") and w.cls
