#!/usr/bin/env python3
"""Harbor collect hook. Runs inside pinbox-env after the agent's container is stopped.

Fetches the grade (and the trajectory) from the running server's admin route,
using the admin token that only this container knows, and writes the evidence
for the verifier to /srv/pinbox/out/:

  grade.json        the GradeReport (reward, progress, checks, failure tags)
  trajectory.jsonl  every tool call the agent made
  final_state.json  the final world state (for audits; includes the hidden part)
  collect.json      how the grade was obtained, plus any errors

If the server does not answer (for example it crashed), the grade is computed
from the state folder the server saved after every call. Either way the truth
is rebuilt from the episode seed, never from data the agent wrote.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"
STATE_DIR = Path(os.environ.get("PINBOX_STATE_DIR", "/srv/pinbox/state"))
OUT = Path("/srv/pinbox/out")
TOKEN_FILE = Path("/srv/pinbox/secret/admin_token")


def _get(route: str, token: str) -> bytes:
    req = urllib.request.Request(f"{BASE}/admin/{route}", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def _write(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _grade_from_state_folder() -> dict:
    from pinbox.grader import grade_state
    from pinbox.state import load_json
    return grade_state(load_json(STATE_DIR / "state.json")).to_dict()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    info = {"grade_source": None, "errors": []}
    token = TOKEN_FILE.read_text(encoding="utf-8").strip() if TOKEN_FILE.exists() else ""

    grade = None
    if token:
        try:
            grade = json.loads(_get("grade", token).decode("utf-8"))
            info["grade_source"] = "admin_route"
        except Exception as e:  # noqa: BLE001 - any failure falls back to the state folder
            info["errors"].append(f"admin grade route failed: {type(e).__name__}: {e}")
    else:
        info["errors"].append("no admin token file")
    if grade is None:
        try:
            grade = _grade_from_state_folder()
            info["grade_source"] = "state_folder"
        except Exception as e:  # noqa: BLE001
            info["errors"].append(f"state-folder grading failed: {type(e).__name__}: {e}")

    if token:
        try:
            _write(OUT / "trajectory.jsonl", _get("trajectory", token))
        except Exception as e:  # noqa: BLE001
            info["errors"].append(f"admin trajectory route failed: {type(e).__name__}: {e}")
    if not (OUT / "trajectory.jsonl").exists() and (STATE_DIR / "trajectory.jsonl").exists():
        shutil.copyfile(STATE_DIR / "trajectory.jsonl", OUT / "trajectory.jsonl")
    if (STATE_DIR / "state.json").exists():
        shutil.copyfile(STATE_DIR / "state.json", OUT / "final_state.json")

    if grade is not None:
        _write(OUT / "grade.json", json.dumps(grade, ensure_ascii=False, indent=2).encode("utf-8"))
    _write(OUT / "collect.json", json.dumps(info, ensure_ascii=False, indent=2).encode("utf-8"))

    if grade is None:
        print("collect: NO GRADE: " + "; ".join(info["errors"]), file=sys.stderr)
        return 1
    print(f"collect: {grade.get('episode_id')} reward {grade.get('reward')} via {info['grade_source']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
