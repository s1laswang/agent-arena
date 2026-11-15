from __future__ import annotations

import io
import json
from pathlib import Path
import re
import tokenize

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ROLES_CARBON_ROOT = REPO_ROOT / "results" / "gemini" / "roles_carbon"
MM_ROOT = ROLES_CARBON_ROOT / "multimodal_evidence"
EH_ROOT = ROLES_CARBON_ROOT / "exploit_hunter"

TARGET_MODEL = "gemini-4-carbon"
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)

COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GOOGLE_KEY_RE = re.compile(r"(?<![A-Za-z0-9_\-])AIza[0-9A-Za-z_\-]{8,60}(?![A-Za-z0-9_\-=])")
SK_KEY_RE = re.compile(r"(?<![A-Za-z0-9_])sk-[A-Za-z0-9_\-]{12,}")
OAUTH_RE = re.compile(r"(?<![A-Za-z0-9_])ya29\.[0-9A-Za-z_\-]{12,}")
ENV_KEY_RE = re.compile(
    r"\b(?:GEMINI_API_KEY|GOOGLE_API_KEY|GOOGLE_GENERATIVE_AI_API_KEY|"
    r"OPENAI_API_KEY|ANTHROPIC_API_KEY|XAI_API_KEY)\b"
    r"[\"']?[ \t]*[:=][ \t]*(\"[^\"]*\"|'[^']*'|[^\s\"',}\]]*)"
)
SAFE_PLACEHOLDERS = frozenset({
    "",
    "null",
    "none",
    "false",
    "true",
    "unset",
    "redacted",
    "[redacted]",
    "<redacted>",
    "empty",
    "missing",
})

EXPECTED_MM_RUNS = frozenset({
    "access-heatmap-carbon",
    "access-heatmap-hard-carbon",
    "access-heatmap-v14-sweep-carbon",
    "belief-chart-forensics-carbon",
    "carbon-trajectory-forensics",
    "carbon-trajectory-forensics-v14-expanded",
    "memo-watermark-ablation-carbon",
    "memo-watermark-hard-ablation-carbon",
    "memo-watermark-hard-seeds5to9-carbon",
    "memo-watermark-med-seeds6to11-carbon",
    "multi-image-dossier-carbon",
    "multi-image-dossier-v14-expanded-carbon",
    "scanned-evidence-ablation-carbon",
})

EXPECTED_WATERMARK_ABLATION_RUNS = (
    "memo-watermark-ablation-carbon",
    "memo-watermark-hard-ablation-carbon",
    "memo-watermark-hard-seeds5to9-carbon",
    "memo-watermark-med-seeds6to11-carbon",
    "scanned-evidence-ablation-carbon",
)

EXPECTED_EH_RUNS = frozenset({
    "blackbox-swarm-carbon",
    "whitebox-swarm-carbon",
})

FORBIDDEN_IMAGE_SUBDIRS = frozenset({"memos", "dossiers", "rasters", "charts"})


@pytest.fixture(autouse=True)
def _keyless_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")


def _is_pos_num(val: object) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and val > 0


def _scan_text_secrets(text: str) -> list[str]:
    findings: list[str] = []
    if GOOGLE_KEY_RE.search(text):
        findings.append("google_api_key")
    if SK_KEY_RE.search(text):
        findings.append("sk_api_key")
    if OAUTH_KEY := OAUTH_RE.search(text):
        if OAUTH_KEY:
            findings.append("oauth_token")
    for match in ENV_KEY_RE.finditer(text):
        raw = match.group(1).strip()
        quoted = len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'"
        inner = raw[1:-1].strip() if quoted else raw
        if inner.lower() in SAFE_PLACEHOLDERS:
            continue
        if set(inner) <= {"*"} or inner.startswith("$"):
            continue
        if not quoted and "=" in inner:
            continue
        if len(inner) >= 4:
            findings.append("env_api_key")
    return findings


def _assert_common_meta(meta: dict[str, object], expected_role: str, run_dir: Path) -> None:
    assert meta.get("role") == expected_role, run_dir
    subrole = meta.get("subrole")
    assert isinstance(subrole, str) and subrole.strip(), run_dir
    assert meta.get("model_id") == TARGET_MODEL, run_dir
    commit = meta.get("commit")
    assert isinstance(commit, str) and COMMIT_RE.fullmatch(commit) is not None, run_dir

    for bad_flag in ("fake_env", "smoke", "stub", "synthetic"):
        assert not bool(meta.get(bad_flag)), (run_dir, bad_flag)

    usage = meta.get("usage")
    assert isinstance(usage, dict), run_dir
    assert _is_pos_num(usage.get("calls")), run_dir
    assert _is_pos_num(usage.get("in")), run_dir
    assert _is_pos_num(usage.get("out")), run_dir
    assert _is_pos_num(usage.get("cost_usd")), run_dir


