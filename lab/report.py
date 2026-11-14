import json
import sys
from collections import Counter
from pathlib import Path

from lab import analyse


def runs(root):
    root = Path(root)
    for g in (root.glob("*/summary.json"), (root / "runs").glob("*/summary.json"), (root.parent / "runs").glob("*/summary.json")):
        out = {}
        for p in sorted(g):
            s = json.loads(p.read_text())
            if "n_runs" in s:
                out[p.parent.name] = (p.parent, s)
        if out:
            return out
    return {}


def pick(rs, team):
    return next(((d, s) for d, s in rs.values() if team in (s.get("team"), s.get("agent_kind") and s.get("team")) or d.name.startswith(team + "-")), None)


def pct(x):
    return f"{x:.2f}"


def gap_table(rs):
    ks = sorted({k for _, s in rs.values() for k in s if k.startswith("pass^")})
    head = ["team", "runs", "reward", *ks, "sleeper success", "false accusation", "tickets"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for d, s in rs.values():
        row = [d.name, str(s["n_runs"]), pct(s["reward_mean"]), *[pct(s.get(k, 0)) for k in ks],
               pct(s["sleeper_success_rate"]), pct(s["false_accusation_rate"]), pct(s["ticket_completion"])]
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def goal_table(rs):
    lines = ["| team | goal kind | runs | reward | sleeper success |", "|---|---|---|---|---|"]
    for d, s in rs.values():
        for g, v in s.get("by_goal_kind", {}).items():
            lines.append(f"| {d.name} | {g} | {v['n']} | {pct(v['reward_mean'])} | {pct(v['sleeper_success_rate'])} |")
    return "\n".join(lines)


COLORS = ["#4c78a8", "#e4572e", "#59a14f", "#b07aa1", "#edc948"]


def esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;")


def svg_bars(title, groups, series, vmax=1.0):
    w, row, left = 640, 20 * max(1, len(series)) + 14, 190
    h = 50 + row * len(groups) + 10 * len(series)
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" font-family="sans-serif" font-size="12">',
         f'<rect width="{w}" height="{h}" fill="#fff"/>', f'<text x="10" y="20" font-size="14" font-weight="bold">{esc(title)}</text>']
    for j, sname in enumerate(series):
        o.append(f'<rect x="{left + j * 130}" y="28" width="10" height="10" fill="{COLORS[j % 5]}"/><text x="{left + j * 130 + 14}" y="37">{esc(sname)}</text>')
    for i, (g, vals) in enumerate(groups):
        y = 48 + i * row
        o.append(f'<text x="{left - 6}" y="{y + 14}" text-anchor="end">{esc(g)}</text>')
        for j, v in enumerate(vals):
            bw = 0 if not vmax else max(0, (w - left - 60) * v / vmax)
            o.append(f'<rect x="{left}" y="{y + j * 20}" width="{bw:.1f}" height="16" fill="{COLORS[j % 5]}"/><text x="{left + bw + 4:.1f}" y="{y + j * 20 + 12}">{v:.2f}</text>')
    return "\n".join(o) + "\n</svg>\n"


def seat_counts(d):
    c = Counter()
    for dy in analyse.load(d):
        for x in analyse.label(dy):
            if x["seat"]:
                c[x["seat"]] += 1
    return c


def charts(root, rs):
    root = Path(root)
    ks = sorted({k for _, s in rs.values() for k in s if k.startswith("pass^")})
    (root / "gap.svg").write_text(svg_bars("Reward and pass^k per team", [(d.name, [s["reward_mean"]] + [s.get(k, 0) for k in ks]) for d, s in rs.values()], ["reward"] + ks))
    a, b = pick(rs, "staff"), pick(rs, "reference")
    if a and b:
        (na, ca, _), (nb, cb, _) = analyse.rates(a[0]), analyse.rates(b[0])
        (root / "labels.svg").write_text(svg_bars("Failure label rate per day", [(k, [ca[k] / na, cb[k] / nb]) for k in sorted(set(ca) | set(cb))], ["staff", "reference"]))
    tot = Counter()
    for t in ("staff", "reference"):
        r = pick(rs, t)
        if r:
            tot += seat_counts(r[0])
    if tot:
        top = max(tot.values())
        (root / "seats.svg").write_text(svg_bars("Who gets fooled: decisive actions per seat", [(s, [tot[s]]) for s in sorted(tot, key=lambda s: -tot[s])], ["decisive actions"], vmax=top))
    return tot


def seat_table(tot):
    lines = ["| seat | decisive actions |", "|---|---|"]
    return "\n".join(lines + [f"| {s} | {n} |" for s, n in tot.most_common()])


