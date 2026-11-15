from __future__ import annotations

import ast
import io
import json
import re
import sys
import tokenize
from pathlib import Path
from typing import Any

import pytest

from canary.env import Env
from canary.eval import run_episode
from canary.rules import TRAIN_SEEDS
from canary.solver.policy import SolverPolicy
from train.compact_render import (
    CompactHFPolicy,
    REQUIRED_PARAM_KEYS,
    compact_system_text,
    compact_tools_spec,
    compact_turn_window,
    compact_user_text,
    estimate_compact_tokens,
    extract_public_ledger,
    parse_instruction_params,
    render_compact_episode_turns,
    render_compact_messages,
    render_compact_prompt_text,
    render_compact_step_prompt,
    render_compact_turn,
)
from train.render import KICKOFF, to_openai_tools

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPACT_RENDER_PATH = REPO_ROOT / "train" / "compact_render.py"
SELF_PATH = Path(__file__).resolve()

FORBIDDEN_TOP_IMPORTS = frozenset({
    "torch",
    "transformers",
    "canary.solver",
    "canary.world",
    "canary.env",
})


class _PureMockTokenizer:
    _TOK_RE = re.compile(r"\S+")

    def apply_chat_template(
        self,
        msgs: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tokenize: bool = False,
        add_generation_prompt: bool = False,
    ) -> str | list[int]:
        txt = render_compact_prompt_text(
            {"messages": msgs, "tools": tools or []},
            add_generation_prompt=add_generation_prompt,
        )
        if not tokenize:
            return txt
        return self(txt, add_special_tokens=False)["input_ids"]

    def __call__(
        self,
        text: str,
        add_special_tokens: bool = False,
        return_offsets_mapping: bool = False,
    ) -> dict[str, Any]:
        ids: list[int] = []
        offsets: list[tuple[int, int]] = []
        for idx, m in enumerate(self._TOK_RE.finditer(text)):
            ids.append((idx % 500) + 10)
            offsets.append((m.start(), m.end()))
        out: dict[str, Any] = {"input_ids": ids}
        if return_offsets_mapping:
            out["offset_mapping"] = offsets
        return out


@pytest.fixture(scope="module")
def solver_rollouts() -> dict[tuple[str, int], dict[str, Any]]:
    cases = (("easy", 100_000), ("medium", 100_000), ("hard", 100_001))
    out: dict[tuple[str, int], dict[str, Any]] = {}
    for tier, seed in cases:
        assert seed in TRAIN_SEEDS
        env = Env(tier, seed)
        ep = run_episode(env, SolverPolicy())
        out[(tier, seed)] = {
            "env": env,
            "ep": ep,
            "instruction": env.instruction(),
            "tools_spec": env.tools_spec(),
            "mole": env._world.mole,
            "decoy": env._world.decoy,
        }
    return out


def test_source_and_ast_hygiene() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    co_tag = "Co-" + "Authored-By"

    for path in (COMPACT_RENDER_PATH, SELF_PATH):
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(path))
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comment_tokens = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert not comment_tokens, f"comment tokens found in {path}"
        assert hash_char not in src, f"hash character found in {path}"
        assert em_dash not in src, f"em dash found in {path}"
        assert en_dash not in src, f"en dash found in {path}"
        assert co_tag not in src, f"forbidden tag found in {path}"

        if path == COMPACT_RENDER_PATH:
            for node in tree.body:
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        name = alias.name
                        root = name.split(".")[0]
                        assert root not in ("torch", "transformers", "canary")
                        for bad in FORBIDDEN_TOP_IMPORTS:
                            assert not (name == bad or name.startswith(bad + "."))
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mod = node.module
                    root = mod.split(".")[0]
                    assert root not in ("torch", "transformers", "canary")
                    for bad in FORBIDDEN_TOP_IMPORTS:
                        assert not (mod == bad or mod.startswith(bad + "."))
        else:
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert alias.name.split(".")[0] not in ("torch", "transformers")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    assert node.module.split(".")[0] not in ("torch", "transformers")

    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules


