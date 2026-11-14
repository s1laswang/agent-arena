"""Prefix-reuse bookkeeping of HFPolicy, without torch: a char-level fake tokenizer + template."""
from canary.types import Step

from train.eval_hf import HFPolicy, common_prefix, run_capped
from train.fake import FakeEnv, FakeSolver


class FakeTok:
    def apply_chat_template(self, msgs, tools=None, tokenize=True, add_generation_prompt=False):
        s = "".join(f"<{m['role']}>{m.get('content') or m.get('tool_calls')}</>" for m in msgs)
        s += "<assistant>" if add_generation_prompt else ""
        return [ord(c) for c in s] if tokenize else s


def steps(n):
    return [Step(i, 1, "read_access_logs", {"day_from": i},
                 {"ok": True, "data": {"rows": "r" * 40}, "error": None}) for i in range(n)]


def test_common_prefix():
    assert common_prefix([1, 2, 3], [1, 2, 4, 5]) == 2 and common_prefix([], [1]) == 0


def test_incremental_ids_equal_full_render_and_prefix_reused():
    p = HFPolicy(None, FakeTok(), "x", max_ctx=10**6, max_new=96)
    p.reset([{"name": "status", "input_schema": {}}], "rules")
    prev = None
    for k in range(1, 15):
        ids = p._prompt_ids(steps(k))
        assert ids == p._ids(p_full := __import__("train.render", fromlist=["x"]).render_messages("rules", steps(k)))
        if prev is not None:
            # everything the cache covered last turn (prompt) is a prefix of the new prompt
            assert common_prefix(prev, ids) == len(prev)
        prev = ids


def test_truncation_is_sticky_so_prefix_survives_between_drops():
    p = HFPolicy(None, FakeTok(), "x", max_ctx=1500 + 96, max_new=96)
    p.reset([], "rules")
    prev, drops, reuse_ok = None, [], 0
    for k in range(1, 40):
        ids = p._prompt_ids(steps(k))
        assert len(ids) <= 1500
        if prev is not None and p.drop == drops[-1]:
            assert common_prefix(prev, ids) == len(prev)
            reuse_ok += 1
        drops.append(p.drop)
        prev = ids
    assert drops[-1] > 0 and reuse_ok > 20


def test_eval_cap_marks_end_reason():
    class Staller(FakeSolver):
        def act(self, history):
            return "status", {}
    ep = run_capped(FakeEnv("easy", 1), Staller(), 7)
    assert ep.end_reason == "eval_cap" and len(ep.steps) == 7 and ep.score == 0
    ep2 = run_capped(FakeEnv("easy", 1), FakeSolver(), 7)
    assert ep2.end_reason == "accused"
