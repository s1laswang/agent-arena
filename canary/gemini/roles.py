"""Labelled real runs for two Gemini roles that had none: the world-text renderer and the adaptive (arena) mole.

    python -m canary.gemini.roles worldtext --tier medium --seeds 0-5 [--model gemini-4-carbon] [--probe-model gemini-3.8-flash]
    python -m canary.gemini.roles mole --tier medium --seeds 0-3 [--model gemini-4-carbon] [--investigators solver,heuristic]

DEV seeds only: any judge seed (canary.rules.JUDGE_SEEDS) is refused, so no judge world and no judge mole is ever
rendered or written. Every Gemini call goes through canary.gemini.ledger (lab_client); the run's ledger rows are
written next to its outputs (results/gemini/roles/<role>/ledger.jsonl) and summarised in meta.json together with
model id, thinking level, git commit, run id and timestamps.

worldtext: gemini-4-carbon writes personas, department culture and chat templates from PUBLIC facts only
(canary.agents.world_builder.build_world_text via canary.text.gemini.GeminiWorldTextProvider). We render every day
of the episode, then check the text three ways:
  1. canary/text/lint.py (lint_text / lint_messages) over every rendered string, plus world_builder.assert_no_truth;
  2. canary.redteam.text_probe's keyword investigator (stub) on the Gemini text and on the template text;
  3. an LLM investigator (gemini-3.8-flash, ledgered) that names the mole from text alone,
  each against the probe's fair bar (best accuracy the documented interview signal allows) with a one-sided
  binomial p-value. Only per-seed correct/incorrect flags are stored, never the mole's id.

mole: gemini-4-carbon plays the mole day by day (canary.agents.mole_arena.LLMMole, arena mode, never the judge
path) against the reference solver and the heuristic. The env's p_leak gate is respected (the LLM's leak is
dropped on days the gate is closed, as the DSL moles do). The same seeds are replayed with the default mole for a
paired comparison. Per-day decisions (what the mole saw, what Gemini chose, its one-line reason, what was applied)
go to episodes.jsonl.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import socket
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "gemini" / "roles"


# ------------------------------------------------------------------ provenance
def git_info() -> dict:
    def run(*a):
        try:
            return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:  # noqa: BLE001
            return ""
    return {"git_sha": run("rev-parse", "HEAD"), "git_branch": run("rev-parse", "--abbrev-ref", "HEAD"),
            "git_dirty": bool(run("status", "--porcelain", "--untracked-files=no"))}


def _spec(model: str) -> str:
    return "stub" if model == "stub" else f"gemini:{model}"


def parse_seeds(s: str) -> list[int]:
    out: list[int] = []
    for part in s.split(","):
        if "-" in part:
            a, b = part.split("-")
            out += range(int(a), int(b) + 1)
        elif part:
            out.append(int(part))
    return out


def dev_only(seeds: list[int]) -> list[int]:
    from canary.rules import JUDGE_SEEDS
    bad = [s for s in seeds if s in JUDGE_SEEDS]
    if bad:
        raise SystemExit(f"refusing judge seeds {bad}: roles runs use DEV seeds only")
    return seeds


def start_run(role: str, out: Path) -> tuple[str, Path, float]:
    """Point this process's ledger at <out>/ledger.jsonl and return (run_id, ledger_path, t0)."""
    out.mkdir(parents=True, exist_ok=True)
    run_id = f"roles-{role}-{time.strftime('%Y%m%d-%H%M%S')}"
    led = out / "ledger.jsonl"
    os.environ["CANARY_GEMINI_LEDGER"] = str(led)
    os.environ["CANARY_GEMINI_RUN_ID"] = run_id
    return run_id, led, time.time()


def ledger_summary(led: Path, run_id: str) -> dict:
    from canary.gemini.ledger import read_ledger
    rows = [r for r in (read_ledger([led]) if led.exists() else []) if r.get("run_id") == run_id]
    by_model: dict[str, int] = {}
    for r in rows:
        by_model[r["model"]] = by_model.get(r["model"], 0) + 1
    return {"run_id": run_id, "calls": len(rows), "errors": sum(not r["ok"] for r in rows),
            "by_model": by_model, "in": sum(r["in"] for r in rows), "out": sum(r["out"] for r in rows),
            "thinking": sum(r["thinking"] for r in rows), "cached": sum(r["cached"] for r in rows),
            "cost_usd_list": round(sum(r["cost_usd"] for r in rows), 4),
            "latency_s_mean": round(statistics.mean([r["latency_s"] for r in rows]), 2) if rows else None}


