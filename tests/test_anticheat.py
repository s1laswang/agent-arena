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
    bad = [(r["tier"], r["probe"], r["mean"], r["errors"]) for r in _rows(battery, "attack") if r["blocked"] is False]
    assert not bad, bad
    for r in _rows(battery, "attack"):
        assert r["mean"] <= 0, r


def test_always_zero_probes_are_exactly_zero(battery):
    for r in battery["rows"]:
        if r["probe"] in ac.SCRIPTED_ALWAYS_ZERO:
            assert r["max"] == 0 and r["mean"] == 0 and r["positive"] == 0, r


def test_stop_early_ladder_scores_exactly_zero(battery):
    ladder = [r for r in battery["rows"] if r["probe"] in ac.LADDER]
    assert len(ladder) == 3 * len(ac.LADDER) and all(r["kind"] == "sanity" for r in ladder)
    for r in ladder:
        assert r["blocked"] and r["max"] == 0 and r["mean"] == 0, r


def test_plus_probes_never_beat_the_solver(battery):
    plus = [r for r in battery["rows"] if r["probe"] in ac.PLUS]
    assert len(plus) == 3 * len(ac.PLUS)
    for r in plus:
        assert r["blocked"], r
        assert r["extra"].get("above_solver", 0) == 0, r
        assert r["extra"].get("max_accusations_accepted", 0) <= 1, r


def test_plus_probe_preempted_by_horizon_is_not_above_solver():
    """A wrong solver accusation on the LAST day (-1), then a plus probe whose extra advance_day reaches the
    horizon first: the probe never replays the accusation (score 0). That is abstaining, not an exploit, so it
    counts as preempted, not as "above the solver" (it failed make reproduce on an honest secret, medium 900017)."""
    from canary.eval import make_env
    from canary.rules import TIERS
    env = make_env("medium", 0)
    wrong = next(e for e in ac._ids(env) if e != env._world.mole)
    actions = [("advance_day", {})] * (TIERS["medium"].n_days - 1) + [("accuse", {"employee": wrong})]
    assert ac.replay_actions("medium", 0, actions).score() == -1.0
    out = ac.plus_envs("medium", 0, actions)
    w_env, n_ok, _, preempted = out["solver_plus_wait_a_day"]
    assert preempted and n_ok == 0 and w_env.score() == 0.0
    r_env, n_ok, _, preempted = out["solver_plus_read_spam"]
    assert not preempted and n_ok == 1 and r_env.score() == -1.0


def test_control_equals_solver(battery):
    solver = {r["tier"]: r for r in battery["rows"] if r["probe"] == "solver"}
    for r in [r for r in battery["rows"] if r["probe"] == ac.CONTROL]:
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


def test_frontier_runs_are_replayed():
    """v1.2 is frozen in rules.TIERS_HISTORY, so the committed frontier runs (gpt-5.5, codex, opencode) are
    re-played and re-graded too, not skipped. Only secret-keyed judge seeds (grok) stay out."""
    rows = ac.replay_committed(ROOT)
    c = ac.replay_counts(rows)
    assert c["replayed"] >= 0.95 * c["n"], c
    for r in rows:
        if "/v1.3/" not in r["file"].replace("\\", "/") and any(m in r["file"] for m in ("gpt-5.5", "opencode")):
            assert r["replayed"] == r["n"] and r["replay_consistent"] is True, r


def test_tiers_version_restores_known_v_mode():
    from canary import rules
    before, before_v = rules.KNOWN_V_MODE, rules.TIERS_VERSION
    with rules.tiers_version("v1.2"):
        assert rules.KNOWN_V_MODE is False and rules.TIERS_VERSION == "v1.2"
    assert rules.KNOWN_V_MODE == before and rules.TIERS_VERSION == before_v


def test_committed_harbor_trials_are_consistent():
    rows = ac.harbor_consistency(ROOT)
    assert rows, "no committed Harbor trials found"
    bad = [(r["trial"], r["problems"]) for r in rows if r["consistent"] is False]
    assert not bad, bad
    assert any(r["trajectory_checked"] for r in rows), "no trial was checked against an agent trajectory"


def _copy_trial(tmp_path, job="g-gemini-try2"):
    import shutil
    src = next((ROOT / "results/harbor" / job).glob("canary-*"))
    dst = tmp_path / "results/harbor" / job / src.name
    shutil.copytree(src, dst)
    return dst


