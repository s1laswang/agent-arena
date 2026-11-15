from __future__ import annotations

import ast
import copy
import gzip
import io
import json
import os
import shutil
import subprocess
import sys
import tokenize
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.env import Env
from canary.gemini import outthink
from canary.rules import tier_params_for_episode
from canary.solver.policy import SolverPolicy
from canary.types import Step
from canary.world import HELDOUT_SEEDS, JUDGE_SEEDS

OUTTHINK_PY_PATH = ROOT / "canary" / "gemini" / "outthink.py"
OUTTHINK_JSON_PATH = ROOT / "results" / "gemini" / "out_think_gemini.json"
CASES_JS_PATH = ROOT / "demo" / "out-think-gemini" / "cases.js"
DEMO_DIR = ROOT / "demo" / "out-think-gemini"
LADDER_JSON_PATH = ROOT / "results" / "gemini" / "ladder.json"
FRONTIER_JSON_PATH = ROOT / "results" / "gemini" / "frontier.json"
ABLATIONS_JSON_PATH = ROOT / "results" / "gemini" / "ablations.json"
SUBMISSION_MD_PATH = ROOT / "docs" / "gemini" / "SUBMISSION.md"
LEDGER_GZ_PATH = ROOT / "results" / "gemini" / "ladder_ledger.jsonl.gz"
PROTECTED_PATHS_FILE = ROOT / ".github" / "protected-paths.txt"

HASH_CHAR = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
FIG_DASH = chr(0x2012)
HORIZ_BAR = chr(0x2015)
UNICODE_DASHES = (FIG_DASH, EN_DASH, EM_DASH, HORIZ_BAR)
FORBIDDEN_FETCH = "fetch" + "("
FORBIDDEN_XHR = "XML" + "HttpRequest"
FORBIDDEN_WS = "Web" + "Socket"
FORBIDDEN_BEACON = "send" + "Beacon"
HTML_COMMENT_OPEN = chr(60) + chr(33) + "--"
SLASH = chr(47)
STAR = chr(42)
LINE_COMMENT = SLASH + SLASH
BLOCK_COMMENT_OPEN = SLASH + STAR

ALLOWED_FAILURE_TAGS = {
    None,
    "ignored_delay",
    "over_caution",
    "variant_inversion",
    "decoy_trap",
    "premature_accusation",
}


def _resolve_js_cmd() -> tuple[list[str], dict[str, str]]:
    clean_env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"}
    }
    for binary in ("node", "nodejs", "bun"):
        found = shutil.which(binary)
        if found:
            return [found, "-e"], clean_env
    for cand in (
        shutil.which("opencode"),
        str(Path.home() / "momin" / "bin" / "opencode"),
        str(Path.home() / ".opencode" / "bin" / "opencode"),
        str(Path.home() / ".local" / "bin" / "opencode"),
    ):
        if cand and Path(cand).is_file() and os.access(cand, os.X_OK):
            bun_env = dict(clean_env)
            bun_env["BUN_BE_BUN"] = "1"
            return [cand, "-e"], bun_env
    pytest.skip("no JavaScript runtime available")


def _find_js_comments(source: str) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    n = len(source)
    i = 0
    line = 1
    in_quote: str | None = None
    in_regex = False
    in_regex_class = False
    prev_sig = "("
    while i < n:
        ch = source[i]
        if in_quote is not None:
            if ch == "\\":
                if i + 1 < n and source[i + 1] == "\n":
                    line += 1
                i += 2
                continue
            if ch == "\n":
                line += 1
            elif ch == in_quote:
                in_quote = None
                prev_sig = '"'
            i += 1
            continue
        if in_regex:
            if ch == "\\":
                i += 2
                continue
            if ch == "[":
                in_regex_class = True
            elif ch == "]":
                in_regex_class = False
            elif ch == SLASH and not in_regex_class:
                in_regex = False
                prev_sig = SLASH
            i += 1
            continue
        if ch in ("'", '"', "`"):
            in_quote = ch
            i += 1
            continue
        if ch == "\n":
            line += 1
            i += 1
            continue
        if ch.isspace():
            i += 1
            continue
        if ch == SLASH and i + 1 < n:
            nxt = source[i + 1]
            if nxt == SLASH:
                hits.append((line, LINE_COMMENT))
                i += 2
                while i < n and source[i] != "\n":
                    i += 1
                continue
            if nxt == STAR:
                hits.append((line, BLOCK_COMMENT_OPEN))
                i += 2
                while i < n:
                    if source[i] == "\n":
                        line += 1
                    if source[i] == STAR and i + 1 < n and source[i + 1] == SLASH:
                        i += 2
                        break
                    i += 1
                continue
            if prev_sig in ("(", ",", "=", ":", "[", "!", "&", "|", "?", "{", "}", ";"):
                in_regex = True
                i += 1
                continue
        prev_sig = ch
        i += 1
    return hits


@pytest.fixture(scope="module")
def cross_audit_bundle() -> dict[str, Any]:
    return {
        "outthink": json.loads(OUTTHINK_JSON_PATH.read_text(encoding="utf-8")),
        "ladder": json.loads(LADDER_JSON_PATH.read_text(encoding="utf-8")),
        "frontier": json.loads(FRONTIER_JSON_PATH.read_text(encoding="utf-8")),
        "ablations": json.loads(ABLATIONS_JSON_PATH.read_text(encoding="utf-8")),
        "submission_md": SUBMISSION_MD_PATH.read_text(encoding="utf-8"),
        "ladder_index": outthink.load_ladder_index(),
        "ledger_index": outthink.load_ledger_index(),
        "solver_ref": outthink.load_solver_reference(),
        "carbon_inproc": outthink.load_carbon_inproc_runs(),
        "carbon_quotes": outthink.load_carbon_transcript_quotes(),
    }


