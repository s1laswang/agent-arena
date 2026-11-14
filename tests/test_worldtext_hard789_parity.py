from __future__ import annotations

import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import tokenize

import pytest

from canary.agents.world_builder import GeminiWorldText, assert_no_truth
from canary.env import Env
from canary.eval import run_episode
from canary.gemini.leak_encodings import (
    audit_env_outputs,
    extract_env_secrets,
    scan_text_for_secret,
)
from canary.gemini.provenance import _inspect_run, scan_file_secrets
from canary.gemini.roles_dashboard import _scan_run_for_secrets
from canary.solver.policy import SolverPolicy
from canary.text.lint import lint_messages, lint_text

ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "results" / "gemini_roles" / "world_text" / "carbon-v14-hard789"
SCRIPT_PATH = ROOT / "scripts" / "run_worldtext_3tier_parity.py"
EXPECTED_SPECS: tuple[tuple[str, int], ...] = (
    ("hard", 7),
    ("hard", 8),
    ("hard", 9),
)
HEX40_RE = re.compile(r"^[0-9a-f]{40}$")


@pytest.fixture(autouse=True)
def _hermetic_keyless_env(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "ledger.jsonl"))


def test_hard789_run_meta_and_provenance() -> None:
    assert RUN_DIR.is_dir()
    meta_files = sorted(RUN_DIR.rglob("meta.json"))
    assert meta_files == [RUN_DIR / "meta.json"]

    for fname in (
        "meta.json",
        "samples.json",
        "summary.md",
        "parity_audit_24worlds.json",
        "parity_audit_24worlds.md",
    ):
        fpath = RUN_DIR / fname
        assert fpath.is_file(), f"missing {fname}"
        raw = fpath.read_text(encoding="utf-8")
        assert raw.strip(), f"empty {fname}"
        assert "\u2014" not in raw, f"em dash in {fname}"
        assert "\u2013" not in raw, f"en dash in {fname}"
        assert scan_file_secrets(fpath, ROOT) == []

    for fp in sorted(p for p in RUN_DIR.rglob("*") if p.is_file()):
        txt = fp.read_text(encoding="utf-8")
        assert "\u2014" not in txt, f"em dash in {fp}"
        assert "\u2013" not in txt, f"en dash in {fp}"
        assert scan_file_secrets(fp, ROOT) == []

    assert _scan_run_for_secrets(RUN_DIR) is False

    meta = json.loads((RUN_DIR / "meta.json").read_text(encoding="utf-8"))
    assert meta["role"] == "world_text"
    assert meta["subrole"] == "company_personas_chatter"
    assert meta["model_id"] == "gemini-4-carbon"
    assert meta["llm_spec"] == "gemini:gemini-4-carbon"
    assert meta["tiers_version"] == "v1.4"
    assert HEX40_RE.match(meta["commit"]), f"invalid 40-char commit: {meta['commit']}"
    assert meta["timestamp"]
    assert meta["command"]
    assert meta["n_worlds"] == 3
    assert meta["llm_ok_count"] == 3
    assert meta["gemini_provider_fallbacks"] == 0
    assert meta["truth_leak_violations"] == 0
    assert meta["lint_violations"] == 0
    assert meta["n_personas_generated"] == 120
    assert meta["n_llm_personas"] == 120
    assert meta["n_interviews_generated"] == 6
    assert meta["n_day_messages_generated"] >= 30
    assert meta["solver_all_clean"] is True
    assert meta["solver_episodes_verified"] == 3
    assert meta["solver_accuracy"] == 1.0
    assert meta["world_specs"] == [{"tier": t, "seed": s} for t, s in EXPECTED_SPECS]

    usage = meta["usage"]
    assert usage["calls"] >= 15
    assert usage["in"] > 0
    assert usage["out"] > 0
    assert usage["thinking"] > 0
    assert usage["total_tokens"] >= usage["in"] + usage["out"]
    assert usage["cost_usd"] > 0.0

    prov = _inspect_run(RUN_DIR / "meta.json", ROOT, ROOT / "data" / "runs" / "committed" / "v1.4")
    assert prov["verified"] is True, f"provenance failed: {prov}"
    assert prov["errors"] == []


