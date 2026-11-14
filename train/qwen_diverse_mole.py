from __future__ import annotations

import argparse
import json
import math
import os
import random
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from canary import rules
from canary.env import Env
from canary.eval import run_episode
from canary.forge.rl_mole import INVESTIGATORS, RLMole, _agent, _default_rollout, rollout as rl_rollout
from canary.mole.dsl import (
    DEFAULT_STRATEGY,
    FRAME_SELECTORS,
    LEAK_SELECTORS,
    MoleDoc,
    MoleView,
    _select_frame,
    _select_leak,
)
from canary.solver.policy import SolverPolicy
from train.grpo_mole import SYSTEM, parse_action, render_view

TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
MIN_SOLVER_ACC = 0.85
TARGET_SOLVER_ACC = 0.89
COUNTERFACTUAL_SEED_BASE = 120_000
VAL_SEED_BASE = 195_000
MAX_NONE_SHARE = 0.15
ACTION_FREQ_CAP = 0.40
ACTION_FREQ_PENALTY_SCALE = 0.25

CANDIDATE_EXPERT_ACTIONS = (
    ("most_recipients", "random_peer"),
    ("most_recipients", "most_restricted_peer"),
    ("most_recipients", "decoy"),
    ("newest", "random_peer"),
    ("newest", "most_restricted_peer"),
    ("oldest", "random_peer"),
    ("random_seeded", "most_restricted_peer"),
    ("random_seeded", "decoy"),
)

LOCAL_MODEL_CANDIDATES = {
    "Qwen/Qwen2.5-0.5B-Instruct": [
        os.path.expanduser("~/agent-arena-data/models/Qwen2.5-0.5B-Instruct"),
    ],
    "Qwen/Qwen2.5-1.5B-Instruct": [
        os.path.expanduser("~/agent-arena-data/models/Qwen2.5-1.5B-Instruct"),
    ],
    "Qwen/Qwen3-0.6B": [
        "/home/silas/momin/fleet/board/sleeper/moletrain_runs/models/Qwen3-0.6B",
    ],
    "Qwen/Qwen3-1.7B": [
        "/home/silas/momin/fleet/board/sleeper/moletrain_runs/models/Qwen3-1.7B",
    ],
}


def resolve_model_path(spec: str | None, adapter_dir: str | None = None) -> str:
    raw = spec
    if not raw and adapter_dir:
        cfg_p = Path(adapter_dir) / "adapter_config.json"
        if cfg_p.is_file():
            raw = json.loads(cfg_p.read_text(encoding="utf-8")).get("base_model_name_or_path")
    if not raw:
        raw = "Qwen/Qwen2.5-1.5B-Instruct"
    expanded = os.path.expanduser(raw)
    if os.path.isdir(expanded):
        return expanded
    for cand in LOCAL_MODEL_CANDIDATES.get(raw, []):
        if os.path.isdir(cand):
            return cand
    return raw


def guard_train_seed(seed: int) -> int:
    s = int(seed)
    if s < 0 or s in rules.JUDGE_SEEDS or s in rules.HELDOUT_SEEDS or s >= VAL_SEED_BASE:
        raise ValueError(f"forbidden held-out, val, or judge seed in training: {s}")
    if not (s in rules.DEV_SEEDS or (s in rules.TRAIN_SEEDS and s < VAL_SEED_BASE)):
        raise ValueError(f"seed {s} outside allowed DEV_SEEDS or TRAIN_SEEDS (<{VAL_SEED_BASE})")
    return s


def guard_counterfactual_seed(seed: int) -> int:
    s = guard_train_seed(seed)
    if not (s in rules.TRAIN_SEEDS and COUNTERFACTUAL_SEED_BASE <= s < VAL_SEED_BASE):
        raise ValueError(
            f"counterfactual seed {s} must lie in TRAIN_SEEDS [{COUNTERFACTUAL_SEED_BASE}, {VAL_SEED_BASE})"
        )
    return s


def render_dict_view(mv: dict | str) -> str:
    if isinstance(mv, str):
        mv = json.loads(mv)
    raw_docs = mv.get("held_docs") if mv.get("held_docs") is not None else (mv.get("docs") or [])
    docs = tuple(
        MoleDoc(
            doc_id=str(d.get("doc_id", "")),
            title=str(d.get("title", "")),
            recipient_count=int(d.get("recipient_count", 0)),
            age_days=int(d.get("age_days", 0)),
        )
        for d in raw_docs
    )
    v = MoleView(
        day=int(mv.get("day", 1)),
        docs=docs,
        days_since_last_leak=int(mv.get("days_since_last_leak", 1)),
        i_am_restricted=int(bool(mv.get("i_am_restricted", False))),
        n_restricted_colleagues=int(mv.get("n_restricted_colleagues", 0)),
        recent_low_recipient_docs=int(mv.get("recent_low_recipient_docs", 0)),
        peers=tuple(mv.get("peers") or ()),
        restricted_peers=tuple(mv.get("restricted_peers") or ()),
        decoy=mv.get("decoy"),
        can_leak=bool(mv.get("can_leak", True)),
    )
    return render_view(v)


def map_carbon_turn(row: dict) -> tuple[str, str, bool]:
    mv = row["mole_view"]
    if isinstance(mv, str):
        mv = json.loads(mv)
    docs = mv.get("held_docs") if mv.get("held_docs") is not None else (mv.get("docs") or [])
    leak = row.get("leak")
    frame = row.get("frame")
    max_rec = max((int(x.get("recipient_count", 0)) for x in docs), default=0)
    min_rec = min((int(x.get("recipient_count", 0)) for x in docs), default=0)
    min_age = min((int(x.get("age_days", 0)) for x in docs), default=0)
    max_age = max((int(x.get("age_days", 0)) for x in docs), default=0)
    by_id = {str(d.get("doc_id", "")): d for d in docs}
    if not leak or leak == "none" or not docs or not mv.get("can_leak", True):
        lsel = "none"
    elif leak in LEAK_SELECTORS and leak not in by_id:
        lsel = str(leak)
    else:
        d = by_id.get(str(leak))
        if d is None:
            lsel = "none"
        elif int(d["recipient_count"]) == max_rec and max_rec > min_rec:
            lsel = "most_recipients"
        elif int(d["age_days"]) == min_age and min_age < max_age:
            lsel = "newest"
        elif int(d["age_days"]) == max_age and max_age > min_age:
            lsel = "oldest"
        elif int(d["recipient_count"]) == min_rec and min_rec < max_rec:
            lsel = "fewest_recipients"
        else:
            lsel = "most_recipients" if int(d["recipient_count"]) >= 10 else "random_seeded"
    peers = set(mv.get("peers") or ())
    rpeers = set(mv.get("restricted_peers") or ())
    if not frame or frame == "none":
        fsel = "none"
    elif frame in FRAME_SELECTORS and frame not in peers and frame != mv.get("decoy"):
        fsel = str(frame)
    elif frame == mv.get("decoy"):
        fsel = "decoy"
    elif frame in rpeers:
        fsel = "most_restricted_peer"
    else:
        fsel = "random_peer"
    trap_only = bool(mv.get("i_am_restricted")) or max_rec <= 8 or not bool(mv.get("can_leak", True))
    return lsel, fsel, trap_only


