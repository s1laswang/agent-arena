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
    VisionMemoSolverPolicy,
    VisualMemoEnv,
    memo_sha256,
    run_paired_ablation_seed,
    verify_history_variants_redacted,
)
from canary.gemini.provenance import _inspect_run, scan_file_secrets
from canary.rules import TIERS_VERSION
from canary.solver.policy import SolverPolicy

REPO_ROOT = Path(__file__).resolve().parents[1]
HARD_RUN_DIR = (
    REPO_ROOT
    / "results"
    / "gemini_roles"
    / "multimodal_evidence"
    / "memo-watermark-hard-ablation-carbon"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class StrictPublicEnvProxy:
    def __init__(self, env: Env):
        object.__setattr__(self, "__wrapped_env__", env)

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AssertionError(f"private Env attribute access forbidden: {name}")
        return getattr(object.__getattribute__(self, "__wrapped_env__"), name)


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


def test_v14_hard_tier_params_and_variant_redaction():
    raw_env = Env("hard", 2)
    assert TIERS_VERSION == "v1.4"
    assert raw_env.p.n_employees == 40
    assert raw_env.p.n_days == 21
    assert raw_env.p.canaries_per_day == 2
    assert raw_env.p.max_variants == 3

    strict_proxy = StrictPublicEnvProxy(raw_env)
    vis_env = VisualMemoEnv(
        strict_proxy,
        vision_mode="stub",
        stub_reader=lambda png_bytes, _doc_id: _decode_variant_from_png_pixels(png_bytes),
        seed_label=2,
    )

    with pytest.raises(KeyError):
        vis_env.inspect_memo("c3-2")

    pol = VisionMemoSolverPolicy(vis_env, SolverPolicy(), name="hard_stub")
    ep = run_episode(vis_env, pol)

    emp_steps = [st for st in ep.steps if st.tool == "list_employees"]
    assert emp_steps
    employees = emp_steps[0].result["data"]["employees"]
    assert len(employees) == 40

    canary_steps = [st for st in ep.steps if st.tool == "plant_canary" and st.result.get("ok")]
    assert canary_steps
    canaries_by_day: dict[int, int] = {}
    planted_variant_labels: set[str] = set()
    for st in canary_steps:
        canaries_by_day[st.day] = canaries_by_day.get(st.day, 0) + 1
        assignment = st.args.get("assignment") or {}
        planted_variant_labels.update(assignment.values())
    assert max(canaries_by_day.values()) == 2
    assert planted_variant_labels == {"A", "B", "C"}

    feed_steps = [st for st in ep.steps if st.tool == "check_leak_feed"]
    assert feed_steps
    surfaced_items = [it for st in feed_steps for it in st.result["data"]["items"]]
    assert surfaced_items
    for item in surfaced_items:
        assert "variant" not in item

    assert verify_history_variants_redacted(vis_env.history) is True
    assert verify_history_variants_redacted(ep.steps) is True
    assert ep.correct is True
    assert ep.score > 0.5

    surfaced_ids = vis_env.surfaced_memo_ids()
    assert "c3-2" in surfaced_ids
    assert "c4-2" in surfaced_ids
    assert vis_env.inspect_memo("c3-2")["variant"] == "B"
    assert vis_env.inspect_memo("c4-2")["variant"] == "C"
    assert "expected_variant" not in vis_env.inspect_memo("c3-2")


def test_v14_hard_paired_stub_and_blind_ablation():
    paired = run_paired_ablation_seed(
        0,
        tier="hard",
        vision_mode="stub",
        stub_reader=lambda png_bytes, _doc_id: _decode_variant_from_png_pixels(png_bytes),
    )
    assert paired["tier"] == "hard"
    assert paired["tiers_version"] == "v1.4"

    mm = paired["multimodal_carbon"]
    bl = paired["blind_no_vision"]
    orc = paired["text_oracle"]

    assert mm["text_feed_variants_redacted"] is True
    assert bl["text_feed_variants_redacted"] is True
    assert mm["score"] == pytest.approx(orc["score"])
    assert mm["accused"] == orc["accused"]
    assert mm["correct"] is True
    assert mm["n_canary_memos_inspected"] >= 1
    assert mm["vision_exact_matches"] == mm["n_memos_inspected"]

    assert bl["correct"] is False
    assert bl["score"] == pytest.approx(0.0)
    assert bl["final_day"] == 21
    assert mm["score"] - bl["score"] > 0.5

    canary_variants = {c["expected_variant"] for c in paired["vision_calls"] if c["is_canary_memo"]}
    assert "A" in canary_variants


def test_committed_hard_ablation_bundle_meta_tokens_and_png_sha256s():
    meta_path = HARD_RUN_DIR / "meta.json"
    comp_path = HARD_RUN_DIR / "comparison.json"
    calls_path = HARD_RUN_DIR / "vision_calls.jsonl"
    summary_path = HARD_RUN_DIR / "summary.md"

    assert meta_path.is_file()
    assert comp_path.is_file()
    assert calls_path.is_file()
    assert summary_path.is_file()

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    comp = json.loads(comp_path.read_text(encoding="utf-8"))
    vision_calls = [
        json.loads(line)
        for line in calls_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert meta["role"] == "multimodal_evidence"
    assert meta["subrole"] == "visual_memo_blind_ablation"
    assert meta["model_id"] == "gemini-4-carbon"
    assert meta["tiers_version"] == "v1.4"
    assert meta["tier"] == "hard"
    assert meta["seeds"] == [0, 1, 2, 3, 4]
    assert meta["n_episodes"] == 5

    usage = meta["usage"]
    assert usage["calls"] == meta["n_images_read_by_model"]
    assert usage["calls"] == len(vision_calls)
    assert usage["calls"] > 0
    assert usage["in"] > 0
    assert usage["out"] > 0
    assert usage["cost_usd"] > 0.0

    assert meta["n_canary_memos_read_by_model"] > 0
    assert meta["variant_vision_accuracy"] >= 0.95
    assert meta["canary_variant_vision_accuracy"] >= 0.95
    assert meta["multimodal_mean_score"] > meta["blind_mean_score"]
    assert len(comp["per_seed"]) == 5

    assert len(meta["memos"]) == meta["n_images_read_by_model"]
    sha_by_seed_doc: dict[tuple[int, str], str] = {}
    for m in meta["memos"]:
        png_file = HARD_RUN_DIR / m["path"]
        assert png_file.is_file(), f"missing memo PNG: {png_file}"
        raw = png_file.read_bytes()
        assert raw[:8] == b"\x89PNG\r\n\x1a\n"
        assert len(raw) == m["bytes"]
        assert SHA256_RE.fullmatch(m["sha256"])
        assert memo_sha256(raw) == m["sha256"]
        with Image.open(io.BytesIO(raw)) as im:
            assert im.format == "PNG"
            assert list(im.size) == list(MEMO_IMAGE_SIZE)
            assert m["size"] == list(MEMO_IMAGE_SIZE)
        sha_by_seed_doc[(m["seed"], m["doc_id"])] = m["sha256"]

    for vc in vision_calls:
        assert vc["model_id"] == "gemini-4-carbon"
        assert vc["tier"] == "hard"
        assert vc["usage"]["in"] > 0
        assert vc["usage"]["out"] > 0
        assert SHA256_RE.fullmatch(vc["memo_sha256"])
        assert sha_by_seed_doc[(vc["seed"], vc["doc_id"])] == vc["memo_sha256"]

    inspected = _inspect_run(
        meta_path,
        REPO_ROOT,
        REPO_ROOT / "data" / "runs" / "committed" / "v1.4",
    )
    assert inspected["verified"] is True, f"provenance errors: {inspected['errors']}"
    assert inspected["model_id"] == "gemini-4-carbon"
    assert inspected["tokens_in"] == usage["in"]
    assert inspected["tokens_out"] == usage["out"]
    assert inspected["secret_leaks"] == []


def test_owned_files_have_no_comments_dashes_or_secrets():
    py_path = Path(__file__).resolve()
    py_text = py_path.read_text(encoding="utf-8")
    assert "\u2014" not in py_text and "\u2013" not in py_text
    assert chr(35) not in py_text
    tokens = list(tokenize.generate_tokens(io.StringIO(py_text).readline))
    comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
    assert comments == []
    assert scan_file_secrets(py_path, REPO_ROOT) == []

    for artifact in sorted(p for p in HARD_RUN_DIR.rglob("*") if p.is_file()):
        assert scan_file_secrets(artifact, REPO_ROOT) == []
        if artifact.suffix in {".json", ".jsonl", ".md"}:
            txt = artifact.read_text(encoding="utf-8")
            assert "\u2014" not in txt and "\u2013" not in txt