def test_parse_instruction_params_and_compact_tools() -> None:
    for tier in ("easy", "medium", "hard"):
        env = Env(tier, 100_000)
        parsed = parse_instruction_params(env.instruction())
        tp = env.p
        assert parsed["n_employees"] == tp.n_employees
        assert parsed["n_days"] == tp.n_days
        assert parsed["leak_damage"] == pytest.approx(tp.leak_damage)
        assert parsed["canary_cost"] == pytest.approx(tp.canary_cost)
        assert parsed["canaries_per_day"] == tp.canaries_per_day
        assert parsed["max_variants"] == tp.max_variants
        assert parsed["delay_choices"] == list(tp.delay_choices)
        assert parsed["fingerprint_accuracy"] == pytest.approx(tp.fingerprint_accuracy)
        assert parsed["actions_per_day"] == tp.actions_per_day
        assert parsed["restrict_cost_per_day"] == pytest.approx(tp.restrict_cost_per_day)
        assert parsed["tool_call_cap"] == tp.tool_call_cap
        assert parsed["decoy"] is tp.decoy
        assert parsed["framing"] is tp.framing
        assert parsed["careful_mole"] is tp.careful_mole
        assert parsed["access_constraints"] is tp.access_constraints

    raw_spec = Env("hard", 100_001).tools_spec()
    full_openai = to_openai_tools(raw_spec)
    compact = compact_tools_spec(raw_spec)
    assert [t["function"]["name"] for t in compact] == [t["function"]["name"] for t in full_openai]
    assert len(json.dumps(compact)) < len(json.dumps(full_openai))
    interview_fn = next(t["function"] for t in compact if t["function"]["name"] == "interview")
    assert set(interview_fn["parameters"]["required"]) == {"employee", "topic"}
    assert "recent_documents" in interview_fn["parameters"]["properties"]["topic"]["enum"]


def test_extract_public_ledger_on_solver_rollouts(
    solver_rollouts: dict[tuple[str, int], dict[str, Any]],
) -> None:
    expected_staff = {"easy": 12, "medium": 20, "hard": 40}

    for (tier, seed), bundle in solver_rollouts.items():
        ep = bundle["ep"]
        instruction = bundle["instruction"]
        mole = bundle["mole"]
        decoy = bundle["decoy"]
        ledger = extract_public_ledger(instruction, ep.steps)

        for req_key in REQUIRED_PARAM_KEYS:
            assert req_key in ledger

        assert len(ledger["employees"]) == expected_staff[tier]
        if tier == "hard":
            assert all(e["clearance"] in (1, 2, 3) for e in ledger["employees"])

        assert len(ledger["canaries"]) >= 3
        for c in ledger["canaries"]:
            assert c["canary_id"].startswith("c")
            assert 1 <= c["day"] <= ledger["n_days"]
            assert 1 <= len(c["variants"]) <= ledger["max_variants"]
            assigned = [emp for emps in c["variants"].values() for emp in emps]
            assert len(assigned) == len(set(assigned)) > 0

        assert len(ledger["leaks"]) >= 2
        canary_ids = {c["canary_id"] for c in ledger["canaries"]}
        canary_leaks = [lk for lk in ledger["leaks"] if lk["doc_id"] in canary_ids]
        assert len(canary_leaks) >= 1
        for lk in canary_leaks:
            assert lk["variant"] is not None
            assert len(lk["candidate_emps"]) >= 1

        counts = ledger["consistency_counts"]
        total_ah = sum(c["after_hours_logs"] for c in counts.values())
        total_logs = sum(c["total_logs"] for c in counts.values())
        assert total_ah > 0
        assert total_logs >= total_ah

        if decoy is not None:
            assert counts[decoy]["angry_msgs"] > 0
            assert counts[mole]["angry_msgs"] == 0
        else:
            assert all(c["angry_msgs"] == 0 for c in counts.values())

        assert ledger["breakeven_p"] == round(1.0 / (1.0 + ledger["known_v"]), 4)
        mid_idx = len(ep.steps) // 2
        mid_ledger = extract_public_ledger(instruction, ep.steps[:mid_idx])
        assert mid_ledger["breakeven_p"] == round(1.0 / (1.0 + mid_ledger["known_v"]), 4)

        assert counts[mole]["canary_misses"] == 0
        assert mole in ledger["consistent_suspects"]

    env_aux = Env("medium", 100_002)
    env_aux.call("list_employees", {})
    env_aux.call("restrict_access", {"employee": "e01"})
    env_aux.call("status", {})
    led_r = extract_public_ledger(env_aux.instruction(), env_aux.history)
    assert led_r["consistency_counts"]["e01"]["restricted"] is True
    env_aux.call("unrestrict_access", {"employee": "e01"})
    led_u = extract_public_ledger(env_aux.instruction(), env_aux.history)
    assert led_u["consistency_counts"]["e01"]["restricted"] is False