@pytest.mark.parametrize("edit", ["reward_txt_and_result", "ledger_score", "trajectory_accused", "second_accusation"])
def test_harbor_consistency_catches_an_edited_trial(tmp_path, edit):
    t = _copy_trial(tmp_path)
    assert ac.check_harbor_trial(t)["consistent"] is True
    if edit == "reward_txt_and_result":      # bump the reported reward everywhere except the sidecar ledger
        (t / "verifier/reward.txt").write_text("1.0")
        r = json.loads((t / "result.json").read_text())
        r["verifier_result"]["rewards"]["reward"] = 1.0
        (t / "result.json").write_text(json.dumps(r))
    elif edit == "ledger_score":             # ...or the ledger copies too, without its accusation event
        for f in ("artifacts/ledger.json", "verifier/ledger.json"):
            d = json.loads((t / f).read_text())
            d["score"] = 1.0
            (t / f).write_text(json.dumps(d))
        (t / "verifier/reward.txt").write_text("1.0")
        r = json.loads((t / "result.json").read_text())
        r["verifier_result"]["rewards"]["reward"] = 1.0
        (t / "result.json").write_text(json.dumps(r))
    elif edit == "trajectory_accused":       # the agent accused someone else than the ledger says
        tr = (t / "agent/trajectory.json").read_text()
        d = json.loads((t / "artifacts/ledger.json").read_text())
        (t / "agent/trajectory.json").write_text(tr.replace(f'"employee": "{d["accused"]}"', '"employee": "e99"'))
    else:                                    # a second accusation slipped into the ledger
        d = json.loads((t / "artifacts/ledger.json").read_text())
        d["ledger"].append(next(e for e in d["ledger"] if e["event"] == "accused"))
        (t / "artifacts/ledger.json").write_text(json.dumps(d))
    row = ac.check_harbor_trial(t)
    assert row["consistent"] is False and row["problems"], row


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


def _verifier_py(tmp: Path, server_base: str | None = None) -> str:
    sh = (ROOT / "harbor/template/tests/test.sh").read_text()
    py = re.search(r"python3[^\n]*<<'PY'\n(.*?)\nPY", sh, re.S).group(1)
    if server_base:
        py = py.replace("http://canary-server:8765", server_base)
    # as_posix: a Windows path pasted into Python source would turn "\U..." into a unicode escape
    # A valid signing key is present, so these cases fail on the ledger itself (signing: test_harbor_ledger_sig.py).
    (tmp / "tests").mkdir(exist_ok=True)
    (tmp / "tests/ledger_key").write_text("ab" * 32)
    return (py.replace("/logs/verifier", (tmp / "logs").as_posix()).replace("/evidence", (tmp / "evidence").as_posix())
              .replace("/tests/ledger_key", (tmp / "tests/ledger_key").as_posix()))


@pytest.mark.parametrize("ledger", [None, "", "not json", '{"score": "nan"}', '{"score": 1e309}', '{"score": 2}',
                                    '{"score": null}', '{"no_score": 1}', '["score", 1]'])
def test_harbor_verifier_fails_closed(tmp_path, ledger):
    """A grader error (missing/garbage/out-of-range ledger) is a failure with reward 0, never a pass."""
    (tmp_path / "logs").mkdir()
    (tmp_path / "evidence").mkdir()
    if ledger is not None:
        (tmp_path / "evidence/ledger.json").write_text(ledger)
    env = {k: v for k, v in os.environ.items() if k not in ("CANARY_LEDGER_TOKEN", "CANARY_LEDGER_KEY")}
    p = subprocess.run([sys.executable, "-c", _verifier_py(tmp_path)], capture_output=True, text=True, env=env)
    assert p.returncode != 0
    assert (tmp_path / "logs/reward.txt").read_text() == "0"
    assert json.loads((tmp_path / "logs/reward.json").read_text()) == {"reward": 0}   # Harbor reads reward.json first


def test_harbor_verifier_ignores_symlinked_evidence(tmp_path):
    (tmp_path / "logs").mkdir()
    (tmp_path / "evidence").mkdir()
    fake = tmp_path / "fake.json"
    fake.write_text('{"score": 1.0}')
    try:
        (tmp_path / "evidence/ledger.json").symlink_to(fake)
    except OSError:   # Windows without developer mode / admin cannot create symlinks
        pytest.skip("symlinks not allowed here")
    env = {k: v for k, v in os.environ.items() if k not in ("CANARY_LEDGER_TOKEN", "CANARY_LEDGER_KEY")}
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


