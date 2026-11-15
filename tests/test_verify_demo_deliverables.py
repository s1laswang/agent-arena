from __future__ import annotations

import importlib.util
import io
import json
import struct
import subprocess
import sys
import tempfile
import tokenize
from pathlib import Path
from typing import Iterator

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "verify_demo_deliverables.py"
PREFLIGHT_PATH = ROOT / "scripts" / "craft_preflight.py"
SELF_PATH = Path(__file__).resolve()
OPENCODE_TMP = Path("/tmp/opencode")

HASH_CH = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


vdd = _load_module("verify_demo_deliverables", SCRIPT_PATH)
preflight = _load_module("craft_preflight_for_demo_test", PREFLIGHT_PATH)


@pytest.fixture()
def clean_tmp() -> Iterator[Path]:
    OPENCODE_TMP.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(OPENCODE_TMP), prefix="test-demo-deliv-") as d:
        yield Path(d)


def _bmff_box(box_type: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(payload), box_type) + payload


def _build_synthetic_mp4(codec_tag: bytes = b"avc1", mdat_payload: bytes = b"\x00\x01\x02\x03") -> bytes:
    ftyp = _bmff_box(b"ftyp", b"isom\x00\x00\x02\x00isomavc1mp41")
    sample_entry = _bmff_box(codec_tag, b"\x00" * 24)
    stsd = _bmff_box(b"stsd", b"\x00\x00\x00\x00\x00\x00\x00\x01" + sample_entry)
    stbl = _bmff_box(b"stbl", stsd)
    minf = _bmff_box(b"minf", stbl)
    mdia = _bmff_box(b"mdia", minf)
    trak = _bmff_box(b"trak", mdia)
    moov = _bmff_box(b"moov", trak)
    mdat = _bmff_box(b"mdat", mdat_payload)
    return ftyp + moov + mdat


def _valid_docs_demo_md() -> str:
    return (
        "Canary 10-minute stage demo\n\n"
        "Headline hard OpenCode + gemini-4-carbon over MCP: "
        "65% [24%, 98%] raw and 72% [52%, 91%] luck-adjusted (n=30, dev seeds 0-29, "
        "post-hoc seed lock in 671ed96 after 8fd4dec).\n\n"
        "Seed 4 replay: python scripts/demo_replay.py --seed 4 --verify -> "
        "true mole e11, solver +0.73 on day 5, gemini +0.40 on day 16.\n\n"
        "Seed 26 Fooled: solver +0.69 on day 7 vs gemini -1.00 on day 10 after accusing e04 "
        "(true mole e08).\n"
    )


def _valid_root_demo_md() -> str:
    return (
        "Canary 3-Minute Peer-Review Click Script\n\n"
        "Locked gap on v1.4 hard (OpenCode + gemini-4-carbon over MCP): "
        "72% [52%, 91%] luck-adjusted (65% [24%, 98%] raw; +0.322 +/- 0.199 vs "
        "SolverPolicy +0.499 +/- 0.119, n=30, dev seeds 0-29, post-hoc lock 671ed96).\n\n"
        "Seed 6 Caught: true mole e34; gemini-4-carbon +0.73 on Day 6 vs SolverPolicy +0.71 on Day 6.\n"
        "Seed 26 Fooled: true mole e08; gemini-4-carbon -1.00 on Day 10 accused e04 vs "
        "SolverPolicy +0.69 on Day 7.\n\n"
        "Living Office v1.6 (docs/demo/living_office_v16.html) is an off-by-default preview "
        "that did NOT pass the Gate B gap gate; frozen v1.4 remains the default benchmark.\n"
    )


def _valid_replay_html() -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Canary Replay</title></head><body>"
        "<h1>Committed v1.4 Hard Replay: 65% [24%, 98%] raw | 72% [52%, 91%] luck-adjusted</h1>"
        "<section id='seed6'>Seed 6 Caught: mole e34, Gemini +0.73 Day 6, Solver +0.71 Day 6</section>"
        "<section id='seed26'>Seed 26 Fooled: true mole e08, Gemini -1.00 Day 10 accused e04, "
        "Solver +0.69 Day 7</section>"
        "</body></html>"
    )


