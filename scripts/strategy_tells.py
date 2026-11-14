import re
from sleeper.company import seat_tools
from sleeper.goals import STRATEGIES

TOOLS = sorted({t for s in ("controller", "finance_ap", "it_admin", "legal", "hr", "sales", "procurement", "ceo_assistant") for t in seat_tools(s)}, key=len, reverse=True)


def reveals(s):
    text = " ".join(s.tells + [s.counter])
    found = []
    for m in re.finditer("|".join(TOOLS), text):
        if m.group() not in found and m.group() not in ("pay", "post_chat"):
            found.append(m.group())
    return ", ".join(found[:4]) or "-"


def cell(x):
    return x.replace("|", "/").replace("\n", " ")


out = ["# Strategy tells and counters", "", "Every tell is visible in tool data an honest seat can call. `reveals` lists the tools named in the tell or counter.", ""]
for kind in ("fraud", "leak", "backdoor", "sabotage", "frame"):
    out += [f"## {kind}", "", "| strategy | tell | counter | reveals |", "|---|---|---|---|"]
    for s in sorted((s for s in STRATEGIES.values() if s.kind == kind), key=lambda s: s.id):
        out.append(f"| {s.id} | {cell('; '.join(s.tells))} | {cell(s.counter)} | {reveals(s)} |")
    out.append("")
open("results/attack/strategy_tells.md", "w").write("\n".join(out))
print(len(STRATEGIES))
