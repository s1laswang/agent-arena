from __future__ import annotations

import ast
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pytest

from canary import rules
from canary.env import Env
from canary.eval import run_episode
from canary.forge.rl_mole import _agent
from canary.mole.dsl import FRAME_SELECTORS, LEAK_SELECTORS, MoleDoc, MoleView
import train

if str(ROOT / "train") not in train.__path__:
    train.__path__.insert(0, str(ROOT / "train"))

import train.batched_mole_eval as bme
from train.grpo_mole import parse_action
from train.qwen_diverse_mole import QwenMolePolicy, TinyByteTokenizer

IMPL_PATH = ROOT / "train" / "batched_mole_eval.py"
TEST_PATH = Path(__file__).resolve()


def _make_view(
    *,
    day: int = 2,
    can_leak: bool = True,
    restricted: int = 0,
    recipient_counts: tuple[int, ...] = (6, 14),
    decoy: str | None = "e03",
) -> MoleView:
    docs = tuple(
        MoleDoc(
            doc_id=f"d{day}_{idx}",
            title=f"Memo {day}_{idx}",
            recipient_count=rc,
            age_days=idx % 3,
        )
        for idx, rc in enumerate(recipient_counts)
    )
    low_cnt = sum(1 for rc in recipient_counts if rc <= 3)
    return MoleView(
        day=day,
        docs=docs,
        days_since_last_leak=1,
        i_am_restricted=restricted,
        n_restricted_colleagues=1,
        recent_low_recipient_docs=low_cnt,
        peers=("e01", "e02", "e03", "e04"),
        restricted_peers=("e02",),
        decoy=decoy,
        can_leak=can_leak,
    )


def test_hygiene_lazy_imports_and_canonical_candidates():
    hash_ch = chr(35)
    em_dash = chr(0x2014)
    for fp in (IMPL_PATH, TEST_PATH):
        txt = fp.read_text(encoding="utf-8")
        assert hash_ch not in txt, f"forbidden hash character in {fp.name}"
        assert em_dash not in txt, f"forbidden em-dash character in {fp.name}"

    tree = ast.parse(IMPL_PATH.read_text(encoding="utf-8"))
    forbidden_top = {"torch", "transformers", "peft"}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden_top
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden_top

    assert len(bme.CANONICAL_ACTIONS) == 24
    assert len(bme.CANONICAL_CANDIDATES) == 24
    assert len(LEAK_SELECTORS) * len(FRAME_SELECTORS) == 24
    for act, cand_json in zip(bme.CANONICAL_ACTIONS, bme.CANONICAL_CANDIDATES):
        assert parse_action(cand_json) == act


def test_dynamic_batch_policy_matches_sequential_episode_scores_and_decisions():
    def _deterministic_single(prompt: str) -> str:
        idx = sum(prompt.encode("utf-8")) % len(bme.CANONICAL_CANDIDATES)
        return bme.CANONICAL_CANDIDATES[idx]

    batch_lock = threading.Lock()
    recorded_batches: list[list[str]] = []

    def _deterministic_batch(prompts: list[str]) -> list[str]:
        time.sleep(0.002)
        with batch_lock:
            recorded_batches.append(list(prompts))
        return [_deterministic_single(p) for p in prompts]

    seeds = [4, 5, 6, 7]
    tier = "easy"

    seq_pol = QwenMolePolicy(generate_fn=_deterministic_single)
    seq_rows: list[dict[str, tuple[float, bool]]] = []
    seq_decisions: dict[tuple[int, str], list[dict]] = {}

    class _DecisionRecorder:
        def __init__(self, inner, log_list: list[dict]):
            self.inner = inner
            self.log_list = log_list

        def decide(self, view: MoleView, rng: random.Random) -> dict:
            out = self.inner.decide(view, rng)
            self.log_list.append(dict(out))
            return out

    for s in seeds:
        row: dict[str, tuple[float, bool]] = {}
        for ag in bme.ALL_AGENTS:
            decs: list[dict] = []
            ep = run_episode(Env(tier, s, mole_strategy=_DecisionRecorder(seq_pol, decs)), _agent(ag, tier, s))
            row[ag] = (float(ep.score), bool(ep.correct))
            seq_decisions[(s, ag)] = decs
        seq_rows.append(row)

    dyn_pol = bme.DynamicBatchMolePolicy(
        max_batch_size=4,
        wait_ms=8.0,
        batch_generate_fn=_deterministic_batch,
    )
    rep = bme.evaluate_batched_mole(
        policy=dyn_pol,
        seeds=seeds,
        tier=tier,
        concurrency=8,
        workers=1,
        bootstrap_resamples=200,
        include_rows=True,
    )
    assert rep["episode_rows"]["candidate"] == seq_rows

    all_seen = [p for batch in recorded_batches for p in batch]
    assert len(all_seen) == len(set(all_seen))
    assert dyn_pol.unique_prompts == len(all_seen)
    assert dyn_pol.unique_prompts == seq_pol.calls
    assert dyn_pol.total_decisions == len(seq_pol.actions)
    assert dyn_pol.cache_hits == dyn_pol.total_decisions - dyn_pol.unique_prompts
    assert dyn_pol.cache_hits > 0
    assert rep["cache_hit_rate"] > 0.0
    assert rep["invalid_rate"] == 0.0
    assert max(len(b) for b in recorded_batches) > 1
    assert max(len(b) for b in recorded_batches) <= 4
    assert rep["batching_stats"]["call_reduction_vs_uncached"] > 1.0

    for s in seeds:
        for ag in bme.ALL_AGENTS:
            decs_check: list[dict] = []
            ep_check = run_episode(
                Env(tier, s, mole_strategy=_DecisionRecorder(dyn_pol, decs_check)),
                _agent(ag, tier, s),
            )
            assert (float(ep_check.score), bool(ep_check.correct)) == seq_rows[seeds.index(s)][ag]
            assert decs_check == seq_decisions[(s, ag)]


