from __future__ import annotations

import ast
import io
import json
import re
import tokenize
from pathlib import Path

import pytest

from canary.gemini import outthink

ROOT = Path(__file__).resolve().parents[1]
README_PATH = ROOT / "demo" / "out-think-gemini" / "README.md"
JSON_PATH = ROOT / "results" / "gemini" / "out_think_gemini.json"
CASES_JS_PATH = ROOT / "demo" / "out-think-gemini" / "cases.js"
MODULE_PATH = ROOT / "canary" / "gemini" / "outthink.py"
PROTECTED_PATHS_FILE = ROOT / ".github" / "protected-paths.txt"

HASH_CHAR = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
FORBIDDEN_DASH_CODEPOINTS = (
    0x2010,
    0x2011,
    0x2012,
    0x2013,
    0x2014,
    0x2015,
    0x2212,
)
FORBIDDEN_NET = "fetch" + "("
STUB_TOKENS = ("TODO", "TBD", "FIXME", "XXX")


@pytest.fixture(scope="module")
def readme_text() -> str:
    assert README_PATH.is_file(), f"missing {README_PATH}"
    txt = README_PATH.read_text(encoding="utf-8")
    assert len(txt.strip()) > 500
    return txt


@pytest.fixture(scope="module")
def corpus_payload() -> dict:
    assert JSON_PATH.is_file(), f"missing {JSON_PATH}"
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


def test_readme_exists_zero_dashes_zero_stubs_and_offline_clean(readme_text: str) -> None:
    assert EM_DASH not in readme_text
    assert EN_DASH not in readme_text
    bad_dashes = [
        (lineno, hex(ord(ch)))
        for lineno, line in enumerate(readme_text.splitlines(), 1)
        for ch in line
        if ord(ch) in FORBIDDEN_DASH_CODEPOINTS
    ]
    assert bad_dashes == []
    assert FORBIDDEN_NET not in readme_text

    for stub in STUB_TOKENS:
        assert re.search(rf"\b{re.escape(stub)}\b", readme_text) is None, f"stub marker {stub} found"


def test_readme_quickstart_and_gameplay_contract(readme_text: str, corpus_payload: dict) -> None:
    assert "open demo/out-think-gemini/index.html" in readme_text
    assert "python3 -m http.server" in readme_text
    assert "Canvas" in readme_text
    assert "Phaser" in readme_text

    for tab_label in ("Canaries", "Leaks", "Access", "Comms", "Steps"):
        assert tab_label in readme_text
    assert "decision_step" in readme_text
    assert "ACCUSE" in readme_text
    assert "HOLD FIRE" in readme_text
    assert "+V_t" in readme_text
    assert "-1.00" in readme_text
    assert "SolverPolicy" in readme_text
    assert "P(top) >= 1 / (1 + V_t)" in readme_text

    meta = corpus_payload["meta"]
    for level in meta["thinking_levels"]:
        assert f"`{level}`" in readme_text
    for model in meta["models"]:
        assert f"`{model}`" in readme_text


