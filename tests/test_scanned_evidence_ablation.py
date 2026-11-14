from __future__ import annotations

import copy
import io
import json
import tokenize
from pathlib import Path

import pytest
from PIL import Image

from canary.env import Env
from canary.eval import run_episode
from canary.gemini.memo_vision import (
    MEMO_IMAGE_SIZE,
    VisualMemoEnv,
    memo_sha256,
    render_leak_memo_png,
    verify_history_variants_redacted,
)
from canary.gemini.provenance import COMMIT_RE, _inspect_run, scan_file_secrets
from canary.solver.policy import SolverPolicy
from canary.types import Step
import scripts.run_memo_vision_ablation as ablation_runner

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = REPO_ROOT / "results" / "gemini_roles" / "multimodal_evidence" / "scanned-evidence-ablation-carbon"


def test_dynamic_episode_count_formatting_in_summary_builder() -> None:
    meta = json.loads((RUN_DIR / "meta.json").read_text(encoding="utf-8"))
    comp = json.loads((RUN_DIR / "comparison.json").read_text(encoding="utf-8"))

    for n_ep in (1, 3, 6, 8):
        meta_copy = copy.deepcopy(meta)
        meta_copy["n_episodes"] = n_ep
        rendered = ablation_runner._build_summary_md(meta_copy, comp)
        expected = f"- Episodes per condition: `{n_ep}` (3 conditions x {n_ep} seeds = {3 * n_ep} paired episodes)"
        assert expected in rendered
        assert "\u2014" not in rendered and "\u2013" not in rendered

    committed_summary = (RUN_DIR / "summary.md").read_text(encoding="utf-8")
    assert "- Episodes per condition: `6` (3 conditions x 6 seeds = 18 paired episodes)" in committed_summary
    assert "(3 conditions x 3 seeds = 9 paired episodes)" not in committed_summary
    assert "\u2014" not in committed_summary and "\u2013" not in committed_summary


def test_check_leak_feed_variant_redaction_keyless() -> None:
    oracle_env = Env("medium", 0)
    oracle_ep = run_episode(oracle_env, SolverPolicy())
    assert verify_history_variants_redacted(oracle_ep.steps) is False

    blind_env = VisualMemoEnv(Env("medium", 0), vision_mode="blind", seed_label=0)
    for st in oracle_ep.steps:
        if blind_env.done:
            break
        res = blind_env.call(st.tool, st.args)
        if st.tool == "check_leak_feed" and res.ok:
            for item in res.data.get("items", []):
                assert "variant" not in item

    assert len(blind_env.surfaced_memo_ids()) > 0
    assert verify_history_variants_redacted(blind_env.history) is True

    leaked_step = Step(
        t=0,
        day=5,
        tool="check_leak_feed",
        args={},
        result={"ok": True, "data": {"items": [{"doc_id": "c3", "day_surfaced": 5, "variant": "C"}]}, "error": None},
    )
    null_variant_step = Step(
        t=1,
        day=5,
        tool="check_leak_feed",
        args={},
        result={"ok": True, "data": {"items": [{"doc_id": "d1-1", "day_surfaced": 3, "variant": None}]}, "error": None},
    )
    assert verify_history_variants_redacted([leaked_step]) is False
    assert verify_history_variants_redacted([null_variant_step]) is False

    comp = json.loads((RUN_DIR / "comparison.json").read_text(encoding="utf-8"))
    assert len(comp["per_seed"]) == 6
    for row in comp["per_seed"]:
        assert row["multimodal_carbon"]["text_feed_variants_redacted"] is True
        assert row["blind_no_vision"]["text_feed_variants_redacted"] is True


