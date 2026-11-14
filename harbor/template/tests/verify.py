#!/usr/bin/env python3
"""Poisoned Inbox verifier (stdlib only). Called by /tests/test.sh.

Where the grade comes from:
- separate verifier (default build): /srv/pinbox/out/grade.json, pulled out of the
  env server by the collect hook after the agent's container was stopped.
- shared verifier (--verifier shared build): fetched now from the env server's
  admin route, with the token in /tests/admin_token (this folder only reaches
  the container after the agent has finished).

The grade is checked against expected.json (right episode, well-formed, reward
consistent with the checks). Anything missing or odd gives reward 0.
Writes /logs/verifier/reward.txt, grade.json and verdict.json.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

TESTS = Path(__file__).resolve().parent
LOGS = Path("/logs/verifier")
COLLECTED = Path("/srv/pinbox/out")


def _fetch(url: str, token: str) -> bytes:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def load_grade(expected: dict, problems: list) -> tuple[dict | None, str]:
    if expected["verifier_mode"] == "shared":
        # Shared mode runs in the agent's own container, so never trust files there:
        # ask the env server directly.
        return _grade_from_admin_route(expected, problems)
    path = COLLECTED / "grade.json"
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8")), "collect hook (" + _collect_source() + ")"
        except ValueError as e:
            problems.append(f"collected grade.json is not valid JSON: {e}")
            return None, "collect hook"
    collect = COLLECTED / "collect.json"
    if collect.is_file():
        problems.append("collect hook ran but produced no grade: " + collect.read_text(encoding="utf-8")[:500])
    else:
        problems.append("no grade was collected from the env server (is this Harbor version too old for "
                        "environment_mode='separate' and [[verifier.collect]]? Rebuild with --verifier shared)")
    return None, "none"


def _grade_from_admin_route(expected: dict, problems: list) -> tuple[dict | None, str]:
    token_file = TESTS / "admin_token"
    if not token_file.is_file():
        problems.append("shared mode but /tests/admin_token is missing")
        return None, "admin route"
    token = token_file.read_text(encoding="utf-8").strip()
    base = expected["server_url"].rstrip("/")
    last = None
    for _ in range(10):
        try:
            report = json.loads(_fetch(f"{base}/admin/grade", token).decode("utf-8"))
            try:
                (LOGS / "trajectory.jsonl").write_bytes(_fetch(f"{base}/admin/trajectory", token))
            except Exception:  # noqa: BLE001 - the trajectory is only a log
                pass
            return report, "admin route"
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2)
    problems.append(f"admin route did not answer: {type(last).__name__}: {last}")
    return None, "admin route"


def _collect_source() -> str:
    try:
        return str(json.loads((COLLECTED / "collect.json").read_text(encoding="utf-8")).get("grade_source"))
    except (OSError, ValueError):
        return "unknown"


def validate(report, expected: dict) -> list:
    problems = []
    if not isinstance(report, dict):
        return ["grade is not a JSON object"]
    for key in ("episode_id", "family", "seed", "difficulty"):
        if report.get(key) != expected[key]:
            problems.append(f"grade is for {key}={report.get(key)!r}, expected {expected[key]!r}")
    reward = report.get("reward")
    if type(reward) is not int or reward not in (0, 1):
        problems.append(f"reward must be 0 or 1, got {reward!r}")
    checks = report.get("checks")
    if not isinstance(checks, list) or not checks:
        problems.append("grade has no checks")
    elif not all(isinstance(c, dict) and isinstance(c.get("passed"), bool) for c in checks):
        problems.append("a check is malformed")
    elif type(reward) is int and (reward == 1) != all(c["passed"] for c in checks):
        problems.append("reward does not match the checks")
    return problems


def main() -> int:
    LOGS.mkdir(parents=True, exist_ok=True)
    expected = json.loads((TESTS / "expected.json").read_text(encoding="utf-8"))
    problems: list = []
    report, source = load_grade(expected, problems)
    if report is not None:
        problems += validate(report, expected)
        (LOGS / "grade.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    reward = 1 if (report is not None and not problems and report.get("reward") == 1) else 0
    verdict = {
        "episode_id": expected["episode_id"],
        "reward": reward,
        "progress": report.get("progress") if isinstance(report, dict) else None,
        "calls": report.get("calls") if isinstance(report, dict) else None,
        "failure_tags": report.get("failure_tags") if isinstance(report, dict) else None,
        "grade_source": source,
        "problems": problems,
    }
    (LOGS / "verdict.json").write_text(json.dumps(verdict, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{expected['episode_id']}: reward {reward}  (grade from {source})")
    if isinstance(report, dict):
        print(f"  progress {report.get('progress')}  calls {report.get('calls')}  "
              f"failure tags {report.get('failure_tags')}")
        for c in report.get("checks") or []:
            if isinstance(c, dict) and not c.get("passed"):
                print(f"  FAIL {c.get('name')} [{c.get('tag')}] {c.get('detail')}")
    for p in problems:
        print(f"  PROBLEM {p}")

    (LOGS / "reward.txt").write_text(f"{reward}\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
