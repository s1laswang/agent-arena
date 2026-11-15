from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import tokenize
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.mole.dsl import MoleStrategy
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, TRAIN_SEEDS

PY_FILE = ROOT / "docs" / "arena" / "mole_rivals.py"
JS_FILE = ROOT / "docs" / "arena" / "mole_rivals.js"
TEST_FILE = Path(__file__).resolve()


def _load_mole_rivals():
    spec = importlib.util.spec_from_file_location("arena_mole_rivals", PY_FILE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["arena_mole_rivals"] = mod
    spec.loader.exec_module(mod)
    return mod


MR = _load_mole_rivals()

ALLOWED_CANARY_MODULES = frozenset(
    {
        "canary",
        "canary.env",
        "canary.rules",
        "canary.types",
        "canary.world",
        "canary.mole",
        "canary.mole.dsl",
        "canary.solver",
        "canary.solver.policy",
        "canary.solver.belief",
        "canary.solver.params",
        "canary.text",
        "canary.text.facts",
        "canary.text.template",
    }
)

FORBIDDEN_SECRET_KEYS = frozenset(
    {
        "mole",
        "true_mole",
        "mole_id",
        "moleId",
        "decoy",
        "correct",
        "true_v",
        "trueV",
        "is_canary",
        "accused",
        "accused_id",
    }
)


def _collect_keys(obj: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            found.add(str(k))
            found |= _collect_keys(v)
    elif isinstance(obj, list):
        for item in obj:
            found |= _collect_keys(item)
    return found


def _extract_js_const_literal(js_src: str, const_name: str) -> Any:
    pattern = re.compile(rf"const\s+{re.escape(const_name)}\s*=\s*([\[{{])")
    match = pattern.search(js_src)
    assert match is not None, f"missing const {const_name} in mole_rivals.js"
    start = match.start(1)
    open_ch = match.group(1)
    close_ch = "]" if open_ch == "[" else "}"
    depth = 0
    in_str = False
    quote_ch = ""
    escaped = False
    end = -1
    for idx in range(start, len(js_src)):
        ch = js_src[idx]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote_ch:
                in_str = False
            continue
        if ch in ('"', "'", "`"):
            in_str = True
            quote_ch = ch
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                end = idx + 1
                break
    assert end > start, f"unterminated literal for {const_name}"
    raw_lit = js_src[start:end]
    quoted_keys = re.sub(r'(?<=[{,\n])\s*([A-Za-z_][A-Za-z0-9_]*)\s*:', r'"\1":', raw_lit)
    clean_json = re.sub(r",\s*([\]}])", r"\1", quoted_keys)
    return json.loads(clean_json)


def _assert_balanced_js_delimiters(js_src: str) -> None:
    pairs = {"{": "}", "(": ")", "[": "]"}
    closing = set(pairs.values())
    stack: list[str] = []
    in_str = False
    quote_ch = ""
    escaped = False
    for idx, ch in enumerate(js_src):
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote_ch:
                in_str = False
            continue
        if ch in ('"', "'", "`"):
            in_str = True
            quote_ch = ch
            continue
        if ch in pairs:
            stack.append(pairs[ch])
        elif ch in closing:
            assert stack and stack[-1] == ch, f"unmatched {ch!r} at offset {idx}"
            stack.pop()
    assert not in_str, "unterminated string literal in mole_rivals.js"
    assert not stack, f"unclosed delimiters in mole_rivals.js: {stack}"


def test_rival_strategies_roundtrip_and_names() -> None:
    assert set(MR.RIVAL_STRATEGIES.keys()) == {
        "default_v0",
        "patient_wide_v1",
        "frontier_synthesis_v14",
    }
    for name, strat in MR.RIVAL_STRATEGIES.items():
        assert isinstance(strat, MoleStrategy)
        rebuilt = MoleStrategy.from_json(json.loads(json.dumps(strat.to_json())))
        assert rebuilt == strat
        assert rebuilt.name == name


@pytest.mark.parametrize("tier", ["easy", "medium", "hard"])
def test_get_mole_briefing_structure_and_no_spoilers(tier: str) -> None:
    briefing = MR.get_mole_briefing(tier)
    assert briefing["tier"] == tier
    assert set(briefing.keys()) == {"tier", "tier_facts", "headline", "rules", "rival_profiles"}
    assert len(briefing["rules"]) == 4
    rule_ids = [r["id"] for r in briefing["rules"]]
    assert rule_ids == [
        "recipient_width",
        "canary_traps",
        "freshness_and_delay",
        "framing_vs_canary",
    ]
    assert len(briefing["rival_profiles"]) == 3
    assert _collect_keys(briefing).isdisjoint(FORBIDDEN_SECRET_KEYS)
    from_json = json.loads(MR.get_mole_briefing_json(tier))
    assert from_json == briefing


@pytest.mark.parametrize("tier,seed", [("easy", 3000), ("medium", 3000), ("hard", 3005), ("hard", 9999)])
def test_compare_human_mole_speed_cache_and_contract_keys(tier: str, seed: int) -> None:
    MR._RIVAL_CACHE.clear()
    summary = {
        "human_done": True,
        "days_survived": 8,
        "leaks_landed": 4,
        "solver_score": 0.64,
        "caught": True,
    }
    t0 = time.perf_counter()
    out = MR.compare_human_mole(tier, seed, summary)
    cold_ms = (time.perf_counter() - t0) * 1000.0
    assert cold_ms < 1500.0, f"expected <1500ms cold on ({tier}, {seed}), got {cold_ms:.2f}ms"

    t1 = time.perf_counter()
    cached_out = MR.compare_human_mole(tier, seed, summary)
    warm_ms = (time.perf_counter() - t1) * 1000.0
    assert warm_ms < 10.0, f"expected <10ms warm cache hit on ({tier}, {seed}), got {warm_ms:.2f}ms"
    assert cached_out["default_mole"] == out["default_mole"]
    assert cached_out["synthesis_mole"] == out["synthesis_mole"]

    assert {
        "human",
        "default_mole",
        "synthesis_mole",
        "patient_mole",
        "rivals",
        "tactical_debrief",
        "tacticalDebrief",
    } <= set(out.keys())
    assert set(out["human"].keys()) == {"days_survived", "leaks_landed", "solver_score", "caught"}
    assert out["human"] == {
        "days_survived": 8,
        "leaks_landed": 4,
        "solver_score": 0.64,
        "caught": True,
    }

    rivals_arr = out["rivals"]
    assert isinstance(rivals_arr, list)
    assert len(rivals_arr) == 4
    assert [r["policy"] for r in rivals_arr] == [
        "human",
        "default_v0",
        "patient_wide_v1",
        "frontier_synthesis_v14",
    ]
    required_row_keys = {
        "label",
        "policy",
        "days_survived",
        "daysSurvived",
        "leaks_landed",
        "leaksLanded",
        "solver_score",
        "solverScore",
        "caught",
    }
    for r_row in rivals_arr:
        assert set(r_row.keys()) == required_row_keys
        assert r_row["days_survived"] == r_row["daysSurvived"]
        assert r_row["leaks_landed"] == r_row["leaksLanded"]
        assert r_row["solver_score"] == r_row["solverScore"]

    expected_rival_keys = {
        "strategy",
        "days_survived",
        "leaks_landed",
        "canary_leaks_surfaced",
        "narrowest_variant_group",
        "solver_score",
        "caught",
        "final_day",
        "leak_events",
    }
    for key, strat_name in (
        ("default_mole", "default_v0"),
        ("patient_mole", "patient_wide_v1"),
        ("synthesis_mole", "frontier_synthesis_v14"),
    ):
        rival = out[key]
        assert set(rival.keys()) == expected_rival_keys
        assert rival["strategy"] == strat_name
        assert rival["days_survived"] == rival["final_day"]
        assert isinstance(rival["leak_events"], list)

    debrief = out["tactical_debrief"]
    assert isinstance(debrief, list)
    assert out["tacticalDebrief"] == debrief
    assert 3 <= len(debrief) <= 5
    joined = " ".join(debrief)
    assert str(seed) in joined
    assert "frontier_synthesis_v14" in joined
    assert "SolverPolicy" in joined
    assert _collect_keys(out).isdisjoint(FORBIDDEN_SECRET_KEYS)


def test_mole_mode_reveal_and_arena_app_schemas() -> None:
    mole_mode_reveal = {
        "ok": True,
        "done": True,
        "seed": 3000,
        "tier": "medium",
        "mole_id": "e05",
        "survived": False,
        "caught": True,
        "accused_id": "e05",
        "final_day": 10,
        "days_survived": 9,
        "mole_score": -0.61,
        "solver_score": 0.61,
        "true_v": 0.85,
        "leaks_count": 3,
        "leaks_made": [
            {"day": 1, "doc_id": "doc_01", "variant": None},
            {"day": 3, "doc_id": "doc_04", "variant": None},
            {"day": 6, "doc_id": "doc_07", "variant": "C"},
        ],
        "leaked_canaries": [
            {
                "doc_id": "doc_07",
                "raw_doc_id": "c3",
                "variant": "C",
                "variant_recipients": ["e01", "e05"],
                "leaked_day": 6,
                "surfaced_day": 8,
                "surfaced": True,
            }
        ],
        "caught_by_canary": {
            "doc_id": "doc_07",
            "raw_doc_id": "c3",
            "variant": "C",
            "variant_recipients": ["e01", "e05"],
            "leaked_day": 6,
            "surfaced_day": 8,
            "surfaced": True,
        },
    }
    out_mm = MR.compare_human_mole("medium", 3000, mole_mode_reveal)
    assert out_mm["human"] == {
        "days_survived": 9,
        "leaks_landed": 3,
        "solver_score": 0.61,
        "caught": True,
    }
    assert any("doc_07" in line and "variant C" in line and "group size 2" in line for line in out_mm["tactical_debrief"])
    assert _collect_keys(out_mm).isdisjoint(FORBIDDEN_SECRET_KEYS)

    leaked_canaries_only = {
        "done": True,
        "days_survived": 11,
        "mole_score": -0.58,
        "caught": True,
        "leaked_canaries": [
            {
                "doc_id": "doc-d4-2",
                "raw_doc_id": "c2",
                "variant": "A",
                "variant_recipients": ["e02", "e05", "e11"],
                "leaked_day": 4,
                "surfaced_day": 6,
                "surfaced": True,
            }
        ],
    }
    out_lc = MR.compare_human_mole("medium", 3000, leaked_canaries_only)
    assert out_lc["human"] == {
        "days_survived": 11,
        "leaks_landed": 1,
        "solver_score": 0.58,
        "caught": True,
    }
    assert any("doc-d4-2" in line and "variant A" in line and "group size 3" in line for line in out_lc["tactical_debrief"])

    leaks_made_only = {
        "done": True,
        "days_survived": 7,
        "solver_score": 0.55,
        "survived": True,
        "leaks_made": [{"day": 2, "doc_id": "doc_02"}, {"day": 4, "doc_id": "doc_05"}],
    }
    out_lm = MR.compare_human_mole("medium", 3000, leaks_made_only)
    assert out_lm["human"] == {
        "days_survived": 7,
        "leaks_landed": 2,
        "solver_score": 0.55,
        "caught": False,
    }

    arena_app_summary = {
        "daysSurvived": 12,
        "leaksLanded": 5,
        "solverScore": 0.44,
        "humanMoleScore": 0.56,
        "caught": False,
    }
    out_ui = MR.compare_human_mole("medium", 3000, arena_app_summary)
    assert out_ui["human"] == {
        "days_survived": 12,
        "leaks_landed": 5,
        "solver_score": 0.44,
        "caught": False,
    }

    arena_app_hm_only = {
        "daysSurvived": 9,
        "leaksLanded": 4,
        "humanMoleScore": 0.38,
        "caught": True,
    }
    out_hm = MR.compare_human_mole("medium", 3000, arena_app_hm_only)
    assert out_hm["human"] == {
        "days_survived": 9,
        "leaks_landed": 4,
        "solver_score": 0.62,
        "caught": True,
    }

    raw = json.dumps(
        {
            "done": True,
            "final_day": 11,
            "leaks": 5,
            "score": 0.52,
            "correct": False,
            "leak_history": [{"doc_id": "c2", "variant": "B", "variant_group_size": 3}],
        }
    )
    parsed = json.loads(MR.compare_human_mole_json("medium", 3000, raw))
    assert parsed["human"] == {
        "days_survived": 11,
        "leaks_landed": 5,
        "solver_score": 0.52,
        "caught": False,
    }
    assert any("c2" in line and "variant B" in line for line in parsed["tactical_debrief"])


@pytest.mark.parametrize(
    "unfinished_payload",
    [
        {"human_done": False, "days_survived": 3, "leaks_landed": 1},
        {"humanDone": False, "daysSurvived": 3, "leaksLanded": 1},
        {"done": False, "final_day": 4},
        {"episode_over": False, "day": 2},
        {"episodeOver": False, "day": 2},
        {"status": "in_progress", "day": 5},
    ],
)
def test_pre_end_zero_leak_invariant(unfinished_payload: dict[str, Any]) -> None:
    MR._RIVAL_CACHE.clear()
    with pytest.raises(ValueError, match="not finished"):
        MR.compare_human_mole("medium", 3000, unfinished_payload)
    with pytest.raises(ValueError, match="not finished"):
        MR.compare_human_mole_json("hard", 3005, json.dumps(unfinished_payload))
    assert MR._RIVAL_CACHE == {}

    sealed = MR.safe_compare_human_mole("medium", 3000, unfinished_payload)
    assert sealed == {"sealed": True, "status": "[SEALED]"}
    assert _collect_keys(sealed).isdisjoint(FORBIDDEN_SECRET_KEYS)


@pytest.mark.parametrize(
    "bad_seed",
    [
        0,
        6,
        26,
        2999,
        10000,
        min(JUDGE_SEEDS),
        max(JUDGE_SEEDS),
        min(HELDOUT_SEEDS),
        max(HELDOUT_SEEDS),
        min(TRAIN_SEEDS),
        800199,
        -1,
        850_000,
        True,
        False,
        3000.0,
        "3000.0",
        "3e3",
        "03000",
        "abc",
        None,
    ],
)
def test_reserved_and_invalid_seeds_refused(bad_seed: Any) -> None:
    with pytest.raises(ValueError):
        MR.validate_seed(bad_seed)
    with pytest.raises(ValueError):
        MR.compare_human_mole("medium", bad_seed, {"done": True, "days_survived": 6})
    with pytest.raises(ValueError):
        MR.safe_compare_human_mole("medium", bad_seed, {"done": False})


def test_public_dev_seed_boundaries_accepted() -> None:
    assert MR.validate_seed(3000) == 3000
    assert MR.validate_seed(9999) == 9999
    assert MR.check_seed("3000") == 3000
    assert MR.check_seed("9999") == 9999


def test_fresh_subprocess_import_trace_stdlib_and_justsilas_canary_only() -> None:
    code = (
        "import importlib.util, json, sys\n"
        "before = set(sys.modules.keys())\n"
        f"spec = importlib.util.spec_from_file_location('mole_rivals', {str(PY_FILE)!r})\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "sys.modules['mole_rivals'] = mod\n"
        "spec.loader.exec_module(mod)\n"
        "mod.get_mole_briefing('medium')\n"
        "mod.compare_human_mole('medium', 3000, {'done': True, 'days_survived': 7, 'leaks_landed': 3, 'solver_score': 0.7, 'caught': True})\n"
        "mod.compare_human_mole('hard', 3005, {'done': True, 'days_survived': 9, 'leaks_landed': 4, 'solver_score': 0.6, 'caught': True})\n"
        "added = sorted(set(sys.modules.keys()) - before)\n"
        "all_mods = sorted(sys.modules.keys())\n"
        "print(json.dumps({'added': added, 'all': all_mods}))\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    env["GOOGLE_API_KEY"] = ""
    env["GEMINI_API_KEY"] = ""
    env["OPENAI_API_KEY"] = ""
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    added = set(payload["added"])
    all_mods = set(payload["all"])
    stdlib = set(sys.stdlib_module_names) | {"__main__", "mole_rivals", "builtins"}
    for mod_name in added:
        top = mod_name.split(".")[0]
        if top in stdlib or top.startswith("_"):
            continue
        assert mod_name in ALLOWED_CANARY_MODULES, f"forbidden module imported: {mod_name}"
    for forbidden in ("numpy", "scipy", "canary.eval", "canary.baselines", "canary.mole.strategies"):
        assert forbidden not in all_mods


def _find_node() -> str | None:
    found = shutil.which("node")
    if found:
        return found
    for cand in (
        Path.home() / "tools" / "node" / "bin" / "node",
        Path("/usr/local/bin/node"),
        Path("/usr/bin/node"),
    ):
        if cand.is_file():
            return str(cand)
    return None


def test_js_static_structure_xss_safe_dom_and_parity() -> None:
    js_text = JS_FILE.read_text(encoding="utf-8")
    _assert_balanced_js_delimiters(js_text)

    for forbidden_sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert forbidden_sink not in js_text, f"XSS-unsafe sink {forbidden_sink} present in mole_rivals.js"
    assert "dom.js" not in js_text, "mole_rivals.js must not statically import ui/dom.js"

    for forbidden_seed_num in ("800000", "800200", "900000", "900040", "100000", "200000"):
        assert forbidden_seed_num not in js_text, f"forbidden seed literal {forbidden_seed_num} in mole_rivals.js"

    assert "parsed < 3000 || parsed > 9999" in js_text
    assert "globalThis.__pyodide" in js_text
    assert "globalThis.pyodide" in js_text
    assert "tacticalDebrief" in js_text

    for required_export in (
        "initMoleRivals",
        "getMoleBriefing",
        "compareHumanMole",
        "safeCompareHumanMole",
        "validateSeed",
        "renderMoleDebriefDom",
        "renderMoleBriefingDom",
        "mountMoleDebrief",
        "renderMoleDebriefHtml",
        "formatMoleDebriefText",
        "escapeHtml",
        "unpackCompareArgs",
        "ensureComparisonContract",
        "arguments.length",
        "globalThis.CanaryMoleRivals = api",
        "window.CanaryMoleRivals = api",
        "export {",
        "export default api;",
    ):
        assert required_export in js_text, f"missing {required_export} in mole_rivals.js"

    for dom_token in (
        "createElement",
        "createTextNode",
        "addEventListener",
        "setAttribute",
        "dataset",
        "aria-",
        "style",
        "replaceChildren",
        "globalThis.document",
    ):
        assert dom_token in js_text, f"missing DOM primitive {dom_token} in mole_rivals.js"

    for arena_css_cls in ("arena-end-card", "h2h-table", "mole-panel", "leak-picker-card"):
        assert arena_css_cls in js_text, f"missing Arena CSS class {arena_css_cls} in mole_rivals.js"

    window_assign_re = re.compile(
        r"(?:\b(?:window|globalThis|self)\.[A-Za-z_$][A-Za-z0-9_$]*|\b(?:const|let|var)\s+[A-Z][A-Z0-9_]{2,})\s*=\s*"
    )
    pre_end_truth_keys = {
        "mole",
        "true_mole",
        "mole_id",
        "decoy",
        "true_decoy",
        "decoy_id",
        "correct",
        "accused_correct",
        "world_seed",
        "_world",
    }
    decoder = json.JSONDecoder()
    for match in window_assign_re.finditer(js_text):
        pos = match.end()
        while pos < len(js_text) and js_text[pos].isspace():
            pos += 1
        if pos < len(js_text) and js_text[pos] in "{[":
            try:
                obj, _ = decoder.raw_decode(js_text, pos)
                assert _collect_keys(obj).isdisjoint(pre_end_truth_keys)
            except json.JSONDecodeError:
                pass

    js_tier_facts = _extract_js_const_literal(js_text, "TIER_FACTS")
    assert _collect_keys(js_tier_facts).isdisjoint(pre_end_truth_keys)
    for tier in ("easy", "medium", "hard"):
        assert js_tier_facts[tier] == MR.get_mole_briefing(tier)["tier_facts"]

    js_rival_profiles = _extract_js_const_literal(js_text, "RIVAL_PROFILES")
    assert _collect_keys(js_rival_profiles).isdisjoint(pre_end_truth_keys)
    assert js_rival_profiles == MR.get_mole_briefing("medium")["rival_profiles"]


def test_js_runtime_behavior_if_node_present(tmp_path: Path) -> None:
    node_bin = _find_node()
    if not node_bin:
        js_text = JS_FILE.read_text(encoding="utf-8")
        assert '"0.00"' in js_text
        assert '"+"' in js_text and '"-"' in js_text
        assert "cachedPyodide" in js_text
        return

    mjs_copy = tmp_path / "mole_rivals.mjs"
    mjs_copy.write_bytes(JS_FILE.read_bytes())

    sample_cmp = MR.compare_human_mole(
        "medium",
        3000,
        {"done": True, "leaks_count": 4, "days_survived": 8, "solver_score": 0.64, "caught": True},
    )
    script = (
        "import { pathToFileURL } from 'node:url';\n"
        "globalThis.window = globalThis;\n"
        f"const mod = await import(pathToFileURL({json.dumps(str(mjs_copy))}).href);\n"
        "if (window.CanaryMoleRivals !== mod.CanaryMoleRivals) throw new Error('window global mismatch');\n"
        "const b = mod.getMoleBriefing('hard');\n"
        "if (b.tier !== 'hard' || b.rules.length !== 4) throw new Error('bad static briefing');\n"
        "for (const bad of [0, 2999, 10000, -1, '3000.0', '3e3', '03000', true, null]) {\n"
        "  let rejected = false;\n"
        "  try { mod.validateSeed(bad); } catch (e) { rejected = true; }\n"
        "  if (!rejected) throw new Error('accepted bad seed ' + String(bad));\n"
        "}\n"
        "if (mod.validateSeed(3000) !== 3000 || mod.validateSeed(9999) !== 9999) throw new Error('valid boundary rejected');\n"
        f"const sample = {json.dumps(sample_cmp)};\n"
        "const mockPy = { runPython: (code) => code.includes('get_mole_briefing_json') ? JSON.stringify(b) : JSON.stringify(sample) };\n"
        "globalThis.__pyodide = mockPy;\n"
        "const cmpGlobal = mod.compareHumanMole('medium', 3000, { daysSurvived: 8, leaksLanded: 4, solverScore: 0.64, caught: true });\n"
        "if (!Array.isArray(cmpGlobal.rivals) || cmpGlobal.rivals.length !== 4) throw new Error('3-arg __pyodide rivals failed');\n"
        "if (!Array.isArray(cmpGlobal.tacticalDebrief)) throw new Error('tacticalDebrief alias missing');\n"
        "delete globalThis.__pyodide;\n"
        "let blocked3 = false;\n"
        "try { mod.compareHumanMole('medium', 3000, { done: false }); } catch (e) { blocked3 = true; }\n"
        "if (!blocked3) throw new Error('3-arg client guard failed');\n"
        "let blocked4 = false;\n"
        "try { mod.compareHumanMole({ runPython: () => '{}' }, 'medium', 3000, { human_done: false }); } catch (e) { blocked4 = true; }\n"
        "if (!blocked4) throw new Error('4-arg client guard failed');\n"
        "await mod.initMoleRivals(mockPy, 'def get_mole_briefing(): pass\\n');\n"
        "const b2 = mod.getMoleBriefing(mockPy, 'hard');\n"
        "if (b2.tier !== 'hard') throw new Error('pyodide briefing failed');\n"
        "const cmp4 = mod.compareHumanMole(mockPy, 'medium', 3000, { human_done: true, days_survived: 8 });\n"
        "if (!cmp4.default_mole || !cmp4.synthesis_mole || !Array.isArray(cmp4.rivals)) throw new Error('4-arg compare failed');\n"
        "const cmp3 = mod.compareHumanMole('medium', 3000, { done: true, leaks_count: 3, days_survived: 8 });\n"
        "if (!cmp3.default_mole || !cmp3.synthesis_mole || !Array.isArray(cmp3.rivals)) throw new Error('3-arg compare failed');\n"
        "const sealed3 = mod.safeCompareHumanMole('medium', 3000, { done: false });\n"
        "if (!sealed3.sealed) throw new Error('3-arg safeCompare sealed failed');\n"
        "const makeDoc = () => ({\n"
        "  createTextNode: (t) => ({ nodeType: 3, textContent: String(t) }),\n"
        "  createElement: (tag) => {\n"
        "    const attrs = {}; const listeners = {}; const children = [];\n"
        "    return {\n"
        "      nodeType: 1, tagName: tag.toUpperCase(), className: '', dataset: {}, style: { cssText: '' },\n"
        "      attrs, listeners, childNodes: children,\n"
        "      setAttribute(k, v) { attrs[k] = String(v); },\n"
        "      addEventListener(ev, fn) { listeners[ev] = fn; },\n"
        "      appendChild(c) { children.push(c); return c; },\n"
        "      replaceChildren() { children.length = 0; }\n"
        "    };\n"
        "  }\n"
        "});\n"
        "const doc = makeDoc();\n"
        "sample.tactical_debrief = ['<img src=x onerror=alert(1)>', '<script>alert(1)</script>'];\n"
        "let copied = '';\n"
        "const domNode = mod.renderMoleDebriefDom(sample, { document: doc, onCopyText: (t) => { copied = t; } });\n"
        "if (!domNode.className.includes('arena-end-card')) throw new Error('missing arena-end-card class');\n"
        "const container = doc.createElement('div');\n"
        "mod.mountMoleDebrief(container, sample, doc);\n"
        "if (container.childNodes.length !== 1) throw new Error('mountMoleDebrief failed');\n"
        "const briefDom = mod.renderMoleBriefingDom('hard', doc);\n"
        "if (!briefDom.className.includes('mole-panel')) throw new Error('missing mole-panel class');\n"
        "const html = mod.renderMoleDebriefHtml(sample);\n"
        "if (html.includes('<script>') || html.includes('<img')) throw new Error('XSS escape failed');\n"
        "const txt = mod.formatMoleDebriefText(sample);\n"
        "if (!txt.includes('frontier_synthesis_v14')) throw new Error('bad text summary');\n"
        "console.log('OK');\n"
    )
    proc = subprocess.run(
        [node_bin, "--input-type=module", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    )
    assert proc.stdout.strip().endswith("OK")


def test_strict_ascii_and_comment_free_hygiene_across_all_owned_files() -> None:
    hash_ch = chr(35)
    slash_slash = chr(47) * 2
    slash_star = chr(47) + chr(42)
    star_slash = chr(42) + chr(47)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    unicode_minus = chr(0x2212)

    for target in (PY_FILE, JS_FILE, TEST_FILE):
        raw = target.read_text(encoding="utf-8")
        assert len(raw.strip()) > 0, f"expected non-empty file: {target}"
        assert raw.isascii(), f"non-ASCII character found in {target.name}"
        assert em_dash not in raw, f"em dash found in {target.name}"
        assert en_dash not in raw, f"en dash found in {target.name}"
        assert unicode_minus not in raw, f"unicode minus found in {target.name}"
        assert hash_ch not in raw, f"hash token found in {target.name}"
        assert slash_slash not in raw, f"line comment token found in {target.name}"
        assert slash_star not in raw, f"block comment open token found in {target.name}"
        assert star_slash not in raw, f"block comment close token found in {target.name}"

    for py_path in (PY_FILE, TEST_FILE):
        raw = py_path.read_text(encoding="utf-8")
        tokens = list(tokenize.generate_tokens(io.StringIO(raw).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == [], f"tokenize.COMMENT found in {py_path.name}"
