"""Anti-cheat battery (ported from Poisoned Inbox's tests/test_eval.py; owner HEAD-INTEGRITY).

Fails if any attack probe's mean > 0, any stop-early ladder episode != 0, the control drifts from the
solver, any replayable committed episode re-grades differently, a tool result aliases env state, the
outcome depends on PYTHONHASHSEED, or the Harbor verifier turns a broken ledger into a non-zero reward.
"""
from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from canary.redteam import anticheat as ac

ROOT = Path(__file__).resolve().parent.parent
SEEDS = [0, 1, 2, 3]


@pytest.fixture(scope="module")
def battery():
    return ac.run_battery(["easy", "medium", "hard"], SEEDS)


def _rows(b, kind=None):
    return [r for r in b["rows"] if kind is None or r["kind"] == kind]


def test_every_probe_ran(battery):
    names = {r["probe"] for r in battery["rows"]}
    expected = set(ac.BASELINE_PROBES) | set(ac.CUSTOM_PROBES) | set(ac.LADDER) | {ac.CONTROL, "solver"}
    assert expected <= names
    assert all(r["n"] == len(SEEDS) for r in battery["rows"])


def test_no_attack_probe_scores_above_zero(battery):
    bad = [(r["tier"], r["probe"], r["mean"], r["errors"]) for r in _rows(battery, "attack") if not r["blocked"]]
    assert not bad, bad
    for r in _rows(battery, "attack"):
        assert r["mean"] <= 0, r


def test_always_zero_probes_are_exactly_zero(battery):
    for r in battery["rows"]:
        if r["probe"] in ac.SCRIPTED_ALWAYS_ZERO:
            assert r["max"] == 0 and r["mean"] == 0 and r["positive"] == 0, r


def test_stop_early_ladder_scores_exactly_zero(battery):
    ladder = _rows(battery, "ladder")
    assert len(ladder) == 3 * len(ac.LADDER)
    for r in ladder:
        assert r["blocked"] and r["max"] == 0 and r["mean"] == 0, r


def test_plus_probes_never_beat_the_solver(battery):
    plus = _rows(battery, "plus")
    assert len(plus) == 3 * len(ac.PLUS)
    for r in plus:
        assert r["blocked"], r
        assert r["extra"].get("above_solver", 0) == 0, r
        assert r["extra"].get("max_accusations_accepted", 0) <= 1, r


def test_control_equals_solver(battery):
    solver = {r["tier"]: r for r in battery["rows"] if r["probe"] == "solver"}
    for r in _rows(battery, "control"):
        assert r["blocked"], r
        assert r["mean"] == solver[r["tier"]]["mean"] > 0
        assert r["extra"].get("drift", 0) == 0


def test_no_probe_got_two_accusations_or_a_bad_canary(battery):
    for r in battery["rows"]:
        assert r["extra"].get("garbage_accepted_accuse", 0) == 0, r
        assert r["extra"].get("per_person_canary_accepted", 0) == 0, r
        assert r["extra"].get("accusations_accepted", 0) <= r["n"], r
        assert r["extra"].get("max_accusations_accepted", 0) <= 1, r   # per episode, not only in total
        assert not r["errors"], r


def test_battery_is_deterministic():
    a = ac.run_battery(["medium"], [7])
    b = ac.run_battery(["medium"], [7])
    assert a == b


# ----------------------------------------------------------------------------- replay
def test_committed_episodes_replay_consistently():
    rows = ac.replay_committed(ROOT)
    assert rows, "no committed episodes found"
    mism = [(r["file"], r["mismatches"][:2]) for r in rows if r["replay_consistent"] is False]
    assert not mism, mism
    assert sum(r["replayed"] for r in rows) > 0, "nothing was replayable"
    line = ac.coverage_line(rows)
    assert "Replay coverage:" in line and "NOTHING" not in line


def test_coverage_line_flags_an_empty_replay():
    rows = [{"n": 5, "replayed": 0, "consistent": 0, "not_replayable": 5, "replay_consistent": None}]
    assert "NOTHING was re-played" in ac.coverage_line(rows)


def test_two_accusations_in_one_episode_are_caught(monkeypatch):
    """The per-episode check: 2 accepted in one episode and 0 in another must not average out to 'fine'."""
    calls = iter([2, 0])
    monkeypatch.setattr(ac, "CUSTOM_PROBES", {"accuse_all_sequential": lambda env: {"accusations_accepted": next(calls)}})
    b = ac.run_battery(["easy"], [0, 1])
    row = next(r for r in b["rows"] if r["probe"] == "accuse_all_sequential")
    assert row["extra"]["accusations_accepted"] == 2 and row["extra"]["max_accusations_accepted"] == 2
    assert row["blocked"] is False


