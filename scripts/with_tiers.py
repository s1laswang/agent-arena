"""Run an analysis script/module under a frozen earlier tiers version (rules.tiers_version), in-process.

    python scripts/with_tiers.py v1.3 scripts/paired_gemini.py --version v1.3
    python scripts/with_tiers.py v1.3 -m canary.analysis.accuse --runs data/runs/committed/v1.3/...

For replay-based analysis (accusation audit, tags, regret, replay verification) of runs played under v1.3.
"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    version, rest = sys.argv[1], sys.argv[2:]
    import os
    from canary import rules
    os.environ["CANARY_TIERS_OVERRIDE"] = version  # child processes (MCP server, driver jobs) follow the same version
    with rules.tiers_version(version):
        assert rules.TIERS_VERSION == version
        if rest[0] == "-m":
            sys.argv = [rest[1]] + rest[2:]
            runpy.run_module(rest[1], run_name="__main__", alter_sys=True)
        else:
            sys.argv = rest
            sys.path.insert(0, str(Path(rest[0]).resolve().parent))
            runpy.run_path(rest[0], run_name="__main__")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit as e:
        raise SystemExit(e.code)