def test_bounded_prompts_across_21_day_hard_and_turn_window(
    solver_rollouts: dict[tuple[str, int], dict[str, Any]],
) -> None:
    hard_seed = 100_005
    assert hard_seed in TRAIN_SEEDS
    env = Env("hard", hard_seed)
    env.call("list_employees", {})
    emps = [f"e{i:02d}" for i in range(40)]

    for day in range(1, 22):
        off1 = (day * 2) % 22
        sub1 = emps[off1 : off1 + 18]
        asg1 = {e: ("A" if i < 6 else ("B" if i < 12 else "C")) for i, e in enumerate(sub1)}
        env.call("plant_canary", {"doc_title": f"Audit {day}A", "assignment": asg1})
        if day % 2 == 0:
            off2 = (day * 5) % 25
            sub2 = emps[off2 : off2 + 15]
            asg2 = {e: ("X" if i < 5 else ("Y" if i < 10 else "Z")) for i, e in enumerate(sub2)}
            env.call("plant_canary", {"doc_title": f"Audit {day}B", "assignment": asg2})
        if day % 3 == 0:
            env.call("check_leak_feed", {})
            env.call("read_access_logs", {"day_from": max(1, day - 2), "day_to": day - 1})
        if day in (4, 14):
            env.call("search_messages", {"query": "joke", "day_from": 1, "day_to": day})
        env.call("advance_day", {})

    ep_21d = env.result("horizon_21d")
    assert ep_21d.final_day == 21
    assert ep_21d.end_reason == "horizon"

    turns_21d = render_compact_episode_turns(ep_21d, env.instruction(), env.tools_spec())
    assert len(turns_21d) == len(ep_21d.steps)
    for turn in turns_21d:
        txt_full = render_compact_prompt_text(turn, add_generation_prompt=False)
        assert len(txt_full) < 7500
        assert estimate_compact_tokens(txt_full) < 1800
        prompt_only = {"tools": turn["tools"], "messages": turn["messages"][:-1]}
        txt_gen = render_compact_prompt_text(prompt_only, add_generation_prompt=True)
        assert len(txt_gen) < 7500
        assert estimate_compact_tokens(txt_gen) < 1800

    hard_bundle = solver_rollouts[("hard", 100_001)]
    solver_turns = render_compact_episode_turns(
        hard_bundle["ep"],
        hard_bundle["instruction"],
        hard_bundle["tools_spec"],
    )
    for turn in solver_turns:
        txt = render_compact_prompt_text(turn, add_generation_prompt=False)
        assert len(txt) < 7500
        assert estimate_compact_tokens(txt) < 1800

    step_msgs = render_compact_step_prompt(env.instruction(), ep_21d.steps, tail_turns=3)
    assert step_msgs == render_compact_messages(env.instruction(), ep_21d.steps, tail_turns=3)
    assert step_msgs[0]["role"] == "system"
    assert step_msgs[1]["role"] == "user"
    assert step_msgs[1]["content"].startswith(KICKOFF)
    assert "CANARIES(" in compact_user_text(extract_public_ledger(env.instruction(), ep_21d.steps))
    assert "Decision rule:" in compact_system_text(env.instruction())

    tok = _PureMockTokenizer()
    non_acc_win = compact_turn_window(solver_turns[0], tok, max_len=2048)
    acc_win = compact_turn_window(solver_turns[-1], tok, max_len=2048)
    assert len(non_acc_win) == 1
    assert len(acc_win) == 1
    ids0, labels0, mask0 = non_acc_win[0]
    ids1, labels1, mask1 = acc_win[0]
    assert len(ids0) == len(labels0) == len(mask0)
    assert labels0[0] == -100 and any(x != -100 for x in labels0)
    assert not any(mask0)
    assert sum(1 for m in mask1 if m) == sum(1 for x in labels1 if x != -100) > 0