def cap_trap_none_rows(
    active_rows: list[dict],
    trap_none_rows: list[dict],
    max_none_share: float = MAX_NONE_SHARE,
) -> list[dict]:
    if max_none_share <= 0.0 or not active_rows:
        return list(active_rows)
    if max_none_share >= 1.0:
        return list(active_rows) + list(trap_none_rows)
    max_k = int((max_none_share * len(active_rows)) / (1.0 - max_none_share))
    while max_k > 0 and (max_k / (len(active_rows) + max_k)) > max_none_share + 1e-12:
        max_k -= 1
    return list(active_rows) + list(trap_none_rows[:max_k])


def _iter_git_decision_lines(repo: str | Path, git_ref: str) -> list[str]:
    repo_str = str(repo)
    bare = "/home/silas/momin/fleet/repos/agent-arena.git"
    candidates = [
        (repo_str, git_ref),
        (bare, git_ref),
        (bare, "refs/remotes/github/fr8/gemini/mole"),
        (repo_str, "refs/remotes/github/fr8/gemini/mole"),
        (repo_str, "refs/remotes/origin/fr8/gemini/mole"),
        (repo_str, "origin/fr8/gemini/mole"),
        (bare, "refs/wip/fr8/gemini/mole"),
    ]
    chosen_repo, chosen_ref, files = None, None, []
    for gr, rf in candidates:
        if not rf or not os.path.exists(gr):
            continue
        try:
            out = subprocess.check_output(
                ["git", "-C", gr, "ls-tree", "-r", "--name-only", rf, "results/gemini_roles/adaptive_mole"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).splitlines()
            dec = sorted(x for x in out if x.endswith("mole_decisions.jsonl"))
            if dec:
                chosen_repo, chosen_ref, files = gr, rf, dec
                break
        except Exception:
            continue
    if not chosen_repo or not chosen_ref:
        return []
    lines: list[str] = []
    for f in files:
        txt = subprocess.check_output(["git", "-C", chosen_repo, "show", f"{chosen_ref}:{f}"], text=True)
        lines.extend(txt.splitlines())
    return lines


def _iter_dir_decision_lines(jsonl_dir: str | Path) -> list[str]:
    root = Path(jsonl_dir)
    if root.is_file():
        files = [root]
    else:
        files = sorted(root.rglob("*.jsonl"))
    lines: list[str] = []
    for f in files:
        lines.extend(f.read_text(encoding="utf-8").splitlines())
    return lines


def extract_carbon_sft(
    repo: str | Path = ".",
    git_ref: str = "refs/remotes/github/fr8/gemini/mole",
    jsonl_dir: str | Path | None = None,
    max_none_share: float = MAX_NONE_SHARE,
) -> list[dict]:
    raw_lines = (
        _iter_dir_decision_lines(jsonl_dir)
        if jsonl_dir is not None
        else _iter_git_decision_lines(repo, git_ref)
    )
    active_rows: list[dict] = []
    trap_none_rows: list[dict] = []
    for ln in raw_lines:
        if not ln.strip():
            continue
        r = json.loads(ln)
        if "seed" in r and r["seed"] is not None:
            guard_train_seed(int(r["seed"]))
        if r.get("error"):
            continue
        mv = r.get("mole_view")
        if isinstance(mv, str):
            mv = json.loads(mv)
        if not isinstance(mv, dict):
            continue
        docs = mv.get("held_docs") if mv.get("held_docs") is not None else mv.get("docs")
        if not docs:
            continue
        lsel, fsel, trap_only = map_carbon_turn({**r, "mole_view": mv})
        rec = {
            "prompt": render_dict_view(mv),
            "target": json.dumps({"leak": lsel, "frame": fsel}),
            "action": [lsel, fsel],
            "source": "gemini-4-carbon",
            "seed": int(r.get("seed", 0)),
            "day": int(mv.get("day", r.get("day", 1))),
            "trap_only": bool(trap_only),
        }
        if lsel == "none":
            if trap_only:
                trap_none_rows.append(rec)
        else:
            active_rows.append(rec)
    return cap_trap_none_rows(active_rows, trap_none_rows, max_none_share=max_none_share)


class RecorderMole:
    def __init__(self, base, views: list[MoleView]):
        self.base = base
        self.views = views

    def decide(self, view: MoleView, rng: random.Random) -> dict:
        self.views.append(view)
        return self.base.decide(view, rng)


class HorizonOverrideMole:
    def __init__(self, base, start_day: int, horizon: int, action: tuple[str, str]):
        self.base = base
        self.start_day = start_day
        self.horizon = horizon
        self.action = action

    def decide(self, view: MoleView, rng: random.Random) -> dict:
        if self.start_day <= view.day < self.start_day + self.horizon:
            return {
                "leak": _select_leak(self.action[0], view, rng),
                "frame": _select_frame(self.action[1], view, rng),
            }
        return self.base.decide(view, rng)


def score_candidate_task(task) -> dict:
    seed, day, tier, horizon, act = task
    guard_counterfactual_seed(seed)
    ov = HorizonOverrideMole(DEFAULT_STRATEGY, day, horizon, act)
    res = {}
    for ag in ("solver",) + INVESTIGATORS:
        r = run_episode(Env(tier, seed, mole_strategy=ov), _agent(ag, tier, seed))
        res[ag] = (float(r.score), bool(r.correct))
    regret = res["solver"][0] - max(res[a][0] for a in INVESTIGATORS)
    return {
        "action": list(act),
        "regret": regret,
        "solver_score": res["solver"][0],
        "solver_correct": res["solver"][1],
        "inv": {a: res[a][0] for a in INVESTIGATORS},
    }


def collect_env_prompts_and_expert(
    n_prompts: int,
    n_expert_states: int = 0,
    workers: int = 1,
    seed: int = 0,
    seed_base: int = COUNTERFACTUAL_SEED_BASE,
    tier: str = "hard",
) -> tuple[list[dict], list[dict]]:
    guard_counterfactual_seed(seed_base)
    rng = random.Random(seed)
    prompts: list[dict] = []
    s = int(seed_base)
    total_needed = max(0, int(n_prompts))
    while len(prompts) < total_needed:
        guard_counterfactual_seed(s)
        views: list[MoleView] = []
        run_episode(Env(tier, s, mole_strategy=RecorderMole(DEFAULT_STRATEGY, views)), SolverPolicy(tier))
        good = [v for v in views if v.docs and v.can_leak]
        if good:
            v = rng.choice(good)
            prompts.append({"seed": s, "day": v.day, "tier": tier, "prompt": render_view(v)})
        s += 1

    n_exp = min(max(0, int(n_expert_states)), len(prompts))
    if n_exp == 0:
        return prompts, []

    expert_states = prompts[:n_exp]
    tasks = [
        (st["seed"], st["day"], st["tier"], 3, act)
        for st in expert_states
        for act in CANDIDATE_EXPERT_ACTIONS
    ]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            scored = list(ex.map(score_candidate_task, tasks))
    else:
        scored = [score_candidate_task(t) for t in tasks]

    expert_sft: list[dict] = []
    k = len(CANDIDATE_EXPERT_ACTIONS)
    for idx, st in enumerate(expert_states):
        chunk = scored[idx * k : (idx + 1) * k]
        catchable = [c for c in chunk if c["solver_correct"] and c["solver_score"] >= 0.25]
        if not catchable:
            continue
        best = max(catchable, key=lambda c: c["regret"])
        expert_sft.append(
            {
                "prompt": st["prompt"],
                "target": json.dumps({"leak": best["action"][0], "frame": best["action"][1]}),
                "action": best["action"],
                "source": "counterfactual_expert",
                "seed": st["seed"],
                "day": st["day"],
                "trap_only": False,
            }
        )
    return prompts[n_exp:], expert_sft


def apply_chat(tok, messages: list[dict], add_gen: bool = True) -> str:
    try:
        return tok.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=add_gen,
            enable_thinking=False,
        )
    except TypeError:
        return tok.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=add_gen,
        )


