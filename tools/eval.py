#!/usr/bin/env python3
"""Run the fixed evaluation set through the real model and report what Polish would do.

  tools/eval.py [--device NPU|CPU] [--model DIR] [--max-prompt-tokens N]

For each message: latency, the rewrite, the fact check and the "keep" words
(plain words the fact check cannot see, such as "again"). Run it on the NPU by
hand after changing the prompt; it is not part of pytest.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="NPU")
    ap.add_argument("--model", default="Qwen3-4B-Instruct-2507-int4-cw-ov")
    ap.add_argument("--max-prompt-tokens", type=int, default=None)
    ap.add_argument("--only", type=int, nargs="*", help="indexes of messages to run")
    args = ap.parse_args()
    os.environ["POLISH_DEVICE"] = args.device
    os.environ["POLISH_MODEL"] = args.model
    if args.max_prompt_tokens:
        os.environ["POLISH_MAX_PROMPT_TOKENS"] = str(args.max_prompt_tokens)

    from polish import daemon  # reads the environment above
    from polish.factcheck import check, normalize
    from polish.prompt import clean_output, reapply_whitespace

    messages = json.loads((ROOT / "tools" / "eval_messages.json").read_text())
    t0 = time.perf_counter()
    pipe = daemon.load_pipeline()
    load = time.perf_counter() - t0
    failures = 0
    worst = 0.0
    for i, m in enumerate(messages):
        if args.only and i not in args.only:
            continue
        t0 = time.perf_counter()
        try:
            out = reapply_whitespace(m["text"], clean_output(daemon.rewrite(pipe, m["text"])))
        except ValueError:
            expected = m.get("expect") == "too_long"
            failures += not expected
            print(f"--- [{i}] too long for the prompt budget{' (expected)' if expected else ' FAIL'}\n")
            continue
        secs = time.perf_counter() - t0
        worst = max(worst, secs)
        missing = check(m["text"], out)
        lost = [w for w in m.get("keep", []) if normalize(w) not in normalize(out)]
        bad = missing or lost
        failures += bool(bad)
        flag = "FAIL " + ", ".join(missing + [f"keep:{w}" for w in lost]) if bad else "ok"
        print(f"--- [{i}] {secs:.1f}s {flag}\n{out}\n", flush=True)
    print(f"load {load:.1f}s, slowest {worst:.1f}s, worst case {load + worst:.1f}s; {failures} failing")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
