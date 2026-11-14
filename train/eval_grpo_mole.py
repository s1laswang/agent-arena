from __future__ import annotations

import argparse
import inspect
import json
import math
import os
import random
import shutil
import tempfile
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from canary import rules
from canary.env import Env
from canary.eval import run_episode
from canary.forge.rl_mole import EVAL_SEED_BASE, INVESTIGATORS, RLMole, _agent, _default_rollout, rollout as rl_rollout
from canary.mole.dsl import MoleView, _select_frame, _select_leak
from train.grpo_mole import SYSTEM, parse_action, render_view

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


def resolve_model_path(spec: str | None, adapter_dir: str | None) -> str:
    raw = spec
    if not raw and adapter_dir:
        cfg_p = Path(adapter_dir) / "adapter_config.json"
        if cfg_p.is_file():
            raw = json.loads(cfg_p.read_text()).get("base_model_name_or_path")
    if not raw:
        raw = "Qwen/Qwen2.5-0.5B-Instruct"
    expanded = os.path.expanduser(raw)
    if os.path.isdir(expanded):
        return expanded
    for cand in LOCAL_MODEL_CANDIDATES.get(raw, []):
        if os.path.isdir(cand):
            return cand
    return raw


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


def apply_chat(tok, system_prompt: str, user_prompt: str) -> str:
    msgs = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
    try:
        return tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    except TypeError:
        return tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)


class GRPOMolePolicy:
    def __init__(
        self,
        model,
        tokenizer,
        device: str,
        system_prompt: str = SYSTEM,
        max_new_tokens: int = 24,
        fallback: tuple[str, str] = ("random_seeded", "none"),
        generate_fn=None,
    ):
        self.model = model
        self.tok = tokenizer
        self.device = device
        self.system_prompt = system_prompt
        self.max_new_tokens = max_new_tokens
        self.fallback = fallback
        self.generate_fn = generate_fn
        self.cache: dict[str, tuple[str, str]] = {}
        self.actions: list[tuple[str, str]] = []
        self.calls = 0
        self.invalid = 0

    def _generate_completion(self, prompt: str) -> str:
        if self.generate_fn is not None:
            return self.generate_fn(prompt)
        import torch

        txt = apply_chat(self.tok, self.system_prompt, prompt)
        enc = self.tok(txt, return_tensors="pt", add_special_tokens=False).to(self.device)
        use_amp = self.device == "cuda"
        pad_id = self.tok.pad_token_id if self.tok.pad_token_id is not None else self.tok.eos_token_id
        self.model.eval()
        with torch.no_grad(), torch.autocast(
            device_type="cuda" if use_amp else "cpu", dtype=torch.float16, enabled=use_amp
        ):
            gen = self.model.generate(
                **enc,
                max_new_tokens=self.max_new_tokens,
                do_sample=False,
                pad_token_id=pad_id,
                use_cache=True,
            )
        return self.tok.decode(gen[0, enc["input_ids"].shape[1]:], skip_special_tokens=True)

    def decide(self, view: MoleView, rng: random.Random) -> dict:
        prompt = render_view(view)
        act = self.cache.get(prompt)
        if act is None:
            self.calls += 1
            comp = self._generate_completion(prompt)
            parsed = parse_action(comp)
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


