from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

from canary.agents.frontier.common import Server
from canary.llm.stub import StubClient
from canary.text.template import TemplateProvider
from canary.types import EpisodeResult, Step
from fake_env import FakeEnv
from scripts import v16_eval_matrix as V16


def test_common_server_passes_canary_provider(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured_envs: list[dict[str, str]] = []

    class DummyProc:
        pid = 12345

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            return None

        def wait(self, timeout: float = 1.0) -> int:
            return 0

    def fake_popen(cmd: Any, cwd: Any = None, env: Any = None, **kwargs: Any) -> DummyProc:
        captured_envs.append(dict(env or {}))
        return DummyProc()

    import canary.mcp_server as mcp_server

    monkeypatch.setattr(
        mcp_server,
        "write_secret_files",
        lambda tier, seed, token, directory=None: {"CANARY_EPISODE_FILE": str(tmp_path / "ep.json")},
    )
    monkeypatch.setattr("canary.agents.frontier.common.subprocess.Popen", fake_popen)
    monkeypatch.setattr("canary.agents.frontier.common.http", lambda *a, **kw: {"ok": True})

    monkeypatch.setenv("CANARY_PROVIDER", "v16:v1_anchoring")
    srv1 = Server("hard", 30, port=18901)
    srv1.start()
    assert captured_envs[-1].get("CANARY_PROVIDER") == "v16:v1_anchoring"

    monkeypatch.delenv("CANARY_PROVIDER", raising=False)
    srv2 = Server("hard", 31, port=18902)
    srv2.start()
    assert "CANARY_PROVIDER" not in captured_envs[-1]


def test_variant_provider_resolution_and_seed_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    assert V16.parse_seed_spec("30-33,35,31") == [30, 31, 32, 33, 35]
    with pytest.raises(ValueError):
        V16.parse_seed_spec("40-30")

    p0 = V16.resolve_provider("v0_v14_control")
    assert isinstance(p0, TemplateProvider)

    called: list[str] = []

    def fake_get_provider(spec: str, **kw: Any) -> str:
        called.append(spec)
        return f"provider:{spec}"

    monkeypatch.setattr("canary.text.gemini.get_provider", fake_get_provider)
    assert V16.resolve_provider("v1_authority") == "provider:v16:v1_authority"
    assert V16.resolve_provider("gemini:gemini-4-carbon") == "provider:gemini:gemini-4-carbon"
    assert called == ["v16:v1_authority", "gemini:gemini-4-carbon"]


def test_fake_cli_end_to_end_gates_and_hygiene(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch"
    out_json = tmp_path / "out" / "fake_control.json"
    rc = V16.main([
        "--variant",
        "v0_v14_control",
        "--tier",
        "easy",
        "--seeds",
        "0-2",
        "--harness",
        "inproc",
        "--jobs",
        "2",
        "--scratch-dir",
        str(scratch),
        "--out",
        str(out_json),
        "--fake",
    ])
    assert rc == 0
    assert out_json.is_file()
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data["variant"] == "v0_v14_control"
    assert data["n_seeds"] == 3
    assert data["seeds"] == [0, 1, 2]
    assert data["do_nothing_mean"] == 0.0
    assert data["stop_early_mean"] == 0.0
    assert data["solver_calibration_diff"] == 0.0
    assert data["replay_verified_count"] == 3
    assert data["replay_verified_rate"] == 1.0
    assert data["gates"]["all_passed"] is True
    assert len(data["per_seed"]) == 3

    raw = out_json.read_text(encoding="utf-8")
    assert '"mole"' not in raw
    assert '"decoy"' not in raw
    assert '"steps"' not in raw
    assert '"transcript"' not in raw

    ckpt = scratch / "inproc" / "v0_v14_control" / "easy" / "episodes.jsonl"
    lines = [json.loads(x) for x in ckpt.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(lines) == 3
    assert all(x["valid"] is True and x["meta"]["valid"] is True for x in lines)


def test_retry_on_error_empty_valid_false_and_exhaustion(tmp_path: Path) -> None:
    sleeps: list[float] = []
    calls_by_seed: dict[int, int] = {}

    def fake_env_factory(tier: str, seed: int, provider: Any) -> FakeEnv:
        return FakeEnv(tier=tier, seed=seed, text_provider=provider)

    def flaky_attempt_runner(seed: int, attempt_idx: int) -> tuple[EpisodeResult, Any, str | None]:
        calls_by_seed[seed] = calls_by_seed.get(seed, 0) + 1
        if attempt_idx == 0:
            raise RuntimeError("transient 503")
        if attempt_idx == 1:
            bad = EpisodeResult("easy", seed, "gemini:gemini-4-carbon", [], 0.0, None, False, 0, "error", {"error": "api"})
            return bad, None, None
        if attempt_idx == 2:
            empty = EpisodeResult("easy", seed, "gemini:gemini-4-carbon", [], 0.0, None, False, 1, "horizon", {})
            return empty, None, None
        env = FakeEnv(tier="easy", seed=seed)
        env.call("list_employees", {})
        env.call("status", {})
        env.call("accuse", {"employee": "e03"})
        good = env.result("gemini:gemini-4-carbon")
        good.meta["V"] = 1.0
        return good, [{"role": "assistant", "content": "", "tool_calls": [{"id": "1", "name": "accuse", "args": {"employee": "e03"}}]}], None

    scratch = tmp_path / "scratch_retry"
    res = V16.evaluate_matrix(
        variant="v0_v14_control",
        tier="easy",
        seeds=[7],
        harness="inproc",
        jobs=1,
        max_retries=3,
        scratch_dir=scratch,
        fake=True,
        sleep_fn=sleeps.append,
        attempt_runner=flaky_attempt_runner,
        env_factory=fake_env_factory,
    )
    assert calls_by_seed[7] == 4
    assert sleeps == [5.0, 15.0, 30.0]
    assert res["gemini_mean"] == 1.0

    ckpt = scratch / "inproc" / "v0_v14_control" / "easy" / "episodes.jsonl"
    lines = [json.loads(x) for x in ckpt.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(lines) == 1
    assert lines[0]["seed"] == 7
    assert lines[0]["valid"] is True

    class FlaggedInvalidResult(EpisodeResult):
        valid = False

    sleeps_fail: list[float] = []
    scratch_fail = tmp_path / "scratch_fail"

    def always_invalid_runner(seed: int, attempt_idx: int) -> tuple[EpisodeResult, Any, str | None]:
        st = Step(t=0, day=1, tool="status", args={}, result={"ok": True, "data": {"day": 1, "V": 1.0}, "error": None})
        bad = FlaggedInvalidResult("easy", seed, "gemini:gemini-4-carbon", [st], 0.0, None, False, 1, "horizon", {})
        return bad, None, None

    with pytest.raises(RuntimeError, match="failed all 3 attempts"):
        V16.evaluate_matrix(
            variant="v0_v14_control",
            tier="easy",
            seeds=[8],
            harness="inproc",
            jobs=1,
            max_retries=2,
            scratch_dir=scratch_fail,
            fake=True,
            sleep_fn=sleeps_fail.append,
            attempt_runner=always_invalid_runner,
            env_factory=fake_env_factory,
        )
    assert sleeps_fail == [5.0, 15.0]
    ckpt_fail = scratch_fail / "inproc" / "v0_v14_control" / "easy" / "episodes.jsonl"
    assert not ckpt_fail.exists()


def test_inproc_timeout_and_zero_model_tool_calls_are_invalid(tmp_path: Path) -> None:
    def fake_env_factory(tier: str, seed: int, provider: Any) -> FakeEnv:
        return FakeEnv(tier=tier, seed=seed, text_provider=provider, tool_call_cap=6)

    res_empty, _, reason_empty = V16.run_inproc_attempt(
        tier="easy",
        seed=1,
        variant="v0_v14_control",
        model="gemini:gemini-4-carbon",
        episode_timeout=5.0,
        fake=True,
        env_factory=fake_env_factory,
        client_factory=lambda _s: StubClient(script=[], model="empty"),
    )
    assert reason_empty == "zero_model_tool_calls"

    class SlowClient(StubClient):
        def _chat(self, *args: Any, **kwargs: Any) -> Any:
            time.sleep(0.2)
            return super()._chat(*args, **kwargs)

    res_to, _, reason_to = V16.run_inproc_attempt(
        tier="easy",
        seed=2,
        variant="v0_v14_control",
        model="gemini:gemini-4-carbon",
        episode_timeout=0.04,
        fake=True,
        env_factory=fake_env_factory,
        client_factory=lambda _s: SlowClient(script=[], model="slow"),
    )
    assert reason_to is not None
    assert "timeout" in reason_to or res_to.end_reason == "error"


def test_resume_skips_completed_valid_seeds(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch_resume"
    invoked: list[int] = []

    def fake_env_factory(tier: str, seed: int, provider: Any) -> FakeEnv:
        return FakeEnv(tier=tier, seed=seed, text_provider=provider)

    def tracking_client_factory(seed: int) -> StubClient:
        invoked.append(seed)
        return V16.make_fake_client(seed)

    V16.evaluate_matrix(
        variant="v0_v14_control",
        tier="easy",
        seeds=[0, 1],
        harness="inproc",
        jobs=1,
        scratch_dir=scratch,
        fake=True,
        env_factory=fake_env_factory,
        client_factory=tracking_client_factory,
    )
    assert invoked == [0, 1]

    invoked.clear()
    out2 = V16.evaluate_matrix(
        variant="v0_v14_control",
        tier="easy",
        seeds=[0, 1, 2],
        harness="inproc",
        jobs=1,
        scratch_dir=scratch,
        fake=True,
        env_factory=fake_env_factory,
        client_factory=tracking_client_factory,
    )
    assert invoked == [2]
    assert out2["seeds"] == [0, 1, 2]
    assert out2["n_seeds"] == 3


def test_paired_bootstrap_ratio_ci_deterministic_seed_42() -> None:
    num = [0.2, 0.4, 0.3, 0.5, 0.1, 0.6]
    den = [0.4, 0.8, 0.6, 1.0, 0.2, 1.2]
    lo1, hi1 = V16.paired_bootstrap_ratio_ci(num, den)
    lo2, hi2 = V16.paired_bootstrap_ratio_ci(num, den)
    assert lo1 == lo2 == pytest.approx(0.5)
    assert hi1 == hi2 == pytest.approx(0.5)

    num2 = [0.1, 0.2, 0.5, 0.3, 0.4, 0.0]
    den2 = [0.5, 0.6, 0.7, 0.8, 0.5, 0.6]
    lo3, hi3 = V16.paired_bootstrap_ratio_ci(num2, den2)
    lo4, hi4 = V16.paired_bootstrap_ratio_ci(num2, den2)
    assert lo3 == lo4
    assert hi3 == hi4
    ratio = (sum(num2) / len(num2)) / (sum(den2) / len(den2))
    assert lo3 is not None and hi3 is not None
    assert lo3 <= ratio <= hi3


def test_hygiene_rejects_forbidden_keys_and_secrets() -> None:
    with pytest.raises(ValueError, match="forbidden hygiene key 'mole'"):
        V16.assert_clean_output({"per_seed": [{"seed": 1, "mole": "e01"}]})
    with pytest.raises(ValueError, match="forbidden hygiene key 'decoy'"):
        V16.assert_clean_output({"decoy": "e02"})
    with pytest.raises(ValueError, match="forbidden hygiene key 'steps'"):
        V16.assert_clean_output({"steps": []})
    with pytest.raises(ValueError, match="secret key pattern"):
        V16.assert_clean_output({"note": "AIzaSyFakeSecretKeyValue1234567890"})


def test_fake_checkpoint_not_resumed_in_real_mode_and_v16_variant_gates(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch_v16"
    out_v1 = V16.evaluate_matrix(
        variant="v1_anchoring_authority_confirmation",
        tier="easy",
        seeds=[30, 31],
        harness="inproc",
        jobs=2,
        scratch_dir=scratch,
        fake=True,
    )
    assert out_v1["gates"]["all_passed"] is True
    assert out_v1["do_nothing_mean"] == 0.0
    assert out_v1["stop_early_mean"] == 0.0
    assert out_v1["solver_calibration_diff"] == 0.0
    assert out_v1["replay_verified_count"] == 2

    ckpt_file = scratch / "inproc" / "v1_anchoring_authority_confirmation" / "easy" / "episodes.jsonl"
    assert len(V16.load_checkpoint_episodes(ckpt_file, tier="easy", fake=True)) == 2
    assert len(V16.load_checkpoint_episodes(ckpt_file, tier="easy", fake=False)) == 0

