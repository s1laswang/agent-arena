from __future__ import annotations

import io
import json
import re
import tokenize
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from canary.env import Env
from canary.gemini.incident_dossier import (
    INCIDENT_DOSSIER_SCHEMA,
    SUBROLE,
    analyze_incident_dossier,
    build_badge_view,
    build_memo_scans_view,
    build_org_map_view,
    collect_dossier_observations,
    dossier_filenames,
    png_sha256,
    render_incident_dossier_pngs,
)
from canary.gemini.ledger import read_ledger
from canary.gemini.provenance import _inspect_run, scan_file_secrets
from canary.llm.base import MissingKeyError
import scripts.run_incident_dossier as runner

ALLOWED_TOOLS = frozenset({
    "list_employees",
    "plant_canary",
    "advance_day",
    "read_access_logs",
    "check_leak_feed",
})


class StrictPublicToolProxy:
    def __init__(self, env: Env):
        object.__setattr__(self, "_inner_call", env.call)
        object.__setattr__(self, "called_tools", [])

    def call(self, tool: str, args: dict):
        assert tool in ALLOWED_TOOLS, f"disallowed tool called during dossier rendering: {tool}"
        self.called_tools.append(tool)
        return self._inner_call(tool, args)

    def __getattr__(self, name: str):
        raise AssertionError(f"hidden attribute access forbidden: {name}")