def load_mole_model(model_spec: str | None, adapter_dir: str | None, tiny: bool = False):
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, Qwen2Config, Qwen2ForCausalLM

    device = "cuda" if (torch.cuda.is_available() and not tiny) else "cpu"
    base_path = resolve_model_path(model_spec, adapter_dir)
    tok_src = adapter_dir if (adapter_dir and (Path(adapter_dir) / "tokenizer_config.json").is_file()) else base_path
    tok = AutoTokenizer.from_pretrained(tok_src)
    tok.padding_side = "left"
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    if tiny:
        cfg = Qwen2Config(
            vocab_size=max(len(tok), 151936),
            hidden_size=64,
            intermediate_size=128,
            num_hidden_layers=2,
            num_attention_heads=4,
            num_key_value_heads=2,
            max_position_embeddings=2048,
        )
        torch.manual_seed(0)
        model = Qwen2ForCausalLM(cfg)
    else:
        dt = torch.float16 if device == "cuda" else torch.float32
        try:
            model = AutoModelForCausalLM.from_pretrained(base_path, dtype=dt)
        except TypeError:
            model = AutoModelForCausalLM.from_pretrained(base_path, torch_dtype=dt)

    if adapter_dir and not tiny:
        ap = Path(adapter_dir)
        cfg_file = ap / "adapter_config.json"
        if cfg_file.is_file():
            with tempfile.TemporaryDirectory() as td:
                td_path = Path(td)
                for item in ap.iterdir():
                    if item.name == "adapter_config.json":
                        clean_cfg = sanitize_peft_config_dict(json.loads(item.read_text()))
                        clean_cfg["base_model_name_or_path"] = base_path
                        (td_path / item.name).write_text(json.dumps(clean_cfg, indent=2))
                    elif item.is_file():
                        os.symlink(item.resolve(), td_path / item.name)
                model = PeftModel.from_pretrained(model, str(td_path)).merge_and_unload()
        else:
            model = PeftModel.from_pretrained(model, str(ap)).merge_and_unload()

    model.config.use_cache = True
    model.to(device).eval()
    return model, tok, device, base_path


def parse_seeds(spec: str, n: int) -> list[int]:
    if spec == "heldout":
        return list(rules.HELDOUT_SEEDS)[:n]
    if spec == "ws3":
        return list(range(EVAL_SEED_BASE, EVAL_SEED_BASE + n))
    if spec == "dev":
        return list(rules.DEV_SEEDS)[:n]
    if "-" in spec:
        lo, hi = spec.split("-", 1)
        full = list(range(int(lo), int(hi) + 1))
        return full[:n] if n > 0 else full
    start = int(spec)
    return list(range(start, start + n))


def boot_ci(xs: list[float], B: int = 2000, seed: int = 0) -> list[float]:
    r = random.Random(seed)
    n = len(xs)
    if n == 0:
        return [0.0, 0.0, 0.0]
    ms = sorted(sum(xs[r.randrange(n)] for _ in range(n)) / n for _ in range(B))
    return [round(sum(xs) / n, 4), round(ms[int(0.025 * B)], 4), round(ms[int(0.975 * B)], 4)]


def summarize_rows(rows: list[dict], min_solver_acc: float) -> dict:
    n = max(1, len(rows))
    ags = ("solver",) + INVESTIGATORS
    out = {
        ag: {
            "score": round(sum(r[ag][0] for r in rows) / n, 4),
            "acc": round(sum(r[ag][1] for r in rows) / n, 4),
            "score_ci95": boot_ci([r[ag][0] for r in rows]),
            "acc_ci95": boot_ci([float(r[ag][1]) for r in rows]),
        }
        for ag in ags
    }
    out["regret"] = {
        k: boot_ci([r["solver"][0] - r[k][0] for r in rows]) for k in INVESTIGATORS
    }
    out["min_regret"] = round(out["solver"]["score"] - max(out[k]["score"] for k in INVESTIGATORS), 4)
    out["strongest_investigator"] = max(INVESTIGATORS, key=lambda k: out[k]["score"])
    out["catchable"] = out["solver"]["acc"] >= min_solver_acc
    return out


def paired_diff(cand_rows: list[dict], base_rows: list[dict]) -> dict:
    ags = ("solver",) + INVESTIGATORS
    return {
        **{f"{ag}_score": boot_ci([y[ag][0] - x[ag][0] for x, y in zip(base_rows, cand_rows)]) for ag in ags},
        "solver_acc": boot_ci([float(y["solver"][1]) - float(x["solver"][1]) for x, y in zip(base_rows, cand_rows)]),
        **{
            f"regret_{k}": boot_ci(
                [(y["solver"][0] - y[k][0]) - (x["solver"][0] - x[k][0]) for x, y in zip(base_rows, cand_rows)]
            )
            for k in INVESTIGATORS
        },
    }