def test_corpus_counts_and_pricing_reconcile_across_outthink_ladder_and_submission(
    cross_audit_bundle: dict[str, Any],
):
    ot = cross_audit_bundle["outthink"]
    lad = cross_audit_bundle["ladder"]
    sub_md = cross_audit_bundle["submission_md"]
    ladder_index = cross_audit_bundle["ladder_index"]
    ledger_index = cross_audit_bundle["ledger_index"]
    meta = ot["meta"]

    lad_prices = lad["prices_usd_per_1m"]
    assert set(outthink.MODEL_PRICES_PER_M.keys()) == set(lad_prices.keys())
    for model_name, rates in outthink.MODEL_PRICES_PER_M.items():
        assert list(rates) == pytest.approx(lad_prices[model_name], abs=1e-9), model_name

    recorded_rows = [r for r in lad["rows"] if r["level"] != "default"]
    imported_rows = [r for r in lad["rows"] if r["level"] == "default"]
    recorded_n = sum(int(r["n"]) for r in recorded_rows)
    imported_n = sum(int(r["n"]) for r in imported_rows)

    assert recorded_n == 550
    assert imported_n == 37
    assert recorded_n + imported_n == int(lad["episodes"]) == 587
    assert meta["total_episodes"] == meta["ladder_corpus_episodes"] == len(ladder_index) == recorded_n
    assert meta["ledger_unique_runs"] == len(ledger_index) == int(lad["ledger"]["run_ids"]) == 618
    assert "587 paired episodes" in sub_md

    recomputed_cost = 0.0
    for (m_name, _lv, _tr, _sd), m_ep in ladder_index.items():
        m_lad = (m_ep.get("meta") or {}).get("ladder") or {}
        m_tok = m_lad.get("tokens") or {}
        m_rid = str(m_lad.get("run_id") or "")
        c_val = float(ledger_index.get(m_rid, {}).get("cost_usd") or 0.0)
        if c_val <= 0.0:
            c_val = outthink.list_price_usd(
                m_name,
                int(m_tok.get("in") or 0),
                int(m_tok.get("out") or 0),
                int(m_tok.get("thinking") or 0),
                int(m_tok.get("cached") or 0),
            )
        recomputed_cost += c_val
    assert meta["total_cost_usd"] == pytest.approx(round(recomputed_cost, 4), abs=1e-6)
    assert meta["total_cost_usd"] == pytest.approx(262.7061, abs=1e-4)

    row_by_cell = {(r["model"], r["level"], r["tier"]): r for r in lad["rows"]}
    c_high_hard = row_by_cell[("gemini-4-carbon", "high", "hard")]
    assert c_high_hard["n"] == 10
    assert round(c_high_hard["ratio"] * 100) == 106
    assert round(c_high_hard["ratio_lo"] * 100) == 94
    assert round(c_high_hard["ratio_hi"] * 100) == 126
    assert round(c_high_hard["cost_per_ep"], 2) == pytest.approx(1.93, abs=1e-6)
    assert "106% [94, 126]" in sub_md

    f_high_hard = row_by_cell[("gemini-3.5-flash", "high", "hard")]
    f_med_hard = row_by_cell[("gemini-3.5-flash", "medium", "hard")]
    assert f_high_hard["n"] == f_med_hard["n"] == 40
    assert round(f_high_hard["ratio"] * 100) == 88
    assert round(f_med_hard["ratio"] * 100) == 87
    assert "88% [51, 138]" in sub_md
    assert "87% [50, 147]" in sub_md


