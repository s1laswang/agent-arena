from __future__ import annotations

import io
import json
import tokenize
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from canary.env import Env
from canary.eval import run_episode
from canary.gemini.ledger import read_ledger
from canary.gemini.memo_vision import (
    MEMO_IMAGE_SIZE,
    MEMO_VISION_SCHEMA,
    VALID_VARIANTS,
    VisionMemoSolverPolicy,
    VisualMemoEnv,
    extract_public_memo_fields,
    inspect_memo_png,
    memo_sha256,
    render_leak_memo_from_item,
    render_leak_memo_png,
    run_paired_ablation_seed,
    verify_history_variants_redacted,
)
from canary.gemini.provenance import _inspect_run, scan_file_secrets
from canary.llm.base import MissingKeyError
from canary.solver.policy import SolverPolicy
import scripts.run_memo_vision_ablation as ablation_runner


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


class FakeDynamicModelsAPI:
    def __init__(self, scripted: list | None = None):
        self._scripted = list(scripted) if scripted is not None else None
        self.calls: list[dict] = []

    def generate_content(self, *, model: str, contents: list, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self._scripted is not None:
            nxt = self._scripted.pop(0)
            if isinstance(nxt, BaseException):
                raise nxt
            return nxt
        img_part = contents[0]
        png_bytes = img_part.inline_data.data
        decoded = _decode_variant_from_png_pixels(png_bytes)
        ticks = (VALID_VARIANTS.index(decoded) + 1) if decoded else 0
        payload = {
            "observed_doc_id": "scanned_doc",
            "observed_day_surfaced": 5,
            "has_canary_watermark": decoded is not None,
            "copy_code_variant": decoded if decoded is not None else "NONE",
            "observed_footer_ticks": ticks,
            "confidence": 0.99,
            "visual_evidence": f"Header bar {ticks} segments, stamp COPY-CODE: {decoded or 'NONE'}, {ticks} footer ticks.",
        }
        um = SimpleNamespace(
            prompt_token_count=640,
            candidates_token_count=92,
            thoughts_token_count=180,
            cached_content_token_count=0,
        )
        return SimpleNamespace(text=json.dumps(payload), usage_metadata=um, model_version="gemini-4-carbon")


class FakeSDKClient:
    def __init__(self, scripted: list | None = None):
        self.models = FakeDynamicModelsAPI(scripted=scripted)


def _fake_response(payload: dict | str, *, tin: int = 610, tout: int = 88, thoughts: int = 150):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    um = SimpleNamespace(
        prompt_token_count=tin,
        candidates_token_count=tout,
        thoughts_token_count=thoughts,
        cached_content_token_count=0,
    )
    return SimpleNamespace(text=text, usage_metadata=um, model_version="gemini-4-carbon")


def _crop_bytes(png_bytes: bytes, box: tuple[int, int, int, int]) -> bytes:
    with Image.open(io.BytesIO(png_bytes)) as im:
        return im.crop(box).tobytes()


def test_memo_rendering_visual_channels_and_determinism():
    item_a = {"doc_id": "c6", "surfaced_day": 9, "variant": "A", "title": "Ignored extra field"}
    pub = extract_public_memo_fields(item_a)
    assert pub == {"doc_id": "c6", "day_surfaced": 9, "variant": "A"}

    png_a1 = render_leak_memo_from_item(item_a)
    png_a2 = render_leak_memo_png(doc_id="c6", day_surfaced=9, variant="A")
    assert png_a1[:8] == b"\x89PNG\r\n\x1a\n"
    assert memo_sha256(png_a1) == memo_sha256(png_a2)

    with Image.open(io.BytesIO(png_a1)) as im:
        assert im.format == "PNG"
        assert im.size == MEMO_IMAGE_SIZE

    png_none = render_leak_memo_png(doc_id="c6", day_surfaced=9, variant=None)
    png_b = render_leak_memo_png(doc_id="c6", day_surfaced=9, variant="B")
    png_c = render_leak_memo_png(doc_id="c6", day_surfaced=9, variant="C")

    header_box = (46, 38, 834, 108)
    stamp_box = (424, 176, 832, 398)
    footer_box = (46, 476, 834, 582)

    for region in (header_box, stamp_box, footer_box):
        crops = {_crop_bytes(p, region) for p in (png_none, png_a1, png_b, png_c)}
        assert len(crops) == 4

    assert _decode_variant_from_png_pixels(png_none) is None
    for v in ("A", "B", "C", "D", "E", "F", "G", "H"):
        rendered = render_leak_memo_png(doc_id="c4", day_surfaced=6, variant=v)
        assert _decode_variant_from_png_pixels(rendered) == v


def test_visual_memo_env_never_reads_private_world_and_redacts_text_variants():
    raw_env = Env("medium", 5)
    strict_proxy = StrictPublicEnvProxy(raw_env)
    vis_env = VisualMemoEnv(
        strict_proxy,
        vision_mode="stub",
        stub_reader=lambda png_bytes, _doc_id: _decode_variant_from_png_pixels(png_bytes),
        seed_label=5,
    )

    with pytest.raises(KeyError):
        vis_env.inspect_memo("c3")

    pol = VisionMemoSolverPolicy(vis_env, SolverPolicy())
    ep = run_episode(vis_env, pol)

    assert ep.correct is True
    assert ep.score > 0.7
    assert verify_history_variants_redacted(vis_env.history) is True
    assert verify_history_variants_redacted(ep.steps) is True

    surfaced_ids = vis_env.surfaced_memo_ids()
    assert "c3" in surfaced_ids
    pub_inspect = vis_env.inspect_memo("c3")
    assert pub_inspect["variant"] == "C"
    assert "expected_variant" not in pub_inspect


def test_inspect_memo_png_uses_part_from_bytes_and_records_ledger(tmp_path, monkeypatch):
    ledger_file = tmp_path / "memo_ledger.jsonl"
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(ledger_file))

    png_bytes = render_leak_memo_png(doc_id="c5", day_surfaced=8, variant="C")
    fake_sdk = FakeSDKClient(scripted=[
        _fake_response({
            "observed_doc_id": "c5",
            "observed_day_surfaced": 8,
            "has_canary_watermark": True,
            "copy_code_variant": "c",
            "observed_footer_ticks": 3,
            "confidence": 0.98,
            "visual_evidence": "3 header segments\u2014stamp COPY-CODE: C\u20133 footer ticks active.",
        }),
    ])

    res = inspect_memo_png(
        png_bytes,
        model_id="gemini-4-carbon",
        sdk_client=fake_sdk,
        run_id="memo-unit-run",
        seed=4,
    )
    assert len(fake_sdk.models.calls) == 1
    call = fake_sdk.models.calls[0]
    assert call["model"] == "gemini-4-carbon"
    img_part, prompt_part = call["contents"]
    assert img_part.inline_data.mime_type == "image/png"
    assert img_part.inline_data.data == png_bytes
    assert isinstance(prompt_part, str) and "COPY-CODE" in prompt_part
    assert call["config"].response_mime_type == "application/json"
    assert call["config"].response_json_schema == MEMO_VISION_SCHEMA

    assert res["variant"] == "C"
    assert "\u2014" not in res["model_response"]["visual_evidence"]
    assert "\u2013" not in res["model_response"]["visual_evidence"]

    rows = read_ledger([ledger_file])
    assert len(rows) == 1
    assert rows[0]["feature"] == "multimodal_evidence"
    assert rows[0]["model"] == "gemini-4-carbon"
    assert rows[0]["ok"] is True
    assert rows[0]["in"] == 610
    assert rows[0]["out"] == 88
    assert rows[0]["thinking"] == 150
    assert rows[0]["run_id"] == "memo-unit-run"


