---
license: apache-2.0
base_model: Qwen/Qwen3-4B-Instruct-2507
tags:
  - openvino
  - npu
  - int4
language:
  - en
  - pt
pipeline_tag: text-generation
---

# Qwen3-4B-Instruct-2507 int4 (channel-wise) for the Intel NPU

This is [Qwen/Qwen3-4B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507) converted to
OpenVINO IR with **symmetric, channel-wise int4** weights, the layout the Intel NPU
(Core Ultra "AI Boost") needs. The usual group-wise int4 conversion loads on the NPU but
produces garbage there.

It was made for [Polish](https://github.com/kidoncio/polish-npu), a local tool that rewrites
selected text with a model on the NPU, but it works with any OpenVINO GenAI `LLMPipeline`.

All credit for the model goes to the Qwen team. The licence is Apache-2.0, the same as the base model's.

## Conversion

```bash
optimum-cli export openvino -m Qwen/Qwen3-4B-Instruct-2507 \
    --weight-format int4 --sym --group-size -1 --ratio 1.0 \
    Qwen3-4B-Instruct-2507-int4-cw-ov
```

Tool versions: optimum-intel 2.2.0, nncf 3.4.0, openvino 2026.4.1, transformers 5.5.4,
torch 2.15.0+cpu.

## Use

```python
import openvino_genai as ov_genai
pipe = ov_genai.LLMPipeline("Qwen3-4B-Instruct-2507-int4-cw-ov", "NPU",
                            MAX_PROMPT_LEN=1024, MIN_RESPONSE_LEN=1024, CACHE_DIR="cache")
print(pipe.generate("Fix the punctuation: hey how are u", max_new_tokens=64))
```

## Speed

Measured on a Core Ultra 9 275HX (NPU 3720), OpenVINO 2026.4.1, greedy decoding:

| | Time |
|---|---|
| First load (NPU compile) | about 20 s |
| Later loads (from `CACHE_DIR`) | 2–3 s |
| Rewrite of a 40-word chat message | 5–11 s |
| Rewrite of a 140-word message | about 19 s |
| Cost per additional token | about 0.09 s |

## Known issue

In long outputs, the int4 weights sometimes corrupt digits, for example "800" became "80.000"
and "300" became "三00". Polish checks every number deterministically and refuses such a rewrite.
