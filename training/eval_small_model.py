"""Run a local Hugging Face model as the agent on eval episodes, grade, print a before/after table.

The model writes tool calls as text (JSON inside <tool_call> ... </tool_call>, the format of
most open chat templates). A tolerant parser (training/common.py) also accepts ```json fences
and bare JSON. Prompts are rendered with the same function used in training.

    # before vs after LoRA, 10 eval episodes per family (GPU; UNTESTED here)
    python training/eval_small_model.py --model Qwen/Qwen3-4B-Instruct-2507 \
        --adapter training/out/Qwen3-4B-Instruct-2507-lora --limit 10 --save-runs runs/small_model
    python -m pinbox eval --include-recorded runs/small_model      # re-grade the saved runs

    # plumbing check, no ML libraries: a fake "model" that writes the reference agent's calls
    python training/eval_small_model.py --dry-run --limit 3

Runs use the frozen EVAL set (Task.eval_specs()); training data never uses those seeds.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training.common import (FIRST_MESSAGE, NUDGE, ROOT, dumps_compact, looks_like_call,  # noqa: E402
                             model_short_name, openai_tools, parse_tool_calls, prose_before_calls, render_text,
                             strip_thinking, tool_message)

from pinbox.client import EpisodeClient  # noqa: E402
from pinbox.episode import Episode  # noqa: E402
from pinbox.eval import summarize  # noqa: E402
from pinbox.grader import grade  # noqa: E402
from pinbox.tasks import all_tasks  # noqa: E402

BUDGET_ERROR = "tool budget exhausted"
END_MARKERS = ("<|im_end|>", "<|endoftext|>", "<|eot_id|>", "<|end|>", "</s>", "<end_of_turn>")


class ContextFull(Exception):
    """The conversation no longer fits in the model's context window."""


# ---------------------------------------------------------------- the agent loop

def run_text_agent(client, model, max_turns: int = 150, max_nudges: int = 2) -> dict:
    """Drive one episode with a text model. `model.generate(messages, tools) -> str`.

    Stops when the model replies without a tool call, at the tool budget, at max_turns, or
    when the context is full. Never grades.
    """
    tools = openai_tools(client.tools())
    messages = [{"role": "system", "content": client.instruction()}, {"role": "user", "content": FIRST_MESSAGE}]
    info = {"stop_reason": "max_turns", "turns": 0, "tool_calls": 0, "parse_errors": 0, "final_text": "",
            "raw": []}
    nudges = 0
    for _ in range(max_turns):
        try:
            text = model.generate(messages, tools)
        except ContextFull:
            info["stop_reason"] = "context_full"
            break
        info["turns"] += 1
        info["raw"].append(text)
        calls = parse_tool_calls(text)
        if not calls:
            clean = strip_thinking(text).strip()
            if looks_like_call(text) and nudges < max_nudges:
                nudges += 1
                info["parse_errors"] += 1
                messages.append({"role": "assistant", "content": clean})
                messages.append({"role": "user", "content": NUDGE})
                continue
            if looks_like_call(text):
                info["parse_errors"] += 1
            messages.append({"role": "assistant", "content": clean or "Done."})
            info["final_text"] = clean
            info["stop_reason"] = "model_done"
            break
        tcs = []
        for name, args in calls:
            cid = f"call_{info['tool_calls'] + len(tcs)}"
            tcs.append({"id": cid, "type": "function", "function": {"name": name, "arguments": dumps_compact(args)}})
        messages.append({"role": "assistant", "content": prose_before_calls(text) or None, "tool_calls": tcs})
        budget_hit = False
        for tc, (name, args) in zip(tcs, calls):
            out = client.call_args(name, args)
            info["tool_calls"] += 1
            messages.append(tool_message(tc["id"], name, out))
            budget_hit = budget_hit or out.get("error") == BUDGET_ERROR
        if budget_hit:
            info["stop_reason"] = "budget_exhausted"
            break
    info["messages"] = messages
    return info


# ---------------------------------------------------------------- models

