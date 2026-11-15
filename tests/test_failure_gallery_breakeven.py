from __future__ import annotations

import ast
import io
import os
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if "canary" in sys.modules and hasattr(sys.modules["canary"], "__path__"):
    _canary_dir = str(_REPO_ROOT / "canary")
    if _canary_dir not in sys.modules["canary"].__path__:
        sys.modules["canary"].__path__.insert(0, _canary_dir)
if "canary.gemini" in sys.modules and hasattr(sys.modules["canary.gemini"], "__path__"):
    _gemini_dir = str(_REPO_ROOT / "canary" / "gemini")
    if _gemini_dir not in sys.modules["canary.gemini"].__path__:
        sys.modules["canary.gemini"].__path__.insert(0, _gemini_dir)

import canary.gemini.gallery_breakeven as gb
from canary.gemini.gallery_breakeven import (
    DEFAULT_OUT,
    ROOT,
    TRANSCRIPT_QUOTES,
    accusation_ev,
    breakeven_posterior,
    compute_spotlight,
    extract_transcript_text,
    main,
    render_markdown,
    verify_transcript_quotes,
)


@pytest.fixture(scope="module")
def spotlight():
    return compute_spotlight(ROOT)


def test_breakeven_math_and_validation():
    assert breakeven_posterior(1.0) == pytest.approx(0.5, abs=1e-12)
    assert breakeven_posterior(0.0) == pytest.approx(1.0, abs=1e-12)
    for v in (0.0, 0.10, 0.16, 0.23, 0.46, 0.67, 1.0):
        p_star = breakeven_posterior(v)
        assert accusation_ev(p_star, v) == pytest.approx(0.0, abs=1e-12)
        assert accusation_ev(min(1.0, p_star + 0.05), v) > 0.0 or v == 0.0
        assert accusation_ev(max(0.0, p_star - 0.05), v) < 0.0
    with pytest.raises(ValueError):
        breakeven_posterior(0.5, wrong_score=0.0)
    with pytest.raises(ValueError):
        breakeven_posterior(-0.01)


def test_spotlight_seeds_posteriors_and_breakeven_margins(spotlight):
    cohorts = spotlight["cohorts"]
    oc_summary = cohorts["opencode-gemini-4-carbon"]
    assert oc_summary["n"] == 30
    assert oc_summary["accused"] == 29
    assert oc_summary["abstained"] == 1
    assert oc_summary["below_exp_seeds"] == [5, 18, 23]
    assert oc_summary["below_true_seeds"] == [5, 18, 23]
    assert oc_summary["below_known_seeds"] == [5, 18, 23]
    assert cohorts["solver"]["below_exp_seeds"] == []
    assert cohorts["solver"]["min_margin_exp"] == pytest.approx(0.1160, abs=1e-3)

    g = spotlight["opencode"]

    s5 = g[5]
    assert s5["accused"] == "e27" and s5["mole"] == "e27" and s5["correct"] is True
    assert s5["p_accused"] == pytest.approx(0.510213, abs=1e-5)
    assert s5["be_exp"] == pytest.approx(0.861141, abs=1e-5)
    assert s5["margin_exp"] == pytest.approx(-0.350928, abs=1e-5)
    assert s5["ev_exp"] == pytest.approx(-0.407516, abs=1e-5)
    assert s5["luck_adjusted"] == pytest.approx(-0.408153, abs=1e-5)

    s18 = g[18]
    assert s18["accused"] == "e29" and s18["mole"] == "e27" and s18["correct"] is False
    assert s18["p_accused"] == pytest.approx(0.627248, abs=1e-5)
    assert s18["be_exp"] == pytest.approx(0.684346, abs=1e-5)
    assert s18["margin_exp"] == pytest.approx(-0.057098, abs=1e-5)
    assert s18["ev_exp"] == pytest.approx(-0.083434, abs=1e-5)
    assert s18["luck_adjusted"] == pytest.approx(-0.084218, abs=1e-5)
    assert s18["accuse_py_verdict"] == "justified"
    assert s18["gallery_fixed50_bucket"] == "wrong_accusation_evidence_backed"

    s23 = g[23]
    assert s23["accused"] == "e29" and s23["mole"] == "e29" and s23["correct"] is True
    assert s23["p_accused"] == pytest.approx(0.451724, abs=1e-5)
    assert s23["be_exp"] == pytest.approx(0.812183, abs=1e-5)
    assert s23["margin_exp"] == pytest.approx(-0.360458, abs=1e-5)
    assert s23["ev_exp"] == pytest.approx(-0.443814, abs=1e-5)
    assert s23["luck_adjusted"] == pytest.approx(-0.444379, abs=1e-5)

    inproc5 = spotlight["inproc"][5]
    assert inproc5["p_accused"] == pytest.approx(0.9014, abs=1e-3)
    assert inproc5["below_breakeven_exp"] is True
    assert inproc5["below_breakeven_true"] is True


