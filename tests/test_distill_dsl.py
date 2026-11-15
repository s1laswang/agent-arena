from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary import forge_track
from canary.env import Env
from canary.eval import run_episode
from canary.mole import distill_dsl
from canary.mole.dsl import MoleStrategy
from canary.solver.policy import SolverPolicy

IMPL_PATH = ROOT / "canary" / "mole" / "distill_dsl.py"
HOF_PATH = ROOT / "data" / "forge" / "hall_of_fame_carbon_distilled.jsonl"
EVAL_PATH = ROOT / "results" / "moletrain" / "carbon_distilled_dsl_eval.json"
TEST_PATH = Path(__file__).resolve()


def test_hygiene_and_artifact_sizes():
    hash_ch = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    for fp in (IMPL_PATH, TEST_PATH):
        txt = fp.read_text(encoding="utf-8")
        assert hash_ch not in txt
        assert em_dash not in txt
        assert en_dash not in txt
    for fp in (HOF_PATH, EVAL_PATH):
        txt = fp.read_text(encoding="utf-8")
        assert em_dash not in txt
        assert en_dash not in txt
    assert EVAL_PATH.stat().st_size < 40_000


def test_map_turn_to_selectors_and_candidates():
    turn_leak = {
        "tier": "hard",
        "leak": "d2",
        "frame": "e03",
        "mole_view": {
            "day": 2,
            "days_since_last_leak": 1,
            "held_docs": [
                {"doc_id": "d1", "recipient_count": 2, "age_days": 0},
                {"doc_id": "d2", "recipient_count": 18, "age_days": 2},
            ],
            "decoy": "e03",
            "peers": ["e01", "e02", "e03"],
            "restricted_peers": ["e02"],
        },
    }
    assert distill_dsl.map_turn_to_selectors(turn_leak) == ("most_recipients", "decoy")

    turn_withhold = {
        "tier": "hard",
        "leak": None,
        "frame": "e02",
        "mole_view": {
            "day": 3,
            "days_since_last_leak": 1,
            "held_docs": [{"doc_id": "d3", "recipient_count": 3, "age_days": 0}],
            "decoy": "e03",
            "peers": ["e01", "e02", "e03"],
            "restricted_peers": ["e02"],
        },
    }
    assert distill_dsl.map_turn_to_selectors(turn_withhold) == ("none", "most_restricted_peer")

    stats = distill_dsl.extract_turn_statistics([turn_leak, turn_withhold])
    cands = distill_dsl.distill_candidates(stats)
    assert len(cands) >= 5
    for c in cands:
        st = MoleStrategy.from_json(c)
        assert 1 <= len(st.rules) <= distill_dsl.MAX_DISTILLED_RULES


def test_offline_check_and_episode_replay():
    assert distill_dsl.main(["--check"]) == 0
    res = distill_dsl.check_distilled_artifacts()
    assert res["ok"] is True
    assert res["hof_entries"] == 5

    rows, strats = forge_track.load(HOF_PATH)
    assert len(rows) == 5 and len(strats) == 5
    ep1 = run_episode(Env("easy", 200_000, mole_strategy=strats[0]), SolverPolicy("easy"))
    ep2 = run_episode(Env("easy", 200_000, mole_strategy=strats[0]), SolverPolicy("easy"))
    assert (ep1.score, ep1.correct, ep1.accused) == (ep2.score, ep2.correct, ep2.accused)

    doc = json.loads(EVAL_PATH.read_text(encoding="utf-8"))
    comb = doc["heldout_eval"]["combined_100"]["moles"]
    assert comb["top_distilled"]["catchable_85"] is True
    assert comb["hof_rotation"]["catchable_85"] is True