def test_all_39_thinking_level_runs_replay_deterministically_in_env(
    cross_audit_bundle: dict[str, Any],
):
    ot = cross_audit_bundle["outthink"]
    lad = cross_audit_bundle["ladder"]
    ladder_index = cross_audit_bundle["ladder_index"]
    ledger_index = cross_audit_bundle["ledger_index"]
    lad_run_ids = set(lad["ledger_run_ids"])

    replayed = 0
    for c in ot["cases"]:
        cid = c["id"]
        tier = c["tier"]
        seed = c["seed"]
        decision_day = c["decision_day"]
        solver_final_score = c["solver"]["final_score"]
        anchor_found = False

        lv_order_indices = [outthink.THINKING_LEVEL_ORDER.index(lv["thinking_level"]) for lv in c["thinking_levels"]]
        assert lv_order_indices == sorted(lv_order_indices), f"{cid} thinking_levels not ordered"

        for lv in c["thinking_levels"]:
            assert lv["key"] == lv["thinking_level"] == lv["level"]
            assert lv["model"] == c["model"]
            assert lv["tier"] == tier
            assert lv["seed"] == seed
            assert lv["source_file"] == "results/gemini/ladder_episodes.jsonl.gz"

            cell_ep = ladder_index[(lv["model"], lv["thinking_level"], tier, seed)]
            env = Env(tier, seed)
            for st in cell_ep["steps"]:
                if env.done:
                    break
                env.call(st["tool"], st.get("args") or {})
            assert env.done is True
            assert float(env.score()) == pytest.approx(float(cell_ep["score"]), abs=1e-6)
            assert lv["score"] == pytest.approx(round(float(env.score()), 4), abs=1e-6)
            assert lv["correct"] is bool(cell_ep["correct"])
            assert lv["correct"] is (env._accused == c["true_mole"])
            assert lv["accused"] == (str(env._accused) if env._accused is not None else None)

            ep_end = str(cell_ep.get("end_reason") or "horizon")
            ep_final_day = int(cell_ep.get("final_day") or decision_day)
            assert lv["end_reason"] == ep_end
            if env._accused is not None:
                assert lv["accused_day"] == ep_final_day == env.day
            else:
                assert lv["accused_day"] is None

            if lv["thinking_level"] == c["anchor_level"]:
                anchor_found = True
                expected_call = "accuse"
            elif ep_end == "accused" and env._accused is not None and ep_final_day <= decision_day:
                expected_call = "accuse"
            else:
                expected_call = "hold_fire"
            assert lv["call_at_t"] == expected_call, f"{cid}/{lv['key']}"

            expected_regret = round(max(0.0, float(solver_final_score) - float(lv["score"])), 4)
            assert lv["regret_total"] == pytest.approx(expected_regret, abs=1e-6)

            lad_meta = (cell_ep.get("meta") or {}).get("ladder") or {}
            tok = lad_meta.get("tokens") or {}
            run_id = str(lad_meta.get("run_id") or "")
            assert lv["run_id"] == run_id
            assert run_id in ledger_index
            assert run_id in lad_run_ids
            assert lv["input_tokens"] == int(tok.get("in") or 0)
            assert lv["output_tokens"] == int(tok.get("out") or 0)
            assert lv["thinking_tokens"] == int(tok.get("thinking") or 0)
            assert lv["cached_tokens"] == int(tok.get("cached") or 0)
            assert lv["calls"] == int(tok.get("calls") or len(cell_ep.get("steps") or []))
            assert lv["ledger_calls"] == int(ledger_index[run_id]["calls"]) > 0

            led_cost = float(ledger_index[run_id].get("cost_usd") or 0.0)
            expected_cost = round(
                led_cost
                if led_cost > 0.0
                else outthink.list_price_usd(
                    lv["model"],
                    lv["input_tokens"],
                    lv["output_tokens"],
                    lv["thinking_tokens"],
                    lv["cached_tokens"],
                ),
                6,
            )
            assert lv["cost_usd"] == pytest.approx(expected_cost, abs=1e-6)
            replayed += 1

        assert anchor_found is True, f"{cid} missing anchor_level {c['anchor_level']}"

    assert replayed == ot["meta"]["level_run_count"] == 39


def test_all_222_ladder_matrix_cells_reconcile_with_env_replay_and_ladder_rows(
    cross_audit_bundle: dict[str, Any],
):
    ot = cross_audit_bundle["outthink"]
    lad = cross_audit_bundle["ladder"]
    ladder_index = cross_audit_bundle["ladder_index"]
    ledger_index = cross_audit_bundle["ledger_index"]

    row_by_cell = {(r["model"], r["level"], r["tier"]): r for r in lad["rows"]}
    lad_run_ids = set(lad["ledger_run_ids"])
    replay_cache: dict[tuple[str, str, str, int], tuple[float, str | None, int]] = {}
    matrix_cell_count = 0

    for c in ot["cases"]:
        tier = c["tier"]
        seed = c["seed"]
        matrix = c["ladder_matrix"]
        assert c["model"] in matrix

        for lv in c["thinking_levels"]:
            m_cell = matrix[c["model"]][lv["thinking_level"]]
            assert m_cell["score"] == lv["score"]
            assert m_cell["correct"] is lv["correct"]
            assert m_cell["accused"] == lv["accused"]
            assert m_cell["end_reason"] == lv["end_reason"]
            assert m_cell["thinking_tokens"] == lv["thinking_tokens"]
            assert m_cell["cost_usd"] == pytest.approx(lv["cost_usd"], abs=1e-6)
            assert m_cell["run_id"] == lv["run_id"]

        for m_name, lv_map in matrix.items():
            assert m_name in outthink.MODEL_PRICES_PER_M
            for m_lv, cell in lv_map.items():
                assert m_lv in outthink.THINKING_LEVEL_ORDER
                ep_key = (m_name, m_lv, tier, seed)
                assert ep_key in ladder_index
                ep = ladder_index[ep_key]

                if ep_key not in replay_cache:
                    env = Env(tier, seed)
                    for st in ep["steps"]:
                        if env.done:
                            break
                        env.call(st["tool"], st.get("args") or {})
                    assert env.done is True
                    replay_cache[ep_key] = (float(env.score()), env._accused, int(env.day))

                live_score, live_accused, live_day = replay_cache[ep_key]
                assert cell["score"] == pytest.approx(round(live_score, 4), abs=1e-6)
                assert cell["accused"] == live_accused
                assert cell["correct"] is (live_accused == c["true_mole"])
                assert cell["final_day"] == int(ep.get("final_day") or 0) == live_day
                assert cell["end_reason"] == str(ep.get("end_reason") or "horizon")
                assert cell["run_id"] in ledger_index
                assert cell["run_id"] in lad_run_ids

                lad_row = row_by_cell[(m_name, m_lv, tier)]
                assert seed in lad_row["seeds"]
                assert cell["run_id"] in lad_row["run_ids"]
                matrix_cell_count += 1

    assert matrix_cell_count == 222
    assert len(replay_cache) == 202