def chat_prompt(tok, user_prompt: str, system_prompt: str = SYSTEM) -> str:
    return apply_chat(
        tok,
        [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        add_gen=True,
    )


class TinyByteTokenizer:
    vocab_size = 512

    def __init__(self):
        self.pad_token = "<pad>"
        self.eos_token = "<eos>"
        self.pad_token_id = 0
        self.eos_token_id = 2
        self.padding_side = "left"

    def __len__(self) -> int:
        return self.vocab_size

    def apply_chat_template(
        self,
        messages: list[dict],
        tokenize: bool = False,
        add_generation_prompt: bool = False,
        enable_thinking: bool = False,
    ) -> str:
        _ = (tokenize, enable_thinking)
        parts = [f"<{m['role']}>{m['content']}</{m['role']}>" for m in messages]
        if add_generation_prompt:
            parts.append("<assistant>")
        return "\n".join(parts)

    def _encode_one(self, text: str) -> list[int]:
        return [b + 4 for b in text.encode("utf-8")[:512]]

    def __call__(
        self,
        texts: str | list[str],
        return_tensors: str | None = None,
        padding: bool = False,
        add_special_tokens: bool = False,
    ):
        _ = add_special_tokens
        if isinstance(texts, str):
            ids = self._encode_one(texts) or [4]
            if return_tensors == "pt":
                import torch

                return self._to_batch_tensors(torch, [ids], padding=False)
            return {"input_ids": ids, "attention_mask": [1] * len(ids)}
        encoded = [self._encode_one(t) or [4] for t in texts]
        if return_tensors == "pt":
            import torch

            return self._to_batch_tensors(torch, encoded, padding=padding)
        return {"input_ids": encoded, "attention_mask": [[1] * len(x) for x in encoded]}

    def _to_batch_tensors(self, torch_mod, seqs: list[list[int]], padding: bool):
        max_l = max(len(x) for x in seqs)
        inp = []
        att = []
        for x in seqs:
            pad_n = (max_l - len(x)) if padding else 0
            if self.padding_side == "left":
                inp.append([self.pad_token_id] * pad_n + x)
                att.append([0] * pad_n + [1] * len(x))
            else:
                inp.append(x + [self.pad_token_id] * pad_n)
                att.append([1] * len(x) + [0] * pad_n)
        t_inp = torch_mod.tensor(inp, dtype=torch_mod.long)
        t_att = torch_mod.tensor(att, dtype=torch_mod.long)

        class _Batch(dict):
            def to(self, dev):
                return _Batch({k: v.to(dev) for k, v in self.items()})

        return _Batch({"input_ids": t_inp, "attention_mask": t_att})

    def decode(self, ids, skip_special_tokens: bool = True) -> str:
        raw = ids.tolist() if hasattr(ids, "tolist") else list(ids)
        bs = bytes(
            x - 4
            for x in raw
            if isinstance(x, int) and 4 <= x < 260 and (not skip_special_tokens or x not in (0, 2))
        )
        return bs.decode("utf-8", errors="ignore")

    def batch_decode(self, batch_ids, skip_special_tokens: bool = True) -> list[str]:
        return [self.decode(row, skip_special_tokens=skip_special_tokens) for row in batch_ids]

    def save_pretrained(self, out_dir: str | Path) -> None:
        p = Path(out_dir)
        p.mkdir(parents=True, exist_ok=True)
        (p / "tokenizer_config.json").write_text(
            json.dumps({"tokenizer_class": "TinyByteTokenizer"}),
            encoding="utf-8",
        )


def load_base_model(
    path: str,
    device: str | None = None,
    tiny: bool = False,
    adapter_dir: str | None = None,
    tokenizer=None,
):
    import torch
    from peft import LoraConfig, PeftModel, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer, Qwen2Config, Qwen2ForCausalLM

    resolved = resolve_model_path(path, adapter_dir)
    if device is None:
        device = "cuda" if (torch.cuda.is_available() and not tiny) else "cpu"
    if tokenizer is not None:
        tok = tokenizer
    elif tiny and (resolved == "tiny-synthetic" or not os.path.isdir(resolved)):
        tok = TinyByteTokenizer()
    else:
        tok = AutoTokenizer.from_pretrained(resolved)
    tok.padding_side = "left"
    if getattr(tok, "pad_token", None) is None:
        tok.pad_token = tok.eos_token

    if tiny:
        vsize = max(len(tok), 512) if isinstance(tok, TinyByteTokenizer) else max(len(tok), 151936)
        cfg = Qwen2Config(
            vocab_size=vsize,
            hidden_size=32 if isinstance(tok, TinyByteTokenizer) else 64,
            intermediate_size=64 if isinstance(tok, TinyByteTokenizer) else 128,
            num_hidden_layers=1 if isinstance(tok, TinyByteTokenizer) else 2,
            num_attention_heads=2 if isinstance(tok, TinyByteTokenizer) else 4,
            num_key_value_heads=1 if isinstance(tok, TinyByteTokenizer) else 2,
            max_position_embeddings=1024 if isinstance(tok, TinyByteTokenizer) else 2048,
        )
        torch.manual_seed(0)
        base = Qwen2ForCausalLM(cfg)
    else:
        dt = torch.float16 if device == "cuda" else torch.float32
        try:
            base = AutoModelForCausalLM.from_pretrained(resolved, dtype=dt)
        except TypeError:
            base = AutoModelForCausalLM.from_pretrained(resolved, torch_dtype=dt)
    base.config.use_cache = False
    lcfg = LoraConfig(
        r=8 if tiny else 16,
        lora_alpha=16 if tiny else 32,
        lora_dropout=0.05,
        target_modules=TARGETS,
        task_type="CAUSAL_LM",
    )
    if adapter_dir and Path(adapter_dir).is_dir():
        model = PeftModel.from_pretrained(base, str(adapter_dir), is_trainable=True)
    else:
        model = get_peft_model(base, lcfg)
    for p in model.parameters():
        if p.requires_grad:
            p.data = p.data.float()
    model.to(device)
    return model, tok, lcfg, device


def save_single_adapter(model, tok, dst: Path, base_model_path: str) -> Path:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "ckpt"
        try:
            model.save_pretrained(tmp, selected_adapters=["default"])
        except TypeError:
            model.save_pretrained(tmp)
        src = tmp / "default" if (tmp / "default").is_dir() else tmp
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    cfg_file = dst / "adapter_config.json"
    if cfg_file.is_file():
        acfg = json.loads(cfg_file.read_text(encoding="utf-8"))
        acfg["base_model_name_or_path"] = base_model_path
        cfg_file.write_text(json.dumps(acfg, indent=2), encoding="utf-8")
    if tok is not None and hasattr(tok, "save_pretrained"):
        tok.save_pretrained(dst)
    return dst


def run_sft(
    model,
    tok,
    sft_rows: list[dict],
    device: str,
    epochs: int = 3,
    batch_size: int = 8,
    lr: float = 2e-4,
    log_path: Path | None = None,
    seed: int = 42,
) -> list[dict]:
    import torch

    rng = random.Random(seed)
    encoded: list[tuple[list[int], list[int]]] = []
    for r in sft_rows:
        p_txt = apply_chat(
            tok,
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": r["prompt"]}],
            add_gen=True,
        )
        full_txt = apply_chat(
            tok,
            [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": r["prompt"]},
                {"role": "assistant", "content": r["target"]},
            ],
            add_gen=False,
        )
        p_ids = tok(p_txt, add_special_tokens=False)["input_ids"]
        f_ids = tok(full_txt, add_special_tokens=False)["input_ids"]
        if len(f_ids) <= len(p_ids):
            continue
        labels = [-100] * len(p_ids) + list(f_ids[len(p_ids) :])
        encoded.append((list(f_ids[:1024]), labels[:1024]))

    if not encoded:
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("", encoding="utf-8")
        return []

    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=lr, weight_decay=0.01)
    use_amp = device == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
    model.train()
    step = 0
    t0 = time.time()
    sft_curve: list[dict] = []
    pad_id = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id
    for ep in range(epochs):
        rng.shuffle(encoded)
        for i in range(0, len(encoded), batch_size):
            batch = encoded[i : i + batch_size]
            max_l = max(len(x[0]) for x in batch)
            inp = torch.full((len(batch), max_l), pad_id, dtype=torch.long, device=device)
            lab = torch.full((len(batch), max_l), -100, dtype=torch.long, device=device)
            att = torch.zeros((len(batch), max_l), dtype=torch.long, device=device)
            for bi, (ids, lbs) in enumerate(batch):
                inp[bi, : len(ids)] = torch.tensor(ids, dtype=torch.long, device=device)
                lab[bi, : len(lbs)] = torch.tensor(lbs, dtype=torch.long, device=device)
                att[bi, : len(ids)] = 1
            opt.zero_grad(set_to_none=True)
            with torch.autocast(
                device_type="cuda" if use_amp else "cpu",
                dtype=torch.float16,
                enabled=use_amp,
            ):
                loss = model(input_ids=inp, attention_mask=att, labels=lab).loss
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            scaler.step(opt)
            scaler.update()
            step += 1
            if step % 15 == 0 or (ep == epochs - 1 and i + batch_size >= len(encoded)):
                rec = {
                    "epoch": ep + 1,
                    "step": step,
                    "loss": round(float(loss.item()), 4),
                    "sec": round(time.time() - t0, 1),
                }
                sft_curve.append(rec)
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("".join(json.dumps(x) + "\n" for x in sft_curve), encoding="utf-8")
    return sft_curve


