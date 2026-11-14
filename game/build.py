"""Build the static Canary browser game into game/site/ (gitignored). Owner: HARNESS (WS6).

    uv run python game/build.py            # then: python -m http.server -d game/site 8000

It plays one full game plus the solver in CPython, records exactly which `canary` modules were imported,
and copies only those files (plus canary_game.py) into game/site/py/. The page loads them into Pyodide
from py/manifest.json. Nothing else from the repo (data/, results/, red-team, MCP server) is shipped.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SITE = HERE / "site"
STATIC = ("index.html", "app.js", "style.css")


_TRACE = """
import json, sys
sys.path.insert(0, sys.argv[1])
import canary_game
g = canary_game.Game(3000)
g.call_json("list_employees", "{}")
g.call_json("advance_day", "{}")
canary_game.solver_result(3000)
print(json.dumps(sorted({m.__file__ for n, m in list(sys.modules.items())
                         if (n == "canary" or n.startswith("canary.")) and getattr(m, "__file__", None)})))
"""


def traced_modules() -> list[Path]:
    """Trace in a FRESH interpreter: in a process that already imported canary (e.g. pytest), a
    before/after diff of sys.modules would miss modules and ship a broken site."""
    out = subprocess.run([sys.executable, "-c", _TRACE, str(HERE)], capture_output=True, text=True,
                         check=True, cwd=ROOT)
    return sorted(Path(f).resolve() for f in json.loads(out.stdout.strip().splitlines()[-1]))


def build(out: Path = SITE) -> dict:
    if out.exists():
        shutil.rmtree(out)
    (out / "py").mkdir(parents=True)
    rels = []
    for f in traced_modules():
        rel = f.relative_to(ROOT)
        dst = out / "py" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst)
        rels.append(rel.as_posix())
    shutil.copy2(HERE / "canary_game.py", out / "py" / "canary_game.py")
    rels.append("canary_game.py")
    for name in STATIC:
        shutil.copy2(HERE / name, out / name)
    ref = HERE / "reference.json"
    if ref.exists():
        shutil.copy2(ref, out / "reference.json")
    manifest = {"files": rels}
    (out / "py" / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest


if __name__ == "__main__":
    m = build()
    print(f"built {SITE.relative_to(ROOT)}: {len(m['files'])} python files")