# ----------------------------------------------------------------------------- round-1 judge findings
def test_shared_verifier_grades_only_from_the_token_ledger(tmp_path):
    """Shared-verifier builds run test.sh INSIDE the agent container, so /evidence is agent-writable there.
    A planted {"score": 1.0} must be ignored: the reward is the real, HMAC-signed server ledger (no accusation -> 0),
    and both reward files are written (Harbor reads reward.json first)."""
    import time
    from tests.test_harbor_ledger_sig import KEY, _file, _free_port, _get
    (tmp_path / "logs").mkdir()
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence/ledger.json").write_text('{"score": 1.0, "done": true, "correct": true}')
    token, port = "tok-" + "2" * 16, _free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith("CANARY_")}
    env.update(CANARY_HOST="127.0.0.1", CANARY_PORT=str(port), CANARY_ALLOW_DEV="1",
               CANARY_EPISODE_FILE=_file(tmp_path, "ep.json", json.dumps({"tier": "easy", "seed": 0})),
               CANARY_LEDGER_TOKEN_FILE=_file(tmp_path, "tok", token),
               CANARY_LEDGER_KEY_FILE=_file(tmp_path, "lk", KEY))
    proc = subprocess.Popen([sys.executable, "-m", "canary.mcp_server"], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(150):
            try:
                if _get(base + "/healthz")[0] == 200:
                    break
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.1)
        venv = {**{k: v for k, v in os.environ.items() if not k.startswith("CANARY_")},
                "CANARY_LEDGER_TOKEN": token, "CANARY_LEDGER_KEY": KEY}
        p = subprocess.run([sys.executable, "-c", _verifier_py(tmp_path, base)], capture_output=True, text=True,
                           env=venv, timeout=120)
    finally:
        proc.terminate()
        proc.communicate(timeout=10)
    assert p.returncode == 0, p.stdout[-800:] + p.stderr[-800:]
    assert float((tmp_path / "logs/reward.txt").read_text()) == 0.0
    assert json.loads((tmp_path / "logs/reward.json").read_text()) == {"reward": 0.0}
    assert "/evidence ignored" in p.stdout and "signature=ok" in p.stdout


def test_shared_verifier_with_unreachable_server_fails_closed_despite_planted_file(tmp_path):
    (tmp_path / "logs").mkdir()
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence/ledger.json").write_text('{"score": 1.0}')
    env = {**{k: v for k, v in os.environ.items() if not k.startswith("CANARY_")}, "CANARY_LEDGER_TOKEN": "x" * 64}
    p = subprocess.run([sys.executable, "-c", _verifier_py(tmp_path, "http://127.0.0.1:9")], capture_output=True,
                       text=True, env=env, timeout=120)
    assert p.returncode != 0 and (tmp_path / "logs/reward.txt").read_text() == "0"


def _copy_job(tmp_path, job):
    import shutil
    src = ROOT / "results/harbor" / job
    dst = tmp_path / "results/harbor" / job
    shutil.copytree(src, dst)
    return dst


@pytest.mark.parametrize("edit", ["holes", "incomplete", "nonzero_reward", "isolation"])
def test_harbor_check_reads_the_cheat_probe_report(tmp_path, edit):
    job = _copy_job(tmp_path, "cheat-probe")
    t = next(p for p in job.iterdir() if p.is_dir())
    assert ac.check_harbor_trial(t)["consistent"] is True
    rep_path = t / "agent/cheat.json"
    rep = json.loads(rep_path.read_text())
    if edit == "holes":
        rep["holes"] = ["secrets.file[/run/canary/ledger_token]"]
        rep_path.write_text(json.dumps(rep))
    elif edit == "incomplete":
        rep["incomplete"] = "sidecar unreachable"
        rep_path.write_text(json.dumps(rep))
    elif edit == "nonzero_reward":   # a never-accuse probe must score exactly 0, wherever the reward came from
        for f in ("verifier/reward.txt",):
            (t / f).write_text("1.0")
        r = json.loads((t / "result.json").read_text())
        r["verifier_result"]["rewards"]["reward"] = 1.0
        (t / "result.json").write_text(json.dumps(r))
        for f in ("artifacts/ledger.json", "verifier/ledger.json"):
            d = json.loads((t / f).read_text())
            d["score"] = 1.0
            (t / f).write_text(json.dumps(d))
    else:
        (t / "agent/isolation.txt").write_text("FINDING: CANARY_LEDGER_TOKEN in env\n")
    row = ac.check_harbor_trial(t)
    assert row["consistent"] is False and row["problems"], row


