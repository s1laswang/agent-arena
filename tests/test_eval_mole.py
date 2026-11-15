from __future__ import annotations

from contextlib import nullcontext
import json
import math
import statistics
import sys
import types

import pytest

from canary import rules
from canary.forge import rl_mole, rl_mole_v2
import train.eval_mole as em
import train.grpo_mole as gm
import train.qwen_diverse_mole as qdm


class _FakeTensor2D:
    def __init__(self, rows: list[list[int]]):
        self.rows = [list(r) for r in rows]

    @property
    def shape(self) -> tuple[int, int]:
        if not self.rows:
            return (0, 0)
        return (len(self.rows), len(self.rows[0]))

    def __getitem__(self, item):
        if isinstance(item, tuple) and len(item) == 2:
            row_sel, col_sel = item
            selected_rows = self.rows[row_sel]
            if isinstance(selected_rows[0], int):
                selected_rows = [selected_rows]
            return _FakeTensor2D([r[col_sel] for r in selected_rows])
        return self.rows[item]

    def __iter__(self):
        return iter(self.rows)


class _FakeBatch(dict):
    def __init__(self, data: dict):
        super().__init__(data)
        self.moved_to: str | None = None

    def to(self, device: str):
        self.moved_to = device
        return self


class _FakeTokenizer:
    SPECIAL = {
        1001: '{"leak": "none", "frame": "none"}',
        1002: "malformed non json output",
        1003: '{"leak": "most_recipients", "frame": "decoy"}',
        1004: '{"leak": "newest", "frame": "random_peer"}',
    }

    def __init__(self):
        self.padding_side = "right"
        self.pad_token = None
        self.eos_token = "<eos>"
        self.pad_token_id = 0
        self.eos_token_id = 2
        self.chat_calls: list[list[dict]] = []
        self.encode_batches: list[list[str]] = []

    def apply_chat_template(self, messages: list[dict], tokenize: bool = False, add_generation_prompt: bool = True) -> str:
        _ = (tokenize, add_generation_prompt)
        self.chat_calls.append(messages)
        return " || ".join(f"{m['role']}:{m['content']}" for m in messages)

    def __call__(self, texts: list[str], return_tensors: str = "pt", padding: bool = True) -> _FakeBatch:
        assert return_tensors == "pt"
        assert padding is True
        self.encode_batches.append(list(texts))
        seqs = [[10 + (idx % 7) for idx in range(max(2, len(t.split())))] for t in texts]
        max_len = max(len(s) for s in seqs)
        padded = []
        masks = []
        for s in seqs:
            pad_n = max_len - len(s)
            if self.padding_side == "left":
                padded.append([self.pad_token_id] * pad_n + s)
                masks.append([0] * pad_n + [1] * len(s))
            else:
                padded.append(s + [self.pad_token_id] * pad_n)
                masks.append([1] * len(s) + [0] * pad_n)
        return _FakeBatch({"input_ids": _FakeTensor2D(padded), "attention_mask": _FakeTensor2D(masks)})

    def batch_decode(self, token_rows: _FakeTensor2D, skip_special_tokens: bool = True) -> list[str]:
        decoded = []
        for row in token_rows:
            pieces = []
            for tok_id in row:
                if skip_special_tokens and tok_id in (self.pad_token_id, self.eos_token_id):
                    continue
                if tok_id in self.SPECIAL:
                    pieces.append(self.SPECIAL[tok_id])
                else:
                    pieces.append(f"tok{tok_id}")
            decoded.append("".join(pieces))
        return decoded


class _FakeModel:
    def __init__(self, reply_tokens: list[int], name: str = "base"):
        self.reply_tokens = list(reply_tokens)
        self.name = name
        self.device = "cpu"
        self.in_eval = False
        self.seen_calls: list[dict] = []
        self._cursor = 0

    def to(self, device: str):
        self.device = device
        return self

    def eval(self):
        self.in_eval = True
        return self

    def generate(self, **kwargs) -> _FakeTensor2D:
        self.seen_calls.append(kwargs)
        inp: _FakeTensor2D = kwargs["input_ids"]
        max_new = int(kwargs["max_new_tokens"])
        assert max_new >= 1
        assert kwargs["do_sample"] is False
        out_rows = []
        for row in inp:
            tok_id = self.reply_tokens[self._cursor % len(self.reply_tokens)]
            self._cursor += 1
            out_rows.append(list(row) + [tok_id, 2][:max_new])
        return _FakeTensor2D(out_rows)


