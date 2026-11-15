"""B4 instruction audit: one Gemini pass over the judged instruction (all tiers) and the tool list.

    uv run --python 3.12 --extra llm python scripts/instruction_audit.py [--model gemini-4-carbon] \
        [--out results/audit/instruction_audit_gemini.md]

The model sees exactly what the agent sees: the Harbor preface plus Env.instruction() for each tier, and the
MCP tool list (Env.tools_spec()). It does not see the source code; every claim it makes is checked by hand
against canary/env.py and canary/world.py in docs/DIFFICULTY.md. Needs GEMINI_API_KEY (from .env); the key
is never printed. One call, so one pass.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROMPT = """You are auditing the task statement of a reinforcement-learning benchmark before it is published.
An AI agent will receive the text below (the same text for every episode of a tier) and play the game
through the listed tools. The benchmark is meant to be hard because the agent must reason well under
uncertainty, NOT because the statement is unfair.

Find every problem of these kinds, quoting the exact words:
1. Trick wording: sentences that are misleading, ambiguous, or that a careful reader could reasonably misread.
2. Hidden information: anything the agent would need to know to play well that the text does not state,
   or a rule that seems to be implied but never written down.
3. Impossible timing: any constraint (days, delays, action budget, call cap, canary limits) that makes a
   described strategy impossible or makes some tool useless.
4. Broken or inconsistent tools: a tool description that disagrees with the rules, a parameter that is
   undocumented, or a number in "Exact parameters" that the prose never explains.
5. Inconsistencies between tiers.

For each finding give: id, category, tier(s), exact quote, why it matters for a strong agent, severity
(high / medium / low), and a suggested rewording. Be concrete. If something is fine, do not list it.
End with a one-paragraph verdict: is the statement fair and complete enough that failure reflects the
agent's reasoning rather than the text?
"""


def build_bundle() -> str:
    from canary.env import Env
    from canary.text.instruction import render
    sys.path.insert(0, str(ROOT / "harbor"))
    from build import PREFACE  # harbor/build.py: the preface every Harbor task gets
    parts = ["=== Harbor preface (prepended to every tier's instruction) ===", PREFACE]
    for tier in ("easy", "medium", "hard"):
        parts += [f"=== Instruction: {tier} tier ===", render(tier)]
    parts += ["=== MCP tool list (name, description, JSON schema) ===",
              json.dumps(Env("medium", 0).tools_spec(), indent=1)]
    return "\n".join(parts)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemini-4-carbon")
    ap.add_argument("--out", default="results/audit/instruction_audit_gemini.md")
    ap.add_argument("--thinking", default="low", help="thinking level; at the model default (medium) gemini-4-carbon "
                    "spent the whole 16k output cap on thoughts and returned no text (first attempt, 17:01 UTC)")
    a = ap.parse_args(argv)
    from canary.llm import get_client
    bundle = build_bundle()
    client = get_client(f"gemini:{a.model}", thinking_level=a.thinking)
    resp = client.chat([{"role": "system", "content": PROMPT}, {"role": "user", "content": bundle}],
                       max_tokens=32000)
    if not resp.text.strip():
        print(f"empty answer (finish reasons {client.finish_reasons}); nothing written", file=sys.stderr)
        return 1
    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    head = (f"# Instruction audit by {a.model} (one pass)\n\n"
            f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} by `scripts/instruction_audit.py`. "
            f"Input: Harbor preface + Env.instruction() for easy/medium/hard + tools_spec ({len(bundle)} chars). "
            f"Usage: {resp.usage.get('in')} in / {resp.usage.get('out')} out tokens, "
            f"cost_usd {resp.usage.get('cost_usd')}, thinking {a.thinking}, finish {client.finish_reasons}. The model's claims are checked against the code in docs/DIFFICULTY.md.\n\n---\n\n")
    out.write_text(head + resp.text.strip() + "\n")
    print(f"wrote {out.relative_to(ROOT)} ({len(resp.text)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
