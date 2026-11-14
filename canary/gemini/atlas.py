"""Failure Atlas: Gemini reads every trajectory our agents produced and explains WHY they fail, tied to the
decisions and the solver regret, with every claim checked in code.

    python -m canary.gemini.atlas --runs data/runs/committed data/gemini/ladder \
        [--model gemini-4-carbon] [--cache-model gemini-3.8-flash] [--out results/gemini] [--replay]

Pipeline (each Gemini capability does real work; every call is in the ledger, feature="atlas"):
 1. long context   pack every episode (tool calls, result summaries, agent thought/message text, per-step solver
                   regret + tags + solver top-suspect belief) into one corpus (~800k tokens, models.count_tokens).
 2. context cache  caches.create on --cache-model with the whole corpus; discovery of the failure-mode taxonomy is a
                   one-shot question over it, followed by many more: per-step labels of every high-regret decision,
                   cohort comparison, solver counterfactuals, thinking-level effects. --crosscheck: --model
                   (gemini-4-carbon, no explicit caching) independently re-reads the corpus in <=250k-token shards
                   and merges; its modes are mapped onto the taxonomy. All long calls stream.
 3. multimodal     belief-trace PNG + transcript excerpt -> Gemini localises the divergence step; compared with
                   the code-computed divergence step.
 4. embeddings     gemini-embedding-2 on the agent's own words at high-regret steps; numpy k-means; Gemini names
                   the clusters; purity vs the taxonomy labels and vs the regret tags.
 5. Batch API      the same per-step labels as independent single-step requests (50% price), resumable; agreement
                   between batch and cached labels is reported.
 6. structured output + verification: pydantic schemas everywhere; quotes must appear verbatim (else dropped and
                   counted); regret_share, episode counts and agreement rates are computed in code.
Every response is stored in results/gemini/atlas_cache/ (gzip): --replay rebuilds the atlas offline, no key.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .atlas_data import (HIGH_REGRET, ROOT, Episode, behaviour_stats, excerpt, high_regret_steps, load_corpus, load_snapshot,
                         pack_corpus, save_snapshot, step_line)
from .atlas_gemini import AtlasOps, ReplayMiss
from .atlas_schema import (ClusterNames, Comparison, Counterfactuals, Divergence, ModeMap, SingleLabel, StepLabels,
                           Taxonomy, ThinkingEffects, Verifier, inline_schema, parse)

DEFAULT_RUNS = ["data/runs/committed", "data/gemini/runs"]
SYSTEM = """You are the failure analyst for Canary, an RL environment where an LLM agent (head of security) must catch
one mole among the staff using canary traps (documents with per-recipient variants), access logs, interviews and
the leak feed, then make exactly one accusation. Reward = remaining company value V on a correct accusation, -1 on
a wrong one, 0 for none. A Bayesian reference solver replays every episode: REGRET on a step is the value the agent
lost versus the solver's choice at that point, computed in code from the solver's belief.
Answer ONLY from the corpus. Every quote must be copied character for character from the named episode block:
quotes are checked by a program and any quote that is not verbatim is discarded. Never invent episode ids or steps."""

QUESTION_THINKING = "medium"  # thinking level for new cached questions (discovery recorded at the default level)
TOOL_DECISION = {"plant_canary": "canary_design", "accuse": "accusation_target", "advance_day": "commit_timing",
                 "restrict_access": "restriction", "unrestrict_access": "restriction"}


def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              timeout=5).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


# ------------------------------------------------------------------------------------------------ stats (code)

def cohort_stats(eps: list[Episode]) -> list[dict]:
    by: dict[str, list[Episode]] = defaultdict(list)
    for e in eps:
        by[e.cohort].append(e)
    rows = []
    for c, es in sorted(by.items()):
        n = len(es)
        rows.append({"cohort": c, "family": es[0].family, "model": es[0].model, "harness": es[0].harness,
                     "tiers_version": es[0].tiers_version, "thinking": es[0].thinking_level,
                     "tiers": dict(Counter(e.tier for e in es)), "episodes": n,
                     "score_mean": round(sum(e.score for e in es) / n, 3),
                     "accuracy": round(sum(e.correct for e in es) / n, 3),
                     "accused_rate": round(sum(bool(e.accused) for e in es) / n, 3),
                     "regret_mean": round(sum(e.total_regret for e in es) / n, 4),
                     "rationale": Counter(e.rationale_source for e in es).most_common(1)[0][0]})
    return rows


def stats_table_text(rows: list[dict]) -> str:
    out = ["cohort | episodes | tiers | mean score | accuracy | mean regret | rationale text"]
    for r in rows:
        out.append(f"{r['cohort']} | {r['episodes']} | {r['tiers']} | {r['score_mean']} | {r['accuracy']} | "
                   f"{r['regret_mean']} | {r['rationale']}")
    return "\n".join(out)


def code_divergence_t(ep: Episode) -> int | None:
    """Code's own divergence step: the single highest-regret step (the accusation, if it was wrong)."""
    if not ep.steps:
        return None
    if ep.accused and not ep.correct:
        acc = [s for s in ep.steps if s.tool == "accuse"]
        if acc:
            return acc[-1].t
    best = max(ep.steps, key=lambda s: s.regret)
    return best.t if best.regret > 0 else None


# ------------------------------------------------------------------------------------------------ fallback

FALLBACK_MODES = [
    ("wrong_accusation", "Wrong accusation", "accusation_target",
     "The agent accused an innocent employee (the solver's belief in the accused was low)."),
    ("premature_accusation", "Premature accusation", "commit_timing",
     "The agent accused before the evidence was decisive (solver P(accused) < 0.6)."),
    ("low_information_canary", "Low-information canary split", "canary_design",
     "Canary variants split the suspects worse than the solver's partition, wasting leak evidence."),
    ("over_restriction", "Restricting the unlikely", "restriction",
     "The agent restricted employees the evidence says are very unlikely to be the mole."),
    ("late_commit", "Waiting past a decisive belief", "commit_timing",
     "The agent advanced the day although accusing now was worth more."),
    ("no_accusation", "No accusation", "commit_timing", "The episode ended without an accusation."),
]


def fallback_label(ep: Episode, s) -> str:
    if s.tool == "accuse":
        if ep.accused and not ep.correct and ep.mole:
            return "wrong_accusation"
        return "premature_accusation"
    if s.tool == "plant_canary":
        return "low_information_canary"
    if s.tool in ("restrict_access", "unrestrict_access"):
        return "over_restriction"
    if s.tool == "advance_day":
        return "late_commit"
    return "other"


