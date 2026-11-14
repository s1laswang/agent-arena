"""Ledger signing (PLAN-95 C1, defence in depth; HARNESS).

The canary-server sidecar HMAC-SHA256-signs every /ledger payload with a build-time key that only the sidecar
image and the separate verifier image hold. harbor/template/tests/test.sh must fail closed (reward 0 plus a FAIL
line) on a missing or bad signature, a missing key, or a score outside {-1, 0} U (0, 1], and must pass a valid
signed ledger through unchanged. These tests run the verifier's real Python (extracted from test.sh) against
ledgers signed by canary.mcp_server.sign_ledger and by a real server process, and check what build.py writes.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from canary.mcp_server import sign_ledger, verify_ledger

ROOT = Path(__file__).resolve().parent.parent
KEY = "ab" * 32
LEDGER = {"score": 0.66, "done": True, "end_reason": "accused", "accused": "e07", "final_day": 9, "V": 0.66,
          "tier": "hard", "episode": "0123456789abcdef",
          "ledger": [{"t": 41, "day": 9, "event": "accused", "detail": {"employee": "e07"}}]}


def _verifier_src(tmp: Path) -> str:
    sh = (ROOT / "harbor/template/tests/test.sh").read_text()
    py = re.search(r"python3 - <<'PY'\n(.*?)\nPY", sh, re.S).group(1)
    return (py.replace("/logs/verifier", (tmp / "logs").as_posix())
              .replace("/evidence", (tmp / "evidence").as_posix())
              .replace("/tests/ledger_key", (tmp / "tests/ledger_key").as_posix()))


def run_verifier(tmp: Path, ledger, key: str | None = KEY, env_key: str | None = None):
    """Run test.sh's Python. `ledger`: dict (dumped), str (raw) or None (no evidence). Returns (rc, reward, out)."""
    for d in ("logs", "evidence", "tests"):
        (tmp / d).mkdir(exist_ok=True)
    if key is not None:
        (tmp / "tests/ledger_key").write_text(key + "\n")
    if ledger is not None:
        (tmp / "evidence/ledger.json").write_text(ledger if isinstance(ledger, str) else json.dumps(ledger))
    env = {k: v for k, v in os.environ.items() if k not in ("CANARY_LEDGER_TOKEN", "CANARY_LEDGER_KEY")}
    if env_key is not None:
        env["CANARY_LEDGER_KEY"] = env_key
    p = subprocess.run([sys.executable, "-c", _verifier_src(tmp)], capture_output=True, text=True, env=env, timeout=60)
    return p.returncode, (tmp / "logs/reward.txt").read_text(), p.stdout + p.stderr


def _fails_closed(rc, reward, out):
    assert rc != 0 and reward == "0" and "FAIL:" in out, (rc, reward, out)


# ----------------------------------------------------------------------------- signer
def test_sign_and_verify_roundtrip():
    s = sign_ledger(LEDGER, KEY)
    assert s["sig"]["alg"] == "HMAC-SHA256" and len(s["sig"]["mac"]) == 64
    assert {k: v for k, v in s.items() if k != "sig"} == LEDGER
    assert verify_ledger(s, KEY) and verify_ledger(json.loads(json.dumps(s)), KEY)   # survives a JSON round trip
    assert sign_ledger(s, KEY) == s                                                  # re-signing is idempotent
    assert not verify_ledger(s, "cd" * 32)
    assert not verify_ledger({**s, "score": 1.0}, KEY)
    assert not verify_ledger(LEDGER, KEY) and not verify_ledger(s, "") and not verify_ledger([s], KEY)


# ----------------------------------------------------------------------------- verifier: valid -> unchanged
@pytest.mark.parametrize("score", [0.66, 1.0, 0.0, -1.0, 0.0001, 1])
def test_valid_signed_ledger_passes_through(tmp_path, score):
    led = sign_ledger({**LEDGER, "score": score}, KEY)
    rc, reward, out = run_verifier(tmp_path, led)
    assert rc == 0, out
    assert float(reward) == float(score) and "signature=ok" in out
    assert json.loads((tmp_path / "logs/ledger.json").read_text()) == led


def test_shared_verifier_key_from_env(tmp_path):
    rc, reward, out = run_verifier(tmp_path, sign_ledger(LEDGER, KEY), key=None, env_key=KEY)
    assert rc == 0 and float(reward) == 0.66, out


