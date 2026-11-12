---
license: apache-2.0
base_model: Qwen/Qwen3-4B-Instruct-2507
base_model_relation: quantized
library_name: openvino
pipeline_tag: text-generation
tags:
  - openvino
  - openvino-genai
  - intel-npu
  - npu
  - int4
  - qwen3
language:
  - en
  - pt
---

# Qwen3-4B-Instruct-2507 — int4 channel-wise, for the Intel NPU

[Qwen/Qwen3-4B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507) converted to
**OpenVINO IR** with **symmetric, channel-wise int4 weights**. This is the layout the **Intel NPU**
(the "AI Boost" in Core Ultra processors) needs to run an LLM correctly.

> **Why this conversion exists.** The usual int4 conversions of Qwen3 (group-wise, asymmetric)
> load on the NPU but produce **garbage**: text that repeats or makes no sense. This copy uses
> `--sym --group-size -1 --ratio 1.0`, the settings the NPU plugin expects. It also runs on the
> CPU and GPU.

- **Base model:** Qwen3-4B-Instruct-2507 (non-thinking, instruction-tuned, 4B parameters, 32k context).
  All credit goes to the [Qwen team](https://huggingface.co/Qwen).
- **Size:** about 2.2 GB.
- **License:** Apache-2.0, the same as the base model.
- **Made for:** [Polish](https://github.com/kidoncio/polish-npu), a local tool that rewrites
  selected text on the NPU. The model works with any OpenVINO GenAI application.

## Requirements

| | Tested with |
|---|---|
| Hardware | Intel Core Ultra (Meteor Lake, Lunar Lake, Arrow Lake): tested on a Core Ultra 9 275HX, NPU 3720 |
| OS | Linux (Bazzite 45 / Fedora 45, kernel 7.3 with `intel_vpu`) |
| Python packages | `openvino==2026.4.1`, `openvino-genai==2026.4.1.0` (Python 3.10–3.12) |
| NPU driver | Intel [linux-npu-driver](https://github.com/intel/linux-npu-driver/releases) 1.38.0, **including the NPU compiler** |

**Linux users, mind the driver.** Some distributions (Fedora, for example) package the NPU driver
**without the compiler** (`libopenvino_intel_npu_compiler.so`). OpenVINO then still lists `NPU`
as a device, but every model fails with `ZE_RESULT_ERROR_UNSUPPORTED_FEATURE`. Install the libraries
from Intel's GitHub release (`intel-level-zero-npu` + `intel-driver-compiler-npu`) instead. To check:

```python
import openvino as ov
core = ov.Core()
print(core.available_devices)                              # must include 'NPU'
print(core.get_property("NPU", "NPU_COMPILER_VERSION"))   # 0 means the compiler is missing
```

Windows with Intel's standard NPU driver should work too, but it is not tested here.

## Download

```bash
pip install "openvino-genai==2026.4.1.0" huggingface_hub
hf download kidoncio/Qwen3-4B-Instruct-2507-int4-cw-ov --local-dir Qwen3-4B-Instruct-2507-int4-cw-ov
```

## Use

```python
import openvino_genai as ov_genai

pipe = ov_genai.LLMPipeline(
    "Qwen3-4B-Instruct-2507-int4-cw-ov", "NPU",
    MAX_PROMPT_LEN=1024,      # the NPU compiles static shapes: longest prompt, in tokens
    MIN_RESPONSE_LEN=512,     # and the longest answer it must be able to produce
    CACHE_DIR="ov_cache",     # the first compile takes ~20 s; later loads ~3 s
)

chat = ov_genai.ChatHistory([
    {"role": "system", "content": "Fix spelling and punctuation. Keep the language. Output only the text."},
    {"role": "user", "content": "hey can u check the deploy again tmrw? its failing on staging"},
])
config = ov_genai.GenerationConfig()
config.max_new_tokens = 128
config.do_sample = False          # greedy decoding: deterministic, which suits rewriting tasks
print(pipe.generate(chat, config).texts[0])
# Hey, can you check the deploy again tomorrow? It's failing on staging.
```

A plain string works as well (`pipe.generate("Say hi in Portuguese.", max_new_tokens=16)`); the
chat template is applied for you. To run on the CPU or GPU, replace `"NPU"` with `"CPU"` or `"GPU"`
and drop the two `*_LEN` options.

### Things to know on the NPU

- **Prompt length is fixed when the model is compiled.** A prompt longer than `MAX_PROMPT_LEN`
  fails, so count tokens with `pipe.get_tokenizer()` and reject long inputs yourself. Larger values
  compile more slowly and use more memory.
- **Always set `CACHE_DIR`.** Without it, every start recompiles the model, which takes about 20 s.
  Changing `MAX_PROMPT_LEN` or `MIN_RESPONSE_LEN` triggers a new compile, which is cached in turn.
- **Speed is roughly proportional to the output length**, at about 0.09 s per token (see below).
  The NPU is a good fit for short tasks that run alongside your work. For long chats, the GPU is faster.
- **There is no reasoning mode.** This is the 2507 Instruct model, so the output contains no `<think>` block.

## Speed

Measured on a Core Ultra 9 275HX (NPU 3720) with OpenVINO 2026.4.1, greedy decoding, rewriting
workplace chat messages with a ~470-token system prompt plus few-shot examples:

| | Time |
|---|---|
| First load (NPU compile, `MAX_PROMPT_LEN=1024`) | about 20 s |
| Later loads (from `CACHE_DIR`) | 2–3 s |
| 40-word message | 5–11 s |
| 140-word message | about 19 s |
| 190-word message | about 31 s |

In the same test, other models from the OpenVINO NPU collection were either slower (Qwen3-8B
int4-cw: 16–18 s per message) or much worse in Portuguese (Phi-3.5-mini, LFM2.5-1.2B).

## Known limitations

- **Digits in long outputs are sometimes corrupted** by the int4 weights. Observed: "800" → "80.000"
  and "300" → "三00". If numbers matter, compare them between the input and the output (Polish does
  this deterministically and rejects such rewrites).
- **Quantization costs some quality** compared with the bf16 base model, especially on long or
  intricate instructions. For rewriting messages of up to about 150 words it worked well in our tests.
- **Only Linux has been tested.**

## How it was made

```bash
pip install "optimum-intel[openvino]==2.2.0" nncf==3.4.0 \
    --extra-index-url https://download.pytorch.org/whl/cpu
optimum-cli export openvino -m Qwen/Qwen3-4B-Instruct-2507 \
    --weight-format int4 --sym --group-size -1 --ratio 1.0 \
    Qwen3-4B-Instruct-2507-int4-cw-ov
```

Tool versions: optimum-intel 2.2.0, nncf 3.4.0, openvino 2026.4.1, transformers 5.5.4,
torch 2.15.0+cpu. The conversion downloads about 8 GB and takes a few minutes on a laptop CPU.
[Polish](https://github.com/kidoncio/polish-npu) has the same recipe as `tools/convert_model.sh`.

## Credits

- Model: [Qwen3-4B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507) by the Qwen team, Apache-2.0.
- Runtime and conversion tools: [OpenVINO](https://github.com/openvinotoolkit/openvino),
  [OpenVINO GenAI](https://github.com/openvinotoolkit/openvino.genai) and
  [optimum-intel](https://github.com/huggingface/optimum-intel).

This is an independent conversion, not affiliated with or endorsed by Qwen or Intel.