def fallback_taxonomy() -> Taxonomy:
    from .atlas_schema import Mode
    return Taxonomy(summary="Deterministic fallback (no Gemini): modes are the decision types where regret occurs.",
                    modes=[Mode(id=i, name=n, description=d, decision=dec, mechanism="(fallback: not analysed)",
                                solver_would="(fallback)", evidence=[]) for i, n, dec, d in FALLBACK_MODES])


# ------------------------------------------------------------------------------------------------ the atlas

class Atlas:
    def __init__(self, eps: list[Episode], ops: AtlasOps, model: str, cache_model: str, out: Path,
                 max_tokens: int = 900_000, log=None):
        self.eps, self.ops, self.model, self.cache_model, self.out = eps, ops, model, cache_model, Path(out)
        self.max_tokens = max_tokens
        self.blind = False
        self.log = log or (lambda *a: print(*a, flush=True))
        self.by_id = {e.id: e for e in eps}
        self.text, self.blocks = pack_corpus(eps)
        self.corpus_sha = hashlib.sha256(self.text.encode()).hexdigest()
        self.verifier = Verifier(eps, self.blocks)
        self.cstats = cohort_stats(eps)
        self.behaviour = behaviour_stats(eps)
        self.errors: list[str] = []
        self.result: dict[str, Any] = {}
        self.cache_name: str | None = None
        self.use_cache = False
        self._cache_failed = False
        self.cache_tokens = 0
        self.cached_tokens_used = 0
        self.hr = high_regret_steps(eps)

    # ---- helpers
    def _gen(self, model, contents, schema_model, tag, **kw):
        try:
            r = self.ops.generate(model, contents, schema=inline_schema(schema_model), tag=tag, **kw)
        except ReplayMiss as e:
            self.errors.append(f"{tag}: replay miss ({e})")
            return None
        except Exception as e:  # noqa: BLE001
            self.errors.append(f"{tag}: {type(e).__name__}: {str(e)[:200]}")
            self.log(f"  ! {tag}: {type(e).__name__}: {str(e)[:200]}")
            return None
        self.cached_tokens_used += (r.get("usage") or {}).get("cached_content_token_count", 0)
        parsed, err = parse(r.get("text", ""), schema_model)
        if parsed is None:
            self.errors.append(f"{tag}: invalid structured output ({err})")
        return parsed

    def _ask_cached(self, question: str, schema_model, tag: str):
        """A question against the cached corpus (explicit context cache), else with the corpus inline."""
        if getattr(self, "use_cache", False) and not self._cache_failed:
            # reuse an answer an earlier run recorded at the default thinking level; new calls think at
            # QUESTION_THINKING (default thinking on the 800k-token cache spent up to 63k thinking tokens and
            # ~8 min per question)
            try:
                r = self.ops.generate(self.cache_model, [question], schema=inline_schema(schema_model), tag=tag,
                                      cache_name=None, cache_key=self.corpus_sha, system=None, recorded_only=True)
                t, _ = parse(r.get("text", ""), schema_model)
                if t is not None:
                    return t
            except ReplayMiss:
                pass
            r = self._gen(self.cache_model, [question], schema_model, tag, cache_name=self._lazy_cache,
                          cache_key=self.corpus_sha, system=None, thinking_level=QUESTION_THINKING)
            if r is not None or not self._cache_failed:
                return r
        return self._gen(self.cache_model, [self.text, question], schema_model, tag, system=SYSTEM)

    # ---- 1. long context
    def count(self):
        try:
            self.tokens = self.ops.count_tokens(self.model, self.text)
        except Exception as e:  # noqa: BLE001
            self.errors.append(f"count_tokens: {e}")
            self.tokens = len(self.text) // 4
        self.log(f"corpus: {len(self.eps)} episodes, {len(self.text):,} chars, {self.tokens:,} tokens ({self.model})")

    DISCOVER_Q = ("TASK. Read every episode above. Build a taxonomy of 4-8 mutually exclusive FAILURE MODES that "
                  "explain where these agents lose value against the reference solver. Ground each mode in the "
                  "high-REGRET steps and in the agent's own words (`says:`). For each mode give 3-8 evidence steps "
                  "from different episodes and cohorts where possible, each with a verbatim quote. Prefer modes that "
                  "are about a decision (how canaries are split, when to commit, whom to accuse, whom to restrict, "
                  "what evidence to gather) over generic ones. Do not estimate frequencies or regret: the program "
                  "computes those.")

    @staticmethod
    def _norm_tax(t: Taxonomy) -> Taxonomy:
        seen, uniq = set(), []
        for m in t.modes:
            mid = m.id.strip().lower().replace(" ", "_")[:40]
            if mid in seen or mid == "other":
                continue
            seen.add(mid)
            uniq.append(m.model_copy(update={"id": mid}))
        return Taxonomy(summary=t.summary, modes=uniq[:10])

    def discover(self) -> Taxonomy | None:
        """One-shot discovery over the WHOLE corpus as a question on the context cache (--cache-model)."""
        q = "COHORT STATS (computed in code):\n" + stats_table_text(self.cstats) + "\n\n" + self.DISCOVER_Q
        t = self._ask_cached(q, Taxonomy, "discover:cached")
        return self._norm_tax(t) if t and t.modes else None

    def shards(self, max_tokens: int = 250_000) -> list[tuple[str, list[Episode]]]:
        """Cohorts packed greedily (family order) into shards of <= max_tokens; big cohorts split by episode."""
        ratio = self.tokens / max(1, len(self.text))
        cost = {e.id: len(self.blocks[e.id]) * ratio for e in self.eps}
        by: dict[str, list[Episode]] = defaultdict(list)
        for e in self.eps:
            by[e.cohort].append(e)
        out, cur, cur_t = [], [], 0.0
        for c in sorted(by, key=lambda c: (by[c][0].family, c)):
            for e in by[c]:
                if cur and cur_t + cost[e.id] > max_tokens:
                    out.append(cur)
                    cur, cur_t = [], 0.0
                cur.append(e)
                cur_t += cost[e.id]
        if cur:
            out.append(cur)
        return [(f"shard{i}:" + "+".join(sorted({e.cohort for e in sh})), sh) for i, sh in enumerate(out)]

    def carbon_crosscheck(self, primary: Taxonomy, shard_tokens: int = 250_000) -> dict | None:
        """Cross-check: --model (gemini-4-carbon, no explicit caching) reads the corpus in <=250k-token shards,
        then merges the shard taxonomies in one call; flash maps the merged modes onto the primary taxonomy."""
        shards = self.shards(shard_tokens)

        def one(sh):
            name, eps = sh
            text, _ = pack_corpus(eps)
            stats = stats_table_text(cohort_stats(eps))
            contents = [text, "COHORT STATS (computed in code):\n" + stats + "\n\n" + self.DISCOVER_Q]
            tag = f"discover:{self.model}:{name[:60]}"
            # a default-thinking answer recorded by an earlier run is reused; new calls use LOW thinking, because
            # at the default level gemini-4-carbon spent its whole 32k output budget thinking on a 300k shard
            try:
                r = self.ops.generate(self.model, contents, schema=inline_schema(Taxonomy), system=SYSTEM, tag=tag,
                                      recorded_only=True)
                t, _ = parse(r.get("text", ""), Taxonomy)
                if t:
                    return name, t
            except ReplayMiss:
                pass
            return name, self._gen(self.model, contents, Taxonomy, tag, system=SYSTEM, thinking_level="low")
        with ThreadPoolExecutor(max_workers=4) as ex:
            res = list(ex.map(one, shards))
        got = [(n, t) for n, t in res if t and t.modes]
        if not got:
            return None
        shard_json = json.dumps([{"shard": n, "summary": t.summary, "modes": [m.model_dump() for m in t.modes]}
                                 for n, t in got], ensure_ascii=False)
        merged = self._gen(self.model, [SYSTEM + "\n\nSHARD TAXONOMIES (each from a different slice of the corpus):\n"
                                        + shard_json + "\n\nCOHORT STATS (computed in code):\n"
                                        + stats_table_text(self.cstats) + "\n\nTASK. Merge these into ONE taxonomy "
                                        "of 4-8 mutually exclusive failure modes. Keep evidence (episode, t, quote) "
                                        "exactly as given; do not write new quotes."], Taxonomy,
                           f"discover:{self.model}:merge")
        if not merged:
            return {"shards": [n for n, _ in got], "modes": [], "mapping": []}
        merged = self._norm_tax(merged)
        prim = "\n".join(f"- {m.id}: {m.name}. {m.description}" for m in primary.modes)
        cand = "\n".join(f"- {m.id}: {m.name}. {m.description}" for m in merged.modes)
        mp = self._gen(self.cache_model, ["PRIMARY TAXONOMY:\n" + prim + "\n\nSECOND TAXONOMY (independent "
                                          "reading):\n" + cand + "\n\nFor each SECOND mode give the PRIMARY mode id "
                                          "that describes the same failure, or 'none'."], ModeMap, "discover:map")
        ids = {m.id for m in primary.modes}
        pairs = [p.model_dump() for p in (mp.pairs if mp else []) if p.second_id in {m.id for m in merged.modes}]
        for p in pairs:
            if p["primary_id"] not in ids:
                p["primary_id"] = "none"
        covered = {p["primary_id"] for p in pairs if p["primary_id"] != "none"}
        evid = []
        for m in merged.modes:
            for ev in m.evidence:
                evid.append(self.verifier.check(ev.episode, ev.t, ev.quote, context=f"carbon:{m.id}"))
        return {"model": self.model, "shards": [n for n, _ in got], "n_shards": len(shards),
                "summary": merged.summary,
                "modes": [{"id": m.id, "name": m.name, "description": m.description, "decision": m.decision}
                          for m in merged.modes],
                "mapping": pairs,
                "primary_modes_recovered": len(covered), "primary_modes": len(ids),
                "second_modes_matched": sum(1 for p in pairs if p["primary_id"] != "none"),
                "quotes_verified": sum(e["verified"] for e in evid), "quotes_checked": len(evid)}

    # ---- 2. context cache
    def open_cache(self):
        """Explicit context caching, created lazily on the first cached question that is not already recorded
        (so a rerun that replays every answer creates no cache)."""
        import threading
        self.use_cache = True
        self._cache_lock = threading.Lock()
        self._cache_failed = False
        self.cache_tokens = self.ops.recorded_cache_tokens(self.cache_model, self.text, SYSTEM)

    def _lazy_cache(self) -> str | None:
        with self._cache_lock:
            if self.cache_name is None and not self._cache_failed:
                try:
                    self.cache_name, self.cache_tokens = self.ops.create_cache(self.cache_model, self.text, SYSTEM)
                    self.log(f"context cache on {self.cache_model}: {self.cache_tokens:,} tokens ({self.cache_name})")
                except Exception as e:  # noqa: BLE001
                    self._cache_failed = True
                    self.errors.append(f"caches.create: {type(e).__name__}: {str(e)[:200]}")
                    self.log(f"  ! cache create failed ({e}); questions will send the corpus inline")
            if self.cache_name is None:
                raise RuntimeError("context cache unavailable")
            return self.cache_name

    def taxonomy_text(self, tax: Taxonomy) -> str:
        return "\n".join(f"- {m.id}: {m.name} ({m.decision}). {m.description}" for m in tax.modes) + \
            "\n- other: none of the above"

    def label_cached(self, tax: Taxonomy, chunk: int = 40) -> dict[tuple[str, int], dict]:
        steps = self.hr
        ids = {m.id for m in tax.modes} | {"other"}
        out: dict[tuple[str, int], dict] = {}
        chunks = [steps[i:i + chunk] for i in range(0, len(steps), chunk)]

        def one(ci_ch):
            ci, ch = ci_ch
            lst = "\n".join(f"{ep.id} t={s.t} {s.tool} regret={s.regret:.3f}" for ep, s in ch)
            q = (f"TAXONOMY:\n{self.taxonomy_text(tax)}\n\nLabel each of these {len(ch)} high-regret decision steps "
                 f"with exactly one mode id. Find each step in its episode block above; read the steps before it and "
                 f"the agent's words. Quote 5-30 words verbatim from that step's line or the agent's `says:` text at "
                 f"or just before it.\n{lst}")
            return self._ask_cached(q, StepLabels, f"label_cached:{ci}")
        with ThreadPoolExecutor(max_workers=6) as ex:
            results = list(ex.map(one, enumerate(chunks)))
        for ch, res in zip(chunks, results):
            want = {(ep.id, s.t) for ep, s in ch}
            for lab in (res.labels if res else []):
                k = (lab.episode, lab.t)
                if k not in want or k in out:
                    continue
                mode = lab.mode if lab.mode in ids else "other"
                v = self.verifier.check(lab.episode, lab.t, lab.quote, context="label_cached")
                out[k] = {"mode": mode, "confidence": lab.confidence, "quote": lab.quote, "verified": v["verified"],
                          "step_verified": v["step_verified"], "source": v["source"], "explanation": lab.explanation}
        self.log(f"cached labels: {len(out)}/{len(steps)} steps")
        return out

    # ---- 5. Batch API
    def label_batch(self, tax: Taxonomy, timeout_s: float, state_file: Path) -> dict[tuple[str, int], dict] | None:
        ids = {m.id for m in tax.modes} | {"other"}
        prompts = []
        for ep, s in self.hr:
            prompts.append(f"{SYSTEM}\n\nTAXONOMY:\n{self.taxonomy_text(tax)}\n\nEXCERPT (the decision to label is "
                           f"marked >>>):\n{excerpt(ep, s.t)}\n\nLabel the >>> decision (t={s.t}, regret "
                           f"{s.regret:.3f}) with exactly one mode id. Quote verbatim from the >>> line or the "
                           f"agent's words right before it.")
        try:
            res = self.ops.batch_generate(self.cache_model, prompts, inline_schema(SingleLabel), timeout_s=timeout_s,
                                          state_file=state_file,
                                          on_poll=lambda st, el: self.log(f"  batch {st} {el:.0f}s"))
        except (ReplayMiss, TimeoutError) as e:
            self.errors.append(f"batch: {e}")
            self.log(f"  batch pending/unavailable: {e}")
            return None
        except Exception as e:  # noqa: BLE001
            self.errors.append(f"batch: {type(e).__name__}: {str(e)[:200]}")
            self.log(f"  ! batch failed: {e}")
            return None
        out = {}
        for (ep, s), r in zip(self.hr, res):
            if not r:
                continue
            lab, _ = parse(r.get("text", ""), SingleLabel)
            if lab is None:
                continue
            v = self.verifier.check(ep.id, s.t, lab.quote, context="label_batch")
            out[(ep.id, s.t)] = {"mode": lab.mode if lab.mode in ids else "other", "confidence": lab.confidence,
                                 "quote": lab.quote, "verified": v["verified"], "step_verified": v["step_verified"],
                                 "source": v["source"], "explanation": lab.explanation}
        self.log(f"batch labels: {len(out)}/{len(self.hr)} steps")
        return out

    # ---- questions on the cache
    def compare(self, tax: Taxonomy) -> Comparison | None:
        beh = "\n".join(f"{c}: {json.dumps(d)}" for c, d in self.behaviour.items())
        q = (f"TAXONOMY:\n{self.taxonomy_text(tax)}\n\nCOHORT STATS (computed in code):\n{stats_table_text(self.cstats)}"
             f"\n\nDECISION STATISTICS PER COHORT (computed in code):\n{beh}"
             "\n\nTASK. Compare how each cohort plays and fails. Cohorts on different tiers_versions played under "
             "different rules (v1.2 showed same-day V drops; v1.4 hard has 40 staff and 3-variant canaries): say so "
             "and never treat them as one pool. Give each cohort 1-3 verbatim quotes (cohorts without agent text: "
             "quote step lines). End with the single most important difference between Gemini and GPT/Grok agents.")
        return self._ask_cached(q, Comparison, "compare")

    def counterfactuals(self, n: int = 12) -> Counterfactuals | None:
        picks, seen = [], Counter()
        for ep, s in self.hr:  # top regret, at most 2 per cohort for spread
            if seen[ep.cohort] >= 2:
                continue
            picks.append((ep, s))
            seen[ep.cohort] += 1
            if len(picks) >= n:
                break
        lst = "\n".join(f"{ep.id} t={s.t} {s.tool} regret={s.regret:.3f} solver_top={s.top}:{s.p_top}" for ep, s in picks)
        q = ("TASK. For each step below, say what the agent did, what the Bayesian reference solver would have done at "
             "that step (canary: a split where each variant group holds similar posterior mass; accusation: only the "
             "top suspect and only once its posterior is high; waiting: only while more evidence is worth more than "
             "the leak damage), and the belief or reasoning error behind the difference. Quote verbatim.\n" + lst)
        self._cf_picks = picks
        return self._ask_cached(q, Counterfactuals, "counterfactual")

    def thinking(self, tax: Taxonomy) -> ThinkingEffects | None:
        lv = Counter((e.model, e.thinking_level) for e in self.eps)
        models = {m for (m, lvl) in lv if sum(1 for (m2, _) in lv if m2 == m) >= 2}
        if not models:
            return None
        q = (f"TAXONOMY:\n{self.taxonomy_text(tax)}\n\nSome models were run at several thinking levels (episode header "
             f"`thinking=`): {sorted(models)}. TASK. For each such model, compare its episodes across thinking levels: "
             "which failure modes shrink with more thinking and which do not. Quote verbatim.")
        return self._ask_cached(q, ThinkingEffects, "thinking")

    # ---- 3. multimodal
    def charts_and_localise(self, n: int = 8, chart_dir: Path | None = None) -> list[dict]:
        from .atlas_charts import pick_showcase, render_belief_chart
        chart_dir = chart_dir or self.out / "atlas_charts"
        chart_dir.mkdir(parents=True, exist_ok=True)
        shows = pick_showcase(self.eps, n)

        def one(ep):
            png = render_belief_chart(ep, chart_dir / f"{ep.id.replace('#', '_')}.png")  # atlas copy, with regret
            ct = code_divergence_t(ep)
            if self.blind:
                # Gemini's copy shows belief curves only and the excerpt has no regret numbers, so agreement with
                # the code's highest-regret step is not given away
                png = render_belief_chart(ep, None, show_regret=False)
                ex = "\n".join(re.sub(r" \| REGRET [0-9.]+( \[[^\]]*\])?", "", step_line(s))
                               + (f"\n   says: {s.rationale[:400]}" if s.rationale else "")
                               for s in ep.steps if s.tool in ("accuse", "plant_canary", "check_leak_feed",
                                                               "restrict_access", "advance_day"))
            else:  # v1 (recorded): chart with regret panel, excerpt with regret
                ex = "\n".join(step_line(s) + (f"\n   says: {s.rationale[:400]}" if s.rationale else "")
                               for s in ep.steps if s.regret >= 0.001 or s.tool in ("accuse", "plant_canary",
                                                                                    "check_leak_feed"))
            q = (f"{SYSTEM}\n\nThe image is the belief trace of episode {ep.id}: the reference solver's posterior over "
                 "time (blue = true mole, orange = the employee the agent accused if innocent, gray = solver's top "
                 "suspect), canaries as violet triangles" + ("" if self.blind else ", regret per step in the lower panel")
                 + ". Below are the key steps "
                 "of the episode. TASK: localise the step t where the agent's course departs from what the solver's "
                 "belief supports, describe what the chart shows there, and quote the agent verbatim.\n\n"
                 + ex[:60000])
            d = self._gen(self.cache_model, [{"image": png, "mime": "image/png"}, q], Divergence, f"localise:{ep.id}")
            acc = [s for s in ep.steps if s.tool == "accuse"]
            backed = bool(acc and not ep.correct and (acc[-1].p_accusee or 0) >= 0.5)
            row = {"episode": ep.id, "chart": f"atlas_charts/{ep.id.replace('#', '_')}.png", "code_t": ct,
                   "evidence_backed_wrong": backed,
                   "cohort": ep.cohort, "correct": ep.correct, "score": ep.score}
            if d:
                v = self.verifier.check(ep.id, None, d.quote, context="localise")
                row.update({"gemini_t": d.divergence_t, "what_chart_shows": d.what_chart_shows,
                            "what_agent_believed": d.what_agent_believed, "quote": d.quote,
                            "verified": v["verified"],
                            "agrees": ct is not None and abs(d.divergence_t - ct) <= 3})
            return row
        with ThreadPoolExecutor(max_workers=4) as ex:
            rows = list(ex.map(one, shows))
        return rows

    # ---- 4. embeddings
    def embed_clusters(self, labels: dict, k: int = 6, max_texts: int = 300) -> dict | None:
        import numpy as np
        items = [(ep, s) for ep, s in self.hr if s.rationale.strip()][:max_texts]
        if len(items) < k * 3:
            return None
        texts = [" ".join(s.rationale.split())[:2000] for _, s in items]
        try:
            vecs = np.array(self.ops.embed(texts), dtype=float)
        except Exception as e:  # noqa: BLE001
            self.errors.append(f"embed: {type(e).__name__}: {str(e)[:200]}")
            return None
        if vecs.ndim != 2 or len(vecs) != len(items):
            self.errors.append(f"embed: got {len(vecs)} vectors for {len(items)} texts")
            return None
        vecs /= np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-12
        assign = kmeans(vecs, k, seed=0)
        clusters = []
        for c in range(k):
            idx = [i for i in range(len(items)) if assign[i] == c]
            if not idx:
                continue
            cen = vecs[idx].mean(0)
            near = sorted(idx, key=lambda i: -float(vecs[i] @ cen))[:5]
            clusters.append({"cluster": c, "size": len(idx), "idx": idx, "examples": near})
        sample = "\n\n".join(f"CLUSTER {c['cluster']} ({c['size']} steps):\n" + "\n".join(
            f"- [{items[i][0].id} t={items[i][1].t} {items[i][1].tool}] {texts[i][:350]}" for i in c["examples"])
            for c in clusters)
        names = self._gen(self.cache_model, [SYSTEM + "\n\nThese are the agents' own words at high-regret steps, "
                                             "grouped by embedding similarity. Name each cluster by the shared "
                                             "reasoning pattern.\n\n" + sample], ClusterNames, "name_clusters")
        nm = {c.cluster: c for c in (names.clusters if names else [])}
        mode_of = {k_: v["mode"] for k_, v in labels.items()}
        out = []
        for c in clusters:
            modes = Counter(mode_of.get((items[i][0].id, items[i][1].t), "unlabelled") for i in c["idx"])
            tags = Counter((items[i][1].tags[0] if items[i][1].tags else items[i][1].tool) for i in c["idx"])
            regret = sum(items[i][1].regret for i in c["idx"])
            out.append({"cluster": c["cluster"], "name": nm[c["cluster"]].name if c["cluster"] in nm else f"cluster {c['cluster']}",
                        "description": nm[c["cluster"]].description if c["cluster"] in nm else "",
                        "size": c["size"], "regret": round(regret, 4),
                        "cohorts": dict(Counter(items[i][0].cohort for i in c["idx"]).most_common(4)),
                        "top_modes": dict(modes.most_common(3)), "top_tags": dict(tags.most_common(3)),
                        "examples": [{"episode": items[i][0].id, "t": items[i][1].t, "text": texts[i][:240]}
                                     for i in c["examples"][:2]]})
        ys_mode = [mode_of.get((ep.id, s.t), "unlabelled") for ep, s in items]
        ys_tag = [(s.tags[0] if s.tags else s.tool) for _, s in items]
        return {"k": k, "n": len(items), "model": "gemini-embedding-2", "clusters": out,
                "purity_vs_modes": purity(assign, ys_mode), "purity_vs_tags": purity(assign, ys_tag),
                "nmi_vs_modes": nmi(assign, ys_mode), "nmi_vs_tags": nmi(assign, ys_tag)}

    # ---- assemble
    def modes_table(self, tax: Taxonomy, labels: dict, source: str) -> list[dict]:
        total = sum(e.total_regret for e in self.eps) or 1.0
        mode_regret: dict[str, float] = defaultdict(float)
        mode_eps: dict[str, set] = defaultdict(set)
        mode_tools: dict[str, Counter] = defaultdict(Counter)
        mode_cohort: dict[str, Counter] = defaultdict(Counter)
        reg = {(ep.id, s.t): (ep, s) for ep, s in self.hr}
        for k, lab in labels.items():
            if k not in reg:
                continue
            ep, s = reg[k]
            mode_regret[lab["mode"]] += s.regret
            mode_eps[lab["mode"]].add(ep.id)
            mode_tools[lab["mode"]][s.tool] += 1
            mode_cohort[lab["mode"]][ep.cohort] += s.regret
        # terminal no-accusation regret is not a step: attributed to its own bucket by code
        term = sum(e.terminal_regret for e in self.eps)
        rows = []
        for m in tax.modes:
            quotes = []
            for ev in m.evidence:
                v = self.verifier.check(ev.episode, ev.t, ev.quote, context=f"mode:{m.id}")
                if v["verified"]:
                    quotes.append({"episode": ev.episode, "t": ev.t, "quote": ev.quote, "why": ev.why,
                                   "verified": True, "step_verified": v["step_verified"], "source": v["source"]})
            # plus verified label quotes (highest regret first) until 4 quotes
            for (eid, t), lab in sorted(labels.items(), key=lambda kv: (kv[1].get("source") != "agent_words",
                                                                         -(reg[kv[0]][1].regret if kv[0] in reg else 0))):
                if len(quotes) >= 4:
                    break
                if lab["mode"] == m.id and lab["verified"] and not any(q["episode"] == eid and q["t"] == t for q in quotes):
                    quotes.append({"episode": eid, "t": t, "quote": lab["quote"], "why": lab["explanation"],
                                   "verified": True, "step_verified": lab["step_verified"],
                                   "source": lab.get("source", "step_record"), "from": "label"})
            # the agent's own words first, then step records
            quotes.sort(key=lambda q: q.get("source") != "agent_words")
            tools = mode_tools[m.id]
            code_decision = TOOL_DECISION.get(tools.most_common(1)[0][0], "other") if tools else m.decision
            rows.append({"id": m.id, "name": m.name, "description": m.description, "decision": m.decision,
                         "decision_by_code": code_decision, "mechanism": m.mechanism, "solver_would": m.solver_would,
                         "regret": round(mode_regret[m.id], 4), "regret_share": round(mode_regret[m.id] / total, 4),
                         "episodes": len(mode_eps[m.id]), "steps": sum(tools.values()),
                         "tools": dict(tools.most_common()),
                         "regret_by_cohort": {c: round(v, 4) for c, v in mode_cohort[m.id].most_common()},
                         "quotes": quotes, "chart": None, "label_source": source})
        rows.sort(key=lambda r: -r["regret"])
        if mode_regret.get("other"):
            rows.append({"id": "other", "name": "Other / unclassified", "description": "High-regret steps Gemini did "
                         "not assign to a mode.", "decision": "other", "decision_by_code": "other", "mechanism": "",
                         "solver_would": "", "regret": round(mode_regret["other"], 4),
                         "regret_share": round(mode_regret["other"] / total, 4), "episodes": len(mode_eps["other"]),
                         "steps": sum(mode_tools["other"].values()), "tools": dict(mode_tools["other"]),
                         "regret_by_cohort": {}, "quotes": [], "chart": None, "label_source": source})
        if term:
            rows.append({"id": "no_accusation_terminal", "name": "Ended without accusing (terminal)",
                         "description": "Value forgone by ending the episode with no accusation (not a single step).",
                         "decision": "commit_timing", "decision_by_code": "commit_timing", "mechanism": "",
                         "solver_would": "accuse the top suspect", "regret": round(term, 4),
                         "regret_share": round(term / total, 4),
                         "episodes": sum(1 for e in self.eps if e.terminal_regret), "steps": 0, "tools": {},
                         "regret_by_cohort": {}, "quotes": [], "chart": None, "label_source": "code"})
        return rows

    def cohort_modes(self, labels: dict) -> dict[str, dict[str, float]]:
        """Per cohort: share of that cohort's total regret in each mode (code)."""
        tot = defaultdict(float)
        for e in self.eps:
            tot[e.cohort] += e.total_regret
        reg = {(ep.id, s.t): (ep, s) for ep, s in self.hr}
        out: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for k, lab in labels.items():
            if k in reg:
                ep, s = reg[k]
                out[ep.cohort][lab["mode"]] += s.regret
        return {c: {m: round(v / tot[c], 4) for m, v in sorted(d.items(), key=lambda kv: -kv[1]) if tot[c]}
                for c, d in out.items()}