class FakeModelsAPI:
    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def generate_content(self, *, model: str, contents: list, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class FakeSDKClient:
    def __init__(self, responses: list):
        self.models = FakeModelsAPI(responses)


def _fake_response(payload: dict | str, *, tin: int = 1840, tout: int = 210, thoughts: int = 620):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    um = SimpleNamespace(
        prompt_token_count=tin,
        candidates_token_count=tout,
        thoughts_token_count=thoughts,
        cached_content_token_count=0,
    )
    return SimpleNamespace(text=text, usage_metadata=um, model_version="gemini-4-carbon")


def test_public_isolation_leak_oblivious_partitioning_and_three_png_determinism():
    env_a = Env("medium", 0)
    proxy_a = StrictPublicToolProxy(env_a)
    obs_a = collect_dossier_observations(proxy_a, seed_label=0, tier="medium", seed_tag="medium_0")
    pngs_a = render_incident_dossier_pngs(obs_a)

    assert set(proxy_a.called_tools) == ALLOWED_TOOLS
    assert proxy_a.called_tools.count("check_leak_feed") == 1
    last_plant_idx = max(i for i, t in enumerate(proxy_a.called_tools) if t == "plant_canary")
    first_feed_idx = proxy_a.called_tools.index("check_leak_feed")
    assert first_feed_idx > last_plant_idx
    assert obs_a["issued_counts_set"] == [3]

    badge_json = json.dumps(build_badge_view(obs_a))
    memos_json = json.dumps(build_memo_scans_view(obs_a))
    org_json = json.dumps(build_org_map_view(obs_a))

    assert "c6" not in badge_json and "Sales" not in badge_json and "variant" not in badge_json
    assert re.search(r"\be\d{2}\b", memos_json) is None
    assert "leaked_variant" not in org_json and "day_surfaced" not in org_json and "after_hours" not in org_json

    env_b = Env("medium", 0)
    obs_b = collect_dossier_observations(StrictPublicToolProxy(env_b), seed_label=0, tier="medium", seed_tag="medium_0")
    pngs_b = render_incident_dossier_pngs(obs_b)

    for key in ("badge_raster", "leaked_memo_scans", "org_canary_map"):
        raw = pngs_a[key]
        assert raw[:8] == b"\x89PNG\r\n\x1a\n"
        assert png_sha256(raw) == png_sha256(pngs_b[key])
        with Image.open(io.BytesIO(raw)) as im:
            assert im.format == "PNG"
            assert im.size[0] >= 1200 and im.size[1] >= 500
            colors = im.getcolors(maxcolors=60000)
            assert colors is not None and len(colors) > 20

    assert len({png_sha256(pngs_a[k]) for k in ("badge_raster", "leaked_memo_scans", "org_canary_map")}) == 3


def test_analyze_incident_dossier_sends_three_png_parts_in_single_call(tmp_path, monkeypatch):
    ledger_file = tmp_path / "dossier_ledger.jsonl"
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(ledger_file))

    obs = collect_dossier_observations(Env("medium", 0), seed_label=0, tier="medium", seed_tag="medium_0")
    pngs = render_incident_dossier_pngs(obs)

    fake_sdk = FakeSDKClient([
        _fake_response({
            "top_suspect_ids": ["E05", "invalid_id"],
            "suspected_decoy_ids": ["e19"],
            "confidence": 0.99,
            "decoded_leaked_canaries": [
                {"doc_id": "C6", "variant": "a"},
                {"doc_id": "c11", "variant": "A"},
            ],
            "suspect_department": "Sales",
            "cross_image_reasoning": "Exhibit 2 shows c6=A and c11=A\u2014intersecting Exhibit 3 isolates e05 while Exhibit 1 flags e19.",
        })
    ])

    res = analyze_incident_dossier(
        pngs["badge_raster"],
        pngs["leaked_memo_scans"],
        pngs["org_canary_map"],
        tier="medium",
        model_id="gemini-4-carbon",
        sdk_client=fake_sdk,
        run_id="dossier-unit-run",
        seed=0,
        valid_ids={f"e{i:02d}" for i in range(20)},
    )

    assert len(fake_sdk.models.calls) == 1
    call = fake_sdk.models.calls[0]
    assert call["model"] == "gemini-4-carbon"
    assert len(call["contents"]) == 4
    p1, p2, p3, prompt_part = call["contents"]
    assert p1.inline_data.mime_type == "image/png"
    assert p2.inline_data.mime_type == "image/png"
    assert p3.inline_data.mime_type == "image/png"
    assert p1.inline_data.data == pngs["badge_raster"]
    assert p2.inline_data.data == pngs["leaked_memo_scans"]
    assert p3.inline_data.data == pngs["org_canary_map"]
    assert isinstance(prompt_part, str) and "Exhibit 1" in prompt_part and "Exhibit 2" in prompt_part and "Exhibit 3" in prompt_part
    assert call["config"].response_mime_type == "application/json"
    assert call["config"].response_json_schema == INCIDENT_DOSSIER_SCHEMA

    pred = res["prediction"]
    assert pred["top_suspect_ids"] == ["e05"]
    assert pred["suspected_decoy_ids"] == ["e19"]
    assert pred["decoded_leaked_canaries"] == [{"doc_id": "c6", "variant": "A"}, {"doc_id": "c11", "variant": "A"}]
    assert pred["suspect_department"] == "Sales"
    assert "\u2014" not in pred["cross_image_reasoning"]

    rows = read_ledger([ledger_file])
    assert len(rows) == 1
    assert rows[0]["feature"] == "multimodal_evidence"
    assert rows[0]["model"] == "gemini-4-carbon"
    assert rows[0]["ok"] is True
    assert rows[0]["in"] == 1840
    assert rows[0]["out"] == 210
    assert rows[0]["thinking"] == 620
    assert rows[0]["meta"]["subrole"] == SUBROLE
    assert rows[0]["meta"]["n_images"] == 3


def test_retries_and_keyless_missing_key_error(tmp_path, monkeypatch):
    ledger_file = tmp_path / "retry_ledger.jsonl"
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(ledger_file))

    class RateLimitError(Exception):
        status_code = 429

    fake_sdk = FakeSDKClient([
        RateLimitError("429 RESOURCE_EXHAUSTED"),
        _fake_response(""),
        _fake_response({
            "top_suspect_ids": ["e38"],
            "suspected_decoy_ids": ["e14"],
            "confidence": 0.97,
            "decoded_leaked_canaries": [{"doc_id": "c3", "variant": "B"}],
            "suspect_department": "Sales",
            "cross_image_reasoning": "e38 matches all leaked canary scans while e14 is framed.",
        }),
    ])

    sleeps: list[float] = []
    res = analyze_incident_dossier(
        b"\x89PNG\r\n\x1a\nb1",
        b"\x89PNG\r\n\x1a\nb2",
        b"\x89PNG\r\n\x1a\nb3",
        tier="hard",
        sdk_client=fake_sdk,
        max_retries=3,
        sleep_fn=sleeps.append,
    )
    assert res["prediction"]["top_suspect_ids"] == ["e38"]
    assert len(sleeps) == 2
    assert [r["ok"] for r in read_ledger([ledger_file])] == [False, False, True]

    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    with pytest.raises(MissingKeyError):
        analyze_incident_dossier(
            b"\x89PNG\r\n\x1a\n1",
            b"\x89PNG\r\n\x1a\n2",
            b"\x89PNG\r\n\x1a\n3",
            max_retries=0,
        )


