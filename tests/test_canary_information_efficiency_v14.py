"""Unit, math-invariant, and fast-check tests for scripts/canary_information_efficiency_v14.py."""
from __future__ import annotations

import copy
import importlib.util
import io
import json
import math
from pathlib import Path
import re
import sys
import tokenize
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCRIPT_PATH = ROOT / "scripts/canary_information_efficiency_v14.py"
TEST_PATH = Path(__file__).resolve()
JSON_PATH = ROOT / "results/eval_v14/canary_information_efficiency_v14.json"
MD_PATH = ROOT / "docs/reports/canary_information_efficiency_v14.md"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


CIE = _load_module("canary_information_efficiency_v14", SCRIPT_PATH)


@pytest.fixture(scope="module")
def committed_payload() -> dict[str, Any]:
    assert JSON_PATH.is_file(), f"missing {JSON_PATH}"
    assert MD_PATH.is_file(), f"missing {MD_PATH}"
    assert JSON_PATH.stat().st_size < CIE.MAX_JSON_BYTES
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


def _read_first_episode(rel_path: str, seed: int = 0) -> dict[str, Any]:
    for line in (ROOT / rel_path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        ep = json.loads(line)
        if int(ep.get("seed", -1)) == seed and ep.get("valid") is not False:
            return ep
    raise AssertionError(f"seed {seed} not found in {rel_path}")


def test_fast_check_full_check_and_hash_fallback(
    committed_payload: dict[str, Any],
    capsys,
    monkeypatch,
):
    assert CIE.render_markdown_report(committed_payload) == MD_PATH.read_text(encoding="utf-8")
    assert CIE.approx_equal(json.loads(CIE.serialize_json(committed_payload)), committed_payload, tol=1e-9)

    calls = {"n": 0}

    def _fake_compute(_root: Path = CIE.ROOT) -> dict[str, Any]:
        calls["n"] += 1
        return copy.deepcopy(committed_payload)

    monkeypatch.setattr(CIE, "compute_all", _fake_compute)

    rc_fast = CIE.main(["--check"])
    out_fast = capsys.readouterr().out
    assert rc_fast == 0
    assert calls["n"] == 0
    assert "OK: canary_information_efficiency_v14 verified" in out_fast

    rc_full = CIE.main(["--check", "--full-check"])
    out_full = capsys.readouterr().out
    assert rc_full == 0
    assert calls["n"] == 1
    assert "OK: canary_information_efficiency_v14 verified" in out_full

    monkeypatch.setattr(CIE, "EXPECTED_INPUTS_SHA256", "0" * 64)
    rc_in_fb = CIE.main(["--check"])
    out_in_fb = capsys.readouterr().out
    assert rc_in_fb == 0
    assert calls["n"] == 2
    assert "OK: canary_information_efficiency_v14 verified" in out_in_fb

    monkeypatch.undo()
    monkeypatch.setattr(CIE, "compute_all", _fake_compute)
    monkeypatch.setattr(CIE, "EXPECTED_OUT_JSON_SHA256", "f" * 64)
    rc_out_fb = CIE.main(["--check"])
    assert rc_out_fb == 0
    assert calls["n"] == 3


def test_information_gain_and_kl_math_invariants():
    assert CIE.binary_entropy_bits(0.0) == 0.0
    assert CIE.binary_entropy_bits(1.0) == 0.0
    assert math.isclose(CIE.binary_entropy_bits(0.5), 1.0, abs_tol=1e-15)
    for p in (0.025, 0.2, 0.37, 0.81):
        assert math.isclose(CIE.binary_entropy_bits(p), CIE.binary_entropy_bits(1.0 - p), abs_tol=1e-15)

    p_vec = [0.55, 0.30, 0.15, 0.0]
    q_unif = [0.25, 0.25, 0.25, 0.25]
    assert CIE.kl_divergence_bits(p_vec, p_vec) == 0.0
    assert CIE.kl_divergence_bits(p_vec, q_unif) > 0.0
    assert math.isclose(
        CIE.kl_divergence_bits(p_vec, q_unif),
        math.log2(4.0) - CIE.entropy_bits(p_vec),
        abs_tol=1e-14,
    )
    assert math.isclose(
        CIE.kl_divergence_bits({"a": 0.7, "b": 0.3}, {"a": 0.5, "b": 0.5}),
        CIE.kl_divergence_bits([0.7, 0.3], [0.5, 0.5]),
        abs_tol=1e-15,
    )
    assert CIE.kl_divergence_bits([0.5, 0.5], [1.0, 0.0]) == math.inf
    with pytest.raises(ValueError):
        CIE.kl_divergence_bits([0.5, 0.5], [1.0])
    with pytest.raises(ValueError):
        CIE.kl_divergence_bits([-0.1, 1.1], [0.5, 0.5])
    with pytest.raises(TypeError):
        CIE.kl_divergence_bits({"a": 1.0}, [1.0])

    assert CIE.canary_leak_ceiling_bits(1, 0.95) == 0.0
    assert math.isclose(CIE.canary_leak_ceiling_bits(3, 1.0), math.log2(3.0), abs_tol=1e-15)
    assert math.isclose(CIE.canary_leak_ceiling_bits(3, 1.0 / 3.0), 0.0, abs_tol=1e-14)
    c_hard = CIE.canary_leak_ceiling_bits(3, 0.95)
    assert math.isclose(
        c_hard,
        CIE.kl_divergence_bits([0.95, 0.025, 0.025], [1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0]),
        abs_tol=1e-14,
    )
    grid = [CIE.canary_leak_ceiling_bits(3, q) for q in (1.0 / 3.0, 0.5, 0.7, 0.9, 0.95, 1.0)]
    assert all(a < b for a, b in zip(grid, grid[1:]))

    assert CIE.interview_channel_mi_bits(0.5, 0.20, 1.0) == 0.0
    assert CIE.interview_channel_mi_bits(0.0, 0.20, 1.2) == 0.0
    assert CIE.interview_channel_mi_bits(1.0, 0.20, 1.2) == 0.0
    for p, lr in ((0.5, 1.2), (1.0 / 40.0, 1.2), (0.5, 1.3), (1.0 / 20.0, 1.3)):
        q0 = 0.20
        q1 = q0 * lr
        q_mix = p * q1 + (1.0 - p) * q0
        post_ev = [p * q1 / q_mix, (1.0 - p) * q0 / q_mix]
        post_co = [p * (1.0 - q1) / (1.0 - q_mix), (1.0 - p) * (1.0 - q0) / (1.0 - q_mix)]
        prior = [p, 1.0 - p]
        expected_kl = q_mix * CIE.kl_divergence_bits(post_ev, prior) + (1.0 - q_mix) * CIE.kl_divergence_bits(post_co, prior)
        assert math.isclose(CIE.interview_channel_mi_bits(p, q0, lr), expected_kl, abs_tol=1e-15)


def test_single_episode_replay_telescoping_and_tamper_guards():
    for rel, n_staff in (
        ("data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl", 40),
        ("data/runs/committed/v1.4/reference/solver-medium-20261114-121126/episodes.jsonl", 20),
    ):
        ep = _read_first_episode(rel, seed=0)
        out = CIE.analyze_episode(ep)
        assert out["residual"] <= 1e-12
        assert math.isclose(sum(out["ch"].values()), out["delta_h"], abs_tol=1e-12)
        assert math.isclose(out["h_final"] + out["delta_h"], math.log2(float(n_staff)), abs_tol=1e-12)
        for can in out["canaries"]:
            assert 0.0 <= float(can["h_rec"]) <= math.log2(3.0) + 1e-12
            assert 0.0 <= float(can["h_post"]) <= math.log2(3.0) + 1e-12
            assert math.isclose(float(can["cov"]) + float(can["careful_w"]), 1.0, abs_tol=1e-12)

    bad_score_ep = copy.deepcopy(
        _read_first_episode("data/runs/committed/v1.4/reference/solver-medium-20261114-121126/episodes.jsonl", seed=0)
    )
    bad_score_ep["score"] = float(bad_score_ep["score"]) + 0.25
    with pytest.raises(ValueError, match="Verdict mismatch"):
        CIE.analyze_episode(bad_score_ep)

    bad_step_ep = copy.deepcopy(
        _read_first_episode("data/runs/committed/v1.4/reference/solver-medium-20261114-121126/episodes.jsonl", seed=0)
    )
    bad_step_ep["steps"][0]["result"] = {"ok": False, "data": {}, "error": "forged"}
    with pytest.raises(ValueError, match="Replay mismatch"):
        CIE.analyze_episode(bad_step_ep)


def test_committed_cohorts_identities_and_headline_alignment(committed_payload: dict[str, Any]):
    assert committed_payload["schema_version"] == CIE.SCHEMA_VERSION
    assert committed_payload["tiers_version"] == "v1.4"
    assert committed_payload["primary_seeds"] == "0-29"
    assert committed_payload["n_seeds_per_cohort"] == 30

    vt = committed_payload["verification_totals"]
    assert vt["cohorts_verified"] == 9
    assert vt["episodes_replayed"] == 270
    assert vt["steps_verified"] == 22450
    assert float(vt["max_telescoping_residual"]) <= 1e-12

    hr = committed_payload["harbor_rehearsal_contrast"]
    assert hr["mcp_only_hard_headline_raw"] == "65% [24%, 98%]"
    assert hr["mcp_only_hard_headline_luck_adjusted"] == "72% [52%, 91%]"
    assert hr["run_ratios_vs_oracle"] == ["93% [20%, 371%]", "116% [78%, 363%]", "131% [86%, 590%]"]
    assert hr["run3_final_valid_trials"] == 9
    assert math.isclose(float(hr["run3_final_mean"]), 0.626, abs_tol=1e-9)
    assert hr["shell_used_trials"] == "20/28"

    for c in committed_payload["cohorts"]:
        assert c["n"] == 30
        pb = c["partition_balance"]
        cm = c["careful_mole_and_capacity"]
        er = c["entropy_reduction"]
        assert 0.0 <= float(pb["posterior_balance_efficiency"]) <= 1.0
        assert math.isclose(
            float(cm["recipient_coverage_mean"]) + float(cm["careful_mole_weight_mean"]),
            1.0,
            abs_tol=1e-5,
        )
        assert math.isclose(
            float(er["h_final_bits_mean"]) + float(er["delta_h_bits_mean"]),
            float(er["h0_bits"]),
            abs_tol=1e-5,
        )
        ch_sum = (
            float(er["leak_and_doc_channel_bits"])
            + float(er["access_log_channel_bits"])
            + float(er["message_channel_bits"])
            + float(er["interview_channel_bits"])
        )
        assert math.isclose(ch_sum, float(er["delta_h_bits_mean"]), abs_tol=1e-4)

    md_txt = MD_PATH.read_text(encoding="utf-8")
    for token in (
        "65% [24%, 98%]",
        "72% [52%, 91%]",
        "101% [79%, 140%]",
        "84% [67%, 103%]",
        "93% [20%, 371%]",
        "116% [78%, 363%]",
        "131% [86%, 590%]",
        "671ed96",
        "cf394894",
        "1bc3e281",
        "aa1c679e",
        "5f9b3297",
    ):
        assert token in md_txt


def test_drift_errors_and_shallow_ci_safety(
    committed_payload: dict[str, Any],
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setattr(CIE, "compute_all", lambda root=CIE.ROOT: copy.deepcopy(committed_payload))
    out_json = tmp_path / "out.json"
    out_md = tmp_path / "out.md"

    assert CIE.main(["--check", "--out-json", str(out_json), "--out-md", str(out_md)]) == 1
    assert CIE.main(["--out-json", str(out_json), "--out-md", str(out_md)]) == 0
    assert CIE.main(["--check", "--out-json", str(out_json), "--out-md", str(out_md)]) == 0

    tampered = json.loads(out_json.read_text(encoding="utf-8"))
    tampered["cohorts"][0]["score_mean"] += 0.1
    out_json.write_text(CIE.serialize_json(tampered), encoding="utf-8")
    assert CIE.main(["--check", "--out-json", str(out_json), "--out-md", str(out_md)]) == 1

    assert CIE.main(["--out-json", str(out_json), "--out-md", str(out_md)]) == 0
    bad_md = tmp_path / "bad.md"
    bad_md.write_text(out_md.read_text(encoding="utf-8") + "\ndrift\n", encoding="utf-8")
    assert CIE.main(["--check", "--out-json", str(out_json), "--out-md", str(bad_md)]) == 1

    monkeypatch.setattr(CIE, "DEFAULT_OUT_JSON", out_json)
    monkeypatch.setattr(CIE, "DEFAULT_OUT_MD", bad_md)
    monkeypatch.setattr(
        CIE,
        "EXPECTED_OUT_JSON_SHA256",
        CIE.hashlib.sha256(out_json.read_bytes()).hexdigest(),
    )
    assert CIE.main(["--check"]) == 1

    oversized = tmp_path / "oversized.json"
    oversized.write_text(" " * CIE.MAX_JSON_BYTES, encoding="utf-8")
    assert CIE.main(["--check", "--out-json", str(oversized), "--out-md", str(out_md)]) == 1

    fake_root = tmp_path / "shallow"
    for rel in ("results/harbor/rehearsal/TABLE.md", "results/harbor/rehearsal/BUILD.txt", "docs/reports/gap.md", "docs/reports/CEO.md"):
        dst = fake_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text((ROOT / rel).read_text(encoding="utf-8"), encoding="utf-8")
    assert CIE.verify_harbor_rehearsal_contrast(fake_root)["run3_final_valid_trials"] == 9
    (fake_root / "docs/reports/gap.md").write_text("stale", encoding="utf-8")
    with pytest.raises(ValueError):
        CIE.verify_harbor_rehearsal_contrast(fake_root)


def test_strict_hygiene_and_artifact_limits():
    assert JSON_PATH.stat().st_size < 80_000
    assert JSON_PATH.stat().st_size < CIE.MAX_JSON_BYTES
    assert MD_PATH.stat().st_size > 1500

    for py_path in (SCRIPT_PATH, TEST_PATH):
        src = py_path.read_text(encoding="utf-8")
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert not comments, f"found comment token in {py_path}"
        assert chr(35) not in src, f"found hash char in {py_path}"

    forbidden_chars = (chr(0x2013), chr(0x2014), chr(0x2212), chr(0x00B1))
    co_author_tag = "Co-Authored-" + "By"
    emp_id_rx = re.compile(r"\be\d{2}\b")

    for path in (SCRIPT_PATH, TEST_PATH, JSON_PATH, MD_PATH):
        txt = path.read_text(encoding="utf-8")
        assert all(ord(ch) < 128 for ch in txt), f"non-ASCII char in {path}"
        for ch in forbidden_chars:
            assert ch not in txt, f"forbidden char {hex(ord(ch))} in {path}"
        assert co_author_tag not in txt, f"co-author tag in {path}"
        assert CIE.check_text_hygiene(str(path), txt) == []

    for artifact in (JSON_PATH, MD_PATH):
        assert not emp_id_rx.search(artifact.read_text(encoding="utf-8"))

    assert CIE.check_text_hygiene("leak", json.dumps({"mo" + "le": "e" + "07"})) != []
    assert CIE.check_text_hygiene("dash", "bad " + chr(0x2014) + " dash") != []
