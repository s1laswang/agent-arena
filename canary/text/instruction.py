"""python -m canary.text.instruction --tier medium > harbor/canary-task/instruction.md"""
from __future__ import annotations

import argparse
import sys


def render(tier: str = "medium") -> str:
    from canary.env import Env
    return Env(tier, 0).instruction()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="medium")
    sys.stdout.write(render(ap.parse_args(argv).tier))


if __name__ == "__main__":
    main()