class QwenMolePolicy:
    def __init__(
        self,
        model=None,
        tok=None,
        device: str = "cpu",
        max_new: int = 24,
        system_prompt: str = SYSTEM,
        fallback: tuple[str, str] = ("random_seeded", "none"),
        generate_fn=None,
    ):
        self.model = model
        self.tok = tok
        self.device = device
        self.max_new = max_new
        self.system_prompt = system_prompt
        self.fallback = fallback
        self.generate_fn = generate_fn
        self.cache: dict[str, tuple[str, str]] = {}
        self.invalid = 0
        self.calls = 0
        self.actions: list[tuple[str, str]] = []

    def _generate_completion(self, prompt: str) -> str:
        if self.generate_fn is not None:
            return self.generate_fn(prompt)
        import torch

        txt_in = apply_chat(
            self.tok,
            [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": prompt}],
            add_gen=True,
        )
        enc = self.tok(txt_in, return_tensors="pt", add_special_tokens=False).to(self.device)
        use_amp = self.device == "cuda"
        pad_id = self.tok.pad_token_id if self.tok.pad_token_id is not None else self.tok.eos_token_id
        self.model.eval()
        with torch.no_grad(), torch.autocast(
            device_type="cuda" if use_amp else "cpu",
            dtype=torch.float16,
            enabled=use_amp,
        ):
            gen = self.model.generate(
                **enc,
                max_new_tokens=self.max_new,
                do_sample=False,
                pad_token_id=pad_id,
                use_cache=True,
            )
        return self.tok.decode(gen[0, enc["input_ids"].shape[1] :], skip_special_tokens=True)

    def decide(self, view: MoleView, rng: random.Random) -> dict:
        prompt = render_view(view)
        act = self.cache.get(prompt)
        if act is None:
            self.calls += 1
            out_txt = self._generate_completion(prompt)
            parsed = parse_action(out_txt)
            if parsed is None:
                self.invalid += 1
                act = self.fallback
            else:
                act = parsed
            self.cache[prompt] = act
        self.actions.append(act)
        return {
            "leak": _select_leak(act[0], view, rng),
            "frame": _select_frame(act[1], view, rng),
        }


def eval_full_episodes(
    model,
    tok,
    device: str,
    seeds: list[int],
    tier: str = "hard",
    generate_fn=None,
) -> tuple[list[dict], dict]:
    qpol = QwenMolePolicy(model, tok, device, generate_fn=generate_fn)
    has_cfg = model is not None and hasattr(model, "config")
    was_uc = getattr(model.config, "use_cache", False) if has_cfg else False
    if has_cfg:
        model.config.use_cache = True
    merged_temp = False
    if model is not None and hasattr(model, "merge_adapter") and hasattr(model, "unmerge_adapter"):
        try:
            model.merge_adapter()
            merged_temp = True
        except Exception:
            merged_temp = False
    rows: list[dict] = []
    t0 = time.time()
    try:
        for s in seeds:
            row = {}
            for ag in ("solver",) + INVESTIGATORS:
                r = run_episode(Env(tier, s, mole_strategy=qpol), _agent(ag, tier, s))
                row[ag] = (float(r.score), bool(r.correct))
            rows.append(row)
    finally:
        if merged_temp:
            model.unmerge_adapter()
        if has_cfg:
            model.config.use_cache = was_uc
    n = max(1, len(rows))
    summ: dict = {
        ag: {
            "score": round(sum(r[ag][0] for r in rows) / n, 4),
            "acc": round(sum(r[ag][1] for r in rows) / n, 4),
        }
        for ag in ("solver",) + INVESTIGATORS
    }
    summ["min_regret"] = round(summ["solver"]["score"] - max(summ[a]["score"] for a in INVESTIGATORS), 4)
    summ["strongest_inv"] = max(INVESTIGATORS, key=lambda a: summ[a]["score"])
    summ["catchable_85"] = summ["solver"]["acc"] >= MIN_SOLVER_ACC
    ac = Counter(qpol.actions)
    tot_a = sum(ac.values()) or 1
    probs = [v / tot_a for v in ac.values()]
    ent = -sum(p * math.log(p + 1e-12) for p in probs)
    summ["distinct_actions"] = len(ac)
    summ["action_entropy_nats"] = round(ent, 4)
    summ["action_profile"] = {"/".join(k): round(v / tot_a, 4) for k, v in ac.most_common(10)}
    summ["unique_prompts_generated"] = qpol.calls
    summ["invalid_generations"] = qpol.invalid
    summ["eval_sec"] = round(time.time() - t0, 1)
    return rows, summ


def grpo_reward_task(task) -> dict:
    row, text, lam_catch = task
    act = parse_action(text)
    if act is None:
        return {"reward": -1.0, "valid": False}
    ov = HorizonOverrideMole(DEFAULT_STRATEGY, int(row["day"]), 3, act)
    res = {}
    tier = row.get("tier", "hard")
    seed = int(row["seed"])
    for ag in ("solver",) + INVESTIGATORS:
        r = run_episode(Env(tier, seed, mole_strategy=ov), _agent(ag, tier, seed))
        res[ag] = (float(r.score), bool(r.correct))
    regret = res["solver"][0] - max(res[a][0] for a in INVESTIGATORS)
    catch_term = 0.15 if res["solver"][1] else -float(lam_catch)
    none_pen = -0.20 if act[0] == "none" else 0.0
    return {
        "reward": regret + catch_term + none_pen,
        "regret": regret,
        "valid": True,
        "action": list(act),
        "solver": res["solver"],
        "inv": {a: res[a][0] for a in INVESTIGATORS},
    }


def apply_batch_diversity_penalty(
    results: list[dict],
    freq_cap: float = ACTION_FREQ_CAP,
    penalty_scale: float = ACTION_FREQ_PENALTY_SCALE,
) -> tuple[list[float], Counter]:
    act_counts: Counter = Counter(tuple(r["action"]) for r in results if r.get("valid"))
    n_res = max(1, len(results))
    adj_rewards: list[float] = []
    for r in results:
        rw = float(r["reward"])
        if r.get("valid"):
            freq = act_counts[tuple(r["action"])] / n_res
            if freq > freq_cap:
                rw -= penalty_scale * (freq - freq_cap)
        adj_rewards.append(rw)
    return adj_rewards, act_counts


def compute_group_advantages(adj_rewards: list[float], group: int, eps: float = 1e-4) -> list[float]:
    if group <= 0 or len(adj_rewards) % group != 0:
        raise ValueError(f"len(adj_rewards)={len(adj_rewards)} must be divisible by group={group}")
    adv: list[float] = []
    for i in range(0, len(adj_rewards), group):
        g = adj_rewards[i : i + group]
        mean = sum(g) / group
        if group > 1:
            var = sum((x - mean) ** 2 for x in g) / (group - 1)
            std = math.sqrt(var)
        else:
            std = 0.0
        denom = std + eps
        adv.extend((x - mean) / denom for x in g)
    return adv


def update_lam_catch(
    lam_catch: float,
    batch_solver_acc: float,
    target_acc: float = TARGET_SOLVER_ACC,
    step_size: float = 1.2,
    lo: float = 0.40,
    hi: float = 3.0,
) -> float:
    return max(lo, min(hi, float(lam_catch) + step_size * (target_acc - float(batch_solver_acc))))


def setup_sft_ref_adapter(model, lcfg) -> None:
    import torch

    model.add_adapter("sft_ref", lcfg)
    with torch.no_grad():
        sd = model.state_dict()
        for k, v in list(sd.items()):
            if ".default." in k:
                rk = k.replace(".default.", ".sft_ref.")
                if rk in sd:
                    sd[rk].copy_(v)
    model.set_adapter("default")
    for n, p in model.named_parameters():
        p.requires_grad = ".default." in n
        if p.requires_grad:
            p.data = p.data.float()


def seq_logprobs_and_entropy(model, full_ids, attn, prompt_len: int, comp_ids, cmask, use_amp: bool):
    import torch

    dev_type = "cuda" if use_amp else "cpu"
    with torch.autocast(device_type=dev_type, dtype=torch.float16, enabled=use_amp):
        logits = model(input_ids=full_ids, attention_mask=attn).logits
    step_logits = logits[:, prompt_len - 1 : -1].float()
    lp = torch.log_softmax(step_logits, dim=-1)
    probs = lp.exp()
    tok_ent = -(probs * lp).sum(dim=-1)
    tlp = lp.gather(-1, comp_ids.unsqueeze(-1)).squeeze(-1)
    denom = cmask.sum(1).clamp(min=1.0)
    seq_lp = (tlp * cmask).sum(1) / denom
    seq_ent = (tok_ent * cmask).sum(1) / denom
    return seq_lp, seq_ent


def select_winner_candidate(candidates: list[tuple[str, Path, dict]]) -> tuple[str, Path, dict]:
    feasible = [
        c
        for c in candidates
        if c[2]["solver"]["acc"] >= MIN_SOLVER_ACC and c[2]["distinct_actions"] >= 2
    ]
    if not feasible:
        feasible = [c for c in candidates if c[2]["solver"]["acc"] >= MIN_SOLVER_ACC]
    if feasible:
        return max(feasible, key=lambda c: (c[2]["min_regret"], c[2]["solver"]["acc"]))
    return max(candidates, key=lambda c: (c[2]["solver"]["acc"], c[2]["min_regret"]))


def run_grpo(
    model,
    tok,
    lcfg,
    grpo_prompts: list[dict],
    device: str,
    out_dir: Path,
    base_model_path: str,
    steps: int = 60,
    prompts_per_step: int = 3,
    group: int = 6,
    lr: float = 1.5e-5,
    beta_kl: float = 0.05,
    ent_coef: float = 0.015,
    lam_catch: float = 0.90,
    target_acc: float = TARGET_SOLVER_ACC,
    freq_cap: float = ACTION_FREQ_CAP,
    eval_every: int = 30,
    val_seeds: list[int] | None = None,
    tier: str = "hard",
    workers: int = 1,
    seed: int = 7,
) -> tuple[list[dict], tuple[str, Path, dict], list[tuple[str, Path, dict]]]:
    import torch

    for p in grpo_prompts:
        if "seed" in p and p["seed"] is not None:
            guard_counterfactual_seed(int(p["seed"]))

    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt_root = out_dir / "ckpts"
    ckpt_root.mkdir(parents=True, exist_ok=True)
    v_seeds = val_seeds if val_seeds is not None else list(range(VAL_SEED_BASE, VAL_SEED_BASE + 12))

    sft_ckpt = save_single_adapter(model, tok, ckpt_root / "ckpt_sft", base_model_path)
    _, val_sft = eval_full_episodes(model, tok, device, v_seeds, tier=tier)
    candidates: list[tuple[str, Path, dict]] = [("sft", sft_ckpt, val_sft)]

    setup_sft_ref_adapter(model, lcfg)
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=lr)
    use_amp = device == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
    rng = random.Random(seed)
    grpo_curve: list[dict] = []
    pad_id = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id
    ex = ProcessPoolExecutor(max_workers=workers) if workers > 1 else None

    try:
        for step in range(1, steps + 1):
            t0 = time.time()
            batch = rng.sample(grpo_prompts, min(prompts_per_step, len(grpo_prompts)))
            texts_in = [
                apply_chat(
                    tok,
                    [{"role": "system", "content": SYSTEM}, {"role": "user", "content": r["prompt"]}],
                    add_gen=True,
                )
                for r in batch
                for _ in range(group)
            ]
            rows_in = [r for r in batch for _ in range(group)]
            enc = tok(texts_in, return_tensors="pt", padding=True, add_special_tokens=False).to(device)
            p_len = enc["input_ids"].shape[1]

            model.eval()
            model.config.use_cache = True
            with torch.no_grad(), torch.autocast(
                device_type="cuda" if use_amp else "cpu",
                dtype=torch.float16,
                enabled=use_amp,
            ):
                gen = model.generate(
                    **enc,
                    max_new_tokens=24,
                    do_sample=True,
                    temperature=0.85,
                    top_p=0.95,
                    pad_token_id=pad_id,
                    use_cache=True,
                )
            model.config.use_cache = False
            comp = gen[:, p_len:]
            decoded = tok.batch_decode(comp, skip_special_tokens=True)

            tasks = [(r, txt, lam_catch) for r, txt in zip(rows_in, decoded)]
            results = list(ex.map(grpo_reward_task, tasks)) if ex else [grpo_reward_task(t) for t in tasks]

            adj_rewards, act_counts = apply_batch_diversity_penalty(results, freq_cap=freq_cap)
            adv_list = compute_group_advantages(adj_rewards, group=group)
            adv = torch.tensor(adv_list, dtype=torch.float32, device=device)

            attn = (gen != pad_id).long()
            attn[:, :p_len] = enc["attention_mask"]
            cmask = attn[:, p_len:].float()

            with torch.no_grad():
                model.set_adapter("sft_ref")
                ref_lp, _ = seq_logprobs_and_entropy(model, gen, attn, p_len, comp, cmask, use_amp)
                model.set_adapter("default")

            model.train()
            opt.zero_grad(set_to_none=True)
            mb = 6
            kl_vals: list[float] = []
            ent_vals: list[float] = []
            for i in range(0, gen.shape[0], mb):
                slp, sent = seq_logprobs_and_entropy(
                    model,
                    gen[i : i + mb],
                    attn[i : i + mb],
                    p_len,
                    comp[i : i + mb],
                    cmask[i : i + mb],
                    use_amp,
                )
                kl_approx = slp - ref_lp[i : i + mb]
                pg_obj = adv[i : i + mb] * slp - beta_kl * (kl_approx**2) * 0.5 + ent_coef * sent
                loss = -pg_obj.sum() / gen.shape[0]
                scaler.scale(loss).backward()
                kl_vals.append(float(kl_approx.abs().mean().item()))
                ent_vals.append(float(sent.mean().item()))
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            scaler.step(opt)
            scaler.update()

            valid = [r for r in results if r["valid"]]
            b_acc = (sum(r["solver"][1] for r in valid) / len(valid)) if valid else target_acc
            lam_catch = update_lam_catch(lam_catch, b_acc, target_acc=target_acc)
            rec = {
                "step": step,
                "reward": round(sum(adj_rewards) / max(1, len(adj_rewards)), 4),
                "mean_regret": round(sum(r["regret"] for r in valid) / len(valid), 4) if valid else None,
                "valid_rate": round(len(valid) / max(1, len(results)), 4),
                "batch_solver_acc": round(b_acc, 4),
                "lam_catch": round(lam_catch, 4),
                "abs_kl": round(sum(kl_vals) / max(1, len(kl_vals)), 4),
                "tok_ent": round(sum(ent_vals) / max(1, len(ent_vals)), 4),
                "top_actions": {"/".join(k): v for k, v in act_counts.most_common(5)},
                "sec": round(time.time() - t0, 1),
            }
            grpo_curve.append(rec)
            (out_dir / "grpo_curve.jsonl").write_text(
                "".join(json.dumps(x) + "\n" for x in grpo_curve),
                encoding="utf-8",
            )

            if eval_every > 0 and (step % eval_every == 0 or step == steps):
                ck = save_single_adapter(model, tok, ckpt_root / f"ckpt_grpo_{step}", base_model_path)
                _, vs = eval_full_episodes(model, tok, device, v_seeds, tier=tier)
                candidates.append((f"grpo_step{step}", ck, vs))
    finally:
        if ex is not None:
            ex.shutdown()

    winner = select_winner_candidate(candidates)
    adapter_out = out_dir / "adapter"
    if adapter_out.exists():
        shutil.rmtree(adapter_out)
    shutil.copytree(winner[1], adapter_out)
    return grpo_curve, (winner[0], adapter_out, winner[2]), candidates