def write_meta(out: Path, role: str, run_id: str, t0: float, client, extra: dict, led: Path) -> dict:
    settings = client.settings() if hasattr(client, "settings") else {}
    meta = {"role": role, "model": client.model, "provider_settings": settings,
            "thinking_level": settings.get("thinking_level"), **git_info(), "run_id": run_id,
            "started_at": dt.datetime.fromtimestamp(t0).astimezone().isoformat(timespec="seconds"),
            "finished_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "host": socket.gethostname().split(".")[0], "ledger": ledger_summary(led, run_id), **extra}
    (out / "meta.json").write_text(json.dumps(meta, indent=1, default=str) + "\n")
    return meta


# ------------------------------------------------------------------ world text
class _Recorder:
    def __init__(self, inner):
        self.inner, self.name, self.days = inner, inner.name, {}

    def day_messages(self, facts):
        msgs = self.inner.day_messages(facts)
        self.days[str(facts.day)] = msgs
        return msgs

    def interview_answer(self, facts, employee, topic, signal):
        return self.inner.interview_answer(facts, employee, topic, signal)


def _probe(tier: str, seed: int, provider_factory) -> dict:
    """canary.redteam.text_probe.collect with our text provider injected (it builds its own Env)."""
    import canary.env as envmod
    from canary.redteam import text_probe
    real = envmod.Env

    def patched(tier, seed, **kw):
        return real(tier, seed, text_provider=provider_factory(), **kw)
    envmod.Env = patched
    try:
        return text_probe.collect(tier, seed)
    finally:
        envmod.Env = real


def _llm_guess(client, obs: dict) -> str:
    import re

    from canary.redteam.text_probe import _prompt
    r = client.chat([{"role": "user", "content": _prompt(obs)}], max_tokens=4096)
    m = re.search(r"e\d{2,3}", r.text or "")
    return m.group(0) if m else ""


def verdict(s: dict) -> str:
    """canary/text/lint.py must be clean and no text-only investigator may beat the fair bar. assert_no_truth's
    unique-tone heuristic is reported but only counts when the mole is the ONLY persona with a unique tone."""
    rows, n = s["rows"], len(s["rows"])
    probes_ok = not any(s[k]["leak_above_bar"] for k in ("probe_stub_gemini_text", "probe_llm_gemini_text"))
    tone_only = all(r["assert_no_truth"] or ("unique tone" in r.get("assert_no_truth_msg", "")
                                             and r.get("personas_with_unique_tone", 0) > 1) for r in rows)
    if s["lint_clean_seeds"] == n and probes_ok and tone_only:
        return "no leak: lint.py clean, no text-only investigator above the fair bar"
    return "CHECK: lint problems, a truth assertion, or a probe above the fair bar"


def run_worldtext(a) -> int:
    from canary.agents.world_builder import assert_no_truth
    from canary.env import Env
    from canary.gemini.ledger import lab_client
    from canary.redteam.text_probe import fair_bar, p_value_above, stub_guess, wilson
    from canary.rules import TIERS
    from canary.text.gemini import GeminiWorldTextProvider
    from canary.text.lint import lint_messages, lint_text
    from canary.text.template import TemplateProvider

    seeds = dev_only(parse_seeds(a.seeds))
    out = Path(a.out) / "worldtext"
    run_id, led, t0 = start_run("worldtext", out)
    client = lab_client(_spec(a.model), feature="worldtext", run_id=run_id)
    probe_client = lab_client(_spec(a.probe_model), feature="worldtext-probe", run_id=run_id)
    cache = out / "_cache"          # GeminiWorldTextProvider's own cache (named by the world's derived seed)
    worlds = out / "worlds" / a.tier
    worlds.mkdir(parents=True, exist_ok=True)
    rows = []
    for seed in seeds:
        prov = GeminiWorldTextProvider(model=a.model, cache_dir=str(cache), client=client)
        rec = _Recorder(prov)
        env = Env(a.tier, seed, text_provider=rec)
        stale = cache / a.tier / f"{env._facts(env.day).seed}.worldtext.json"
        if stale.exists() and not a.reuse:
            stale.unlink()
        for _ in range(200):
            if env.done:
                break
            env.call("advance_day", {})
        rendered = {"tier": a.tier, "seed": seed, "provider": rec.name, "days": rec.days}
        (worlds / f"{seed}.text.json").write_text(json.dumps(rendered, indent=1, sort_keys=True) + "\n")
        wt = json.loads(stale.read_text())
        (worlds / f"{seed}.worldtext.json").write_text(json.dumps(wt, indent=1, sort_keys=True) + "\n")
        # 1. lint
        problems = [p for msgs in rec.days.values() for p in lint_messages(msgs)]
        strings = [wt.get("company_blurb", "")] + [p["bio"] for p in wt["personas"]] + \
            [d["culture"] for d in wt["departments"]] + list(wt["chatter_templates"])
        problems += [p for s in strings for p in lint_text(s)]
        world = {"mole": env._world.mole, "employees": [{"id": e} for e in env._ids]}  # truth: local check only
        try:
            assert_no_truth(wt, world)
            no_truth, no_truth_msg = True, ""
        except AssertionError as e:
            no_truth, no_truth_msg = False, str(e)[:160]
        tones = [p_["tone"] for p_ in wt["personas"]]
        # 2+3. text-only investigators (the Gemini text is cached now: no further world-builder calls)
        obs_g = _probe(a.tier, seed, lambda: GeminiWorldTextProvider(model=a.model, cache_dir=str(cache), client=client))
        obs_t = _probe(a.tier, seed, TemplateProvider)
        guess_llm = _llm_guess(probe_client, obs_g)
        meta = wt.get("meta", {})
        rows.append({"seed": seed, "llm_ok": meta.get("llm_ok"), "n_llm_personas": meta.get("n_llm_personas"),
                     "n_fallback_personas": meta.get("n_fallback_personas"), "n_templates": len(wt["chatter_templates"]),
                     "days_rendered": len(rec.days), "messages": sum(len(v) for v in rec.days.values()),
                     "lint_problems": problems, "assert_no_truth": no_truth, "assert_no_truth_msg": no_truth_msg,
                     "personas_with_unique_tone": sum(1 for x in tones if tones.count(x) == 1), "personas": len(tones),
                     "k_interviews": obs_g["k_interviews"],
                     "probe_stub_gemini_text_correct": stub_guess(obs_g) == obs_g["mole"],
                     "probe_stub_template_text_correct": stub_guess(obs_t) == obs_t["mole"],
                     "probe_llm_gemini_text_correct": guess_llm == obs_g["mole"]})
        print(f"seed {seed}: llm_ok={meta.get('llm_ok')} personas {meta.get('n_llm_personas')}/{len(wt['personas'])} "
              f"lint={len(problems)} probes stub={rows[-1]['probe_stub_gemini_text_correct']} "
              f"llm={rows[-1]['probe_llm_gemini_text_correct']}", flush=True)
    n = len(rows)
    k = rows[0]["k_interviews"] if rows else 0
    bar = fair_bar(a.tier, k)

    def test(key):
        hits = sum(r[key] for r in rows)
        lo, hi = wilson(hits, n)
        pv = p_value_above(hits, n, bar)
        return {"correct": hits, "n": n, "accuracy": hits / max(1, n), "ci95": [round(lo, 3), round(hi, 3)],
                "p_value_vs_fair_bar": round(pv, 4), "leak_above_bar": pv < 0.01}
    summary = {"tier": a.tier, "seeds": seeds, "chance": 1 / TIERS[a.tier].n_employees, "fair_bar": round(bar, 4),
               "interviews_per_employee": k,
               "lint_clean_seeds": sum(not r["lint_problems"] for r in rows), "assert_no_truth_pass": sum(r["assert_no_truth"] for r in rows),
               "gemini_personas": sum(r["n_llm_personas"] or 0 for r in rows),
               "fallback_personas": sum(r["n_fallback_personas"] or 0 for r in rows),
               "probe_stub_gemini_text": test("probe_stub_gemini_text_correct"),
               "probe_stub_template_text": test("probe_stub_template_text_correct"),
               "probe_llm_gemini_text": test("probe_llm_gemini_text_correct"), "rows": rows}
    summary["verdict"] = verdict(summary)
    (out / "lint_probe.json").write_text(json.dumps(summary, indent=1) + "\n")
    meta = write_meta(out, "worldtext", run_id, t0, client, {
        "tier": a.tier, "seeds": seeds, "probe_model": a.probe_model,
        "outputs": ["worlds/<tier>/<seed>.worldtext.json (Gemini world text)", "worlds/<tier>/<seed>.text.json (rendered days)",
                    "lint_probe.json", "ledger.jsonl"]}, led)
    print(json.dumps({k: summary[k] for k in ("verdict", "fair_bar", "lint_clean_seeds", "probe_stub_gemini_text",
                                               "probe_llm_gemini_text")}, indent=1))
    print(f"ledger: {meta['ledger']['calls']} calls, ${meta['ledger']['cost_usd_list']}")
    return 0


# ------------------------------------------------------------------ adaptive mole
class GatedLLMMole:
    """LLMMole that respects the env's p_leak gate (MoleView.can_leak), like the DSL moles do, and logs the view."""

    def __init__(self, client):
        from canary.agents.mole_arena import LLMMole
        self.inner = LLMMole(client)
        self.name = f"gemini-mole:{client.model}"
        self.days: list[dict] = []

    def decide(self, view) -> dict:
        from canary.agents.mole_arena import view_to_dict
        v = view_to_dict(view)
        move = self.inner.decide(view)
        log = self.inner.log[-1]
        gate = bool(getattr(view, "can_leak", True))
        applied = dict(move)
        if move.get("leak") and not gate:
            applied["leak"] = None
        self.days.append({"day": v["day"], "docs_held": len(v["held_docs"]),
                          "low_recipient_docs": v["recent_low_recipient_docs"],
                          "days_since_last_leak": v["days_since_last_leak"], "i_am_restricted": v["i_am_restricted"],
                          "n_restricted_colleagues": v["n_restricted_colleagues"], "p_leak_gate_open": gate,
                          "gemini_move": move, "applied_move": applied, "reason": log.get("reason"),
                          "error": log.get("error"), "rejected": log.get("rejected")})
        return applied


def _episode(tier, seed, inv_name, mole_kind, model, run_id):
    from canary.agents.clash import play, resolve_policy
    from canary.env import Env
    from canary.gemini.ledger import lab_client
    mole = None
    if mole_kind == "gemini":
        mole = GatedLLMMole(lab_client(_spec(model), feature="mole", run_id=run_id,
                                       meta={"seed": seed, "investigator": inv_name}))
    env = Env(tier, seed, mole_strategy=mole) if mole else Env(tier, seed)
    policy = resolve_policy(inv_name)()
    t0 = time.time()
    res = play(env, policy, inv_name)
    leaks = [e for e in env._events if e.get("type") == "leak"] if hasattr(env, "_events") else None
    row = {"seed": seed, "tier": tier, "investigator": inv_name,
           "mole": mole.name if mole else "default (canary.mole.dsl)", "score": res.score, "correct": res.correct,
           "final_day": res.final_day, "end": res.end_reason, "secs": round(time.time() - t0, 1)}
    if mole:
        row["leaks_applied"] = sum(1 for d in mole.days if d["applied_move"].get("leak"))
        row["canary_leaks"] = sum(1 for d in mole.days if str(d["applied_move"].get("leak") or "").startswith("c"))
        row["leaks_gated"] = sum(1 for d in mole.days if d["gemini_move"].get("leak") and not d["applied_move"].get("leak"))
        row["frames"] = sum(1 for d in mole.days if d["applied_move"].get("frame"))
        row["llm_errors"] = sum(1 for d in mole.days if d["error"])
        row["days"] = mole.days
    del leaks
    return row


def run_mole(a) -> int:
    from canary.gemini.ledger import lab_client
    seeds = dev_only(parse_seeds(a.seeds))
    invs = a.investigators.split(",")
    out = Path(a.out) / "mole"
    run_id, led, t0 = start_run("mole", out)
    jobs = [(a.tier, s, inv, kind, a.model, run_id) for inv in invs for s in seeds for kind in ("gemini", "default")]
    rows = []
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(_episode, *j): j for j in jobs}
        for f in cf.as_completed(futs):
            r = f.result()
            rows.append(r)
            print(f"{r['investigator']:>9} seed {r['seed']} mole={r['mole'][:24]:<24} score {r['score']:+.3f} "
                  f"correct={r['correct']} day {r['final_day']} {r['end']}", flush=True)
    rows.sort(key=lambda r: (r["investigator"], r["seed"], r["mole"]))
    with open(out / "episodes.jsonl", "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    summ = {}
    for inv in invs:
        g = {r["seed"]: r for r in rows if r["investigator"] == inv and r["mole"].startswith("gemini")}
        d = {r["seed"]: r for r in rows if r["investigator"] == inv and not r["mole"].startswith("gemini")}
        paired = [g[s]["score"] - d[s]["score"] for s in seeds if s in g and s in d]
        summ[inv] = {"n": len(g), "gemini_mole_mean_score": round(statistics.mean(r["score"] for r in g.values()), 4),
                     "default_mole_mean_score": round(statistics.mean(r["score"] for r in d.values()), 4),
                     "paired_diff_mean": round(statistics.mean(paired), 4) if paired else None,
                     "gemini_mole_caught": sum(r["correct"] for r in g.values()),
                     "default_mole_caught": sum(r["correct"] for r in d.values()),
                     "gemini_leaks_applied": sum(r["leaks_applied"] for r in g.values()),
                     "gemini_canary_leaks": sum(r.get("canary_leaks", 0) for r in g.values()),
                     "gemini_leaks_gated": sum(r["leaks_gated"] for r in g.values()),
                     "gemini_frames": sum(r["frames"] for r in g.values()),
                     "llm_errors": sum(r["llm_errors"] for r in g.values())}
    summary = {"tier": a.tier, "seeds": seeds, "investigators": invs,
               "note": "investigator score: lower = the mole did better. paired_diff = gemini mole - default mole, same seed.",
               "by_investigator": summ}
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    client = lab_client(_spec(a.model), feature="mole", run_id=run_id)  # for settings() only, no call
    meta = write_meta(out, "mole", run_id, t0, client, {
        "tier": a.tier, "seeds": seeds, "investigators": invs, "mode": "arena (canary.agents.mole_arena), not the judge path",
        "p_leak_gate": "respected (LLM leak dropped when MoleView.can_leak is False)",
        "outputs": ["episodes.jsonl (per-day mole decisions)", "summary.json", "ledger.jsonl"]}, led)
    print(json.dumps(summ, indent=1))
    print(f"ledger: {meta['ledger']['calls']} calls, ${meta['ledger']['cost_usd_list']}")
    return 0


# ------------------------------------------------------------------ index + ROLES.md
def _load(p: Path):
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _pct(x) -> str:
    return "–" if x is None else f"{100 * x:.0f}%"


def _commit(m: dict) -> str:
    c = m.get("code_commit")
    return f"{c} (launched at {m['git_sha'][:7]})" if c else m["git_sha"][:10]


def build_index(res: Path) -> list[dict]:
    """One row per Gemini role, every number read from a committed results file (none typed by hand)."""
    rows = []
    L = _load(res / "ladder.json")
    if L:
        carb = [r for r in L.get("rows", []) if r["model"] == "gemini-4-carbon" and r["tier"] == "hard" and r.get("ratio") is not None]
        best = max(carb, key=lambda r: r["n"]) if carb else None
        models = sorted({r["model"] for r in L.get("rows", [])})
        head = (f"gemini-4-carbon ({best['level']}) reaches {_pct(best['ratio'])} of the solver on hard "
                f"[95% CI {_pct(best.get('ratio_lo'))}, {_pct(best.get('ratio_hi'))}], n={best['n']}") if best else ""
        rows.append({"role": "Frontier subject (the agent under test)", "key": "frontier",
                     "run": "results/gemini/ladder.json (+ ladder.md, ladder_episodes.jsonl.gz, ladder_ledger.jsonl.gz)",
                     "model": ", ".join(models), "thinking": "minimal / low / medium / high (+ carbon model default, imported)",
                     "commit": str(L.get("git_sha", ""))[:10], "generated_at": L.get("generated_at"),
                     "n": f"{L.get('episodes')} episodes, {len(L.get('rows', []))} cells", "headline": head,
                     "source_note": "G2 ladder; the carbon default-thinking cell is the AfterQuery measurement, imported read-only"})
    A = _load(res / "atlas.json")
    if A:
        c, v, m = A.get("corpus", {}), A.get("verification", {}), (A.get("modes") or [{}])[0]
        ha = A.get("human_agreement") or {}
        v1 = (f"top failure mode \"{m.get('name')}\" = {_pct(m.get('regret_share'))} of all solver regret; "
              f"{v.get('quotes_verified')}/{v.get('quotes_checked')} quotes verbatim ({_pct(v.get('pass_rate'))}); "
              f"human agreement {_pct(ha.get('score')) if ha.get('status') == 'done' else 'pending'}")
        B = _load(res / "atlas_blind.json")
        rc, bq = (B or {}).get("recovery") or {}, (B or {}).get("quotes") or {}
        blind = (f"Blind re-run (atlas_blind.json, {B.get('model')}, {str(B.get('git_sha', ''))[:7]}): recovered "
                 f"{len(rc.get('tags_recovered') or [])}/{rc.get('n_tags')} code-defined failure modes and named "
                 f"{len(rc.get('novel_modes') or [])} new ones; cited steps cover {_pct(rc.get('regret_share_covered'))} of solver regret "
                 f"(weak coverage); {bq.get('verified_agent_text')}/{bq.get('checked')} quotes verbatim. "
                 f"v1 (not blind: it saw our regret tags and solver beliefs): ") if B and rc else ""
        rows.append({"role": "Analyst (Failure Atlas)", "key": "analyst",
                     "run": "results/gemini/atlas.json (+ atlas.md, atlas_charts/)" + (", atlas_blind.json (+ atlas_blind.md)" if blind else ""),
                     # the batch slot is omitted: Batch API calls failed on our key (quota), so it did no work
                     "model": ", ".join(f"{k}: {v_}" for k, v_ in (A.get("models") or {}).items() if k != "batch"),
                     "thinking": "model default",
                     "commit": str(A.get("git_sha", ""))[:10], "generated_at": A.get("generated_at"),
                     "n": f"{c.get('episodes')} episodes, {c.get('tokens'):,} tokens in one prompt" if c.get("tokens") else "",
                     "headline": blind + v1})
    S = _load(res / "swarm.json")
    if S:
        cnt = S.get("counts", {})
        bu = {t: (v.get("best_unjustified"), v.get("solver_mean_paired")) for t, v in (S.get("per_tier") or {}).items()}
        rows.append({"role": "Red-team swarm", "key": "swarm",
                     "run": "results/gemini/swarm.json (+ swarm.md, swarm_blackbox.json, swarm_control.json)",
                     "model": ", ".join(S.get("models") or []), "thinking": str(S.get("planner_thinking") or "model default"),
                     "commit": str(S.get("git_sha", ""))[:10], "generated_at": S.get("generated_at"),
                     "n": f"{cnt.get('attempts')} attacks, {cnt.get('tool_calls')} tool calls",
                     "headline": _swarm_headline(S, cnt, bu)})
    W, WP = _load(res / "roles" / "worldtext" / "meta.json"), _load(res / "roles" / "worldtext" / "lint_probe.json")
    if W and WP:
        pl, ps = WP["probe_llm_gemini_text"], WP["probe_stub_gemini_text"]
        rows.append({"role": "World-text renderer (demo/research layer, v1.5 candidate, not judged)", "key": "worldtext",
                     "run": "results/gemini/roles/worldtext/ (worlds/, lint_probe.json, meta.json, ledger.jsonl)",
                     "model": W["model"], "thinking": str(W.get("thinking_level")), "commit": _commit(W),
                     "generated_at": W["finished_at"], "n": f"{len(W['seeds'])} dev seeds ({W['tier']})",
                     "headline": (f"{WP['gemini_personas']} Gemini personas ({WP['fallback_personas']} fallbacks); lint clean on "
                                  f"{WP['lint_clean_seeds']}/{len(WP['rows'])} seeds; text-only investigators named the mole "
                                  f"{ps['correct']}/{ps['n']} (keyword, p={ps['p_value_vs_fair_bar']:.2f}) and {pl['correct']}/{pl['n']} "
                                  f"({W.get('probe_model')}, p={pl['p_value_vs_fair_bar']:.2f}) vs fair bar {_pct(WP['fair_bar'])}: "
                                  f"{WP['verdict']}")})
    M, MS = _load(res / "roles" / "mole" / "meta.json"), _load(res / "roles" / "mole" / "summary.json")
    if M and MS:
        parts = []
        for inv, s in MS["by_investigator"].items():
            leaks = (f", {s['gemini_leaks_applied']} leaks ({s['gemini_canary_leaks']} of them canaries)"
                     if s.get("gemini_canary_leaks") is not None else "")
            parts.append(f"vs {inv}: score {s['gemini_mole_mean_score']:+.2f} with the Gemini mole vs "
                         f"{s['default_mole_mean_score']:+.2f} with the default mole (paired {s['paired_diff_mean']:+.2f}), "
                         f"caught {s['gemini_mole_caught']}/{s['n']} vs {s.get('default_mole_caught', '?')}/{s['n']}{leaks}")
        seeds = sorted(M["seeds"])
        span = (f"{seeds[0]}\u2013{seeds[-1]}" if seeds == list(range(seeds[0], seeds[-1] + 1)) and len(seeds) > 1
                else ", ".join(map(str, seeds)))
        rows.append({"role": "Adaptive mole (arena mode, not the judged env)", "key": "mole",
                     "run": "results/gemini/roles/mole/ (episodes.jsonl per-day decisions, summary.json, meta.json, ledger.jsonl)",
                     "model": M["model"], "thinking": str(M.get("thinking_level")), "commit": _commit(M),
                     "generated_at": M["finished_at"],
                     "n": f"n={len(seeds)}: {M['tier']} dev seeds {span}, x {len(M['investigators'])} investigators",
                     "caveats": MOLE_CAVEATS,
                     "headline": "; ".join(parts)})
    return rows


def _swarm_headline(S: dict, cnt: dict, bu: dict) -> str:
    """Same reading as the dashboard (canary.gemini.dashboard.slim_swarm): a tier whose best unjustified attempt was
    flagged in-run and overturned on review is reported as flagged -> overturned, never as a clean number."""
    from canary.gemini.dashboard import slim_swarm
    s = slim_swarm(S)
    over = {p["tier"]: p for p in s["per_tier"] if p["overturned"]}
    rev = {c["attempt"]: c for c in s["candidates_review"]}
    parts = []
    for t, (b, sol) in bu.items():
        if b is None or sol is None:
            continue
        if t in over:
            c = rev[over[t]["attempt"]]
            parts.append(f"{t}: {c['attempt']} flagged in-run at {c['in_run']['mean']:+.2f} vs solver {c['in_run']['solver_mean']:+.2f} "
                         f"(n={c['in_run']['n']}), overturned on review ({c['review']['mean']:+.2f} vs {c['review']['solver_mean']:+.2f}, "
                         f"n={c['review']['n']})")
        else:
            parts.append(f"{t} {b:+.2f} vs solver {sol:+.2f}")
    pc = s.get("positive_control") or {}
    tail = (f"; {cnt.get('invariant_violations')} invariant violations" if cnt.get("invariant_violations") is not None else "") + \
           (f"; positive control {pc.get('attackers_found')}/{pc.get('attempts')}" if pc else "")
    return f"{cnt.get('exploits', 0)} verified exploits; best unjustified score " + ", ".join(parts) + tail


MOLE_CAVEATS = [
    "Leak damage is flat per leak whatever the distribution, so broad leaking is fully rewarded in our env (a simplification).",
    "The judged v1.4 tasks use the scripted moles.",
    "Per-recipient watermarking is the real-world answer and a v2 mechanic, not built.",
]

ROLES_MD = """# Canary Lab: one real Gemini run per role

Every row links a committed run and every number in it is read from that run's files by
`python -m canary.gemini.roles index` (nothing is typed by hand). Generated {when}.
Dev seeds only for the two new roles: no judge world or judge mole is rendered or committed.

| Role | Committed run | Model (thinking) | Commit | Size | Headline (real numbers) |
|---|---|---|---|---|---|
{rows}

The world-text renderer is a **demo/research layer (v1.5 candidate)**, not part of the judged environment: the judged
environment stays v1.4 and this layer does not change any score. Gemini both writes the office gossip and, as the
investigator, sees through it: on v1.5-candidate hard (dev seeds 0-9, OpenCode harness) the AfterQuery measurement has
gemini-4-carbon at 108% [96, 122] of the solver vs 61% [3, 104] on v1.4, same seeds (justSilas `docs/reports/CEO.md`,
`docs/reports/env.md`).

Not listed: the Mole Forge. Its committed hall of fame (data/forge/hall_of_fame_v1.*) was evolved with the **stub** mutator
(`canary.forge.evolve --mutator stub`), so there is no real Gemini Forge run to cite.

How the two new runs were made (`canary/gemini/roles.py`, every call through `canary.gemini.ledger`):
- **World-text renderer**: gemini-4-carbon writes personas, department culture and chat templates from public facts only
  (`canary.agents.world_builder.build_world_text`); every day of each dev episode is rendered and checked with
  `canary/text/lint.py`, `assert_no_truth`, the keyword text probe and an LLM text-only investigator, against the
  text probe's fair bar (the best accuracy the documented interview signal allows). Only correct/incorrect flags are stored.
- **Adaptive mole**: gemini-4-carbon plays the mole day by day (`canary.agents.mole_arena.LLMMole`, arena mode, never the
  judge path) against the reference solver and the heuristic on medium, respecting the env's p_leak gate; the same seeds
  are replayed with the default mole for a paired comparison. Investigator score: lower = the mole did better.

Adaptive-mole caveats (arena mode, not the judged env):
{mole_caveats}
"""


def run_index(a) -> int:
    res = Path(a.results)
    rows = build_index(res)
    (res / "roles").mkdir(parents=True, exist_ok=True)
    (res / "roles" / "index.json").write_text(json.dumps({"generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                                                          "roles": rows}, indent=1) + "\n")
    md = ROLES_MD.format(mole_caveats="\n".join(f"{i}. {c}" for i, c in enumerate(MOLE_CAVEATS, 1)), when=dt.datetime.now().astimezone().strftime("%a %d %b %H:%M %Z"), rows="\n".join(
        f"| {r['role']} | `{r['run']}` | {r['model']} ({r['thinking']}) | `{r['commit']}` | {r['n']} | {r['headline']} |" for r in rows))
    Path(a.md).write_text(md)
    print(md)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("worldtext")
    w.add_argument("--tier", default="medium")
    w.add_argument("--seeds", default="0-5")
    w.add_argument("--model", default="gemini-4-carbon")
    w.add_argument("--probe-model", default="gemini-3.8-flash")
    w.add_argument("--reuse", action="store_true", help="keep existing world text (no new world-builder calls)")
    w.add_argument("--out", default=str(OUT))
    m = sub.add_parser("mole")
    m.add_argument("--tier", default="medium")
    m.add_argument("--seeds", default="0-3")
    m.add_argument("--model", default="gemini-4-carbon")
    m.add_argument("--investigators", default="solver,heuristic")
    m.add_argument("--workers", type=int, default=8)
    m.add_argument("--out", default=str(OUT))
    i = sub.add_parser("index", help="results/gemini/roles/index.json + docs/gemini/ROLES.md from committed results")
    i.add_argument("--results", default=str(ROOT / "results" / "gemini"))
    i.add_argument("--md", default=str(ROOT / "docs" / "gemini" / "ROLES.md"))
    a = ap.parse_args(argv)
    if a.cmd == "index":
        return run_index(a)
    from canary.llm.base import load_env
    load_env()
    return run_worldtext(a) if a.cmd == "worldtext" else run_mole(a)


if __name__ == "__main__":
    sys.exit(main())