def _valid_living_office_html() -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Living Office v1.6 Preview</title></head><body>"
        "<div class='gate-banner'>OFF-BY-DEFAULT v1.6 PREVIEW: V1.6 is off by default and "
        "did NOT pass the Gate B gap gate. Frozen v1.4 (a8f99c2537c91d72) remains the judged default.</div>"
        "<script>const LOCAL_ONLY = true;</script>"
        "</body></html>"
    )


def _valid_arena_index_html() -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<link rel='stylesheet' href='./ui/arena.css'>"
        "<script src='https://cdn.jsdelivr.net/pyodide/v0.27.7/full/pyodide.js' async defer></script>"
        "</head><body>"
        "<div id='arenaRoot'>Canary Arena v1.4 | Living Office V1.6 PREVIEW - OFF BY DEFAULT</div>"
        "<script type='module' src='./arena_boot.js'></script>"
        "</body></html>"
    )


def _populate_full_pass_tree(base: Path) -> None:
    (base / "docs" / "demo").mkdir(parents=True, exist_ok=True)
    (base / "docs" / "arena").mkdir(parents=True, exist_ok=True)
    (base / "docs" / "DEMO.md").write_text(_valid_docs_demo_md(), encoding="utf-8")
    (base / "DEMO.md").write_text(_valid_root_demo_md(), encoding="utf-8")
    (base / "docs" / "demo" / "replay.html").write_text(_valid_replay_html(), encoding="utf-8")
    (base / "docs" / "demo" / "living_office_v16.html").write_text(
        _valid_living_office_html(), encoding="utf-8"
    )
    (base / "docs" / "demo" / "canary_demo.mp4").write_bytes(_build_synthetic_mp4())
    (base / "docs" / "arena" / "index.html").write_text(_valid_arena_index_html(), encoding="utf-8")