def evaluate_mole_policy(
    policy: GRPOMolePolicy,
    tier: str,
    seeds: list[int],
    workers: int = 1,
    min_solver_acc: float = 0.85,
    rl_policy_path: str | None = None,
) -> dict:
    t0 = time.time()
    ags = ("solver",) + INVESTIGATORS
    cand_rows = []
    for s in seeds:
        row = {}
        for ag in ags:
            ep = run_episode(Env(tier, s, mole_strategy=policy), _agent(ag, tier, s))
            row[ag] = (float(ep.score), bool(ep.correct))
        cand_rows.append(row)

    tasks_def = [(None, tier, s) for s in seeds]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            def_rows = list(ex.map(_default_rollout, tasks_def))
    else:
        def_rows = [_default_rollout(t) for t in tasks_def]

    rl_rows = None
    if rl_policy_path and Path(rl_policy_path).is_file():
        rl_pol = RLMole.from_json(json.loads(Path(rl_policy_path).read_text()))
        tasks_rl = [(rl_pol.p, tier, s, ags, False) for s in seeds]
        if workers > 1:
            with ProcessPoolExecutor(max_workers=workers) as ex:
                rl_rows = list(ex.map(rl_rollout, tasks_rl))
        else:
            rl_rows = [rl_rollout(t) for t in tasks_rl]

    ac = Counter(policy.actions)
    tot = sum(ac.values()) or 1
    probs = [v / tot for v in ac.values()]
    ent = -sum(p * math.log(p + 1e-12) for p in probs)

    res = {
        "tier": tier,
        "seeds": f"{seeds[0]}-{seeds[-1]}" if seeds else "",
        "n": len(seeds),
        "min_solver_acc": min_solver_acc,
        "seconds": round(time.time() - t0, 2),
        "grpo_mole": summarize_rows(cand_rows, min_solver_acc),
        "default_mole": summarize_rows(def_rows, min_solver_acc),
        "diff_grpo_minus_default": paired_diff(cand_rows, def_rows),
        "action_stats": {
            "total_decisions": sum(ac.values()),
            "unique_prompts_generated": policy.calls,
            "invalid_generations": policy.invalid,
            "invalid_rate": round(policy.invalid / max(1, policy.calls), 4),
            "distinct_actions": len(ac),
            "action_entropy_nats": round(ent, 4),
            "action_profile": {"/".join(k): round(v / tot, 4) for k, v in ac.most_common(12)},
        },
    }
    if rl_rows is not None:
        res["rl_mole"] = summarize_rows(rl_rows, min_solver_acc)
        res["diff_grpo_minus_rl_mole"] = paired_diff(cand_rows, rl_rows)
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m train.eval_grpo_mole")
    ap.add_argument("--adapter", default=None, help="Path to PEFT LoRA adapter dir (e.g. lora-step200)")
    ap.add_argument("--model", default=None, help="Base model path or HF repo ID (auto-detected from adapter if omitted)")
    ap.add_argument("--tier", default="hard")
    ap.add_argument("--seeds", default="heldout", help="heldout (800000+), ws3 (200000+), dev, or START-END")
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--workers", type=int, default=min(4, int(os.environ.get("SLURM_CPUS_PER_TASK", "2"))))
    ap.add_argument("--min-solver-acc", type=float, default=0.85)
    ap.add_argument("--max-new", type=int, default=24)
    ap.add_argument("--rl-policy", default="data/rl_mole/policy_final.json")
    ap.add_argument("--out", default=None, help="Output JSON path")
    ap.add_argument("--tiny", action="store_true", help="CPU smoke test with tiny random Qwen2")
    a = ap.parse_args(argv)

    seeds = parse_seeds(a.seeds, a.n)
    if any(s in rules.JUDGE_SEEDS for s in seeds):
        raise ValueError("Refusing to evaluate on JUDGE_SEEDS")

    model, tok, device, base_path = load_mole_model(a.model, a.adapter, tiny=a.tiny)
    pol = GRPOMolePolicy(model, tok, device, max_new_tokens=a.max_new)
    report = evaluate_mole_policy(
        pol,
        tier=a.tier,
        seeds=seeds,
        workers=a.workers,
        min_solver_acc=a.min_solver_acc,
        rl_policy_path=a.rl_policy,
    )
    report["model"] = base_path
    report["adapter"] = a.adapter
    report["device"] = device
    report["tiny"] = a.tiny

    if a.out:
        out_p = Path(a.out)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