def test_hard789_samples_and_summary_pass_truth_lint_and_secret_scans() -> None:
    summary_raw = (RUN_DIR / "summary.md").read_text(encoding="utf-8")
    assert_no_truth(summary_raw, {})

    samples = json.loads((RUN_DIR / "samples.json").read_text(encoding="utf-8"))
    assert samples["role"] == "world_text"
    assert samples["subrole"] == "company_personas_chatter"
    assert samples["model_id"] == "gemini-4-carbon"
    assert samples["tiers_version"] == "v1.4"
    assert samples["n_worlds"] == 3
    assert len(samples["worlds"]) == 3
    assert [(w["tier"], int(w["seed"])) for w in samples["worlds"]] == list(EXPECTED_SPECS)

    for w in samples["worlds"]:
        tier = str(w["tier"])
        seed = int(w["seed"])
        env = Env(tier, seed)
        world = env._world
        mole_id = world.mole
        _, world_secrets = extract_env_secrets(env)
        secret_targets = [mole_id, *world_secrets]

        assert_no_truth(w, world)
        assert scan_text_for_secret(w, world_secrets) == []

        wb = w["world_builder"]
        assert wb["llm_ok"] is True
        assert wb["n_fallback_personas"] == 0
        assert wb["n_personas"] == 40
        assert wb["n_llm_personas"] == 40

        prose_items = (
            [wb["company_blurb"]]
            + [p["bio"] for p in wb["sample_personas"]]
            + [d["culture"] for d in wb["departments"]]
            + list(wb["sample_chatter_templates"])
        )
        for text_item in prose_items:
            assert lint_text(text_item) == []
            assert_no_truth(text_item, world)
            assert scan_text_for_secret(text_item, secret_targets) == []

        sample_rendered = wb["sample_rendered_day1_messages"]
        assert lint_messages(sample_rendered) == []
        assert_no_truth(sample_rendered, world)
        assert scan_text_for_secret(sample_rendered, world_secrets) == []

        gp = w["gemini_provider"]
        assert gp["fallbacks"] == 0
        for msg_batch in (gp["day1_messages"], gp["day2_messages"]):
            assert len(msg_batch) >= 5
            assert lint_messages(msg_batch) == []
            assert_no_truth(msg_batch, world)
            assert scan_text_for_secret(msg_batch, world_secrets) == []

        combined_gp_msgs = list(gp["day1_messages"]) + list(gp["day2_messages"])
        assert scan_text_for_secret(combined_gp_msgs, world_secrets) == []

        iv_answers = [
            gp["interviews"]["cooperative"]["answer"],
            gp["interviews"]["evasive"]["answer"],
        ]
        for ans in iv_answers:
            assert ans.strip()
            assert lint_text(ans) == []
            assert_no_truth(ans, world)
            assert scan_text_for_secret(ans, secret_targets) == []
        assert scan_text_for_secret(iv_answers, secret_targets) == []

        assert w["integrity"]["truth_leak_violations"] == 0
        assert w["integrity"]["lint_violations"] == 0
        assert w["solver_verification"]["clean_run"] is True
        assert w["solver_verification"]["correct"] is True


