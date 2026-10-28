#!/usr/bin/env python3
"""Frugal bench: nightly consolidation, replayed by small local models.

Question: does a model that fits on a laptop (and soon on a phone)
consolidate a life memory as faithfully as a frontier model? We replay real
consolidation nights, with exactly the production instructions, and compare
with the memories the production model had drawn from them.

Usage (on an Apple Silicon Mac, MLX):
  run.py dataset.json --model mlx-community/Qwen3.5-4B-MLX-4bit --out sorties/

dataset.json comes from the real database and stays outside the repository: it
contains a life. So do the outputs. Only aggregate numbers can be published.
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from pensine import injection  # noqa: E402
from pensine.governor import Governor  # noqa: E402
from pensine.llm import extract_json  # noqa: E402

PROMPT = (ROOT / "consolidation" / "prompts" / "nightly.md").read_text(encoding="utf-8")


def build_prompt(batch: dict, owner: str, constitution: str) -> str:
    material = json.dumps({"connaissances_actuelles": [], "intentions_ouvertes": [],
                           "evenements": batch["events"]}, ensure_ascii=False, default=str)
    fenced, token = injection.fence(material)
    return (PROMPT.replace("{{OWNER}}", owner)
            .replace("{{CONSTITUTION}}", constitution)
            .replace("{{TODAY}}", batch["night"][:10])
            .replace("{{FENCE}}", token)
            .replace("{{EVENTS}}", fenced))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("dataset", type=Path)
    p.add_argument("--model", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--owner", default="la personne")  # French: injected into the French prompt
    p.add_argument("--skip-nights", nargs="*", default=[])
    p.add_argument("--max-tokens", type=int, default=6000)
    args = p.parse_args()

    from mlx_lm import generate, load
    from mlx_lm.sample_utils import make_sampler

    data = json.loads(args.dataset.read_text(encoding="utf-8"))
    constitution = Governor().constitution_text()
    t0 = time.time()
    model, tok = load(args.model)
    load_s = time.time() - t0
    sampler = make_sampler(temp=0.2)
    results = []
    for batch in data["batches"]:
        if any(batch["night"].startswith(s) for s in args.skip_nights):
            continue
        prompt = build_prompt(batch, args.owner, constitution)
        msgs = [{"role": "user", "content": prompt}]
        try:  # "thinking" models answer directly when asked to
            chat = tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False,
                                           enable_thinking=False)
        except TypeError:
            chat = tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False)
        n_in = len(tok.encode(chat))
        t = time.time()
        raw = generate(model, tok, prompt=chat, max_tokens=args.max_tokens, sampler=sampler)
        dt = time.time() - t
        try:
            out = extract_json(raw)
            ok = isinstance(out, dict) and isinstance(out.get("memories"), list)
        except Exception:
            out, ok = None, False
        results.append({"night": batch["night"], "seconds": round(dt, 1), "tokens_in": n_in,
                        "tokens_out": len(tok.encode(raw)), "json_ok": ok,
                        "memories": (out or {}).get("memories") if ok else None,
                        "raw": None if ok else raw[-3000:]})
        print(f"{batch['night'][:10]}  {dt:6.1f}s  json={'ok' if ok else 'KO'}  "
              f"memories={len(results[-1]['memories'] or [])}", flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    name = args.model.split("/")[-1]
    (args.out / f"{name}.json").write_text(json.dumps(
        {"model": args.model, "load_seconds": round(load_s, 1),
         "run_at": datetime.now().isoformat(timespec="seconds"), "results": results},
        ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