def _git_show_bytes(spec: str) -> bytes | None:
    proc = subprocess.run(
        ["git", "cat-file", "-p", spec],
        cwd=ROOT,
        capture_output=True,
        timeout=15,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def test_source_hygiene_ascii_zero_comments_and_zero_em_dashes() -> None:
    for path in (SCRIPT_PATH, SELF_PATH):
        raw = path.read_text(encoding="utf-8")
        assert raw.isascii(), f"non-ASCII character in {path.name}"
        assert EM_DASH not in raw, f"em dash in {path.name}"
        assert EN_DASH not in raw, f"en dash in {path.name}"
        assert HASH_CH not in raw, f"hash character in {path.name}"
        tokens = list(tokenize.generate_tokens(io.StringIO(raw).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == []


def test_live_repo_passes_and_compatible_with_craft_preflight(capsys) -> None:
    results = vdd.audit_repo(root=ROOT)
    assert [r.name for r in results] == list(vdd.CHECK_NAMES)
    assert all(r.status == "PASS" for r in results), results

    opt_results = preflight.run_optional_verifier(
        "verify_demo_deliverables",
        SCRIPT_PATH,
        root=ROOT,
        gate_label="Demo Deliverables Verification",
    )
    assert len(opt_results) == 3
    assert all(r.status == "PASS" for r in opt_results), opt_results

    rc = vdd.main(["--root", str(ROOT), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is True
    assert len(payload["results"]) == 3
    assert payload["results"] == payload["checks"]


def test_synthetic_all_surfaces_pass_in_tmp_path(tmp_path: Path) -> None:
    _populate_full_pass_tree(tmp_path)
    results = vdd.audit_repo(root=tmp_path)
    assert all(r.status == "PASS" for r in results), results
    assert vdd.main(["--root", str(tmp_path)]) == 0


def test_numeric_provenance_fail_fixtures(tmp_path: Path) -> None:
    empty_dir = tmp_path / "missing_docs_demo"
    empty_dir.mkdir()
    assert vdd.main(["--root", str(empty_dir)]) == 1
    r_missing = vdd.check_demo_numeric_provenance(empty_dir)
    assert r_missing.status == "FAIL"
    assert any("missing required docs/DEMO.md" in d for d in r_missing.details)

    bad_ci = tmp_path / "bad_ci"
    _populate_full_pass_tree(bad_ci)
    (bad_ci / "DEMO.md").write_text(
        _valid_root_demo_md()
        .replace("72% [52%, 91%]", "68% [50%, 89%]")
        .replace("+0.322", "+0.355"),
        encoding="utf-8",
    )
    r_ci = vdd.check_demo_numeric_provenance(bad_ci)
    assert r_ci.status == "FAIL"
    assert any("72% [52%, 91%]" in d for d in r_ci.details)
    assert any("+0.322" in d for d in r_ci.details)

    bad_prereg = tmp_path / "bad_prereg"
    _populate_full_pass_tree(bad_prereg)
    (bad_prereg / "DEMO.md").write_text(
        _valid_root_demo_md() + "\nWe pre-registered dev seeds 0-29 before running.\n",
        encoding="utf-8",
    )
    r_prereg = vdd.check_demo_numeric_provenance(bad_prereg)
    assert r_prereg.status == "FAIL"
    assert any("pre-registration" in d for d in r_prereg.details)

    bad_seeds = tmp_path / "bad_seeds"
    _populate_full_pass_tree(bad_seeds)
    (bad_seeds / "docs" / "demo" / "replay.html").write_text(
        _valid_replay_html().replace("e34", "e19").replace("e08", "e12").replace("+0.69", "+0.81"),
        encoding="utf-8",
    )
    r_seeds = vdd.check_demo_numeric_provenance(bad_seeds)
    assert r_seeds.status == "FAIL"
    assert any("e34" in d for d in r_seeds.details)
    assert any("e08" in d for d in r_seeds.details)
    assert any("+0.69" in d for d in r_seeds.details)


def test_living_office_honesty_fail_fixtures(tmp_path: Path) -> None:
    no_banner = tmp_path / "no_banner"
    _populate_full_pass_tree(no_banner)
    (no_banner / "docs" / "demo" / "living_office_v16.html").write_text(
        "<!doctype html><html><body><h1>Living Office v1.6</h1><p>v1.4</p></body></html>",
        encoding="utf-8",
    )
    r_nobanner = vdd.check_living_office_honesty(no_banner)
    assert r_nobanner.status == "FAIL"
    assert any("off-by-default" in d for d in r_nobanner.details)
    assert any("Gate-B-not-passed" in d for d in r_nobanner.details)

    replaced_claim = tmp_path / "replaced_claim"
    _populate_full_pass_tree(replaced_claim)
    (replaced_claim / "docs" / "demo" / "living_office_v16.html").write_text(
        _valid_living_office_html()
        + "<p>Canary v1.6 replaced frozen v1.4 (a8f99c2537c91d72) and passed Gate B.</p>",
        encoding="utf-8",
    )
    r_rep = vdd.check_living_office_honesty(replaced_claim)
    assert r_rep.status == "FAIL"
    assert any("replaced" in d for d in r_rep.details)
    assert any("passed Gate B" in d for d in r_rep.details)


def test_offline_html_mp4_em_dash_secret_and_protected_fail_fixtures(
    tmp_path: Path, clean_tmp: Path
) -> None:
    ext_html = tmp_path / "ext_html"
    _populate_full_pass_tree(ext_html)
    (ext_html / "docs" / "demo" / "replay.html").write_text(
        _valid_replay_html().replace(
            "</head>",
            "<script src='https://cdn.example.com/chart.js'></script>"
            "<link rel='stylesheet' href='https://fonts.googleapis.com/css?family=Inter'>"
            "</head>",
        )
        + "<script>fetch('https://api.example.com/telemetry');</script>",
        encoding="utf-8",
    )
    r_ext = vdd.check_demo_offline_assets_and_hygiene(ext_html)
    assert r_ext.status == "FAIL"
    assert any("external script" in d for d in r_ext.details)
    assert any("external link/stylesheet" in d for d in r_ext.details)
    assert any("fetch" in d for d in r_ext.details)

    empty_mp4 = tmp_path / "empty_mp4"
    _populate_full_pass_tree(empty_mp4)
    (empty_mp4 / "docs" / "demo" / "canary_demo.mp4").write_bytes(b"")
    r_empty = vdd.check_demo_offline_assets_and_hygiene(empty_mp4)
    assert r_empty.status == "FAIL"
    assert any("empty (0 bytes)" in d for d in r_empty.details)

    wrong_codec = tmp_path / "wrong_codec"
    _populate_full_pass_tree(wrong_codec)
    (wrong_codec / "docs" / "demo" / "canary_demo.mp4").write_bytes(
        _build_synthetic_mp4(codec_tag=b"vp09")
    )
    r_codec = vdd.check_demo_offline_assets_and_hygiene(wrong_codec)
    assert r_codec.status == "FAIL"
    assert any("avc1" in d for d in r_codec.details)

    oversized_mp4 = clean_tmp / "oversized_mp4"
    _populate_full_pass_tree(oversized_mp4)
    big_mp4_path = oversized_mp4 / "docs" / "demo" / "canary_demo.mp4"
    with big_mp4_path.open("wb") as fh:
        fh.truncate(vdd.MAX_MP4_BYTES)
    r_big = vdd.check_demo_offline_assets_and_hygiene(oversized_mp4)
    assert r_big.status == "FAIL"
    assert any("exceeds 15 MiB budget" in d for d in r_big.details)

    hygiene_bad = tmp_path / "hygiene_bad"
    _populate_full_pass_tree(hygiene_bad)
    fake_key = "AIza" + "SyTestKey0123456789abcdefghijk"
    (hygiene_bad / "DEMO.md").write_text(
        _valid_root_demo_md() + f"\nBad dash {EM_DASH} and key {fake_key}\n",
        encoding="utf-8",
    )
    r_hyg = vdd.check_demo_offline_assets_and_hygiene(hygiene_bad)
    assert r_hyg.status == "FAIL"
    assert any("em dash" in d for d in r_hyg.details)
    assert any("google_api_key" in d for d in r_hyg.details)

    git_repo = tmp_path / "git_protected"
    _populate_full_pass_tree(git_repo)
    (git_repo / "canary").mkdir(parents=True, exist_ok=True)
    (git_repo / "canary" / "env.py").write_text("x = 1\n", encoding="utf-8")
    git_env = {"GIT_CEILING_DIRECTORIES": str(tmp_path), "PATH": "/usr/bin:/bin:/usr/local/bin"}
    subprocess.run(["git", "init", "-q"], cwd=git_repo, env=git_env, check=True)
    subprocess.run(["git", "config", "user.email", "t@e.com"], cwd=git_repo, env=git_env, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=git_repo, env=git_env, check=True)
    subprocess.run(["git", "add", "."], cwd=git_repo, env=git_env, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=git_repo, env=git_env, check=True)
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=git_repo,
        env=git_env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/justSilas", base_sha],
        cwd=git_repo,
        env=git_env,
        check=True,
    )
    (git_repo / "canary" / "env.py").write_text("x = 2\n", encoding="utf-8")
    r_prot = vdd.check_demo_offline_assets_and_hygiene(git_repo)
    assert r_prot.status == "FAIL"
    assert any("canary/env.py" in d for d in r_prot.details)


def test_fleet_demo_branches_via_git_show_if_available(clean_tmp: Path) -> None:
    demo_md_bytes = _git_show_bytes("origin/fr8/canary/demo-script:DEMO.md")
    if demo_md_bytes is None:
        pytest.skip("origin/fr8/canary/demo-script:DEMO.md not present in local git object store")

    stage = clean_tmp / "fleet_stage"
    (stage / "docs" / "demo").mkdir(parents=True, exist_ok=True)
    (stage / "docs" / "arena").mkdir(parents=True, exist_ok=True)
    (stage / "docs" / "DEMO.md").write_text(
        (ROOT / "docs" / "DEMO.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (stage / "DEMO.md").write_bytes(demo_md_bytes)

    optional_blobs = (
        ("origin/fr8/canary/demo-living-office:docs/demo/living_office_v16.html", "docs/demo/living_office_v16.html"),
        ("origin/fr8/canary/demo-video:docs/demo/canary_demo.mp4", "docs/demo/canary_demo.mp4"),
        ("origin/fr8/canary/demo-replay:docs/demo/replay.html", "docs/demo/replay.html"),
        ("origin/fr8/canary/canary-moletrain-w1-arena:docs/arena/index.html", "docs/arena/index.html"),
    )
    for git_spec, rel_dst in optional_blobs:
        blob = _git_show_bytes(git_spec)
        if blob is not None:
            dst = stage / rel_dst
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(blob)

    results = vdd.audit_repo(root=stage)
    assert all(r.status == "PASS" for r in results), results
