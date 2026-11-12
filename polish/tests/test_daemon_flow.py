"""The request flow, with fake clipboard, keys, focus, pill and model."""
import asyncio

import pytest

from polish import daemon
from polish.core import ModelHolder, Window
from polish.protocol import Done, Failed, Working

KWRITE = Window("{1}", "org.kde.kwrite")
OTHER = Window("{2}", "org.kde.kwrite")
ORIGINAL = {"text/plain;charset=utf-8": b"old clipboard"}


class Log(list):
    pass


class FakeClipboard:
    def __init__(self, log, selection):
        self.log, self.selection, self.text = log, selection, "old clipboard"

    def save(self):
        return dict(ORIGINAL)

    def restore(self, saved):
        self.log.append("restore")

    def clear(self):
        self.log.append("clear")

    def wait_text(self, timeout=0.5):
        return self.selection

    def primary_text(self):
        return self.selection

    def set_text(self, text):
        self.log.append(("set", text))


class FakeKeys:
    ok = True

    def __init__(self, log):
        self.log = log

    def wait_released(self, timeout=3.0):
        self.log.append("released")
        return True

    def copy(self):
        self.log.append("copy")

    def paste(self):
        self.log.append("paste")


class FakeFocus:
    def __init__(self, log, windows):
        self.log, self.windows = log, list(windows)

    async def active(self):
        self.log.append("focus")
        return self.windows.pop(0) if len(self.windows) > 1 else self.windows[0]


class FakePill:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def send(self, msg):
        if self.fail:
            raise OSError("cannot start the pill")
        self.sent.append(msg)


def make_app(monkeypatch, selection="oi tudo bem", windows=(KWRITE, KWRITE), rewrite="Oi, tudo bem?", pill=None):
    app = daemon.Polish()
    log = Log()
    app.clipboard = FakeClipboard(log, selection)
    app.keys = FakeKeys(log)
    app.focus = FakeFocus(log, windows)
    app.pill = pill or FakePill()
    app.models = ModelHolder(lambda: "pipe", 300, lambda: 0.0)
    monkeypatch.setattr(daemon, "rewrite", lambda pipe, text: rewrite)

    async def fake_sleep(secs):
        log.append(("sleep", secs))
    app._sleep = fake_sleep
    return app, log


def run(app):
    async def go():
        assert app.request() == "start"
        while app._tasks:
            await asyncio.sleep(0.01)
    asyncio.run(go())


def test_paste_waits_for_release_before_the_focus_check(monkeypatch):
    app, log = make_app(monkeypatch)
    run(app)
    after_set = log[log.index(("set", "Oi, tudo bem?")):]
    assert after_set[1:4] == ["released", ("sleep", daemon.FOCUS_SETTLE_SECONDS), "focus"]
    assert after_set[4] == "paste"


def test_clipboard_is_restored_only_after_the_app_had_time_to_paste(monkeypatch):
    app, log = make_app(monkeypatch)
    run(app)
    i = log.index("paste")
    assert log[i + 1] == ("sleep", daemon.PASTE_SETTLE_SECONDS) and daemon.PASTE_SETTLE_SECONDS >= 1.0
    assert log[i + 2] == "restore"
    assert app.pill.sent[-1] == Done(daemon.T["done"])


def test_focus_changed_leaves_the_result_on_the_clipboard(monkeypatch):
    app, log = make_app(monkeypatch, windows=(KWRITE, OTHER))
    run(app)
    assert "paste" not in log
    assert app.pill.sent[-1] == Done(daemon.T["copied"])


def test_empty_rewrite_keeps_the_original(monkeypatch):
    app, log = make_app(monkeypatch, rewrite="   ")
    run(app)
    assert not any(isinstance(e, tuple) and e[0] == "set" for e in log)
    assert app.pill.sent[-1] == Failed(daemon.T["kept"])


def test_pill_failure_does_not_leave_polish_busy(monkeypatch):
    app, log = make_app(monkeypatch, pill=FakePill(fail=True))
    run(app)
    assert app.busy.try_start()


def test_terminal_path_never_touches_the_clipboard_before_the_result(monkeypatch):
    app, log = make_app(monkeypatch, windows=(Window("{3}", "org.kde.konsole"),), selection="")
    run(app)
    assert "clear" not in log and "copy" not in log and "restore" not in log
    assert app.pill.sent[-1] == Failed(daemon.T["nothing"])


def test_pill_shows_working_first(monkeypatch):
    app, log = make_app(monkeypatch)
    run(app)
    assert app.pill.sent[0] == Working()