@pytest.mark.parametrize("edit", ["mean", "n_trials", "bucket"])
def test_harbor_job_summary_must_match_its_trials(tmp_path, edit):
    job = _copy_job(tmp_path, "oracle")
    rows = ac.harbor_consistency(tmp_path)
    assert rows and all(r["consistent"] is True for r in rows), rows
    J = json.loads((job / "result.json").read_text())
    ev = next(iter(J["stats"]["evals"].values()))
    if edit == "mean":
        ev["metrics"][0]["mean"] = 0.99
    elif edit == "n_trials":
        ev["n_trials"] = 5
    else:
        k = next(iter(ev["reward_stats"]["reward"]))
        ev["reward_stats"]["reward"]["1.0"] = ev["reward_stats"]["reward"].pop(k)
    (job / "result.json").write_text(json.dumps(J))
    bad = [r for r in ac.harbor_consistency(tmp_path) if r["consistent"] is False]
    assert bad and bad[0]["kind"] == "job", bad


def test_harbor_check_cannot_prove_a_coherent_forgery_is_fake(tmp_path):
    """Documented limit (anticheat.py docstring, EXPLOITS.md): the check catches files that DISAGREE. A forger who
    edits every copy the same way (accusation marked correct, score = V, reward.txt, result.json) passes."""
    job = _copy_job(tmp_path, "stop_early")
    t = next(p for p in job.iterdir() if p.is_dir())
    for f in ("artifacts/ledger.json", "verifier/ledger.json"):
        d = json.loads((t / f).read_text())
        ev = next(e for e in d["ledger"] if e["event"] == "accused")
        ev["detail"]["correct"] = True
        d.update(score=round(ev["detail"]["V"], 10), correct=True, accused_correct=True)
        (t / f).write_text(json.dumps(d))
    v = round(ev["detail"]["V"], 10)
    (t / "verifier/reward.txt").write_text(repr(v))
    if (t / "verifier/reward.json").is_file():
        (t / "verifier/reward.json").write_text(json.dumps({"reward": v}))
    out = (t / "verifier/test-stdout.txt").read_text()
    (t / "verifier/test-stdout.txt").write_text(out.replace("reward=-1.0", f"reward={v!r}"))
    r = json.loads((t / "result.json").read_text())
    r["verifier_result"]["rewards"]["reward"] = v
    (t / "result.json").write_text(json.dumps(r))
    assert ac.check_harbor_trial(t)["consistent"] is True


def test_fast_mode_rule_needs_statistical_evidence(monkeypatch):
    """5-19 seeds: a guesser that is right on 4 of 6 seeds by luck is not a failure (one-sided 95% lower bound
    <= 0), but a probe that is right on every seed (an exploit) still fails."""
    from tests.integrity_helpers import make_env, true_mole
    calls = {"n": 0}

    def lucky(env):
        calls["n"] += 1
        mole = true_mole(make_env(env.tier, env.seed))
        ids = [e for e in ac._ids(env) if e != mole]
        env.call("accuse", {"employee": mole if calls["n"] % 3 else ids[0]})
        return {}

    def always_right(env):
        env.call("accuse", {"employee": true_mole(make_env(env.tier, env.seed))})
        return {}

    monkeypatch.setattr(ac, "BASELINE_PROBES", ())
    monkeypatch.setattr(ac, "CUSTOM_PROBES", {"lucky": lucky, "always_right": always_right})
    b = ac.run_battery(["easy"], [0, 1, 2, 3, 4, 5])
    by = {r["probe"]: r for r in b["rows"]}
    assert by["lucky"]["mean"] > 0 and by["lucky"]["blocked"] is True, by["lucky"]
    assert by["always_right"]["blocked"] is False, by["always_right"]


