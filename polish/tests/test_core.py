"""Hardware-independent request logic."""
from polish.core import Busy, ModelHolder, Window, decide_paste, is_terminal

A, B = Window("{a}", "org.mozilla.firefox"), Window("{b}", "org.mozilla.firefox")


def test_terminals_by_class_or_last_segment():
    assert is_terminal("com.mitchellh.ghostty") and is_terminal("org.kde.konsole") and is_terminal("kitty")
    assert not is_terminal("Slack") and not is_terminal("teams-for-linux")


def test_custom_terminal_list_replaces_the_default():
    assert is_terminal("my-term", frozenset({"my-term"})) and not is_terminal("kitty", frozenset({"my-term"}))


def test_paste_only_when_same_window_not_terminal_and_keys_work():
    assert decide_paste(A, A, terminal=False, keys_ok=True) == "paste"
    assert decide_paste(A, B, terminal=False, keys_ok=True) == "clipboard"  # same class, other window
    assert decide_paste(A, None, terminal=False, keys_ok=True) == "clipboard"
    assert decide_paste(A, A, terminal=True, keys_ok=True) == "clipboard"
    assert decide_paste(None, None, terminal=True, keys_ok=True) == "clipboard"
    assert decide_paste(A, A, terminal=False, keys_ok=False) == "clipboard"


def test_second_press_while_busy_is_ignored():
    b = Busy()
    assert b.try_start() and not b.try_start()
    b.finish()
    assert b.try_start()


def test_model_loads_on_demand_and_unloads_when_idle():
    now = [0.0]
    loads = []
    h = ModelHolder(lambda: loads.append(1) or "pipe", idle_seconds=300, clock=lambda: now[0])
    assert not h.loaded
    assert h.get() == "pipe" and h.get() == "pipe" and len(loads) == 1
    now[0] = 299
    assert not h.maybe_unload()
    now[0] = 300
    assert h.maybe_unload() and not h.loaded
    h.get()
    assert len(loads) == 2


def test_idle_timer_counts_from_the_last_use():
    now = [0.0]
    h = ModelHolder(lambda: "pipe", idle_seconds=300, clock=lambda: now[0])
    h.get()
    now[0] = 200
    h.get()
    now[0] = 450
    assert not h.maybe_unload()
