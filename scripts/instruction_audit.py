"""B4 instruction audit (docs/DIFFICULTY.md): mechanical checks of the judged instruction, plus one Gemini pass.

    uv run --python 3.12 --extra dev python scripts/instruction_audit.py --checks            # no keys, ~seconds
    uv run --python 3.12 --extra llm python scripts/instruction_audit.py --gemini [--model gemini-4-carbon]

--checks writes results/audit/instruction_checks.md and results/audit/instruction_bundle.txt:
  * renders canary.text.instruction for easy / medium / hard (the exact text the agent gets), with sha256;
  * checks harbor/canary-task/instruction.md is the medium render;
  * checks every TierParams field is printed in "Exact parameters" and every tool named in the text exists;
  * smoke-tests all 13 MCP tools on a fresh Env per tier (valid args, documented fields);
  * computes the timing budget: actions x days vs the call cap, and the last day a canary can still surface.

--gemini: the model sees exactly what the agent sees (Harbor preface + the three renders + the tool list), never
the source code. Every claim it makes is checked by hand against the code in docs/DIFFICULTY.md. Needs
GEMINI_API_KEY (python-dotenv reads .env; the key is never printed). One call = one pass.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CANARY_ALLOW_DEV", "1")
TIERS = ("easy", "medium", "hard")

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


def renders() -> dict[str, str]:
    from canary.text.instruction import render
    return {t: render(t) for t in TIERS}


def build_bundle() -> str:
    from canary.env import Env
    sys.path.insert(0, str(ROOT / "harbor"))
    from build import PREFACE  # harbor/build.py: the preface every Harbor task gets
    parts = ["=== Harbor preface (prepended to every tier's instruction) ===", PREFACE]
    for tier, txt in renders().items():
        parts += [f"=== Instruction: {tier} tier ===", txt]
    parts += ["=== MCP tool list (name, description, JSON schema) ===",
              json.dumps(Env("medium", 0).tools_spec(), indent=1)]
    return "\n".join(parts)


def smoke(tier: str, seed: int = 4242) -> list[tuple[str, bool, str]]:
    """Call every tool once with valid arguments on a fresh Env; return (tool, ok, fields or error)."""
    from canary.env import Env
    env = Env(tier, seed)
    out = []

    def call(tool, args):
        r = env.call(tool, args)
        out.append((tool, bool(r.ok), ", ".join(sorted(r.data)) if r.ok else str(r.error)))
        return r

    emps = call("list_employees", {}).data["employees"]
    a, b = emps[0]["id"], emps[1]["id"]
    call("status", {})
    call("list_documents", {"day_from": 1, "day_to": 1})
    call("plant_canary", {"doc_title": "Audit memo", "assignment": {a: "A", b: "B"}})
    call("interview", {"employee": a, "topic": "recent_documents"})
    call("restrict_access", {"employee": b})
    call("unrestrict_access", {"employee": b})
    call("advance_day", {})
    call("read_access_logs", {"day_from": 1, "day_to": 1})
    msgs = call("search_messages", {"query": "the"}).data.get("messages") or []
    if msgs:
        call("read_message", {"id": msgs[0]["id"]})
    else:
        out.append(("read_message", False, "no message matched 'the' to read"))
    call("check_leak_feed", {})
    call("accuse", {"employee": a})
    return out


def checks() -> str:
    from canary.env import Env
    from canary.rules import TIERS as P
    from canary.rules import TIERS_VERSION
    R = renders()
    names = [t["name"] for t in Env("hard", 0).tools_spec()]
    L = [f"# Instruction audit: mechanical checks (rules {TIERS_VERSION})", "",
         f"Generated by `scripts/instruction_audit.py --checks` at git `{_git()}`. No API keys.", "",
         "## Renders", "", "| tier | chars | sha256 (first 16) |", "|---|---|---|"]
    for t, txt in R.items():
        L.append(f"| {t} | {len(txt)} | `{hashlib.sha256(txt.encode()).hexdigest()[:16]}` |")
    harbor = (ROOT / "harbor/canary-task/instruction.md").read_text()
    L += ["", f"- `harbor/canary-task/instruction.md` equals the medium render (ignoring trailing whitespace): "
          f"**{harbor.rstrip() == R['medium'].rstrip()}**"]
    L += ["", "## Every number is printed", ""]
    for t, txt in R.items():
        params = P[t].to_dict()
        missing = [k for k in params if f"- {k}: " not in txt]
        L.append(f"- {t}: {len(params)} TierParams fields, missing from \"Exact parameters\": "
                 f"**{missing or 'none'}**")
    L += ["", "## Every tool the text names exists", ""]
    for t, txt in R.items():
        named = sorted(set(re.findall(r"`([a-z_]+)\(", txt)) | {n for n in names if f"`{n}`" in txt})
        unknown = [n for n in named if n not in names]
        unmentioned = [n for n in names if n not in txt]
        L.append(f"- {t}: named {len(named)}; unknown: **{unknown or 'none'}**; tools never mentioned in the text "
                 f"(described only in the tool list): {unmentioned or 'none'}")
    L += ["", "## Tool smoke test (fresh Env, dev seed 4242, one valid call per tool)", "",
          "| tier | tool | ok | fields returned / error |", "|---|---|---|---|"]
    bad = 0
    for t in TIERS:
        for tool, ok, info in smoke(t):
            bad += not ok
            L.append(f"| {t} | `{tool}` | {'yes' if ok else '**NO**'} | {info} |")
    L += ["", f"Failures: **{bad}**.", "", "## Timing budget", "",
          "| tier | days | actions/day | investigative actions available | call cap | leak delay | last plant day whose canary can surface by the horizon |",
          "|---|---|---|---|---|---|---|"]
    for t in TIERS:
        p = P[t]
        last = p.n_days - min(p.delay_choices)
        L.append(f"| {t} | {p.n_days} | {p.actions_per_day} | {p.actions_per_day * p.n_days} | {p.tool_call_cap} | "
                 f"{', '.join(map(str, p.delay_choices))} | day {last} (leaked the same evening, shortest delay) |")
    L += ["", "The investigative budget never exceeds the call cap, so the cap only binds on agents that spam free "
          "calls. A canary leaks at the end of a day and appears `delay` days later, so the last day on which a "
          "plant can still pay off is the horizon minus the shortest delay."]
    return "\n".join(L) + "\n"


def _git() -> str:
    import subprocess
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "?"


def gemini(model: str, thinking: str, out: str) -> int:
    from canary.llm import get_client
    bundle = build_bundle()
    client = get_client(f"gemini:{model}", thinking_level=thinking)
    resp = client.chat([{"role": "system", "content": PROMPT}, {"role": "user", "content": bundle}],
                       max_tokens=32000)
    if not resp.text.strip():
        print(f"empty answer (finish reasons {client.finish_reasons}); nothing written", file=sys.stderr)
        return 1
    path = ROOT / out
    path.parent.mkdir(parents=True, exist_ok=True)
    head = (f"# Instruction audit by {model} (one pass)\n\n"
            f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} at git `{_git()}` by "
            f"`scripts/instruction_audit.py --gemini`. Input: Harbor preface + Env.instruction() for easy/medium/hard "
            f"+ tools_spec ({len(bundle)} chars, sha256 {hashlib.sha256(bundle.encode()).hexdigest()[:16]}). "
            f"Usage: {resp.usage.get('in')} in / {resp.usage.get('out')} out tokens, cost_usd {resp.usage.get('cost_usd')}, "
            f"thinking {thinking}, finish {client.finish_reasons}. The model's claims are checked against the code in "
            f"docs/DIFFICULTY.md.\n\n---\n\n")
    path.write_text(head + resp.text.strip() + "\n")
    print(f"wrote {path.relative_to(ROOT)} ({len(resp.text)} chars)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checks", action="store_true")
    ap.add_argument("--gemini", action="store_true")
    ap.add_argument("--model", default="gemini-4-carbon")
    ap.add_argument("--out", default="results/audit/instruction_audit_gemini.md")
    ap.add_argument("--thinking", default="low", help="thinking level; at the model default (medium) gemini-4-carbon "
                    "spent its whole 16k output cap on thoughts and returned no text in the first draft's attempt")
    a = ap.parse_args(argv)
    if not (a.checks or a.gemini):
        ap.error("pass --checks and/or --gemini")
    if a.checks:
        d = ROOT / "results/audit"
        d.mkdir(parents=True, exist_ok=True)
        (d / "instruction_bundle.txt").write_text(build_bundle())
        (d / "instruction_checks.md").write_text(checks())
        print("wrote results/audit/instruction_checks.md and instruction_bundle.txt")
    if a.gemini:
        return gemini(a.model, a.thinking, a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