def test_effort_ladder_stopping_early_and_guessing_never_pays():
    """The solver stopped at 25/50/75/90% of its calls, then accusing its best guess, scores below the full solver
    (medium, 20 dev seeds; this ladder CAN fail, unlike the no-accusation stop-early ladder)."""
    seeds = range(20)
    solver, cuts = [], {n: [] for n in ac.CUT_GUESS}
    for s in seeds:
        actions, sc = ac.solver_actions("medium", s)
        solver.append(sc)
        for n, v in ac.cut_guess_scores("medium", s, len(actions)).items():
            cuts[n].append(v)
    m = sum(solver) / len(solver)
    for n, v in cuts.items():
        assert sum(v) / len(v) < m, (n, sum(v) / len(v), m)


@pytest.mark.parametrize("ok,code", [(True, 0), (False, 1), (None, 0)])
def test_make_reproduce_exits_1_on_anti_cheat_failure(monkeypatch, tmp_path, ok, code):
    import canary.reproduce as R
    from canary import eval as E
    monkeypatch.setattr(R, "reproduce", lambda *a, **k: {"anticheat_ok": ok})
    assert E.main(["--reproduce", "--results-dir", str(tmp_path)]) == code


def test_only_secret_seed_episodes_are_not_replayable():
    """Backs the docs' wording 'every committed episode except the secret-keyed judge-seed ones re-plays'."""
    rows = ac.replay_committed(ROOT)
    assert all(not r.get("why") for r in rows if r["not_replayable"]), [r for r in rows if r.get("why")]
    assert all(r["replay_consistent"] is not False for r in rows)


def test_committed_public_secret_battery_artifact():
    """results/anticheat/exploits.json: the full 40-judge-seed battery under a PUBLIC test secret (exact, repeatable)."""
    p = ROOT / "results/anticheat/exploits.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d["all_blocked"] is True and d["replay_all_consistent"] is True and d["harbor_all_consistent"] is True
    assert d["world_secret_public"] and d["seeds"][2] == 40
    assert all(r["n"] == 40 for r in d["rows"])
    assert {r["kind"] for r in d["rows"]} >= {"attack", "sanity", "effort", "reference"}


# ----------------------------------------------------------------------------- round-2 judge findings
def test_garbage_args_reaches_every_tool(battery):
    """Each tool's garbage runs on its own fresh Env, so no tool's malformed calls are hidden behind an early end."""
    from canary.env import _SPECS
    for r in battery["rows"]:
        if r["probe"] == "garbage_args":
            assert r["extra"]["garbage_tools_unreached"] == 0, r
            assert r["extra"]["garbage_nonzero_scores"] == 0, r
            assert r["extra"]["garbage_tools"] == (len(_SPECS) + 1) * r["n"], r   # every tool + made-up names


def test_accusing_probes_really_accuse(battery):
    for r in battery["rows"]:
        if r["probe"] in ac.EXPECT_ACCUSE:
            assert r["extra"].get("accused", 0) == r["n"], r


def test_an_accusing_probe_that_never_accuses_fails(monkeypatch):
    monkeypatch.setattr(ac, "BASELINE_PROBES", ())
    monkeypatch.setattr(ac, "CUSTOM_PROBES", {"canary_per_person": lambda env: {}})   # tests nothing
    b = ac.run_battery(["easy"], [0, 1])
    row = next(r for r in b["rows"] if r["probe"] == "canary_per_person")
    assert row["blocked"] is False and b["all_blocked"] is False, row


def test_bad_canary_acceptance_fails_the_plus_probe(monkeypatch):
    real = ac._extra_calls

    def accepted_canary(name, ids, target):
        if name == "solver_plus_bad_canary":   # a canary the Env accepts: the probe must notice, not stay "blocked"
            return [("plant_canary", {"doc_title": "Q3 board memo", "assignment": {ids[0]: "a"}})]
        return real(name, ids, target)

    monkeypatch.setattr(ac, "_extra_calls", accepted_canary)
    monkeypatch.setattr(ac, "BASELINE_PROBES", ())
    monkeypatch.setattr(ac, "CUSTOM_PROBES", {})
    b = ac.run_battery(["easy"], [0, 1])
    row = next(r for r in b["rows"] if r["probe"] == "solver_plus_bad_canary")
    assert row["extra"]["extra_canary_accepted"] > 0 and row["blocked"] is False, row