LEVELS = ["minimal", "low", "medium", "high", "xhigh", "default"]


def thinking_table(eps: list[Episode], cohort_modes: dict) -> list[dict]:
    """Code-computed: per (model, harness, version) with >= 2 thinking levels, one row per level."""
    groups: dict[tuple, dict[str, list[Episode]]] = defaultdict(lambda: defaultdict(list))
    for e in eps:
        groups[(e.model, e.harness, e.tiers_version)][e.thinking_level].append(e)
    rows = []
    for (m, h, v), lv in sorted(groups.items()):
        if len(lv) < 2:
            continue
        for level in sorted(lv, key=lambda x: LEVELS.index(x) if x in LEVELS else 99):
            es = lv[level]
            n = len(es)
            acc = [s for e in es for s in e.steps if s.tool == "accuse"]
            rows.append({"model": m, "harness": h, "tiers_version": v, "thinking": level, "episodes": n,
                         "tiers": dict(Counter(e.tier for e in es)),
                         "score_mean": round(sum(e.score for e in es) / n, 3),
                         "accuracy": round(sum(e.correct for e in es) / n, 3),
                         "regret_mean": round(sum(e.total_regret for e in es) / n, 4),
                         "p_accused_mean": round(sum((s.p_accusee or 0) for s in acc) / len(acc), 3) if acc else None,
                         "canary_regret_per_episode": round(sum(s.regret for e in es for s in e.steps
                                                                if s.tool == "plant_canary") / n, 4),
                         "mode_share": cohort_modes.get(es[0].cohort, {})})
    return rows


