from __future__ import annotations

import io
import json
from pathlib import Path
import tokenize

from canary.social.cache_audit import (
    DEFAULT_JSON_OUT,
    DEFAULT_MD_OUT,
    ROOT,
    audit_committed_cache_files,
    audit_v16_seed_coverage_and_invariance,
    build_full_cache_audit,
)


def test_committed_gemini_cache_inventory_provenance_and_hygiene():
    inv = audit_committed_cache_files()
    assert inv["total_files"] == 256
    assert inv["sha256_filenames"] == 256
    assert inv["real_count"] == 256
    assert inv["gemini_4_carbon_count"] == 256
    assert inv["total_bodies"] == 712
    assert inv["schema_errors"] == 0
    assert inv["secret_hits"] == 0
    assert inv["labels"] == {"REAL": 256}
    assert inv["models"] == {"gemini-4-carbon": 256}


def test_v16_gemini_cache_seed_coverage_canary_invariance_and_solver_parity():
    cov = audit_v16_seed_coverage_and_invariance(seeds=[0, 1, 2, 4, 9])
    by_seed = {r["seed"]: r for r in cov["per_seed"]}
    assert by_seed[0]["prompts_hit"] == 18 and by_seed[0]["full_hit"] is True
    assert by_seed[1]["prompts_hit"] == 18 and by_seed[1]["full_hit"] is True
    assert by_seed[2]["prompts_hit"] == 18 and by_seed[2]["full_hit"] is True
    assert by_seed[4]["prompts_hit"] == 16 and by_seed[4]["prompts_fallback"] == 2
    assert by_seed[9]["prompts_hit"] == 0 and by_seed[9]["prompts_fallback"] == 18

    assert cov["total_lint_errors"] == 0
    assert cov["total_decoy_vocab_errors"] == 0
    assert cov["total_decoy_role_errors"] == 0
    assert cov["total_anger_non_decoy_errors"] == 0

    cpi = cov["canary_planting_invariance"]
    assert cpi["seeds_tested"] == [0, 1, 2]
    assert cpi["prompts_checked"] == 54
    assert cpi["prompts_matched"] == 54
    assert cpi["prompt_match_rate"] == 1.0
    assert cpi["message_match_rate"] == 1.0

    sol = cov["solver_invariance"]
    assert sol["exact_seed_matches"] == 5
    assert abs(sol["calibration_diff"]) < 1e-12
    assert sol["do_nothing_mean"] == 0.0
    assert sol["stop_early_mean"] == 0.0


def test_committed_cache_audit_artifacts_match_recomputation():
    assert DEFAULT_JSON_OUT.is_file()
    assert DEFAULT_MD_OUT.is_file()
    saved = json.loads(DEFAULT_JSON_OUT.read_text(encoding="utf-8"))
    assert saved["passed"] is True
    assert saved["cache_inventory"]["total_files"] == 256
    assert saved["v16_hard_coverage"]["prompts_hit"] == 158
    assert saved["v16_hard_coverage"]["prompts_total"] == 180
    assert saved["v16_hard_coverage"]["full_hit_seeds"] == [0, 1, 2, 3, 5, 6]
    assert saved["v16_hard_coverage"]["canary_planting_invariance"]["prompts_matched"] == 108
    assert saved["v16_hard_coverage"]["canary_planting_invariance"]["prompts_checked"] == 108
    assert saved["v16_hard_coverage"]["solver_invariance"]["solver_template_mean"] == 0.576
    assert saved["v16_hard_coverage"]["solver_invariance"]["solver_v16_gemini_mean"] == 0.576

    md = DEFAULT_MD_OUT.read_text(encoding="utf-8")
    assert "\u2014" not in md and "\u2013" not in md
    assert "158/180" in md and "256" in md and "0.576" in md

    for py_rel in ("canary/social/cache_audit.py", "tests/test_v16_gemini_cache_audit.py"):
        src = (ROOT / py_rel).read_text(encoding="utf-8")
        assert "\u2014" not in src and "\u2013" not in src
        comments = [t for t in tokenize.generate_tokens(io.StringIO(src).readline) if t.type == tokenize.COMMENT]
        assert comments == []