def boot_ci(xs: list[float], B: int = 2000, seed: int = 0) -> list[float]:
    r = random.Random(seed)
    n = len(xs)
    ms = sorted(sum(xs[r.randrange(n)] for _ in range(n)) / n for _ in range(B))
    return [round(sum(xs) / n, 4), round(ms[int(0.025 * B)], 4), round(ms[int(0.975 * B)], 4)]


def paired_report(q_rows: list[dict], base_rows: list[dict], label: str) -> dict:
    ags = ("solver",) + INVESTIGATORS
    out: dict = {"comparison": label, "n": len(q_rows)}
    for nm, rs in (("qwen_mole", q_rows), ("baseline", base_rows)):
        out[nm] = {
            ag: {
                "score": boot_ci([x[ag][0] for x in rs]),
                "acc": boot_ci([float(x[ag][1]) for x in rs]),
            }
            for ag in ags
        }
        out[nm]["regret"] = {k: boot_ci([x["solver"][0] - x[k][0] for x in rs]) for k in INVESTIGATORS}
    out["diff_qwen_minus_baseline"] = {
        **{f"{ag}_score": boot_ci([y[ag][0] - x[ag][0] for x, y in zip(base_rows, q_rows)]) for ag in ags},
        "solver_acc": boot_ci([float(y["solver"][1]) - float(x["solver"][1]) for x, y in zip(base_rows, q_rows)]),
        **{
            f"regret_{k}": boot_ci(
                [(y["solver"][0] - y[k][0]) - (x["solver"][0] - x[k][0]) for x, y in zip(base_rows, q_rows)]
            )
            for k in INVESTIGATORS
        },
    }
    return out