def test_committed_artifact_reproduces_a_slice():
    """Recompute 2 judge seeds of the medium tier under the public test secret and compare every row's per-seed
    scores with the committed results/anticheat/exploits.json (not just its own pass flags)."""
    from canary import rules
    from canary.world import set_world_secret
    d = json.loads((ROOT / "results/anticheat/exploits.json").read_text(encoding="utf-8"))
    seeds = list(rules.JUDGE_SEEDS)[:2]
    set_world_secret(d["world_secret_public"].encode())
    try:
        b = ac.run_battery(["medium"], seeds)
    finally:
        set_world_secret(None)
    committed = {r["probe"]: r for r in d["rows"] if r["tier"] == "medium"}
    for r in b["rows"]:
        c = committed[r["probe"]]
        assert c["seeds"][:2] == seeds and c["scores"][:2] == r["scores"], (r["probe"], c["scores"][:2], r["scores"])


def test_cheat_probe_trial_without_its_report_is_flagged(tmp_path):
    job = _copy_job(tmp_path, "cheat-probe")
    t = next(p for p in job.iterdir() if p.is_dir())
    (t / "agent/cheat.json").unlink()
    row = ac.check_harbor_trial(t)
    assert row["consistent"] is False and any("cheat.json is missing" in p for p in row["problems"]), row


def test_published_retired_key_catches_an_edit_that_was_not_re_signed(tmp_path):
    """With the build's retired signing key published next to the job, a matching edit of every copy that was NOT
    re-signed is caught (see the next test for the limit)."""
    job = _copy_job(tmp_path, "cheat-probe")
    t = next(p for p in job.iterdir() if p.is_dir())
    assert ac.check_harbor_trial(t).get("hmac_verified") is True
    for f in ("artifacts/ledger.json", "verifier/ledger.json"):
        d = json.loads((t / f).read_text())
        d["final_day"] = 7                       # same edit everywhere: the files still agree with each other
        (t / f).write_text(json.dumps(d))
    row = ac.check_harbor_trial(t)
    assert row["consistent"] is False and any("HMAC" in p for p in row["problems"]), row


def test_replay_catches_a_tampered_step(tmp_path):
    src = next(f for f in sorted((ROOT / "data/runs/committed").glob("v1.3/reference/solver-medium-*/episodes.jsonl")))
    dst = tmp_path / "data/runs/committed/v1.3/fake/medium"
    dst.mkdir(parents=True)
    e = json.loads(src.read_text().splitlines()[0])
    e["steps"][1]["result"] = {"ok": True, "data": {"note": "edited"}, "error": None}   # score and accused untouched
    (dst / "episodes.jsonl").write_text(json.dumps(e) + "\n")
    (dst / "meta.json").write_text(json.dumps({"tiers_version": "v1.3"}))
    rows = ac.replay_committed(tmp_path)
    assert rows[0]["replay_consistent"] is False and rows[0]["step_mismatches"] >= 1, rows[0]


def test_every_committed_step_replays_identically():
    c = ac.replay_counts(ac.replay_committed(ROOT))
    assert c["steps"] > 10_000 and c["step_mismatches"] == 0, c


