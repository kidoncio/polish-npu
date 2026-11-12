#!/usr/bin/env python3
"""Polish: rewrite the selected text with a local LLM on the Intel NPU.

Listens on a Unix socket at $XDG_RUNTIME_DIR/polish.sock; the command
"polish\\n" polishes the current selection. It asks KWin which window is
focused, copies the selection with an injected Ctrl+C, rewrites it, checks that
no fact was lost and pastes the result back with Ctrl+V. If the window changed
or is a terminal, the result is left on the clipboard instead. The pill
(pill.py, a separate process on the system Python + GTK4) shows the state.

The model is loaded on the first request and unloaded after POLISH_IDLE_SECONDS
without one. Message text is never logged.

Configuration (environment variables):
  POLISH_MODEL              model folder under models/   (Qwen3-4B-Instruct-2507-int4-cw-ov)
  POLISH_DEVICE             OpenVINO device; falls back to CPU if it fails   (NPU)
  POLISH_IDLE_SECONDS       unload the model after this long unused          (300)
  POLISH_MAX_PROMPT_TOKENS  longest prompt accepted, examples included (700: about 150 words
                            of message, which keeps the NPU under 30 s; at most 1024)
  POLISH_TERMINALS          comma-separated window classes treated as terminals
"""
import asyncio
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import openvino_genai as ov_genai

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from polish.core import DEFAULT_TERMINALS, Busy, ModelHolder, decide_paste, is_terminal  # noqa: E402
from polish.desktop import Clipboard, Focus, Keys  # noqa: E402
from polish.factcheck import check  # noqa: E402
from polish.i18n import strings_for  # noqa: E402
from polish.prompt import build_chat, clean_output, max_new_tokens, reapply_whitespace  # noqa: E402
from polish.protocol import Done, Failed, Hide, Working, encode  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MODEL = ROOT / "models" / os.environ.get("POLISH_MODEL", "Qwen3-4B-Instruct-2507-int4-cw-ov")
DEVICE = os.environ.get("POLISH_DEVICE", "NPU")
IDLE_SECONDS = float(os.environ.get("POLISH_IDLE_SECONDS", "300"))
NPU_PROMPT_LEN = 1024  # NPU MAX_PROMPT_LEN: the compiled (and cached) prompt size
MAX_RESPONSE_TOKENS = 1024  # NPU MIN_RESPONSE_LEN: the longest answer it can give
MAX_PROMPT_TOKENS = min(int(os.environ.get("POLISH_MAX_PROMPT_TOKENS", "700")), NPU_PROMPT_LEN)
TERMINALS = (frozenset(c.strip().lower() for c in os.environ["POLISH_TERMINALS"].split(",") if c.strip())
             if os.environ.get("POLISH_TERMINALS") else DEFAULT_TERMINALS)
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
SOCK = RUNTIME / "polish.sock"
LAYER_SHELL = "/usr/lib64/libgtk4-layer-shell.so.0"
T = strings_for(os.environ)


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def load_pipeline() -> ov_genai.LLMPipeline:
    if not MODEL.is_dir():
        raise RuntimeError(f"model not found: {MODEL} (run install.sh)")
    cache = str(ROOT / "cache")
    for device in dict.fromkeys([DEVICE, "CPU"]):  # requested device, then CPU
        cfg = {"CACHE_DIR": cache}
        if device == "NPU":
            cfg |= {"MAX_PROMPT_LEN": NPU_PROMPT_LEN, "MIN_RESPONSE_LEN": MAX_RESPONSE_TOKENS}
        try:
            t0 = time.perf_counter()
            pipe = ov_genai.LLMPipeline(str(MODEL), device, **cfg)
            log(f"model {MODEL.name} loaded on {device} ({time.perf_counter() - t0:.1f}s)")
            return pipe
        except RuntimeError as e:
            log(f"could not load on {device}: {str(e).strip().splitlines()[-1]}")
    raise RuntimeError("no usable OpenVINO device")


def n_tokens(tokenizer, text: str) -> int:
    return int(tokenizer.encode(text, add_special_tokens=False).input_ids.get_shape()[1])


def rewrite(pipe: ov_genai.LLMPipeline, text: str) -> str:
    """Raises ValueError("too long") when the prompt exceeds the budget."""
    chat = ov_genai.ChatHistory(build_chat(text))
    tok = pipe.get_tokenizer()
    if n_tokens(tok, tok.apply_chat_template(chat, add_generation_prompt=True)) > MAX_PROMPT_TOKENS:
        raise ValueError("too long")
    cfg = ov_genai.GenerationConfig()
    cfg.do_sample = False
    cfg.max_new_tokens = min(max_new_tokens(n_tokens(tok, text)), MAX_RESPONSE_TOKENS)
    return pipe.generate(chat, cfg).texts[0]