def test_env_key_wins_over_a_planted_key_file(tmp_path):
    """Shared verifier: /tests is in the agent's container, so a key file there must not override [verifier].env."""
    forged = sign_ledger({**LEDGER, "score": 1.0}, "agent-chosen-key")
    _fails_closed(*run_verifier(tmp_path, forged, key="agent-chosen-key", env_key=KEY))


# ----------------------------------------------------------------------------- verifier: fail closed
def test_forged_score_scores_zero(tmp_path):
    led = sign_ledger(LEDGER, KEY)
    led["score"] = 1.0
    _fails_closed(*run_verifier(tmp_path, led))


@pytest.mark.parametrize("field,value", [("accused", "e00"), ("end_reason", "horizon"), ("V", 1.0), ("done", False),
                                         ("ledger", []), ("extra", "x")])
def test_tampered_field_scores_zero(tmp_path, field, value):
    led = sign_ledger(LEDGER, KEY)
    led[field] = value
    _fails_closed(*run_verifier(tmp_path, led))


def test_tampered_nested_event_scores_zero(tmp_path):
    led = sign_ledger(LEDGER, KEY)
    led["ledger"][0]["detail"]["employee"] = "e01"
    _fails_closed(*run_verifier(tmp_path, led))


@pytest.mark.parametrize("sig", [None, {}, {"alg": "HMAC-SHA256"}, {"alg": "none", "mac": ""}, "deadbeef",
                                 {"alg": "HMAC-SHA256", "mac": "0" * 64}, {"alg": "HMAC-SHA256", "mac": 0}])
def test_missing_or_bad_signature_scores_zero(tmp_path, sig):
    led = dict(LEDGER) if sig is None else {**LEDGER, "sig": sig}
    _fails_closed(*run_verifier(tmp_path, led))


def test_signed_with_another_key_scores_zero(tmp_path):
    _fails_closed(*run_verifier(tmp_path, sign_ledger(LEDGER, "cd" * 32)))


@pytest.mark.parametrize("key", [None, ""])
def test_missing_key_scores_zero(tmp_path, key):
    _fails_closed(*run_verifier(tmp_path, sign_ledger(LEDGER, KEY), key=key))


def test_symlinked_key_is_ignored(tmp_path):
    (tmp_path / "tests").mkdir()
    real = tmp_path / "k"
    real.write_text(KEY)
    try:
        (tmp_path / "tests/ledger_key").symlink_to(real)
    except OSError:
        pytest.skip("symlinks not allowed here")
    _fails_closed(*run_verifier(tmp_path, sign_ledger(LEDGER, KEY), key=None))


@pytest.mark.parametrize("score", [-0.5, -1.0000001, 1.0000001, 2, -2, 1e309, float("nan"), "1.0", None, True, [1]])
def test_signed_score_outside_range_scores_zero(tmp_path, score):
    """Even a validly signed ledger must carry a score in {-1, 0} U (0, 1]."""
    _fails_closed(*run_verifier(tmp_path, sign_ledger({**LEDGER, "score": score}, KEY)))


@pytest.mark.parametrize("raw", ["", "not json", "[1, 2]", "null"])
def test_garbage_scores_zero(tmp_path, raw):
    _fails_closed(*run_verifier(tmp_path, raw))


def test_no_evidence_scores_zero(tmp_path):
    _fails_closed(*run_verifier(tmp_path, None))


# ----------------------------------------------------------------------------- real server -> verifier
def _free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get(url: str):
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, ""


def _file(tmp: Path, name: str, text: str) -> str:
    f = tmp / name
    f.write_text(text)
    f.chmod(0o600)
    return str(f)


@pytest.mark.parametrize("policy", ["solver", "do_nothing", "stop_early"])
def test_real_server_signs_and_verifier_reproduces_score(tmp_path, policy):
    """Server with CANARY_LEDGER_KEY_FILE -> GET /ledger -> test.sh: reward = the in-process score, bit for bit."""
    from canary.env import Env
    from canary.eval import make_policy_factory, run_episode
    from canary.mcp_server import play_policy

    tier, seed, token = "hard", 3, "tok-" + "1" * 16
    env = {k: v for k, v in os.environ.items() if not k.startswith("CANARY_")}
    port = _free_port()
    env.update(CANARY_HOST="127.0.0.1", CANARY_PORT=str(port), CANARY_ALLOW_DEV="1",
               CANARY_EPISODE_FILE=_file(tmp_path, "ep.json", json.dumps({"tier": tier, "seed": seed})),
               CANARY_LEDGER_TOKEN_FILE=_file(tmp_path, "tok", token),
               CANARY_LEDGER_KEY_FILE=_file(tmp_path, "lk", KEY + "\n"))
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
        asyncio.run(play_policy(base + "/mcp", make_policy_factory(policy)(0)))
        code, raw = _get(f"{base}/ledger?token={token}")
        assert code == 200
    finally:
        proc.terminate()
        log = proc.communicate(timeout=10)[0]
    led = json.loads(raw)
    assert verify_ledger(led, KEY), led.get("sig")
    local = run_episode(Env(tier, seed), make_policy_factory(policy)(0))
    (tmp_path / "v").mkdir()
    rc, reward, out = run_verifier(tmp_path / "v", raw)
    assert rc == 0, out
    assert float(reward) == led["score"] == local.score
    if policy == "do_nothing":
        assert float(reward) == 0.0
    assert KEY not in log and token not in log and "HMAC-SHA256" in log