def test_dynamic_batch_invalid_fallback_and_left_padding_invariance():
    call_idx = 0

    def _mixed_batch(prompts: list[str]) -> list[str]:
        nonlocal call_idx
        out = []
        for p in prompts:
            call_idx += 1
            if "Day 1." in p:
                out.append("not valid json output")
            else:
                out.append('{"leak": "most_recipients", "frame": "decoy"}')
        return out

    pol = bme.DynamicBatchMolePolicy(max_batch_size=4, wait_ms=0.0, batch_generate_fn=_mixed_batch)
    v1 = _make_view(day=1, recipient_counts=(5, 18))
    v2 = _make_view(day=2, recipient_counts=(5, 18))
    d1 = pol.decide(v1, random.Random(0))
    d2 = pol.decide(v2, random.Random(0))
    assert d1["frame"] is None
    assert d2 == {"leak": "d2_1", "frame": "e03"}
    st = pol.stats()
    assert st["invalid_generations"] == 1
    assert st["unique_prompts"] == 2
    assert math.isclose(st["invalid_rate"], 0.5, abs_tol=1e-6)

    tok = TinyByteTokenizer()
    lm = bme.TinyNumpyCausalLM(vocab_size=len(tok), hidden_size=32, seed=11)
    p_short = _make_view(day=1, recipient_counts=(12,))
    p_long = _make_view(day=4, recipient_counts=(4, 8, 12, 16, 22))
    pol_b1 = bme.DynamicBatchMolePolicy(model=lm, tok=tok, max_new_tokens=16, max_batch_size=1, wait_ms=0.0)
    pol_b8 = bme.DynamicBatchMolePolicy(model=lm, tok=tok, max_new_tokens=16, max_batch_size=8, wait_ms=10.0)
    pol_b8.prepare_run(total_episodes=2, concurrency=2)

    raw_b1 = pol_b1._generate_texts([bme.render_view(p_short), bme.render_view(p_long)])
    raw_b8 = pol_b8._generate_texts([bme.render_view(p_short), bme.render_view(p_long)])
    assert raw_b1 == raw_b8


