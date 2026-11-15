from __future__ import annotations

from dataclasses import replace
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tokenize

import pytest

from canary import rules

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "verify_staffai_branch.py"
SUMMARY_MD_PATH = ROOT / "docs" / "reports" / "staffai_social_summary.md"

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
HASH_CHAR = chr(35)


def _load_verifier():
    spec = importlib.util.spec_from_file_location("verify_staffai_branch", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


verifier = _load_verifier()


def _init_git_repo(repo: Path, files: dict[str, str | bytes]) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "-f", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
    subprocess.run(["git", "update-ref", "refs/remotes/origin/justSilas", "HEAD"], cwd=repo, check=True)


def _make_cache_entry(body_a: str, body_b: str, *, label: str = "REAL", model: str = "gemini-4-carbon") -> tuple[str, str]:
    key = hashlib.sha256(f"{body_a}|{body_b}|{label}|{model}".encode("utf-8")).hexdigest()
    payload = {
        "provenance": {
            "commit": "edbe48ac",
            "label": label,
            "model": model,
        },
        "text": json.dumps({"bodies": [body_a, body_b]}),
        "tool_calls": [],
    }
    return f"{key}.json", json.dumps(payload, indent=1, sort_keys=True)


def _render_synthetic_summary(ledger: dict[str, str], extra_link: str = "") -> str:
    h1 = HASH_CHAR
    lines = [
        f"{h1} Synthetic StaffAI Summary",
        "",
        "Verified statements: solver_v14 == solver_v16 == 0.576 on hard seeds 0-9 (tier hash a8f99c2537c91d72 under v1.4).",
        "Primary v1.4 OpenCode gemini-4-carbon scores 0.351 (60.9% raw, 55.7% luck-adjusted).",
        "Relayed 30-32 v5_full9_cocktail scores 0.617 vs 0.523 control; Gate B is NOT met, so v1.4 ships unchanged.",
        "Committed cache holds 256 REAL gemini-4-carbon files; v6_horizon_escalation emits 63 msgs across Days 1..21.",
        "",
        "| Metric Key | Verified Value | Source |",
        "|---|---|---|",
    ]
    for k, v in ledger.items():
        lines.append(f"| `{k}` | `{v}` | verified |")
    if extra_link:
        lines.append("")
        lines.append(extra_link)
    return "\n".join(lines) + "\n"


def test_real_repo_passes_staffai_branch_verifier_under_5s(capsys):
    rc_json = verifier.main(["--root", str(ROOT), "--json"])
    out_json = capsys.readouterr().out
    payload = json.loads(out_json)

    assert rc_json == 0
    assert payload["passed"] is True
    assert payload["elapsed_s"] < 5.0

    by_name = {r["name"]: r for r in payload["results"]}
    guard = by_name["Protected-Path & Frozen-Tier Guard"]
    hygiene = by_name["Secret & Gemini-Cache Hygiene"]
    consistency = by_name["Cross-Report Numeric & Dossier Consistency"]

    assert guard["status"] == "PASS"
    assert guard["metrics"]["protected_touched"] == []
    assert guard["metrics"]["tiers_version"] == "v1.4"
    assert guard["metrics"]["v14_tier_hash"] == "a8f99c2537c91d72"
    assert guard["metrics"]["v13_tier_hash"] == "8df71cf570bb48bc"
    assert guard["metrics"]["default_provider"] == "template"

    assert hygiene["status"] == "PASS"
    assert hygiene["metrics"]["cache_file_count"] == 256
    assert hygiene["metrics"]["cache_provenance_label"] == "REAL"
    assert hygiene["metrics"]["cache_provenance_model"] == "gemini-4-carbon"
    assert hygiene["metrics"]["cache_total_bodies"] == 712

    assert consistency["status"] == "PASS"
    m = consistency["metrics"]
    assert m["solver_v14_hard_0_9"] == "0.576"
    assert m["solver_v16_hard_0_9"] == "0.576"
    assert m["do_nothing_hard_0_9"] == "0.000"
    assert m["stop_early_hard_0_9"] == "0.000"
    assert m["v14_opencode_hard_0_9_raw_mean"] == "0.351"
    assert m["v14_opencode_hard_0_9_raw_pct"] == "60.9%"
    assert m["v14_opencode_hard_0_9_luck_adj_pct"] == "55.7%"
    assert m["relayed_30_32_v5_full9_mean"] == "0.617"
    assert m["relayed_30_32_v0_control_mean"] == "0.523"
    assert m["gate_b_status"] == "NOT MET"
    assert m["shipped_default_version"] == "v1.4"
    assert m["gemini_cache_real_files"] == "256"
    assert m["gemini_cache_model"] == "gemini-4-carbon"
    assert m["v6_horizon_active_days"] == "1..21"
    assert m["v6_horizon_total_messages"] == "63"

    rc_txt = verifier.main(["--root", str(ROOT)])
    out_txt = capsys.readouterr().out
    assert rc_txt == 0
    assert "SUMMARY: 3 PASS, 0 FAIL" in out_txt


def test_protected_path_guard_and_frozen_tier_drift(tmp_path, monkeypatch):
    for prot in (
        "canary/env.py",
        "canary/rules.py",
        "canary/solver/policy.py",
        "canary/reproduce.py",
        "harbor/build.py",
        "harbor/canary-task/task.toml",
    ):
        assert verifier.is_protected_path(prot), prot

    for allowed in (
        "canary/social/engine.py",
        "canary/text/gemini.py",
        "scripts/verify_staffai_branch.py",
        "docs/reports/staffai_social_summary.md",
        "tests/test_staffai_branch_hygiene.py",
    ):
        assert not verifier.is_protected_path(allowed), allowed

    repo_ok = tmp_path / "repo_ok"
    _init_git_repo(repo_ok, {"canary/env.py": "x = 1\n", "canary/social/a.py": "a = 1\n"})
    (repo_ok / "canary" / "social" / "b.py").write_text("b = 2\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_ok, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "social-only"], cwd=repo_ok, check=True)

    res_ok = verifier.check_protected_paths_and_frozen_tiers(repo_ok)
    assert res_ok.status == "PASS"
    assert res_ok.metrics["base_ref_exists"] is True
    assert res_ok.metrics["protected_touched"] == []

    res_no_ref = verifier.check_protected_paths_and_frozen_tiers(repo_ok, base_ref="origin/missing_ref")
    assert res_no_ref.status == "PASS"
    assert res_no_ref.metrics["base_ref_exists"] is False

    for idx, bad_rel in enumerate(
        (
            "canary/env.py",
            "canary/rules.py",
            "canary/solver/belief.py",
            "canary/reproduce.py",
            "harbor/canary-task/instruction.md",
        )
    ):
        bad_repo = tmp_path / f"bad_prot_{idx}"
        _init_git_repo(bad_repo, {"README.md": "ok\n"})
        target = bad_repo / bad_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("modified = True\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=bad_repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "touch-protected"], cwd=bad_repo, check=True)
        res_bad = verifier.check_protected_paths_and_frozen_tiers(bad_repo)
        assert res_bad.status == "FAIL"
        assert bad_rel in res_bad.metrics["protected_touched"]

    monkeypatch.setattr(rules, "TIERS_VERSION", "v1.6")
    assert verifier.check_protected_paths_and_frozen_tiers(repo_ok).status == "FAIL"

    monkeypatch.setattr(rules, "TIERS_VERSION", "v1.4")
    monkeypatch.setitem(rules.TIERS, "hard", replace(rules.TIERS["hard"], n_days=99))
    res_hash = verifier.check_protected_paths_and_frozen_tiers(repo_ok)
    assert res_hash.status == "FAIL"
    assert any("a8f99c2537c91d72" in d for d in res_hash.details)


def test_secret_and_gemini_cache_hygiene_synthetic_cases(tmp_path, monkeypatch):
    fn1, c1 = _make_cache_entry(
        "After the meeting e01 reviewed the Q2 budget doc.",
        "During sync e05 asked about the leak timeline doc.",
    )
    fn2, c2 = _make_cache_entry(
        "In legal sync e09 flagged the draft circulation doc.",
        "Post-meeting note on e12 and the board deck doc.",
    )
    clean_repo = tmp_path / "cache_clean"
    _init_git_repo(
        clean_repo,
        {
            f"data/gemini_cache/{fn1}": c1,
            f"data/gemini_cache/{fn2}": c2,
            ".env.example": "GEMINI_API_KEY=\n",
        },
    )
    res_clean = verifier.check_secret_and_cache_hygiene(clean_repo, expected_cache_count=2)
    assert res_clean.status == "PASS"
    assert res_clean.metrics["cache_total_bodies"] == 4

    res_wrong_count = verifier.check_secret_and_cache_hygiene(clean_repo, expected_cache_count=256)
    assert res_wrong_count.status == "FAIL"

    stub_repo = tmp_path / "cache_stub"
    s_fn, s_c = _make_cache_entry("Doc note e01.", "Leak meeting e02.", label="stub")
    _init_git_repo(stub_repo, {f"data/gemini_cache/{s_fn}": s_c})
    res_stub = verifier.check_secret_and_cache_hygiene(stub_repo, expected_cache_count=1)
    assert res_stub.status == "FAIL"
    assert any("provenance.label" in d for d in res_stub.details)

    wrong_model_repo = tmp_path / "cache_model"
    m_fn, m_c = _make_cache_entry("Doc note e01.", "Leak meeting e02.", model="gemini-2.0-flash")
    _init_git_repo(wrong_model_repo, {f"data/gemini_cache/{m_fn}": m_c})
    res_model = verifier.check_secret_and_cache_hygiene(wrong_model_repo, expected_cache_count=1)
    assert res_model.status == "FAIL"
    assert any("provenance.model" in d for d in res_model.details)

    bad_name_repo = tmp_path / "cache_bad_name"
    _init_git_repo(bad_name_repo, {"data/gemini_cache/not_a_sha256.json": c1})
    assert verifier.check_secret_and_cache_hygiene(bad_name_repo, expected_cache_count=None).status == "FAIL"

    mole_word_repo = tmp_path / "cache_mole_word"
    mw_fn, mw_c = _make_cache_entry("In meeting e01 said the mole leaked the doc.", "Normal doc note e02.")
    _init_git_repo(mole_word_repo, {f"data/gemini_cache/{mw_fn}": mw_c})
    res_mole = verifier.check_secret_and_cache_hygiene(mole_word_repo, expected_cache_count=1)
    assert res_mole.status == "FAIL"
    assert any("mole" in d for d in res_mole.details)

    fake_gkey = "AI" + "za" + "SySyntheticLeakToken" + ("Z" * 18)
    fake_sk = "s" + "k-proj-" + ("Q" * 24)
    secret_repo = tmp_path / "cache_secret"
    sec_fn, sec_c = _make_cache_entry(f"Token {fake_gkey}", f"Other {fake_sk} api_key=123")
    _init_git_repo(secret_repo, {f"data/gemini_cache/{sec_fn}": sec_c, ".env": "SECRET=1\n"})
    res_sec = verifier.check_secret_and_cache_hygiene(secret_repo, expected_cache_count=1)
    assert res_sec.status == "FAIL"
    joined = "\n".join(res_sec.details)
    assert "google_api_key" in joined
    assert "sk_api_key" in joined
    assert ".env" in joined
    assert fake_gkey not in joined
    assert fake_sk not in joined

    live_env_val = "live-secret-token-value-11223344"
    monkeypatch.setenv("GEMINI_API_KEY", live_env_val)
    env_leak_repo = tmp_path / "env_val_leak"
    el_fn, el_c = _make_cache_entry(f"Echo {live_env_val} in doc.", "Second doc line.")
    _init_git_repo(env_leak_repo, {f"data/gemini_cache/{el_fn}": el_c})
    res_el = verifier.check_secret_and_cache_hygiene(env_leak_repo, expected_cache_count=1)
    assert res_el.status == "FAIL"
    assert any("GEMINI_API_KEY" in d for d in res_el.details)


def test_cross_report_numeric_consistency_catches_tampering(tmp_path):
    syn = tmp_path / "syn_repo"
    (syn / "results" / "v16_social").mkdir(parents=True)
    (syn / "data" / "gemini_cache").mkdir(parents=True)
    (syn / "docs" / "reports").mkdir(parents=True)

    shutil.copy2(
        ROOT / "results" / "v16_social" / "paired_v14_vs_v16_0_9.json",
        syn / "results" / "v16_social" / "paired_v14_vs_v16_0_9.json",
    )
    shutil.copy2(
        ROOT / "results" / "v16_social" / "reference_seeds_30_49.json",
        syn / "results" / "v16_social" / "reference_seeds_30_49.json",
    )
    fn1, c1 = _make_cache_entry("Doc sync on e01.", "Meeting leak check on e02.")
    (syn / "data" / "gemini_cache" / fn1).write_text(c1, encoding="utf-8")

    ledger, errs = verifier.recompute_headline_metrics(syn)
    assert errs == []
    summary_file = syn / "docs" / "reports" / "staffai_social_summary.md"
    summary_file.write_text(_render_synthetic_summary(ledger), encoding="utf-8")

    assert verifier.check_cross_report_consistency(syn).status == "PASS"

    bad_ledger = dict(ledger, v14_opencode_hard_0_9_raw_mean="0.399")
    summary_file.write_text(_render_synthetic_summary(bad_ledger), encoding="utf-8")
    res_bad_num = verifier.check_cross_report_consistency(syn)
    assert res_bad_num.status == "FAIL"
    assert any("v14_opencode_hard_0_9_raw_mean" in d for d in res_bad_num.details)

    summary_file.write_text(
        _render_synthetic_summary(ledger) + "\n Gate B is met now.\n",
        encoding="utf-8",
    )
    res_false_gate = verifier.check_cross_report_consistency(syn)
    assert res_false_gate.status == "FAIL"
    assert any("Gate B is met" in d for d in res_false_gate.details)

    summary_file.write_text(
        _render_synthetic_summary(ledger) + f"\nBad dash {EM_DASH} here.\n",
        encoding="utf-8",
    )
    res_dash = verifier.check_cross_report_consistency(syn)
    assert res_dash.status == "FAIL"
    assert any("dash" in d for d in res_dash.details)

    summary_file.write_text(
        _render_synthetic_summary(ledger, extra_link="[broken](nonexistent_target.md)"),
        encoding="utf-8",
    )
    res_link = verifier.check_cross_report_consistency(syn)
    assert res_link.status == "FAIL"
    assert any("broken relative link" in d for d in res_link.details)

    summary_file.write_text(_render_synthetic_summary(ledger), encoding="utf-8")
    paired_copy_path = syn / "results" / "v16_social" / "paired_v14_vs_v16_0_9.json"
    paired_obj = json.loads(paired_copy_path.read_text(encoding="utf-8"))
    paired_obj["reference_checks"]["solver_v16_mean"] = 0.500
    paired_copy_path.write_text(json.dumps(paired_obj), encoding="utf-8")
    res_cal = verifier.check_cross_report_consistency(syn)
    assert res_cal.status == "FAIL"
    assert any("solver_v14_mean != solver_v16_mean" in d for d in res_cal.details)


def test_zero_comments_zero_em_dashes_and_offline_context(monkeypatch):
    this_test = Path(__file__).resolve()
    for py_path in (SCRIPT_PATH, this_test):
        src = py_path.read_text(encoding="utf-8")
        assert HASH_CHAR not in src, py_path.name
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == [], (py_path.name, comments)

    for path in (SCRIPT_PATH, SUMMARY_MD_PATH, this_test):
        txt = path.read_text(encoding="utf-8")
        assert EM_DASH not in txt and EN_DASH not in txt, path.name

    monkeypatch.setenv("CANARY_OFFLINE", "0")
    monkeypatch.setenv("CANARY_PROVIDER", "v16:v5_full9_cocktail")
    with verifier._force_offline():
        assert os.environ.get("CANARY_OFFLINE") == "1"
        assert "CANARY_PROVIDER" not in os.environ
    assert os.environ.get("CANARY_OFFLINE") == "0"
    assert os.environ.get("CANARY_PROVIDER") == "v16:v5_full9_cocktail"