class HFModel:
    """A local HF causal LM (optionally with a LoRA adapter). Greedy decoding. Lazy imports."""

    def __init__(self, model_id: str, adapter: str | None = None, precision: str = "fp16", attn: str = "sdpa",
                 max_new_tokens: int = 512, max_ctx: int = 32768, protocol: str = "auto",
                 trust_remote_code: bool = False):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from training.common import choose_protocol, dtype_kwarg
        self.torch = torch
        tok_src = adapter if adapter and (Path(adapter) / "tokenizer_config.json").exists() else model_id
        self.tok = AutoTokenizer.from_pretrained(tok_src, trust_remote_code=trust_remote_code)
        if self.tok.pad_token is None:
            self.tok.pad_token = self.tok.eos_token
        dtype = torch.float16 if (precision == "fp16" and torch.cuda.is_available()) else torch.float32
        model = AutoModelForCausalLM.from_pretrained(model_id, attn_implementation=attn,
                                                     trust_remote_code=trust_remote_code, **dtype_kwarg(dtype))
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        model.to(self.device)
        self.has_adapter = bool(adapter)
        if adapter:
            from peft import PeftModel
            model = PeftModel.from_pretrained(model, adapter)
        model.eval()
        self.model = model
        self.adapter_on = self.has_adapter
        self.protocol = choose_protocol(self.tok, protocol)
        self.max_new_tokens = max_new_tokens
        self.max_ctx = max_ctx
        print(f"[eval] loaded {model_id}{' + ' + adapter if adapter else ''} on {self.device}, "
              f"protocol {self.protocol}", flush=True)

    @contextlib.contextmanager
    def use_adapter(self, on: bool):
        if self.has_adapter and not on:
            with self.model.disable_adapter():
                yield
        else:
            yield

    def generate(self, messages: list, tools: list) -> str:
        torch = self.torch
        prompt = render_text(self.tok, messages, tools, self.protocol, add_generation_prompt=True)
        ids = self.tok(prompt, return_tensors="pt", add_special_tokens=False)["input_ids"].to(self.device)
        if ids.shape[1] + self.max_new_tokens > self.max_ctx:
            raise ContextFull()
        with torch.no_grad(), self.use_adapter(self.adapter_on):
            out = self.model.generate(input_ids=ids, attention_mask=torch.ones_like(ids),
                                      max_new_tokens=self.max_new_tokens, do_sample=False,
                                      pad_token_id=self.tok.pad_token_id)
        text = self.tok.decode(out[0, ids.shape[1]:], skip_special_tokens=False)
        markers = [m for m in (*END_MARKERS, self.tok.eos_token, self.tok.pad_token) if m]
        cut = min([text.find(m) for m in markers if m in text] or [len(text)])
        return text[:cut]


class FakeReferenceModel:
    """Dry-run 'model': writes the reference agent's calls as text, in three different formats,
    so the prompt rendering, the parser and the loop are all exercised. Should score 1."""

    def __init__(self, episode):
        from pinbox.agents.baselines import reference_trajectory
        self.calls = [(r["tool"], r.get("args") or {}) for r in reference_trajectory(episode)]

    def generate(self, messages: list, tools: list) -> str:
        render_text(None, messages, tools, "plain", add_generation_prompt=True)   # exercise rendering
        k = sum(1 for m in messages if m["role"] == "tool")
        if k >= len(self.calls):
            return "Done. I worked through the whole queue."
        name, args = self.calls[k]
        style = k % 3
        if style == 0:
            return "<tool_call>\n" + json.dumps({"name": name, "arguments": args}) + "\n</tool_call>"
        if style == 1:
            return "Next step.\n```json\n" + json.dumps({"tool": name, "args": args}, indent=1) + "\n```"
        return json.dumps({"name": name, "arguments": json.dumps(args)})


class FakeIdleModel:
    """Dry-run 'before' model: answers at once without doing anything. Should score 0."""

    def generate(self, messages: list, tools: list) -> str:
        render_text(None, messages, tools, "plain", add_generation_prompt=True)
        return "I have read the task. Nothing else to do."


# ---------------------------------------------------------------- eval