def cmd_extract_sft(a) -> dict:
    carbon_rows = extract_carbon_sft(
        repo=a.repo,
        git_ref=a.git_ref,
        jsonl_dir=a.jsonl_dir,
        max_none_share=a.max_none_share,
    )
    grpo_prompts: list[dict] = []
    expert_rows: list[dict] = []
    total_env = a.n_counterfactual + a.n_grpo_prompts
    if total_env > 0:
        grpo_prompts, expert_rows = collect_env_prompts_and_expert(
            n_prompts=total_env,
            n_expert_states=a.n_counterfactual,
            workers=a.workers,
            seed=a.seed,
            seed_base=a.seed_base,
            tier=a.tier,
        )
    sft_rows = carbon_rows + expert_rows * max(1, a.expert_repeat)
    out_p = Path(a.out)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text("".join(json.dumps(r) + "\n" for r in sft_rows), encoding="utf-8")
    if a.prompts_out and grpo_prompts:
        pp = Path(a.prompts_out)
        pp.parent.mkdir(parents=True, exist_ok=True)
        pp.write_text("".join(json.dumps(r) + "\n" for r in grpo_prompts), encoding="utf-8")
    none_cnt = sum(1 for r in carbon_rows if r["action"][0] == "none")
    meta = {
        "carbon_rows": len(carbon_rows),
        "carbon_none_share": round(none_cnt / max(1, len(carbon_rows)), 4),
        "counterfactual_rows": len(expert_rows),
        "total_sft_rows": len(sft_rows),
        "grpo_prompts": len(grpo_prompts),
        "out": str(out_p),
    }
    print(json.dumps(meta), flush=True)
    return meta