class PillClient:
    """The pill process; relaunched if it dies."""

    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def send(self, msg) -> None:
        with self._lock:
            for _ in range(2):
                if self._proc is None or self._proc.poll() is not None:
                    env = dict(os.environ, LD_PRELOAD=LAYER_SHELL)
                    self._proc = subprocess.Popen(
                        ["/usr/bin/python3", str(HERE / "pill.py")],
                        stdin=subprocess.PIPE, text=True, env=env)
                try:
                    self._proc.stdin.write(encode(msg))
                    self._proc.stdin.flush()
                    return
                except BrokenPipeError:
                    self._proc = None


class Polish:
    def __init__(self):
        self.pill = PillClient()
        self.busy = Busy()
        self.models = ModelHolder(load_pipeline, IDLE_SECONDS, time.monotonic)
        self.clipboard = Clipboard()
        self.keys = Keys(RUNTIME)
        self.focus = Focus(RUNTIME)
        self.generation = 0  # invalidates "hide pill" timers from older requests
        self._tasks: set[asyncio.Task] = set()  # asyncio keeps only weak references to tasks

    async def start(self) -> None:
        if not self.keys.start():
            log("ydotoold unavailable (/dev/uinput not writable?): clipboard only, no selection outside terminals")
        await self.focus.connect()

    def request(self) -> str:
        if not self.busy.try_start():
            return "busy"
        self.generation += 1
        task = asyncio.get_running_loop().create_task(self._run(self.generation))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return "start"

    async def _run(self, gen: int) -> None:
        self.pill.send(Working())
        try:
            msg, hide_after = await self._polish(gen)
        except Exception as e:  # noqa: BLE001 — shown on the pill and logged
            log(f"error: {e}")
            msg, hide_after = Failed(f"{T['error']}: {e}"), 5
        finally:
            self.busy.finish()
        self._show_then_hide(msg, gen, hide_after)

    async def _polish(self, gen: int):
        t0 = time.perf_counter()
        win0 = await self.focus.active()
        terminal = win0 is None or is_terminal(win0.cls, TERMINALS)
        log(f"request: window {win0.cls if win0 else 'unknown'}{' (terminal)' if terminal else ''}")
        saved = await asyncio.to_thread(self.clipboard.save)
        pasted = False
        try:
            if terminal:
                text = await asyncio.to_thread(self.clipboard.primary_text)
            elif not self.keys.ok:
                return Failed(T["no_keys"]), 5
            else:
                await asyncio.to_thread(self.clipboard.clear)
                await asyncio.to_thread(self.keys.copy)
                text = await asyncio.to_thread(self.clipboard.wait_text)
            if not text.strip():
                return Failed(T["nothing"]), 3

            pipe = await asyncio.to_thread(self.models.get)
            try:
                raw = await asyncio.to_thread(rewrite, pipe, text)
            except ValueError:
                log(f"{len(text)} chars: over the {MAX_PROMPT_TOKENS}-token prompt budget")
                return Failed(T["too_long"]), 4
            out = reapply_whitespace(text, clean_output(raw))
            missing = check(text, out)
            log(f"{len(text)} → {len(out)} chars in {time.perf_counter() - t0:.1f}s"
                + (f"; fact check failed: {', '.join(m.split(':')[0] for m in missing)}" if missing else ""))
            if missing:
                return Failed(T["kept"]), 5

            await asyncio.to_thread(self.clipboard.set_text, out)
            pasted = True  # from here on the result owns the clipboard
            win1 = await self.focus.active()
            if decide_paste(win0, win1, terminal, self.keys.ok) == "clipboard":
                if not terminal and win1 != win0:
                    log("focus changed: left on the clipboard")
                return Done(T["copied"]), 3
            await asyncio.to_thread(self.keys.paste)
            await asyncio.sleep(0.3)  # let the app read the clipboard before restoring it
            await asyncio.to_thread(self.clipboard.restore, saved)
            return Done(T["done"]), 2
        finally:
            if not pasted:
                await asyncio.to_thread(self.clipboard.restore, saved)

    def _show_then_hide(self, msg, gen: int, hide_after: float) -> None:
        self.pill.send(msg)

        def hide():
            if self.generation == gen:  # no newer request took over the pill
                self.pill.send(Hide())
        asyncio.get_running_loop().call_later(hide_after, hide)

    async def unload_when_idle(self) -> None:
        while True:
            await asyncio.sleep(30)
            if await asyncio.to_thread(self.models.maybe_unload):
                log("model unloaded")


async def main() -> int:
    app = Polish()
    await app.start()

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        cmd = (await reader.readline()).decode("utf-8", "replace").strip()
        reply = app.request() if cmd == "polish" else f"unknown command: {cmd}"
        writer.write(reply.encode())
        await writer.drain()
        writer.close()

    SOCK.unlink(missing_ok=True)
    server = await asyncio.start_unix_server(serve, path=str(SOCK))
    os.chmod(SOCK, 0o600)
    log(f"listening on {SOCK}")
    asyncio.get_running_loop().create_task(app.unload_when_idle())
    try:
        async with server:
            await server.serve_forever()
    finally:
        app.keys.stop()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