def test_cross_model_carbon_ladder_and_inproc_fallback_provenance(
    cross_audit_bundle: dict[str, Any],
):
    ot = cross_audit_bundle["outthink"]
    lad = cross_audit_bundle["ladder"]
    carbon_inproc = cross_audit_bundle["carbon_inproc"]
    row_by_cell = {(r["model"], r["level"], r["tier"]): r for r in lad["rows"]}

    ladder_entries = 0
    inproc_entries = 0

    for c in ot["cases"]:
        tier = c["tier"]
        seed = c["seed"]
        cmc_list = c["cross_model_carbon"]
        assert len(cmc_list) >= 1
        carbon_matrix = c["ladder_matrix"].get("gemini-4-carbon", {})

        for cmc in cmc_list:
            assert cmc["model"] == "gemini-4-carbon"
            if cmc["run_id"].startswith("inproc:"):
                assert not carbon_matrix
                assert cmc["run_id"] == f"inproc:v1.4:gemini-4-carbon/{tier}/{seed}"
                in_ep = carbon_inproc[(tier, seed)]
                env = Env(tier, seed)
                for st in in_ep["steps"]:
                    if env.done:
                        break
                    env.call(st["tool"], st.get("args") or {})
                assert env.done is True
                assert cmc["score"] == pytest.approx(round(float(env.score()), 4), abs=1e-6)
                assert cmc["accused"] == (str(env._accused) if env._accused is not None else None)
                assert cmc["correct"] is (env._accused == c["true_mole"])
                if env._accused is not None:
                    assert cmc["accused_day"] == int(in_ep["final_day"]) == env.day
                in_u = (in_ep.get("meta") or {}).get("usage") or {}
                assert cmc["thinking_tokens"] == int(in_u.get("out") or 0)
                assert cmc["cost_usd"] > 0.0
                imp_row = row_by_cell[("gemini-4-carbon", "default", tier)]
                assert seed in imp_row["seeds"]
                inproc_entries += 1
            else:
                c_lv = cmc["thinking_level"]
                assert c_lv in ("low", "high")
                m_cell = carbon_matrix[c_lv]
                assert cmc["run_id"] == m_cell["run_id"]
                assert cmc["score"] == m_cell["score"]
                assert cmc["correct"] is m_cell["correct"]
                assert cmc["accused"] == m_cell["accused"]
                assert cmc["thinking_tokens"] == m_cell["thinking_tokens"]
                assert cmc["cost_usd"] == pytest.approx(m_cell["cost_usd"], abs=1e-6)
                if cmc["accused"] is not None:
                    assert cmc["accused_day"] == m_cell["final_day"]
                else:
                    assert cmc["accused_day"] is None
                ladder_entries += 1

    assert ladder_entries == 22
    assert inproc_entries == 1


def test_reference_solver_full_horizon_replay_and_bayesian_decision_threshold(
    cross_audit_bundle: dict[str, Any],
):
    ot = cross_audit_bundle["outthink"]
    solver_ref = cross_audit_bundle["solver_ref"]
    ladder_index = cross_audit_bundle["ladder_index"]

    hold_fire_cases = 0
    accuse_cases = 0
    replayed_solver_worlds: set[tuple[str, int]] = set()

    for c in ot["cases"]:
        tier = c["tier"]
        seed = c["seed"]
        assert seed not in HELDOUT_SEEDS
        assert seed not in JUDGE_SEEDS
        ref_ep = solver_ref[(tier, seed)]

        if (tier, seed) not in replayed_solver_worlds:
            s_env = Env(tier, seed)
            for st in ref_ep["steps"]:
                if s_env.done:
                    break
                s_env.call(st["tool"], st.get("args") or {})
            assert s_env.done is True
            assert float(s_env.score()) == pytest.approx(float(ref_ep["score"]), abs=1e-6)
            assert s_env._accused == ref_ep.get("accused")
            replayed_solver_worlds.add((tier, seed))

        slv = c["solver"]
        assert slv["final_accused"] == ref_ep.get("accused")
        assert slv["final_day"] == int(ref_ep["final_day"])
        assert slv["final_score"] == pytest.approx(round(float(ref_ep["score"]), 4), abs=1e-6)
        assert slv["correct"] is bool(ref_ep["correct"])
        assert slv["ev_hold_fire"] == pytest.approx(round(max(0.0, slv["final_score"]), 4), abs=1e-6)

        anchor_ep = ladder_index[(c["model"], c["anchor_level"], tier, seed)]
        steps = [Step(**{k: s.get(k) for k in ("t", "day", "tool", "args", "result")}) for s in anchor_ep["steps"]]
        d_step = c["decision_step"]
        env = Env(tier, seed)
        sp = SolverPolicy(tier_params_for_episode(tier, steps))
        for st in steps[:d_step]:
            env.call(st.tool, st.args or {})
            sp._ingest(st)
        sp.seen = d_step
        sp.obs.leak_timing_known = sp.v_drops_reveal_leaks()
        raw_post = sp.belief()

        v_dec = round(float(env.V), 4)
        assert c["value_at_decision"] == pytest.approx(v_dec, abs=1e-6)
        raw_top = max(raw_post, key=raw_post.get)
        be_prob = round(1.0 / (1.0 + v_dec), 4)
        ev_acc = round((float(raw_post[raw_top]) * v_dec) - (1.0 - float(raw_post[raw_top])), 4)

        assert slv["top_suspect"] == str(raw_top)
        assert slv["top_prob"] == pytest.approx(round(float(raw_post[raw_top]), 4), abs=1e-6)
        assert slv["break_even_prob"] == pytest.approx(be_prob, abs=1e-6)
        assert slv["ev_accuse_top"] == pytest.approx(ev_acc, abs=1e-6)

        if float(raw_post[raw_top]) >= be_prob:
            assert slv["recommended_call"] == "accuse"
            assert slv["ev_accuse_top"] >= -1e-4
            accuse_cases += 1
        else:
            assert slv["recommended_call"] == "hold_fire"
            assert slv["ev_accuse_top"] <= 1e-4
            hold_fire_cases += 1

    assert len(replayed_solver_worlds) == 11
    assert hold_fire_cases == ot["meta"]["hold_fire_cases"] == 8
    assert accuse_cases == ot["meta"]["accuse_cases"] == 4