def _install_fake_ml_stack(monkeypatch, base_tokens: list[int], adapter_tokens: list[int]) -> dict:
    recorded: dict = {}

    fake_torch = types.ModuleType("torch")
    fake_torch.float16 = "fake_fp16"
    fake_torch.bfloat16 = "fake_bf16"
    fake_torch.no_grad = nullcontext

    fake_transformers = types.ModuleType("transformers")

    class AutoTokenizer:
        @staticmethod
        def from_pretrained(model_name: str):
            recorded["tok_model"] = model_name
            tok = _FakeTokenizer()
            recorded["tok"] = tok
            return tok

    class AutoModelForCausalLM:
        @staticmethod
        def from_pretrained(model_name: str, dtype=None):
            recorded["base_model_name"] = model_name
            recorded["dtype"] = dtype
            m = _FakeModel(base_tokens, name="base")
            recorded["base_model"] = m
            return m

    fake_transformers.AutoTokenizer = AutoTokenizer
    fake_transformers.AutoModelForCausalLM = AutoModelForCausalLM

    fake_peft = types.ModuleType("peft")

    class PeftModel:
        @staticmethod
        def from_pretrained(base_model, adapter_path: str):
            recorded["peft_base"] = base_model
            recorded["adapter_path"] = adapter_path
            m = _FakeModel(adapter_tokens, name="adapter")
            m.device = base_model.device
            recorded["adapter_model"] = m
            return m

    fake_peft.PeftModel = PeftModel

    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    monkeypatch.setitem(sys.modules, "peft", fake_peft)
    return recorded


def test_mean_ci_empty_singleton_constant_and_general():
    empty = em.mean_ci([])
    assert empty["n"] == 0
    assert math.isnan(empty["mean"])
    assert math.isnan(empty["ci95"][0]) and math.isnan(empty["ci95"][1])

    single = em.mean_ci([0.375])
    assert single["n"] == 1
    assert single["mean"] == pytest.approx(0.375)
    assert math.isnan(single["ci95"][0]) and math.isnan(single["ci95"][1])

    const = em.mean_ci([0.25, 0.25, 0.25, 0.25])
    assert const["n"] == 4
    assert const["mean"] == pytest.approx(0.25)
    assert const["ci95"] == [pytest.approx(0.25), pytest.approx(0.25)]

    xs = [0.10, 0.30, 0.50, 0.70, 0.90]
    got = em.mean_ci(xs)
    exp_mean = statistics.fmean(xs)
    exp_half = 1.96 * statistics.stdev(xs) / math.sqrt(len(xs))
    assert got["n"] == 5
    assert got["mean"] == pytest.approx(exp_mean)
    assert got["ci95"][0] == pytest.approx(exp_mean - exp_half)
    assert got["ci95"][1] == pytest.approx(exp_mean + exp_half)
    assert got["ci95"][0] < got["mean"] < got["ci95"][1]


def test_summarize_mixed_valid_invalid_and_all_invalid():
    rows = [
        {
            "reward": 0.35,
            "valid": True,
            "solver": (0.75, True),
            "inv": {
                "grok_tactics": (0.40, True),
                "heuristic": (0.10, False),
                "hinted_heuristic": (0.25, True),
            },
        },
        {
            "reward": -0.70,
            "valid": True,
            "solver": (0.00, False),
            "inv": {
                "grok_tactics": (0.20, True),
                "heuristic": (-0.10, False),
                "hinted_heuristic": (0.05, False),
            },
        },
        {
            "reward": -1.0,
            "valid": False,
        },
    ]
    s = em.summarize(rows)
    assert s["reward"]["n"] == 3
    assert s["reward"]["mean"] == pytest.approx((0.35 - 0.70 - 1.0) / 3.0)
    assert s["valid"]["n"] == 3
    assert s["valid"]["mean"] == pytest.approx(2.0 / 3.0)
    assert s["solver_catch"]["n"] == 3
    assert s["solver_catch"]["mean"] == pytest.approx(1.0 / 3.0)
    assert s["regret"]["n"] == 2
    assert s["regret"]["mean"] == pytest.approx(((0.75 - 0.40) + (0.00 - 0.20)) / 2.0)

    all_bad = em.summarize([{"reward": -1.0, "valid": False}, {"reward": -1.0, "valid": False}])
    assert all_bad["valid"]["mean"] == pytest.approx(0.0)
    assert all_bad["solver_catch"]["mean"] == pytest.approx(0.0)
    assert all_bad["regret"]["n"] == 0
    assert math.isnan(all_bad["regret"]["mean"])


