from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import sys
import tokenize
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import export_arena_research_cards as exporter

SCRIPT_PATH = ROOT / "scripts" / "export_arena_research_cards.py"
JSON_PATH = ROOT / "docs" / "arena" / "data" / "research_cards.json"
JS_PATH = ROOT / "docs" / "arena" / "data" / "research_cards.js"
SELF_TEST_PATH = Path(__file__).resolve()

ALL_FOUR_FILES: tuple[Path, ...] = (
    SCRIPT_PATH,
    JSON_PATH,
    JS_PATH,
    SELF_TEST_PATH,
)

HASH_CH = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)
SLASH_SLASH = chr(47) * 2
SLASH_STAR = chr(47) + chr(42)
STAR_SLASH = chr(42) + chr(47)

EXPECTED_CARD_IDS: tuple[str, ...] = (
    "passive_interview_crowding",
    "blackwell_canary_dominance",
    "base_rate_log_fallacy",
    "overprecision_breakeven",
    "othello_scrutiny_trap",
    "cheap_talk_rumor_credulity",
    "ulterior_motive_inversion",
    "illusory_truth_plausibility",
    "positive_test_heuristic",
    "sleeper_trigger_evasion",
    "rcpo_catchability_floor",
    "belief_distillation_gap",
)

EXPECTED_CARD_KEYS: tuple[str, ...] = (
    "card_id",
    "title",
    "pillar",
    "trigger_tag",
    "applicable_modes",
    "authors_year",
    "venue",
    "doi",
    "verbatim_quote",
    "canary_metric",
    "debrief_tip",
)

FORBIDDEN_JSON_KEYS: frozenset[str] = frozenset(
    {
        "mole",
        "true_mole",
        "moleId",
        "mole_id",
        "decoy",
        "true_decoy",
        "decoy_id",
        "correct",
        "accused_correct",
        "true_v",
        "true_V",
        "trueV",
        "is_canary",
        "is_mole",
        "leaking_sprite_employee",
        "mole_sprite",
        "culprit_sprite",
        "leaker_employee",
        "world_seed",
        "_world",
        "seed",
        "case_seed",
        "episode_seed",
        "seeds",
        "case_seeds",
        "episode_seeds",
    }
)


def _find_node() -> str | None:
    found = shutil.which("node")
    if found:
        return found
    for cand in (
        Path.home() / "tools" / "node" / "bin" / "node",
        Path("/home/silas/tools/node/bin/node"),
        Path("/usr/local/bin/node"),
        Path("/usr/bin/node"),
    ):
        if cand.is_file():
            return str(cand)
    return None


