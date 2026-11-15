from __future__ import annotations

import ast
import gzip
import io
import json
import tokenize
from collections import defaultdict
from pathlib import Path

import pytest

from canary.gemini.outthink_thought_quotes import (
    DEFAULT_JSON_OUT,
    KIND_ORDER,
    LEVEL_ORDER,
    MAX_JSON_BYTES,
    MODEL_ORDER,
    ROOT,
    TIER_ORDER,
    UNICODE_DASH_CODES,
    _best_verbatim_span,
    build_thought_quotes,
    main,
    render_json,
    validate_thought_quotes,
)
from canary.world import HELDOUT_SEEDS, JUDGE_SEEDS

MODULE_PATH = ROOT / "canary" / "gemini" / "outthink_thought_quotes.py"
ANNOTATIONS_JSON = ROOT / "results" / "gemini" / "outthink_annotations.json"


@pytest.fixture(scope="module")
def quotes_doc() -> dict:
    return json.loads(DEFAULT_JSON_OUT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def annotations_doc() -> dict:
    return json.loads(ANNOTATIONS_JSON.read_text(encoding="utf-8"))


def _read_repo_source(rel_path: str, cache: dict[str, str]) -> str:
    if rel_path not in cache:
        fp = ROOT / rel_path
        assert fp.is_file(), f"missing source_file {rel_path}"
        if rel_path.endswith(".gz"):
            with gzip.open(fp, "rt", encoding="utf-8") as fh:
                cache[rel_path] = fh.read()
        else:
            cache[rel_path] = fp.read_text(encoding="utf-8")
    return cache[rel_path]


def test_json_file_exists_under_size_budget_and_schema(
    quotes_doc: dict,
    annotations_doc: dict,
) -> None:
    assert DEFAULT_JSON_OUT.is_file()
    raw_bytes = DEFAULT_JSON_OUT.read_bytes()
    assert 10_000 < len(raw_bytes) < MAX_JSON_BYTES

    assert set(quotes_doc.keys()) == {
        "generated_from_git_sha",
        "summary",
        "by_episode",
        "by_tier_seed",
        "quotes",
    }
    sha = quotes_doc["generated_from_git_sha"]
    assert isinstance(sha, str) and len(sha) == 40
    assert all(ch in "0123456789abcdef" for ch in sha)
    assert sha == annotations_doc["generated_from_git_sha"]
    assert validate_thought_quotes(quotes_doc, root=ROOT) == []


def test_summary_rollups_kinds_models_levels_and_thought_signatures(
    quotes_doc: dict,
) -> None:
    summary = quotes_doc["summary"]
    quotes = quotes_doc["quotes"]

    assert summary["total_quotes"] == 268
    assert summary["verified_quotes"] == 268
    assert len(quotes) == 268

    by_kind = summary["counts_by_kind"]
    assert set(by_kind.keys()) == set(KIND_ORDER)
    assert sum(by_kind.values()) == len(quotes)
    for kind in KIND_ORDER:
        assert by_kind[kind] == sum(1 for q in quotes if q["kind"] == kind)
        assert by_kind[kind] >= 50

    by_model = summary["counts_by_model"]
    assert set(by_model.keys()) == set(MODEL_ORDER)
    assert sum(by_model.values()) == len(quotes)
    for model in MODEL_ORDER:
        assert by_model[model] == sum(1 for q in quotes if q["model"] == model)
        assert by_model[model] >= 6

    by_level = summary["counts_by_thinking_level"]
    assert sum(by_level.values()) == len(quotes)
    for lv, cnt in by_level.items():
        assert lv in (*LEVEL_ORDER, "unknown")
        assert cnt == sum(1 for q in quotes if (q["thinking_level"] or "unknown") == lv)

    sig_by_src = summary["thought_signature_parts_by_source"]
    assert summary["thought_signature_part_count"] == 14911
    assert sum(sig_by_src.values()) == summary["thought_signature_part_count"]
    assert set(sig_by_src.keys()) == {
        "inproc-gemini-4-carbon",
        "opencode-gemini-3.5-flash",
        "opencode-gemini-4-carbon",
        "replay-ladder",
        "replay-ladder-showcase",
    }
    assert summary["quotes_with_thought_signature"] == 150
    assert summary["quotes_with_thought_signature"] == sum(
        1 for q in quotes if q["has_thought_signature"]
    )
    assert summary["thoughts_token_count_total"] == 219526
    assert summary["episodes_covered"] == len(quotes_doc["by_episode"]) == 107
    assert summary["tier_seeds_covered"] == len(quotes_doc["by_tier_seed"]) == 41


def test_every_quote_is_verbatim_substring_of_committed_source_file(
    quotes_doc: dict,
) -> None:
    quotes = quotes_doc["quotes"]
    source_cache: dict[str, str] = {}
    seen_ids: set[str] = set()
    seen_triples: set[tuple[str, str, str]] = set()

    for idx, q in enumerate(quotes, start=1):
        expected_id = f"tq_{idx:04d}"
        assert q["quote_id"] == expected_id
        assert expected_id not in seen_ids
        seen_ids.add(expected_id)

        triple = (q["source_file"], q["kind"], q["text"])
        assert triple not in seen_triples
        seen_triples.add(triple)

        txt = q["text"]
        assert isinstance(txt, str) and 14 <= len(txt) <= 240
        assert q["char_len"] == len(txt)
        assert q["kind"] in KIND_ORDER
        assert q["model"] in MODEL_ORDER
        if q["tier"] is not None:
            assert q["tier"] in TIER_ORDER
        if q["seed"] is not None:
            assert isinstance(q["seed"], int) and q["seed"] >= 0
            assert q["seed"] not in JUDGE_SEEDS
            assert q["seed"] not in HELDOUT_SEEDS
        assert isinstance(q["has_thought_signature"], bool)

        raw_src = _read_repo_source(q["source_file"], source_cache)
        assert txt in raw_src, f"{expected_id} not verbatim in {q['source_file']}"


def test_episode_and_tier_seed_indexes_reconcile_with_quotes_and_annotations(
    quotes_doc: dict,
    annotations_doc: dict,
) -> None:
    quotes = quotes_doc["quotes"]
    by_qid = {q["quote_id"]: q for q in quotes}

    expected_by_ep: dict[str, list[str]] = defaultdict(list)
    expected_by_ts: dict[str, list[str]] = defaultdict(list)
    for q in quotes:
        if q["episode"]:
            expected_by_ep[q["episode"]].append(q["quote_id"])
        if q["tier"] is not None and q["seed"] is not None:
            expected_by_ts[f"{q['tier']}/{q['seed']}"].append(q["quote_id"])

    assert quotes_doc["by_episode"] == dict(expected_by_ep)
    assert quotes_doc["by_tier_seed"] == dict(expected_by_ts)

    ann_episodes = annotations_doc["episodes"]
    matched_ann = 0
    for ep_key, qids in quotes_doc["by_episode"].items():
        assert len(qids) >= 1
        for qid in qids:
            assert by_qid[qid]["episode"] == ep_key
        if ep_key in ann_episodes:
            matched_ann += 1
            ann_ep = ann_episodes[ep_key]
            sample_q = by_qid[qids[0]]
            assert sample_q["model"] == ann_ep["model"]
            assert sample_q["tier"] == ann_ep["tier"]
            assert sample_q["seed"] == ann_ep["seed"]
    assert matched_ann >= 20


def test_synthetic_root_roundtrip_unicode_dash_splitting_and_tamper_detection(
    tmp_path: Path,
) -> None:
    em = chr(0x2014)
    en = chr(0x2013)
    raw_blob = f"Prefix clause {em} Verbatim reasoning span before canary check {en} trailing note"
    span = _best_verbatim_span(raw_blob, raw_blob)
    assert span == "Verbatim reasoning span before canary check"

    fake_key = "AIza" + "B" * 35
    secret_blob = f" Leak token {fake_key} inside thought part "
    assert _best_verbatim_span(secret_blob, secret_blob) is None

    rl_dir = tmp_path / "results" / "gemini" / "replay-ladder" / "gemini-4-carbon"
    rl_dir.mkdir(parents=True)
    manifest_path = tmp_path / "results" / "gemini" / "replay-ladder" / "manifest.json"
    manifest_path.write_text(
        json.dumps({"episodes": {"gemini-4-carbon/high/hard/1": {"calls": 1}}}),
        encoding="utf-8",
    )
    inner_body = json.dumps(
        {
            "usageMetadata": {"thoughtsTokenCount": 412},
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "thought": True,
                                "text": f"Step 1 {em} Cross-checking canary access logs before accusing suspect e04.",
                                "thoughtSignature": "sig_opaque_token_abc123",
                            },
                            {
                                "functionCall": {"name": "accuse", "args": {"employee_id": "e04"}},
                            },
                        ]
                    }
                }
            ],
        }
    )
    gz_payload = json.dumps(
        {
            "model": "gemini-4-carbon",
            "ts": 1700000000.0,
            "body": inner_body,
        }
    )
    with gzip.open(rl_dir / "call_0001.json.gz", "wt", encoding="utf-8") as fh:
        fh.write(gz_payload)

    atlas_dir = tmp_path / "results" / "gemini"
    (atlas_dir / "atlas.json").write_text(
        json.dumps(
            {
                "modes": [
                    {
                        "id": "premature_accusation",
                        "quotes": [
                            {
                                "episode": "g3.1flashlite-low.in.v14.m2",
                                "t": 4,
                                "verified": True,
                                "quote": "t4 d2 accuse(e03) without planting any canary trap first",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    out_fp = tmp_path / "synthetic_quotes.json"
    assert main(["--root", str(tmp_path), "--json-out", str(out_fp)]) == 0
    assert out_fp.is_file()
    assert main(["--root", str(tmp_path), "--json-out", str(out_fp), "--check"]) == 0

    syn_doc = json.loads(out_fp.read_text(encoding="utf-8"))
    assert validate_thought_quotes(syn_doc, root=tmp_path) == []
    assert syn_doc["summary"]["total_quotes"] == 2
    assert syn_doc["summary"]["thought_signature_part_count"] == 1
    assert syn_doc["summary"]["quotes_with_thought_signature"] == 1
    assert syn_doc["summary"]["thoughts_token_count_total"] == 412

    tampered = json.loads(json.dumps(syn_doc))
    tampered["quotes"][0]["text"] = "Fabricated quote text absent from transcript"
    tampered["quotes"][0]["char_len"] = len(tampered["quotes"][0]["text"])
    errs = validate_thought_quotes(tampered, root=tmp_path)
    assert len(errs) == 1
    assert "not verbatim" in errs[0]

    bad_fp = tmp_path / "tampered_quotes.json"
    bad_fp.write_text(render_json(tampered), encoding="utf-8")
    assert main(["--root", str(tmp_path), "--json-out", str(bad_fp), "--check"]) == 1


def test_cli_deterministic_check_on_live_repo(tmp_path: Path) -> None:
    assert main(["--check"]) == 0
    rebuilt_fp = tmp_path / "rebuilt_thought_quotes.json"
    assert main(["--out", str(rebuilt_fp)]) == 0
    assert rebuilt_fp.read_bytes() == DEFAULT_JSON_OUT.read_bytes()
    rebuilt_doc = build_thought_quotes(root=ROOT)
    assert render_json(rebuilt_doc) == DEFAULT_JSON_OUT.read_text(encoding="utf-8")


def test_zero_comments_zero_unicode_dashes_and_zero_live_api_imports() -> None:
    self_path = Path(__file__).resolve()
    py_files = (MODULE_PATH, self_path)
    all_files = (*py_files, DEFAULT_JSON_OUT)
    hash_char = chr(35)
    dash_chars = tuple(chr(c) for c in UNICODE_DASH_CODES)
    dash_escapes = tuple("\\u" + f"{c:04x}" for c in UNICODE_DASH_CODES)

    for py_fp in py_files:
        src = py_fp.read_text(encoding="utf-8")
        assert hash_char not in src, f"hash or comment character found in {py_fp.name}"
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        assert [t for t in tokens if t.type == tokenize.COMMENT] == []

        tree = ast.parse(src)
        forbidden = {
            "google",
            "genai",
            "httpx",
            "requests",
            "urllib",
            "http",
            "socket",
            "aiohttp",
            "canary.gemini.sdk",
            "canary.gemini.atlas_gemini",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    assert top not in forbidden and alias.name not in forbidden
            elif isinstance(node, ast.ImportFrom) and node.module:
                top = node.module.split(".")[0]
                assert top not in forbidden and node.module not in forbidden

    for fp in all_files:
        txt = fp.read_text(encoding="utf-8")
        for dch in dash_chars:
            assert dch not in txt, f"unicode dash found in {fp.name}"
        low = txt.lower()
        for desc in dash_escapes:
            assert desc not in low, f"escaped unicode dash found in {fp.name}"
