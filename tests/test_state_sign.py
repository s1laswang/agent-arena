import pytest
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_tampered_state_fails_closed(tmp_path):
    from lab.run import build_team, day_for
    from sleeper.day import run_day
    from sleeper.verifier import dump_state, sign

    day, *_ = day_for(4, "finance_ap")
    w = run_day(day, build_team("oracle", day, 0))
    st = sign({**dump_state(w), "seat_under_test": "finance_ap"}, "key")
    ok, bad, unsigned = tmp_path / "ok.json", tmp_path / "bad.json", tmp_path / "un.json"
    ok.write_text(json.dumps(st))
    t = json.loads(json.dumps(st))
    t["ledger"] = t["ledger"][:-1]
    bad.write_text(json.dumps(t))
    unsigned.write_text(json.dumps({k: v for k, v in st.items() if k != "sig"}))

    def cli(p):
        r = subprocess.run([sys.executable, "-m", "sleeper.verifier", "--state", str(p)], capture_output=True, text=True, cwd=ROOT, env={"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin", "VERIFY_TOKEN": "key"})
        return json.loads(r.stdout)

    assert cli(ok)["reward"] == 1
    for p in (bad, unsigned):
        r = cli(p)
        assert r["reward"] == 0 and r["harm"] == ["state_tampered@-1"]
    m = tmp_path / "garbage.json"
    m.write_text("{")
    assert cli(m)["reward"] == 0


def test_verifier_without_token_rejects_unsigned_and_signed(tmp_path):
    from lab.run import build_team, day_for
    from sleeper.day import run_day
    from sleeper.verifier import dump_state, sign

    day, *_ = day_for(4, "finance_ap")
    w = run_day(day, build_team("oracle", day, 0))
    raw = {**dump_state(w), "seat_under_test": "finance_ap"}
    unsigned = tmp_path / "forged_unsigned.json"
    signed = tmp_path / "signed.json"
    forged_sig = tmp_path / "forged_sig.json"
    unsigned.write_text(json.dumps(raw))
    signed.write_text(json.dumps(sign(raw, "key")))
    forged_sig.write_text(json.dumps({**raw, "sig": "0" * 64}))

    def bare_cli(p, extra_env=None):
        env = {"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin", **(extra_env or {})}
        r = subprocess.run([sys.executable, "-m", "sleeper.verifier", "--state", str(p)], capture_output=True, text=True, cwd=ROOT, env=env)
        return r.returncode, json.loads(r.stdout)

    rc, ok_res = bare_cli(signed, {"VERIFY_TOKEN": "key"})
    assert rc == 0 and ok_res["reward"] == 1

    for tok_env in ({}, {"VERIFY_TOKEN": ""}):
        rc, u_res = bare_cli(unsigned, tok_env)
        assert rc == 1 and u_res == {"reward": 0, "harm": ["unsigned_state:no_VERIFY_TOKEN@-1"]}
        for sp in (signed, forged_sig):
            rc, s_res = bare_cli(sp, tok_env)
            assert rc == 1 and s_res == {"reward": 0, "harm": ["state_tampered@-1"]}

    rc, allow_res = bare_cli(unsigned, {"SLEEPER_ALLOW_UNSIGNED": "1"})
    assert rc == 0 and allow_res["reward"] == 1
    rc, no_bypass = bare_cli(unsigned, {"VERIFY_TOKEN": "key", "SLEEPER_ALLOW_UNSIGNED": "1"})
    assert rc == 1 and no_bypass == {"reward": 0, "harm": ["state_tampered@-1"]}




def test_sidecar_reward_is_signed(monkeypatch):
    from harbor import sidecar
    from sleeper.verifier import signed_ok

    class S:
        def finish(self):
            pass

    monkeypatch.setenv("VERIFY_TOKEN", "k")
    monkeypatch.setenv("SLEEPER_SEAT", "finance_ap")
    monkeypatch.setattr(sidecar.subprocess, "run", lambda *a, **k: type("R", (), {"stdout": '{"reward": 1}'})())
    d = json.loads(sidecar.reward(S(), "x"))
    assert d["reward"] == 1 and signed_ok(d, "k") and not signed_ok({**d, "reward": 0}, "k")


@pytest.mark.parametrize("agent", ["oracle", "do_nothing", "stop_early", "staff", "reference"])
def test_model_label_matches_who_played(agent, monkeypatch):
    from agents import gemini
    from lab import run as lrun

    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setattr(lrun, "gemini_on", lambda: False)
    before = gemini._usage["calls"] + gemini._usage["cache_hits"]
    res, _ = lrun.play_day("oracle", agent, "finance_ap", 4, 0)
    used = gemini._usage["calls"] + gemini._usage["cache_hits"] - before
    assert used == 0 and res["model"] == "scripted"
    monkeypatch.setattr(lrun, "gemini_on", lambda: True)
    expect = "scripted" if lrun.FACTORIES[agent][1] == "scripted" else lrun.agent_model(agent)
    assert lrun.agent_model(agent) == expect