def test_build_refuses_shared_mode_without_the_explicit_flag(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("harbor_build", ROOT / "harbor/build.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    with pytest.raises(SystemExit):
        build.main(["--tiers", "hard", "--seeds", "900000", "--out", str(tmp_path), "--verifier", "shared"])


# ----------------------------------------------------------------------------- round-3 judge findings
def _forge_signed_trial_to_correct(t, key: bytes):
    """Rewrite a signed stop_early trial from a wrong accusation (-1) into a correct one, re-signed with the key."""
    import hashlib
    import hmac as _hmac
    for f in ("artifacts/ledger.json", "verifier/ledger.json"):
        d = json.loads((t / f).read_text())
        ev = next(e for e in d["ledger"] if e["event"] == "accused")
        ev["detail"]["correct"] = True
        d.update(score=round(ev["detail"]["V"], 10), correct=True, accused_correct=True)
        body = {k: v for k, v in d.items() if k != "sig"}
        d["sig"]["mac"] = _hmac.new(key, json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
                                    .encode(), hashlib.sha256).hexdigest()
        (t / f).write_text(json.dumps(d))
    v = d["score"]
    (t / "verifier/reward.txt").write_text(repr(v))
    (t / "verifier/reward.json").write_text(json.dumps({"reward": v}))
    out = (t / "verifier/test-stdout.txt").read_text()
    (t / "verifier/test-stdout.txt").write_text(out.replace("reward=-1.0", f"reward={v!r}"))
    r = json.loads((t / "result.json").read_text())
    r["verifier_result"]["rewards"]["reward"] = v
    (t / "result.json").write_text(json.dumps(r))


def test_published_key_cannot_catch_a_re_signed_forgery(tmp_path):
    """Documented limit (EXPLOITS.md, harbor_md): once a build's key is public, a forger can re-sign. A trial rewritten
    from -1 to a correct accusation, re-signed and edited everywhere, passes the trial check."""
    job = _copy_job(tmp_path, "signed-stop_early")
    t = next(p for p in job.iterdir() if p.is_dir())
    _forge_signed_trial_to_correct(t, (job / "ledger_key").read_text().strip().encode())
    row = ac.check_harbor_trial(t)
    assert row["consistent"] is True and row["hmac_verified"] is True, row


@pytest.mark.parametrize("where", ["reward.json", "test-stdout"])
def test_harbor_check_compares_every_printed_reward(tmp_path, where):
    job = _copy_job(tmp_path, "signed-stop_early")
    t = next(p for p in job.iterdir() if p.is_dir())
    if where == "reward.json":
        (t / "verifier/reward.json").write_text('{"reward": 1.0}')
    else:
        out = (t / "verifier/test-stdout.txt").read_text()
        (t / "verifier/test-stdout.txt").write_text(out.replace("reward=-1.0", "reward=1.0"))
    row = ac.check_harbor_trial(t)
    assert row["consistent"] is False, row


def test_probe_trial_without_a_reward_is_not_waved_through(tmp_path):
    """A cheat_probe trial that lost its verifier reward is not 'infrastructure': it is flagged, holes or not."""
    job = _copy_job(tmp_path, "cheat-probe")
    t = next(p for p in job.iterdir() if p.is_dir())
    r = json.loads((t / "result.json").read_text())
    r["verifier_result"] = None
    (t / "result.json").write_text(json.dumps(r))
    rep = json.loads((t / "agent/cheat.json").read_text())
    rep["holes"] = ["secrets.file[/run/canary/ledger_token]"]
    (t / "agent/cheat.json").write_text(json.dumps(rep))
    row = ac.check_harbor_trial(t)
    assert row["consistent"] is False and any("holes" in p for p in row["problems"]), row


def test_verify_artifact_reruns_and_diffs(tmp_path, capsys):
    """`make anticheat-verify` in miniature: a 2-seed artifact under the public secret verifies; one edited number fails."""
    from canary import rules
    from canary.world import set_world_secret
    secret = "canary-anticheat-public-test-v1"
    set_world_secret(secret.encode())
    try:
        ac.run_and_write(["medium"], list(rules.JUDGE_SEEDS)[:2], tmp_path, replay=False, quiet=True,
                         extra={"world_secret_public": secret})
    finally:
        set_world_secret(None)
    p = tmp_path / "exploits.json"
    assert ac.verify_artifact(p) == 0
    d = json.loads(p.read_text())
    d["rows"][0]["mean"] = 0.5
    p.write_text(json.dumps(d))
    assert ac.verify_artifact(p) == 1
    assert "differences" in capsys.readouterr().out


def test_two_lucky_guesses_are_not_judged(monkeypatch):
    """CI found this: with 2 seeds, a guess that happens to be right twice has zero spread, and a naive lower bound
    called it an exploit. Under 5 seeds a chance-based attack row is reported (blocked None), never failed."""
    from tests.integrity_helpers import make_env, true_mole

    def right_twice(env):
        env.call("accuse", {"employee": true_mole(make_env(env.tier, env.seed))})
        return {}

    monkeypatch.setattr(ac, "BASELINE_PROBES", ())
    monkeypatch.setattr(ac, "CUSTOM_PROBES", {"right_twice": right_twice})
    b = ac.run_battery(["easy"], [0, 1])
    row = next(r for r in b["rows"] if r["probe"] == "right_twice")
    assert row["mean"] > 0 and row["blocked"] is None and b["all_blocked"] is True, row