def test_cli_runner_mixed_tiers_writes_fifteen_style_manifest_and_passes_provenance(tmp_path, monkeypatch):
    ledger_file = tmp_path / "cli_ledger.jsonl"
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(ledger_file))
    out_dir = tmp_path / "results" / "gemini_roles" / "multimodal_evidence" / "multi-image-dossier-carbon"

    fake_sdk = FakeSDKClient([
        _fake_response({
            "top_suspect_ids": ["e05"],
            "suspected_decoy_ids": ["e19"],
            "confidence": 0.99,
            "decoded_leaked_canaries": [
                {"doc_id": "c6", "variant": "A"},
                {"doc_id": "c11", "variant": "A"},
            ],
            "suspect_department": "Sales",
            "cross_image_reasoning": "Medium 0: c6=A and c11=A isolate e05 (Sales); e19 is framed decoy.",
        }),
        _fake_response({
            "top_suspect_ids": ["e38"],
            "suspected_decoy_ids": ["e14"],
            "confidence": 0.98,
            "decoded_leaked_canaries": [
                {"doc_id": "c3", "variant": "B"},
                {"doc_id": "c6-2", "variant": "B"},
                {"doc_id": "c10-2", "variant": "C"},
                {"doc_id": "c12", "variant": "A"},
            ],
            "suspect_department": "Sales",
            "cross_image_reasoning": "Hard 0: c3=B, c6-2=B, c10-2=C, c12=A isolate e38 (Sales); e14 is framed decoy.",
        }),
    ])

    rc = runner.main(["--worlds", "medium:0,hard:0", "--out", str(out_dir)], sdk_client=fake_sdk)
    assert rc == 0

    meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    results = json.loads((out_dir / "results.json").read_text(encoding="utf-8"))
    summary_md = (out_dir / "summary.md").read_text(encoding="utf-8")

    assert meta["role"] == "multimodal_evidence"
    assert meta["subrole"] == "multi_image_incident_dossier"
    assert meta["model_id"] == "gemini-4-carbon"
    assert meta["episode_count"] == 2
    assert meta["n_images_read_by_model"] == 6
    assert meta["top1_mole_accuracy"] == 1.0
    assert meta["top1_decoy_accuracy"] == 1.0
    assert meta["usage"]["calls"] == 2

    m = results["metrics"]
    assert m["memo_scan_readout_accuracy"] == 1.0
    assert m["suspect_dept_accuracy"] == 1.0
    assert m["image1_only_mole_accuracy"] == 0.0
    assert m["image1_only_decoy_trap_rate"] == 1.0
    assert m["image2_only_mole_accuracy"] == 0.0
    assert m["image3_only_deterministic_mole_accuracy"] == 0.0

    png_files = sorted((out_dir / "dossiers").glob("*.png"))
    assert len(png_files) == 6
    for tag in ("medium_0", "hard_0"):
        fnames = dossier_filenames(tag)
        for fn in fnames.values():
            assert (out_dir / "dossiers" / fn).is_file()

    prov = _inspect_run(out_dir / "meta.json", tmp_path, tmp_path / "data" / "runs" / "committed" / "v1.4")
    assert prov["verified"] is True
    assert prov["errors"] == []
    assert prov["count"] == 2
    assert "\u2014" not in summary_md and "\u2013" not in summary_md


def test_created_files_have_zero_hash_comments_em_dashes_or_secrets():
    root = Path(__file__).resolve().parents[1]
    hash_char = chr(35)
    targets = [
        root / "canary" / "gemini" / "incident_dossier.py",
        root / "scripts" / "run_incident_dossier.py",
        root / "tests" / "test_incident_dossier.py",
    ]
    for path in targets:
        text = path.read_text(encoding="utf-8")
        assert "\u2014" not in text and "\u2013" not in text, f"dash found in {path}"
        assert hash_char not in text, f"hash char found in {path}"
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        comments = [t for t in tokens if t.type == tokenize.COMMENT]
        assert not comments, f"comment found in {path}: {comments[0]}"
        assert scan_file_secrets(path, root) == []
