from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary import rules
from canary.agents import analyst
from canary.agents._common import resolve_client
from canary.agents.runlog import git_sha
from canary.analysis.tags import to_result
from canary.env import Env
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS
from canary.solver.policy import SolverPolicy, accuse_value
from canary.solver.regret import _gini, attribute, q_continue

FRONTIER_FAMILIES = ("codex-gpt-5.5", "gpt-5.5", "grok", "opencode-gpt-5.6-sol")
DEFAULT_OUT = Path("results/gemini_roles/failure_analyst/carbon-longctx-corpus")
DEFAULT_DOC = Path("docs/gemini/FAILURE_GALLERY_CARBON.md")

VERBATIM_RULES = (
    "\n\nSTRICT GROUNDING AND SCHEMA RULES (enforced in code by exact substring check):\n"
    "1. Produce 5 to 6 distinct failure-mode clusters grounded in the corpus decisions and solver regret tags "
    "(premature_accusation, ignored_delay, uninformative_canary, over_restriction, budget_waste, no_accusation).\n"
    "2. Respect strict character caps: summary <= 900 chars; cluster.name <= 60 chars; "
    "cluster.description <= 450 chars; 2 to 3 quotes per cluster; quote.quote <= 220 chars.\n"
    "3. Do not use unicode em dashes or en dashes anywhere; use plain ASCII hyphens, colons, or semicolons.\n"
    "4. Every Quote.episode MUST be copied verbatim from the token immediately after '### ' up to the first space, "
    "including '#<index>' (example: 'codex:gpt-5.5/medium/0#73'). Never include '### ' or 'score=' in episode.\n"
    "5. Every Quote.quote MUST be an exact, unmodified, single-line substring copied character-for-character from "
    "inside that exact episode block (such as a 'regret t=...' line, a '### <key> score=...' line, or a short "
    "'d<day> <tool>(...) -> ok' line under 220 chars). Never add ellipses '...', never paraphrase, and never merge lines."
)


def clean_dashes(text: str) -> str:
    return (text or "").replace("\u2014", " - ").replace("\u2013", "-")


@contextmanager
def tier_context(version: str):
    target = "v1.3" if version == "v1.2" else version
    old_kv = rules.KNOWN_V_MODE
    with rules.tiers_version(target):
        rules.KNOWN_V_MODE = version != "v1.2"
        try:
            yield
        finally:
            rules.KNOWN_V_MODE = old_kv


def matches_frontier_path(rel_parts: tuple[str, ...], families: tuple[str, ...] | None) -> bool:
    if "superseded" in rel_parts or "reference" in rel_parts:
        return False
    if families is None:
        return True
    return any(any(part == fam or part.startswith(fam + "-") for fam in families) for part in rel_parts[:-1])


