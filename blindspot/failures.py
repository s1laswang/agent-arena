"""Loader for the failure research dataset (data/failures)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "data" / "failures"


def cases() -> dict[str, dict]:
    out = {}
    for p in sorted(ROOT.glob("cases_*.json")):
        for c in json.loads(p.read_text(encoding="utf-8")):
            out[c["id"]] = c
    return out


def patterns() -> list[dict]:
    return json.loads((ROOT / "patterns.json").read_text(encoding="utf-8"))["patterns"]


def pattern_for_family(family: str) -> dict | None:
    return next((p for p in patterns() if p.get("family") == family), None)


def _money(loss):
    if not loss or loss.get("amount") is None:
        return "no money figure"
    a = loss["amount"]
    for unit, div in (("trillion", 1e12), ("bn", 1e9), ("m", 1e6)):
        if a >= div:
            return f"{loss['currency']} {a / div:,.1f}{'' if unit != 'trillion' else ''} {unit}".replace(" bn", "bn").replace(" m", "m")
    return f"{loss['currency']} {a:,.0f}"


def to_markdown() -> str:
    cs = failures_cases = cases()
    pats = patterns()
    out = ["# Failure research: what actually breaks companies", "",
           "Generated from `data/failures/*.json` by `python -m blindspot.failures`. Do not edit by hand.",
           "", f"{len(cs)} real, sourced cases. Every number comes from a cited source; where a source",
           "was unavailable the field is null and the case's `notes` say so. Loss figures are sometimes",
           "exposure (money wired and later recovered, or asset size at bankruptcy), not realised loss:",
           "see each case's loss description.", "",
           "## How the cases become the environment", "",
           "| Pattern | Kind | Ticket family | What the agent sees | Control that catches it | Real cases |",
           "|---|---|---|---|---|---|"]
    for p in pats:
        fam = p.get("family") or "(planned)"
        out.append(f"| {p['id']} {p['name']} | {p['kind']} | {fam} | {p.get('office_hazard', '')} | "
                   f"{p['control']} | {', '.join(p['cases']) or '(synthetic, see notes)'} |")
    for cat, title in (("accidental", "Honest mistakes"), ("structural", "Structural / organisational"),
                       ("cultural", "Group and cultural"), ("external_fraud", "Outside fraud exploiting weak controls")):
        out += ["", f"## {title}", ""]
        for c in sorted((c for c in cs.values() if c["category"] == cat), key=lambda c: c["year"] or 0):
            out += [f"### {c['name']} ({c['year']}) - {_money(c.get('loss'))}", "",
                    c["what_happened"], "",
                    f"- **Mechanism:** {c['mechanism']}",
                    f"- **Warning signals that existed:** " + " / ".join(c["warning_signals"]),
                    f"- **Failed controls:** " + "; ".join(c["failed_controls"]),
                    f"- **Control that would most plausibly have caught it:** {c['preventing_control']}",
                    f"- **Lesson for an AI employee:** {c['agent_lesson']}",
                    f"- **Becomes in the environment:** {c['translation_to_office_task']}",
                    f"- **Loss note:** {(c.get('loss') or {}).get('description', '')}",
                    "- **Sources:** " + "; ".join(f"[{s['title']}]({s['url']})" for s in c["sources"])]
            if c.get("notes"):
                out.append(f"- **Caveats:** {c['notes']}")
            out.append("")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    p = ROOT.parent.parent / "docs" / "FAILURE-RESEARCH.md"
    p.write_text(to_markdown(), encoding="utf-8")
    print(f"wrote {p}")