def pick_specs(families=None, limit: int = 0, difficulties=None) -> list:
    """Eval-set (family, seed, difficulty) triples; `limit` per family, spread over difficulties."""
    out = []
    for task in all_tasks():
        if families and task.family not in families:
            continue
        specs = [(s, d) for s, d in task.eval_specs() if not difficulties or d in difficulties]
        if limit:
            by_d: dict = {}
            for s, d in specs:
                by_d.setdefault(d, []).append((s, d))
            mixed = []
            while any(by_d.values()):          # round-robin over difficulties
                for d in sorted(by_d):
                    if by_d[d]:
                        mixed.append(by_d[d].pop(0))
            specs = mixed[:limit]
        out += [(task.family, int(s), int(d)) for s, d in specs]
    return out


def _slug(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in text)[:80]


def run_variant(label: str, variant: str, model_for, specs: list, repeats: int = 1, max_turns: int = 150,
                save_dir=None, log=print) -> list:
    """Run one model variant over the specs. `model_for(episode)` returns the model to use."""
    runs = []
    for family, seed, diff in specs:
        for rep in range(max(1, repeats)):
            ep = Episode.create(family, seed, diff, info={"agent": label, "kind": "llm", "repeat": rep,
                                                          "variant": variant})
            t0 = time.time()
            try:
                info = run_text_agent(EpisodeClient(ep), model_for(ep), max_turns=max_turns)
            except Exception as e:  # a model crash is that run's result, not the whole eval's
                info = {"stop_reason": f"error: {type(e).__name__}: {e}"[:200], "turns": 0, "tool_calls": 0,
                        "parse_errors": 0, "raw": [], "messages": []}
            rep_ = grade(ep)
            run = {"episode_id": ep.episode_id, "family": family, "seed": seed, "difficulty": diff, "repeat": rep,
                   "reward": rep_.reward, "progress": rep_.progress, "failure_tags": rep_.failure_tags,
                   "calls": rep_.calls, "stop_reason": info["stop_reason"], "turns": info["turns"],
                   "parse_errors": info["parse_errors"], "seconds": round(time.time() - t0, 1)}
            if save_dir:
                folder = Path(save_dir) / _slug(label) / (ep.episode_id + (f"-r{rep}" if rep else ""))
                ep.info.update({"reward": rep_.reward, "stop_reason": info["stop_reason"]})
                ep.save(folder)
                with open(folder / "transcript.json", "w", encoding="utf-8", newline="\n") as f:
                    json.dump({"run": run, "raw_outputs": info.get("raw", []),
                               "messages": info.get("messages", [])}, f, ensure_ascii=False, indent=1)
                    f.write("\n")
                run["trajectory"] = (folder / "trajectory.jsonl").as_posix()
            runs.append(run)
            if log:
                log(f"[eval] {label:<34} {ep.episode_id:<18} reward {rep_.reward}  progress {rep_.progress:.2f}  "
                    f"calls {rep_.calls:>3}  {info['stop_reason']}")
    return runs


def reference_runs(specs: list) -> list:
    runs = []
    for family, seed, diff in specs:
        ep = Episode.create(family, seed, diff)
        ep.task.reference(EpisodeClient(ep))
        r = grade(ep)
        runs.append({"episode_id": ep.episode_id, "family": family, "seed": seed, "difficulty": diff, "repeat": 0,
                     "reward": r.reward, "progress": r.progress, "failure_tags": r.failure_tags, "calls": r.calls,
                     "stop_reason": "scripted", "turns": 0, "parse_errors": 0})
    return runs