def _collect_all_json_keys(node: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        for k, v in node.items():
            found.add(str(k))
            found |= _collect_all_json_keys(v)
    elif isinstance(node, list):
        for item in node:
            found |= _collect_all_json_keys(item)
    return found


def test_01_top_level_schema_and_live_v14_hash() -> None:
    payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    assert tuple(payload.keys()) == (
        "schema_version",
        "tiers_version",
        "frozen_v14_hash",
        "cards",
    )
    assert payload["schema_version"] == "1.0"
    assert payload["tiers_version"] == "v1.4"
    assert payload["frozen_v14_hash"] == "a8f99c2537c91d72"
    assert exporter.compute_live_v14_hash() == "a8f99c2537c91d72"


def test_02_twelve_required_card_ids_in_exact_order() -> None:
    payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    cards = payload["cards"]
    assert isinstance(cards, list)
    assert len(cards) == 12
    card_ids = tuple(card["card_id"] for card in cards)
    assert len(set(card_ids)) == 12
    assert card_ids == EXPECTED_CARD_IDS


def test_03_card_safe_schema_keys_and_applicable_modes() -> None:
    payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    allowed_modes = {"duel", "solver", "mole", "living"}
    seen_modes: set[str] = set()
    seen_triggers: set[str] = set()

    for card in payload["cards"]:
        assert tuple(card.keys()) == EXPECTED_CARD_KEYS
        for key in EXPECTED_CARD_KEYS:
            if key == "applicable_modes":
                modes = card[key]
                assert isinstance(modes, list) and len(modes) >= 1
                assert len(modes) == len(set(modes))
                assert set(modes).issubset(allowed_modes)
                seen_modes.update(modes)
            else:
                val = card[key]
                assert isinstance(val, str) and len(val.strip()) >= 3
        seen_triggers.add(card["trigger_tag"])

    assert seen_modes == allowed_modes
    assert len(seen_triggers) == 12


def test_04_doi_format_and_zero_url_double_slash() -> None:
    payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    doi_rx = re.compile(r"^10\.\d{4,9}/[A-Za-z0-9._;()/-]+$")
    dois: list[str] = []
    for card in payload["cards"]:
        doi = card["doi"]
        assert doi_rx.match(doi), f"invalid doi on {card['card_id']}: {doi!r}"
        assert SLASH_SLASH not in doi
        assert not doi.lower().startswith("http")
        dois.append(doi)
    assert len(set(dois)) == 12


def test_05_verified_canary_metrics_and_quotes_content() -> None:
    payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    by_id = {c["card_id"]: c for c in payload["cards"]}

    expected_metric_tokens: dict[str, tuple[str, ...]] = {
        "passive_interview_crowding": ("0.00477", "68.0", "242/303"),
        "blackwell_canary_dominance": ("0.86544", "181.4x", "4.233"),
        "base_rate_log_fallacy": ("4.84%", "9/9", "after_hours"),
        "overprecision_breakeven": ("1/(1+V)", "+22.94 pp", "23"),
        "othello_scrutiny_trap": ("0.20", "52.0%", "24.0%"),
        "cheap_talk_rumor_credulity": ("I = 0.0000", "4.40", "-0.995"),
        "ulterior_motive_inversion": ("61%", "108%", "v1.5-candidate"),
        "illusory_truth_plausibility": ("78.0%", "C_reg(d)", "100.0%"),
        "positive_test_heuristic": ("1-on-1", "32.6%", "81.8%"),
        "sleeper_trigger_evasion": ("careful_mole", "recent_low_recipient_docs >= 2", "+0.1650"),
        "rcpo_catchability_floor": (">= 85%", "99.4%", "75.0%"),
        "belief_distillation_gap": ("-0.457 -> -0.050", "0.000", "DAgger"),
    }
    for cid, tokens in expected_metric_tokens.items():
        metric_txt = by_id[cid]["canary_metric"]
        for tok in tokens:
            assert tok in metric_txt, f"missing {tok!r} in {cid} canary_metric"
        assert len(by_id[cid]["verbatim_quote"]) >= 80
        assert len(by_id[cid]["debrief_tip"]) >= 40

    assert "54%" in by_id["passive_interview_crowding"]["verbatim_quote"]


def test_06_json_and_js_file_size_under_25kb_and_wrapper_prefix() -> None:
    assert JSON_PATH.is_file()
    assert JS_PATH.is_file()
    json_bytes = JSON_PATH.read_bytes()
    js_bytes = JS_PATH.read_bytes()
    assert 1000 < len(json_bytes) < 25000
    assert 1000 < len(js_bytes) < 25600

    js_text = js_bytes.decode("utf-8")
    assert js_text.startswith("globalThis.CANARY_RESEARCH_CARDS = {\n")
    assert js_text.endswith(
        "};\nexport const CANARY_RESEARCH_CARDS = globalThis.CANARY_RESEARCH_CARDS;\n"
    )


def test_07_byte_exact_deterministic_regeneration_and_cli_check(tmp_path: Path) -> None:
    assert exporter.main(["--check"]) == 0

    out_json_1 = tmp_path / "run1" / "research_cards.json"
    out_js_1 = tmp_path / "run1" / "research_cards.js"
    out_json_2 = tmp_path / "run2" / "research_cards.json"
    out_js_2 = tmp_path / "run2" / "research_cards.js"

    assert exporter.main(["--out-json", str(out_json_1), "--out-js", str(out_js_1)]) == 0
    assert exporter.main(["--out-json", str(out_json_2), "--out-js", str(out_js_2)]) == 0

    committed_json = JSON_PATH.read_bytes()
    committed_js = JS_PATH.read_bytes()
    assert out_json_1.read_bytes() == committed_json
    assert out_json_2.read_bytes() == committed_json
    assert out_js_1.read_bytes() == committed_js
    assert out_js_2.read_bytes() == committed_js

    out_js_2.write_text(out_js_2.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert exporter.main(["--check", "--out-json", str(out_json_2), "--out-js", str(out_js_2)]) == 1


def test_08_all_four_files_pure_ascii_and_zero_unicode_dashes() -> None:
    for path in ALL_FOUR_FILES:
        assert path.is_file(), f"missing {path}"
        raw_bytes = path.read_bytes()
        assert all(b < 128 for b in raw_bytes), f"non-ASCII byte in {path.name}"
        text = raw_bytes.decode("utf-8")
        assert text.isascii(), f"non-ASCII char in {path.name}"
        assert EM_DASH not in text, f"em dash in {path.name}"
        assert EN_DASH not in text, f"en dash in {path.name}"
        assert UNICODE_MINUS not in text, f"unicode minus in {path.name}"


def test_09_zero_python_and_js_comments_across_all_four_files() -> None:
    for py_path in (SCRIPT_PATH, SELF_TEST_PATH):
        py_src = py_path.read_text(encoding="utf-8")
        assert HASH_CH not in py_src, f"hash character in {py_path.name}"
        tokens = list(tokenize.generate_tokens(io.StringIO(py_src).readline))
        comment_tokens = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert not comment_tokens, f"Python comment found in {py_path.name}"

    for path in ALL_FOUR_FILES:
        text = path.read_text(encoding="utf-8")
        assert HASH_CH not in text, f"hash marker in {path.name}"
        assert SLASH_SLASH not in text, f"double-slash marker in {path.name}"
        assert SLASH_STAR not in text, f"block-comment open marker in {path.name}"
        assert STAR_SLASH not in text, f"block-comment close marker in {path.name}"


def test_10_zero_forbidden_pre_end_truth_keys_anywhere() -> None:
    json_payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    all_keys = _collect_all_json_keys(json_payload)
    assert all_keys.isdisjoint(FORBIDDEN_JSON_KEYS)
    assert not any(k.isdigit() for k in all_keys)

    js_text = JS_PATH.read_text(encoding="utf-8")
    prefix = "globalThis.CANARY_RESEARCH_CARDS = "
    suffix = ";\nexport const CANARY_RESEARCH_CARDS = globalThis.CANARY_RESEARCH_CARDS;\n"
    assert js_text.startswith(prefix) and js_text.endswith(suffix)
    js_embedded_obj = json.loads(js_text[len(prefix) : len(js_text) - len(suffix)])
    assert js_embedded_obj == json_payload
    assert _collect_all_json_keys(js_embedded_obj).isdisjoint(FORBIDDEN_JSON_KEYS)


def test_11_zero_employee_ids_secrets_and_xss_sinks() -> None:
    emp_word_rx = re.compile(r"\be(?:0[0-9]|[1-3][0-9]|40)\b")
    emp_substrings = tuple(f"e{idx:02d}" for idx in range(1, 41))
    secret_tokens = (
        "SA" + "LT",
        "CANARY_" + "WORLD_SECRET",
        "CANARY_" + "LEDGER_TOKEN",
        "CANARY_" + "ADMIN_TOKEN",
        "world" + "_secret",
        "ledger" + "_token",
        "ledger" + "_key",
        "world " + "secret",
        "ledger " + "token",
    )
    xss_sinks = (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
    )

    for target in (SCRIPT_PATH, JSON_PATH, JS_PATH):
        raw = target.read_text(encoding="utf-8")
        assert emp_word_rx.search(raw) is None, f"employee ID token in {target.name}"
        for emp_sub in emp_substrings:
            assert emp_sub not in raw, f"employee ID substring {emp_sub} in {target.name}"
        for sec in secret_tokens:
            assert sec.lower() not in raw.lower(), f"forbidden secret token in {target.name}"

    for path in ALL_FOUR_FILES:
        raw = path.read_text(encoding="utf-8")
        assert emp_word_rx.search(raw) is None, f"employee ID token in {path.name}"
        for sink in (xss_sinks if path is not SELF_TEST_PATH else ()):
            assert sink not in raw, f"XSS sink in {path.name}"


def test_12_nodejs_esm_import_and_globalthis_contract() -> None:
    node_bin = _find_node()
    assert node_bin is not None, "expected Node.js binary to be available for ESM import verification"

    probe = (
        f"import * as mod from {json.dumps(JS_PATH.as_uri())};"
        f"import fs from 'node:fs';"
        f"const expected = JSON.parse(fs.readFileSync({json.dumps(str(JSON_PATH))}, 'utf8'));"
        "if (!mod.CANARY_RESEARCH_CARDS) process.exit(2);"
        "if (globalThis.CANARY_RESEARCH_CARDS !== mod.CANARY_RESEARCH_CARDS) process.exit(3);"
        "if (mod.CANARY_RESEARCH_CARDS.cards.length !== 12) process.exit(4);"
        "if (JSON.stringify(mod.CANARY_RESEARCH_CARDS) !== JSON.stringify(expected)) process.exit(5);"
    )
    proc = subprocess.run(
        [node_bin, "--input-type=module", "-e", probe],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, f"rc={proc.returncode} stderr={proc.stderr}"