def test_replay_detects_a_tampered_score(tmp_path):
    src = next(f for f in sorted((ROOT / "data/runs/committed").glob("v1.3/reference/solver-medium-*/episodes.jsonl")))
    dst = tmp_path / "data/runs/committed/v1.3/fake/medium"
    dst.mkdir(parents=True)
    lines = src.read_text().splitlines()
    e = json.loads(lines[0])
    e["score"] = 1.0           # claim a perfect score the trajectory never earned
    (dst / "episodes.jsonl").write_text(json.dumps(e) + "\n")
    (dst / "meta.json").write_text(json.dumps({"tiers_version": "v1.3"}))
    rows = ac.replay_committed(tmp_path)
    assert rows and rows[0]["replay_consistent"] is False


# ----------------------------------------------------------------------------- grader hardening
def _mutate(x):
    if isinstance(x, dict):
        for k in list(x):
            _mutate(x[k])
        x["__mutated__"] = True
        x.pop("recipients", None)
    elif isinstance(x, list):
        for v in x:
            _mutate(v)
        x.append("e00")


def test_tool_results_are_detached_copies():
    actions, score = ac.solver_actions("medium", 3)
    from canary.eval import make_env
    env = make_env("medium", 3)
    for tool, args in actions:
        r = env.call(tool, copy.deepcopy(args))
        _mutate(r.data)
    clean = ac.replay_actions("medium", 3, actions)
    assert env.score() == clean.score() == score
    assert env.docs == clean.docs
    assert env.call("list_documents", {"day_from": 1, "day_to": 1}).data == \
        clean.call("list_documents", {"day_from": 1, "day_to": 1}).data


_HASH_SCRIPT = """
import json
from canary.redteam import anticheat as ac
b = ac.run_battery(["medium", "hard"], [0, 5])
print(json.dumps(b, sort_keys=True))
"""


def test_identical_across_pythonhashseed():
    outs = []
    for hs in ("0", "1", "4242"):
        env = {**os.environ, "PYTHONHASHSEED": hs}
        env.pop("CANARY_WORLD_SECRET", None)
        p = subprocess.run([sys.executable, "-c", _HASH_SCRIPT], capture_output=True, text=True, env=env,
                           cwd=ROOT, timeout=300)
        assert p.returncode == 0, p.stderr[-2000:]
        outs.append(p.stdout)
    assert outs[0] == outs[1] == outs[2]


def _verifier_py(tmp: Path) -> str:
    sh = (ROOT / "harbor/template/tests/test.sh").read_text()
    py = re.search(r"python3 - <<'PY'\n(.*?)\nPY", sh, re.S).group(1)
    # as_posix: a Windows path pasted into Python source would turn "\U..." into a unicode escape
    return py.replace("/logs/verifier", (tmp / "logs").as_posix()).replace("/evidence", (tmp / "evidence").as_posix())


@pytest.mark.parametrize("ledger", [None, "", "not json", '{"score": "nan"}', '{"score": 1e309}', '{"score": 2}',
                                    '{"score": null}', '{"no_score": 1}', '["score", 1]'])
def test_harbor_verifier_fails_closed(tmp_path, ledger):
    """A grader error (missing/garbage/out-of-range ledger) is a failure with reward 0, never a pass."""
    (tmp_path / "logs").mkdir()
    (tmp_path / "evidence").mkdir()
    if ledger is not None:
        (tmp_path / "evidence/ledger.json").write_text(ledger)
    env = {k: v for k, v in os.environ.items() if k != "CANARY_LEDGER_TOKEN"}
    p = subprocess.run([sys.executable, "-c", _verifier_py(tmp_path)], capture_output=True, text=True, env=env)
    assert p.returncode != 0
    assert (tmp_path / "logs/reward.txt").read_text() == "0"


def test_harbor_verifier_ignores_symlinked_evidence(tmp_path):
    (tmp_path / "logs").mkdir()
    (tmp_path / "evidence").mkdir()
    fake = tmp_path / "fake.json"
    fake.write_text('{"score": 1.0}')
    try:
        (tmp_path / "evidence/ledger.json").symlink_to(fake)
    except OSError:   # Windows without developer mode / admin cannot create symlinks
        pytest.skip("symlinks not allowed here")
    env = {k: v for k, v in os.environ.items() if k != "CANARY_LEDGER_TOKEN"}
    p = subprocess.run([sys.executable, "-c", _verifier_py(tmp_path)], capture_output=True, text=True, env=env)
    assert p.returncode != 0 and (tmp_path / "logs/reward.txt").read_text() == "0"


def test_cheat_corpus_injection_changes_nothing():
    """Momin's cheat corpus (data/redteam/corpus.jsonl), injected mid-episode into the solver: no call is accepted
    and the solver's score is exactly unchanged. Full sweep: `python -m canary.redteam.corpus eval`."""
    from canary.redteam import corpus
    rows = corpus.load()
    assert len(rows) >= 100
    res = corpus.evaluate(["medium", "hard"], [11], rows[::4])
    assert res["runs"] > 0 and not res["changed"] and not res["accepted"], res
