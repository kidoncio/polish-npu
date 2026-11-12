#!/usr/bin/env bash
# Polish installer for Bazzite / Fedora Atomic with an Intel Core Ultra NPU.
#
# Everything heavy goes into a Fedora distrobox; the host only gets a systemd
# user unit, a small trigger script and a .desktop entry. Safe to re-run.
#
#   ./install.sh [--container NAME] [--shortcut KEYS] [--enable] [--convert-model]
#
#   --container NAME   distrobox name; an existing Utter container works too (default: polish)
#   --shortcut KEYS    register a KDE global shortcut, e.g. Meta+Shift+P (Copilot+P)
#   --enable           enable and start the service now and on every login
#   --convert-model    convert Qwen3-4B-Instruct-2507 locally instead of downloading
#                      the converted copy (~8 GB download plus PyTorch, a few minutes)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTAINER=polish
SHORTCUT=""
ENABLE=0
CONVERT=0
IMAGE=registry.fedoraproject.org/fedora:45
MODEL=Qwen3-4B-Instruct-2507-int4-cw-ov
MODEL_REPO=kidoncio/$MODEL
MODEL_REVISION=d339ec6c5d7f11edbe8af76788c85f8542c70dba  # pinned commit of $MODEL_REPO

# Intel's Linux NPU driver. Fedora's intel-npu-driver package ships without the
# NPU compiler, so every model compile fails (ZE_RESULT_ERROR_UNSUPPORTED_FEATURE).
DRIVER_VERSION=1.38.0
DRIVER_URL="https://github.com/intel/linux-npu-driver/releases/download/v${DRIVER_VERSION}/linux-npu-driver-v1.38.0.20260910-34487311128-ubuntu2604.tar.gz"
DRIVER_SHA256=83685e6d92f4db1ca65e442846d487c7feb1335634b33994292ceb38f933bcc7

while [[ $# -gt 0 ]]; do
    case $1 in
        --container) CONTAINER=$2; shift 2 ;;
        --shortcut) SHORTCUT=$2; shift 2 ;;
        --enable) ENABLE=1; shift ;;
        --convert-model) CONVERT=1; shift ;;
        -h|--help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }
inbox() { distrobox enter "$CONTAINER" -- bash -c "$1"; }

# --- 1. host checks ------------------------------------------------------------
step "Checking host"
command -v distrobox >/dev/null || die "distrobox not found (it ships with Bazzite)"
[[ -e /dev/accel/accel0 ]] || die "no NPU device at /dev/accel/accel0 — Intel Core Ultra with the intel_vpu kernel driver required"
[[ -w /dev/accel/accel0 ]] || warn "/dev/accel/accel0 is not writable by you; add yourself to the 'render' group"
[[ ${XDG_SESSION_TYPE:-} == wayland ]] || warn "not a Wayland session; Polish needs KDE Plasma 6 on Wayland"
[[ -w /dev/uinput ]] || warn "/dev/uinput is not writable by you: Polish can only use the clipboard; selection replacement needs /dev/uinput"
echo "NPU: $(cat /sys/class/accel/accel0/device/device 2>/dev/null || echo unknown) via $(basename "$(readlink -f /sys/class/accel/accel0/device/driver)")"

# --- 2. container --------------------------------------------------------------
step "Distrobox '$CONTAINER' ($IMAGE)"
if ! distrobox list 2>/dev/null | awk -F'|' '{gsub(/ /,"",$2); print $2}' | grep -qx "$CONTAINER"; then
    distrobox create --name "$CONTAINER" --image "$IMAGE" --yes
fi
inbox 'sudo dnf install -y -q oneapi-level-zero tbb gtk4 gtk4-layer-shell python3-gobject python3-cairo \
                               wl-clipboard ydotool python3-pip binutils'
inbox 'rpm -q intel-npu-driver >/dev/null 2>&1 && sudo dnf remove -y -q intel-npu-driver || true'

# --- 3. Intel NPU user-space driver + compiler --------------------------------
step "Intel NPU driver $DRIVER_VERSION"
if inbox "test -e /usr/lib64/libze_intel_npu.so.$DRIVER_VERSION -a -e /usr/lib64/libopenvino_intel_npu_compiler.so"; then
    echo "already installed"