@pytest.mark.parametrize(("tier", "seed"), EXPECTED_SPECS)
def test_hard789_world_files_pass_truth_lint_secret_scan_and_solver(tier: str, seed: int) -> None:
    wt_path = RUN_DIR / "worlds" / tier / f"{seed}.worldtext.json"
    tx_path = RUN_DIR / "worlds" / tier / f"{seed}.text.json"
    assert wt_path.is_file(), f"missing {wt_path}"
    assert tx_path.is_file(), f"missing {tx_path}"

    wt_raw = wt_path.read_text(encoding="utf-8")
    tx_raw = tx_path.read_text(encoding="utf-8")
    for fp, raw in ((wt_path, wt_raw), (tx_path, tx_raw)):
        assert "\u2014" not in raw and "\u2013" not in raw
        assert scan_file_secrets(fp, ROOT) == []

    wt = json.loads(wt_raw)
    tx = json.loads(tx_raw)

    ref_env = Env(tier, seed)
    world = ref_env._world
    mole_id = world.mole
    _, world_secrets = extract_env_secrets(ref_env)
    secret_targets = [mole_id, *world_secrets]

    assert wt["meta"]["llm_ok"] is True
    assert wt["meta"]["n_fallback_personas"] == 0
    assert len(wt["personas"]) == 40
    assert len(world.employees) == 40

    assert_no_truth(wt, world)
    assert_no_truth(tx, world)
    assert scan_text_for_secret(wt, world_secrets) == []
    assert scan_text_for_secret(tx, world_secrets) == []

    wt_strings = (
        [wt["company_blurb"]]
        + [p["bio"] for p in wt["personas"]]
        + [d["culture"] for d in wt["departments"]]
        + list(wt["chatter_templates"])
    )
    for item in wt_strings:
        assert item.strip()
        assert lint_text(item) == []
        assert_no_truth(item, world)
        assert scan_text_for_secret(item, secret_targets) == []

    assert set(tx["days"]) == {"1", "2"}
    assert len(tx["interviews"]) == 2
    for day_key in ("1", "2"):
        msgs = tx["days"][day_key]
        assert len(msgs) >= 5
        assert lint_messages(msgs) == []
        assert_no_truth(msgs, world)
        assert scan_text_for_secret(msgs, world_secrets) == []

    all_day_msgs = list(tx["days"]["1"]) + list(tx["days"]["2"])
    assert lint_messages(all_day_msgs) == []
    assert scan_text_for_secret(all_day_msgs, world_secrets) == []

    assert any("|cooperative|" in k for k in tx["interviews"])
    assert any("|evasive|" in k for k in tx["interviews"])
    iv_values = list(tx["interviews"].values())
    for ans in iv_values:
        assert ans.strip()
        assert lint_text(ans) == []
        assert_no_truth(ans, world)
        assert scan_text_for_secret(ans, secret_targets) == []
    assert scan_text_for_secret(iv_values, secret_targets) == []

    provider = GeminiWorldText(wt, name="gemini-world:gemini-4-carbon")
    solver_env = Env(tier, seed, text_provider=provider)
    ep = run_episode(solver_env, SolverPolicy())
    assert solver_env.done
    assert ep.end_reason != "error"
    assert ep.correct is True
    env_msgs = list(solver_env._messages.values())
    assert lint_messages(env_msgs) == []
    assert_no_truth(env_msgs, world)
    assert scan_text_for_secret(env_msgs, world_secrets) == []
    assert audit_env_outputs(solver_env, step_episode=False) == []