def load_corpus(
    runs_root: str | Path = "data/runs/committed",
    families: tuple[str, ...] | None = FRONTIER_FAMILIES,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    root = Path(runs_root)
    records: list[dict[str, Any]] = []
    n_invalid_skipped = 0
    files_loaded: list[str] = []
    for f in sorted(root.rglob("episodes.jsonl")):
        rel = f.relative_to(root).parts
        if not matches_frontier_path(rel, families):
            continue
        ver = next((p for p in rel if p.startswith("v1.")), "v1.2")
        rel_str = str(f.relative_to(root))
        files_loaded.append(rel_str)
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            if (d.get("meta") or {}).get("valid") is False:
                n_invalid_skipped += 1
                continue
            with tier_context(ver):
                ep = to_result(d)
                true_mole = None
                decoy = None
                if ep.seed not in JUDGE_SEEDS and ep.seed not in HELDOUT_SEEDS:
                    world = Env(ep.tier, ep.seed)._world
                    true_mole = world.mole
                    decoy = world.decoy
                    ep.meta = dict(ep.meta or {}, decoy=decoy)
                tg = attribute(ep)
            idx = len(records)
            key = f"{d.get('agent')}/{d.get('tier')}/{d.get('seed')}#{idx}"
            total_regret = round(sum(float(x.get("regret", 0.0)) for x in tg), 6)
            tag_set = sorted({str(t) for x in tg for t in x.get("tags", [])})
            records.append(
                {
                    "index": idx,
                    "key": key,
                    "tiers_version": ver,
                    "run_path": rel_str,
                    "episode": d,
                    "regret_rows": tg,
                    "total_regret": total_regret,
                    "tag_set": tag_set,
                    "true_mole": true_mole,
                    "decoy": decoy,
                }
            )
    stats = build_pack_stats(records, n_invalid_skipped, files_loaded)
    return records, stats


def build_pack_stats(
    records: list[dict[str, Any]],
    n_invalid_skipped: int,
    files_loaded: list[str],
) -> dict[str, Any]:
    episodes = [r["episode"] for r in records]
    tags = [r["regret_rows"] for r in records]
    packed_text, _ = analyst.pack(episodes, tags)
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for r in records:
        ep = r["episode"]
        gk = (r["tiers_version"], str(ep.get("agent")), str(ep.get("tier")))
        grouped.setdefault(gk, []).append(r)
    by_group = []
    for (ver, agent, tier), lst in sorted(grouped.items()):
        n = len(lst)
        mean_score = sum(float(x["episode"].get("score", 0.0)) for x in lst) / n
        acc = sum(1 for x in lst if x["episode"].get("correct")) / n
        reg = sum(float(x["total_regret"]) for x in lst)
        by_group.append(
            {
                "tiers_version": ver,
                "agent": agent,
                "tier": tier,
                "n": n,
                "mean_score": round(mean_score, 4),
                "accuracy": round(acc, 4),
                "total_regret": round(reg, 4),
            }
        )
    tag_eps: Counter[str] = Counter()
    tag_inst: Counter[str] = Counter()
    tag_reg: Counter[str] = Counter()
    for r in records:
        seen = set()
        for row in r["regret_rows"]:
            rv = float(row.get("regret", 0.0))
            for t in row.get("tags", []):
                ts = str(t)
                tag_inst[ts] += 1
                tag_reg[ts] += rv
                seen.add(ts)
        for ts in seen:
            tag_eps[ts] += 1
    regret_tags = {
        t: {
            "episodes_with": tag_eps[t],
            "instances": tag_inst[t],
            "regret_sum": round(tag_reg[t], 4),
        }
        for t in sorted(tag_inst, key=lambda k: (-tag_reg[k], -tag_eps[k], k))
    }
    episode_summaries = [
        {
            "index": r["index"],
            "episode_key": r["key"],
            "tiers_version": r["tiers_version"],
            "run_path": r["run_path"],
            "agent": r["episode"].get("agent"),
            "tier": r["episode"].get("tier"),
            "seed": r["episode"].get("seed"),
            "score": r["episode"].get("score"),
            "correct": bool(r["episode"].get("correct")),
            "accused": r["episode"].get("accused"),
            "final_day": r["episode"].get("final_day"),
            "end_reason": r["episode"].get("end_reason"),
            "total_regret": round(r["total_regret"], 4),
            "tags": r["tag_set"],
        }
        for r in records
    ]
    return {
        "n_episodes_packed": len(records),
        "n_invalid_skipped": n_invalid_skipped,
        "packed_chars": len(packed_text),
        "files_loaded": files_loaded,
        "by_version_agent_tier": by_group,
        "regret_tags": regret_tags,
        "episodes": episode_summaries,
    }


def _extract_raw_meta(resp: Any, latency_s: float) -> dict[str, Any]:
    raw = getattr(resp, "raw", None)
    um = getattr(raw, "usage_metadata", None) if raw is not None else None

    def _u(attr: str) -> int:
        v = getattr(um, attr, 0) if um is not None else 0
        return v if isinstance(v, int) else 0

    cands = (getattr(raw, "candidates", None) or []) if raw is not None else []
    finish_reason = str(getattr(cands[0], "finish_reason", None)) if cands else None
    usage = dict(getattr(resp, "usage", {}) or {})
    prompt_tokens = int(usage.get("in", 0) or _u("prompt_token_count"))
    out_tokens = int(usage.get("out", 0) or (_u("candidates_token_count") + _u("thoughts_token_count")))
    thinking_tokens = _u("thoughts_token_count")
    candidates_tokens = _u("candidates_token_count")
    cached_tokens = int(usage.get("cached_in", 0) or _u("cached_content_token_count"))
    cost_usd = float(usage.get("cost_usd_est", usage.get("cost_usd", 0.0)) or 0.0)
    thoughts = clean_dashes(getattr(resp, "thoughts", "") or "")
    text = getattr(resp, "text", "") or ""
    return {
        "text": text,
        "thoughts": thoughts,
        "finish_reason": finish_reason,
        "latency_s": round(latency_s, 3),
        "usage": {
            "prompt_tokens": prompt_tokens,
            "out_tokens": out_tokens,
            "candidates_tokens": candidates_tokens,
            "thinking_tokens": thinking_tokens,
            "cached_tokens": cached_tokens,
            "cost_usd": round(cost_usd, 6),
        },
    }


class AnalystCaptureClient:
    def __init__(self, inner: Any, corpus_note: str = "", extra_note: str = ""):
        self.inner = inner
        self.corpus_note = corpus_note
        self.extra_note = extra_note
        self.calls: list[dict[str, Any]] = []

    @property
    def model_id(self) -> str:
        m = getattr(self.inner, "model", "") or ""
        if m:
            return str(m)
        return str(getattr(self.inner, "name", "stub") or "stub")

    def chat(self, messages, tools=None, temperature=0.0, response_schema=None):
        patched = []
        for m in messages:
            if m.get("role") == "system":
                content = str(m.get("content") or "") + VERBATIM_RULES
                if self.corpus_note:
                    content += "\n\nCORPUS METADATA:\n" + self.corpus_note
                if self.extra_note:
                    content += "\n\nRETRY NOTE:\n" + self.extra_note
                patched.append({**m, "content": content})
            else:
                patched.append(dict(m))
        t0 = time.time()
        resp = self.inner.chat(patched, tools=tools, temperature=temperature, response_schema=response_schema)
        dt = time.time() - t0
        self.calls.append(_extract_raw_meta(resp, dt))
        return resp


def make_client(spec_or_client: Any, run_id: str = "carbon-longctx-corpus"):
    if not isinstance(spec_or_client, str):
        return spec_or_client
    if spec_or_client.partition(":")[0] == "gemini":
        from canary.gemini.ledger import lab_client
        return lab_client(spec_or_client, feature="failure_analyst", run_id=run_id)
    return resolve_client(spec_or_client)


def audit_quotes(raw_text: str, blocks: dict[str, str]) -> dict[str, Any]:
    try:
        parsed = analyst.Report.model_validate(json.loads(raw_text or ""))
    except Exception as exc:
        return {
            "parsed_ok": False,
            "error": f"{type(exc).__name__}: {str(exc)[:240]}",
            "n_clusters_raw": 0,
            "n_quotes_raw": 0,
            "n_quotes_verified": 0,
            "verified_quotes_pct": 0.0,
            "unverified": [],
        }
    total = 0
    verified = 0
    unverified = []
    for c in parsed.clusters:
        for q in c.quotes:
            total += 1
            qt = q.quote.strip()
            if q.episode in blocks and qt and qt in blocks[q.episode]:
                verified += 1
            else:
                unverified.append({"cluster": c.name, "episode": q.episode, "quote": q.quote})
    pct = round(100.0 * verified / total, 2) if total > 0 else 0.0
    return {
        "parsed_ok": True,
        "error": None,
        "n_clusters_raw": len(parsed.clusters),
        "n_quotes_raw": total,
        "n_quotes_verified": verified,
        "verified_quotes_pct": pct,
        "unverified": unverified,
    }


def sanitize_report(report: analyst.Report) -> analyst.Report:
    clusters = [
        c.model_copy(
            update={
                "name": clean_dashes(c.name)[:80],
                "description": clean_dashes(c.description)[:600],
            }
        )
        for c in report.clusters
    ]
    return report.model_copy(update={"summary": clean_dashes(report.summary)[:1200], "clusters": clusters})


def fmt_assignment(asg: dict[str, str]) -> str:
    if not asg:
        return "{}"
    by_lab: dict[str, list[str]] = {}
    for emp, lab in sorted(asg.items()):
        by_lab.setdefault(str(lab), []).append(str(emp))
    parts = []
    for lab, emps in sorted(by_lab.items()):
        if len(emps) <= 3:
            parts.append(f"{lab}:[{','.join(emps)}]")
        else:
            parts.append(f"{lab}:[{emps[0]}..{emps[-1]}({len(emps)})]")
    return "{" + ", ".join(parts) + "}"


def fmt_agent_step(st: Any, post: dict[str, float]) -> str:
    args = st.args or {}
    res = st.result or {}
    ok = res.get("ok", True)
    suffix = "" if ok else f" -> ERR {res.get('error')}"
    if st.tool == "plant_canary":
        asg = args.get("assignment") or {}
        g = _gini(post, asg) if post else 0.0
        return f"plant_canary({len(asg)} staff, { fmt_assignment(asg) }, gini={g:.2f}){suffix}"
    if st.tool == "accuse":
        return f"accuse(employee={args.get('employee')}){suffix}"
    if st.tool in ("restrict_access", "unrestrict_access"):
        return f"{st.tool}(employee={args.get('employee')}){suffix}"
    if st.tool == "interview":
        return f"interview(employee={args.get('employee')}, topic={args.get('topic')}){suffix}"
    if st.tool == "search_messages":
        return f"search_messages(query={args.get('query')!r}){suffix}"
    if st.tool in ("read_access_logs", "list_documents"):
        return f"{st.tool}(d={args.get('day_from')}..{args.get('day_to')}){suffix}"
    return f"{st.tool}(){suffix}"


def build_trajectory_comparison(rec: dict[str, Any], max_rows: int = 9) -> dict[str, Any]:
    ver = rec["tiers_version"]
    d = rec["episode"]
    true_mole = rec["true_mole"]
    decoy = rec["decoy"]
    with tier_context(ver):
        ep = to_result(d)
        if decoy is not None:
            ep.meta = dict(ep.meta or {}, decoy=decoy)
        tg = attribute(ep)
        params = rules.tier_params_for_episode(ep.tier, ep.steps)
        sp = SolverPolicy(params)
        planted_days: set[int] = set()
        candidates: list[dict[str, Any]] = []
        for i, st in enumerate(ep.steps):
            for prev in ep.steps[sp.seen : i]:
                sp._ingest(prev)
            sp.seen = i
            if not sp.obs.employees:
                continue
            row = tg[i]
            post = sp.belief()
            best = max(post, key=post.get)
            p_best = post[best]
            days_left = params.n_days - st.day
            qc = q_continue(post, sp.V, params, days_left)
            qa = accuse_value(p_best, sp.V, params)
            thr = sp.default_threshold()
            if qa >= max(qc, 0.0) and (p_best >= thr or (days_left <= 0 and qa > 0.0)):
                cf_best = f"accuse(employee={best}) [E[V]={qa:+.3f}]"
            elif days_left <= 0 and qa <= 0.0:
                cf_best = f"advance_day() [abstain: 0.000 > E[accuse {best}]={qa:+.3f}]"
            else:
                part = sp.partition(post)
                g_sol = _gini(post, part) if part else 0.0
                if (st.day not in planted_days or st.tool == "plant_canary") and part:
                    cf_best = f"plant_canary({fmt_assignment(part)}) [gini={g_sol:.2f}, Q_cont={qc:+.3f}]"
                else:
                    cf_best = f"advance_day() [wait leak delay: Q_cont={qc:+.3f} vs E[accuse {best}]={qa:+.3f}]"
            post_parts = [f"P(top={best})={p_best:.3f}"]
            if true_mole is not None:
                post_parts.insert(0, f"P(mole={true_mole})={post.get(true_mole, 0.0):.3f}")
            if st.tool == "accuse":
                acc_emp = st.args.get("employee")
                if acc_emp and acc_emp not in (true_mole, best):
                    post_parts.append(f"P(accused={acc_emp})={post.get(acc_emp, 0.0):.3f}")
            priority = 0
            if st.tool == "accuse" or i == len(ep.steps) - 1:
                priority = 4
            elif row.get("tags") and float(row.get("regret", 0.0)) > 0:
                priority = 3
            elif row.get("tags") or float(row.get("regret", 0.0)) >= 0.01 or st.tool == "restrict_access":
                priority = 2
            elif st.tool == "plant_canary":
                priority = 1
            if priority > 0:
                candidates.append(
                    {
                        "idx": i,
                        "priority": priority,
                        "regret": float(row.get("regret", 0.0)),
                        "day": st.day,
                        "step": st.t,
                        "agent_action": fmt_agent_step(st, post),
                        "posterior": ", ".join(post_parts),
                        "solver_action": cf_best,
                        "tags": list(row.get("tags", [])),
                    }
                )
            if st.tool == "plant_canary" and (st.result or {}).get("ok", True):
                planted_days.add(st.day)
        if ep.end_reason != "accused" and len(tg) > len(ep.steps):
            for prev in ep.steps[sp.seen :]:
                sp._ingest(prev)
            term = tg[-1]
            post = sp.belief() if sp.obs.employees else {}
            if post:
                best = max(post, key=post.get)
                p_best = post[best]
                qa = accuse_value(p_best, sp.V, params)
                post_parts = [f"P(top={best})={p_best:.3f}"]
                if true_mole is not None:
                    post_parts.insert(0, f"P(mole={true_mole})={post.get(true_mole, 0.0):.3f}")
                cf_best = (
                    f"accuse(employee={best}) [E[V]={qa:+.3f}]"
                    if qa > 0.0
                    else f"abstain at horizon [0.000 >= E[accuse {best}]={qa:+.3f}]"
                )
                candidates.append(
                    {
                        "idx": len(ep.steps),
                        "priority": 4,
                        "regret": float(term.get("regret", 0.0)),
                        "day": ep.final_day,
                        "step": len(ep.steps),
                        "agent_action": f"(episode ended: {ep.end_reason}, no accusation)",
                        "posterior": ", ".join(post_parts),
                        "solver_action": cf_best,
                        "tags": list(term.get("tags", [])),
                    }
                )
    if len(candidates) > max_rows:
        must_keep = {0, len(candidates) - 1}
        ranked = sorted(
            range(len(candidates)),
            key=lambda k: (-candidates[k]["priority"], -candidates[k]["regret"], k),
        )
        for k in ranked:
            if len(must_keep) >= max_rows:
                break
            must_keep.add(k)
        selected = [candidates[k] for k in sorted(must_keep)]
    else:
        selected = candidates
    return {
        "episode_key": rec["key"],
        "tiers_version": ver,
        "agent": d.get("agent"),
        "tier": d.get("tier"),
        "seed": d.get("seed"),
        "score": d.get("score"),
        "correct": bool(d.get("correct")),
        "accused": d.get("accused"),
        "true_mole": true_mole,
        "decoy": decoy,
        "final_day": d.get("final_day"),
        "end_reason": d.get("end_reason"),
        "total_regret": round(rec["total_regret"], 4),
        "rows": selected,
    }


TAG_KEYWORDS = {
    "premature_accusation": ("premature", "gamble", "accuse", "rushed", "commit", "threshold", "framing"),
    "ignored_delay": ("delay", "pending", "surface", "latency", "window"),
    "uninformative_canary": ("canary", "partition", "variant", "split", "gini", "uninformative"),
    "over_restriction": ("restrict", "lockdown", "over_restriction"),
    "budget_waste": ("budget", "waste", "redundant", "interview", "repeated", "query", "search"),
    "no_accusation": ("abstain", "no_accusation", "horizon", "timeout", "unaccused"),
}


def select_cluster_episodes(
    clusters: list[analyst.Cluster],
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_key = {r["key"]: r for r in records}
    used: set[str] = set()
    chosen: list[dict[str, Any]] = []
    for c in clusters:
        quoted = [by_key[q.episode] for q in c.quotes if q.episode in by_key]
        quoted_sorted = sorted(
            quoted,
            key=lambda r: (not bool(r["episode"].get("correct")), r["total_regret"], len(r["tag_set"])),
            reverse=True,
        )
        pick = next((r for r in quoted_sorted if r["key"] not in used), None)
        if pick is None:
            blob = (c.name + " " + c.description).lower()
            matched_tags = [
                tag for tag, words in TAG_KEYWORDS.items() if tag in blob or any(w in blob for w in words)
            ]
            pool = [
                r
                for r in records
                if r["key"] not in used and any(t in r["tag_set"] for t in matched_tags)
            ]
            pool.sort(
                key=lambda r: (not bool(r["episode"].get("correct")), r["total_regret"]),
                reverse=True,
            )
            pick = pool[0] if pool else (quoted_sorted[0] if quoted_sorted else records[0])
        used.add(pick["key"])
        chosen.append(pick)
    return chosen


def render_failure_gallery(
    report: analyst.Report,
    source: str,
    meta: dict[str, Any],
    pack_stats: dict[str, Any],
    trajectories: list[tuple[analyst.Cluster, dict[str, Any]]],
) -> str:
    src_label = "llm" if source == "llm" else "fallback: tag counts"
    usage = meta["usage"]
    lines = [
        f"# Frontier Failure Gallery ({meta['model_id']}, source={src_label})",
        "",
        "Long-context failure analysis over all committed frontier episodes in `data/runs/committed/` "
        "(`codex:gpt-5.5`, `openai:gpt-5.5`, `grok`, `opencode:openai/gpt-5.6-sol` across `v1.2` and `v1.3`, "
        "excluding `superseded/` and `reference/`), paired with deterministic Bayesian solver regret attribution "
        "(`canary.solver.regret.attribute` under the matching tier version via `canary.rules.tiers_version`).",
        "",
        "## Run Provenance & Verification Summary",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Role | `{meta['role']}` |",
        f"| Model ID | `{meta['model_id']}` |",
        f"| Analysis Source | `{meta['source']}` |",
        f"| Commit | `{meta['commit']}` |",
        f"| Episodes Packed | `{meta['n_episodes_packed']}` (`{pack_stats['n_invalid_skipped']}` infra-invalid skipped) |",
        f"| Packed Corpus Chars | `{pack_stats['packed_chars']:,}` |",
        f"| Prompt / Output Tokens | `{usage['prompt_tokens']:,}` in / `{usage['out_tokens']:,}` out (cost `${usage['cost_usd']:.4f}`) |",
        f"| Verbatim Quote Verification | `{meta['verified_quotes_pct']:.1f}%` (`{meta['n_quotes_verified']}/{meta['n_quotes_raw']}` quotes verified in code) |",
        "",
        "## Corpus & Deterministic Solver Regret Breakdown",
        "",
        "| Tiers | Agent | Tier | Episodes | Mean Score | Accuracy | Total Solver Regret (V) |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for row in pack_stats["by_version_agent_tier"]:
        lines.append(
            f"| `{row['tiers_version']}` | `{row['agent']}` | `{row['tier']}` | {row['n']} | "
            f"{row['mean_score']:+.3f} | {row['accuracy']:.0%} | {row['total_regret']:.3f} |"
        )
    lines += [
        "",
        "### Solver Regret Tags Across Corpus",
        "",
        "| Regret Tag | Episodes Affected | Decision Instances | Total Regret Lost (V) |",
        "|---|---:|---:|---:|",
    ]
    n_tot = max(1, pack_stats["n_episodes_packed"])
    for tag, info in pack_stats["regret_tags"].items():
        pct = 100.0 * info["episodes_with"] / n_tot
        lines.append(
            f"| `{tag}` | {info['episodes_with']}/{pack_stats['n_episodes_packed']} ({pct:.1f}%) | "
            f"{info['instances']} | {info['regret_sum']:.4f} |"
        )
    lines += [
        "",
        f"## Clustered Failure Modes ({meta['model_id']})",
        "",
        clean_dashes(report.summary),
        "",
    ]
    for idx, cluster in enumerate(report.clusters, start=1):
        lines += [
            f"### {idx}. {clean_dashes(cluster.name)} ({cluster.count} episodes)",
            "",
            clean_dashes(cluster.description),
            "",
            "Verified verbatim quotes from packed corpus blocks:",
            "",
        ]
        for q in cluster.quotes:
            lines.append(f"> `{q.episode}`: `{q.quote}`")
        lines.append("")
    lines += [
        "## Annotated Trajectory Comparisons per Top Failure Mode",
        "",
        "Each table below replays the Bayesian reference solver (`SolverPolicy`) step-by-step on the public "
        "observations seen by the agent up to that exact decision under the matching tier rules (`v1.2` or `v1.3`), "
        "comparing the agent's action against `P(mole)` and the solver's counterfactual best action.",
        "",
    ]
    for idx, (cluster, traj) in enumerate(trajectories, start=1):
        mole_str = f"`{traj['true_mole']}`" if traj["true_mole"] else "judge-salted (hidden)"
        acc_str = f"`{traj['accused']}`" if traj["accused"] else "`None`"
        lines += [
            f"### Mode {idx}: {clean_dashes(cluster.name)}",
            "",
            f"Episode `{traj['episode_key']}` (`{traj['tiers_version']}`, score `{traj['score']:+.3f}`, "
            f"correct=`{traj['correct']}`, accused={acc_str}, true mole={mole_str}, "
            f"end=`{traj['end_reason']}` on day `{traj['final_day']}`, total solver regret `{traj['total_regret']:.3f} V`):",
            "",
            "| Day (Step) | Agent Action | Solver Posterior P(mole) | Counterfactual Best Solver Action | Step Regret / Tags |",
            "|---|---|---|---|---|",
        ]
        for r in traj["rows"]:
            t_str = ", ".join(r["tags"]) if r["tags"] else "-"
            lines.append(
                f"| d{r['day']} (t={r['step']}) | `{r['agent_action']}` | {r['posterior']} | "
                f"`{r['solver_action']}` | `{r['regret']:.3f}` ({t_str}) |"
            )
        lines.append("")
    return clean_dashes("\n".join(lines).rstrip() + "\n")


def run_failure_analyst(
    runs_root: str | Path = "data/runs/committed",
    llm: Any = "gemini:gemini-4-carbon",
    out_dir: str | Path = DEFAULT_OUT,
    doc_out: str | Path | None = DEFAULT_DOC,
    require_llm: bool | None = None,
    command_str: str | None = None,
    families: tuple[str, ...] | None = FRONTIER_FAMILIES,
) -> dict[str, Any]:
    if require_llm is None:
        require_llm = isinstance(llm, str) and not llm.startswith("stub")
    records, pack_stats = load_corpus(runs_root=runs_root, families=families)
    if not records:
        raise ValueError(f"no valid frontier episodes found under {runs_root}")
    episodes = [r["episode"] for r in records]
    tags = [r["regret_rows"] for r in records]
    _, blocks = analyst.pack(episodes, tags)

    out_path = Path(out_dir)
    inner = make_client(llm, run_id=out_path.name)
    v12_idx = [r["index"] for r in records if r["tiers_version"] == "v1.2"]
    v13_idx = [r["index"] for r in records if r["tiers_version"] == "v1.3"]
    n_correct = sum(1 for r in records if r["episode"].get("correct"))
    n_wrong = sum(
        1 for r in records if not r["episode"].get("correct") and r["episode"].get("end_reason") == "accused"
    )
    n_abstain = len(records) - n_correct - n_wrong
    corpus_note = json.dumps(
        {
            "n_episodes": len(records),
            "n_correct": n_correct,
            "n_wrong_accusations": n_wrong,
            "n_horizon_no_accusation": n_abstain,
            "v1.2_index_range": [min(v12_idx), max(v12_idx)] if v12_idx else [],
            "v1.3_index_range": [min(v13_idx), max(v13_idx)] if v13_idx else [],
            "solver_regret_tags": pack_stats["regret_tags"],
        }
    )
    capture = AnalystCaptureClient(inner, corpus_note=corpus_note)

    _, report, source = analyst.analyze(episodes, tags, capture, return_report=True)
    last_raw = capture.calls[-1]["text"] if capture.calls else ""
    quote_audit = audit_quotes(last_raw, blocks)

    needs_retry = (
        require_llm
        and (
            source != "llm"
            or not quote_audit["parsed_ok"]
            or quote_audit["n_quotes_raw"] == 0
            or quote_audit["verified_quotes_pct"] < 100.0
            or len(report.clusters) < quote_audit["n_clusters_raw"]
        )
    )
    if needs_retry:
        bad_desc = json.dumps(quote_audit["unverified"][:5])
        err_desc = quote_audit["error"] or source
        capture.extra_note = (
            f"Previous output failed verification (status={err_desc}, unverified_quotes={bad_desc}). "
            "Fix every quote so Quote.episode is an exact block key and Quote.quote is an exact single-line "
            "substring <= 220 chars present in that episode block."
        )
        _, report, source = analyst.analyze(episodes, tags, capture, return_report=True)
        last_raw = capture.calls[-1]["text"] if capture.calls else ""
        quote_audit = audit_quotes(last_raw, blocks)

    report = sanitize_report(report)
    if source == "llm":
        reverified = analyst._verify(report, blocks)
        assert reverified is not None
        report = reverified
        verified_quotes_pct = quote_audit["verified_quotes_pct"]
        n_quotes_raw = quote_audit["n_quotes_raw"]
        n_quotes_verified = quote_audit["n_quotes_verified"]
    else:
        n_quotes_raw = sum(len(c.quotes) for c in report.clusters)
        n_quotes_verified = sum(
            1
            for c in report.clusters
            for q in c.quotes
            if q.episode in blocks and q.quote.strip() and q.quote.strip() in blocks[q.episode]
        )
        verified_quotes_pct = 0.0

    if require_llm:
        if source != "llm":
            raise AssertionError(f"expected source == 'llm', got {source!r} (audit={quote_audit})")
        if verified_quotes_pct != 100.0 or n_quotes_raw == 0 or n_quotes_verified != n_quotes_raw:
            raise AssertionError(
                f"expected 100% verified verbatim quotes, got {verified_quotes_pct}% "
                f"({n_quotes_verified}/{n_quotes_raw}): {quote_audit['unverified']}"
            )
        for c in report.clusters:
            for q in c.quotes:
                if q.episode not in blocks or not q.quote.strip() or q.quote.strip() not in blocks[q.episode]:
                    raise AssertionError(f"unverified quote in report: {q}")

    prompt_tokens = sum(c["usage"]["prompt_tokens"] for c in capture.calls)
    out_tokens = sum(c["usage"]["out_tokens"] for c in capture.calls)
    thinking_tokens = sum(c["usage"]["thinking_tokens"] for c in capture.calls)
    cached_tokens = sum(c["usage"]["cached_tokens"] for c in capture.calls)
    cost_usd = round(sum(c["usage"]["cost_usd"] for c in capture.calls), 6)

    chosen_eps = select_cluster_episodes(report.clusters, records)
    trajectories = [(c, build_trajectory_comparison(rec)) for c, rec in zip(report.clusters, chosen_eps)]

    meta = {
        "role": "failure_analyst",
        "model_id": capture.model_id,
        "commit": git_sha(),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "command": command_str or "python scripts/run_role_failure_analyst.py",
        "usage": {
            "prompt_tokens": prompt_tokens,
            "out_tokens": out_tokens,
            "thinking_tokens": thinking_tokens,
            "cached_tokens": cached_tokens,
            "cost_usd": cost_usd,
            "calls": len(capture.calls),
        },
        "n_episodes_packed": len(records),
        "packed_chars": pack_stats["packed_chars"],
        "source": "llm" if source == "llm" else source,
        "verified_quotes_pct": verified_quotes_pct,
        "n_clusters": len(report.clusters),
        "n_quotes_raw": n_quotes_raw,
        "n_quotes_verified": n_quotes_verified,
    }

    gallery_md = render_failure_gallery(report, source, meta, pack_stats, trajectories)

    out_path.mkdir(parents=True, exist_ok=True)
    (out_path / "meta.json").write_text(clean_dashes(json.dumps(meta, indent=2)) + "\n")
    report_payload = {
        **report.model_dump(),
        "source": meta["source"],
        "verified_quotes_pct": verified_quotes_pct,
    }
    (out_path / "report.json").write_text(clean_dashes(json.dumps(report_payload, indent=2)) + "\n")

    parsed_raw = None
    if last_raw:
        try:
            parsed_raw = json.loads(last_raw)
        except json.JSONDecodeError:
            parsed_raw = None
    raw_payload = {
        "model_id": capture.model_id,
        "calls": [
            {
                "finish_reason": c["finish_reason"],
                "latency_s": c["latency_s"],
                "usage": c["usage"],
                "thoughts": c["thoughts"],
                "text": clean_dashes(c["text"]),
            }
            for c in capture.calls
        ],
        "final_parsed": parsed_raw,
        "quote_audit": quote_audit,
    }
    (out_path / "raw_response.json").write_text(clean_dashes(json.dumps(raw_payload, indent=2)) + "\n")
    (out_path / "pack_stats.json").write_text(clean_dashes(json.dumps(pack_stats, indent=2)) + "\n")
    (out_path / "failure_gallery.md").write_text(gallery_md)

    if doc_out is not None:
        doc_path = Path(doc_out)
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(gallery_md)

    return {
        "meta": meta,
        "report": report,
        "pack_stats": pack_stats,
        "gallery_md": gallery_md,
        "out_dir": str(out_path),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="data/runs/committed")
    ap.add_argument("--llm", default="gemini:gemini-4-carbon")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--doc-out", default=str(DEFAULT_DOC))
    ap.add_argument("--no-doc", action="store_true")
    ap.add_argument("--require-llm", action="store_true")
    args = ap.parse_args(argv)

    raw_argv = argv if argv is not None else sys.argv[1:]
    cmd = "python scripts/run_role_failure_analyst.py" + (" " + " ".join(raw_argv) if raw_argv else "")
    require_llm = True if args.require_llm else (not str(args.llm).startswith("stub"))
    doc_target = None if args.no_doc else args.doc_out

    res = run_failure_analyst(
        runs_root=args.runs,
        llm=args.llm,
        out_dir=args.out,
        doc_out=doc_target,
        require_llm=require_llm,
        command_str=cmd,
    )
    m = res["meta"]
    print(
        f"role={m['role']} model={m['model_id']} source={m['source']} "
        f"episodes={m['n_episodes_packed']} clusters={m['n_clusters']} "
        f"verified_quotes={m['verified_quotes_pct']}% cost=${m['usage']['cost_usd']:.4f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