def test_thirty_seed_additive_gap_identity_and_counterfactual(spotlight):
    pairs = spotlight["pairs"]
    assert len(pairs) == 30
    for seed, row in pairs.items():
        la_parts = row["leak"] + row["canary"] + row["restrict"] + row["penalty"] + row["abstain"]
        assert la_parts == pytest.approx(row["la_gap"], abs=1e-12), seed
        assert row["la_gap"] + row["luck"] == pytest.approx(row["raw_gap"], abs=1e-12), seed

    tot = spotlight["totals"]
    assert tot["la_gap"] == pytest.approx(4.1897, abs=1e-4)
    assert tot["raw_gap"] == pytest.approx(5.3000, abs=1e-12)
    assert tot["leak"] == pytest.approx(1.7500, abs=1e-12)
    assert tot["canary"] == pytest.approx(-1.6900, abs=1e-12)
    assert tot["restrict"] == pytest.approx(0.1200, abs=1e-12)
    assert tot["penalty"] == pytest.approx(3.3898, abs=1e-4)
    assert tot["abstain"] == pytest.approx(0.6199, abs=1e-4)
    assert tot["luck"] == pytest.approx(1.1103, abs=1e-4)
    assert tot["penalty_below_breakeven"] == pytest.approx(1.6429, abs=1e-4)
    assert (
        tot["leak"] + tot["canary"] + tot["restrict"] + tot["penalty"] + tot["abstain"]
        == pytest.approx(tot["la_gap"], abs=1e-12)
    )
    assert tot["la_gap"] + tot["luck"] == pytest.approx(tot["raw_gap"], abs=1e-12)

    cf = spotlight["counterfactual"]
    assert cf["seeds"] == [5, 18, 23]
    assert cf["ev_exp_gain_sum"] == pytest.approx(0.9348, abs=1e-4)
    assert cf["la_gain_sum"] == pytest.approx(0.9368, abs=1e-4)
    assert cf["raw_gain_sum"] == pytest.approx(0.61, abs=1e-12)


def test_verbatim_transcript_quotes_and_gallery_cross_reference(spotlight):
    verified = verify_transcript_quotes(ROOT)
    assert set(verified) == {5, 11, 18, 23}
    md = render_markdown(spotlight)
    assert DEFAULT_OUT.read_text(encoding="utf-8") == md
    assert (DEFAULT_OUT.parent / "failure_gallery.md").is_file()

    for seed, quote in TRANSCRIPT_QUOTES.items():
        assert quote in extract_transcript_text(seed, root=ROOT)
        assert quote in md

    assert "docs/reports/failure_gallery.md" in md
    assert "18-episode OpenCode v1.4 subset" in md
    assert "all `30` judged hard seeds `0..29`" in md
    assert "`seed 5` at `51.02%` vs `86.11%` break-even" in md
    assert "`seed 23` at `45.17%` vs `81.22%`" in md
    assert "`seed 18` at `62.72%` vs `68.43%`" in md


def test_cli_check_exit_zero_keyless_and_drift_guard(spotlight, tmp_path, monkeypatch):
    clean_env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"}
    }
    clean_env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.run(
        [sys.executable, "-m", "canary.gemini.gallery_breakeven", "--check"],
        cwd=ROOT,
        env=clean_env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "failure_gallery_breakeven reproduces" in proc.stdout

    monkeypatch.setattr(gb, "compute_spotlight", lambda _root=ROOT: spotlight)
    out_file = tmp_path / "failure_gallery_breakeven.md"
    assert main(["--out", str(out_file)]) == 0
    assert main(["--out", str(out_file), "--check"]) == 0
    out_file.write_text(out_file.read_text(encoding="utf-8") + "\ndrift\n", encoding="utf-8")
    assert main(["--out", str(out_file), "--check"]) == 1


def test_zero_comments_zero_forbidden_dashes_and_zero_gemini_calls():
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    py_files = [
        ROOT / "canary" / "gemini" / "gallery_breakeven.py",
        Path(__file__).resolve(),
    ]
    all_files = [*py_files, DEFAULT_OUT]

    for path in all_files:
        txt = path.read_text(encoding="utf-8")
        assert em_dash not in txt, f"em dash found in {path}"
        assert en_dash not in txt, f"en dash found in {path}"

    for py_path in py_files:
        src = py_path.read_text(encoding="utf-8")
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == [], f"comment tokens in {py_path}: {comments}"
        assert chr(35) not in src, f"hash char found in {py_path}"

    tree = ast.parse((ROOT / "canary" / "gemini" / "gallery_breakeven.py").read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    forbidden = ("google", "genai", "atlas_gemini", "gateway", "httpx", "requests", "urllib")
    for mod in imported:
        assert not any(f in mod for f in forbidden), f"forbidden module imported: {mod}"