else
    # Under $HOME: always shared with the container (/tmp may not be).
    mkdir -p "${XDG_CACHE_HOME:-$HOME/.cache}"
    tmp=$(mktemp -d -p "${XDG_CACHE_HOME:-$HOME/.cache}" polish-driver.XXXX); trap 'rm -rf "$tmp"' EXIT
    curl -fL --progress-bar -o "$tmp/driver.tgz" "$DRIVER_URL"
    echo "$DRIVER_SHA256  $tmp/driver.tgz" | sha256sum -c --quiet || die "driver checksum mismatch"
    tar -xzf "$tmp/driver.tgz" -C "$tmp"
    inbox "set -e; cd '$tmp'; mkdir -p x
           for deb in intel-level-zero-npu_*.deb intel-driver-compiler-npu_*.deb; do
               ar x \"\$deb\" && tar -xf data.tar.* -C x && rm -f data.tar.* control.tar.* debian-binary
           done
           sudo install -m 0644 x/usr/lib/x86_64-linux-gnu/lib* /usr/lib64/
           sudo ln -sf libze_intel_npu.so.$DRIVER_VERSION /usr/lib64/libze_intel_npu.so.1
           sudo ldconfig"
fi

# --- 4. Python environment -----------------------------------------------------
step "Python 3.12 venv with OpenVINO"
inbox "set -e; export PATH=\$HOME/.local/bin:\$PATH
       command -v uv >/dev/null || python3 -m pip install -q --user uv
       cd '$ROOT'
       [[ -x .venv/bin/python ]] || uv venv -q -p 3.12 .venv
       uv pip install -q -p .venv -r requirements.txt"

# --- 5. model ------------------------------------------------------------------
if [[ -d $ROOT/models/$MODEL ]]; then
    step "Model $MODEL"; echo "already present"
elif [[ $CONVERT == 1 ]]; then
    step "Converting $MODEL locally"
    inbox "cd '$ROOT' && tools/convert_model.sh models/$MODEL"
else
    step "Model $MODEL_REPO (~2.2 GB)"
    inbox "cd '$ROOT' && .venv/bin/hf download $MODEL_REPO ${MODEL_REVISION:+--revision $MODEL_REVISION} --local-dir models/$MODEL" \
        || die "download failed; retry, or use --convert-model"
fi

# --- 6. NPU self-test ----------------------------------------------------------
step "NPU self-test"
inbox "cd '$ROOT' && .venv/bin/python - <<'EOF'
import numpy as np, openvino as ov
from openvino import opset13 as o
core = ov.Core()
if 'NPU' not in core.available_devices:
    raise SystemExit('NPU not visible to OpenVINO (devices: %s)' % core.available_devices)
x = o.parameter([1, 64], np.float32)
m = ov.Model([o.relu(o.matmul(x, o.constant(np.ones((64, 64), np.float32)), False, False))], [x])
core.compile_model(m, 'NPU')(np.ones((1, 64), np.float32))
print('OK:', core.get_property('NPU', 'FULL_DEVICE_NAME'))
EOF" || warn "NPU self-test failed; Polish will fall back to the CPU"

# --- 7. host integration -------------------------------------------------------
step "Installing service, trigger and launcher"
install -Dm755 "$ROOT/contrib/polish-trigger" "$HOME/.local/bin/polish-trigger"
install -Dm644 "$ROOT/contrib/io.github.kidoncio.polish.desktop" \
    "$HOME/.local/share/applications/io.github.kidoncio.polish.desktop"
command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 >/dev/null 2>&1 || true  # let KDE see the launcher
mkdir -p "$HOME/.config/systemd/user"
sed -e "s|@ROOT@|$ROOT|g" -e "s|@CONTAINER@|$CONTAINER|g" \
    "$ROOT/contrib/polish.service" | grep -v '^# Template' > "$HOME/.config/systemd/user/polish.service"
systemctl --user daemon-reload

if [[ $ENABLE == 1 ]]; then
    systemctl --user enable --now polish
    systemctl --user restart polish  # pick up a changed unit on re-runs
fi

# --- 8. KDE shortcut (optional) -----------------------------------------------
if [[ -n $SHORTCUT ]]; then
    step "KDE global shortcut $SHORTCUT"
    "$ROOT/contrib/kde-shortcut.sh" "$SHORTCUT"
fi

step "Done"
[[ $ENABLE == 1 ]] || echo "Start it now and on every login:  systemctl --user enable --now polish"
[[ -n $SHORTCUT ]] || echo "Bind a shortcut to 'polish-trigger' (e.g. ./install.sh --shortcut Meta+Shift+P on KDE: Copilot+P)"
echo "Logs:  journalctl --user -u polish -f"
