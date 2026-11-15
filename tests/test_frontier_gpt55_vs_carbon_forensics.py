"""Tests for scripts/frontier_gpt55_vs_carbon_forensics.py and v1.4 cross-vendor forensics artifacts."""
from __future__ import annotations

import copy
import importlib.util
import json
import math
import os
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
SCRIPT_PATH = SCRIPTS_DIR / "frontier_gpt55_vs_carbon_forensics.py"
JSON_PATH = ROOT / "results" / "frontier_replication" / "v1.4" / "gpt55_vs_carbon_forensics.json"
MD_PATH = ROOT / "docs" / "reports" / "frontier_gpt55_vs_carbon_forensics_v14.md"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _load_module():
    spec = importlib.util.spec_from_file_location("frontier_gpt55_vs_carbon_forensics", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


fgc = _load_module()
INITIAL_ALLOW_DEV = os.environ.get("CANARY_ALLOW_DEV")


def _forbid_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail(*args, **kwargs):
        raise AssertionError(f"subprocess call forbidden at runtime: {args}")

    monkeypatch.setattr(subprocess, "run", _fail)
    monkeypatch.setattr(subprocess, "Popen", _fail)
    monkeypatch.setattr(subprocess, "check_call", _fail)
    monkeypatch.setattr(subprocess, "check_output", _fail)


def _set_keyless_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.setenv(var, "")
    for var in ("GOOGLE_GENERATIVE_AI_API_KEY", "ANTHROPIC_API_KEY", "CANARY_WORLD_SECRET"):
        monkeypatch.delenv(var, raising=False)


def _populate_gitless_root(syn_root: Path, include_outputs: bool = True) -> Path:
    (syn_root / "data" / "runs" / "committed").mkdir(parents=True, exist_ok=True)
    (syn_root / "results" / "harbor").mkdir(parents=True, exist_ok=True)
    os.symlink(
        ROOT / "data" / "runs" / "committed" / "v1.4",
        syn_root / "data" / "runs" / "committed" / "v1.4",
    )
    os.symlink(
        ROOT / "results" / "harbor" / "rehearsal",
        syn_root / "results" / "harbor" / "rehearsal",
    )
    if include_outputs:
        (syn_root / "results" / "frontier_replication" / "v1.4").mkdir(parents=True, exist_ok=True)
        (syn_root / "docs" / "reports").mkdir(parents=True, exist_ok=True)
        os.symlink(JSON_PATH, fgc.default_json_path(syn_root))
        os.symlink(MD_PATH, fgc.default_md_path(syn_root))
    assert not (syn_root / ".git").exists()
    return syn_root


@pytest.fixture(scope="module")
def gitless_bundle(tmp_path_factory: pytest.TempPathFactory):
    syn_root = _populate_gitless_root(tmp_path_factory.mktemp("gitless_forensics_root"), include_outputs=True)
    mp = pytest.MonkeyPatch()
    _forbid_subprocess(mp)
    _set_keyless_env(mp)
    env_before = dict(os.environ)
    try:
        payload = fgc.compute_forensics(root=syn_root)
        assert dict(os.environ) == env_before
    finally:
        mp.undo()
    return syn_root, payload


def test_check_cli_keyless_no_subprocess_and_gitless_root(gitless_bundle, monkeypatch, tmp_path, capsys):
    syn_root, payload = gitless_bundle
    _forbid_subprocess(monkeypatch)
    _set_keyless_env(monkeypatch)
    assert not (syn_root / ".git").exists()

    assert fgc.main(["--root", str(syn_root), "--check"]) == 0
    out_syn = capsys.readouterr().out
    assert "OK gpt55_vs_carbon_forensics=PASS seeds=30 verified=90 gpt55=101%/84% carbon=65%/72%" in out_syn

    monkeypatch.setattr(fgc, "compute_forensics", lambda root=ROOT: copy.deepcopy(payload))
    assert fgc.main(["--check"]) == 0
    out_repo = capsys.readouterr().out
    assert "OK gpt55_vs_carbon_forensics=PASS" in out_repo

    assert JSON_PATH.read_bytes() == fgc.serialize_forensics_json(payload).encode("utf-8")
    assert MD_PATH.read_bytes() == fgc.render_markdown(payload).encode("utf-8")

    shallow_root = _populate_gitless_root(tmp_path / "shallow_zip_tree", include_outputs=False)
    out_json = tmp_path / "out" / "gpt55_vs_carbon_forensics.json"
    out_md = tmp_path / "out" / "frontier_gpt55_vs_carbon_forensics_v14.md"
    assert fgc.main(["--root", str(shallow_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 1
    assert fgc.main(["--root", str(shallow_root), "--out-json", str(out_json), "--out-md", str(out_md), "--write"]) == 0
    assert out_json.read_bytes() == JSON_PATH.read_bytes()
    assert out_md.read_bytes() == MD_PATH.read_bytes()
    assert fgc.main(["--root", str(shallow_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 0

    with pytest.raises(SystemExit):
        fgc.main(["--write", "--check"])


def test_tamper_detection_json_md_size_and_replay(gitless_bundle, monkeypatch, tmp_path):
    syn_root, payload = gitless_bundle
    _forbid_subprocess(monkeypatch)
    _set_keyless_env(monkeypatch)
    monkeypatch.setattr(fgc, "compute_forensics", lambda root=ROOT: copy.deepcopy(payload))

    out_json = tmp_path / "tamper" / "gpt55_vs_carbon_forensics.json"
    out_md = tmp_path / "tamper" / "frontier_gpt55_vs_carbon_forensics_v14.md"
    base_args = ["--root", str(syn_root), "--out-json", str(out_json), "--out-md", str(out_md)]

    assert fgc.main([*base_args, "--write"]) == 0
    assert fgc.main([*base_args, "--check"]) == 0

    doc = json.loads(out_json.read_text(encoding="utf-8"))
    orig_score = doc["cohort_summaries"]["gpt_5_5"]["mean_score"]

    doc["cohort_summaries"]["gpt_5_5"]["mean_score"] = orig_score + 1e-11
    out_json.write_text(fgc.serialize_forensics_json(doc), encoding="utf-8")
    assert fgc.main([*base_args, "--check"]) == 0

    doc["cohort_summaries"]["gpt_5_5"]["mean_score"] = orig_score + 0.01
    out_json.write_text(fgc.serialize_forensics_json(doc), encoding="utf-8")
    assert fgc.main([*base_args, "--check"]) == 1

    doc["cohort_summaries"]["gpt_5_5"]["mean_score"] = orig_score
    doc["cohort_summaries"]["carbon"]["raw_ratio_pct"] = 66
    out_json.write_text(fgc.serialize_forensics_json(doc), encoding="utf-8")
    assert fgc.main([*base_args, "--check"]) == 1

    doc["cohort_summaries"]["carbon"]["raw_ratio_pct"] = 65
    clean_json_txt = fgc.serialize_forensics_json(doc)
    out_json.write_text(clean_json_txt, encoding="utf-8")
    assert fgc.main([*base_args, "--check"]) == 0

    orig_md_txt = out_md.read_text(encoding="utf-8")
    assert "101% [79%, 140%]" in orig_md_txt
    out_md.write_text(orig_md_txt.replace("101% [79%, 140%]", "102% [79%, 140%]", 1), encoding="utf-8")
    assert fgc.main([*base_args, "--check"]) == 1

    out_md.write_text(orig_md_txt + chr(0x2014) + "\n", encoding="utf-8")
    assert fgc.main([*base_args, "--check"]) == 1

    out_md.write_text(orig_md_txt, encoding="utf-8")
    oversized = clean_json_txt.rstrip("\n") + (" " * 5_000) + "\n"
    assert len(oversized.encode("utf-8")) > fgc.MAX_JSON_BYTES
    out_json.write_text(oversized, encoding="utf-8")
    assert fgc.main([*base_args, "--check"]) == 1

    ep_path = ROOT / "data" / "runs" / "committed" / "v1.4" / "opencode-gpt-5.5" / "hard" / "episodes.jsonl"
    first_ep = json.loads(ep_path.read_text(encoding="utf-8").splitlines()[0])
    monkeypatch.setenv("CANARY_ALLOW_DEV", "1")
    with pytest.raises(ValueError, match="replay mismatch"):
        fgc._replay_and_audit_episode({**first_ep, "score": 0.25})
    with pytest.raises(ValueError, match="replay mismatch"):
        fgc._replay_and_audit_episode({**first_ep, "meta": {**first_ep["meta"], "rc": 124}})


def test_exact_justsilas_5f9b3297_numbers_and_forensics(gitless_bundle):
    assert os.environ.get("CANARY_ALLOW_DEV") == INITIAL_ALLOW_DEV
    _, data = gitless_bundle
    assert data["schema_version"] == "v1.4-frontier-gpt55-vs-carbon-forensics-1"
    assert data["tiers_version"] == "v1.4"
    assert data["upstream_justsilas_sync_commit"] == "5f9b3297"
    assert data["pure_cpu_zero_api_calls"] is True
    assert data["zero_subprocesses"] is True
    assert data["zero_git_history_calls"] is True

    rv = data["replay_verification"]
    assert rv == {
        "paired_seeds_count": 30,
        "total_episodes_verified": 90,
        "mismatches": 0,
        "step_mismatches": 0,
        "duplicates": 0,
    }

    prov = data["provenance_and_locks"]
    harbor = prov["upstream_justsilas_sync"]["harbor_rehearsal"]
    assert harbor["final_branch_commit"] == "d0ead011"
    assert harbor["ceo_correction_commit"] == "5f9b3297"
    assert harbor["final_ratios_pct"] == [93, 116, 131]
    assert harbor["valid_trials_by_run"] == [10, 10, 9]
    assert harbor["run3_final"] == {
        "n_valid": 9,
        "infra_excluded": 1,
        "mean": 0.626,
        "ratio_pct": 131,
        "ci_pct": [86, 590],
    }

    assert prov["primary_carbon_hard_0_29"]["classification"] == "post_hoc_lock"
    assert prov["primary_carbon_hard_0_29"]["episodes_commit"] == "8fd4dec"
    assert prov["primary_carbon_hard_0_29"]["lock_commit"] == "671ed96"
    assert prov["primary_carbon_hard_0_29"]["lock_delay_s"] == 28
    assert prov["gpt_5_5_hard_0_29"]["classification"] == "pre_registered"
    assert prov["gpt_5_5_hard_0_29"]["prereg_commit"] == "cf394894"
    assert prov["gpt_5_5_hard_0_29"]["results_commit"] == "ca0a0dc0"
    assert prov["gpt_5_5_hard_0_29"]["upstream_sync_commit"] == "5f9b3297"
    assert prov["gpt_5_5_hard_0_29"]["timeout_cap_s"] == 7200
    assert prov["gpt_5_5_hard_0_29"]["clean_rc0_non_accuse_seeds"] == [0, 17]

    cs = data["cohort_summaries"]
    gp, ca, so = cs["gpt_5_5"], cs["carbon"], cs["solver"]

    assert gp["n"] == 30
    assert round(gp["mean_score"], 3) == 0.504
    assert math.isclose(gp["mean_score"], 0.503667, abs_tol=1e-6)
    assert gp["raw_ratio_pct"] == 101
    assert gp["raw_ratio_ci_pct"] == [79, 140]
    assert round(gp["mean_post_expected"], 3) == 0.418
    assert math.isclose(gp["mean_post_expected"], 0.417754, abs_tol=1e-6)
    assert gp["luck_adjusted_ratio_pct"] == 84
    assert gp["luck_adjusted_ratio_ci_pct"] == [67, 103]
    assert gp["accused_count"] == 28
    assert gp["correct_count"] == 28
    assert gp["wrong_count"] == 0
    assert gp["non_accuse_count"] == 2

    assert ca["n"] == 30
    assert round(ca["mean_score"], 3) == 0.322
    assert math.isclose(ca["mean_score"], 0.322333, abs_tol=1e-6)
    assert ca["raw_ratio_pct"] == 65
    assert ca["raw_ratio_ci_pct"] == [24, 98]
    assert round(ca["mean_post_expected"], 3) == 0.360
    assert math.isclose(ca["mean_post_expected"], 0.359545, abs_tol=1e-6)
    assert ca["luck_adjusted_ratio_pct"] == 72
    assert ca["luck_adjusted_ratio_ci_pct"] == [52, 91]
    assert ca["accused_count"] == 29
    assert ca["correct_count"] == 25
    assert ca["wrong_count"] == 4
    assert ca["non_accuse_count"] == 1

    assert so["n"] == 30
    assert round(so["mean_score"], 3) == 0.499
    assert round(so["mean_post_expected"], 3) == 0.499
    assert so["accused_count"] == 30
    assert so["correct_count"] == 29
    assert so["wrong_count"] == 1

    div = data["divergence_forensics"]
    assert div["divergence_seeds"] == [0, 1, 11, 15, 17, 18, 26]
    assert div["divergence_count"] == 7
    assert div["concordant_correct_seeds_count"] == 23
    assert div["carbon_wrong_accusation_seeds"] == [1, 15, 18, 26]
    assert div["carbon_abstention_seeds"] == [11]
    assert div["gpt55_non_accuse_prose_exit_seeds"] == [0, 17]
    assert div["carbon_failures_solved_by_gpt55_count"] == 5

    assert [c["seed"] for c in div["carbon_wrong_cases"]] == [1, 15, 18, 26]
    assert [c["seed"] for c in div["carbon_abstention_cases"]] == [11]
    prose_cases = div["gpt55_non_accuse_prose_cases"]
    assert [c["seed"] for c in prose_cases] == [0, 17]
    assert [c["prose_suspect_named"] for c in prose_cases] == ["e38", "e28"]
    assert [c["mole"] for c in prose_cases] == ["e38", "e28"]
    assert all(c["rc"] == 0 and c["matches_true_mole"] and c["matches_top_posterior"] for c in prose_cases)

    sm = data["seed_matrix"]
    assert [r["seed"] for r in sm] == list(range(30))
    for r in sm:
        s = r["seed"]
        if s in (0, 17):
            assert r["gpt55"]["accused"] is None and r["carbon"]["correct"] is True
        elif s in (1, 15, 18, 26):
            assert r["carbon"]["correct"] is False and r["carbon"]["score"] == -1.0 and r["gpt55"]["correct"] is True
        elif s == 11:
            assert r["carbon"]["accused"] is None and r["gpt55"]["correct"] is True
        else:
            assert r["gpt55"]["correct"] is True and r["carbon"]["correct"] is True
            assert r["gpt55"]["accused"] == r["mole"] == r["carbon"]["accused"]

    g_raw = [float(r["gpt55"]["score"]) for r in sm]
    s_raw = [float(r["solver"]["score"]) for r in sm]
    ref_lo, ref_hi = fgc.boot_ratio(g_raw, s_raw, B=400, rng_seed=0)
    fast_lo, fast_hi = fgc._fast_boot_ratio(g_raw, s_raw, B=400, rng_seed=0)
    assert math.isclose(ref_lo, fast_lo, abs_tol=1e-12)
    assert math.isclose(ref_hi, fast_hi, abs_tol=1e-12)

    md = MD_PATH.read_text(encoding="utf-8")
    for token in (
        "5f9b3297",
        "101% [79%, 140%]",
        "84% [67%, 103%]",
        "65% [24%, 98%]",
        "72% [52%, 91%]",
        "93%, 116%, 131%",
        "[10, 10, 9]",
        "e38",
        "e28",
    ):
        assert token in md


def test_strict_hygiene_ascii_dashes_secrets_bytes_and_zero_comments():
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    this_test = Path(__file__).resolve()
    py_files = [SCRIPT_PATH, this_test]
    owned_files = [SCRIPT_PATH, this_test, JSON_PATH, MD_PATH]

    assert fgc.MAX_JSON_BYTES == 38_000
    json_bytes = JSON_PATH.read_bytes()
    assert 0 < len(json_bytes) <= 38_000

    for pf in py_files:
        with pf.open("rb") as fh:
            tokens = list(tokenize.tokenize(fh.readline))
        comments = [t for t in tokens if t.type == tokenize.COMMENT]
        assert not comments, f"found comments in {pf}: {comments}"
        src = pf.read_text(encoding="utf-8")
        assert hash_char not in src, f"found {hash_char!r} character in {pf}"

    for f in owned_files:
        raw = f.read_bytes()
        txt = raw.decode("utf-8")
        assert txt.isascii(), f"non-ASCII characters in {f}"
        assert em_dash not in txt, f"em dash in {f}"
        assert en_dash not in txt, f"en dash in {f}"
        assert fgc._scan_hygiene_errors(raw, str(f)) == []

    fake_google = (("AI" + "za") + ("X" * 24)).encode("ascii")
    fake_sk = (("s" + "k-") + ("Y" * 20)).encode("ascii")
    fake_tsig = ('"thought' + 'Signature": "' + ("Z" * 70) + '"').encode("ascii")
    for bad_raw in (fake_google, fake_sk, fake_tsig):
        assert len(fgc._scan_hygiene_errors(bad_raw, "synthetic")) == 1
