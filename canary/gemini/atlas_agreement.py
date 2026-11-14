"""Failure Atlas: human validation sheet and agreement score.

    python -m canary.gemini.atlas_agreement --make-sheet   # 30 claims from results/gemini/atlas.json ->
                                                          #   docs/gemini/validation.md (+ validation_context.md)
    python -m canary.gemini.atlas_agreement                # read the filled sheet -> human_agreement in atlas.json

The labeller writes agree / disagree / unsure (or a / d / u, y / n) in the "verdict" column.
score = agree / (agree + disagree); unsure rows are reported but not scored.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHEET = ROOT / "docs" / "gemini" / "validation.md"
CONTEXT = ROOT / "docs" / "gemini" / "validation_context.md"
ATLAS = ROOT / "results" / "gemini" / "atlas.json"

VERDICTS = {"agree": "agree", "a": "agree", "y": "agree", "yes": "agree", "disagree": "disagree", "d": "disagree",
            "n": "disagree", "no": "disagree", "unsure": "unsure", "u": "unsure", "?": "unsure"}


def _cell(s: str) -> str:
    return " ".join(str(s).split()).replace("|", "/")


def claims_from_atlas(atlas: dict, n: int = 30, seed: int = 0) -> list[dict]:
    """Stratified sample of verified claims: mode evidence, step labels, counterfactuals, chart localisations."""
    rng = random.Random(seed)
    names = {m["id"]: m["name"] for m in atlas.get("modes", [])}
    pools: dict[str, list[dict]] = {"mode": [], "label": [], "counterfactual": [], "localisation": []}
    for m in atlas.get("modes", []):
        for q in m.get("quotes", []):
            if q.get("verified") and q.get("from") != "label":
                pools["mode"].append({"kind": "mode", "episode": q["episode"], "t": q.get("t"),
                                      "claim": f"This step is an instance of \"{m['name']}\": {q.get('why', '')}",
                                      "quote": q["quote"]})
    for s in (atlas.get("labels") or {}).get("steps", []):
        if s.get("verified") and s.get("mode") in names:
            pools["label"].append({"kind": "label", "episode": s["episode"], "t": s["t"],
                                   "claim": f"Failure mode \"{names[s['mode']]}\": {s.get('explanation', '')}",
                                   "quote": s["quote"]})
    for cf in atlas.get("counterfactuals", []):
        if cf.get("verified"):
            pools["counterfactual"].append({"kind": "counterfactual", "episode": cf["episode"], "t": cf["t"],
                                            "claim": f"The solver would instead: {cf['solver_would']} Agent's error: "
                                                     f"{cf['why_diverged']}", "quote": cf["quote"]})
    for row in (atlas.get("localisation") or {}).get("rows", []):
        if row.get("verified") and row.get("gemini_t") is not None:
            pools["localisation"].append({"kind": "localisation", "episode": row["episode"], "t": row["gemini_t"],
                                          "claim": f"The agent's course diverges from the evidence here: "
                                                   f"{row.get('what_agent_believed', '')}", "quote": row["quote"]})
    quota = {"mode": 10, "label": 12, "counterfactual": 5, "localisation": 3}
    out: list[dict] = []
    for k, pool in pools.items():
        rng.shuffle(pool)
        out += pool[:quota[k]]
    rest = [c for k, p in pools.items() for c in p[quota[k]:]]
    rng.shuffle(rest)
    out += rest[: max(0, n - len(out))]
    seen, uniq = set(), []
    for c in out:
        key = (c["episode"], c["t"], c["kind"])
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    return uniq[:n]


def make_sheet(atlas: dict, eps=None, path: Path = SHEET, context_path: Path = CONTEXT, n: int = 30,
               force: bool = False) -> list[dict]:
    if path.exists() and not force and any(r["verdict"] for r in parse_sheet(path.read_text())):
        raise SystemExit(f"{path} already has verdicts; refusing to overwrite (use --force)")
    claims = claims_from_atlas(atlas, n)
    lines = ["# Atlas validation sheet (human labeller: Ivar)", "",
             "Gemini made each claim below about one decision of one agent episode. Its quote is verified verbatim by "
             "code; what we need from you is whether the **claim** is right. For each row open the matching section "
             "in [validation_context.md](validation_context.md) (the steps around t, the agent's own words, and the "
             "reference solver's belief/regret), then write **agree**, **disagree** or **unsure** in the verdict "
             "column (a / d / u also work). About 1 minute per row. Then commit and push, and run "
             "`python -m canary.gemini.atlas_agreement` (or tell the atlas engineer).", "",
             f"Generated {time.strftime('%Y-%m-%d %H:%M')} from atlas.json `{atlas.get('git_sha', '')}`.", "",
             "| # | episode | t | claim | quote | verdict | note |", "|---|---|---|---|---|---|---|"]
    for i, c in enumerate(claims, 1):
        lines.append(f"| {i} | {c['episode']} | {c['t']} | {_cell(c['claim'])} | \"{_cell(c['quote'])[:300]}\" |  |  |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    if eps is not None:
        from .atlas_data import excerpt
        by = {e.id: e for e in eps}
        ctx = ["# Validation context", "", "Steps around each claim. `>>>` marks the step. REGRET = value lost vs the "
               "reference solver at that step; top = solver's most likely mole and its probability; mole = the "
               "solver's probability on the true mole.", ""]
        for i, c in enumerate(claims, 1):
            ep = by.get(c["episode"])
            ctx += [f"## {i}. {c['episode']} t={c['t']} ({c['kind']})", "", f"**Claim:** {c['claim']}", "", "```",
                    excerpt(ep, c["t"], before=6, after=2, rationale_chars=700) if ep else "(episode not loaded)",
                    "```", ""]
        context_path.write_text("\n".join(ctx))
    return claims


def parse_sheet(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        if not re.match(r"^\|\s*\d+\s*\|", line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 6:
            continue
        v = VERDICTS.get(cells[5].lower().strip(" *`"), "") if cells[5] else ""
        rows.append({"n": int(cells[0]), "episode": cells[1], "t": cells[2], "verdict": v,
                     "note": cells[6] if len(cells) > 6 else ""})
    return rows


def agreement(rows: list[dict]) -> dict:
    c = Counter(r["verdict"] for r in rows if r["verdict"])
    scored = c["agree"] + c["disagree"]
    status = "pending" if not c else ("done" if sum(c.values()) >= len(rows) else "partial")
    return {"status": status, "n_claims": len(rows), "n_labelled": sum(c.values()), "agree": c["agree"],
            "disagree": c["disagree"], "unsure": c["unsure"], "score": round(c["agree"] / scored, 4) if scored else None,
            "labeller": "Ivar (human)", "sheet": "docs/gemini/validation.md", "computed_at": time.strftime("%Y-%m-%dT%H:%M")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--atlas", default=str(ATLAS))
    ap.add_argument("--sheet", default=str(SHEET))
    ap.add_argument("--make-sheet", action="store_true")
    ap.add_argument("--runs", nargs="*", default=None, help="corpus dirs (for the context file)")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    atlas = json.loads(Path(a.atlas).read_text())
    if a.make_sheet:
        eps = None
        if a.runs:
            from .atlas_data import load_corpus
            eps = load_corpus(a.runs)
        claims = make_sheet(atlas, eps, Path(a.sheet), force=a.force)
        print(f"wrote {a.sheet} ({len(claims)} claims)")
        return 0
    ha = agreement(parse_sheet(Path(a.sheet).read_text()))
    atlas["human_agreement"] = ha
    Path(a.atlas).write_text(json.dumps(atlas, indent=1, default=str))
    print(json.dumps(ha))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
