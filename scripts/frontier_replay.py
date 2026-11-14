import glob
import json
import os
import sys

from scripts.cli_seat import ROOT, rescore


def check(path):
    rec = json.load(open(path))
    saved = rec["scores"]
    got = rescore(rec)
    bad = {k: (saved[k], got.get(k)) for k in saved if saved[k] != got.get(k)}
    return bad


def main(argv=None):
    a = argv if argv is not None else sys.argv[1:]
    paths = a or sorted(p for p in glob.glob(os.path.join(ROOT, "results", "frontier", "**", "*.json"), recursive=True) if "/cache/" not in p and not p.endswith(".state.json"))
    fail = 0
    for p in paths:
        if os.path.basename(p) == "GAP.json":
            continue
        try:
            bad = check(p)
        except Exception as e:
            bad = {"error": f"{type(e).__name__}: {e}"}
        fail += bool(bad)
        print(("FAIL " if bad else "ok   ") + os.path.relpath(p, ROOT), bad or "")
    print(f"{len(paths) - fail}/{len(paths)} replayed identically")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
