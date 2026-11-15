from __future__ import annotations

import importlib.util
import json
import sys
import tokenize
from pathlib import Path

import pytest

from canary import world
from canary.env import Env
from canary.eval import run_episode
from canary.solver.policy import SolverPolicy

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "audit_arena_engine_parity.py"
REPORT_PATH = ROOT / "docs" / "reports" / "integrity_arena_engine_parity.md"
TEST_PATH = Path(__file__).resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("audit_arena_engine_parity", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


audit_mod = _load_module()


@pytest.fixture(scope="module")
def quick_audit_run(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("w4_arena_parity")
    out_json = out_dir / "arena_engine_parity.json"
    before_secret = world._SET_SECRET
    rc = audit_mod.main([
        "--quick",
        "--out-json",
        str(out_json),
        "--check-report",
        str(REPORT_PATH),
    ])
    after_secret = world._SET_SECRET
    assert out_json.is_file()
    summary = json.loads(out_json.read_text(encoding="utf-8"))
    return {
        "rc": rc,
        "before_secret": before_secret,
        "after_secret": after_secret,
        "summary": summary,
    }


def test_quick_end_to_end_arena_engine_parity_and_secret_restoration(quick_audit_run):
    assert quick_audit_run["rc"] == 0
    assert quick_audit_run["before_secret"] == quick_audit_run["after_secret"]

    s = quick_audit_run["summary"]
    assert s["all_passed"] is True
    assert s["live_api_calls"] == 0
    assert s["tiers_version"] == "v1.4"
    assert s["known_v_mode"] is True
    assert s["quick"] is True

    fp = s["fuzz_parity"]
    assert fp["passed"] is True
    assert fp["targets"] == ["easy", "medium", "hard", "hard_forge", "hard_rl"]
    assert fp["states_checked"] >= 200
    assert fp["unsurfaced_leak_states_checked"] >= 50
    assert fp["detail_role_parity_checks"] >= 120
    assert fp["violations_count"] == 0
    assert fp["outcome_counts"]["correct_accuse"] >= 5
    assert fp["outcome_counts"]["wrong_accuse"] >= 5
    assert fp["outcome_counts"]["abstain_horizon"] >= 5
    assert fp["outcome_counts"]["tool_cap"] >= 1

    fw = fp["game_seed_firewall"]
    assert fw["judge_seeds_probed"] == 40
    assert fw["judge_seeds_refused"] == 40
    assert fw["heldout_seeds_probed"] == 200
    assert fw["heldout_seeds_refused"] == 200
    assert fw["low_dev_seeds_probed"] >= 30
    assert fw["low_dev_seeds_refused"] == fw["low_dev_seeds_probed"]
    assert fw["malformed_seeds_refused"] == fw["malformed_seeds_probed"]
    assert fw["violations"] == []

    pc = s["planted_controls"]
    assert pc["passed"] is True
    assert pc["clean_control_false_positives"] == 0
    assert pc["controls_total"] == 8
    assert pc["controls_caught"] == 8

    cs = s["cross_squad"]
    assert cs["passed"] is True
    assert cs["targets_configured"] == 5
    assert cs["refs_present"] + cs["refs_skipped_absent"] == 5
    assert cs["hard_failures"] == 0
    for surf in cs["surfaces"].values():
        if surf["present"]:
            assert surf["status"] == "PASS"
            assert surf["pre_end_leaks"] == []
        else:
            assert surf["status"] == "SKIPPED_ABSENT_REF"

    for issue in s["report_only_issues"]:
        assert str(issue["id"]).startswith("ISSUE-ARENA-ENGINE-")


def test_missing_remote_refs_gracefully_skip_in_single_branch_ci(tmp_path):
    out_json = tmp_path / "absent_refs.json"
    rc = audit_mod.main([
        "--quick",
        "--simulate-missing-refs",
        "--out-json",
        str(out_json),
    ])
    assert rc == 0
    summary = json.loads(out_json.read_text(encoding="utf-8"))
    assert summary["all_passed"] is True
    cs = summary["cross_squad"]
    assert cs["passed"] is True
    assert cs["refs_present"] == 0
    assert cs["refs_skipped_absent"] == 5
    assert summary["report_only_issues"] == []
    for surf in cs["surfaces"].values():
        assert surf["present"] is False
        assert surf["status"] == "SKIPPED_ABSENT_REF"


def test_synthetic_cross_squad_fixtures_and_leak_detectors():
    synth_eval_py = (
        "import json\n"
        "from canary.env import Env\n"
        "from canary.eval import run_episode\n"
        "def actions_from_episode(ep):\n"
        "    return [[st.tool, dict(st.args)] for st in ep.steps]\n"
        "def verify_action_list_parity(tier, seed, actions):\n"
        "    env = Env(tier, int(seed))\n"
        "    for t, a in actions:\n"
        "        env.call(t, a)\n"
        "    v = env.verdict()\n"
        "    return {'ok': True, 'score': v['score'], 'correct': v['correct'], 'accused': v['accused']}\n"
        "def duel_end_screen_summary(tier, seed, h, g, s):\n"
        "    return {'caught_first': 'gemini'}\n"
        "class ArenaSession:\n"
        "    def __init__(self, tier, seed):\n"
        "        self.env = Env(tier, int(seed))\n"
        "    def reveal_json(self):\n"
        "        return json.dumps({'error': 'the episode is not over yet'})\n"
    )
    eval_res, eval_issues = audit_mod.audit_eval_scoring_parity_source(synth_eval_py, "synthetic:eval")
    assert eval_res["status"] == "PASS"
    assert any(i["id"] == "ISSUE-ARENA-ENGINE-EVAL-SESSION-UNBOUNDED-SEED" for i in eval_issues)

    synth_mole_leaky_py = (
        "class _S:\n"
        "    last_applied = {'can_leak_gate': False, 'leak': 'd1-1'}\n"
        "class MoleModeSession:\n"
        "    def __init__(self, seed, tier='medium'):\n"
        "        if not isinstance(seed, int) or isinstance(seed, bool) or not (3000 <= seed <= 9999):\n"
        "            raise ValueError('bad seed')\n"
        "        from canary.env import Env\n"
        "        self._env = Env(tier, seed)\n"
        "        self._strategy = _S()\n"
        "        self.done = False\n"
        "    def get_mole_debrief(self):\n"
        "        if not self.done:\n"
        "            return {'ok': False, 'done': False}\n"
        "        return {'ok': True, 'solver_score': self._env.score()}\n"
        "    def get_mole_day_view(self):\n"
        "        return {'day': 1, 'done': False, 'leakable_docs': [{'doc_id': 'doc-1', 'is_canary': True}]}\n"
        "    def step_mole_day(self, action):\n"
        "        self.done = True\n"
        "        return {'ok': True}\n"
    )
    mm_res, _ = audit_mod.audit_strategies_mole_mode_source(synth_mole_leaky_py, "synthetic:mole", quick=True)
    assert mm_res["status"] == "FAIL"
    assert any("is_canary" in x for x in mm_res["pre_end_leaks"])

    sol_3000 = run_episode(Env("medium", 3000), SolverPolicy())
    sol_6 = run_episode(Env("hard", 6), SolverPolicy())
    mole_6 = Env("hard", 6)._world.mole
    decoy_6 = Env("hard", 6)._world.decoy

    bad_seeds_md = (
        "Catalog\n```json\n"
        + json.dumps({
            "schema_version": "canary_arena_seeds_v1",
            "mode_1_solo_investigator": {
                "curated_public_seeds": [3000],
                "default_seed_solver_benchmark": {
                    "seed": 3000,
                    "score": sol_3000.score,
                    "final_day": sol_3000.final_day,
                    "tool_calls": len(sol_3000.steps),
                    "correct": sol_3000.correct,
                    "live_mole_id": "e09",
                },
            },
            "mode_2_ai_duel": {"headline_seeds": []},
        })
        + "\n```\n"
    )
    sd_res, _ = audit_mod.audit_research_seeds_catalog_source(bad_seeds_md, "synthetic:seeds", quick=True)
    assert sd_res["status"] == "FAIL"
    assert "mode_1_default_seed_live_mole_not_sealed" in sd_res["pre_end_leaks"]

    clean_living_js = "export const CANARY_LIVING_OFFICE_PACK = " + json.dumps({
        "default_enabled": False,
        "off_by_default": True,
        "gateBPassed": False,
        "gate_b_passed": False,
        "provenance": {"offline_only": True, "live_api_calls": 0, "cache_prompts_hit": 54},
        "episodes": {
            "hard:6": {
                "tier": "hard",
                "seed": 6,
                "days": [{"day": d, "new_rumours": []} for d in range(1, 22)],
                "sealed_reveal": {
                    "mole": mole_6,
                    "decoy": decoy_6,
                    "solver_accused": sol_6.accused,
                    "solver_correct": sol_6.correct,
                    "solver_final_day": sol_6.final_day,
                    "solver_score": round(float(sol_6.score), 4),
                },
            }
        },
    }) + ";\n"
    lo_ok, _ = audit_mod.audit_staffai_living_office_source(clean_living_js, "synthetic:living", quick=True)
    assert lo_ok["status"] == "PASS"

    leaky_living_js = clean_living_js.replace('"new_rumours": []', '"new_rumours": [], "mole": "e34"')
    lo_bad, _ = audit_mod.audit_staffai_living_office_source(leaky_living_js, "synthetic:living_bad", quick=True)
    assert lo_bad["status"] == "FAIL"
    assert any(".mole" in x for x in lo_bad["pre_end_leaks"])

    bad_replay_js = "export class CanaryReplayEngine {}\n"
    re_bad, _ = audit_mod.audit_port_replay_engine_source(bad_replay_js, "synthetic:replay_bad", quick=True)
    assert re_bad["status"] == "FAIL"


def test_report_and_owned_files_strict_hygiene_gates(tmp_path):
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    minus_sign = chr(0x2212)
    banned_a = "pre-" + "reg"
    banned_b = "pre" + "reg"
    co_author = "-".join(("Co", "Authored", "By"))

    bad_md = tmp_path / "bad_report.md"
    bad_md.write_text(f"bad {em_dash} {en_dash} {minus_sign} {banned_a} {banned_b} {co_author}\n", encoding="utf-8")
    bad_chk = audit_mod.check_report_hygiene(bad_md)
    assert bad_chk["ok"] is False
    assert "em_dash" in bad_chk["problems"]
    assert "en_dash" in bad_chk["problems"]
    assert "unicode_minus" in bad_chk["problems"]
    assert f"banned_term:{banned_a}" in bad_chk["problems"]
    assert f"banned_term:{banned_b}" in bad_chk["problems"]
    assert "co_authored_by" in bad_chk["problems"]

    rep_chk = audit_mod.check_report_hygiene(REPORT_PATH)
    assert rep_chk == {"ok": True, "problems": []}

    rep_txt = REPORT_PATH.read_text(encoding="utf-8")
    for token in (
        "58716742",
        "KNOWN_V_MODE",
        "1,745",
        "1,151",
        "40/40",
        "200/200",
        "8/8",
        "1bc3e281",
        "ISSUE-ARENA-ENGINE-MOLE-PLEAK-GATE-BYPASS",
        "ISSUE-ARENA-ENGINE-MOLE-RECIPIENT-LIST-EXPOSURE",
        "ISSUE-ARENA-ENGINE-EVAL-SESSION-UNBOUNDED-SEED",
        "ISSUE-ARENA-ENGINE-REPLAY-COMPACT-RESTRICT-AND-ZEROV",
        "ISSUE-ARENA-ENGINE-DUEL-TIEBREAK-ORDER-DIVERGENCE",
        "ISSUE-ARENA-ENGINE-SEEDS-DOC-REJECTED-INTERVIEW-COUNT",
    ):
        assert token in rep_txt, token

    for path in (SCRIPT_PATH, REPORT_PATH, TEST_PATH):
        assert path.is_file(), path
        assert path.stat().st_size <= 130 * 1024, (path, path.stat().st_size)
        txt = path.read_text(encoding="utf-8")
        assert em_dash not in txt, path
        assert en_dash not in txt, path
        assert minus_sign not in txt, path
        assert banned_a not in txt.lower(), path
        assert banned_b not in txt.lower(), path
        assert co_author.lower() not in txt.lower(), path

    for py_path in (SCRIPT_PATH, TEST_PATH):
        with open(py_path, "rb") as fh:
            comments = [tok for tok in tokenize.tokenize(fh.readline) if tok.type == tokenize.COMMENT]
        assert comments == [], (py_path, comments)
