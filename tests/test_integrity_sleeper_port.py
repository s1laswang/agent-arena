"""Canary-specific attacks ported from the Sleeper red team (owner: rw-exploit). Offline, no model calls."""
from __future__ import annotations

import concurrent.futures as cf

import pytest

from canary.mcp_server import Episode, build_app
from tests.integrity_helpers import make_env, true_mole

pytestmark = pytest.mark.usefixtures("allow_dev")


@pytest.fixture
def allow_dev(monkeypatch):
    monkeypatch.setenv("CANARY_ALLOW_DEV", "1")


def ids(env):
    return [e["id"] for e in env.call("list_employees", {}).data["employees"]]


def wrong(env):
    return float(env.p.wrong_accusation_score)


def spam_to_cap(env):
    while not env.done:
        env.call("status", {})


@pytest.mark.parametrize("tier", ["easy", "medium"])
def test_accuse_after_cap_end_scores_zero(tier):
    env = make_env(tier, 3)
    spam_to_cap(env)
    assert env._end_reason == "tool_cap"
    r = env.call("accuse", {"employee": true_mole(env)})
    assert not r.ok and r.error == "episode over"
    assert env.score() == 0.0


def test_accuse_on_the_last_allowed_call_still_counts():
    env = make_env("easy", 3)
    for _ in range(env.p.tool_call_cap - 1):
        env.call("status", {})
    assert not env.done
    r = env.call("accuse", {"employee": true_mole(env)})
    assert r.ok and env.score() == pytest.approx(env.V)
    assert env._end_reason != "tool_cap"


@pytest.mark.parametrize("bad", ["e99", "e12", "e-1", "e00 ", " e00", "e00\n", "e00​", "е" + "00", "e0", "e000", "E00", "e00\x00",
                                 "x" * 100000, 0, 1, True, False, 1.5, ["e00"], {"employee": "e00"}, None])
def test_foreign_and_lookalike_ids_rejected_without_locking(bad):
    env = make_env("easy", 4)
    mole = true_mole(env)
    n, V = len(env.history), env.V
    r = env.call("accuse", {"employee": bad})
    assert not r.ok and not env.done and env.score() == 0.0 and env.V == V
    assert sum(1 for e in env.ledger() if e.event == "accused") == 0
    assert env.call("accuse", {"employee": mole}).ok and env.score() > 0
    assert len(env.history) == n + 2


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_accuse_every_person_one_world_per_person(seed):
    base = make_env("easy", seed)
    mole = true_mole(base)
    results = {}
    for p in ids(base):
        env = make_env("easy", seed)
        r = env.call("accuse", {"employee": p})
        results[p] = (r.ok, r.error, {k: v for k, v in r.data.items() if k != "accused"}, env.score())
    assert len({(a, b, str(c)) for a, b, c, _ in results.values()}) == 1
    pos = [p for p, v in results.items() if v[3] > 0]
    assert pos == [mole]
    assert all(v[3] == wrong(base) for p, v in results.items() if p != mole)


def test_parallel_accuse_everyone_in_one_episode():
    ep = Episode("easy", 5)
    people = ids(ep.env)
    with cf.ThreadPoolExecutor(len(people)) as ex:
        res = list(ex.map(lambda p: ep.call("accuse", {"employee": p}), people))
    assert sum(1 for r in res if r.ok) == 1
    assert sum(1 for e in ep.env.ledger() if e.event == "accused") == 1
    assert ep.env.score() in (pytest.approx(ep.env.V), wrong(ep.env))


@pytest.mark.parametrize("tool", ["accuse", "restrict_access", "interview", "plant_canary", "list_documents", "read_access_logs",
                                  "search_messages", "read_message", "check_leak_feed", "advance_day", "status"])
@pytest.mark.parametrize("args", [[], None, "x", 3, {"employee": {"a": 1}}, {"day_from": "x", "day_to": None}, {"day_from": -10 ** 9, "day_to": 10 ** 9},
                                  {"assignment": [1], "doc_title": "x"}, {"query": None}, {"id": ["m1"]}])
def test_crashing_args_never_mutate_state_or_dodge_the_cap(tool, args):
    ep = Episode("easy", 6)
    e = ep.env
    before = (e.V, len(e.ledger()), e.day, len(e.history), e.done)
    r = ep.call(tool, args)
    if not r.ok:
        assert (e.V, len(e.ledger()), e.day, e.done) == before[:3] + (before[4],) or r.error == "daily action limit; call advance_day"
        assert len(e.history) == before[3] + 1, "a rejected call must still count toward the tool cap"


def test_ledger_and_admin_routes_closed_to_the_agent():
    from starlette.testclient import TestClient

    ep = Episode("easy", 7)
    c = TestClient(build_app(ep, ledger_token="a" * 64, admin_token=None))
    for url in ("/ledger", "/ledger?token=", "/ledger?token=x", "/ledger?token=" + "a" * 63):
        assert c.get(url).status_code == 403, url
    for url in ("/admin/reset", "/admin/reset?token=", "/admin/reset?token=a"):
        assert c.post(url, json={"tier": "easy", "seed": 900000}).status_code == 403
    assert c.get("/ledger?token=" + "a" * 64).status_code == 200
    assert c.get("/healthz").json() == {"ok": True}


def test_ledger_without_token_config_is_always_403():
    from starlette.testclient import TestClient

    c = TestClient(build_app(Episode("easy", 7), ledger_token=None, admin_token=None))
    assert c.get("/ledger").status_code == 403 and c.get("/ledger?token=None").status_code == 403


def nocomment(path):
    return "\n".join(l for l in path.read_text().splitlines() if not l.lstrip().startswith("#"))


@pytest.fixture(scope="module")
def harbor_task(tmp_path_factory):
    import subprocess, sys
    out = tmp_path_factory.mktemp("ds")
    r = subprocess.run([sys.executable, "harbor/build.py", "--tiers", "easy", "--seeds", "900000", "--out", str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return next(out.glob("canary-*"))


def test_harbor_agent_side_has_no_secret(harbor_task):
    salt = (harbor_task / "environment/canary-server/data/worlds/judge/SALT").read_text().strip()
    seed = "900000"
    for f in harbor_task.rglob("*"):
        if not f.is_file() or "canary-server" in f.relative_to(harbor_task).parts or f.parts[-2] == "solution":
            continue
        t = f.read_text(errors="ignore")
        assert salt not in t, f
    main = nocomment(harbor_task / "environment/Dockerfile") + (harbor_task / "environment/opencode.json").read_text()
    assert seed not in main and "SALT" not in main and "COPY canary" not in main
    assert "canary-server" in (harbor_task / "environment/.dockerignore").read_text()


def test_harbor_compose_has_no_shared_namespace_or_volume(harbor_task):
    c = nocomment(harbor_task / "environment/docker-compose.yaml")
    for bad in ("pid:", "volumes:", "docker.sock", "privileged", "network_mode", "cap_add", "ports:"):
        assert bad not in c, bad


def test_harbor_verifier_reward_only_from_ledger(harbor_task):
    sh = (harbor_task / "tests/test.sh").read_text()
    assert "is_symlink()" in sh and "-1.0 <= score <= 1.0" in sh
    assert "/agent" not in sh and "/app" not in sh


@pytest.mark.xfail(strict=True, reason="FINDING: sidecar receives GEMINI_API_KEY (compose passes the host key into the game server); no path to main found, but least privilege says the template provider needs no key")
def test_harbor_sidecar_gets_no_model_key(harbor_task):
    assert "GEMINI_API_KEY" not in nocomment(harbor_task / "environment/docker-compose.yaml")