def test_constrained_logprob_probs_sum_to_one_trap_only_none_and_mutual_info():
    def _none_preferring_scorer(prompt: str, candidates: list[str]) -> list[float]:
        scores: list[float] = []
        bias = (len(prompt) % 7) * 0.2
        for i, cand in enumerate(candidates):
            obj = json.loads(cand)
            if obj["leak"] == "none":
                scores.append(35.0 + 0.1 * i)
            elif obj["leak"] == "most_recipients" and obj["frame"] == "decoy":
                scores.append(4.0 + bias)
            else:
                scores.append(-1.0 - 0.05 * i)
        return scores

    pol_masked = bme.ConstrainedLogprobMolePolicy(
        trap_only_none=True,
        greedy=True,
        score_candidates_fn=_none_preferring_scorer,
        wait_ms=0.0,
    )
    pol_unmasked = bme.ConstrainedLogprobMolePolicy(
        trap_only_none=False,
        greedy=True,
        score_candidates_fn=_none_preferring_scorer,
        wait_ms=0.0,
    )

    v_wide_open = _make_view(day=2, can_leak=True, restricted=0, recipient_counts=(4, 9))
    probs_masked = pol_masked.action_probabilities(v_wide_open)
    assert len(probs_masked) == 24
    assert math.isclose(sum(probs_masked), 1.0, abs_tol=1e-9)
    for i, (lsel, _) in enumerate(bme.CANONICAL_ACTIONS):
        if lsel == "none":
            assert probs_masked[i] == 0.0
        else:
            assert probs_masked[i] > 0.0

    dec_masked = pol_masked.decide(v_wide_open, random.Random(0))
    assert dec_masked == {"leak": "d2_1", "frame": "e03"}
    assert pol_masked.stats()["invalid_rate"] == 0.0
    assert pol_masked.stats()["masked_none_states"] == 1

    class _ZeroRng(random.Random):
        def random(self) -> float:
            return 0.0

    pol_stoch = bme.ConstrainedLogprobMolePolicy(
        trap_only_none=True,
        greedy=False,
        score_candidates_fn=_none_preferring_scorer,
        wait_ms=0.0,
    )
    dec_stoch = pol_stoch.decide(v_wide_open, _ZeroRng(0))
    assert dec_stoch["leak"] is not None

    v_narrow_trap = _make_view(day=3, can_leak=True, restricted=0, recipient_counts=(3, 8))
    probs_narrow = pol_masked.action_probabilities(v_narrow_trap)
    assert math.isclose(sum(probs_narrow), 1.0, abs_tol=1e-9)
    assert sum(probs_narrow[i] for i, (l, _) in enumerate(bme.CANONICAL_ACTIONS) if l == "none") > 0.99
    assert pol_masked.decide(v_narrow_trap, random.Random(0))["leak"] is None

    v_restricted = _make_view(day=4, can_leak=True, restricted=1, recipient_counts=(12, 20))
    probs_rest = pol_masked.action_probabilities(v_restricted)
    assert math.isclose(sum(probs_rest), 1.0, abs_tol=1e-9)
    assert pol_masked.decide(v_restricted, random.Random(0))["leak"] is None

    v_noleak = _make_view(day=5, can_leak=False, restricted=0, recipient_counts=(12, 20))
    probs_noleak = pol_masked.action_probabilities(v_noleak)
    assert math.isclose(sum(probs_noleak), 1.0, abs_tol=1e-9)
    assert sum(probs_noleak[i] for i, (l, _) in enumerate(bme.CANONICAL_ACTIONS) if l == "none") > 0.99

    probs_unmasked = pol_unmasked.action_probabilities(v_wide_open)
    assert math.isclose(sum(probs_unmasked), 1.0, abs_tol=1e-9)
    assert pol_unmasked.decide(v_wide_open, random.Random(0))["leak"] is None

    pol_const = bme.ConstrainedLogprobMolePolicy(
        score_candidates_fn=lambda _p: [float(-i) for i in range(24)],
        wait_ms=0.0,
    )
    pol_const.decide(v_wide_open, random.Random(0))
    pol_const.decide(v_narrow_trap, random.Random(0))
    mi_const = pol_const.empirical_mutual_information()
    assert mi_const["mi_nats"] == 0.0
    assert mi_const["mi_bits"] == 0.0

    def _two_state_peaked(prompt: str) -> list[float]:
        vec = [-40.0] * 24
        if "Day 2." in prompt:
            vec[0] = 0.0
        else:
            vec[9] = 0.0
        return vec

    pol_peaked = bme.ConstrainedLogprobMolePolicy(score_candidates_fn=_two_state_peaked, wait_ms=0.0)
    pol_peaked.decide(v_wide_open, random.Random(0))
    pol_peaked.decide(v_narrow_trap, random.Random(0))
    mi_peaked = pol_peaked.empirical_mutual_information()
    assert math.isclose(mi_peaked["mi_nats"], math.log(2.0), abs_tol=1e-4)
    assert math.isclose(mi_peaked["mi_bits"], 1.0, abs_tol=1e-4)
    assert math.isclose(sum(mi_peaked["mean_action_probs"].values()), 1.0, abs_tol=1e-5)