def test_server_without_key_serves_unsigned_and_verifier_refuses(tmp_path):
    from canary.mcp_server import Episode, build_app
    from starlette.testclient import TestClient

    ep = Episode("easy", 0, "template")
    with TestClient(build_app(ep, ledger_token="t")) as c:
        unsigned = c.get("/ledger?token=t").json()
    with TestClient(build_app(ep, ledger_token="t", ledger_key=KEY)) as c:
        signed = c.get("/ledger?token=t").json()
        assert c.get("/ledger").status_code == 403
    assert "sig" not in unsigned and verify_ledger(signed, KEY)
    _fails_closed(*run_verifier(tmp_path, unsigned))


# ----------------------------------------------------------------------------- build.py
def _build_mod():
    spec = importlib.util.spec_from_file_location("harbor_build", ROOT / "harbor/build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mode(p: Path) -> int:
    return stat.S_IMODE(p.stat().st_mode)


def test_build_writes_key_only_to_sidecar_and_verifier(tmp_path):
    assert _build_mod().main(["--tiers", "hard", "--seeds", "900000,900001", "--out", str(tmp_path)]) == 0
    tasks = sorted(tmp_path.glob("canary-*"))
    assert [t.name for t in tasks] == ["canary-hard-900000", "canary-hard-900001"]
    keys = set()
    for t in tasks:
        side, ver = t / "environment/canary-server/ledger_key", t / "tests/ledger_key"
        assert side.read_bytes() == ver.read_bytes() and len(side.read_bytes()) == 64
        assert _mode(side) == _mode(ver) == 0o600
        keys.add(side.read_bytes())
        # nowhere else: not in the agent image's context (environment/ minus canary-server/), not in solution/
        hits = [p.relative_to(t).as_posix() for p in t.rglob("*") if p.is_file() and side.read_bytes() in p.read_bytes()]
        assert sorted(hits) == ["environment/canary-server/ledger_key", "tests/ledger_key"], hits
        assert "canary-server/" in (t / "environment/.dockerignore").read_text()
        assert "CANARY_LEDGER_KEY_FILE" in (t / "environment/docker-compose.yaml").read_text()
        assert "ledger_key" in (t / "environment/canary-server/Dockerfile").read_text()
        assert "chmod 0600 /tests/ledger_key" in (t / "tests/Dockerfile").read_text()
        assert "CANARY_LEDGER_KEY" not in (t / "task.toml").read_text()      # separate verifier: no env copy
    assert len(keys) == 1   # one key per build


def test_build_shared_verifier_passes_key_via_verifier_env(tmp_path):
    assert _build_mod().main(["--tiers", "hard", "--seeds", "900000", "--out", str(tmp_path), "--verifier", "shared"]) == 0
    t = tmp_path / "canary-hard-900000"
    key = (t / "environment/canary-server/ledger_key").read_text()
    assert not (t / "tests/ledger_key").exists() and not (t / "tests/Dockerfile").exists()
    import tomllib
    cfg = tomllib.loads((t / "task.toml").read_text())
    assert cfg["verifier"]["env"]["CANARY_LEDGER_KEY"] == key
    assert key not in (t / "environment/docker-compose.yaml").read_text()


def test_build_rebuild_draws_a_new_key(tmp_path):
    b = _build_mod()
    b.main(["--tiers", "hard", "--seeds", "900000", "--out", str(tmp_path / "a")])
    b.main(["--tiers", "hard", "--seeds", "900000", "--out", str(tmp_path / "b")])
    k = lambda d: (tmp_path / d / "canary-hard-900000/tests/ledger_key").read_bytes()  # noqa: E731
    assert k("a") != k("b")
