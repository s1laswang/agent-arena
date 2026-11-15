from __future__ import annotations

import io
import json
import re
import tokenize
from pathlib import Path

import pytest
from PIL import Image

from canary.env import Env
from canary.eval import run_episode
from canary.gemini.memo_vision import (
    MEMO_IMAGE_SIZE,
    VALID_VARIANTS,
    VisualMemoEnv,
    memo_sha256,
    render_leak_memo_png,
    run_paired_ablation_seed,
    verify_history_variants_redacted,
)
from canary.gemini.provenance import COMMIT_RE, _inspect_run, scan_file_secrets
from canary.solver.policy import SolverPolicy

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = (
    REPO_ROOT
    / "results"
    / "gemini_roles"
    / "multimodal_evidence"
    / "memo-watermark-hard-seeds10to14-carbon"
)
HARD_0TO4_DIR = (
    REPO_ROOT
    / "results"
    / "gemini_roles"
    / "multimodal_evidence"
    / "memo-watermark-hard-ablation-carbon"
)
HARD_5TO9_DIR = (
    REPO_ROOT
    / "results"
    / "gemini_roles"
    / "multimodal_evidence"
    / "memo-watermark-hard-seeds5to9-carbon"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _decode_variant_from_png_pixels(png_bytes: bytes) -> str | None:
    with Image.open(io.BytesIO(png_bytes)) as im:
        rgb = im.convert("RGB")
        footer_bg = (28, 35, 48)
        active_ticks = 0
        for idx in range(1, 9):
            px = rgb.getpixel((74 + (idx - 1) * 88, 516))
            if px != footer_bg:
                active_ticks += 1
        if active_ticks == 0:
            return None
        return VALID_VARIANTS[active_ticks - 1]


def test_hard_seeds10to14_pngs_magic_dimensions_and_deterministic_sha256() -> None:
    meta = json.loads((RUN_DIR / "meta.json").read_text(encoding="utf-8"))
    comp = json.loads((RUN_DIR / "comparison.json").read_text(encoding="utf-8"))
    vision_calls = [
        json.loads(line)
        for line in (RUN_DIR / "vision_calls.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    memos = meta["memos"]
    assert len(memos) == 39
    assert len(vision_calls) == len(memos)
    assert comp["memos"] == memos
    assert comp["vision_calls"] == vision_calls

    expected_rel_paths = {m["path"] for m in memos}
    actual_rel_paths = {p.relative_to(RUN_DIR).as_posix() for p in (RUN_DIR / "memos").glob("*.png")}
    assert actual_rel_paths == expected_rel_paths

    sha_by_content_key: dict[tuple[str, int, str | None], str] = {}
    for m, vc in zip(memos, vision_calls):
        assert m["seed"] == vc["seed"]
        assert m["doc_id"] == vc["doc_id"]
        assert m["day_surfaced"] == vc["day_surfaced"]
        assert m["is_canary_memo"] == vc["is_canary_memo"]
        assert m["path"] == vc["memo_path"]

        png_path = RUN_DIR / m["path"]
        assert png_path.is_file(), f"missing rendered memo PNG: {png_path}"
        raw = png_path.read_bytes()
        assert raw[:8] == b"\x89PNG\r\n\x1a\n"
        assert len(raw) == m["bytes"] == vc["memo_bytes"]

        digest = memo_sha256(raw)
        assert SHA256_RE.fullmatch(digest)
        assert digest == m["sha256"] == vc["memo_sha256"]

        with Image.open(io.BytesIO(raw)) as im:
            assert im.format == "PNG"
            assert list(im.size) == m["size"] == vc["memo_size"] == list(MEMO_IMAGE_SIZE)

        content_key = (vc["doc_id"], vc["day_surfaced"], vc["expected_variant"])
        if content_key in sha_by_content_key:
            assert sha_by_content_key[content_key] == digest
        else:
            sha_by_content_key[content_key] = digest

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
        assert _decode_variant_from_png_pixels(raw) == vc["expected_variant"]
        assert _decode_variant_from_png_pixels(rerendered) == vc["expected_variant"]

        alt_variant = "B" if vc["expected_variant"] == "A" else "A"
        alt_rendered = render_leak_memo_png(
            doc_id=vc["doc_id"],
            day_surfaced=vc["day_surfaced"],
            variant=alt_variant,
        )
        assert memo_sha256(rerendered) != memo_sha256(alt_rendered)


def test_hard_seeds10to14_check_leak_feed_variant_redaction(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)

    comp = json.loads((RUN_DIR / "comparison.json").read_text(encoding="utf-8"))
    assert [row["seed"] for row in comp["per_seed"]] == [10, 11, 12, 13, 14]

    for row in comp["per_seed"]:
        seed = row["seed"]
        assert row["tier"] == "hard"
        assert row["tiers_version"] == "v1.4"
        assert row["multimodal_carbon"]["text_feed_variants_redacted"] is True
        assert row["blind_no_vision"]["text_feed_variants_redacted"] is True

        oracle_ep = run_episode(Env("hard", seed), SolverPolicy())
        assert verify_history_variants_redacted(oracle_ep.steps) is False

        paired = run_paired_ablation_seed(
            seed,
            tier="hard",
            vision_mode="stub",
            stub_reader=lambda png_bytes, _doc_id: _decode_variant_from_png_pixels(png_bytes),
        )
        assert paired["multimodal_carbon"]["text_feed_variants_redacted"] is True
        assert paired["blind_no_vision"]["text_feed_variants_redacted"] is True
        assert paired["multimodal_carbon"]["score"] == pytest.approx(row["multimodal_carbon"]["score"])
        assert paired["blind_no_vision"]["score"] == pytest.approx(row["blind_no_vision"]["score"])
        assert paired["text_oracle"]["score"] == pytest.approx(row["text_oracle"]["score"])

    blind_env = VisualMemoEnv(Env("hard", 11), vision_mode="blind", seed_label=11)
    oracle_seed11 = run_episode(Env("hard", 11), SolverPolicy())
    for st in oracle_seed11.steps:
        if blind_env.done:
            break
        res = blind_env.call(st.tool, st.args)
        if st.tool == "check_leak_feed" and res.ok:
            for item in res.data.get("items", []):
                assert "variant" not in item
    assert len(blind_env.surfaced_memo_ids()) == 4
    assert verify_history_variants_redacted(blind_env.history) is True


def test_hard_seeds10to14_meta_schema_and_provenance() -> None:
    meta_path = RUN_DIR / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    comp = json.loads((RUN_DIR / "comparison.json").read_text(encoding="utf-8"))
    summary_md = (RUN_DIR / "summary.md").read_text(encoding="utf-8")
    vision_calls = [
        json.loads(line)
        for line in (RUN_DIR / "vision_calls.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

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
    assert meta["tier"] == "hard"
    assert meta["seeds"] == [10, 11, 12, 13, 14]
    assert meta["n_episodes"] == 5
    assert COMMIT_RE.fullmatch(meta["commit"])
    assert meta["git_sha"] == meta["commit"] == comp["commit"]
    assert "memo-watermark-hard-seeds10to14-carbon" in meta["command"]
    assert "--tier hard" in meta["command"]
    assert "--seeds 10,11,12,13,14" in meta["command"]
    assert "- Episodes per condition: `5` (3 conditions x 5 seeds = 15 paired episodes)" in summary_md

    assert meta["n_images_read_by_model"] == 39
    assert meta["n_canary_memos_read_by_model"] == 6
    assert meta["variant_vision_accuracy"] == 1.0
    assert meta["canary_variant_vision_accuracy"] == 1.0
    assert meta["multimodal_mean_score"] == pytest.approx(0.376)
    assert meta["oracle_mean_score"] == pytest.approx(0.376)
    assert meta["multimodal_mean_score"] == pytest.approx(meta["oracle_mean_score"])
    assert meta["blind_mean_score"] == pytest.approx(0.234)
    assert meta["multimodal_mean_score"] > meta["blind_mean_score"]
    assert meta["blind_ablation_mean_score"] == pytest.approx(meta["blind_mean_score"])
    assert meta["multimodal_accuracy"] == 1.0
    assert meta["blind_accuracy"] == pytest.approx(0.6)
    assert meta["oracle_accuracy"] == 1.0
    assert meta["oracle_score_recovery_ratio"] == pytest.approx(1.0)

    canary_variants = {vc["expected_variant"] for vc in vision_calls if vc["is_canary_memo"]}
    assert canary_variants == {"A", "B", "C"}

    usage = meta["usage"]
    assert usage["calls"] == 39
    assert usage["in"] == sum(vc["usage"]["in"] for vc in vision_calls)
    assert usage["out"] == sum(vc["usage"]["out"] for vc in vision_calls)
    assert usage["thinking"] == sum(vc["usage"]["thinking"] for vc in vision_calls)
    assert usage["in"] > 0
    assert usage["out"] > 0
    assert usage["thinking"] > 0
    assert usage["cost_usd"] > 0.0
    assert usage["latency_s"] > 0.0

    for vc in vision_calls:
        assert vc["model_id"] == "gemini-4-carbon"
        assert vc["tier"] == "hard"
        assert vc["variant_exact_match"] is True
        assert vc["model_response"]["observed_doc_id"] == vc["doc_id"]
        assert vc["model_response"]["observed_day_surfaced"] == vc["day_surfaced"]
        assert vc["usage"]["in"] > 0
        assert vc["usage"]["out"] > 0

    inspected = _inspect_run(
        meta_path,
        REPO_ROOT,
        REPO_ROOT / "data" / "runs" / "committed" / "v1.4",
    )
    assert inspected["verified"] is True, f"provenance errors: {inspected['errors']}"
    assert inspected["errors"] == []
    assert inspected["secret_leaks"] == []
    assert inspected["role"] == "multimodal_evidence"
    assert inspected["model_id"] == "gemini-4-carbon"
    assert inspected["count"] == 5
    assert inspected["tokens_in"] == usage["in"]
    assert inspected["tokens_out"] == usage["out"]

    if (HARD_0TO4_DIR / "meta.json").is_file() and (HARD_5TO9_DIR / "meta.json").is_file():
        m0 = json.loads((HARD_0TO4_DIR / "meta.json").read_text(encoding="utf-8"))
        m5 = json.loads((HARD_5TO9_DIR / "meta.json").read_text(encoding="utf-8"))
        pooled_hard_seeds = m0["seeds"] + m5["seeds"] + meta["seeds"]
        assert pooled_hard_seeds == list(range(15))


def test_owned_files_have_zero_comments_em_dashes_or_secrets() -> None:
    py_targets = [
        REPO_ROOT / "canary" / "gemini" / "memo_vision.py",
        REPO_ROOT / "scripts" / "run_memo_vision_ablation.py",
        Path(__file__).resolve(),
    ]
    for path in py_targets:
        text = path.read_text(encoding="utf-8")
        assert "\u2014" not in text and "\u2013" not in text
        assert chr(35) not in text
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == []
        assert scan_file_secrets(path, REPO_ROOT) == []

    for artifact in sorted(p for p in RUN_DIR.rglob("*") if p.is_file()):
        assert scan_file_secrets(artifact, REPO_ROOT) == []
        if artifact.suffix in {".json", ".jsonl", ".md"}:
            txt = artifact.read_text(encoding="utf-8")
            assert "\u2014" not in txt and "\u2013" not in txt
