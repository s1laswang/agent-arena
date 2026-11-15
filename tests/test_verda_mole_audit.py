from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCRIPT_PATH = ROOT / "scripts" / "audit_verda_and_ws3_moles.py"
JSON_PATH = ROOT / "results" / "moletrain" / "verda_ws3_forensics.json"
MD_PATH = ROOT / "docs" / "reports" / "moletrain_verda_audit.md"
TEST_PATH = Path(__file__).resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("audit_verda_and_ws3_moles", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_hygiene_and_artifact_bounds():
    hash_ch = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    for fp in (SCRIPT_PATH, TEST_PATH):
        txt = fp.read_text(encoding="utf-8")
        assert hash_ch not in txt
        assert em_dash not in txt
        assert en_dash not in txt
    for fp in (JSON_PATH, MD_PATH):
        txt = fp.read_text(encoding="utf-8")
        assert em_dash not in txt
        assert en_dash not in txt
    assert JSON_PATH.stat().st_size < 45_000


def test_entropy_valid_reward_and_collapse_step():
    mod = _load_module()
    assert mod.shannon_entropy_nats({"none/decoy": 200}) == 0.0
    assert math.isclose(mod.shannon_entropy_nats({"a": 50, "b": 50}), math.log(2.0), abs_tol=2e-4)
    assert mod.valid_only_step_reward({"valid": 0.0, "reward": -1.0}) is None
    vrew = mod.valid_only_step_reward({"valid": 0.5, "reward": -0.55})
    assert vrew is not None and math.isclose(vrew, -0.10, abs_tol=1e-9)

    rows = []
    for st in range(10):
        rows.append({"step": st, "valid": 0.50, "reward": -0.50, "actions": {"a": 4, "b": 4}})
    for st in range(10, 40):
        rows.append({"step": st, "valid": 1.00, "reward": -0.05, "actions": {"none/decoy": 8}})
    assert mod.compute_collapse_step(rows, window=25, min_valid=0.90, min_top1_share=0.95) == 9
    assert mod.compute_collapse_step(rows, window=25, min_valid=0.90, min_top1_share=0.99) == 10


def test_offline_clean_clone_check_and_tamper_detection(tmp_path: Path):
    mod = _load_module()
    rc = mod.main(
        [
            "--check",
            "--verda-dir",
            str(tmp_path / "missing_verda"),
            "--git-repo",
            str(tmp_path / "missing_git"),
        ]
    )
    assert rc == 0

    bad_md = tmp_path / "tampered.md"
    bad_md.write_text(MD_PATH.read_text(encoding="utf-8") + "\nextra line\n", encoding="utf-8")
    errs = mod.verify_artifacts(
        out_json=JSON_PATH,
        out_md=bad_md,
        verda_dir=tmp_path / "missing_verda",
        git_repo=tmp_path / "missing_git",
    )
    assert any("does not match render_markdown" in e for e in errs)


def test_honesty_verdict_and_forensics_schema():
    doc = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    verdict = doc["honesty_verdict"]
    assert verdict["verdict"] == "negative_collapse_baseline"
    assert verdict["stronger_trained_mole_claimed"] is False
    assert len(doc["grpo_runs"]) == 14
    assert len(doc["verda_heldout_evals"]) == 11
    gem = doc["gemini_4_carbon"]
    assert gem["total_turns"] == 696
    assert gem["valid_turns"] == 696
    assert gem["domain_shift"]["hard"]["judged_nominal_p_leak_gate"] == 0.65
