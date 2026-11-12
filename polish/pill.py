#!/usr/bin/python3
"""Polish pill: status indicator at the top of the screen (GTK4 + wlr-layer-shell).

Reads polish.protocol messages from stdin, one per line. Never takes keyboard
focus (Polish pastes into the focused window, so the pill must not steal it) and
lets clicks pass through. Runs on the system Python and needs
LD_PRELOAD=libgtk4-layer-shell.so (a gtk4-layer-shell requirement).
"""
import os
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
import cairo  # noqa: E402
from gi.repository import GLib, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as Layer  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from polish.i18n import strings_for  # noqa: E402
from polish.protocol import Done, Failed, Hide, Working, decode  # noqa: E402

T = strings_for(os.environ)

CSS = b"""
window { background: transparent; }
.pill {
  border-radius: 999px; padding: 7px 16px; color: white;
  font-weight: 600; font-size: 15px;
  box-shadow: 0 3px 10px rgba(0,0,0,.45);
}
.wait { background: #c98a10; }
.done { background: #1f9d55; }
.fail { background: #555b63; }
"""


class Pill(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="io.github.kidoncio.PolishPill")

    def do_activate(self):
        css = Gtk.CssProvider()
        css.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gtk.Widget.get_display(Gtk.Label()), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        w = self.win = Gtk.Window(application=self)
        Layer.init_for_window(w)
        Layer.set_layer(w, Layer.Layer.OVERLAY)
        Layer.set_anchor(w, Layer.Edge.TOP, True)
        Layer.set_margin(w, Layer.Edge.TOP, 14)
        Layer.set_keyboard_mode(w, Layer.KeyboardMode.NONE)
        Layer.set_namespace(w, "polish")

        self.box = Gtk.Box(spacing=8)
        self.box.add_css_class("pill")
        self.icon = Gtk.Label()
        self.spinner = Gtk.Spinner()
        self.text = Gtk.Label()
        for child in (self.icon, self.spinner, self.text):
            self.box.append(child)
        w.set_child(self.box)
        # Clicks pass through the pill: empty input region.
        w.connect("realize", lambda *_: w.get_surface().set_input_region(cairo.Region()))

        self.hold()  # stay alive while the window is hidden
        ch = GLib.IOChannel.unix_new(sys.stdin.fileno())
        GLib.io_add_watch(ch, GLib.PRIORITY_DEFAULT, GLib.IOCondition.IN | GLib.IOCondition.HUP,
                          self._on_stdin)

    def _on_stdin(self, ch, cond):
        line = sys.stdin.readline()
        if not line:  # daemon closed the pipe
            self.quit()
            return False
        msg = decode(line)
        if msg is not None:
            self.show(msg)
        return True

    def _style(self, css_class, icon, text, spinning=False):
        for c in ("wait", "done", "fail"):
            self.box.remove_css_class(c)
        self.box.add_css_class(css_class)
        self.icon.set_visible(not spinning)
        self.icon.set_text(icon)
        self.spinner.set_visible(spinning)
        self.spinner.set_spinning(spinning)
        self.text.set_text(text)

    def show(self, msg):
        match msg:
            case Working():
                self._style("wait", "", T["working"], spinning=True)
            case Done(message):
                self._style("done", "✓", message)
            case Failed(message):
                self._style("fail", "!", message)
            case Hide():
                self.win.set_visible(False)
                return
        self.win.set_visible(True)


if __name__ == "__main__":
    sys.exit(Pill().run([]))
