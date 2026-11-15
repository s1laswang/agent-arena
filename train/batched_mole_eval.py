from __future__ import annotations

import argparse
from collections import Counter, deque
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import contextmanager
import importlib.util
import inspect
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import random
import tempfile
import threading
import time
from types import SimpleNamespace
from typing import Any, Callable, Sequence

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import numpy as np

from canary import rules, world as canary_world
from canary.env import Env
from canary.eval import run_episode
from canary.forge.rl_mole import EVAL_SEED_BASE, INVESTIGATORS, RLMole, _agent
from canary.forge.rl_mole_v2 import RLMoleV2
from canary.mole.dsl import (
    DEFAULT_STRATEGY,
    FRAME_SELECTORS,
    LEAK_SELECTORS,
    MoleView,
    _select_frame,
    _select_leak,
)
from train.grpo_mole import SYSTEM, parse_action, render_view
from train.qwen_diverse_mole import TinyByteTokenizer, apply_chat, resolve_model_path

ALL_AGENTS: tuple[str, ...] = ("solver",) + tuple(INVESTIGATORS)
CANONICAL_ACTIONS: tuple[tuple[str, str], ...] = tuple(
    (leak_sel, frame_sel)
    for leak_sel in LEAK_SELECTORS
    for frame_sel in FRAME_SELECTORS
)
CANONICAL_CANDIDATES: tuple[str, ...] = tuple(
    json.dumps({"leak": leak_sel, "frame": frame_sel})
    for leak_sel, frame_sel in CANONICAL_ACTIONS
)

DEFAULT_RL_MOLE_PATH = "data/rl_mole/policy_final.json"
DEFAULT_RL_MOLE_V2_PATH = "results/moletrain/rl_mole_v2_policy.json"

FALLBACK_LORA_KEYS = {
    "r",
    "lora_alpha",
    "lora_dropout",
    "target_modules",
    "bias",
    "fan_in_fan_out",
    "modules_to_save",
    "layers_to_transform",
    "layers_pattern",
    "rank_pattern",
    "alpha_pattern",
    "use_rslora",
    "use_dora",
    "init_lora_weights",
    "loftq_config",
    "peft_type",
    "base_model_name_or_path",
    "auto_mapping",
    "task_type",
    "inference_mode",
}


def sanitize_peft_config_dict(cfg: dict) -> dict:
    try:
        from peft import LoraConfig

        allowed = set(inspect.signature(LoraConfig.__init__).parameters.keys()) - {"self", "kwargs"}
        allowed.update({"peft_type", "base_model_name_or_path", "auto_mapping", "task_type", "inference_mode"})
    except ImportError:
        allowed = set(FALLBACK_LORA_KEYS)
    return {k: v for k, v in cfg.items() if k in allowed}


def guard_eval_seeds(seeds: Sequence[int]) -> list[int]:
    out = [int(s) for s in seeds]
    if not out:
        raise ValueError("seeds must be non-empty")
    judge = set(rules.JUDGE_SEEDS)
    for s in out:
        if s < 0 or s in judge:
            raise ValueError(f"Refusing to evaluate on JUDGE_SEEDS or negative seed: {s}")
    return out


def parse_seeds(spec: str, n: int = 60) -> list[int]:
    raw = str(spec).strip()
    if raw == "heldout":
        seeds = list(rules.HELDOUT_SEEDS)[: max(0, int(n))]
    elif raw == "ws3":
        seeds = list(range(EVAL_SEED_BASE, EVAL_SEED_BASE + max(0, int(n))))
    elif raw == "dev":
        seeds = list(rules.DEV_SEEDS)[: max(0, int(n))]
    elif raw == "judge":
        seeds = list(rules.JUDGE_SEEDS)[: max(1, int(n))]
    elif "," in raw:
        seeds = []
        for part in raw.split(","):
            p = part.strip()
            if not p:
                continue
            if "-" in p:
                lo_s, hi_s = p.split("-", 1)
                lo, hi = int(lo_s), int(hi_s)
                if hi < lo:
                    raise ValueError(f"empty seed range: {p}")
                seeds.extend(range(lo, hi + 1))
            else:
                seeds.append(int(p))
        if n > 0:
            seeds = seeds[: int(n)]
    elif "-" in raw:
        lo_s, hi_s = raw.split("-", 1)
        lo, hi = int(lo_s), int(hi_s)
        if hi < lo:
            raise ValueError(f"empty seed range: {raw}")
        full = list(range(lo, hi + 1))
        seeds = full[: int(n)] if n > 0 else full
    else:
        start = int(raw)
        seeds = list(range(start, start + max(0, int(n))))
    return guard_eval_seeds(seeds)


def shannon_entropy_nats(probs: Sequence[float]) -> float:
    return float(-sum(float(p) * math.log(float(p)) for p in probs if float(p) > 0.0))


def should_mask_none_leak(view: MoleView, trap_only_none: bool) -> bool:
    if not trap_only_none:
        return False
    max_rec = int(view.feature("max_recipient_count"))
    return bool(view.can_leak) and (not bool(view.i_am_restricted)) and (max_rec >= 9)


def compute_constrained_probs(
    raw_logprobs: Sequence[float],
    mask_none: bool = False,
    temperature: float = 1.0,
) -> list[float]:
    if len(raw_logprobs) != len(CANONICAL_ACTIONS):
        raise ValueError(f"expected {len(CANONICAL_ACTIONS)} candidate logprobs, got {len(raw_logprobs)}")
    temp = max(1e-6, float(temperature))
    allowed = [
        i
        for i, (leak_sel, _) in enumerate(CANONICAL_ACTIONS)
        if not (mask_none and leak_sel == "none")
    ]
    if not allowed:
        allowed = list(range(len(CANONICAL_ACTIONS)))
    scaled = {i: float(raw_logprobs[i]) / temp for i in allowed}
    m = max(scaled.values())
    exps = {i: math.exp(scaled[i] - m) for i in allowed}
    z = sum(exps.values())
    if z <= 0.0 or not math.isfinite(z):
        uniform = 1.0 / float(len(allowed))
        return [uniform if i in exps else 0.0 for i in range(len(CANONICAL_ACTIONS))]
    return [exps[i] / z if i in exps else 0.0 for i in range(len(CANONICAL_ACTIONS))]


def compute_mutual_information_from_probs(prob_rows: Sequence[Sequence[float]]) -> dict[str, Any]:
    m = len(prob_rows)
    if m == 0:
        return {
            "n_states": 0,
            "mi_nats": 0.0,
            "mi_bits": 0.0,
            "h_marginal_nats": 0.0,
            "h_conditional_nats": 0.0,
            "leak_mi_nats": 0.0,
            "frame_mi_nats": 0.0,
            "mean_action_probs": {f"{l}/{f}": 0.0 for l, f in CANONICAL_ACTIONS},
            "mean_candidate_probs": {c: 0.0 for c in CANONICAL_CANDIDATES},
        }
    mat = np.asarray(prob_rows, dtype=np.float64)
    if mat.ndim != 2 or mat.shape[1] != len(CANONICAL_ACTIONS):
        raise ValueError(f"expected (N, {len(CANONICAL_ACTIONS)}) probability matrix, got {mat.shape}")
    pbar = np.mean(mat, axis=0)
    h_marg = shannon_entropy_nats(pbar.tolist())
    h_cond = sum(shannon_entropy_nats(row.tolist()) for row in mat) / float(m)
    mi_nats = max(0.0, h_marg - h_cond)
    mi_bits = mi_nats / math.log(2.0)

    grid = mat.reshape(m, len(LEAK_SELECTORS), len(FRAME_SELECTORS))
    leak_mat = grid.sum(axis=2)
    frame_mat = grid.sum(axis=1)
    leak_pbar = np.mean(leak_mat, axis=0)
    frame_pbar = np.mean(frame_mat, axis=0)
    leak_mi = max(
        0.0,
        shannon_entropy_nats(leak_pbar.tolist())
        - sum(shannon_entropy_nats(r.tolist()) for r in leak_mat) / float(m),
    )
    frame_mi = max(
        0.0,
        shannon_entropy_nats(frame_pbar.tolist())
        - sum(shannon_entropy_nats(r.tolist()) for r in frame_mat) / float(m),
    )
    return {
        "n_states": m,
        "mi_nats": round(mi_nats, 6),
        "mi_bits": round(mi_bits, 6),
        "h_marginal_nats": round(h_marg, 6),
        "h_conditional_nats": round(h_cond, 6),
        "leak_mi_nats": round(leak_mi, 6),
        "frame_mi_nats": round(frame_mi, 6),
        "mean_action_probs": {
            f"{l}/{f}": round(float(pbar[i]), 6)
            for i, (l, f) in enumerate(CANONICAL_ACTIONS)
        },
        "mean_candidate_probs": {
            CANONICAL_CANDIDATES[i]: round(float(pbar[i]), 6)
            for i in range(len(CANONICAL_ACTIONS))
        },
    }