def test_failure_taxonomy_and_analyst_quotes_match_ground_truth_and_world_decoy(
    cross_audit_bundle: dict[str, Any],
):
    ot = cross_audit_bundle["outthink"]
    ladder_index = cross_audit_bundle["ladder_index"]
    carbon_quotes = cross_audit_bundle["carbon_quotes"]

    seen_non_null_tags: set[str] = set()
    checked = 0

    for c in ot["cases"]:
        tier = c["tier"]
        seed = c["seed"]
        world = Env(tier, seed)._world
        true_mole = str(world.mole)
        decoy = str(world.decoy) if getattr(world, "decoy", None) else None
        assert c["true_mole"] == true_mole

        slv = c["solver"]
        for lv in c["thinking_levels"]:
            tag = lv["failure_tag"]
            assert tag in ALLOWED_FAILURE_TAGS
            if tag is not None:
                seen_non_null_tags.add(tag)

            ep = ladder_index[(lv["model"], lv["thinking_level"], tier, seed)]
            exp_tag, exp_quote = outthink.derive_level_annotation(
                ep=ep,
                call_at_t=lv["call_at_t"],
                decision_day=c["decision_day"],
                true_mole=true_mole,
                decoy=decoy,
                top_suspect=slv["top_suspect"],
                top_prob=slv["top_prob"],
                break_even_prob=slv["break_even_prob"],
                recommended_call=slv["recommended_call"],
                carbon_quotes=carbon_quotes,
            )
            assert tag == exp_tag, f"{c['id']}/{lv['key']}"
            assert lv["analyst_quote"] == exp_quote, f"{c['id']}/{lv['key']}"

            if lv["correct"]:
                if (
                    slv["recommended_call"] == "accuse"
                    and lv["call_at_t"] == "hold_fire"
                    and int(ep.get("final_day") or c["decision_day"]) > c["decision_day"]
                ):
                    assert tag == "ignored_delay"
                else:
                    assert tag is None
            else:
                assert tag is not None
                assert tag != "ignored_delay"
                if lv["end_reason"] != "accused" or lv["accused"] is None:
                    assert tag == "over_caution"
                elif slv["top_prob"] >= slv["break_even_prob"] and slv["top_suspect"] == true_mole:
                    assert tag == "variant_inversion"
                elif decoy and lv["accused"] == decoy:
                    assert tag == "decoy_trap"
                else:
                    assert tag == "premature_accusation"
            checked += 1

    assert checked == 39
    assert len(seen_non_null_tags) >= 3


def test_frontier_and_ablations_cross_consistency_with_outthink_models_and_levels(
    cross_audit_bundle: dict[str, Any],
):
    ot = cross_audit_bundle["outthink"]
    lad = cross_audit_bundle["ladder"]
    fr = cross_audit_bundle["frontier"]
    abl = cross_audit_bundle["ablations"]

    row_by_cell = {(r["model"], r["level"], r["tier"]): r for r in lad["rows"]}
    gemini_frontier_models: set[str] = set()
    gemini_frontier_levels: set[str] = set()
    frontier_checked = 0

    for tier_key in ("medium", "hard"):
        for pt in fr["points"][tier_key]:
            if pt.get("kind") != "gemini":
                continue
            gemini_frontier_models.add(pt["model"])
            gemini_frontier_levels.add(pt["level"])
            lad_row = row_by_cell[(pt["model"], pt["level"], pt["tier"])]
            assert pt["n"] == lad_row["n"]
            assert pt["ratio"] == pytest.approx(lad_row["ratio"], abs=1e-6)
            assert pt["ratio_lo"] == pytest.approx(lad_row["ratio_lo"], abs=1e-6)
            assert pt["ratio_hi"] == pytest.approx(lad_row["ratio_hi"], abs=1e-6)
            assert pt["cost_per_ep_usd"] == pytest.approx(lad_row["cost_per_ep"], abs=1e-6)
            frontier_checked += 1

    assert frontier_checked >= 40
    assert set(ot["meta"]["models"]).issubset(gemini_frontier_models)
    assert set(ot["meta"]["thinking_levels"]).issubset(gemini_frontier_levels)

    exact_sweep_matches = 0
    for sw in abl["thinking_sweep"]:
        lad_row = row_by_cell[(sw["model"], sw["level"], sw["tier"])]
        assert sw["n"] <= lad_row["n"]
        if sw["n"] == lad_row["n"]:
            assert sw["pct_of_solver"] == round(lad_row["ratio"] * 100)
            assert sw["usd_per_ep"] == pytest.approx(round(lad_row["cost_per_ep"], 3), abs=1e-6)
            exact_sweep_matches += 1
    assert exact_sweep_matches >= 25