def fit_budget(eps: list[Episode], budget_tokens: int, chars_per_token: float = 2.52) -> list[Episode]:
    """Cap episodes per cohort (lowest seeds kept, tiers balanced) until the packed corpus fits the budget; the
    atlas reports the corpus it actually read."""
    by: dict[str, list[Episode]] = defaultdict(list)
    for e in eps:
        by[e.cohort].append(e)
    for c in by:  # interleave tiers so a cap keeps both
        tiers = sorted({e.tier for e in by[c]})
        lists = [sorted((e for e in by[c] if e.tier == t), key=lambda e: e.seed) for t in tiers]
        by[c] = [e for grp in __import__("itertools").zip_longest(*lists) for e in grp if e is not None]
    size = {e.id: len(pack_corpus([e])[0]) / chars_per_token for e in eps}
    cap = max(len(v) for v in by.values())
    while cap > 1:
        keep = [e for c in by for e in by[c][:cap]]
        if sum(size[e.id] for e in keep) <= budget_tokens:
            return sorted(keep, key=lambda e: e.id)
        cap -= 1
    return sorted([e for c in by for e in by[c][:1]], key=lambda e: e.id)


def ledger_spend() -> dict:
    """All atlas rows in the local usage ledger (every live run that produced the recorded responses)."""
    try:
        from .ledger import read_ledger
        rows = [r for r in read_ledger() if r.get("feature") == "atlas"]
    except Exception:  # noqa: BLE001
        return {}
    by = Counter(r["kind"] for r in rows)
    return {"calls": len(rows), "failed": sum(1 for r in rows if not r.get("ok")),
            "cost_usd": round(sum(r.get("cost_usd", 0) for r in rows), 2),
            "in": sum(r.get("in", 0) for r in rows), "cached": sum(r.get("cached", 0) for r in rows),
            "thinking": sum(r.get("thinking", 0) for r in rows), "by_kind": dict(by)}


