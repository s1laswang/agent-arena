"""Zero-API tests: the resumable Gemini driver's infra classification, and the replay verifier."""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT / "scripts"))
    spec.loader.exec_module(mod)
    return mod


def test_infra_reason_classes(tmp_path):
    gr = _load("gemini_runner")
    ok = {"end_reason": "accused", "meta": {"rc": 0}}
    assert gr.infra_reason("opencode", tmp_path, ok) is None
    assert gr.infra_reason("opencode", tmp_path, {"end_reason": "error", "meta": {"rc": 0}}) is None  # agent stopped: valid 0
    assert gr.infra_reason("opencode", tmp_path, {"end_reason": "error", "meta": {"error": "infra:provider_rate_limit",
                                                                                     "valid": False}}).startswith("invalid")
    assert gr.infra_reason("opencode", tmp_path, {"end_reason": "error", "meta": {"rc": "timeout"}}) == "timeout"
    assert gr.infra_reason("inproc", tmp_path, {"end_reason": "error", "meta": {"error": "ClientError('429 RESOURCE_EXHAUSTED')"}})
    assert gr.infra_reason("inproc", tmp_path, {"end_reason": "horizon", "meta": {}}) is None
    assert gr.RATE.search("api: ClientError 429 RESOURCE_EXHAUSTED")
    j = gr.Job("opencode", "hard", 3, tmp_path, "gemini-4-carbon", 3600)
    assert "google/gemini-4-carbon" in j.cmd() and "--retries" in j.cmd()
    assert "gemini:gemini-4-carbon" in gr.Job("inproc", "hard", 3, tmp_path, "gemini-4-carbon", 3600).cmd()


def test_verify_replay_matches_solver_episode(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_ALLOW_DEV", "1")
    import dataclasses
    from canary.agents.loop import run_episode
    from canary.baselines import Heuristic
    from canary.env import Env
    vr = _load("verify_replay")
    res = run_episode(Env("medium", 0), Heuristic(), "heuristic")
    f = tmp_path / "episodes.jsonl"
    f.write_text(json.dumps(dataclasses.asdict(res), default=str) + "\n")
    assert vr.main([str(f)]) == 0
    e = json.loads(f.read_text())
    e["score"] += 0.5
    f.write_text(json.dumps(e) + "\n")
    assert vr.main([str(f)]) == 1