def cmd_sft(a) -> dict:
    rows = [
        json.loads(ln)
        for ln in Path(a.data).read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    resolved = resolve_model_path(a.model)
    model, tok, _, device = load_base_model(resolved, tiny=a.tiny)
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    curve = run_sft(
        model,
        tok,
        rows,
        device=device,
        epochs=a.epochs,
        batch_size=a.batch_size,
        lr=a.lr,
        log_path=out_dir / "sft_curve.jsonl",
        seed=a.seed,
    )
    adapter_dir = save_single_adapter(model, tok, out_dir / "adapter", resolved)
    meta = {"adapter_dir": str(adapter_dir), "steps": len(curve), "rows": len(rows), "device": device}
    print(json.dumps(meta), flush=True)
    return meta


def cmd_grpo(a) -> dict:
    resolved = resolve_model_path(a.model, a.sft_adapter)
    model, tok, lcfg, device = load_base_model(resolved, tiny=a.tiny, adapter_dir=a.sft_adapter)
    if a.prompts:
        prompts = [
            json.loads(ln)
            for ln in Path(a.prompts).read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
    else:
        prompts, _ = collect_env_prompts_and_expert(
            n_prompts=a.n_prompts,
            n_expert_states=0,
            workers=a.workers,
            seed=a.seed,
            seed_base=a.seed_base,
            tier=a.tier,
        )
    v_seeds = list(range(VAL_SEED_BASE, VAL_SEED_BASE + a.val_seeds))
    out_dir = Path(a.out)
    curve, (winner_name, adapter_dir, winner_val), _ = run_grpo(
        model=model,
        tok=tok,
        lcfg=lcfg,
        grpo_prompts=prompts,
        device=device,
        out_dir=out_dir,
        base_model_path=resolved,
        steps=a.steps,
        prompts_per_step=a.prompts_per_step,
        group=a.group,
        lr=a.lr,
        beta_kl=a.beta_kl,
        ent_coef=a.ent_coef,
        lam_catch=a.lam_catch,
        target_acc=a.target_acc,
        freq_cap=a.freq_cap,
        eval_every=a.eval_every,
        val_seeds=v_seeds,
        tier=a.tier,
        workers=a.workers,
        seed=a.seed,
    )
    meta = {
        "winner": winner_name,
        "adapter_dir": str(adapter_dir),
        "val": winner_val,
        "steps": len(curve),
    }
    (out_dir / "grpo_summary.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta), flush=True)
    return meta


def cmd_all(a) -> dict:
    t0 = time.time()
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    carbon_rows = extract_carbon_sft(
        repo=a.repo,
        git_ref=a.git_ref,
        jsonl_dir=a.jsonl_dir,
        max_none_share=a.max_none_share,
    )
    grpo_prompts, expert_rows = collect_env_prompts_and_expert(
        n_prompts=a.n_prompts,
        n_expert_states=a.n_counterfactual,
        workers=a.workers,
        seed=a.seed,
        seed_base=a.seed_base,
        tier=a.tier,
    )
    if a.tiny:
        carbon_rows = carbon_rows[:16]
    sft_rows = carbon_rows + expert_rows * (1 if a.tiny else 2)
    (out_dir / "sft_dataset.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in sft_rows),
        encoding="utf-8",
    )

    resolved = resolve_model_path(a.model)
    model, tok, lcfg, device = load_base_model(resolved, tiny=a.tiny)
    run_sft(
        model=model,
        tok=tok,
        sft_rows=sft_rows,
        device=device,
        epochs=a.sft_epochs,
        batch_size=a.sft_batch_size,
        lr=a.sft_lr,
        log_path=out_dir / "sft_curve.jsonl",
        seed=42,
    )
    v_seeds = list(range(VAL_SEED_BASE, VAL_SEED_BASE + a.val_seeds))
    _, (winner_name, adapter_dir, winner_val), candidates = run_grpo(
        model=model,
        tok=tok,
        lcfg=lcfg,
        grpo_prompts=grpo_prompts,
        device=device,
        out_dir=out_dir,
        base_model_path=resolved,
        steps=a.grpo_steps,
        prompts_per_step=a.prompts_per_step,
        group=a.group,
        lr=a.grpo_lr,
        beta_kl=a.beta_kl,
        ent_coef=a.ent_coef,
        lam_catch=a.lam_catch,
        target_acc=a.target_acc,
        freq_cap=a.freq_cap,
        eval_every=a.eval_every,
        val_seeds=v_seeds,
        tier=a.tier,
        workers=a.workers,
        seed=7,
    )

    summary: dict = {
        "model": resolved,
        "tiny": bool(a.tiny),
        "winner_checkpoint": winner_name,
        "total_seconds": round(time.time() - t0, 1),
        "sft_examples": {
            "carbon_transcripts": len(carbon_rows),
            "counterfactual_expert": len(expert_rows),
            "total": len(sft_rows),
        },
        "val_candidates": {nm: vs for nm, _, vs in candidates},
        "adapter_dir": str(adapter_dir),
    }

    if a.heldout_seeds > 0:
        seeds_800k = list(range(800_000, 800_000 + a.heldout_seeds))
        seeds_200k = list(range(200_000, 200_000 + a.heldout_seeds))
        q_800k, sum_800k = eval_full_episodes(model, tok, device, seeds_800k)
        q_200k, sum_200k = eval_full_episodes(model, tok, device, seeds_200k)
        d_800k = [_default_rollout((None, "hard", s)) for s in seeds_800k]
        d_200k = [_default_rollout((None, "hard", s)) for s in seeds_200k]
        rl_pol_path = Path(a.repo) / "data" / "rl_mole" / "policy_final.json"
        if rl_pol_path.is_file():
            rl_pol = RLMole.from_json(json.loads(rl_pol_path.read_text(encoding="utf-8")))
            ags = ("solver",) + INVESTIGATORS
            r_200k = [rl_rollout((rl_pol.p, "hard", s, ags, False)) for s in seeds_200k]
        else:
            r_200k = None
        summary["heldout_800k_summary"] = sum_800k
        summary["heldout_200k_summary"] = sum_200k
        summary["paired_800k_vs_default"] = paired_report(q_800k, d_800k, "qwen_vs_default_800k")
        summary["paired_200k_vs_default"] = paired_report(q_200k, d_200k, "qwen_vs_default_200k")
        summary["paired_200k_vs_rl_mole"] = (
            paired_report(q_200k, r_200k, "qwen_vs_rl_mole_200k") if r_200k else None
        )

    (out_dir / "eval_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary), flush=True)
    return summary


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="train.qwen_diverse_mole")
    sub = ap.add_subparsers(dest="subcommand", required=True)

    p_ext = sub.add_parser("extract-sft")
    p_ext.add_argument("--repo", default=".")
    p_ext.add_argument("--git-ref", default="refs/remotes/github/fr8/gemini/mole")
    p_ext.add_argument("--jsonl-dir", default=None)
    p_ext.add_argument("--max-none-share", type=float, default=MAX_NONE_SHARE)
    p_ext.add_argument("--n-counterfactual", type=int, default=0)
    p_ext.add_argument("--n-grpo-prompts", type=int, default=0)
    p_ext.add_argument("--seed-base", type=int, default=COUNTERFACTUAL_SEED_BASE)
    p_ext.add_argument("--tier", default="hard")
    p_ext.add_argument("--expert-repeat", type=int, default=1)
    p_ext.add_argument("--workers", type=int, default=1)
    p_ext.add_argument("--seed", type=int, default=0)
    p_ext.add_argument("--out", required=True)
    p_ext.add_argument("--prompts-out", default=None)
    p_ext.set_defaults(func=cmd_extract_sft)

    p_sft = sub.add_parser("sft")
    p_sft.add_argument("--model", default="Qwen/Qwen2.5-1.5B-Instruct")
    p_sft.add_argument("--data", required=True)
    p_sft.add_argument("--out", required=True)
    p_sft.add_argument("--epochs", type=int, default=3)
    p_sft.add_argument("--batch-size", type=int, default=8)
    p_sft.add_argument("--lr", type=float, default=2e-4)
    p_sft.add_argument("--tiny", action="store_true")
    p_sft.add_argument("--seed", type=int, default=42)
    p_sft.set_defaults(func=cmd_sft)

    p_grpo = sub.add_parser("grpo")
    p_grpo.add_argument("--model", default="Qwen/Qwen2.5-1.5B-Instruct")
    p_grpo.add_argument("--sft-adapter", default=None)
    p_grpo.add_argument("--prompts", default=None)
    p_grpo.add_argument("--n-prompts", type=int, default=60)
    p_grpo.add_argument("--seed-base", type=int, default=COUNTERFACTUAL_SEED_BASE)
    p_grpo.add_argument("--tier", default="hard")
    p_grpo.add_argument("--out", required=True)
    p_grpo.add_argument("--steps", type=int, default=60)
    p_grpo.add_argument("--prompts-per-step", type=int, default=3)
    p_grpo.add_argument("--group", type=int, default=6)
    p_grpo.add_argument("--lr", type=float, default=1.5e-5)
    p_grpo.add_argument("--beta-kl", type=float, default=0.05)
    p_grpo.add_argument("--ent-coef", type=float, default=0.015)
    p_grpo.add_argument("--lam-catch", type=float, default=0.90)
    p_grpo.add_argument("--target-acc", type=float, default=TARGET_SOLVER_ACC)
    p_grpo.add_argument("--freq-cap", type=float, default=ACTION_FREQ_CAP)
    p_grpo.add_argument("--eval-every", type=int, default=30)
    p_grpo.add_argument("--val-seeds", type=int, default=12)
    p_grpo.add_argument("--workers", type=int, default=1)
    p_grpo.add_argument("--tiny", action="store_true")
    p_grpo.add_argument("--seed", type=int, default=7)
    p_grpo.set_defaults(func=cmd_grpo)

    p_all = sub.add_parser("all")
    p_all.add_argument("--repo", default=".")
    p_all.add_argument("--git-ref", default="refs/remotes/github/fr8/gemini/mole")
    p_all.add_argument("--jsonl-dir", default=None)
    p_all.add_argument("--model", default="Qwen/Qwen2.5-1.5B-Instruct")
    p_all.add_argument("--out", required=True)
    p_all.add_argument("--max-none-share", type=float, default=MAX_NONE_SHARE)
    p_all.add_argument("--n-prompts", type=int, default=220)
    p_all.add_argument("--n-counterfactual", type=int, default=90)
    p_all.add_argument("--seed-base", type=int, default=COUNTERFACTUAL_SEED_BASE)
    p_all.add_argument("--tier", default="hard")
    p_all.add_argument("--sft-epochs", type=int, default=3)
    p_all.add_argument("--sft-batch-size", type=int, default=8)
    p_all.add_argument("--sft-lr", type=float, default=2e-4)
    p_all.add_argument("--grpo-steps", type=int, default=60)
    p_all.add_argument("--prompts-per-step", type=int, default=3)
    p_all.add_argument("--group", type=int, default=6)
    p_all.add_argument("--grpo-lr", type=float, default=1.5e-5)
    p_all.add_argument("--beta-kl", type=float, default=0.05)
    p_all.add_argument("--ent-coef", type=float, default=0.015)
    p_all.add_argument("--lam-catch", type=float, default=0.90)
    p_all.add_argument("--target-acc", type=float, default=TARGET_SOLVER_ACC)
    p_all.add_argument("--freq-cap", type=float, default=ACTION_FREQ_CAP)
    p_all.add_argument("--eval-every", type=int, default=30)
    p_all.add_argument("--val-seeds", type=int, default=12)
    p_all.add_argument("--heldout-seeds", type=int, default=0)
    p_all.add_argument("--workers", type=int, default=1)
    p_all.add_argument("--tiny", action="store_true")
    p_all.add_argument("--seed", type=int, default=0)
    p_all.set_defaults(func=cmd_all)

    return ap


def main(argv: list[str] | None = None):
    ap = build_parser()
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    main()