def test_judge_seeds_refused():
    dummy_pol = bme.DynamicBatchMolePolicy(
        wait_ms=0.0,
        batch_generate_fn=lambda ps: ['{"leak": "most_recipients", "frame": "none"}' for _ in ps],
    )
    for bad_seeds in (
        [rules.JUDGE_SEEDS.start],
        [rules.JUDGE_SEEDS.stop - 1],
        [800_000, rules.JUDGE_SEEDS.start],
        [-1],
        [],
    ):
        with pytest.raises(ValueError):
            bme.guard_eval_seeds(bad_seeds)
        with pytest.raises(ValueError):
            bme.evaluate_batched_mole(dummy_pol, seeds=bad_seeds, tier="easy", concurrency=2)

    for bad_spec in ("judge", "900000", "899999-900002", "800000,900005"):
        with pytest.raises(ValueError):
            bme.parse_seeds(bad_spec, n=5)
        with pytest.raises(ValueError):
            bme.main(["--tiny", "--seeds", bad_spec, "--n", "2", "--tier", "easy"])


def test_cli_tiny_end_to_end_greedy_and_constrained(tmp_path):
    greedy_out = tmp_path / "greedy_eval.json"
    t0 = time.perf_counter()
    rc_g = bme.main(
        [
            "--tiny",
            "--mode",
            "greedy",
            "--tier",
            "easy",
            "--seeds",
            "heldout",
            "--n",
            "2",
            "--batch-size",
            "8",
            "--concurrency",
            "4",
            "--bootstrap-resamples",
            "200",
            "--out",
            str(greedy_out),
        ]
    )
    dt_g = time.perf_counter() - t0
    assert rc_g == 0
    assert dt_g < 30.0
    assert greedy_out.is_file()
    rep_g = json.loads(greedy_out.read_text(encoding="utf-8"))
    assert rep_g["mode"] == "greedy"
    assert rep_g["tiny"] is True
    assert rep_g["n"] == 2
    assert rep_g["agents"] == ["solver", "grok_tactics", "heuristic", "hinted_heuristic"]
    assert isinstance(rep_g["catchable_85"], bool)
    assert 0.0 <= rep_g["invalid_rate"] <= 1.0
    assert 0.0 <= rep_g["cache_hit_rate"] <= 1.0
    assert "default_mole" in rep_g
    assert "diff_candidate_minus_default" in rep_g
    if (ROOT / bme.DEFAULT_RL_MOLE_PATH).is_file():
        assert "rl_mole" in rep_g
        assert "diff_candidate_minus_rl_mole" in rep_g
    if (ROOT / bme.DEFAULT_RL_MOLE_V2_PATH).is_file():
        assert "rl_mole_v2" in rep_g
        assert "diff_candidate_minus_rl_mole_v2" in rep_g
    for ag in bme.ALL_AGENTS:
        mean_s, lo_s, hi_s = rep_g["candidate_mole"][ag]["score_ci95"]
        assert lo_s <= mean_s <= hi_s

    constrained_out = tmp_path / "constrained_eval.json"
    t1 = time.perf_counter()
    rc_c = bme.main(
        [
            "--tiny",
            "--mode",
            "constrained",
            "--trap-only-none",
            "--tier",
            "easy",
            "--seeds",
            "ws3",
            "--n",
            "2",
            "--batch-size",
            "8",
            "--concurrency",
            "4",
            "--bootstrap-resamples",
            "200",
            "--out",
            str(constrained_out),
        ]
    )
    dt_c = time.perf_counter() - t1
    assert rc_c == 0
    assert dt_c < 30.0
    assert constrained_out.is_file()
    rep_c = json.loads(constrained_out.read_text(encoding="utf-8"))
    assert rep_c["mode"] == "constrained"
    assert rep_c["invalid_rate"] == 0.0
    assert rep_c["policy_stats"]["invalid_generations"] == 0
    assert rep_c["policy_stats"]["trap_only_none"] is True
    mi = rep_c["policy_stats"]["mutual_information"]
    assert mi["n_states"] == rep_c["policy_stats"]["total_decisions"]
    assert mi["mi_nats"] >= 0.0
    assert math.isclose(sum(mi["mean_action_probs"].values()), 1.0, abs_tol=1e-4)

    sub_out = tmp_path / "subprocess_tiny.json"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "train.batched_mole_eval",
            "--tiny",
            "--mode",
            "constrained",
            "--tier",
            "easy",
            "--seeds",
            "200010-200011",
            "--n",
            "2",
            "--no-rl-baselines",
            "--out",
            str(sub_out),
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        check=True,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    sub_rep = json.loads(sub_out.read_text(encoding="utf-8"))
    assert sub_rep["seed_range"] == [200010, 200011]
    assert sub_rep["invalid_rate"] == 0.0