def kmeans(X, k: int, seed: int = 0, iters: int = 50):
    import numpy as np
    rng = np.random.default_rng(seed)
    # k-means++ init
    C = [X[rng.integers(len(X))]]
    for _ in range(1, k):
        d = np.min(((X[:, None, :] - np.array(C)[None]) ** 2).sum(-1), axis=1)
        C.append(X[rng.choice(len(X), p=d / d.sum() if d.sum() > 0 else None)])
    C = np.array(C)
    a = np.zeros(len(X), dtype=int)
    for _ in range(iters):
        a_new = ((X[:, None, :] - C[None]) ** 2).sum(-1).argmin(1)
        if (a_new == a).all() and _ > 0:
            break
        a = a_new
        for j in range(k):
            if (a == j).any():
                C[j] = X[a == j].mean(0)
    return a.tolist()


def purity(assign: list[int], ys: list[str]) -> float:
    by = defaultdict(Counter)
    for a, y in zip(assign, ys):
        by[a][y] += 1
    return round(sum(c.most_common(1)[0][1] for c in by.values()) / max(1, len(ys)), 4)


def nmi(assign: list, ys: list) -> float:
    import math
    n = len(ys)
    if not n:
        return 0.0
    pa, pb, pab = Counter(assign), Counter(ys), Counter(zip(assign, ys))
    mi = sum(c / n * math.log((c / n) / (pa[a] / n * pb[b] / n)) for (a, b), c in pab.items())
    ha = -sum(c / n * math.log(c / n) for c in pa.values())
    hb = -sum(c / n * math.log(c / n) for c in pb.values())
    return round(mi / math.sqrt(ha * hb), 4) if ha > 0 and hb > 0 else 0.0