def test_scanned_evidence_ablation_png_hashes_and_determinism() -> None:
    meta = json.loads((RUN_DIR / "meta.json").read_text(encoding="utf-8"))
    vision_calls = [
        json.loads(line)
        for line in (RUN_DIR / "vision_calls.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    memos = meta["memos"]
    assert len(memos) == 37
    assert len(vision_calls) == len(memos)

    expected_rel_paths = {m["path"] for m in memos}
    actual_rel_paths = {p.relative_to(RUN_DIR).as_posix() for p in (RUN_DIR / "memos").glob("*.png")}
    assert actual_rel_paths == expected_rel_paths

    for m, vc in zip(memos, vision_calls):
        png_path = RUN_DIR / m["path"]
        assert png_path.is_file()
        raw = png_path.read_bytes()
        assert raw[:8] == b"\x89PNG\r\n\x1a\n"
        assert len(raw) == m["bytes"] == vc["memo_bytes"]
        digest = memo_sha256(raw)
        assert digest == m["sha256"] == vc["memo_sha256"]
        with Image.open(io.BytesIO(raw)) as im:
            assert im.format == "PNG"
            assert list(im.size) == m["size"] == vc["memo_size"] == list(MEMO_IMAGE_SIZE)

        rerendered = render_leak_memo_png(
            doc_id=vc["doc_id"],
            day_surfaced=vc["day_surfaced"],
            variant=vc["expected_variant"],
        )
        rerendered_repeat = render_leak_memo_png(
            doc_id=vc["doc_id"],
            day_surfaced=vc["day_surfaced"],
            variant=vc["expected_variant"],
        )
        assert rerendered[:8] == b"\x89PNG\r\n\x1a\n"
        assert memo_sha256(rerendered) == memo_sha256(rerendered_repeat)
        with Image.open(io.BytesIO(rerendered)) as rerendered_im:
            assert rerendered_im.format == "PNG"
            assert list(rerendered_im.size) == list(MEMO_IMAGE_SIZE)
        alt_variant = "B" if vc["expected_variant"] == "A" else "A"
        alt_rendered = render_leak_memo_png(
            doc_id=vc["doc_id"],
            day_surfaced=vc["day_surfaced"],
            variant=alt_variant,
        )
        assert memo_sha256(rerendered) != memo_sha256(alt_rendered)


def test_scanned_evidence_ablation_meta_schema_and_provenance() -> None:
    meta_path = RUN_DIR / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    comp = json.loads((RUN_DIR / "comparison.json").read_text(encoding="utf-8"))

    required_keys = {
        "role",
        "subrole",
        "model_id",
        "tiers_version",
        "tier",
        "seeds",
        "commit",
        "git_sha",
        "timestamp",
        "command",
        "ledger_run_id",
        "n_episodes",
        "n_images_read_by_model",
        "n_canary_memos_read_by_model",
        "variant_vision_accuracy",
        "canary_variant_vision_accuracy",
        "multimodal_mean_score",
        "blind_mean_score",
        "blind_ablation_mean_score",
        "oracle_mean_score",
        "multimodal_accuracy",
        "blind_accuracy",
        "oracle_accuracy",
        "oracle_score_recovery_ratio",
        "memos",
        "usage",
    }
    assert required_keys.issubset(meta.keys())

    assert meta["role"] == "multimodal_evidence"
    assert meta["subrole"] == "visual_memo_blind_ablation"
    assert meta["model_id"] == "gemini-4-carbon"
    assert meta["tiers_version"] == "v1.4"
    assert meta["tier"] == "medium"
    assert meta["seeds"] == [0, 1, 2, 3, 4, 5]
    assert meta["n_episodes"] == 6
    assert COMMIT_RE.fullmatch(meta["commit"])
    assert meta["git_sha"] == meta["commit"] == comp["commit"]
    assert "scanned-evidence-ablation-carbon" in meta["command"]
    assert "--seeds 0,1,2,3,4,5" in meta["command"]

    assert meta["n_images_read_by_model"] == 37
    assert meta["n_canary_memos_read_by_model"] == 10
    assert meta["variant_vision_accuracy"] == 1.0
    assert meta["canary_variant_vision_accuracy"] == 1.0
    assert meta["multimodal_mean_score"] == pytest.approx(meta["oracle_mean_score"])
    assert meta["multimodal_mean_score"] > 0.6
    assert meta["blind_mean_score"] == pytest.approx(0.0)
    assert meta["blind_ablation_mean_score"] == pytest.approx(0.0)
    assert meta["multimodal_accuracy"] == 1.0
    assert meta["blind_accuracy"] == 0.0
    assert meta["oracle_accuracy"] == 1.0
    assert meta["oracle_score_recovery_ratio"] == pytest.approx(1.0)

    usage = meta["usage"]
    assert usage["calls"] == 37
    assert usage["in"] > 0
    assert usage["out"] > 0
    assert usage["cost_usd"] > 0.0
    assert usage["latency_s"] > 0.0

    inspected = _inspect_run(meta_path, REPO_ROOT, REPO_ROOT / "data" / "runs" / "committed" / "v1.4")
    assert inspected["verified"] is True, f"provenance errors: {inspected['errors']}"
    assert inspected["errors"] == []
    assert inspected["secret_leaks"] == []
    assert inspected["role"] == "multimodal_evidence"
    assert inspected["model_id"] == "gemini-4-carbon"
    assert inspected["count"] == 6


def test_owned_files_have_zero_comments_em_dashes_or_secrets() -> None:
    py_targets = [
        REPO_ROOT / "scripts" / "run_memo_vision_ablation.py",
        REPO_ROOT / "tests" / "test_scanned_evidence_ablation.py",
    ]
    for path in py_targets:
        text = path.read_text(encoding="utf-8")
        assert "\u2014" not in text and "\u2013" not in text
        assert chr(35) not in text
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        comments = [t for t in tokens if t.type == tokenize.COMMENT]
        assert comments == []
        assert scan_file_secrets(path, REPO_ROOT) == []

    for artifact in sorted(p for p in RUN_DIR.rglob("*") if p.is_file()):
        assert scan_file_secrets(artifact, REPO_ROOT) == []
        if artifact.suffix in {".json", ".jsonl", ".md"}:
            txt = artifact.read_text(encoding="utf-8")
            assert "\u2014" not in txt and "\u2013" not in txt