def test_tiny_numpy_exact_scoring_and_constrained_concurrent_determinism():
    tok = TinyByteTokenizer()
    lm = bme.TinyNumpyCausalLM(vocab_size=len(tok), hidden_size=32, seed=3)
    p_ids_a = [10, 25, 44, 19, 88]
    p_ids_b = [7, 13, 99]
    c_ids_0 = [127, 42, 66, 129]
    c_ids_1 = [127, 55, 129]
    pairs = [
        (0, 0, p_ids_a, c_ids_0),
        (0, 1, p_ids_a, c_ids_1),
        (1, 0, p_ids_b, c_ids_0),
        (1, 1, p_ids_b, c_ids_1),
    ]
    fast_scores = {(pi, ci): val for pi, ci, val in lm.score_candidates(pairs, pad_id=0, length_norm=False)}
    for pi, ci, p_ids, c_ids in pairs:
        seq = np.asarray([p_ids + c_ids], dtype=np.int64)
        att = np.ones_like(seq)
        full_logits = lm.forward_logits(seq, att)[0, len(p_ids) - 1 : len(p_ids) + len(c_ids) - 1].astype(np.float64)
        m = np.max(full_logits, axis=-1, keepdims=True)
        lp = full_logits - (m + np.log(np.sum(np.exp(full_logits - m), axis=-1, keepdims=True)))
        ref = float(sum(lp[idx, tok_id] for idx, tok_id in enumerate(c_ids)))
        assert math.isclose(fast_scores[(pi, ci)], ref, rel_tol=1e-5, abs_tol=1e-5)

    seeds = [12, 13, 14]
    pol_seq = bme.ConstrainedLogprobMolePolicy(
        model=lm,
        tok=tok,
        trap_only_none=True,
        max_batch_size=1,
        wait_ms=0.0,
    )
    pol_conc = bme.ConstrainedLogprobMolePolicy(
        model=lm,
        tok=tok,
        trap_only_none=True,
        max_batch_size=6,
        wait_ms=6.0,
    )
    rep_seq = bme.evaluate_batched_mole(
        pol_seq,
        seeds=seeds,
        tier="easy",
        concurrency=1,
        bootstrap_resamples=100,
        include_rows=True,
    )
    rep_conc = bme.evaluate_batched_mole(
        pol_conc,
        seeds=seeds,
        tier="easy",
        concurrency=8,
        bootstrap_resamples=100,
        include_rows=True,
    )
    assert rep_conc["episode_rows"]["candidate"] == rep_seq["episode_rows"]["candidate"]
    assert math.isclose(
        rep_conc["policy_stats"]["unique_state_mutual_info_nats"],
        rep_seq["policy_stats"]["unique_state_mutual_info_nats"],
        abs_tol=1e-6,
    )
    assert rep_conc["policy_stats"]["unique_state_mutual_info_nats"] > 0.0


def test_seed_parsing_and_peft_merge_lifecycle_guard():
    assert bme.parse_seeds("heldout", 4) == [800_000, 800_001, 800_002, 800_003]
    assert bme.parse_seeds("ws3", 3) == [200_000, 200_001, 200_002]
    assert bme.parse_seeds("dev", 2) == [0, 1]
    assert bme.parse_seeds("200010-200015", 3) == [200_010, 200_011, 200_012]
    assert bme.parse_seeds("200010-200012", 0) == [200_010, 200_011, 200_012]
    assert bme.parse_seeds("15,18-19", 10) == [15, 18, 19]

    class _MockCfg:
        use_cache = False

    class _MockPeft:
        def __init__(self):
            self.config = _MockCfg()
            self.events: list[str] = []

        def merge_adapter(self) -> None:
            self.events.append("merge")

        def unmerge_adapter(self) -> None:
            self.events.append("unmerge")

    mock_peft = _MockPeft()
    pol = bme.DynamicBatchMolePolicy(
        model=mock_peft,
        wait_ms=0.0,
        batch_generate_fn=lambda ps: ['{"leak": "most_recipients", "frame": "decoy"}' for _ in ps],
    )
    rep = bme.evaluate_batched_mole(pol, seeds=[20], tier="easy", concurrency=2, bootstrap_resamples=50)
    assert rep["n"] == 1
    assert mock_peft.events == ["merge", "unmerge"]
    assert mock_peft.config.use_cache is False