def test_readme_exact_metrics_match_outthink_corpus(readme_text: str, corpus_payload: dict) -> None:
    meta = corpus_payload["meta"]
    cases = corpus_payload["cases"]

    case_count = int(meta["case_count"])
    unique_worlds = sorted({(str(c["tier"]), int(c["seed"])) for c in cases})
    world_count = len(unique_worlds)
    hold_fire_count = sum(1 for c in cases if c["solver"]["recommended_call"] == "hold_fire")
    accuse_count = sum(1 for c in cases if c["solver"]["recommended_call"] == "accuse")
    level_run_count = sum(len(c["thinking_levels"]) for c in cases)
    total_episodes = int(meta["total_episodes"])
    ledger_runs = int(meta["ledger_unique_runs"])
    total_cost_usd = float(meta["total_cost_usd"])

    assert case_count == len(cases) == 12
    assert world_count == 11
    assert hold_fire_count == int(meta["hold_fire_cases"]) == 8
    assert accuse_count == int(meta["accuse_cases"]) == 4
    assert level_run_count == int(meta["level_run_count"]) == 39
    assert total_episodes == int(meta["ladder_corpus_episodes"]) == 550
    assert ledger_runs == 618
    assert f"${total_cost_usd:.2f}" == "$262.71"

    for exact_token in (
        f"`{case_count}`",
        f"`{world_count}`",
        f"`{hold_fire_count}`",
        f"`{accuse_count}`",
        f"`{level_run_count}`",
        f"`{total_episodes}`",
        f"`{ledger_runs}`",
        f"`${total_cost_usd:.2f}`",
        f"`${total_cost_usd:.4f}`",
        "`v1.4`",
    ):
        assert exact_token in readme_text, f"missing exact verified metric {exact_token}"

    for level in ("minimal", "low", "medium", "high", "xhigh"):
        scores = [
            float(lv["score"])
            for c in cases
            for lv in c["thinking_levels"]
            if lv["thinking_level"] == level
        ]
        n = len(scores)
        score_sum = sum(scores)
        mean_score = score_sum / n
        sum_str = f"{score_sum:+.2f}"
        mean_str = f"{mean_score:+.4f}"
        row_pattern = (
            rf"\|\s*`{re.escape(level)}`\s*\|\s*`{n}`\s*\|\s*`{re.escape(sum_str)}`\s*\|\s*`{re.escape(mean_str)}`\s*\|"
        )
        assert re.search(row_pattern, readme_text) is not None, f"mismatch in level table row for {level}"

    for c in cases:
        cid = str(c["id"])
        tier = str(c["tier"])
        seed = int(c["seed"])
        model = str(c["model"])
        anchor_lv = str(c["anchor_level"])
        day = int(c["decision_day"])
        step = int(c["decision_step"])
        vt = f"{float(c['value_at_decision']):.2f}"
        be = f"{float(c['solver']['break_even_prob']):.4f}"
        top_p = f"{float(c['solver']['top_prob']):.4f}"
        call = str(c["solver"]["recommended_call"])
        case_row_re = (
            rf"\|\s*`{re.escape(cid)}`\s*"
            rf"\|\s*`{re.escape(tier)}`,\s*seed\s*`{seed}`\s*"
            rf"\|\s*`{re.escape(model)}`\s*@\s*`{re.escape(anchor_lv)}`\s*"
            rf"\|\s*Day\s*`{day}`,\s*Step\s*`{step}`\s*"
            rf"\|\s*`{re.escape(vt)}`\s*"
            rf"\|\s*`{re.escape(be)}`\s*"
            rf"\|\s*`{re.escape(top_p)}`\s*"
            rf"\|\s*`{re.escape(call)}`\s*\|"
        )
        assert re.search(case_row_re, readme_text) is not None, f"scenario row mismatch for {cid}"


def test_readme_cited_paths_and_keyless_verification_commands(
    readme_text: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    required_existing_paths = (
        "canary/gemini/outthink.py",
        "results/gemini/out_think_gemini.json",
        "demo/out-think-gemini/cases.js",
        "results/gemini/ladder_episodes.jsonl.gz",
        "results/gemini/ladder_ledger.jsonl.gz",
        "data/runs/committed/v1.4/reference",
        "tests/test_gemini_lab_outthink.py",
        "tests/test_outthink_demo_readme.py",
    )
    for rel in required_existing_paths:
        assert rel in readme_text, f"README missing reference to {rel}"
        assert (ROOT / rel).exists(), f"referenced path missing on disk: {rel}"

    assert "docs/demo/ASSETS.md" in readme_text
    if (ROOT / "demo" / "out-think-gemini" / "index.html").is_file():
        assert (ROOT / "docs" / "demo" / "ASSETS.md").is_file()
        assert (ROOT / "demo" / "out-think-gemini" / "scene.js").is_file()

    assert "PYTHONPATH=. python -m canary.gemini.outthink --check" in readme_text
    assert "pytest -q tests/test_gemini_lab_outthink.py tests/test_outthink_demo_readme.py" in readme_text

    for key_var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key_var, raising=False)
    rc = outthink.main(["--check"])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert "OK:" in captured.out


def test_self_hygiene_zero_comments_dashes_genai_imports_and_protected_paths() -> None:
    self_path = Path(__file__).resolve()
    src = self_path.read_text(encoding="utf-8")

    assert HASH_CHAR not in src
    comments = [
        tok
        for tok in tokenize.generate_tokens(io.StringIO(src).readline)
        if tok.type == tokenize.COMMENT
    ]
    assert comments == []

    for ch in src:
        assert ord(ch) not in FORBIDDEN_DASH_CODEPOINTS
    assert FORBIDDEN_NET not in src

    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "google" not in alias.name and "genai" not in alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert "google" not in node.module and "genai" not in node.module

    rules = [
        ln.strip()
        for ln in PROTECTED_PATHS_FILE.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith(HASH_CHAR)
    ]
    assert rules

    checked = {
        README_PATH.relative_to(ROOT).as_posix(),
        self_path.relative_to(ROOT).as_posix(),
    }

    for rel in checked:
        for rule in rules:
            if rule.endswith("/"):
                assert not rel.startswith(rule), f"protected directory touched: {rel}"
            else:
                assert rel != rule, f"protected file touched: {rel}"