def test_inspect_memo_png_retries_and_keyless_raises(tmp_path, monkeypatch):
    ledger_file = tmp_path / "retry_ledger.jsonl"
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(ledger_file))

    class Transient429(Exception):
        status_code = 429

    fake_sdk = FakeSDKClient(scripted=[
        Transient429("429 RESOURCE_EXHAUSTED"),
        _fake_response(""),
        _fake_response({
            "observed_doc_id": "d1-1",
            "observed_day_surfaced": 3,
            "has_canary_watermark": False,
            "copy_code_variant": "NONE",
            "observed_footer_ticks": 0,
            "confidence": 0.99,
            "visual_evidence": "Unwatermarked regular leak scan.",
        }),
    ])
    sleeps: list[float] = []
    res = inspect_memo_png(
        b"\x89PNG\r\n\x1a\nstub",
        sdk_client=fake_sdk,
        max_retries=3,
        sleep_fn=sleeps.append,
    )
    assert res["variant"] is None
    assert len(sleeps) == 2
    rows = read_ledger([ledger_file])
    assert [r["ok"] for r in rows] == [False, False, True]

    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    with pytest.raises(MissingKeyError):
        inspect_memo_png(b"\x89PNG\r\n\x1a\n", max_retries=0)


def test_paired_ablation_stub_recovers_oracle_while_blind_collapses():
    for seed in (3, 4, 5):
        paired = run_paired_ablation_seed(
            seed,
            tier="medium",
            vision_mode="stub",
            stub_reader=lambda png_bytes, _doc_id: _decode_variant_from_png_pixels(png_bytes),
        )
        assert paired["multimodal_carbon"]["score"] == pytest.approx(paired["text_oracle"]["score"])
        assert paired["multimodal_carbon"]["correct"] is True
        assert paired["blind_no_vision"]["score"] == pytest.approx(0.0)
        assert paired["blind_no_vision"]["correct"] is False
        assert paired["multimodal_carbon"]["text_feed_variants_redacted"] is True
        assert paired["blind_no_vision"]["text_feed_variants_redacted"] is True


