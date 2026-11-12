#!/usr/bin/env bash
# Convert Qwen3-4B-Instruct-2507 to the int4 layout the Intel NPU needs
# (symmetric, channel-wise). Run inside the distrobox from the repo root.
#
#   tools/convert_model.sh OUT_DIR
#
# Downloads ~8 GB from Hugging Face and installs PyTorch (CPU) into .venv-export.
set -euo pipefail
out=${1:?usage: $0 OUT_DIR}
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PATH=$HOME/.local/bin:$PATH

[[ -x .venv-export/bin/python ]] || uv venv -q -p 3.12 .venv-export
VIRTUAL_ENV=.venv-export uv pip install -q "optimum-intel[openvino]==2.2.0" nncf==3.4.0 \
    --extra-index-url https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match

.venv-export/bin/optimum-cli export openvino -m Qwen/Qwen3-4B-Instruct-2507 \
    --weight-format int4 --sym --group-size -1 --ratio 1.0 "$out"
echo "converted into $out (you can delete .venv-export now)"