def print_table(results: dict) -> None:
    fams = []
    for s in results["eval_set"]:
        if s["family"] not in fams:
            fams.append(s["family"])
    head = (f"{'variant':<10} {'agent':<34} {'runs':>4} {'mean':>6} {'pass^1':>6} {'progress':>8} "
            f"{'calls':>6} {'parse_err':>9}" + "".join(f" {f[:10]:>10}" for f in fams))
    print(head)
    print("-" * len(head))
    for label, entry in results["agents"].items():
        s = results["summary"][label]
        runs = entry["runs"]
        calls = sum(r["calls"] for r in runs) / max(1, len(runs))
        perr = sum(r.get("parse_errors", 0) for r in runs)
        row = (f"{entry.get('variant', ''):<10} {label[:34]:<34} {s['n_runs']:>4} {s['mean_reward']:>6.3f} "
               f"{s['pass_k'].get('1', 0):>6.3f} {s.get('mean_progress', 0):>8.3f} {calls:>6.1f} {perr:>9}")
        row += "".join(f" {s['by_family'].get(f, float('nan')):>10.3f}" for f in fams)
        print(row)
    b = next((results["summary"][k] for k, v in results["agents"].items() if v.get("variant") == "before"), None)
    a = next((results["summary"][k] for k, v in results["agents"].items() if v.get("variant") == "after"), None)
    if a and b:
        print(f"\nchange in mean reward (after - before): {a['mean_reward'] - b['mean_reward']:+.3f}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Evaluate a small local model (before/after LoRA) on eval episodes.")
    ap.add_argument("--model", default="Qwen/Qwen3-4B-Instruct-2507")
    ap.add_argument("--adapter", default="", help="LoRA adapter folder (adds the 'after' variant)")
    ap.add_argument("--variants", default="", help="comma list of before,after (default: both if --adapter)")
    ap.add_argument("--families", default="")
    ap.add_argument("--difficulties", default="")
    ap.add_argument("--limit", type=int, default=0, help="episodes per family (0 = the whole eval set)")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--max-turns", type=int, default=150)
    ap.add_argument("--max-new-tokens", type=int, default=512)
    ap.add_argument("--max-ctx", type=int, default=32768)
    ap.add_argument("--protocol", choices=["auto", "native", "plain"], default="auto",
                    help="must match what train_lora.py used")
    ap.add_argument("--precision", choices=["fp16", "fp32"], default="fp16")
    ap.add_argument("--attn", default="sdpa")
    ap.add_argument("--trust-remote-code", action="store_true")
    ap.add_argument("--no-reference", action="store_true", help="leave the scripted reference row out")
    ap.add_argument("--save-runs", default="", help="save each run here (re-grade with pinbox eval --include-recorded)")
    ap.add_argument("--out", default=str(ROOT / "training" / "out" / "small_model_eval.json"))
    ap.add_argument("--dry-run", action="store_true", help="fake models, no ML libraries: tests the plumbing")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    fams = [f.strip() for f in args.families.split(",") if f.strip()] or None
    diffs = [int(d) for d in args.difficulties.split(",") if d.strip()] or None
    specs = pick_specs(fams, args.limit, diffs)
    if not specs:
        print("[eval] no episodes selected")
        return 2
    log = None if args.quiet else print
    variants = [v.strip() for v in args.variants.split(",") if v.strip()] or \
        (["before", "after"] if (args.adapter or args.dry_run) else ["before"])
    agents: dict = {}

    if args.dry_run:
        fakes = {"before": ("fake-idle (before)", lambda ep: FakeIdleModel()),
                 "after": ("fake-reference-as-text (after)", lambda ep: FakeReferenceModel(ep))}
        for v in variants:
            label, make = fakes[v]
            agents[label] = {"kind": "fake", "variant": v,
                             "runs": run_variant(label, v, make, specs, args.repeats, args.max_turns,
                                                 args.save_runs or None, log)}
    else:
        if "after" in variants and not args.adapter:
            ap.error("--variants after needs --adapter")
        model = HFModel(args.model, args.adapter or None, args.precision, args.attn, args.max_new_tokens,
                        args.max_ctx, args.protocol, args.trust_remote_code)
        short = model_short_name(args.model)
        for v in variants:
            model.adapter_on = v == "after"
            label = short + ("+lora" if v == "after" else "")
            agents[label] = {"kind": "llm", "variant": v, "model": args.model,
                             "adapter": args.adapter if v == "after" else None,
                             "runs": run_variant(label, v, lambda ep: model, specs, args.repeats, args.max_turns,
                                                 args.save_runs or None, log)}
    if not args.no_reference:
        agents["reference (scripted)"] = {"kind": "scripted", "variant": "ref", "runs": reference_runs(specs)}

    results = {"generated_by": "training/eval_small_model.py", "dry_run": bool(args.dry_run),
               "eval_set": [{"family": f, "seed": s, "difficulty": d, "episode_id": f"{f}-s{s}-d{d}"}
                            for f, s, d in specs],
               "agents": agents, "summary": {k: summarize(v["runs"]) for k, v in agents.items()}}
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            json.dump(results, f, ensure_ascii=False, indent=1)
            f.write("\n")
    print()
    print_table(results)
    if args.out:
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
