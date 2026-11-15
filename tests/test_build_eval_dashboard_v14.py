from __future__ import annotations

import ast
import io
import json
import re
import shutil
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import build_eval_dashboard_v14 as dash

OWNED_SCRIPT = ROOT / "scripts/build_eval_dashboard_v14.py"
OWNED_HTML = ROOT / "results/eval_v14/headline_dashboard_v14.html"
OWNED_GUIDE = ROOT / "docs/reports/eval_dashboard_guide_v14.md"
OWNED_TEST = ROOT / "tests/test_build_eval_dashboard_v14.py"


def test_check_flag_byte_parity() -> None:
    assert OWNED_HTML.is_file()
    assert OWNED_GUIDE.is_file()
    rc = dash.main(["--check", "--root", str(ROOT)])
    assert rc == 0


def test_html_size_offline_and_svg_structure() -> None:
    raw_bytes = OWNED_HTML.read_bytes()
    assert len(raw_bytes) < 60000
    assert len(raw_bytes) < 60 * 1024
    html_text = raw_bytes.decode("utf-8")

    lower = html_text.lower()
    assert ("http" + "://") not in lower
    assert ("https" + "://") not in lower

    assert '<svg id="forest-svg"' in html_text
    assert '<svg id="cf-svg"' in html_text
    assert "2x2 Harness x Tier Crossover" in html_text
    assert "Judge Rerun Operating Characteristics" in html_text


def test_interactive_controls_and_metric_order() -> None:
    html_text = OWNED_HTML.read_text(encoding="utf-8")

    tier_btns = re.findall(r'data-tier="([^"]+)"[^>]*>([^<]+)</button>', html_text)
    assert [t[0] for t in tier_btns] == ["hard", "medium", "all"]

    metric_btns = re.findall(r'data-metric="([^"]+)"[^>]*>([^<]+)</button>', html_text)
    assert [m[0] for m in metric_btns] == ["raw", "la", "win", "p3"]
    assert [m[1] for m in metric_btns] == [
        "Raw % Solver",
        "Luck-Adjusted % Solver",
        "Winnable %",
        "Calibrated pass^3",
    ]


def test_honest_disclosure_banner_and_embedded_payload() -> None:
    html_text = OWNED_HTML.read_text(encoding="utf-8")
    md_text = OWNED_GUIDE.read_text(encoding="utf-8")

    expected_tokens = [
        "65% [24%, 98%]",
        "72% [52%, 91%]",
        "671ed96",
        "NOT pre-registered",
        "afterquery-final",
        "1bc3e281",
        "aa1c679e",
        "5f9b3297",
        "+0.472",
        "93%",
        "+0.585",
        "116%",
        "+0.626",
        "131%",
        "+0.506",
        "20/28",
        "did NOT reproduce",
        "cf394894",
        "ca0a0dc0",
        "+0.504 +/- 0.064",
        "101% [79%, 140%]",
        "84% [67%, 103%]",
        "17.2",
        "8.5",
    ]
    for tok in expected_tokens:
        assert tok in html_text, f"Missing {tok!r} in HTML"

    assert "65% [24%, 98%]" in md_text
    assert "101% [79%, 140%]" in md_text
    assert "93%" in md_text and "116%" in md_text and "131%" in md_text

    m = re.search(
        r'<script id="eval-v14-data" type="application/json">(.*?)</script>',
        html_text,
        re.DOTALL,
    )
    assert m is not None
    payload = json.loads(m.group(1))
    assert len(payload["r"]) == 27
    assert len(payload["b2"]) == 39
    assert len(payload["cf"]) == 7

    cols = payload["rc"]
    rows = [dict(zip(cols, vals)) for vals in payload["r"]]
    sec_a = [r for r in rows if r["sec"] == "A"]
    sec_b1 = [r for r in rows if r["sec"] == "B1"]
    assert len(sec_a) == 24
    assert len(sec_b1) == 3

    gpt55 = [r for r in sec_a if r["agent"] == "opencode:openai/gpt-5.5" and r["tier"] == "hard"]
    assert len(gpt55) == 1
    assert abs(gpt55[0]["raw"] - 1.0094) < 1e-3
    assert abs(gpt55[0]["la"] - 0.8367) < 1e-3


def test_no_git_shallow_isolated_build_and_tamper_detection(tmp_path: Path) -> None:
    for rel in dash.INPUT_JSON_RELS.values():
        src = ROOT / rel
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    src_ep = ROOT / dash.GPT55_EPISODES_REL
    dst_ep = tmp_path / dash.GPT55_EPISODES_REL
    dst_ep.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_ep, dst_ep)

    assert not (tmp_path / ".git").exists()
    assert dash.main(["--check", "--root", str(tmp_path)]) == 1
    assert dash.main(["--root", str(tmp_path)]) == 0
    assert dash.main(["--check", "--root", str(tmp_path)]) == 0

    assert (tmp_path / dash.DEFAULT_HTML_REL).read_bytes() == OWNED_HTML.read_bytes()
    assert (tmp_path / dash.DEFAULT_GUIDE_REL).read_bytes() == OWNED_GUIDE.read_bytes()

    (tmp_path / dash.DEFAULT_GUIDE_REL).write_text("tampered\n", encoding="utf-8")
    assert dash.main(["--check", "--root", str(tmp_path)]) == 1


def test_strict_code_and_text_hygiene() -> None:
    for py_file in (OWNED_SCRIPT, OWNED_TEST):
        src = py_file.read_text(encoding="utf-8")
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [t for t in tokens if t.type == tokenize.COMMENT]
        assert comments == [], f"Found comment tokens in {py_file}: {comments}"
        assert chr(35) not in src, f"Found literal hash character in {py_file}"

    tree = ast.parse(OWNED_SCRIPT.read_text(encoding="utf-8"))
    imported_names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.append(node.module)
    assert "subprocess" not in imported_names

    for fpath in (OWNED_SCRIPT, OWNED_HTML, OWNED_GUIDE, OWNED_TEST):
        txt = fpath.read_text(encoding="utf-8")
        assert "\u2013" not in txt
        assert "\u2014" not in txt
        assert "\u00b1" not in txt

    for out_path in (OWNED_HTML, OWNED_GUIDE):
        out_txt = out_path.read_text(encoding="utf-8")
        assert re.search(r"\be\d{2}\b", out_txt) is None
        assert "mole_id" not in out_txt.lower()