class TinyNumpyCausalLM:
    def __init__(self, vocab_size: int = 512, hidden_size: int = 32, seed: int = 0):
        self.vocab_size = int(vocab_size)
        self.hidden_size = int(hidden_size)
        self.device = "cpu"
        self.config = SimpleNamespace(
            vocab_size=self.vocab_size,
            hidden_size=self.hidden_size,
            intermediate_size=self.hidden_size * 2,
            num_hidden_layers=1,
            num_attention_heads=2,
            num_key_value_heads=1,
            max_position_embeddings=1024,
            use_cache=True,
            model_type="qwen2_tiny_numpy",
        )
        rng = np.random.default_rng(seed)
        scale = 1.0 / math.sqrt(float(self.hidden_size))
        self.emb = rng.normal(0.0, 0.35, (self.vocab_size, self.hidden_size)).astype(np.float32)
        self.w_mix = rng.normal(0.0, scale, (self.hidden_size, self.hidden_size)).astype(np.float32)
        self.w_head = rng.normal(0.0, scale, (self.hidden_size, self.vocab_size)).astype(np.float32)
        self.b_head = np.zeros(self.vocab_size, dtype=np.float32)

    def eval(self) -> "TinyNumpyCausalLM":
        return self

    def to(self, device: str) -> "TinyNumpyCausalLM":
        self.device = str(device)
        return self

    def _causal_hidden(self, input_ids: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
        ids = np.clip(np.asarray(input_ids, dtype=np.int64), 0, self.vocab_size - 1)
        mask = np.asarray(attention_mask, dtype=np.float32)
        tok_e = self.emb[ids] * mask[:, :, None]
        pos = np.cumsum(mask, axis=1)
        feat = np.tanh(tok_e + 0.15 * np.sin(pos[:, :, None] * 0.25)) * mask[:, :, None]
        ctx = np.cumsum(feat, axis=1) / np.maximum(1.0, pos[:, :, None])
        return np.tanh(tok_e + (ctx @ self.w_mix))

    def forward_logits(self, input_ids: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
        h = self._causal_hidden(input_ids, attention_mask)
        return h @ self.w_head + self.b_head

    def generate_greedy(
        self,
        input_ids: np.ndarray,
        attention_mask: np.ndarray,
        max_new_tokens: int,
        eos_token_id: int = 2,
    ) -> np.ndarray:
        cur_ids = np.asarray(input_ids, dtype=np.int64)
        cur_att = np.asarray(attention_mask, dtype=np.float32)
        bsz = cur_ids.shape[0]
        ids_clipped = np.clip(cur_ids, 0, self.vocab_size - 1)
        tok_e = self.emb[ids_clipped] * cur_att[:, :, None]
        pos = np.cumsum(cur_att, axis=1)
        feat = np.tanh(tok_e + 0.15 * np.sin(pos[:, :, None] * 0.25)) * cur_att[:, :, None]
        running_sum = np.sum(feat, axis=1)
        running_pos = pos[:, -1:]
        last_tok_e = tok_e[:, -1, :]
        finished = np.zeros(bsz, dtype=bool)
        gen_cols: list[np.ndarray] = []
        n_steps = max(1, int(max_new_tokens))
        for step_i in range(n_steps):
            ctx_last = running_sum / np.maximum(1.0, running_pos)
            h_last = np.tanh(last_tok_e + (ctx_last @ self.w_mix))
            last_logits = h_last @ self.w_head + self.b_head
            next_tok = np.argmax(last_logits, axis=-1).astype(np.int64)
            next_tok = np.where(finished, int(eos_token_id), next_tok)
            finished = finished | (next_tok == int(eos_token_id))
            gen_cols.append(next_tok[:, None])
            if bool(np.all(finished)) or step_i + 1 >= n_steps:
                break
            running_pos = running_pos + 1.0
            last_tok_e = self.emb[np.clip(next_tok, 0, self.vocab_size - 1)]
            next_feat = np.tanh(last_tok_e + 0.15 * np.sin(running_pos * 0.25))
            running_sum = running_sum + next_feat
        return np.concatenate([cur_ids] + gen_cols, axis=1)

    def score_candidates(
        self,
        pairs: Sequence[tuple[int, int, list[int], list[int]]],
        pad_id: int = 0,
        length_norm: bool = False,
        chunk_size: int = 48,
    ) -> list[tuple[int, int, float]]:
        _ = chunk_size
        by_prompt: dict[int, tuple[list[int], list[tuple[int, list[int]]]]] = {}
        for p_idx, c_idx, p_ids, c_ids in pairs:
            entry = by_prompt.get(p_idx)
            if entry is None:
                by_prompt[p_idx] = (p_ids, [(c_idx, c_ids)])
            else:
                entry[1].append((c_idx, c_ids))

        results: list[tuple[int, int, float]] = []
        clamp_pad = min(max(0, int(pad_id)), self.vocab_size - 1)
        for p_idx, (p_ids, cand_list) in by_prompt.items():
            lp_len = len(p_ids)
            p_arr = np.clip(np.asarray(p_ids, dtype=np.int64), 0, self.vocab_size - 1)
            p_tok_e = self.emb[p_arr]
            p_pos = np.arange(1, lp_len + 1, dtype=np.float32)[:, None]
            p_feat = np.tanh(p_tok_e + 0.15 * np.sin(p_pos * 0.25))
            if lp_len > 1:
                prefix_before_last = np.sum(p_feat[:-1], axis=0)
            else:
                prefix_before_last = np.zeros(self.hidden_size, dtype=np.float32)

            max_lc = max(len(c_ids) for _, c_ids in cand_list)
            k_cands = len(cand_list)
            step_ids = np.full((k_cands, max_lc), clamp_pad, dtype=np.int64)
            tgt_ids = np.full((k_cands, max_lc), clamp_pad, dtype=np.int64)
            for bi, (_, c_ids) in enumerate(cand_list):
                lc_len = len(c_ids)
                step_seq = [int(p_arr[-1])] + [int(x) for x in c_ids[:-1]]
                step_ids[bi, :lc_len] = np.clip(np.asarray(step_seq, dtype=np.int64), 0, self.vocab_size - 1)
                tgt_ids[bi, :lc_len] = np.clip(np.asarray(c_ids, dtype=np.int64), 0, self.vocab_size - 1)

            s_tok_e = self.emb[step_ids]
            s_pos = float(lp_len) + np.arange(max_lc, dtype=np.float32)[None, :, None]
            s_feat = np.tanh(s_tok_e + 0.15 * np.sin(s_pos * 0.25))
            s_cum = prefix_before_last[None, None, :] + np.cumsum(s_feat, axis=1)
            s_ctx = s_cum / np.maximum(1.0, s_pos)
            s_h = np.tanh(s_tok_e + (s_ctx @ self.w_mix))
            logits = (s_h @ self.w_head + self.b_head).astype(np.float64)
            m = np.max(logits, axis=-1, keepdims=True)
            log_z = m + np.log(np.sum(np.exp(logits - m), axis=-1, keepdims=True))
            log_probs = logits - log_z
            gathered = np.take_along_axis(log_probs, tgt_ids[:, :, None], axis=-1).squeeze(-1)

            for bi, (c_idx, c_ids) in enumerate(cand_list):
                lc_len = len(c_ids)
                tok_lp = gathered[bi, :lc_len]
                score = float(np.mean(tok_lp)) if length_norm else float(np.sum(tok_lp))
                results.append((p_idx, c_idx, score))
        return results


def load_eval_model(
    model_spec: str | None = None,
    adapter_dir: str | None = None,
    tiny: bool = False,
    device: str | None = None,
):
    base_path = resolve_model_path(model_spec if not tiny else (model_spec or "tiny-synthetic"), adapter_dir)
    if tiny:
        tok = TinyByteTokenizer()
        tok.padding_side = "left"
        has_torch = (
            importlib.util.find_spec("torch") is not None
            and importlib.util.find_spec("transformers") is not None
        )
        if has_torch:
            import torch
            from transformers import Qwen2Config, Qwen2ForCausalLM

            dev = device or "cpu"
            cfg = Qwen2Config(
                vocab_size=max(len(tok), 512),
                hidden_size=32,
                intermediate_size=64,
                num_hidden_layers=1,
                num_attention_heads=2,
                num_key_value_heads=1,
                max_position_embeddings=1024,
            )
            torch.manual_seed(0)
            model = Qwen2ForCausalLM(cfg)
            if adapter_dir and Path(adapter_dir).is_dir() and importlib.util.find_spec("peft") is not None:
                from peft import PeftModel

                model = PeftModel.from_pretrained(model, str(adapter_dir)).merge_and_unload()
            model.config.use_cache = True
            model.to(dev).eval()
            return model, tok, dev, base_path
        dev = device or "cpu"
        model = TinyNumpyCausalLM(vocab_size=max(len(tok), 512), hidden_size=32, seed=0).to(dev).eval()
        return model, tok, dev, base_path

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    dev = device or ("cuda" if torch.cuda.is_available() else "cpu")
    tok_src = (
        adapter_dir
        if (adapter_dir and (Path(adapter_dir) / "tokenizer_config.json").is_file())
        else base_path
    )
    tok = AutoTokenizer.from_pretrained(tok_src)
    tok.padding_side = "left"
    if getattr(tok, "pad_token", None) is None:
        tok.pad_token = tok.eos_token

    dt = torch.float16 if str(dev).startswith("cuda") else torch.float32
    try:
        model = AutoModelForCausalLM.from_pretrained(base_path, dtype=dt)
    except TypeError:
        model = AutoModelForCausalLM.from_pretrained(base_path, torch_dtype=dt)

    if adapter_dir:
        ap = Path(adapter_dir)
        cfg_file = ap / "adapter_config.json"
        if cfg_file.is_file():
            with tempfile.TemporaryDirectory() as td:
                td_path = Path(td)
                for item in ap.iterdir():
                    if item.name == "adapter_config.json":
                        clean_cfg = sanitize_peft_config_dict(json.loads(item.read_text(encoding="utf-8")))
                        clean_cfg["base_model_name_or_path"] = base_path
                        (td_path / item.name).write_text(json.dumps(clean_cfg, indent=2), encoding="utf-8")
                    elif item.is_file():
                        os.symlink(item.resolve(), td_path / item.name)
                model = PeftModel.from_pretrained(model, str(td_path)).merge_and_unload()
        else:
            model = PeftModel.from_pretrained(model, str(ap)).merge_and_unload()

    model.config.use_cache = True
    model.to(dev).eval()
    return model, tok, dev, base_path


class _PendingPrompt:
    __slots__ = ("done", "value", "error")

    def __init__(self) -> None:
        self.done: bool = False
        self.value: Any = None
        self.error: BaseException | None = None


class _MicroBatchEngine:
    def __init__(
        self,
        run_batch_fn: Callable[[list[str]], list[Any]],
        max_batch_size: int = 24,
        wait_ms: float = 5.0,
    ):
        self._run_batch_fn = run_batch_fn
        self.max_batch_size = max(1, int(max_batch_size))
        self.wait_ms = max(0.0, float(wait_ms))
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self.cache: dict[str, Any] = {}
        self._inflight: dict[str, _PendingPrompt] = {}
        self._queue: deque[tuple[str, _PendingPrompt]] = deque()
        self._batcher_busy = False
        self._waiting_threads = 0
        self._active_episodes = 0
        self._remaining_episodes = 0
        self._expected_concurrency = 1
        self.total_requests = 0
        self.cache_hits = 0
        self.unique_prompts = 0
        self.batches_flushed = 0
        self.batch_sizes: list[int] = []
        self.batch_time_sec = 0.0

    def prepare_run(self, total_episodes: int, concurrency: int) -> None:
        with self._cond:
            self._remaining_episodes = max(0, int(total_episodes))
            self._expected_concurrency = max(1, int(concurrency))
            self._cond.notify_all()

    @contextmanager
    def episode_slot(self):
        with self._cond:
            self._active_episodes += 1
            self._cond.notify_all()
        try:
            yield
        finally:
            with self._cond:
                self._active_episodes = max(0, self._active_episodes - 1)
                if self._remaining_episodes > 0:
                    self._remaining_episodes -= 1
                self._cond.notify_all()

    def flush_barrier(self) -> None:
        with self._cond:
            self._cond.notify_all()

    def _barrier_ready(self) -> bool:
        if len(self._queue) >= self.max_batch_size:
            return True
        if self.wait_ms <= 0.0:
            return True
        if self._remaining_episodes > 0:
            target = min(self._expected_concurrency, self._remaining_episodes)
            if self._waiting_threads >= target:
                return True
        return False

    def resolve(self, prompt: str) -> Any:
        wait_s = self.wait_ms / 1000.0
        with self._cond:
            self.total_requests += 1
            if prompt in self.cache:
                self.cache_hits += 1
                return self.cache[prompt]
            pending = self._inflight.get(prompt)
            if pending is not None:
                self.cache_hits += 1
            else:
                pending = _PendingPrompt()
                self._inflight[prompt] = pending
                self._queue.append((prompt, pending))

            self._waiting_threads += 1
            self._cond.notify_all()
            try:
                while not pending.done:
                    if (not self._batcher_busy) and self._queue:
                        self._batcher_busy = True
                        try:
                            deadline = time.perf_counter() + wait_s
                            while not self._barrier_ready():
                                rem = deadline - time.perf_counter()
                                if rem <= 0.0:
                                    break
                                self._cond.wait(timeout=rem)
                            n_take = min(len(self._queue), self.max_batch_size)
                            batch_items = [self._queue.popleft() for _ in range(n_take)]
                        except BaseException:
                            self._batcher_busy = False
                            self._cond.notify_all()
                            raise

                        batch_prompts = [p for p, _ in batch_items]
                        self._cond.release()
                        t0 = time.perf_counter()
                        batch_err: BaseException | None = None
                        batch_vals: list[Any] = []
                        try:
                            batch_vals = list(self._run_batch_fn(batch_prompts))
                            if len(batch_vals) != len(batch_prompts):
                                raise RuntimeError(
                                    f"batch callback returned {len(batch_vals)} items for {len(batch_prompts)} prompts"
                                )
                        except BaseException as exc:
                            batch_err = exc
                        dt = time.perf_counter() - t0
                        self._cond.acquire()

                        self.batch_time_sec += dt
                        if batch_err is not None:
                            for p, item in batch_items:
                                self._inflight.pop(p, None)
                                item.error = batch_err
                                item.done = True
                        else:
                            self.batches_flushed += 1
                            self.batch_sizes.append(len(batch_items))
                            self.unique_prompts += len(batch_items)
                            for (p, item), val in zip(batch_items, batch_vals):
                                self.cache[p] = val
                                self._inflight.pop(p, None)
                                item.value = val
                                item.done = True
                        self._batcher_busy = False
                        self._cond.notify_all()
                    else:
                        self._cond.wait()
            finally:
                self._waiting_threads -= 1
                self._cond.notify_all()

            if pending.error is not None:
                raise pending.error
            return pending.value


class DynamicBatchMolePolicy:
    def __init__(
        self,
        model=None,
        tok=None,
        device: str = "cpu",
        max_new_tokens: int = 20,
        max_batch_size: int = 24,
        wait_ms: float = 5.0,
        system_prompt: str = SYSTEM,
        fallback: tuple[str, str] = ("random_seeded", "none"),
        batch_generate_fn: Callable[[list[str]], Sequence[str]] | None = None,
        name: str = "dynamic_batch_qwen_mole",
    ):
        self.model = model
        self.tok = tok
        self.device = str(device)
        self.max_new_tokens = int(max_new_tokens)
        self.max_batch_size = max(1, int(max_batch_size))
        self.wait_ms = max(0.0, float(wait_ms))
        self.system_prompt = system_prompt
        self.fallback = fallback
        self.batch_generate_fn = batch_generate_fn
        self.name = name
        self._record_lock = threading.Lock()
        self.actions: list[tuple[str, str]] = []
        self.invalid = 0
        self.invalid_decisions = 0
        self._engine = _MicroBatchEngine(
            run_batch_fn=self._execute_batch,
            max_batch_size=self.max_batch_size,
            wait_ms=self.wait_ms,
        )

    @property
    def calls(self) -> int:
        return self._engine.unique_prompts

    @property
    def unique_prompts(self) -> int:
        return self._engine.unique_prompts

    @property
    def cache_hits(self) -> int:
        return self._engine.cache_hits

    @property
    def total_decisions(self) -> int:
        return self._engine.total_requests

    @property
    def batches_flushed(self) -> int:
        return self._engine.batches_flushed

    @property
    def batch_sizes(self) -> list[int]:
        return list(self._engine.batch_sizes)

    @property
    def cache(self) -> dict[str, tuple[str, str]]:
        return {k: v[0] for k, v in self._engine.cache.items()}

    def prepare_run(self, total_episodes: int, concurrency: int) -> None:
        self._engine.prepare_run(total_episodes=total_episodes, concurrency=concurrency)

    @contextmanager
    def episode_slot(self):
        with self._engine.episode_slot():
            yield

    def flush(self) -> None:
        self._engine.flush_barrier()

    def _generate_texts(self, prompts: list[str]) -> list[str]:
        if self.batch_generate_fn is not None:
            return [str(x) for x in self.batch_generate_fn(list(prompts))]
        if self.model is None or self.tok is None:
            raise ValueError("DynamicBatchMolePolicy requires (model, tok) or batch_generate_fn")

        self.tok.padding_side = "left"
        if getattr(self.tok, "pad_token", None) is None:
            self.tok.pad_token = self.tok.eos_token
        pad_id = (
            int(self.tok.pad_token_id)
            if getattr(self.tok, "pad_token_id", None) is not None
            else int(self.tok.eos_token_id)
        )
        eos_id = int(getattr(self.tok, "eos_token_id", 2) or 2)
        texts_in = [
            apply_chat(
                self.tok,
                [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": p},
                ],
                add_gen=True,
            )
            for p in prompts
        ]

        if isinstance(self.model, TinyNumpyCausalLM):
            enc_raw = self.tok(texts_in, padding=False, add_special_tokens=False)
            seqs = [row or [4] for row in enc_raw["input_ids"]]
            max_l = max(len(x) for x in seqs)
            inp = np.full((len(seqs), max_l), pad_id, dtype=np.int64)
            att = np.zeros((len(seqs), max_l), dtype=np.int64)
            for bi, seq in enumerate(seqs):
                inp[bi, max_l - len(seq) :] = seq
                att[bi, max_l - len(seq) :] = 1
            gen = self.model.generate_greedy(
                inp,
                att,
                max_new_tokens=self.max_new_tokens,
                eos_token_id=eos_id,
            )
            comp = gen[:, max_l:]
            return list(self.tok.batch_decode(comp, skip_special_tokens=True))

        import torch

        enc = self.tok(texts_in, return_tensors="pt", padding=True, add_special_tokens=False).to(self.device)
        prompt_len = int(enc["input_ids"].shape[1])
        use_amp = self.device.startswith("cuda")
        self.model.eval()
        with torch.no_grad(), torch.autocast(
            device_type="cuda" if use_amp else "cpu",
            dtype=torch.float16,
            enabled=use_amp,
        ):
            gen = self.model.generate(
                **enc,
                max_new_tokens=self.max_new_tokens,
                do_sample=False,
                pad_token_id=pad_id,
                use_cache=True,
            )
        comp = gen[:, prompt_len:]
        return list(self.tok.batch_decode(comp, skip_special_tokens=True))

    def _execute_batch(self, prompts: list[str]) -> list[tuple[tuple[str, str], bool]]:
        completions = self._generate_texts(prompts)
        parsed_batch: list[tuple[tuple[str, str], bool]] = []
        inv_cnt = 0
        for comp in completions:
            parsed = parse_action(comp)
            if parsed is None:
                inv_cnt += 1
                parsed_batch.append((self.fallback, False))
            else:
                parsed_batch.append((parsed, True))
        if inv_cnt:
            with self._record_lock:
                self.invalid += inv_cnt
        return parsed_batch

    def decide(self, view: MoleView, rng: random.Random) -> dict[str, str | None]:
        prompt = render_view(view)
        act, is_valid = self._engine.resolve(prompt)
        with self._record_lock:
            self.actions.append(act)
            if not is_valid:
                self.invalid_decisions += 1
        return {
            "leak": _select_leak(act[0], view, rng),
            "frame": _select_frame(act[1], view, rng),
        }

    def stats(self) -> dict[str, Any]:
        with self._record_lock:
            acts = list(self.actions)
            inv_gen = int(self.invalid)
            inv_dec = int(self.invalid_decisions)
        tot = self._engine.total_requests
        uniq = self._engine.unique_prompts
        hits = self._engine.cache_hits
        batches = self._engine.batches_flushed
        bsizes = list(self._engine.batch_sizes)
        ac = Counter(acts)
        denom_a = max(1, len(acts))
        ent = shannon_entropy_nats([v / float(denom_a) for v in ac.values()])
        return {
            "mode": "greedy",
            "total_decisions": tot,
            "unique_prompts": uniq,
            "cache_hits": hits,
            "cache_hit_rate": round(hits / float(max(1, tot)), 4),
            "batches_flushed": batches,
            "batch_sizes": bsizes,
            "mean_batch_size": round(uniq / float(max(1, batches)), 4),
            "max_observed_batch_size": max(bsizes, default=0),
            "invalid_generations": inv_gen,
            "invalid_decisions": inv_dec,
            "invalid_rate": round(inv_gen / float(max(1, uniq)), 4) if uniq > 0 else 0.0,
            "decision_invalid_rate": round(inv_dec / float(max(1, tot)), 4) if tot > 0 else 0.0,
            "batch_generate_sec": round(self._engine.batch_time_sec, 4),
            "call_reduction_vs_uncached": round(tot / float(max(1, batches)), 4) if batches > 0 else 1.0,
            "call_reduction_vs_seq_cached": round(uniq / float(max(1, batches)), 4) if batches > 0 else 1.0,
            "distinct_actions": len(ac),
            "action_entropy_nats": round(ent, 4),
            "action_profile": {"/".join(k): round(v / float(denom_a), 4) for k, v in ac.most_common(24)},
        }


class ConstrainedLogprobMolePolicy:
    def __init__(
        self,
        model=None,
        tok=None,
        device: str = "cpu",
        trap_only_none: bool = False,
        greedy: bool = True,
        temperature: float = 1.0,
        length_norm: bool = False,
        max_batch_size: int = 24,
        cand_chunk_size: int = 48,
        wait_ms: float = 5.0,
        system_prompt: str = SYSTEM,
        score_candidates_fn: Callable[..., Sequence[float]] | None = None,
        name: str = "constrained_logprob_qwen_mole",
    ):
        self.model = model
        self.tok = tok
        self.device = str(device)
        self.trap_only_none = bool(trap_only_none)
        self.greedy = bool(greedy)
        self.temperature = float(temperature)
        self.length_norm = bool(length_norm)
        self.max_batch_size = max(1, int(max_batch_size))
        self.cand_chunk_size = max(1, int(cand_chunk_size))
        self.wait_ms = max(0.0, float(wait_ms))
        self.system_prompt = system_prompt
        self.score_candidates_fn = score_candidates_fn
        self.name = name
        self.invalid = 0
        self._cand_token_ids: list[list[int]] | None = None
        if self.tok is not None:
            self._cand_token_ids = [
                list(self.tok(c, add_special_tokens=False)["input_ids"])
                for c in CANONICAL_CANDIDATES
            ]
        self._record_lock = threading.Lock()
        self.actions: list[tuple[str, str]] = []
        self.state_probs: list[tuple[float, ...]] = []
        self.unique_state_probs: dict[tuple[str, bool], tuple[float, ...]] = {}
        self.masked_none_states = 0
        self._engine = _MicroBatchEngine(
            run_batch_fn=self._score_prompt_batch,
            max_batch_size=self.max_batch_size,
            wait_ms=self.wait_ms,
        )

    @property
    def calls(self) -> int:
        return self._engine.unique_prompts

    @property
    def unique_prompts(self) -> int:
        return self._engine.unique_prompts

    @property
    def cache_hits(self) -> int:
        return self._engine.cache_hits

    @property
    def total_decisions(self) -> int:
        return self._engine.total_requests

    @property
    def batches_flushed(self) -> int:
        return self._engine.batches_flushed

    @property
    def batch_sizes(self) -> list[int]:
        return list(self._engine.batch_sizes)

    def prepare_run(self, total_episodes: int, concurrency: int) -> None:
        self._engine.prepare_run(total_episodes=total_episodes, concurrency=concurrency)

    @contextmanager
    def episode_slot(self):
        with self._engine.episode_slot():
            yield

    def flush(self) -> None:
        self._engine.flush_barrier()

    def _invoke_custom_scorer(self, prompt: str) -> tuple[float, ...]:
        assert self.score_candidates_fn is not None
        try:
            vals = self.score_candidates_fn(prompt, list(CANONICAL_CANDIDATES))
        except TypeError:
            vals = self.score_candidates_fn(prompt)
        out = tuple(float(x) for x in vals)
        if len(out) != len(CANONICAL_CANDIDATES):
            raise ValueError(
                f"score_candidates_fn must return {len(CANONICAL_CANDIDATES)} logprobs, got {len(out)}"
            )
        return out

    def _score_prompt_batch(self, prompts: list[str]) -> list[tuple[float, ...]]:
        if self.score_candidates_fn is not None:
            return [self._invoke_custom_scorer(p) for p in prompts]
        if self.model is None or self.tok is None:
            raise ValueError("ConstrainedLogprobMolePolicy requires (model, tok) or score_candidates_fn")

        if self._cand_token_ids is None:
            self._cand_token_ids = [
                list(self.tok(c, add_special_tokens=False)["input_ids"])
                for c in CANONICAL_CANDIDATES
            ]
        pad_id = (
            int(self.tok.pad_token_id)
            if getattr(self.tok, "pad_token_id", None) is not None
            else int(getattr(self.tok, "eos_token_id", 0) or 0)
        )
        prompt_ids_list: list[list[int]] = []
        for p in prompts:
            chat_txt = apply_chat(
                self.tok,
                [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": p},
                ],
                add_gen=True,
            )
            p_ids = list(self.tok(chat_txt, add_special_tokens=False)["input_ids"]) or [4]
            prompt_ids_list.append(p_ids)

        pairs: list[tuple[int, int, list[int], list[int]]] = [
            (p_idx, c_idx, p_ids, c_ids)
            for p_idx, p_ids in enumerate(prompt_ids_list)
            for c_idx, c_ids in enumerate(self._cand_token_ids)
        ]
        scores_grid = [[0.0] * len(CANONICAL_CANDIDATES) for _ in range(len(prompts))]

        if isinstance(self.model, TinyNumpyCausalLM):
            scored = self.model.score_candidates(
                pairs,
                pad_id=pad_id,
                length_norm=self.length_norm,
                chunk_size=self.cand_chunk_size,
            )
            for p_idx, c_idx, val in scored:
                scores_grid[p_idx][c_idx] = val
            return [tuple(row) for row in scores_grid]

        import torch

        use_amp = self.device.startswith("cuda")
        self.model.eval()
        step = max(1, int(self.cand_chunk_size))
        for start in range(0, len(pairs), step):
            chunk = pairs[start : start + step]
            max_l = max(len(p_ids) + len(c_ids) for _, _, p_ids, c_ids in chunk)
            inp = torch.full((len(chunk), max_l), pad_id, dtype=torch.long, device=self.device)
            att = torch.zeros((len(chunk), max_l), dtype=torch.long, device=self.device)
            for bi, (_, _, p_ids, c_ids) in enumerate(chunk):
                seq = p_ids + c_ids
                inp[bi, : len(seq)] = torch.tensor(seq, dtype=torch.long, device=self.device)
                att[bi, : len(seq)] = 1
            with torch.no_grad(), torch.autocast(
                device_type="cuda" if use_amp else "cpu",
                dtype=torch.float16,
                enabled=use_amp,
            ):
                logits = self.model(input_ids=inp, attention_mask=att, use_cache=False).logits
            for bi, (p_idx, c_idx, p_ids, c_ids) in enumerate(chunk):
                lp_len = len(p_ids)
                lc_len = len(c_ids)
                slice_logits = logits[bi, lp_len - 1 : lp_len + lc_len - 1].float()
                log_probs = torch.log_softmax(slice_logits, dim=-1)
                tgt = torch.tensor(c_ids, dtype=torch.long, device=slice_logits.device)
                tok_lp = log_probs.gather(-1, tgt.unsqueeze(-1)).squeeze(-1)
                val = float(tok_lp.mean().item()) if self.length_norm else float(tok_lp.sum().item())
                scores_grid[p_idx][c_idx] = val
        return [tuple(row) for row in scores_grid]

    def action_probabilities(self, view: MoleView) -> list[float]:
        prompt = render_view(view)
        raw_logps = self._engine.resolve(prompt)
        mask_none = should_mask_none_leak(view, self.trap_only_none)
        return compute_constrained_probs(raw_logps, mask_none=mask_none, temperature=self.temperature)

    def action_distribution(self, view: MoleView) -> dict[str, float]:
        probs = self.action_probabilities(view)
        return {CANONICAL_CANDIDATES[i]: probs[i] for i in range(len(CANONICAL_CANDIDATES))}

    def decide(self, view: MoleView, rng: random.Random) -> dict[str, str | None]:
        prompt = render_view(view)
        raw_logps = self._engine.resolve(prompt)
        mask_none = should_mask_none_leak(view, self.trap_only_none)
        probs = compute_constrained_probs(raw_logps, mask_none=mask_none, temperature=self.temperature)
        allowed = [
            i
            for i, (leak_sel, _) in enumerate(CANONICAL_ACTIONS)
            if not (mask_none and leak_sel == "none")
        ]
        if self.greedy:
            chosen_idx = max(allowed, key=lambda i: (float(raw_logps[i]), -i))
        else:
            allowed_probs = np.asarray([probs[i] for i in allowed], dtype=np.float64)
            total_p = float(allowed_probs.sum())
            u = rng.random() * (total_p if total_p > 0.0 else 1.0)
            pos = int(np.searchsorted(np.cumsum(allowed_probs), u))
            pos = min(max(0, pos), len(allowed) - 1)
            chosen_idx = allowed[pos]

        act = CANONICAL_ACTIONS[chosen_idx]
        probs_tup = tuple(probs)
        with self._record_lock:
            self.actions.append(act)
            self.state_probs.append(probs_tup)
            self.unique_state_probs[(prompt, mask_none)] = probs_tup
            if mask_none:
                self.masked_none_states += 1
        return {
            "leak": _select_leak(act[0], view, rng),
            "frame": _select_frame(act[1], view, rng),
        }

    def empirical_mutual_information(self, unique_only: bool = False) -> dict[str, Any]:
        with self._record_lock:
            rows = list(self.unique_state_probs.values()) if unique_only else list(self.state_probs)
        return compute_mutual_information_from_probs(rows)

    def stats(self) -> dict[str, Any]:
        with self._record_lock:
            acts = list(self.actions)
            masked_cnt = int(self.masked_none_states)
        mi_all = self.empirical_mutual_information(unique_only=False)
        mi_uniq = self.empirical_mutual_information(unique_only=True)
        tot = self._engine.total_requests
        uniq = self._engine.unique_prompts
        hits = self._engine.cache_hits
        batches = self._engine.batches_flushed
        bsizes = list(self._engine.batch_sizes)
        ac = Counter(acts)
        denom_a = max(1, len(acts))
        ent = shannon_entropy_nats([v / float(denom_a) for v in ac.values()])
        return {
            "mode": "constrained",
            "trap_only_none": self.trap_only_none,
            "greedy": self.greedy,
            "temperature": self.temperature,
            "length_norm": self.length_norm,
            "masked_none_states": masked_cnt,
            "total_decisions": tot,
            "unique_prompts": uniq,
            "cache_hits": hits,
            "cache_hit_rate": round(hits / float(max(1, tot)), 4),
            "batches_flushed": batches,
            "batch_sizes": bsizes,
            "mean_batch_size": round(uniq / float(max(1, batches)), 4),
            "max_observed_batch_size": max(bsizes, default=0),
            "invalid_generations": 0,
            "invalid_decisions": 0,
            "invalid_rate": 0.0,
            "decision_invalid_rate": 0.0,
            "batch_generate_sec": round(self._engine.batch_time_sec, 4),
            "call_reduction_vs_uncached": round(tot / float(max(1, batches)), 4) if batches > 0 else 1.0,
            "call_reduction_vs_seq_cached": round(uniq / float(max(1, batches)), 4) if batches > 0 else 1.0,
            "distinct_actions": len(ac),
            "action_entropy_nats": round(ent, 4),
            "action_profile": {"/".join(k): round(v / float(denom_a), 4) for k, v in ac.most_common(24)},
            "mutual_info_nats": mi_all["mi_nats"],
            "mutual_info_bits": mi_all["mi_bits"],
            "unique_state_mutual_info_nats": mi_uniq["mi_nats"],
            "mutual_information": mi_all,
            "unique_state_mutual_information": mi_uniq,
        }


def boot_ci(xs: Sequence[float], B: int = 2000, seed: int = 0) -> list[float]:
    n = len(xs)
    if n == 0:
        return [0.0, 0.0, 0.0]
    rng = random.Random(seed)
    vals = [float(x) for x in xs]
    means = sorted(sum(vals[rng.randrange(n)] for _ in range(n)) / float(n) for _ in range(B))
    return [
        round(sum(vals) / float(n), 4),
        round(means[int(0.025 * B)], 4),
        round(means[int(0.975 * B)], 4),
    ]


def summarize_rows(
    rows: list[dict[str, tuple[float, bool]]],
    min_solver_acc: float = 0.85,
    default_solver_score: float | None = None,
    B: int = 2000,
) -> dict[str, Any]:
    n = max(1, len(rows))
    raw_solver_score = sum(r["solver"][0] for r in rows) / float(n)
    raw_solver_acc = sum(float(r["solver"][1]) for r in rows) / float(n)
    ref_score = raw_solver_score if default_solver_score is None else float(default_solver_score)
    out: dict[str, Any] = {
        ag: {
            "score": round(sum(r[ag][0] for r in rows) / float(n), 4),
            "acc": round(sum(float(r[ag][1]) for r in rows) / float(n), 4),
            "score_ci95": boot_ci([r[ag][0] for r in rows], B=B, seed=0),
            "acc_ci95": boot_ci([float(r[ag][1]) for r in rows], B=B, seed=0),
        }
        for ag in ALL_AGENTS
    }
    out["regret"] = {
        k: boot_ci([r["solver"][0] - r[k][0] for r in rows], B=B, seed=0)
        for k in INVESTIGATORS
    }
    out["min_regret"] = round(out["solver"]["score"] - max(out[k]["score"] for k in INVESTIGATORS), 4)
    out["strongest_investigator"] = max(INVESTIGATORS, key=lambda k: out[k]["score"])
    out["catchable"] = bool(raw_solver_acc >= min_solver_acc - 1e-12)
    out["catchable_85"] = bool(raw_solver_acc >= 0.85 - 1e-12)
    out["catchable_85_value_guarded"] = bool(
        (raw_solver_acc >= 0.85 - 1e-12) and (raw_solver_score >= 0.5 * ref_score - 1e-12)
    )
    return out


def paired_diff(
    cand_rows: list[dict[str, tuple[float, bool]]],
    ref_rows: list[dict[str, tuple[float, bool]]],
    B: int = 2000,
) -> dict[str, Any]:
    diff: dict[str, Any] = {
        **{
            f"{ag}_score": boot_ci(
                [y[ag][0] - x[ag][0] for x, y in zip(ref_rows, cand_rows)],
                B=B,
                seed=0,
            )
            for ag in ALL_AGENTS
        },
        "solver_acc": boot_ci(
            [float(y["solver"][1]) - float(x["solver"][1]) for x, y in zip(ref_rows, cand_rows)],
            B=B,
            seed=0,
        ),
        **{
            f"regret_{k}": boot_ci(
                [(y["solver"][0] - y[k][0]) - (x["solver"][0] - x[k][0]) for x, y in zip(ref_rows, cand_rows)],
                B=B,
                seed=0,
            )
            for k in INVESTIGATORS
        },
    }
    n_c = max(1, len(cand_rows))
    n_r = max(1, len(ref_rows))
    c_min_reg = sum(y["solver"][0] for y in cand_rows) / float(n_c) - max(
        sum(y[k][0] for y in cand_rows) / float(n_c) for k in INVESTIGATORS
    )
    r_min_reg = sum(x["solver"][0] for x in ref_rows) / float(n_r) - max(
        sum(x[k][0] for x in ref_rows) / float(n_r) for k in INVESTIGATORS
    )
    diff["min_regret_diff"] = round(c_min_reg - r_min_reg, 4)
    return diff


def _init_worker_secret(secret: bytes | None) -> None:
    if secret is not None and len(secret) >= 16:
        canary_world.set_world_secret(secret)


def _baseline_seed_rollout(task) -> dict[str, tuple[float, bool]]:
    kind, payload, tier, seed = task
    out: dict[str, tuple[float, bool]] = {}
    for ag in ALL_AGENTS:
        if kind == "default":
            strat = DEFAULT_STRATEGY
        elif kind == "rl_v1":
            params, greedy = payload
            strat = RLMole(params, greedy=greedy)
        elif kind == "rl_v2":
            params, greedy, none_pen, none_gap = payload
            strat = RLMoleV2(
                params,
                greedy=greedy,
                none_penalty=none_pen,
                none_cap_gap=none_gap,
            )
        else:
            raise ValueError(f"unknown baseline rollout kind: {kind}")
        ep = run_episode(Env(tier, seed, mole_strategy=strat), _agent(ag, tier, seed))
        out[ag] = (float(ep.score), bool(ep.correct))
    return out


def _load_rl_v1_policy(spec: RLMole | str | Path | None) -> RLMole | None:
    if spec is None:
        return None
    if isinstance(spec, RLMole):
        return spec
    s_txt = str(spec).strip()
    if not s_txt or s_txt.lower() == "none":
        return None
    p = Path(s_txt)
    if not p.is_file():
        return None
    obj = json.loads(p.read_text(encoding="utf-8"))
    if obj.get("kind") == "rl_mole":
        return RLMole.from_json(obj)
    return None


def _load_rl_v2_policy(spec: RLMoleV2 | str | Path | None) -> RLMoleV2 | None:
    if spec is None:
        return None
    if isinstance(spec, RLMoleV2):
        return spec
    s_txt = str(spec).strip()
    if not s_txt or s_txt.lower() == "none":
        return None
    p = Path(s_txt)
    if not p.is_file():
        return None
    obj = json.loads(p.read_text(encoding="utf-8"))
    if obj.get("kind") == "rl_mole_v2":
        return RLMoleV2.from_json(obj)
    return None


def evaluate_batched_mole(
    policy: DynamicBatchMolePolicy | ConstrainedLogprobMolePolicy | Any,
    seeds: Sequence[int],
    tier: str = "hard",
    concurrency: int = 16,
    workers: int = 1,
    min_solver_acc: float = 0.85,
    rl_policy: RLMole | str | Path | None = None,
    rl_v2_policy: RLMoleV2 | str | Path | None = None,
    bootstrap_resamples: int = 2000,
    include_rows: bool = False,
) -> dict[str, Any]:
    seed_list = guard_eval_seeds(seeds)
    t_total = time.perf_counter()

    shared_secret: bytes | None = None
    for s in seed_list:
        k = canary_world._key(s)
        if k != b"public" and len(k) >= 16:
            shared_secret = k
            break

    cand_tasks = [(idx, s, ag) for idx, s in enumerate(seed_list) for ag in ALL_AGENTS]
    eff_conc = max(1, min(int(concurrency), len(cand_tasks)))
    if hasattr(policy, "prepare_run"):
        policy.prepare_run(total_episodes=len(cand_tasks), concurrency=eff_conc)

    model_obj = getattr(policy, "model", None)
    has_cfg = model_obj is not None and hasattr(model_obj, "config")
    was_uc = getattr(model_obj.config, "use_cache", False) if has_cfg else False
    if has_cfg:
        model_obj.config.use_cache = True
    merged_temp = False
    if (
        model_obj is not None
        and hasattr(model_obj, "merge_adapter")
        and hasattr(model_obj, "unmerge_adapter")
    ):
        try:
            model_obj.merge_adapter()
            merged_temp = True
        except Exception:
            merged_temp = False

    def _run_cand_episode(item: tuple[int, int, str]) -> tuple[int, str, float, bool]:
        idx, s, ag = item
        if hasattr(policy, "episode_slot"):
            with policy.episode_slot():
                ep = run_episode(Env(tier, s, mole_strategy=policy), _agent(ag, tier, s))
        else:
            ep = run_episode(Env(tier, s, mole_strategy=policy), _agent(ag, tier, s))
        return idx, ag, float(ep.score), bool(ep.correct)

    cand_rows: list[dict[str, tuple[float, bool]]] = [{} for _ in seed_list]
    t_cand0 = time.perf_counter()
    try:
        if eff_conc > 1:
            with ThreadPoolExecutor(max_workers=eff_conc) as ex:
                for idx, ag, sc, corr in ex.map(_run_cand_episode, cand_tasks):
                    cand_rows[idx][ag] = (sc, corr)
        else:
            for item in cand_tasks:
                idx, ag, sc, corr = _run_cand_episode(item)
                cand_rows[idx][ag] = (sc, corr)
    finally:
        if merged_temp:
            model_obj.unmerge_adapter()
        if has_cfg:
            model_obj.config.use_cache = was_uc
    cand_sec = time.perf_counter() - t_cand0

    rl_v1 = _load_rl_v1_policy(rl_policy)
    rl_v2 = _load_rl_v2_policy(rl_v2_policy)

    def_tasks = [("default", None, tier, s) for s in seed_list]
    v1_tasks = (
        [("rl_v1", ({k: v.copy() for k, v in rl_v1.p.items()}, rl_v1.greedy), tier, s) for s in seed_list]
        if rl_v1 is not None
        else []
    )
    v2_tasks = (
        [
            (
                "rl_v2",
                (
                    {k: v.copy() for k, v in rl_v2.p.items()},
                    rl_v2.greedy,
                    rl_v2.none_penalty,
                    rl_v2.none_cap_gap,
                ),
                tier,
                s,
            )
            for s in seed_list
        ]
        if rl_v2 is not None
        else []
    )

    all_base_tasks = def_tasks + v1_tasks + v2_tasks
    n_seeds = len(seed_list)
    cpu_w = max(1, int(workers))
    if cpu_w > 1 and len(all_base_tasks) >= 8:
        with ProcessPoolExecutor(
            max_workers=cpu_w,
            mp_context=mp.get_context("spawn"),
            initializer=_init_worker_secret,
            initargs=(shared_secret,),
        ) as pool:
            base_out = list(pool.map(_baseline_seed_rollout, all_base_tasks))
    else:
        base_out = [_baseline_seed_rollout(t) for t in all_base_tasks]

    def_rows = base_out[:n_seeds]
    offset = n_seeds
    rl_rows = None
    if rl_v1 is not None:
        rl_rows = base_out[offset : offset + n_seeds]
        offset += n_seeds
    rl_v2_rows = None
    if rl_v2 is not None:
        rl_v2_rows = base_out[offset : offset + n_seeds]

    def_solver_score = sum(r["solver"][0] for r in def_rows) / float(max(1, n_seeds))
    cand_summary = summarize_rows(
        cand_rows,
        min_solver_acc=min_solver_acc,
        default_solver_score=def_solver_score,
        B=bootstrap_resamples,
    )
    def_summary = summarize_rows(
        def_rows,
        min_solver_acc=min_solver_acc,
        default_solver_score=def_solver_score,
        B=bootstrap_resamples,
    )

    if hasattr(policy, "stats"):
        pstats = policy.stats()
    else:
        acts = list(getattr(policy, "actions", []))
        ac = Counter(acts)
        tot_a = max(1, len(acts))
        uniq = int(getattr(policy, "calls", len(acts)))
        inv = int(getattr(policy, "invalid", 0))
        hits = max(0, len(acts) - uniq)
        pstats = {
            "mode": "custom",
            "total_decisions": len(acts),
            "unique_prompts": uniq,
            "cache_hits": hits,
            "cache_hit_rate": round(hits / float(tot_a), 4) if acts else 0.0,
            "batches_flushed": uniq,
            "batch_sizes": [1] * uniq,
            "mean_batch_size": 1.0 if uniq else 0.0,
            "max_observed_batch_size": 1 if uniq else 0,
            "invalid_generations": inv,
            "invalid_decisions": inv,
            "invalid_rate": round(inv / float(max(1, uniq)), 4) if uniq else 0.0,
            "decision_invalid_rate": round(inv / float(tot_a), 4) if acts else 0.0,
            "batch_generate_sec": 0.0,
            "call_reduction_vs_uncached": round(len(acts) / float(max(1, uniq)), 4) if uniq else 1.0,
            "call_reduction_vs_seq_cached": 1.0,
            "distinct_actions": len(ac),
            "action_entropy_nats": round(
                shannon_entropy_nats([v / float(tot_a) for v in ac.values()]),
                4,
            ),
            "action_profile": {"/".join(k): round(v / float(tot_a), 4) for k, v in ac.most_common(24)},
        }

    total_sec = time.perf_counter() - t_total
    report: dict[str, Any] = {
        "tier": tier,
        "seeds": f"{seed_list[0]}-{seed_list[-1]}",
        "seed_range": [seed_list[0], seed_list[-1]],
        "n": n_seeds,
        "agents": list(ALL_AGENTS),
        "concurrency": eff_conc,
        "min_solver_acc": min_solver_acc,
        "bootstrap_resamples": bootstrap_resamples,
        "seconds": round(total_sec, 3),
        "catchable_85": cand_summary["catchable_85"],
        "catchable_85_value_guarded": cand_summary["catchable_85_value_guarded"],
        "invalid_rate": pstats["invalid_rate"],
        "cache_hit_rate": pstats["cache_hit_rate"],
        "candidate_mole": cand_summary,
        "default_mole": def_summary,
        "diff_candidate_minus_default": paired_diff(cand_rows, def_rows, B=bootstrap_resamples),
        "policy_stats": pstats,
        "batching_stats": {
            "concurrency": eff_conc,
            "max_batch_size": int(getattr(policy, "max_batch_size", 1)),
            "total_episodes": len(cand_tasks),
            "total_decisions": pstats["total_decisions"],
            "unique_prompts": pstats["unique_prompts"],
            "cache_hits": pstats["cache_hits"],
            "cache_hit_rate": pstats["cache_hit_rate"],
            "batches_flushed": pstats["batches_flushed"],
            "mean_batch_size": pstats["mean_batch_size"],
            "max_observed_batch_size": pstats["max_observed_batch_size"],
            "call_reduction_vs_uncached": pstats["call_reduction_vs_uncached"],
            "call_reduction_vs_seq_cached": pstats["call_reduction_vs_seq_cached"],
            "candidate_eval_sec": round(cand_sec, 4),
            "batch_forward_sec": pstats["batch_generate_sec"],
            "episodes_per_sec": round(len(cand_tasks) / max(1e-6, cand_sec), 3),
        },
    }
    if rl_rows is not None:
        report["rl_mole"] = summarize_rows(
            rl_rows,
            min_solver_acc=min_solver_acc,
            default_solver_score=def_solver_score,
            B=bootstrap_resamples,
        )
        report["diff_candidate_minus_rl_mole"] = paired_diff(cand_rows, rl_rows, B=bootstrap_resamples)
    if rl_v2_rows is not None:
        report["rl_mole_v2"] = summarize_rows(
            rl_v2_rows,
            min_solver_acc=min_solver_acc,
            default_solver_score=def_solver_score,
            B=bootstrap_resamples,
        )
        report["diff_candidate_minus_rl_mole_v2"] = paired_diff(
            cand_rows,
            rl_v2_rows,
            B=bootstrap_resamples,
        )
    if include_rows:
        ep_rows: dict[str, Any] = {"candidate": cand_rows, "default": def_rows}
        if rl_rows is not None:
            ep_rows["rl_mole"] = rl_rows
        if rl_v2_rows is not None:
            ep_rows["rl_mole_v2"] = rl_v2_rows
        report["episode_rows"] = ep_rows
    return report


def _default_cpu_workers() -> int:
    return 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m train.batched_mole_eval")
    ap.add_argument("--model", default=None)
    ap.add_argument("--adapter", default=None)
    ap.add_argument("--mode", choices=("greedy", "constrained"), default="greedy")
    ap.add_argument("--seeds", default="heldout")
    ap.add_argument("--n", type=int, default=None)
    ap.add_argument("--tier", default="hard")
    ap.add_argument("--batch-size", type=int, default=24)
    ap.add_argument("--cand-chunk-size", type=int, default=48)
    ap.add_argument("--concurrency", type=int, default=16)
    ap.add_argument("--max-new-tokens", "--max-new", dest="max_new_tokens", type=int, default=20)
    ap.add_argument("--wait-ms", type=float, default=5.0)
    ap.add_argument("--trap-only-none", action="store_true")
    ap.add_argument("--stochastic", action="store_true")
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--length-norm", action="store_true")
    ap.add_argument("--min-solver-acc", type=float, default=0.85)
    ap.add_argument("--bootstrap-resamples", type=int, default=2000)
    ap.add_argument("--rl-policy", default=DEFAULT_RL_MOLE_PATH)
    ap.add_argument("--rl-v2-policy", default=DEFAULT_RL_MOLE_V2_PATH)
    ap.add_argument("--no-rl-baselines", action="store_true")
    ap.add_argument("--workers", type=int, default=_default_cpu_workers())
    ap.add_argument("--device", default=None)
    ap.add_argument("--tiny", action="store_true")
    ap.add_argument("--out", default=None)
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_parser()
    a = ap.parse_args(argv)

    n_seeds = int(a.n) if a.n is not None else (2 if a.tiny else 60)
    seeds = parse_seeds(a.seeds, n_seeds)

    model, tok, dev, base_path = load_eval_model(
        model_spec=a.model,
        adapter_dir=a.adapter,
        tiny=bool(a.tiny),
        device=a.device,
    )
    if a.mode == "greedy":
        policy: DynamicBatchMolePolicy | ConstrainedLogprobMolePolicy = DynamicBatchMolePolicy(
            model=model,
            tok=tok,
            device=dev,
            max_new_tokens=a.max_new_tokens,
            max_batch_size=a.batch_size,
            wait_ms=a.wait_ms,
        )
    else:
        policy = ConstrainedLogprobMolePolicy(
            model=model,
            tok=tok,
            device=dev,
            trap_only_none=bool(a.trap_only_none),
            greedy=not bool(a.stochastic),
            temperature=a.temperature,
            length_norm=bool(a.length_norm),
            max_batch_size=a.batch_size,
            cand_chunk_size=a.cand_chunk_size,
            wait_ms=a.wait_ms,
        )

    rl_p = None if a.no_rl_baselines else a.rl_policy
    rl_v2_p = None if a.no_rl_baselines else a.rl_v2_policy
    report = evaluate_batched_mole(
        policy=policy,
        seeds=seeds,
        tier=a.tier,
        concurrency=a.concurrency,
        workers=a.workers,
        min_solver_acc=a.min_solver_acc,
        rl_policy=rl_p,
        rl_v2_policy=rl_v2_p,
        bootstrap_resamples=a.bootstrap_resamples,
    )
    report["model"] = base_path
    report["adapter"] = a.adapter
    report["mode"] = a.mode
    report["device"] = dev
    report["tiny"] = bool(a.tiny)

    if a.out:
        out_p = Path(a.out)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