def test_parity_audit_24worlds_json_and_md() -> None:
    audit_json_fp = RUN_DIR / "parity_audit_24worlds.json"
    audit_md_fp = RUN_DIR / "parity_audit_24worlds.md"
    assert audit_json_fp.is_file()
    assert audit_md_fp.is_file()

    report = json.loads(audit_json_fp.read_text(encoding="utf-8"))
    md_text = audit_md_fp.read_text(encoding="utf-8")

    assert "**PASS**" in md_text
    assert "Unified 24-World 3-Tier Non-Leak and SolverPolicy Parity Audit" in md_text
    assert_no_truth(report, {})
    assert_no_truth(md_text, {})

    assert report["ok"] is True
    assert report["passed"] is True
    assert report["model_id"] == "gemini-4-carbon"
    assert report["tiers_version"] == "v1.4"
    assert report["n_worlds"] == 24
    assert report["llm_ok_worlds"] == 24
    assert report["n_personas_total"] == 648
    assert "results/gemini_roles/world_text/carbon-v14-hard789/worlds" in report["source_dirs"]

    assert report["non_leak"]["ok"] is True
    assert report["non_leak"]["n_truth_violations"] == 0
    assert report["non_leak"]["n_lint_violations"] == 0
    assert report["non_leak"]["n_leak_encoding_violations"] == 0
    assert report["non_leak"]["missing_files"] == []
    assert report["non_leak"]["text_leak_any"] is False

    assert report["solver_parity"]["ok"] is True
    assert report["solver_parity"]["n"] == 24
    assert report["solver_parity"]["world_catch_rate"] >= 0.90

    le = report["leak_encodings"]
    assert le["ok"] is True
    assert le["n_supported_encodings"] == 37
    assert le["n_worlds_scanned"] == 24
    assert le["n_worldtext_files_scanned"] == 24
    assert le["n_text_files_scanned"] == 24
    assert le["n_personas_scanned"] == 648
    assert le["n_violations"] == 0
    assert le["violations"] == []
    assert len(le["per_world"]) == 24
    for pw in le["per_world"]:
        assert pw["clean"] is True
        assert pw["llm_ok"] is True

    expected_tiers = {
        "easy": (4, [0, 1, 2, 3], 48),
        "medium": (10, list(range(10)), 200),
        "hard": (10, list(range(10)), 400),
    }
    assert set(report["tiers"].keys()) == set(expected_tiers.keys())
    for tier, (exp_n, exp_seeds, exp_personas) in expected_tiers.items():
        tr = report["tiers"][tier]
        assert tr["ok"] is True
        assert tr["passed"] is True
        assert tr["n"] == exp_n
        assert tr["n_seeds"] == exp_n
        assert tr["seeds"] == exp_seeds
        assert tr["n_personas"] == exp_personas
        assert tr["non_leak"]["ok"] is True
        assert tr["non_leak"]["n_truth_violations"] == 0
        assert tr["non_leak"]["n_lint_violations"] == 0
        assert tr["non_leak"]["text_probe"]["text_leak"] is False
        assert tr["solver_parity"]["ok"] is True
        assert tr["solver_parity"]["n"] == exp_n
        assert tr["leak_encodings_ok"] is True
        assert tr["leak_encoding_violations"] == 0
        for row in tr["per_seed"]:
            src_rel = str(row["source_path"])
            assert not src_rel.startswith("/tmp")
            assert (ROOT / src_rel).is_file()


def test_parity_script_24worlds_preset_runs_keyless_under_15s(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["GEMINI_API_KEY"] = ""
    env["GOOGLE_API_KEY"] = ""
    env["GOOGLE_GENERATIVE_AI_API_KEY"] = ""
    env.pop("GEMINI_GATEWAY_URL", None)
    env["PYTHONPATH"] = str(ROOT)

    t0 = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--preset", "24worlds", "--out-dir", str(tmp_path)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    elapsed = time.perf_counter() - t0
    assert proc.returncode == 0, f"stderr={proc.stderr}\nstdout={proc.stdout}"
    assert elapsed < 15.0, f"expected <15s keyless runtime, took {elapsed:.2f}s"

    out_summary = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out_summary["ok"] is True
    assert out_summary["n_worlds"] == 24
    assert out_summary["n_personas_total"] == 648

    saved = json.loads((tmp_path / "parity_audit_24worlds.json").read_text(encoding="utf-8"))
    assert saved["ok"] is True
    assert saved["non_leak"]["ok"] is True
    assert saved["solver_parity"]["ok"] is True
    assert saved["tiers"]["easy"]["n"] == 4 and saved["tiers"]["easy"]["ok"] is True
    assert saved["tiers"]["medium"]["n"] == 10 and saved["tiers"]["medium"]["ok"] is True
    assert saved["tiers"]["hard"]["n"] == 10 and saved["tiers"]["hard"]["ok"] is True
    assert (tmp_path / "parity_audit_24worlds.md").is_file()
    assert not (tmp_path / "meta.json").exists()


def test_source_files_have_no_comments_em_dashes_or_secrets() -> None:
    targets = [
        SCRIPT_PATH,
        Path(__file__).resolve(),
    ]
    for fpath in targets:
        src = fpath.read_text(encoding="utf-8")
        assert "\u2014" not in src, f"em dash in {fpath}"
        assert "\u2013" not in src, f"en dash in {fpath}"
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == [], f"found comment in {fpath}: {comments}"
        assert scan_file_secrets(fpath, ROOT) == []