def test_cli_runner_writes_verified_provenance_bundle(tmp_path, monkeypatch):
    ledger_file = tmp_path / "cli_ledger.jsonl"
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(ledger_file))

    out_dir = tmp_path / "results" / "gemini_roles" / "multimodal_evidence" / "memo-watermark-ablation-carbon"
    fake_sdk = FakeSDKClient()

    rc = ablation_runner.main(["--tier", "medium", "--seeds", "3,4,5", "--out", str(out_dir)], sdk_client=fake_sdk)
    assert rc == 0

    meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    comp = json.loads((out_dir / "comparison.json").read_text(encoding="utf-8"))
    summary_md = (out_dir / "summary.md").read_text(encoding="utf-8")
    vision_lines = [
        json.loads(line)
        for line in (out_dir / "vision_calls.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert meta["role"] == "multimodal_evidence"
    assert meta["subrole"] == "visual_memo_blind_ablation"
    assert meta["model_id"] == "gemini-4-carbon"
    assert meta["tiers_version"] == "v1.4"
    assert meta["n_episodes"] == 3
    assert meta["n_images_read_by_model"] == len(vision_lines)
    assert meta["n_images_read_by_model"] == len(fake_sdk.models.calls)
    assert meta["variant_vision_accuracy"] == 1.0
    assert meta["multimodal_mean_score"] == pytest.approx(meta["oracle_mean_score"])
    assert meta["multimodal_mean_score"] > 0.65
    assert meta["blind_mean_score"] == pytest.approx(0.0)
    assert meta["usage"]["in"] > 0 and meta["usage"]["out"] > 0

    assert len(comp["per_seed"]) == 3
    for m in meta["memos"]:
        fp = out_dir / m["path"]
        assert fp.is_file()
        assert memo_sha256(fp.read_bytes()) == m["sha256"]

    assert "\u2014" not in summary_md and "\u2013" not in summary_md

    inspected = _inspect_run(out_dir / "meta.json", tmp_path, tmp_path / "data" / "runs" / "committed" / "v1.4")
    assert inspected["verified"] is True, f"provenance errors: {inspected['errors']}"
    assert inspected["count"] == 3


def test_created_python_files_have_no_comments_dashes_or_secrets():
    root = Path(__file__).resolve().parents[1]
    targets = [
        root / "canary" / "gemini" / "memo_vision.py",
        root / "scripts" / "run_memo_vision_ablation.py",
        root / "tests" / "test_memo_vision.py",
    ]
    for path in targets:
        text = path.read_text(encoding="utf-8")
        assert "\u2014" not in text and "\u2013" not in text, f"dash found in {path}"
        assert chr(35) not in text, f"hash char found in {path}"
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        comments = [t for t in tokens if t.type == tokenize.COMMENT]
        assert not comments, f"comment found in {path}: {comments[0]}"
        assert scan_file_secrets(path, root) == []