def test_heldout_seed_base_disjoint_from_all_train_val_eval_and_judge_ranges(monkeypatch):
    assert em.HELDOUT_SEED_BASE == 400_000
    eval_mole_window = range(em.HELDOUT_SEED_BASE, em.HELDOUT_SEED_BASE + 50_000)

    other_ranges = {
        "dev_seeds": rules.DEV_SEEDS,
        "rules_train_seeds": rules.TRAIN_SEEDS,
        "rl_mole_train": range(rl_mole.TRAIN_SEED_BASE, rl_mole.TRAIN_SEED_BASE + 100_000),
        "rl_mole_eval_ws3": range(rl_mole.EVAL_SEED_BASE, rl_mole.EVAL_SEED_BASE + 100_000),
        "rl_mole_v2_train": rl_mole_v2.TRAIN_SEEDS,
        "rl_mole_v2_val": rl_mole_v2.VAL_SEEDS,
        "qwen_diverse_val": range(qdm.VAL_SEED_BASE, 200_000),
        "grpo_mole_prompts": range(gm.PROMPT_SEED_BASE, gm.PROMPT_SEED_BASE + 100_000),
        "rules_heldout": rules.HELDOUT_SEEDS,
        "judge_seeds": rules.JUDGE_SEEDS,
    }
    lo_em, hi_em = eval_mole_window.start, eval_mole_window.stop
    for label, rng in other_ranges.items():
        overlaps = max(lo_em, rng.start) < min(hi_em, rng.stop)
        assert not overlaps, f"HELDOUT_SEED_BASE window overlaps {label}: {rng}"

    monkeypatch.setattr(gm, "PROMPT_SEED_BASE", em.HELDOUT_SEED_BASE)
    collected = gm.collect_prompts(3, tier="easy", seed=12345)
    assert len(collected) == 3
    for row in collected:
        s = row["seed"]
        assert em.HELDOUT_SEED_BASE <= s < em.HELDOUT_SEED_BASE + 100
        for rng in other_ranges.values():
            assert s not in rng


def test_generate_batches_left_pads_and_slices_prompt(monkeypatch):
    _install_fake_ml_stack(monkeypatch, [1003], [1004])
    tok = _FakeTokenizer()
    model = _FakeModel([1003, 1004, 1001], name="gen_test").to("cuda")
    rows = [
        {"prompt": "short prompt"},
        {"prompt": "a much longer mole view prompt with extra words"},
        {"prompt": "third state"},
        {"prompt": "fourth state with several tokens"},
        {"prompt": "fifth"},
    ]
    outs = em.generate(model, tok, rows, max_new=16, batch=2)
    assert tok.padding_side == "left"
    assert tok.pad_token == "<eos>"
    assert len(model.seen_calls) == 3
    assert [c["input_ids"].shape[0] for c in model.seen_calls] == [2, 2, 1]
    assert outs == [
        '{"leak": "most_recipients", "frame": "decoy"}',
        '{"leak": "newest", "frame": "random_peer"}',
        '{"leak": "none", "frame": "none"}',
        '{"leak": "most_recipients", "frame": "decoy"}',
        '{"leak": "newest", "frame": "random_peer"}',
    ]


def test_main_end_to_end_writes_eval_json_without_cuda_or_weights(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(gm, "PROMPT_SEED_BASE", gm.PROMPT_SEED_BASE)
    recorded = _install_fake_ml_stack(
        monkeypatch,
        base_tokens=[1002, 1001, 1002],
        adapter_tokens=[1003, 1004, 1003],
    )
    out_file = tmp_path / "eval.json"
    em.main(
        [
            "--model",
            "Qwen/Qwen2.5-1.5B-Instruct",
            "--adapter",
            "mock-lora-step200",
            "--n",
            "3",
            "--tier",
            "easy",
            "--max-new",
            "16",
            "--batch",
            "2",
            "--workers",
            "1",
            "--fp16",
            "--out",
            str(out_file),
        ]
    )
    stdout = capsys.readouterr().out
    assert "base" in stdout and "adapter_result" in stdout and "paired diff" in stdout
    assert recorded["dtype"] == "fake_fp16"
    assert recorded["base_model"].device == "cuda"
    assert recorded["base_model"].in_eval is True
    assert recorded["adapter_model"].in_eval is True
    assert recorded["adapter_path"] == "mock-lora-step200"

    assert out_file.is_file()
    payload = json.loads(out_file.read_text(encoding="utf-8"))
    assert payload["model"] == "Qwen/Qwen2.5-1.5B-Instruct"
    assert payload["adapter"] == "mock-lora-step200"
    assert payload["tier"] == "easy"
    assert payload["n"] == 3
    assert payload["heldout_seed_base"] == 400_000
    assert len(payload["seeds"]) == 2
    assert payload["seeds"][0] >= 400_000
    assert payload["seeds"][1] >= payload["seeds"][0]
    assert payload["base"]["valid"]["mean"] == pytest.approx(1.0 / 3.0)
    assert payload["adapter_result"]["valid"]["mean"] == pytest.approx(1.0)
    assert payload["reward_diff_adapter_minus_base"]["n"] == 3
    assert payload["reward_diff_adapter_minus_base"]["mean"] > 0.0
    assert payload["actions_adapter"] == [
        ["most_recipients", "decoy"],
        ["newest", "random_peer"],
        ["most_recipients", "decoy"],
    ]

    out_bf16 = tmp_path / "eval_bf16.json"
    recorded_bf16 = _install_fake_ml_stack(monkeypatch, base_tokens=[1001], adapter_tokens=[1003])
    em.main(
        [
            "--model",
            "Qwen/Qwen2.5-0.5B-Instruct",
            "--adapter",
            "mock-lora-step50",
            "--n",
            "2",
            "--tier",
            "easy",
            "--workers",
            "1",
            "--out",
            str(out_bf16),
        ]
    )
    assert recorded_bf16["dtype"] == "fake_bf16"
    assert out_bf16.is_file()