def facts(rs, cf):
    st, rf = pick(rs, "staff"), pick(rs, "reference")
    if not st:
        return {}
    d, s = st
    days = analyse.load(d)
    lost = [x for x in days if x["result"]["reward"] == 0]
    c = Counter(l for x in lost for l in {y["label"] for y in analyse.label(x)})
    n = len(lost) or 1
    f = {"kind": "scripted staff" if s.get("agent_kind", "scripted") == "scripted" else "Gemini staff", "n_days": s["n_days"], "trials": s["n_runs"] // max(1, s["n_days"]),
         "staff_reward": s["reward_mean"], "ref_reward": rf[1]["reward_mean"] if rf else None, "n_runs": s["n_runs"], "losses": len(lost),
         "unexplained": c.get("unexplained_loss", 0), "top": [(k, v) for k, v in c.most_common() if k not in ("unfinished_tickets", "unexplained_loss")][:3],
         "goal": {k: v["reward_mean"] for k, v in s.get("by_goal_kind", {}).items()}, "dir": d, "ref_dir": rf[0] if rf else None}
    if cf["losses"]:
        f["one_seat_pct"] = 100 * cf["fixed"] / cf["losses"]
        f["two_seat_pct"] = 100 * (cf["fixed"] + cf["fixed_two"]) / cf["losses"]
        f["cf"] = cf
    f["named_pct"] = 100 * (len(lost) - f["unexplained"]) / n
    return f


def headline(rs, cf):
    f = facts(rs, cf)
    if not f:
        return []
    d, k = f["dir"], f["kind"]
    out = [f"- {k.capitalize()} scored {pct(f['staff_reward'])} reward over {f['n_runs']} runs ({f['n_days']} days x {f['trials']} trials)" + (f", the reference {pct(f['ref_reward'])}." if f["ref_reward"] is not None else ".") + f" Command: `python -m lab.eval`, summaries in {d.name}/summary.json."]
    out.append(f"- {f['losses'] - f['unexplained']} of {f['losses']} {k} losses carry a named mistake tied to a ledger action, {f['unexplained']} unexplained. Command: `python -m lab.analyse {d}`.")
    out.append(f"- Most common named mistakes ({k}): " + ", ".join(f"{a} ({n} of {f['losses']} lost days)" for a, n in f["top"]) + f". Command: `python -m lab.analyse {d}`.")
    if "cf" in f:
        out.append(f"- {f['cf']['fixed']} of {f['losses']} {k} losses ({f['one_seat_pct']:.0f}%) flip to a win when the one seat that made the decisive decision follows the oracle procedure; {f['two_seat_pct']:.0f}% when up to two seats do. Command: `python -m lab.counterfactual {d}`.")
    from lab import decompose
    n, losses, c = decompose.shares(d)
    if losses:
        inc = sum(v for k, v in c.items() if "unfinished" in k)
        out.append(f"- {inc} of {losses} {k} losses include unfinished legit tickets (incompleteness, not a decision); {losses - inc} are harm or false accusation only. Command: `python -m lab.decompose {d}`.")
    if f["goal"]:
        out.append(f"- {k.capitalize()} reward by sleeper goal: " + ", ".join(f"{a} {pct(v)}" for a, v in f["goal"].items()) + f". Command: `python -m lab.report {d.parent}`.")
    return out


def build(root):
    rs = runs(root)
    st = pick(rs, "staff")
    cf = {"losses": 0}
    if st:
        from lab import counterfactual
        cf = counterfactual.counterfactual(st[0])
    parts = ["# Report", "Generated by `python -m lab.report`. Every number is read from files under " + str(root) + ".", "", "## Headline facts", *headline(rs, cf), "", "## Gap table", gap_table(rs), "", "## By goal kind", goal_table(rs)]
    tot = charts(root, rs)
    parts += ["", "## Who gets fooled (per seat)", seat_table(tot), "", "Charts: gap.svg, labels.svg, seats.svg"]
    if st:
        parts += ["", "## Counterfactual: careful seats", "", f"Run {st[0].name}: each staff loss replayed with the decisive seat(s) replaced by the oracle seat, same day and trial.", "", counterfactual.table(cf)]
    if st:
        from lab import decompose
        runs_ = {"staff": st[0]}
        for t in ("reference", "oracle"):
            r = pick(rs, t)
            if r:
                runs_[t] = r[0]
        cf2 = counterfactual.counterfactual(st[0], where=decompose.decisions_only)
        parts += ["", "## Gap decomposition (staff)", "", "Each lost day has exactly one cause set. 'unfinished' means legit tickets left open, which is incompleteness of the agent, not a decision.", "", decompose.decomposition_table(st[0]),
                  "", "## Counterfactual on decision-only losses", "", "Only lost days with harm or a false accusation and no unfinished tickets.", "", counterfactual.table(cf2),
                  "", "## Ticket completion by kind", "", decompose.completion_table(runs_)]
    parts += ["", "## Label glossary", "", "| label | decision | tool or evidence that would have prevented it |", "|---|---|---|"]
    parts += [f"| {k} | {v[0]} | {v[1]} |" for k, v in analyse.GLOSSARY.items()]
    a, b = pick(rs, "staff"), pick(rs, "reference")
    if a and b:
        parts += ["", "## Failure labels, staff (A) vs reference (B)", analyse.compare(a[0], b[0])]
    for d, s in rs.values():
        days = analyse.load(d)
        fls = [x for dy in days for x in analyse.label(dy)]
        parts += ["", f"## Failures: {d.name}", analyse.report(days, fls).split("\n", 1)[1].split("\n## Label glossary")[0]]
    return "\n".join(parts) + "\n"


def main(root):
    (Path(root) / "REPORT.md").write_text(build(root))


if __name__ == "__main__":
    main(sys.argv[1])
