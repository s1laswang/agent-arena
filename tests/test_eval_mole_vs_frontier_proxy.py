from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys
import time

import pytest

from canary.env import Env
from canary.eval import run_episode
from canary.forge.rl_mole import RLMole
from canary.forge.rl_mole_v2 import RLMoleV2
from canary.mole.dsl import MoleStrategy

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "eval_mole_vs_frontier_proxy.py"


def _load_eval_module():
    spec = importlib.util.spec_from_file_location("eval_mole_vs_frontier_proxy", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load_eval_module()


def test_gemini_carbon_proxy_two_seeds_deterministic():
    proxy_cls, source = M.resolve_gemini_carbon_proxy()
    assert source in ("builtin_fallback", "canary.forge.frontier_proxies:GeminiCarbonProxy")
    for seed in (200_000, 200_001):
        r1 = run_episode(Env("hard", seed), proxy_cls(seed=seed))
        r2 = run_episode(Env("hard", seed), proxy_cls(seed=seed))
        assert -1.0 <= r1.score <= 1.0
        assert (r1.score, r1.correct, r1.accused) == (r2.score, r2.correct, r2.accused)


def test_policy_spec_loader_includes_rl_mole_v2(monkeypatch):
    assert M.DEFAULT_POLICY_SPECS == (
        "default",
        "rl_mole:data/rl_mole/policy_final.json",
        "rl_mole_v2:results/moletrain/rl_mole_v2_policy.json",
        "fixed:none/decoy",
        "fixed:random_seeded/decoy",
    )
    ap = M.build_arg_parser()
    defaults = ap.parse_args([])
    assert defaults.n_per_suite == 30

    sp_def = M.parse_mole_spec("default")
    assert sp_def.instantiate() is None

    sp_v1 = M.parse_mole_spec("rl_mole:data/rl_mole/policy_final.json")
    pol_v1 = sp_v1.instantiate()
    assert isinstance(pol_v1, RLMole)
    assert pol_v1.greedy is False

    sp_v2 = M.parse_mole_spec("rl_mole_v2:results/moletrain/rl_mole_v2_policy.json")
    pol_v2 = sp_v2.instantiate()
    assert sp_v2.kind == "rl_mole_v2"
    assert isinstance(pol_v2, RLMoleV2)
    assert pol_v2.greedy is False

    sp_v2_g = M.parse_mole_spec("v2g=rl_mole_v2_greedy:results/moletrain/rl_mole_v2_policy.json")
    pol_v2_g = sp_v2_g.instantiate()
    assert sp_v2_g.label == "v2g"
    assert isinstance(pol_v2_g, RLMoleV2)
    assert pol_v2_g.greedy is True

    calls: list[Path] = []

    def _fake_load(cls, p):
        calls.append(Path(p))
        return cls.from_json(json.loads(Path(p).read_text(encoding="utf-8")))

    monkeypatch.setattr(RLMoleV2, "load", classmethod(_fake_load), raising=False)
    sp_via_load = M.parse_mole_spec("rl_mole_v2:results/moletrain/rl_mole_v2_policy.json")
    assert len(calls) == 1
    assert isinstance(sp_via_load.instantiate(), RLMoleV2)

    sp_fix = M.parse_mole_spec("fixed:random_seeded/decoy")
    assert isinstance(sp_fix.instantiate(), MoleStrategy)

    args = ap.parse_args(["--policies", "default", "--extra-rl", "results/moletrain/rl_mole_v2_policy.json"])
    collected = M.collect_policy_specs(args)
    assert [c.label for c in collected] == [
        "default",
        "rl_mole_v2:results/moletrain/rl_mole_v2_policy.json",
    ]

    with pytest.raises(ValueError):
        M.parse_mole_spec("fixed:bad_selector/decoy")
    with pytest.raises(ValueError):
        M.validate_seed_hygiene([0])
    with pytest.raises(ValueError):
        M.validate_seed_hygiene([150_000])
    with pytest.raises(ValueError):
        M.validate_seed_hygiene([350_000])
    with pytest.raises(ValueError):
        M.validate_seed_hygiene([900_000])


def test_generated_matrix_check_and_tamper_guards(tmp_path):
    t0 = time.perf_counter()
    rc = M.main(["--check"])
    elapsed = time.perf_counter() - t0
    assert rc == 0
    assert elapsed < 1.0

    report = M.check_matrix_file(M.DEFAULT_OUT)
    assert report["ok"] is True
    assert 0 < report["size_bytes"] < 45_000
    assert report["base_suites"] == ["200000-200029", "800000-800029"]
    assert report["total_unique_seeds"] == 60
    assert report["policies"] == list(M.DEFAULT_POLICY_SPECS)

    raw = json.loads(M.DEFAULT_OUT.read_text(encoding="utf-8"))
    for suite_name in ("200000-200029", "800000-800029", "combined_60"):
        s_pols = raw["suites"][suite_name]["policies"]
        assert s_pols["rl_mole_v2:results/moletrain/rl_mole_v2_policy.json"]["catchable_85"] is True
        assert s_pols["fixed:none/decoy"]["catchable_85"] is False

    overlap = copy.deepcopy(raw)
    overlap["suites"]["800000-800029"]["seed_range"] = "200015-200044"
    overlap_path = tmp_path / "overlap.json"
    overlap_path.write_text(M._dumps_matrix_json(overlap) + "\n", encoding="utf-8")
    assert M.main(["--check", "--out", str(overlap_path)]) == 1

    bad_catch = copy.deepcopy(raw)
    bad_catch["suites"]["200000-200029"]["policies"]["fixed:none/decoy"]["catchable_85"] = True
    bad_catch["suites"]["200000-200029"]["policies"]["fixed:none/decoy"]["catchable_75"] = True
    bad_catch["headline"]["fixed:none/decoy"]["200000-200029"]["catchable_85"] = True
    bad_catch_path = tmp_path / "bad_catch.json"
    bad_catch_path.write_text(M._dumps_matrix_json(bad_catch) + "\n", encoding="utf-8")
    assert M.main(["--check", "--out", str(bad_catch_path)]) == 1

    oversized_path = tmp_path / "oversized.json"
    oversized_path.write_text(" " * 45_001 + M._dumps_matrix_json(raw), encoding="utf-8")
    assert M.main(["--check", "--out", str(oversized_path)]) == 1