def _assert_clean_tree(role_root: Path) -> list[Path]:
    assert role_root.is_dir(), role_root
    run_dirs = sorted(p for p in role_root.iterdir() if p.is_dir())
    for p in role_root.rglob("*"):
        if p.is_dir():
            assert p.name not in FORBIDDEN_IMAGE_SUBDIRS, f"forbidden subdir committed: {p}"
            continue
        assert p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".py"}, f"forbidden file committed: {p}"
        text = p.read_text(encoding="utf-8")
        assert EM_DASH not in text, f"em-dash in {p}"
        assert EN_DASH not in text, f"en-dash in {p}"
        assert "results/gemini_roles/" not in text, f"stale gemini_roles path in {p}"
        leaks = _scan_text_secrets(text)
        assert leaks == [], f"secret leak in {p}: {leaks}"
        if p.suffix == ".json":
            json.loads(text)
        elif p.suffix == ".jsonl":
            rows = [json.loads(ln) for ln in text.splitlines() if ln.strip()]
            assert len(rows) > 0, f"empty jsonl: {p}"
    return run_dirs


def test_multimodal_evidence_13_folders_provenance_and_image_manifests() -> None:
    assert len(EXPECTED_MM_RUNS) == 13
    run_dirs = _assert_clean_tree(MM_ROOT)
    actual_names = {p.name for p in run_dirs}
    assert EXPECTED_MM_RUNS.issubset(actual_names)

    baseline_total_images = 0
    for run_dir in run_dirs:
        meta_path = run_dir / "meta.json"
        summary_path = run_dir / "summary.md"
        assert meta_path.is_file(), run_dir
        assert summary_path.is_file() and summary_path.stat().st_size > 100, run_dir

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        _assert_common_meta(meta, "multimodal_evidence", run_dir)

        n_images = meta.get("n_images_read_by_model")
        assert isinstance(n_images, int) and not isinstance(n_images, bool) and n_images > 0, run_dir
        assert meta.get("part_from_bytes") is True, run_dir

        manifest = meta.get("image_manifest")
        assert isinstance(manifest, dict), run_dir
        assert manifest.get("count") == n_images, run_dir
        assert manifest.get("mime_type") == "image/png", run_dir
        assert isinstance(manifest.get("total_bytes"), int) and manifest["total_bytes"] > 0, run_dir

        dims = manifest.get("dimensions")
        assert isinstance(dims, list) and len(dims) >= 1, run_dir
        for pair in dims:
            assert isinstance(pair, list) and len(pair) == 2, run_dir
            assert all(isinstance(x, int) and x > 0 for x in pair), run_dir

        images = manifest.get("images")
        assert isinstance(images, list) and len(images) == n_images, run_dir
        byte_sum = 0
        for img in images:
            assert isinstance(img, dict), run_dir
            rel_path = img.get("path")
            assert isinstance(rel_path, str) and rel_path.endswith(".png"), run_dir
            w = img.get("width")
            h = img.get("height")
            sz = img.get("size")
            b = img.get("bytes")
            digest = img.get("sha256")
            assert isinstance(w, int) and w > 0, run_dir
            assert isinstance(h, int) and h > 0, run_dir
            assert sz == [w, h], run_dir
            assert isinstance(b, int) and b > 0, run_dir
            assert isinstance(digest, str) and SHA256_RE.fullmatch(digest) is not None, run_dir
            byte_sum += b
        assert byte_sum == manifest["total_bytes"], run_dir

        has_companion = any(
            (run_dir / fname).is_file()
            for fname in ("comparison.json", "results.json", "diagnoses.json")
        )
        assert has_companion, run_dir
        if (run_dir / "comparison.json").is_file():
            vcalls_path = run_dir / "vision_calls.jsonl"
            assert vcalls_path.is_file(), run_dir
            vcalls = [json.loads(ln) for ln in vcalls_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            assert len(vcalls) == n_images, run_dir

        if run_dir.name in EXPECTED_MM_RUNS:
            baseline_total_images += n_images

    assert baseline_total_images == 191


def test_pooled_watermark_ablation_22_unique_episodes_exact_math() -> None:
    unique_episodes: dict[tuple[str, int], dict[str, object]] = {}

    for run_name in EXPECTED_WATERMARK_ABLATION_RUNS:
        run_dir = MM_ROOT / run_name
        comp = json.loads((run_dir / "comparison.json").read_text(encoding="utf-8"))
        default_tier = str(comp["tier"])
        for row in comp["per_seed"]:
            tier = str(row.get("tier") or default_tier)
            seed = int(row["seed"])
            key = (tier, seed)
            mm_ep = row["multimodal_carbon"]
            bl_ep = row["blind_no_vision"]
            orc_ep = row["text_oracle"]
            entry = {
                "mm_score": float(mm_ep["score"]),
                "bl_score": float(bl_ep["score"]),
                "orc_score": float(orc_ep["score"]),
                "n_memos": int(mm_ep["n_memos_inspected"]),
                "vision_exact": int(mm_ep["vision_exact_matches"]),
                "mm_correct": bool(mm_ep["correct"]),
                "bl_correct": bool(bl_ep["correct"]),
            }
            if key in unique_episodes:
                assert unique_episodes[key] == entry, f"inconsistent duplicate episode {key}"
            else:
                unique_episodes[key] = entry

    assert len(unique_episodes) == 22
    expected_keys = {("medium", s) for s in range(12)} | {("hard", s) for s in range(10)}
    assert set(unique_episodes.keys()) == expected_keys

    rows = [unique_episodes[k] for k in sorted(unique_episodes)]
    total_scans = sum(int(r["n_memos"]) for r in rows)
    total_exact = sum(int(r["vision_exact"]) for r in rows)
    mm_mean = sum(float(r["mm_score"]) for r in rows) / len(rows)
    bl_mean = sum(float(r["bl_score"]) for r in rows) / len(rows)
    orc_mean = sum(float(r["orc_score"]) for r in rows) / len(rows)
    vision_acc_pct = 100.0 * total_exact / total_scans
    oracle_recovery_pct = 100.0 * (mm_mean / orc_mean)

    assert total_scans == 101
    assert total_exact == 101
    assert vision_acc_pct == pytest.approx(100.0, abs=1e-9)
    assert f"{mm_mean:+.4f}" == "+0.6832"
    assert f"{bl_mean:+.4f}" == "+0.1705"
    assert f"{orc_mean:+.4f}" == "+0.6832"
    assert round(mm_mean, 4) == 0.6832
    assert round(bl_mean, 4) == 0.1705
    assert oracle_recovery_pct == pytest.approx(100.0, abs=1e-9)


def test_exploit_hunter_2_folders_provenance_and_8_inproc_3_mcp_channels() -> None:
    assert len(EXPECTED_EH_RUNS) == 2
    run_dirs = _assert_clean_tree(EH_ROOT)
    actual_names = {p.name for p in run_dirs}
    assert EXPECTED_EH_RUNS.issubset(actual_names)

    for run_dir in run_dirs:
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        _assert_common_meta(meta, "exploit_hunter", run_dir)
        assert (run_dir / "swarm.json").is_file(), run_dir
        assert (run_dir / "swarm.md").is_file() and (run_dir / "swarm.md").stat().st_size > 100, run_dir
        assert not (run_dir / "generated_holdouts.py").exists(), run_dir

    bb_dir = EH_ROOT / "blackbox-swarm-carbon"
    wb_dir = EH_ROOT / "whitebox-swarm-carbon"

    bb_attempts_jsonl = [
        json.loads(ln)
        for ln in (bb_dir / "attempts.jsonl").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    assert len(bb_attempts_jsonl) == 6

    tot_attempts = 0
    tot_inproc = 0
    tot_mcp = 0
    tot_ledger_verified = 0

    for run_name, expected_total, expected_inproc, expected_mcp in (
        ("blackbox-swarm-carbon", 6, 4, 2),
        ("whitebox-swarm-carbon", 5, 4, 1),
    ):
        swarm_doc = json.loads((EH_ROOT / run_name / "swarm.json").read_text(encoding="utf-8"))
        attempts = swarm_doc["attempts"]
        assert isinstance(attempts, list) and len(attempts) == expected_total
        mcp_count = sum(
            1
            for a in attempts
            if str(a.get("channel") or "").strip().lower() == "mcp"
            or str(a.get("id") or "").strip().endswith("-mcp")
        )
        inproc_count = len(attempts) - mcp_count
        ledger_count = sum(1 for a in attempts if bool(a.get("ledger_verified")))
        assert inproc_count == expected_inproc
        assert mcp_count == expected_mcp
        assert ledger_count == expected_total

        tot_attempts += len(attempts)
        tot_inproc += inproc_count
        tot_mcp += mcp_count
        tot_ledger_verified += ledger_count

    wb_meta = json.loads((wb_dir / "meta.json").read_text(encoding="utf-8"))
    assert wb_meta["pack_files"] == 104
    assert wb_meta["pack_tokens"] == 203463

    assert tot_attempts == 11
    assert tot_inproc == 8
    assert tot_mcp == 3
    assert tot_ledger_verified == 11


def test_this_test_file_has_zero_comments_dashes_or_secrets() -> None:
    self_path = Path(__file__).resolve()
    src = self_path.read_text(encoding="utf-8")
    assert EM_DASH not in src
    assert EN_DASH not in src
    tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
    assert comments == []
    assert _scan_text_secrets(src) == []
