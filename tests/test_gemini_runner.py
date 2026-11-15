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
    # our-side timeout counts as played (never retried)
    assert gr.infra_reason("opencode", tmp_path, {"end_reason": "error", "meta": {"rc": "timeout"}}) is None
    # empty final model reply (0 output tokens, finish=stop) -> infra-invalid, retried
    (tmp_path / "transcripts").mkdir()
    fin = lambda reason, out: json.dumps({"type": "step_finish", "part": {  # noqa: E731
        "type": "step-finish", "reason": reason, "tokens": {"input": 10, "output": out, "reasoning": 0}}})
    (tmp_path / "transcripts" / "7.txt").write_text(fin("tool-calls", 30) + "\n" + fin("stop", 0) + "\n")
    ep7 = {"seed": 7, "end_reason": "error", "meta": {"rc": 0}}
    assert "empty_model_response" in gr.infra_reason("opencode", tmp_path, ep7)
    start = json.dumps({"type": "step_start", "part": {"type": "step-start"}})
    text = json.dumps({"type": "text", "part": {"type": "text", "text": "I have enough; stopping here."}})
    # a few output tokens but nothing visible (no text, no tool call) -> still an empty reply
    (tmp_path / "transcripts" / "7.txt").write_text("\n".join([start, fin("tool-calls", 30), start, fin("stop", 44)]))
    assert "output_tokens=44" in gr.infra_reason("opencode", tmp_path, ep7)
    (tmp_path / "transcripts" / "7.txt").write_text("\n".join([start, fin("tool-calls", 30), start, text, fin("stop", 12)]))
    assert gr.infra_reason("opencode", tmp_path, ep7) is None        # the agent wrote a reply and stopped: played, 0
    from canary.agents.frontier.common import classify_infra
    assert classify_infra(fin("stop", 0), "") == "empty_model_response"
    assert classify_infra(start + "\n" + text + "\n" + fin("stop", 5), "") is None
    assert gr.infra_reason("inproc", tmp_path, {"end_reason": "error", "meta": {"error": "ClientError('429 RESOURCE_EXHAUSTED')"}})
    assert gr.infra_reason("inproc", tmp_path, {"end_reason": "horizon", "meta": {}}) is None
    assert gr.RATE.search("api: ClientError 429 RESOURCE_EXHAUSTED")
    assert gr.RATE.search("invalid: infra:provider_quota") and gr.RATE.search("invalid: infra:provider_rate_limit")
    j = gr.Job("opencode", "hard", 3, tmp_path, "gemini-4-carbon", 3600)
    assert "google/gemini-4-carbon" in j.cmd() and "--retries" in j.cmd()
    assert "gemini:gemini-4-carbon" in gr.Job("inproc", "hard", 3, tmp_path, "gemini-4-carbon", 3600).cmd()


def test_tiers_override_wraps_children(tmp_path, monkeypatch):
    gr = _load("gemini_runner")
    monkeypatch.setenv("CANARY_TIERS_OVERRIDE", "v1.3")
    cmd = gr.Job("opencode", "hard", 3, tmp_path, "gemini-4-carbon", 3600).cmd()
    i = cmd.index("scripts/with_tiers.py")
    assert cmd[i + 1] == "v1.3" and cmd[i + 2] == "-m" and cmd[i + 3] == "canary.agents.frontier.opencode_run"


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