def label_agreement(a: dict, b: dict) -> dict:
    keys = set(a) & set(b)
    agree = sum(a[k]["mode"] == b[k]["mode"] for k in keys)
    return {"n": len(keys), "agree": agree, "rate": round(agree / len(keys), 4) if keys else None}


# ------------------------------------------------------------------------------------------------ run

def run(args) -> dict:
    t0 = time.time()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cache_dir = Path(args.cache_dir) if args.cache_dir else out / "atlas_cache"
    snap = cache_dir / "corpus.json.gz"
    if args.replay and snap.exists():
        eps = load_snapshot(snap)  # the exact corpus the recorded responses were made from
    else:
        runs = [str(ROOT / r) if not Path(r).is_absolute() else r for r in args.runs]
        eps = load_corpus([r for r in runs if Path(r).exists()])
    if getattr(args, "exclude", None):
        eps = [e for e in eps if not any(x in e.cohort for x in args.exclude)]
    if getattr(args, "budget_tokens", 0) and not (args.replay and snap.exists()):
        eps = fit_budget(eps, args.budget_tokens)
    if args.limit:
        random.Random(0).shuffle(eps)
        eps = sorted(eps[:args.limit], key=lambda e: e.id)
    if not args.replay:
        save_snapshot(eps, snap)
    ops = AtlasOps(replay=args.replay, cache_dir=cache_dir)
    A = Atlas(eps, ops, args.model, args.cache_model, out, max_tokens=args.max_tokens)
    A.blind = bool(getattr(args, "blind_localise", False))
    A.count()
    if not args.no_cache:
        A.open_cache()
    tax = A.discover()
    if tax is None:
        if not args.allow_fallback:
            A.log("discovery failed; refusing to publish a deterministic-fallback atlas (errors: "
                  f"{A.errors[-3:]}). Rerun, or pass --allow-fallback for a non-Gemini draft.")
            ops.delete_cache(A.cache_name)
            raise SystemExit(2)
        A.log("  discovery failed -> deterministic fallback taxonomy (--allow-fallback)")
        tax = fallback_taxonomy()
    A.log(f"taxonomy: {[m.id for m in tax.modes]}")
    xcheck_pool = ThreadPoolExecutor(max_workers=2)
    xcheck_f = xcheck_pool.submit(A.carbon_crosscheck, tax, args.shard_tokens) \
        if args.crosscheck and args.model != args.cache_model else None
    labels_cached = A.label_cached(tax) if not args.skip_labels else {}
    # the Batch API job runs server-side while the cached questions and charts proceed
    batch_f = xcheck_pool.submit(A.label_batch, tax, args.batch_timeout, cache_dir / "batch_state.json") \
        if args.batch else None
    comparison = A.compare(tax)
    cfs = A.counterfactuals()
    thinking = A.thinking(tax)
    loc = A.charts_and_localise(args.charts) if args.charts else []
    labels_batch = batch_f.result() if batch_f is not None else None
    labels = labels_batch if labels_batch else labels_cached
    if not labels:
        labels = {(ep.id, s.t): {"mode": fallback_label(ep, s), "confidence": 1.0, "quote": step_line(s),
                                 "verified": True, "step_verified": True, "explanation": "deterministic fallback"}
                  for ep, s in A.hr}
        if not any(m.id in {"wrong_accusation", "low_information_canary"} for m in tax.modes):
            tax = Taxonomy(summary=tax.summary, modes=tax.modes + fallback_taxonomy().modes)
        source = "fallback"
    else:
        source = "batch" if labels_batch else "cached"
    clusters = A.embed_clusters(labels) if args.embed else None
    modes = A.modes_table(tax, labels, source)
    # charts: attach a showcase chart to each mode (the episode with the most regret in that mode, if charted)
    charted = {r["episode"]: r["chart"] for r in loc}
    reg = {(ep.id, s.t): s.regret for ep, s in A.hr}
    for m in modes:
        best = sorted(((reg.get(k, 0), k[0]) for k, lab in labels.items() if lab["mode"] == m["id"]), reverse=True)
        m["chart"] = next((charted[e] for _, e in best if e in charted), None)
    cf_rows = []
    if cfs:
        valid = {(ep.id, s.t): (ep, s) for ep, s in getattr(A, "_cf_picks", [])}
        for it in cfs.items:
            if (it.episode, it.t) not in valid:
                continue
            v = A.verifier.check(it.episode, it.t, it.quote, context="counterfactual")
            ep, s = valid[(it.episode, it.t)]
            cf_rows.append({**it.model_dump(), "regret": s.regret, "tool": s.tool, "cohort": ep.cohort,
                            "verified": v["verified"], "step_verified": v["step_verified"]})
    comp = None
    if comparison:
        cohorts = {r["cohort"] for r in A.cstats}
        comp = {"cross_family_finding": comparison.cross_family_finding, "caveats": comparison.caveats, "cohorts": []}
        for c in comparison.cohorts:
            ev = [{**A.verifier.check(e.episode, e.t, e.quote, context=f"compare:{c.cohort}"), "why": e.why}
                  for e in c.evidence]
            comp["cohorts"].append({"cohort": c.cohort, "known": c.cohort in cohorts, "dominant_modes": c.dominant_modes,
                                    "behaviour": c.behaviour, "quotes": [q for q in ev if q["verified"]]})
    think = None
    if thinking:
        think = {"summary": thinking.summary, "findings": []}
        for f in thinking.findings:
            ev = [A.verifier.check(e.episode, e.t, e.quote, context="thinking") for e in f.evidence]
            think["findings"].append({**f.model_dump(exclude={"evidence"}), "quotes": [q for q in ev if q["verified"]]})
    crosscheck = None
    if xcheck_f is not None:
        try:
            crosscheck = xcheck_f.result()
        except Exception as e:  # noqa: BLE001
            A.errors.append(f"crosscheck: {type(e).__name__}: {str(e)[:200]}")
    xcheck_pool.shutdown(wait=False)
    loc_n = [r for r in loc if "gemini_t" in r]
    result = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "git_sha": git_sha(),
        "ledger_run_ids": sorted(ops.source_run_ids),
        "models": {"long_context": args.model, "cache": args.cache_model, "embedding": "gemini-embedding-2",
                   "batch": args.cache_model},
        "corpus": {"episodes": len(eps), "tokens": A.tokens,
                   "cached_questions": 1 + (len(A.hr) + 39) // 40 * bool(labels_cached) + (comparison is not None)
                   + (cfs is not None) + (thinking is not None), "chars": len(A.text), "cached_tokens": A.cached_tokens_used,
                   "cache_size_tokens": A.cache_tokens, "high_regret_steps": len(A.hr),
                   "high_regret_threshold": HIGH_REGRET, "total_regret": round(sum(e.total_regret for e in eps), 4),
                   "high_regret_share": round(sum(s.regret for _, s in A.hr) / max(1e-9, sum(e.total_regret for e in eps)), 4),
                   "cohorts": A.cstats, "sha256": A.corpus_sha},
        "summary": tax.summary,
        "modes": modes,
        "cohort_mode_share": A.cohort_modes(labels),
        "cohort_behaviour": A.behaviour,
        "thinking_table": thinking_table(eps, A.cohort_modes(labels)),
        "comparison": comp,
        "counterfactuals": cf_rows,
        "thinking": think,
        "localisation": {"rows": loc, "n": len(loc_n), "agree_within_3_steps": sum(bool(r.get("agrees")) for r in loc_n),
                         "rate": round(sum(bool(r.get("agrees")) for r in loc_n) / len(loc_n), 4) if loc_n else None},
        "clusters": clusters,
        "crosscheck": crosscheck,
        "discovery": {"mode": "one-shot over the whole corpus, as a question on the explicit context cache",
                      "model": None if source == "fallback" else args.cache_model},
        "labels": {"source": source, "n": len(labels), "cached_n": len(labels_cached),
                   "batch_n": len(labels_batch) if labels_batch else 0,
                   "batch_vs_cached": label_agreement(labels_batch, labels_cached) if labels_batch else None,
                   "batch_job": ops.last_batch or None,
                   "steps": [{"episode": k[0], "t": k[1], **v} for k, v in sorted(labels.items())]},
        "verification": A.verifier.summary(),
        "dropped_quotes": A.verifier.dropped[:200],
        "human_agreement": {"status": "pending"},
        "spend": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in ops.stats.items()},
        "spend_ledger": ledger_spend(),
        "errors": A.errors,
        "elapsed_s": round(time.time() - t0, 1),
        "replay": bool(args.replay),
    }
    prev = out / "atlas.json"
    if prev.exists():  # keep a human agreement score that atlas_agreement already wrote
        try:
            ha = json.loads(prev.read_text()).get("human_agreement")
            if ha and ha.get("status") != "pending":
                result["human_agreement"] = ha
        except json.JSONDecodeError:
            pass
    ops.delete_cache(A.cache_name)
    (out / "atlas.json").write_text(json.dumps(result, indent=1, default=str))
    from .atlas_report import render_md
    (out / "atlas.md").write_text(render_md(result))
    A.log(f"wrote {out/'atlas.json'} and atlas.md: {len(modes)} modes, verification {result['verification']}, "
          f"spend ${ops.stats['cost_usd']:.2f}, {ops.stats['calls']} calls, {ops.stats['replayed']} replayed")
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", nargs="+", default=DEFAULT_RUNS)
    ap.add_argument("--model", default="gemini-4-carbon", help="cross-check reader (sharded long context)")
    ap.add_argument("--cache-model", default="gemini-3.8-flash",
                    help="model with createCachedContent for the cached questions, labels, batch, multimodal")
    ap.add_argument("--out", default=str(ROOT / "results" / "gemini"))
    ap.add_argument("--cache-dir", default=None, help="response cache (default results/gemini/atlas_cache)")
    ap.add_argument("--replay", action="store_true", help="offline: answer every call from the response cache")
    ap.add_argument("--max-tokens", type=int, default=900_000, help="shard by family above this")
    ap.add_argument("--limit", type=int, default=0, help="random subset of episodes (smoke)")
    ap.add_argument("--charts", type=int, default=8)
    ap.add_argument("--no-cache", action="store_true", help="skip explicit context caching")
    ap.add_argument("--skip-labels", action="store_true")
    ap.add_argument("--batch", action="store_true", help="also label every high-regret step via the Batch API")
    ap.add_argument("--batch-timeout", type=float, default=1800)
    ap.add_argument("--embed", action="store_true", help="embedding clusters of the agents' words")
    ap.add_argument("--crosscheck", action="store_true",
                    help="independent --model reading in <= --shard-tokens shards + merge, mapped onto the taxonomy")
    ap.add_argument("--shard-tokens", type=int, default=250_000)
    ap.add_argument("--blind-localise", action="store_true",
                    help="multimodal localisation without regret in the chart/excerpt (v2)")
    ap.add_argument("--exclude", nargs="*", default=[], help="drop cohorts whose id contains any of these")
    ap.add_argument("--budget-tokens", type=int, default=0,
                    help="cap episodes per cohort so the corpus fits (one cache holds <= ~1M tokens)")
    ap.add_argument("--allow-fallback", action="store_true",
                    help="write a deterministic (non-Gemini) atlas if discovery fails (never publish it)")
    ap.add_argument("--blind", action="store_true",
                    help="blind re-run: only what the agents saw/did/said; recovery scored in code (atlas_blind.py)")
    a = ap.parse_args(argv)
    if a.blind:
        from .atlas_blind import run as run_blind
        if not a.cache_dir:
            a.cache_dir = str(Path(a.out) / "atlas_cache_blind")
        run_blind(a)
        return 0
    run(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