def test_ledger_token_billing_and_cache_accounting_across_case_runs(
    cross_audit_bundle: dict[str, Any],
):
    ot = cross_audit_bundle["outthink"]
    lad = cross_audit_bundle["ladder"]

    raw_calls_total = 0
    calls_by_run: dict[str, int] = defaultdict(int)
    cost_by_run: dict[str, float] = defaultdict(float)

    with gzip.open(LEDGER_GZ_PATH, "rt", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            raw_calls_total += 1
            tin = int(row.get("in") or 0)
            tout = int(row.get("out") or 0)
            tthink = int(row.get("thinking") or 0)
            tcached = int(row.get("cached") or 0)
            assert tin >= 0 and tout >= 0 and tthink >= 0 and tcached >= 0
            assert tcached <= tin
            rid = row.get("run_id")
            if rid:
                calls_by_run[str(rid)] += 1
                cost_by_run[str(rid)] += float(row.get("cost_usd") or 0.0)

    assert raw_calls_total == int(lad["ledger"]["calls"]) == 36164
    assert len(calls_by_run) == int(lad["ledger"]["run_ids"]) == ot["meta"]["ledger_unique_runs"] == 618

    for c in ot["cases"]:
        for lv in c["thinking_levels"]:
            rid = lv["run_id"]
            assert lv["ledger_calls"] == calls_by_run[rid] > 0
            assert lv["cached_tokens"] <= lv["input_tokens"]
            if lv["thinking_level"] == "minimal":
                assert lv["thinking_tokens"] == 0
            elif lv["thinking_level"] in ("high", "xhigh"):
                assert lv["thinking_tokens"] > 0
            if cost_by_run[rid] > 0.0:
                assert lv["cost_usd"] == pytest.approx(round(cost_by_run[rid], 6), abs=1e-6)


def test_pre_decision_evidence_reconstruction_from_raw_anchor_steps(
    cross_audit_bundle: dict[str, Any],
):
    ot = cross_audit_bundle["outthink"]
    ladder_index = cross_audit_bundle["ladder_index"]

    for c in ot["cases"]:
        anchor_ep = ladder_index[(c["model"], c["anchor_level"], c["tier"], c["seed"])]
        pre_steps = [
            Step(**{k: s.get(k) for k in ("t", "day", "tool", "args", "result")})
            for s in anchor_ep["steps"][: c["decision_step"]]
        ]
        assert len(pre_steps) == c["decision_step"]

        planted_ids: list[str] = []
        canary_asg: dict[str, dict[str, str]] = {}
        latest_feed: list[dict[str, Any]] = []
        dedup_logs: list[tuple[int, str, str, bool]] = []
        seen_logs: set[tuple[int, str, str, bool]] = set()
        read_msg_ids: set[str] = set()
        search_msg_ids: list[str] = []
        interview_total = 0

        for idx, st in enumerate(pre_steps):
            assert c["tool_steps"][idx]["summary"] == outthink.summarize_step(st)
            res = st.result or {}
            if not res.get("ok"):
                continue
            data = res.get("data") or {}
            tname = st.tool.strip()
            if tname == "plant_canary":
                can_id = str(data.get("canary_id") or "")
                if can_id:
                    planted_ids.append(can_id)
                    canary_asg[can_id] = {
                        str(k): str(v) for k, v in (st.args or {}).get("assignment", {}).items()
                    }
            elif tname == "check_leak_feed":
                latest_feed = list(data.get("items") or [])
            elif tname == "read_access_logs":
                for lg in data.get("logs") or []:
                    key_lg = (
                        int(lg.get("day", st.day)),
                        str(lg.get("employee") or ""),
                        outthink.clean_text(str(lg.get("doc_id") or "")),
                        bool(lg.get("after_hours", False)),
                    )
                    if key_lg not in seen_logs and key_lg[1]:
                        seen_logs.add(key_lg)
                        dedup_logs.append(key_lg)
            elif tname == "read_message":
                mid = str((data.get("message") or {}).get("id") or "")
                if mid:
                    read_msg_ids.add(mid)
            elif tname == "search_messages":
                for m in data.get("messages") or []:
                    mid = str(m.get("id") or "")
                    if mid:
                        search_msg_ids.append(mid)
            elif tname == "interview":
                interview_total += 1

        assert [can["canary_id"] for can in c["canaries"]] == planted_ids
        assert len(c["leaks"]) == len(latest_feed)
        assert [
            (lg["day"], lg["employee"], lg["doc_id"], lg["after_hours"]) for lg in c["access_logs"]
        ] == dedup_logs

        comm_sort_keys = [
            (int(cm["day"]), 0 if cm["kind"] == "chat" else 1, cm["speaker"]) for cm in c["comms"]
        ]
        assert comm_sort_keys == sorted(comm_sort_keys)
        assert sum(1 for cm in c["comms"] if cm["kind"] == "interview") == interview_total

        expected_unique_chats = len(read_msg_ids | set(search_msg_ids))
        actual_chats = sum(1 for cm in c["comms"] if cm["kind"] == "chat")
        assert actual_chats >= expected_unique_chats

        for can in c["canaries"]:
            rebuilt_map: dict[str, str] = {}
            for var_entry in can["variants"]:
                for recip in var_entry["recipients"]:
                    rebuilt_map[recip] = var_entry["variant"]
            assert rebuilt_map == canary_asg[can["canary_id"]]


def test_js_bundle_deep_equality_and_isolation_in_node_and_browser_contexts():
    cmd_prefix, env = _resolve_js_cmd()
    run_env = dict(env)
    run_env["CASES_JS_PATH"] = str(CASES_JS_PATH)
    run_env["OUTTHINK_JSON_PATH"] = str(OUTTHINK_JSON_PATH)

    script = (
        'const fs = require("fs");\n'
        'const vm = require("vm");\n'
        'const jsCode = fs.readFileSync(process.env.CASES_JS_PATH, "utf8");\n'
        'const rawJson = JSON.parse(fs.readFileSync(process.env.OUTTHINK_JSON_PATH, "utf8"));\n'
        "const cjsBox = { module: { exports: {} } };\n"
        "vm.createContext(cjsBox);\n"
        "vm.runInContext(jsCode, cjsBox);\n"
        "const browserWin = {};\n"
        "const browserBox = { window: browserWin, globalThis: browserWin };\n"
        "vm.createContext(browserBox);\n"
        "vm.runInContext(jsCode, browserBox);\n"
        "const extraKeys = Object.keys(browserWin).filter(k => k !== 'OUTTHINK_DATA' && k !== 'OUTTHINK_CASES');\n"
        "process.stdout.write(JSON.stringify({\n"
        "  cjsDeepEqual: JSON.stringify(cjsBox.module.exports) === JSON.stringify(rawJson),\n"
        "  winDeepEqual: JSON.stringify(browserWin.OUTTHINK_DATA) === JSON.stringify(rawJson),\n"
        "  casesRefEqual: browserWin.OUTTHINK_CASES === browserWin.OUTTHINK_DATA.cases,\n"
        "  extraKeys\n"
        "}));\n"
    )
    proc = subprocess.run(
        [*cmd_prefix, script],
        cwd=ROOT,
        env=run_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["cjsDeepEqual"] is True
    assert report["winDeepEqual"] is True
    assert report["casesRefEqual"] is True
    assert report["extraKeys"] == []


def test_sibling_outthink_bundles_join_cleanly_when_present(
    cross_audit_bundle: dict[str, Any],
):
    ot = cross_audit_bundle["outthink"]
    for c in ot["cases"]:
        assert c["id"] and c["tier"] in ("medium", "hard") and isinstance(c["seed"], int)
        assert len(c["suspects"]) >= 4
        for lv in c["thinking_levels"]:
            assert lv["model"] and lv["thinking_level"] and lv["run_id"]

    cmd_prefix, env = _resolve_js_cmd()
    run_env = dict(env)
    run_env["OUTTHINK_DEMO_DIR"] = str(DEMO_DIR)
    script = (
        'const fs = require("fs");\n'
        'const path = require("path");\n'
        'const vm = require("vm");\n'
        "const dir = process.env.OUTTHINK_DEMO_DIR;\n"
        "const win = {};\n"
        "const box = { console, Date, Math, Number, String, Boolean, Array, Object, JSON, Set, Map, RegExp, Error, TypeError, parseInt, parseFloat, isNaN, isFinite };\n"
        "box.window = win;\n"
        "box.globalThis = win;\n"
        "box.self = win;\n"
        "vm.createContext(box);\n"
        "const loaded = [];\n"
        "for (const rel of ['assets/manifest.js', 'cases.js', 'annotations.js', 'evidence_cards.js', 'chatter.js', 'engine.js']) {\n"
        "  const p = path.join(dir, rel);\n"
        "  if (fs.existsSync(p)) {\n"
        "    vm.runInContext(fs.readFileSync(p, 'utf8'), box, { filename: rel });\n"
        "    loaded.push(rel);\n"
        "  }\n"
        "}\n"
        "const cases = win.OUTTHINK_CASES || [];\n"
        "let engineSummary = null;\n"
        "if (win.OutThinkEngine && typeof win.OutThinkEngine.loadDataset === 'function') {\n"
        "  const ds = win.OutThinkEngine.loadDataset();\n"
        "  engineSummary = { count: ds.count, isFallback: Boolean(ds.isFallback), isBootstrap: Boolean(ds.isBootstrapFallback) };\n"
        "}\n"
        "let annHits = 0;\n"
        "if (typeof win.getOutthinkAnnotation === 'function') {\n"
        "  for (const c of cases) {\n"
        "    for (const lv of c.thinking_levels || []) {\n"
        "      if (win.getOutthinkAnnotation(lv.model, lv.thinking_level, c.tier, c.seed)) annHits += 1;\n"
        "    }\n"
        "  }\n"
        "}\n"
        "let cardCount = 0;\n"
        "if (typeof win.listOutthinkEvidenceCards === 'function') {\n"
        "  cardCount = win.listOutthinkEvidenceCards().length;\n"
        "}\n"
        "let chatterChecked = 0;\n"
        "if (typeof win.getOutthinkChatter === 'function') {\n"
        "  for (const c of cases) {\n"
        "    const ch = win.getOutthinkChatter(c.id || c);\n"
        "    if (ch) chatterChecked += 1;\n"
        "  }\n"
        "}\n"
        "process.stdout.write(JSON.stringify({ loaded, caseCount: cases.length, engineSummary, annHits, cardCount, chatterChecked }));\n"
    )
    proc = subprocess.run(
        [*cmd_prefix, script],
        cwd=ROOT,
        env=run_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    res = json.loads(proc.stdout)
    assert "cases.js" in res["loaded"]
    assert res["caseCount"] == 12
    if "engine.js" in res["loaded"]:
        assert res["engineSummary"] == {"count": 12, "isFallback": False, "isBootstrap": False}
    if "annotations.js" in res["loaded"]:
        assert res["annHits"] == 39
    if "evidence_cards.js" in res["loaded"]:
        assert res["cardCount"] >= 1
    if "chatter.js" in res["loaded"]:
        assert res["chatterChecked"] >= 0


def test_validate_payload_catches_comprehensive_corruptions(
    cross_audit_bundle: dict[str, Any],
):
    base = cross_audit_bundle["outthink"]
    assert outthink.validate_payload(base) == []

    assert outthink.validate_payload({"cases": []}) == ["missing meta dict"]
    assert outthink.validate_payload({"meta": {}, "cases": base["cases"][:7]}) == [
        "cases must be a list of at least 8 decision points"
    ]

    dup_id = copy.deepcopy(base)
    dup_id["cases"][1]["id"] = dup_id["cases"][0]["id"]
    assert any("duplicate case id" in e for e in outthink.validate_payload(dup_id))

    missing_key = copy.deepcopy(base)
    del missing_key["cases"][0]["company"]
    assert any("missing key company" in e for e in outthink.validate_payload(missing_key))

    one_level = copy.deepcopy(base)
    one_level["cases"][0]["thinking_levels"] = one_level["cases"][0]["thinking_levels"][:1]
    assert any("fewer than 2 thinking_levels" in e for e in outthink.validate_payload(one_level))

    bad_lv = copy.deepcopy(base)
    bad_lv["cases"][0]["thinking_levels"][0]["run_id"] = ""
    bad_lv["cases"][0]["thinking_levels"][0]["ledger_calls"] = 0
    bad_lv["cases"][0]["thinking_levels"][0]["call_at_t"] = "wait"
    lv_errs = outthink.validate_payload(bad_lv)
    assert any("missing run_id" in e for e in lv_errs)
    assert any("zero ledger_calls" in e for e in lv_errs)
    assert any("invalid call_at_t" in e for e in lv_errs)

    all_accuse = copy.deepcopy(base)
    for c in all_accuse["cases"]:
        c["solver"]["recommended_call"] = "accuse"
    assert any("expected both accuse and hold_fire" in e for e in outthink.validate_payload(all_accuse))

    no_xhigh = copy.deepcopy(base)
    for c in no_xhigh["cases"]:
        c["thinking_levels"] = [lv for lv in c["thinking_levels"] if lv["thinking_level"] != "xhigh"]
    assert any("missing thinking level xhigh" in e for e in outthink.validate_payload(no_xhigh))


def test_ascii_encoding_and_zero_forbidden_characters_across_outthink_artifacts():
    for fpath in (OUTTHINK_JSON_PATH, CASES_JS_PATH):
        txt = fpath.read_text(encoding="utf-8")
        assert txt.isascii(), f"non-ASCII char in {fpath}"
        for dch in UNICODE_DASHES:
            assert dch not in txt, f"unicode dash in {fpath}"
        for code in (0x2012, 0x2013, 0x2014, 0x2015):
            esc = "\\u" + f"{code:04x}"
            assert esc not in txt.lower(), f"escaped dash {esc} in {fpath}"
        assert HTML_COMMENT_OPEN not in txt
        for tok in (FORBIDDEN_FETCH, FORBIDDEN_XHR, FORBIDDEN_WS, FORBIDDEN_BEACON):
            assert tok not in txt, f"forbidden network token {tok} in {fpath}"
        assert "AIza" not in txt
        assert "sk-" not in txt

    assert _find_js_comments(CASES_JS_PATH.read_text(encoding="utf-8")) == []


def test_self_hygiene_zero_comments_dashes_api_imports_and_three_dot_protected_paths():
    self_path = Path(__file__).resolve()
    for py_path in (OUTTHINK_PY_PATH, self_path):
        src = py_path.read_text(encoding="utf-8")
        assert HASH_CHAR not in src, f"hash char in {py_path}"
        for dch in UNICODE_DASHES:
            assert dch not in src, f"unicode dash in {py_path}"
        assert FORBIDDEN_FETCH not in src
        comments = [
            tok for tok in tokenize.generate_tokens(io.StringIO(src).readline) if tok.type == tokenize.COMMENT
        ]
        assert comments == []
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for banned in ("genai", "google", "httpx", "requests", "urllib"):
                        assert banned not in alias.name
            elif isinstance(node, ast.ImportFrom) and node.module:
                for banned in ("genai", "google", "httpx", "requests", "urllib"):
                    assert banned not in node.module

    rules = [
        ln.strip()
        for ln in PROTECTED_PATHS_FILE.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith(HASH_CHAR)
    ]
    checked = {self_path.relative_to(ROOT).as_posix()}

    status_proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if status_proc.returncode == 0:
        for line in status_proc.stdout.splitlines():
            if len(line) > 3:
                entry = line[3:].strip()
                if " -> " in entry:
                    entry = entry.split(" -> ", 1)[1].strip()
                checked.add(entry)

    diff_proc = subprocess.run(
        ["git", "diff", "--name-only", "origin/justSilas...HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if diff_proc.returncode == 0:
        for rel in diff_proc.stdout.splitlines():
            if rel.strip():
                checked.add(rel.strip())

    for rel in checked:
        for rule in rules:
            if rule.endswith("/"):
                assert not rel.startswith(rule), f"protected dir touched: {rel}"
            else:
                assert rel != rule, f"protected file touched: {rel}"