def test_compact_hf_policy_executes_valid_calls_and_falls_back_on_malformed() -> None:
    seed = 100_000
    assert seed in TRAIN_SEEDS
    env = Env("easy", seed)

    scripted_outputs = [
        '<tool_call>\n{"name": "list_employees", "arguments": {}}\n</tool_call>',
        (
            '<tool_call>\n{"name": "plant_canary", "arguments": {"doc_title": "Q4 Plan", '
            '"assignment": {"e00": "A", "e01": "A", "e02": "A", "e03": "A", '
            '"e04": "B", "e05": "B", "e06": "B", "e07": "B", '
            '"e08": "C", "e09": "C", "e10": "C", "e11": "C"}}}\n</tool_call>'
        ),
        '<tool_call>\n{"name": "advance_day", "arguments": {}}\n</tool_call>',
        '<tool_call>\n{"name": "check_leak_feed", "arguments": {}}\n</tool_call>',
    ]
    state = {"idx": 0}

    def valid_gen(turn: dict[str, Any]) -> str:
        assert "messages" in turn and "tools" in turn
        idx = state["idx"]
        state["idx"] += 1
        if idx < len(scripted_outputs):
            return scripted_outputs[idx]
        user_txt = turn["messages"][1]["content"]
        m = re.search(r"CONSISTENT_SUSPECTS\(\d+\): \[([a-z0-9_]+)", user_txt)
        suspect = m.group(1) if m else "e00"
        return json.dumps({"name": "accuse", "arguments": {"employee": suspect}})

    policy = CompactHFPolicy(generator=valid_gen, name="compact_gen_test")
    ep = run_episode(env, policy)
    assert ep.end_reason == "accused"
    assert ep.accused is not None
    assert policy.calls == len(ep.steps) == 5
    assert policy.invalid == 0

    env_bad = Env("easy", seed)
    malformed_queue = [
        "not json at all",
        '{"name": "status", "arguments": "{unclosed"}',
        '<tool_call>{"name": "nonexistent_tool", "arguments": {}}</tool_call>',
        '{"name": "list_employees", "arguments": {}}',
    ]
    b_idx = {"i": 0}

    def mixed_gen(_turn: dict[str, Any]) -> str:
        out = malformed_queue[b_idx["i"]]
        b_idx["i"] += 1
        return out

    bad_policy = CompactHFPolicy(generator=mixed_gen)
    bad_policy.reset(env_bad.tools_spec(), env_bad.instruction())

    for expected_invalid in (1, 2, 3):
        tool, args = bad_policy.act(list(env_bad.history))
        assert (tool, args) == ("status", {})
        assert bad_policy.invalid == expected_invalid
        res = env_bad.call(tool, args)
        assert res.ok is True

    tool4, args4 = bad_policy.act(list(env_bad.history))
    assert (tool4, args4) == ("list_employees", {})
    assert bad_policy.invalid == 3
    assert bad_policy.calls == 4

    sample_turn = render_compact_turn(
        env_bad.instruction(),
        env_bad.tools_spec(),
        list(env_bad.history),
        target_step=None,
    )
    assert sample_turn["messages"][0]["role"] == "system"
