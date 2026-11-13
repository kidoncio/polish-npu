# Polish

**Select a message, press a shortcut, and get it back clearer. Rewritten locally by a small LLM on the Intel NPU.**

Write a quick message to a colleague in Teams, Slack or an email. Select it and press
**Copilot + P**. A few seconds later the selection is replaced by the same message with
the typos, accents and punctuation fixed, and the sentences made clearer:

```
 oi pessoal o deploy de hj falhou de novo no staging, alguem consegue olhar antes das 15h? nao precisa reverter
 ──►  ◌ Polishing…
 ──►  ✓ Done
 Oi, pessoal, o deploy de hoje falhou de novo no staging. Alguém consegue olhar antes das 15h? Não precisa reverter.
```

Polish keeps the language you wrote in and never translates. It keeps your tone and
**every piece of information**. A deterministic check compares the rewrite with the
original, and if a date, number, link, name, negation or word such as "again" went
missing, it keeps your original text. Nothing leaves your machine.

It is the sibling of [Utter](https://github.com/kidoncio/utter-npu), which does voice
dictation on the same NPU.

## Why

I write a lot of short messages in a hurry, and they go out with missing accents,
abbreviations and run-on sentences. A cloud assistant can fix them, but that means
pasting work chat into a third-party service, and copying back and forth.

A Core Ultra laptop has an NPU that sits idle almost all the time. It can run a 4B
model well enough to polish a chat message in about 10 seconds, without touching the
CPU or the GPU you are working with.

## Requirements

Tested on:

| Component | Version |
|---|---|
| Distro | Bazzite 45 (Fedora Kinoite, `bazzite-dx-nvidia` image) |
| Kernel | 7.3 (`intel_vpu` driver + `intel-npu-firmware`, both shipped by Bazzite) |
| CPU / NPU | Intel Core Ultra 9 275HX (Arrow Lake-HX), NPU 3720 |
| Desktop | **KDE Plasma 6.8, Wayland** |
| Laptop | Acer Predator Helios Neo 16 AI (Copilot key) |

Polish needs KDE Plasma, because it asks KWin which window is focused. To copy and
paste for you, it also needs write access to `/dev/uinput`, which Bazzite grants to
the seated user. Without that access it works on terminals only, through the clipboard.

### What gets installed

The host gets three small files. Everything else lives in a [distrobox](https://distrobox.it/)
running Fedora 45, which can be the same one Utter uses.

**Host** (already on Bazzite): `distrobox`, `podman`, `systemd`, `python3`, `gdbus`,
`notify-send`, `/dev/accel/accel0` and `/dev/uinput`.

**Container** (`dnf`):

| Package | Why |
|---|---|
| `oneapi-level-zero`, `tbb` | OpenVINO's path to the NPU |
| **Intel `linux-npu-driver` 1.38.0** (from GitHub) | NPU driver **and compiler**; Fedora's package lacks the compiler (see Utter's README) |
| `gtk4`, `gtk4-layer-shell`, `python3-gobject`, `python3-cairo` | the status pill |
| `wl-clipboard` | reading and restoring the clipboard |
| `ydotool` | the Ctrl+C and Ctrl+V that copy the selection and paste the result |
| `python3-pip`, `binutils` | bootstrap `uv`; unpack Intel's `.deb` files |

**Python 3.12 venv** (`requirements.txt`): `openvino` 2026.4.1, `openvino-genai` 2026.4.1,
`huggingface_hub`, `dbus-fast`, `pytest`.

**Model:** [`kidoncio/Qwen3-4B-Instruct-2507-int4-cw-ov`](https://huggingface.co/kidoncio/Qwen3-4B-Instruct-2507-int4-cw-ov),
about 2.2 GB. It is
[Qwen3-4B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507) converted with
**symmetric channel-wise int4**, the only int4 layout that works on the NPU.
`./install.sh --convert-model` builds it yourself instead (`tools/convert_model.sh`).

## Install

```bash
git clone https://github.com/kidoncio/polish-npu.git ~/polish-npu
cd ~/polish-npu
./install.sh --enable --shortcut Meta+Shift+P
```

`Meta+Shift+P` is what **Copilot + P** sends: the Copilot key is `Meta+Shift+F23` and holds
`Meta+Shift` while pressed. The installer is idempotent, so it is safe to re-run. To share
Utter's container, add `--container <name>`.

## Use

1. Select the text: a chat message, an email, anything in a text field.
2. Press **Copilot + P** and let go. The amber **Polishing…** pill appears.
3. In about 5–20 seconds the selection is replaced, and the pill turns green.
   Your clipboard is restored to what it held before.

What you may see instead:

| Pill | Meaning |
|---|---|
| **Copied — Ctrl+V** | You switched windows while it worked, or you are in a terminal. The result is on the clipboard. |
| **Would change information — kept the original** | The rewrite lost or changed a fact, so nothing was touched. |
| **Nothing selected** | Nothing was copied from the focused window. |
| **Text too long** | Over about 150 words, which would not finish within 30 s on the NPU. |

The first press after a while loads the model from the NPU cache, which takes about 3 s.
The model is unloaded after 5 minutes without use, so it holds no memory in between.
The pill speaks Portuguese on `pt_*` locales and English otherwise.

## Configure

Set these with `systemctl --user edit polish` (`[Service]` → `Environment=...`):

| Variable | Default | Meaning |
|---|---|---|
| `POLISH_DEVICE` | `NPU` | OpenVINO device. Falls back to `CPU` automatically if it fails. |
| `POLISH_MODEL` | `Qwen3-4B-Instruct-2507-int4-cw-ov` | folder under `models/` |
| `POLISH_IDLE_SECONDS` | `300` | unload the model after this long unused |
| `POLISH_MAX_PROMPT_TOKENS` | `700` | longest prompt accepted, at most 1024 |
| `POLISH_TERMINALS` | konsole, kitty, ghostty, … | comma-separated window classes that get the clipboard instead of a paste |

## Benchmarks

Measured on a Core Ultra 9 275HX with the same prompt, on three sample messages (two in
Portuguese, one in English):

| Model | Device | Per message | Verdict |
|---|---|---|---|
| **Qwen3-4B-Instruct-2507 int4 channel-wise** | **NPU** | **5–11 s**, load 2–3 s | real rewrite, keeps the facts |
| Qwen3-8B int4 channel-wise (OpenVINO) | NPU | 16–18 s | too conservative; turned "amanhã" into "hoje" |
| Qwen3-4B int4 group-wise | NPU | ~60 s | garbage: the NPU needs channel-wise int4 |
| Qwen3-4B int4 | CPU | ~10 s | correct, but barely rewrites |
| LFM2.5-1.2B, Phi-3.5-mini (OpenVINO NPU collection) | NPU | 4 s / 12 s | translated, invented facts, or broke the Portuguese |

The latency grows by about 0.09 s per token: a 140-word message takes about 19 s. The
evaluation set lives in `tools/eval_messages.json`. To rerun it:

```bash
distrobox enter polish -- bash -c 'cd ~/polish-npu && .venv/bin/python tools/eval.py'
```

## How it works

```
 KDE shortcut ──► polish-trigger (host) ──"polish"──► polish.sock
                                                         │
          ┌──────────────── polish.service (distrobox) ──┴──────────────────┐
          │ daemon.py                                                       │
          │   KWin script ──► focused window (id + class)                    │
          │   wait for the keys to be released ──► Ctrl+C (ydotool)          │
          │   Qwen3-4B (OpenVINO GenAI, NPU, loaded on demand)               │
          │   fact check ──► same window? Ctrl+V : clipboard                 │
          │   pill.py (GTK4 layer shell, system Python)                      │
          └─────────────────────────────────────────────────────────────────┘
```

- `polish/factcheck.py`: the deterministic check. It covers numbers, links, mentions,
  `code`, emoji, day words, negations, meaning words (again, still, only…), names and the
  language.
- `polish/prompt.py`: the prompt, few-shot examples in the message's language, and
  output cleanup.
- `polish/core.py`: the paste decision, the one-request-at-a-time guard and the
  on-demand model holder.
- `polish/desktop.py`: the clipboard (`wl-clipboard`), key injection (`ydotool`) and the
  focused window (a KWin script that calls back over D-Bus).
- `polish/daemon.py`: the socket server and the request flow.
- `polish/pill.py`: the overlay, on the container's system Python.

Lessons learned the hard way:

- **The shortcut fires when the key goes down, while Copilot is still held.** An
  injected Ctrl+C would arrive as Ctrl+Shift+Meta+C, and faking the modifiers' release
  lets the held letter reach the app. Polish reads the key state (`EVIOCGKEY`, never
  keystrokes) and waits until you let go.
- **A KDE shortcut registered from outside stays inactive until the next login.**
  `contrib/kde-shortcut.sh` marks it present, so it works right away.
- **Few-shot examples in another language make the model translate.** Polish detects
  the language and shows only examples in that language.
- **The int4 model sometimes corrupts digits in long outputs** ("800" → "80.000"). The
  fact check catches it, and your text is left alone.

## Limitations

- Only one clipboard type is restored: an image or files, otherwise the plain text.
  If your clipboard held rich text, its formatting is lost after a paste, though the
  text is kept.
- Apps that copy the whole line on Ctrl+C when nothing is selected (VS Code, for
  example) get that line polished.
- The fact check cannot see every dropped word. It covers facts and a list of meaning
  words; the rest is up to the prompt.

## Troubleshooting

| Symptom | Check |
|---|---|
| The shortcut types the letter instead | `contrib/kde-shortcut.sh Meta+Shift+P` again, or log out and in |
| "Polish is not running" notification | `systemctl --user status polish`, `journalctl --user -u polish -n 50` |
| Service is `active`, but the log stops at `Starting container...` | an install from before 2026-11-13 can hang when another app starts the same container at the same time. Run `./install.sh` again to update the unit. |
| "Can't simulate keys" | `/dev/uinput` is not writable by you |
| Log says `loaded on CPU` | the NPU failed; see the line above it. Polish still works, but more slowly. |
| Always "kept the original" | `journalctl --user -u polish` lists which kinds of facts were lost |

## Development

```bash
distrobox enter polish -- bash -c 'cd ~/polish-npu && .venv/bin/pytest -q'
```
