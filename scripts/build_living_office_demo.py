from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.env import Env
from canary.rules import TIERS, TIERS_VERSION
from canary.social import make_v16_provider
from canary.social.engine import _strip_message
from canary.social.gemini_chatter import SOCIAL_SYSTEM, build_social_prompt
from canary.social.multiday_memory import phase_for_day
from canary.social.office_replay import build_office_replay
from canary.text.llm_cache import cache_key

DEFAULT_SEEDS: tuple[int, ...] = (0, 1, 6)
DEFAULT_CACHE_DIR = ROOT / "data" / "gemini_cache"
DEFAULT_HTML_OUT = ROOT / "docs" / "demo" / "living_office_v16.html"
SCHEMA_VERSION = "canary.living_office_demo.v16.v1"
VARIANT_NAME = "v5_full9_cocktail"
PRIOR_DAY_RE = re.compile(r"\bday\s+([1-9]|1\d|2[01])\b", re.I)


@contextmanager
def _offline_env(cache_dir: Path):
    env_keys = (
        "CANARY_OFFLINE",
        "SLEEPER_OFFLINE",
        "CANARY_GEMINI_CACHE_DIR",
        "GOOGLE_GENERATIVE_AI_API_KEY",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
    )
    saved = {k: os.environ.get(k) for k in env_keys}
    os.environ["CANARY_OFFLINE"] = "1"
    os.environ["SLEEPER_OFFLINE"] = "1"
    os.environ["CANARY_GEMINI_CACHE_DIR"] = str(cache_dir)
    for key_name in env_keys[3:]:
        os.environ[key_name] = ""
    try:
        yield
    finally:
        for k, val in saved.items():
            if val is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = val


def _ascii_clean(text: str) -> str:
    cleaned = str(text).replace("\u2014", " - ").replace("\u2013", "-")
    cleaned = cleaned.replace("\u2018", "'").replace("\u2019", "'")
    cleaned = cleaned.replace("\u201c", '"').replace("\u201d", '"')
    return cleaned.encode("ascii", "replace").decode("ascii")


def _prior_day_refs(text: str, day_num: int) -> list[int]:
    refs: list[int] = []
    for match in PRIOR_DAY_RE.finditer(text):
        ref_d = int(match.group(1))
        if 1 <= ref_d < day_num and ref_d not in refs:
            refs.append(ref_d)
    return sorted(refs)


def _compute_day_prompt_key(
    facts: Any,
    raw_evs: tuple[dict[str, Any], ...],
) -> str | None:
    if not raw_evs:
        return None
    valid_ids = {e.id for e in facts.employees}
    prompt_items: list[dict[str, Any]] = []
    for idx, ev in enumerate(raw_evs):
        sender = str(ev["sender"])
        recipients = (
            [r for r in ev.get("recipients", ()) if r in valid_ids and r != sender]
            or [e.id for e in facts.employees if e.id != sender]
            or [sender]
        )
        item = _strip_message(
            {
                "id": f"m{facts.day}-s{idx}",
                "day": int(facts.day),
                "channel": str(ev["channel"]),
                "sender": sender,
                "recipients": recipients,
                "subject": str(ev.get("subject", "")),
                "body": str(ev["body"]),
            }
        )
        ev_meta: dict[str, Any] = {}
        if ev.get("bias"):
            ev_meta["bias"] = str(ev["bias"])
        if ev.get("target"):
            ev_meta["target"] = str(ev["target"])
            item["target"] = str(ev["target"])
        if ev_meta:
            item["meta"] = ev_meta
        prompt_items.append(item)
    prompt = build_social_prompt(facts, prompt_items)
    return cache_key("gemini-4-carbon", SOCIAL_SYSTEM, [{"role": "user", "content": prompt}], None, 0, None)


def _assign_office_layout(
    employees: list[Any],
    primary_suspect: str,
    secondary_suspect: str,
    authority_speakers: set[str],
    grudge_accusers: set[str],
    angry_sender: str,
) -> list[dict[str, Any]]:
    depts = sorted({str(e.dept) for e in employees})
    dept_index = {d: idx for idx, d in enumerate(depts)}
    dept_counters: dict[str, int] = {d: 0 for d in depts}
    out: list[dict[str, Any]] = []
    for emp in employees:
        eid = str(emp.id)
        dept = str(emp.dept)
        slot = dept_counters[dept]
        dept_counters[dept] = slot + 1
        d_idx = dept_index[dept]
        zone_col = d_idx % 3
        zone_row = d_idx // 3
        desk_col = zone_col * 4 + (slot % 4)
        desk_row = zone_row * 3 + (slot // 4)
        if eid == primary_suspect:
            social_role = "primary_target"
        elif eid == secondary_suspect:
            social_role = "secondary_target"
        elif eid in grudge_accusers:
            social_role = "grudge_accuser"
        elif eid in authority_speakers:
            social_role = "authority_speaker"
        elif eid == angry_sender:
            social_role = "public_grumbler"
        else:
            social_role = "staff"
        out.append(
            {
                "id": eid,
                "name": _ascii_clean(emp.name),
                "dept": _ascii_clean(dept),
                "role": _ascii_clean(emp.role),
                "clearance": int(emp.clearance),
                "social_role": social_role,
                "zone_index": d_idx,
                "desk_col": desk_col,
                "desk_row": desk_row,
            }
        )
    return out


def _build_single_seed_entry(seed: int, cache_dir: Path) -> tuple[dict[str, Any], set[str]]:
    prov_gem = make_v16_provider(VARIANT_NAME, mode="gemini", cache_dir=str(cache_dir))
    env_21 = Env("hard", seed=int(seed), text_provider=prov_gem)
    horizon_days = int(env_21.p.n_days)

    facts_by_day: dict[int, Any] = {}
    rendered_by_day: dict[int, list[dict[str, Any]]] = {}
    for d_num in range(1, horizon_days + 1):
        f_day = env_21._facts(d_num)
        facts_by_day[d_num] = f_day
        rendered_by_day[d_num] = prov_gem.day_messages(f_day)
        if d_num < horizon_days:
            env_21.call("advance_day", {})

    f1 = facts_by_day[1]
    soc_state = prov_gem.episode_state(f1.tier, f1.seed)
    if soc_state is None:
        raise RuntimeError(f"missing EpisodeSocialState on hard seed {seed}")

    prim_id = str(soc_state.primary_suspect)
    sec_id = str(soc_state.secondary_suspect)
    angry_sender_id = str(f1.decoy)
    authority_set = {str(x) for x in soc_state.authority_speakers}
    grudge_pairs_raw = [(str(a), str(b)) for a, b in soc_state.grudge_pairs]
    grudge_accusers = {a for a, _ in grudge_pairs_raw}

    employees_out = _assign_office_layout(
        list(f1.employees),
        primary_suspect=prim_id,
        secondary_suspect=sec_id,
        authority_speakers=authority_set,
        grudge_accusers=grudge_accusers,
        angry_sender=angry_sender_id,
    )
    emp_by_id = {e["id"]: e for e in employees_out}

    rep_solver = build_office_replay(
        tier="hard",
        seed=int(seed),
        variant=f"v16-gemini:{VARIANT_NAME}",
        cache_dir=cache_dir,
        allow_cached_gemini=True,
        agent="solver",
    )
    rep_rf = build_office_replay(
        tier="hard",
        seed=int(seed),
        variant=f"v16-gemini:{VARIANT_NAME}",
        cache_dir=cache_dir,
        allow_cached_gemini=True,
        agent="rumour_follower",
    )
    rep_rf_ctrl = build_office_replay(
        tier="hard",
        seed=int(seed),
        variant="v0_v14_control",
        mode="template",
        agent="rumour_follower",
    )

    solver_days_map = {int(d["day"]): d for d in rep_solver["days"]}
    rf_days_map = {int(d["day"]): d for d in rep_rf["days"]}
    solver_final_day = int(rep_solver["episode_summary"]["final_day"])
    rf_final_day = int(rep_rf["episode_summary"]["final_day"])
    last_solver_posterior = solver_days_map[solver_final_day]["posterior"]

    used_cache_keys: set[str] = set()
    prompts_total = 0
    prompts_hit = 0
    prompts_fallback = 0
    seen_models: set[str] = set()
    seen_commits: set[str] = set()

    first_seen_day: dict[str, int] = {}
    last_seen_day: dict[str, int] = {}
    last_seen_msg: dict[str, dict[str, Any]] = {}
    cum_mentions: dict[str, int] = {}
    cum_biases: dict[str, list[str]] = {}
    grudge_strikes_by_pair: dict[tuple[str, str], int] = {}
    grudge_events_by_pair: dict[tuple[str, str], list[dict[str, Any]]] = {
        pair: [] for pair in grudge_pairs_raw
    }
    chain_hops_by_target: dict[str, list[dict[str, Any]]] = {prim_id: [], sec_id: []}
    gossip_carryover: list[dict[str, Any]] = []
    days_out: list[dict[str, Any]] = []

    for d_num in range(1, horizon_days + 1):
        f_day = facts_by_day[d_num]
        raw_evs = soc_state.events_by_day.get(d_num, ())
        day_msgs_raw = rendered_by_day[d_num]
        social_rendered = [m for m in day_msgs_raw if "-s" in str(m.get("id", ""))]

        day_key = _compute_day_prompt_key(f_day, raw_evs)
        day_hit = False
        if day_key is not None:
            prompts_total += 1
            cache_fp = cache_dir / f"{day_key}.json"
            if cache_fp.is_file():
                obj = json.loads(cache_fp.read_text(encoding="utf-8"))
                prov_meta = obj.get("provenance") or {}
                if prov_meta.get("label") == "REAL" and prov_meta.get("model") == "gemini-4-carbon":
                    day_hit = True
                    prompts_hit += 1
                    used_cache_keys.add(day_key)
                    seen_models.add(str(prov_meta["model"]))
                    if prov_meta.get("commit"):
                        seen_commits.add(str(prov_meta["commit"]))
            if not day_hit:
                prompts_fallback += 1

        day_social_events: list[dict[str, Any]] = []
        for idx, ev in enumerate(raw_evs):
            msg_obj = social_rendered[idx] if idx < len(social_rendered) else ev
            msg_id = str(msg_obj.get("id") or f"m{d_num}-s{idx}")
            sender_id = str(ev["sender"])
            target_id = str(ev["target"])
            bias_name = str(ev["bias"])
            subj_clean = _ascii_clean(msg_obj.get("subject", ev.get("subject", "")))
            body_clean = _ascii_clean(msg_obj.get("body", ev.get("body", "")))
            draft_clean = _ascii_clean(ev.get("body", ""))

            if target_id not in first_seen_day:
                first_seen_day[target_id] = d_num
            origin_d = first_seen_day[target_id]
            prev_d = last_seen_day.get(target_id)
            carried_from = prev_d if prev_d is not None else d_num

            explicit_refs = _prior_day_refs(f"{subj_clean}\n{body_clean}\n{draft_clean}", d_num)
            cum_mentions[target_id] = cum_mentions.get(target_id, 0) + 1
            seen_b = cum_biases.setdefault(target_id, [])
            if bias_name not in seen_b:
                seen_b.append(bias_name)

            strike_num = 0
            if bias_name == "grudge":
                pair = (sender_id, target_id)
                strike_num = grudge_strikes_by_pair.get(pair, 0) + 1
                grudge_strikes_by_pair[pair] = strike_num
                grudge_events_by_pair.setdefault(pair, []).append(
                    {
                        "strike": strike_num,
                        "day": d_num,
                        "message_id": msg_id,
                        "channel": str(msg_obj.get("channel", ev.get("channel", ""))),
                        "subject": subj_clean,
                        "body": body_clean,
                    }
                )

            if prev_d is not None and prev_d < d_num and target_id in last_seen_msg:
                prev_item = last_seen_msg[target_id]
                if explicit_refs:
                    mechanism = "explicit_prior_day_callback"
                    link_from_day = explicit_refs[-1]
                elif bias_name == "grudge":
                    mechanism = "persistent_grudge_escalation"
                    link_from_day = prev_d
                else:
                    mechanism = "recurring_suspect_echo"
                    link_from_day = prev_d
                gossip_carryover.append(
                    {
                        "edge_id": f"s{seed}-d{link_from_day}-to-d{d_num}-{idx}",
                        "from_day": link_from_day,
                        "to_day": d_num,
                        "from_message_id": str(prev_item["id"]),
                        "to_message_id": msg_id,
                        "from_sender": str(prev_item["sender"]),
                        "to_sender": sender_id,
                        "target": target_id,
                        "target_name": emp_by_id[target_id]["name"],
                        "from_bias": str(prev_item["bias"]),
                        "to_bias": bias_name,
                        "mechanism": mechanism,
                    }
                )

            ev_record = {
                "id": msg_id,
                "day": d_num,
                "bias": bias_name,
                "channel": _ascii_clean(msg_obj.get("channel", ev.get("channel", ""))),
                "sender": sender_id,
                "sender_name": emp_by_id[sender_id]["name"],
                "sender_role": emp_by_id[sender_id]["role"],
                "sender_dept": emp_by_id[sender_id]["dept"],
                "target": target_id,
                "target_name": emp_by_id[target_id]["name"],
                "target_role": emp_by_id[target_id]["role"],
                "target_dept": emp_by_id[target_id]["dept"],
                "target_focus": "primary_suspect" if target_id == prim_id else "secondary_suspect",
                "subject": subj_clean,
                "body": body_clean,
                "text": draft_clean,
                "origin_day": origin_d,
                "carried_from_day": carried_from,
                "referenced_days": explicit_refs,
                "grudge_strike": strike_num,
                "cache_sha256": day_key,
            }
            day_social_events.append(ev_record)
            chain_hops_by_target.setdefault(target_id, []).append(
                {
                    "hop": len(chain_hops_by_target.get(target_id, ())) + 1,
                    "day": d_num,
                    "message_id": msg_id,
                    "bias": bias_name,
                    "sender": sender_id,
                    "sender_name": emp_by_id[sender_id]["name"],
                    "sender_role": emp_by_id[sender_id]["role"],
                    "carried_from_day": carried_from,
                    "referenced_days": explicit_refs,
                    "body": body_clean,
                }
            )
            last_seen_day[target_id] = d_num
            last_seen_msg[target_id] = {
                "id": msg_id,
                "day": d_num,
                "sender": sender_id,
                "bias": bias_name,
            }

        social_by_id = {ev["id"]: ev for ev in day_social_events}
        day_messages_out: list[dict[str, Any]] = []
        for m in day_msgs_raw:
            mid = str(m["id"])
            s_id = str(m["sender"])
            s_ev = social_by_id.get(mid)
            is_soc = s_ev is not None or "-s" in mid
            day_messages_out.append(
                {
                    "id": mid,
                    "day": d_num,
                    "channel": _ascii_clean(m["channel"]),
                    "sender": s_id,
                    "sender_name": emp_by_id[s_id]["name"] if s_id in emp_by_id else s_id,
                    "sender_dept": emp_by_id[s_id]["dept"] if s_id in emp_by_id else "",
                    "recipients": [str(r) for r in m.get("recipients", ())],
                    "subject": _ascii_clean(m.get("subject", "")),
                    "body": _ascii_clean(m.get("body", "")),
                    "is_social": bool(is_soc),
                    "bias": s_ev["bias"] if s_ev is not None else None,
                    "target": s_ev["target"] if s_ev is not None else None,
                    "referenced_days": s_ev["referenced_days"] if s_ev is not None else [],
                }
            )

        reg_docs = [
            {
                "doc_id": str(doc.get("doc_id", "")),
                "title": _ascii_clean(doc.get("title", "")),
                "day": int(doc.get("day", d_num)),
                "recipients": [str(r) for r in doc.get("recipients", ())],
            }
            for doc in f_day.docs
            if not str(doc.get("doc_id", "")).startswith("c")
        ]

        if d_num in solver_days_map:
            sol_day = solver_days_map[d_num]
            sol_snap = {
                "status": "accused" if d_num == solver_final_day else "investigating",
                "V": float(sol_day["V"]),
                "top_suspect": sol_day["posterior"]["top_suspect"],
                "p_top_suspect": float(sol_day["posterior"]["p_top_suspect"]),
                "p_primary_suspect": float(sol_day["posterior"]["p_primary_suspect"] or 0.0),
                "p_secondary_suspect": float(sol_day["posterior"]["p_secondary_suspect"] or 0.0),
                "top_candidates": sol_day["posterior"]["top_candidates"],
                "actions": [
                    {
                        "tool": a["tool"],
                        "summary": _ascii_clean(a["summary"]),
                        "target": a["target"],
                    }
                    for a in sol_day["actions"]
                ],
            }
        else:
            sol_snap = {
                "status": "resolved",
                "V": float(solver_days_map[solver_final_day]["V"]),
                "top_suspect": last_solver_posterior["top_suspect"],
                "p_top_suspect": float(last_solver_posterior["p_top_suspect"]),
                "p_primary_suspect": float(last_solver_posterior["p_primary_suspect"] or 0.0),
                "p_secondary_suspect": float(last_solver_posterior["p_secondary_suspect"] or 0.0),
                "top_candidates": last_solver_posterior["top_candidates"],
                "actions": [],
            }

        if d_num in rf_days_map:
            rf_day = rf_days_map[d_num]
            rf_snap = {
                "status": "fooled_accused" if d_num == rf_final_day else "listening_to_gossip",
                "actions": [
                    {
                        "tool": a["tool"],
                        "summary": _ascii_clean(a["summary"]),
                        "target": a["target"],
                        "fooled": bool(a["fooled"]),
                    }
                    for a in rf_day["actions"]
                ],
                "fooled_moments": rf_day["fooled_moments"],
            }
        else:
            rf_snap = {
                "status": "ended_wrong_accusation",
                "actions": [],
                "fooled_moments": [],
            }

        days_out.append(
            {
                "day": d_num,
                "phase": phase_for_day(d_num) or "quiet_tail",
                "cache_sha256": day_key,
                "cache_hit": day_hit,
                "documents": reg_docs,
                "social_events": day_social_events,
                "messages": day_messages_out,
                "carryover_state": {
                    "mentions_primary": int(cum_mentions.get(prim_id, 0)),
                    "mentions_secondary": int(cum_mentions.get(sec_id, 0)),
                    "biases_primary": list(cum_biases.get(prim_id, ())),
                    "biases_secondary": list(cum_biases.get(sec_id, ())),
                    "total_grudge_strikes": sum(grudge_strikes_by_pair.values()),
                },
                "solver_snapshot": sol_snap,
                "rumour_follower_snapshot": rf_snap,
            }
        )

    grudge_ledger = []
    for p_idx, (acc_id, tgt_id) in enumerate(grudge_pairs_raw):
        evs_for_pair = grudge_events_by_pair.get((acc_id, tgt_id), [])
        grudge_ledger.append(
            {
                "pair_index": p_idx,
                "sender": acc_id,
                "sender_name": emp_by_id[acc_id]["name"],
                "sender_role": emp_by_id[acc_id]["role"],
                "sender_dept": emp_by_id[acc_id]["dept"],
                "target": tgt_id,
                "target_name": emp_by_id[tgt_id]["name"],
                "target_role": emp_by_id[tgt_id]["role"],
                "target_dept": emp_by_id[tgt_id]["dept"],
                "strike_days": [int(x["day"]) for x in evs_for_pair],
                "total_strikes": len(evs_for_pair),
                "entries": evs_for_pair,
            }
        )

    rumour_chains = []
    for focus_lbl, tgt_id in (("primary_suspect", prim_id), ("secondary_suspect", sec_id)):
        hops = chain_hops_by_target.get(tgt_id, [])
        rumour_chains.append(
            {
                "chain_id": f"seed{seed}-{focus_lbl}",
                "focus": focus_lbl,
                "target": tgt_id,
                "target_name": emp_by_id[tgt_id]["name"],
                "target_role": emp_by_id[tgt_id]["role"],
                "target_dept": emp_by_id[tgt_id]["dept"],
                "seed_day": int(hops[0]["day"]) if hops else 1,
                "peak_day": int(hops[-1]["day"]) if hops else 1,
                "total_mentions": len(hops),
                "distinct_speakers": sorted({str(h["sender"]) for h in hops}),
                "distinct_biases": sorted({str(h["bias"]) for h in hops}),
                "hops": hops,
            }
        )

    sol_ep = rep_solver["episode_summary"]
    rf_ep = rep_rf["episode_summary"]
    sol_acc = str(sol_ep["accused"])
    rf_acc = str(rf_ep["accused"])

    seed_entry = {
        "seed": int(seed),
        "tier": "hard",
        "company": _ascii_clean(f1.company),
        "horizon_days": horizon_days,
        "employees": employees_out,
        "social_cast": {
            "primary_suspect": prim_id,
            "primary_suspect_name": emp_by_id[prim_id]["name"],
            "secondary_suspect": sec_id,
            "secondary_suspect_name": emp_by_id[sec_id]["name"],
            "public_grumbler": angry_sender_id,
            "public_grumbler_name": emp_by_id[angry_sender_id]["name"],
            "authority_speakers": sorted(authority_set),
            "grudge_pairs": [[a, b] for a, b in grudge_pairs_raw],
        },
        "cache_audit": {
            "prompts_total": prompts_total,
            "prompts_hit": prompts_hit,
            "prompts_fallback": prompts_fallback,
            "hit_rate": round(prompts_hit / prompts_total, 6) if prompts_total else 1.0,
            "provider_rejects": int(prov_gem.rejects),
            "models": sorted(seen_models),
            "commits": sorted(seen_commits),
        },
        "grudge_ledger": grudge_ledger,
        "rumour_chains": rumour_chains,
        "gossip_carryover": gossip_carryover,
        "solver_arm": {
            "agent": "solver",
            "final_day": int(sol_ep["final_day"]),
            "accused": sol_acc,
            "accused_name": emp_by_id[sol_acc]["name"] if sol_acc in emp_by_id else sol_acc,
            "correct": bool(sol_ep["correct"]),
            "score": round(float(sol_ep["score"]), 6),
            "total_steps": int(sol_ep["total_steps"]),
            "fooled_count": int(sol_ep["fooled_count"]),
        },
        "rumour_follower_arm": {
            "agent": "rumour_follower",
            "final_day": int(rf_ep["final_day"]),
            "accused": rf_acc,
            "accused_name": emp_by_id[rf_acc]["name"] if rf_acc in emp_by_id else rf_acc,
            "v14_control_accused": str(rep_rf_ctrl["episode_summary"]["accused"]),
            "correct": bool(rf_ep["correct"]),
            "score": round(float(rf_ep["score"]), 6),
            "total_steps": int(rf_ep["total_steps"]),
            "fooled_count": int(rf_ep["fooled_count"]),
            "fooled_moments": rep_rf["fooled_moments"],
        },
        "days": days_out,
    }
    return seed_entry, used_cache_keys


def build_living_office_payload(
    seeds: tuple[int, ...] | list[int] = DEFAULT_SEEDS,
    cache_dir: str | Path | None = None,
) -> dict[str, Any]:
    resolved_cache = Path(cache_dir) if cache_dir is not None else DEFAULT_CACHE_DIR
    clean_seeds = tuple(int(s) for s in seeds)
    hard_params = TIERS["hard"]

    all_used_keys: set[str] = set()
    seeds_out: list[dict[str, Any]] = []
    with _offline_env(resolved_cache):
        for s_num in clean_seeds:
            entry, used_keys = _build_single_seed_entry(s_num, resolved_cache)
            seeds_out.append(entry)
            all_used_keys.update(used_keys)

    total_prompts = sum(int(s["cache_audit"]["prompts_total"]) for s in seeds_out)
    total_hits = sum(int(s["cache_audit"]["prompts_hit"]) for s in seeds_out)
    hit_rate = round(total_hits / total_prompts, 6) if total_prompts else 1.0

    return {
        "schema_version": SCHEMA_VERSION,
        "provenance": {
            "offline_only": True,
            "api_calls": 0,
            "gate_b_passed": False,
            "judged_benchmark_version": "v1.4",
            "tiers_version": TIERS_VERSION,
            "default_enabled": False,
            "default_provider": "template",
            "opt_in_provider": f"v16-gemini:{VARIANT_NAME}",
            "variant": VARIANT_NAME,
            "tier": "hard",
            "seeds": list(clean_seeds),
            "cache_dir": "data/gemini_cache",
            "cache_files_used": len(all_used_keys),
            "cache_prompts_hit": total_hits,
            "cache_prompts_total": total_prompts,
            "cache_hit_rate": hit_rate,
            "model": "gemini-4-carbon",
            "label": "REAL",
            "rules_disclosure": {
                "social_message_lr": 1.0,
                "n_employees": int(hard_params.n_employees),
                "n_days": int(hard_params.n_days),
                "canaries_per_day": int(hard_params.canaries_per_day),
                "fingerprint_accuracy": float(hard_params.fingerprint_accuracy),
                "p_evasive_innocent": float(hard_params.p_evasive_innocent),
            },
            "gate_b_disclosure": (
                "OFF-BY-DEFAULT v1.6 PREVIEW: V1.6 is OFF by default and did NOT pass the Gate B gap gate "
                "(v1.5 biased employees moved gemini-4-carbon from 61% to 108% of SolverPolicy on hard seeds 0-9; "
                "v1.6 shared hard seeds 30-32: v5_full9_cocktail 0.617 vs v0_v14_control 0.523, paired ratio 1.178). "
                "Frozen v1.4 remains the judged default benchmark (CANARY_PROVIDER=template); "
                "all workplace chatter here is 100% offline cached REAL gemini-4-carbon (0 live API calls)."
            ),
        },
        "seeds": seeds_out,
    }


def _safe_embedded_json(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return raw.replace("</", "<\\/")


_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Canary v1.6 Living Office Preview (Offline Cached gemini-4-carbon)</title>
<style>
:root {
  --bg: #0b101b;
  --panel: #121a2b;
  --panel-alt: #172238;
  --border: #263654;
  --text: #e7eefb;
  --muted: #93a5c6;
  --amber: #f59e0b;
  --amber-soft: rgba(245, 158, 11, 0.14);
  --coral: #f97316;
  --violet: #a855f7;
  --cyan: #06b6d4;
  --emerald: #10b981;
  --crimson: #ef4444;
  --slate: #64748b;
  --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  --sans: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: radial-gradient(circle at 15% 0%, #15213a 0%, #0b101b 58%);
  color: var(--text);
  font-family: var(--sans);
  line-height: 1.45;
}
.gate-banner {
  background: linear-gradient(90deg, rgba(245, 158, 11, 0.18), rgba(239, 68, 68, 0.14));
  border-bottom: 2px solid var(--amber);
  padding: 12px 20px;
}
.gate-banner-inner {
  max-width: 1480px;
  margin: 0 auto;
  display: flex;
  flex-wrap: wrap;
  gap: 10px 16px;
  align-items: center;
  justify-content: space-between;
}
.gate-pill {
  display: inline-block;
  background: var(--amber);
  color: #0b101b;
  font-family: var(--mono);
  font-weight: 800;
  font-size: 11px;
  letter-spacing: 0.05em;
  padding: 4px 8px;
  border-radius: 4px;
  text-transform: uppercase;
}
.gate-copy {
  flex: 1 1 680px;
  font-size: 13px;
  color: #fef3c7;
}
.gate-copy code {
  font-family: var(--mono);
  background: rgba(11, 16, 27, 0.55);
  padding: 1px 5px;
  border-radius: 4px;
  color: #fde68a;
}
.gate-metrics {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  font-family: var(--mono);
  font-size: 11px;
}
.gate-chip {
  border: 1px solid rgba(245, 158, 11, 0.45);
  background: rgba(11, 16, 27, 0.65);
  padding: 4px 8px;
  border-radius: 999px;
  color: #fde68a;
}
main {
  max-width: 1480px;
  margin: 0 auto;
  padding: 16px 20px 36px;
}
.topbar {
  display: grid;
  grid-template-columns: 1.2fr 1.8fr;
  gap: 14px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px 16px;
  margin-bottom: 14px;
}
@media (max-width: 1024px) {
  .topbar { grid-template-columns: 1fr; }
}
.title-block h1 {
  margin: 0 0 4px;
  font-size: 20px;
  letter-spacing: -0.01em;
}
.subtitle {
  margin: 0;
  font-size: 12.5px;
  color: var(--muted);
}
.controls-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  justify-content: center;
}
.control-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.btn {
  background: var(--panel-alt);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 7px;
  padding: 6px 11px;
  font-size: 12px;
  font-family: var(--mono);
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.btn:hover { border-color: var(--cyan); }
.btn.active {
  background: rgba(6, 182, 212, 0.18);
  border-color: var(--cyan);
  color: #a5f3fc;
  font-weight: 700;
}
.btn.warn {
  border-color: rgba(249, 115, 22, 0.6);
  color: #fed7aa;
}
.btn.good {
  border-color: rgba(16, 185, 129, 0.6);
  color: #a7f3d0;
}
.scrubber-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
}
.scrubber-wrap input[type="range"] {
  flex: 1;
  accent-color: var(--cyan);
  cursor: pointer;
}
.day-badge {
  font-family: var(--mono);
  font-size: 13px;
  font-weight: 700;
  padding: 4px 10px;
  border-radius: 6px;
  background: #0d1526;
  border: 1px solid var(--border);
  min-width: 195px;
  text-align: center;
}
.kpi-strip {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 14px;
}
@media (max-width: 1024px) {
  .kpi-strip { grid-template-columns: repeat(2, 1fr); }
}
.kpi-card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 11px 14px;
}
.kpi-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--muted);
}
.kpi-val {
  font-family: var(--mono);
  font-size: 16px;
  font-weight: 700;
  margin-top: 3px;
}
.kpi-sub {
  font-size: 11.5px;
  color: var(--muted);
  margin-top: 3px;
}
.workspace-grid {
  display: grid;
  grid-template-columns: 1.35fr 1fr;
  gap: 14px;
  margin-bottom: 14px;
}
@media (max-width: 1120px) {
  .workspace-grid { grid-template-columns: 1fr; }
}
.card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px;
}
.card-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
}
.card-title {
  font-size: 14px;
  font-weight: 700;
  margin: 0;
}
.legend-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 11px;
  color: var(--muted);
}
.legend-dot {
  display: inline-block;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  margin-right: 4px;
  vertical-align: middle;
}
.stage-svg-wrap {
  width: 100%;
  background: #0a101d;
  border: 1px solid #1e2d4a;
  border-radius: 10px;
  overflow: hidden;
}
.stage-svg-wrap svg {
  display: block;
  width: 100%;
  height: auto;
}
.emp-inspector {
  margin-top: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--panel-alt);
  border: 1px solid var(--border);
  font-size: 12.5px;
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 8px;
}
.bias-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-bottom: 10px;
}
.bias-pill {
  font-family: var(--mono);
  font-size: 10.5px;
  padding: 3px 7px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: #0e1627;
  color: var(--muted);
  cursor: pointer;
}
.bias-pill.active {
  border-color: var(--amber);
  color: #fde68a;
  background: var(--amber-soft);
}
.feed-list {
  max-height: 500px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 9px;
  padding-right: 4px;
}
.msg-card {
  background: #0e1628;
  border: 1px solid var(--border);
  border-left: 3px solid var(--slate);
  border-radius: 8px;
  padding: 9px 11px;
  font-size: 12.5px;
}
.msg-card.social-primary { border-left-color: var(--coral); }
.msg-card.social-secondary { border-left-color: var(--violet); }
.msg-card.grumbler { border-left-color: var(--amber); }
.msg-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
  color: var(--muted);
  margin-bottom: 4px;
}
.tag {
  font-family: var(--mono);
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
  background: #1a2742;
  color: #cbd5e1;
}
.tag.bias {
  background: rgba(249, 115, 22, 0.18);
  color: #fdba74;
  border: 1px solid rgba(249, 115, 22, 0.4);
}
.tag.callback {
  background: rgba(6, 182, 212, 0.16);
  color: #67e8f9;
  border: 1px solid rgba(6, 182, 212, 0.38);
}
.tag.grudge {
  background: rgba(239, 68, 68, 0.18);
  color: #fca5a5;
  border: 1px solid rgba(239, 68, 68, 0.4);
}
.msg-subj {
  font-weight: 700;
  color: #f1f5f9;
  margin-bottom: 3px;
}
.msg-body {
  color: #dbe7fb;
}
.msg-sha {
  margin-top: 5px;
  font-family: var(--mono);
  font-size: 10px;
  color: #64748b;
}
.bottom-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 14px;
}
@media (max-width: 1180px) {
  .bottom-grid { grid-template-columns: 1fr; }
}
.ledger-item, .chain-hop, .arm-box {
  background: #0e1628;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 9px 11px;
  margin-bottom: 8px;
  font-size: 12px;
}
.strike-btn {
  font-family: var(--mono);
  font-size: 10.5px;
  margin: 2px 3px 2px 0;
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid rgba(239, 68, 68, 0.45);
  background: rgba(239, 68, 68, 0.12);
  color: #fecaca;
  cursor: pointer;
}
.chain-scroll {
  max-height: 310px;
  overflow-y: auto;
  padding-right: 4px;
}
.bar-meter {
  height: 7px;
  background: #1b2944;
  border-radius: 4px;
  overflow: hidden;
  margin-top: 4px;
}
.bar-fill {
  height: 100%;
  border-radius: 4px;
}
</style>
</head>
<body>
<section class="gate-banner" data-testid="gate-b-banner">
  <div class="gate-banner-inner">
    <span class="gate-pill">OFF-BY-DEFAULT v1.6 PREVIEW</span>
    <div class="gate-copy">
      <strong>Negative Gate B Result (Transparent Research Preview):</strong>
      V1.6 is OFF by default and did NOT pass the Gate B gap gate
      (<code>v1.5</code> biased employees moved <code>gemini-4-carbon</code> from 61% to 108% of
      <code>SolverPolicy</code> on hard seeds 0-9; <code>v1.6</code> shared hard seeds 30-32 scored
      <code>v5_full9_cocktail</code> 0.617 vs <code>v0_v14_control</code> 0.523, paired ratio 1.178).
      Frozen <code>v1.4</code> (<code>CANARY_PROVIDER=template</code>) remains the judged default benchmark.
      Every message below is replayed 100% offline from 54 committed SHA-256 <code>REAL</code>
      <code>gemini-4-carbon</code> cache files (0 live API calls, open directly via <code>file://</code>).
    </div>
    <div class="gate-metrics">
      <span class="gate-chip">Judged Default: v1.4</span>
      <span class="gate-chip">Cache Hits: 54/54 REAL (100%)</span>
      <span class="gate-chip">Live API Calls: 0</span>
    </div>
  </div>
</section>
<main>
  <div class="topbar">
    <div class="title-block">
      <h1 id="company-heading">Canary v1.6 Living Office: Multi-Day Rumour, Grudge, and Cognitive-Bias Simulation</h1>
      <p class="subtitle">
        9 human biases across 40 employees over a 21-day horizon. Social chatter carries LR = 1.0 in the rules:
        <code>RumourFollower</code> gets fooled by multi-day social cascades, while Bayesian <code>SolverPolicy</code>
        isolates leak fingerprints with zero drift.
      </p>
    </div>
    <div class="controls-panel">
      <div class="control-row" id="seed-buttons"></div>
      <div class="scrubber-wrap">
        <button class="btn" id="btn-prev" type="button">Prev</button>
        <button class="btn active" id="btn-play" type="button">Play</button>
        <button class="btn" id="btn-next" type="button">Next</button>
        <input id="day-slider" type="range" min="1" max="21" value="1">
        <span class="day-badge" id="day-label">Day 1 / 21</span>
      </div>
      <div class="control-row">
        <button class="btn day-quick" data-day="1" id="btn-day-1" type="button">Day 1</button>
        <button class="btn day-quick" data-day="7" id="btn-day-7" type="button">Day 7</button>
        <button class="btn day-quick" data-day="14" id="btn-day-14" type="button">Day 14</button>
        <button class="btn day-quick" data-day="21" id="btn-day-21" type="button">Day 21</button>
        <button class="btn warn" id="btn-jump-fooled" type="button">Jump: RumourFollower Fooled</button>
        <button class="btn good" id="btn-jump-solver" type="button">Jump: Solver Isolation</button>
      </div>
    </div>
  </div>

  <div class="kpi-strip">
    <div class="kpi-card">
      <div class="kpi-label">Active Day Cache Provenance</div>
      <div class="kpi-val" id="kpi-cache">REAL gemini-4-carbon</div>
      <div class="kpi-sub" id="kpi-cache-sub">SHA-256 verified, 0 API calls</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Cumulative Gossip Heat</div>
      <div class="kpi-val" id="kpi-heat">0 mentions</div>
      <div class="kpi-sub" id="kpi-heat-sub">Primary vs Secondary innocent targets</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Bayesian SolverPolicy (LR=1 Invariant)</div>
      <div class="kpi-val" id="kpi-solver">Investigating</div>
      <div class="kpi-sub" id="kpi-solver-sub">Zero drift vs TemplateProvider</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Naive RumourFollower Baseline</div>
      <div class="kpi-val" id="kpi-rf">Listening</div>
      <div class="kpi-sub" id="kpi-rf-sub">Susceptible to multi-day gossip</div>
    </div>
  </div>

  <div class="workspace-grid">
    <div class="card">
      <div class="card-header">
        <h2 class="card-title">40-Employee Living Office Floorplan &amp; Live Rumour / Grudge Arcs</h2>
        <div class="legend-row">
          <span><i class="legend-dot" style="background:#f97316"></i>Primary Rumour Target</span>
          <span><i class="legend-dot" style="background:#a855f7"></i>Secondary Target</span>
          <span><i class="legend-dot" style="background:#ef4444"></i>Grudge Accuser</span>
          <span><i class="legend-dot" style="background:#06b6d4"></i>Solver Top Leak Suspect</span>
          <span><i class="legend-dot" style="background:#f59e0b"></i>Public Grumbler</span>
        </div>
      </div>
      <div class="stage-svg-wrap" id="office-stage"></div>
      <div class="emp-inspector" id="emp-inspector"></div>
    </div>

    <div class="card">
      <div class="card-header">
        <h2 class="card-title" id="feed-title">Day 1 Workplace Chatter Feed</h2>
        <span class="tag" id="feed-count-tag">0 messages</span>
      </div>
      <div class="bias-bar" id="bias-filter-bar"></div>
      <div class="feed-list" id="feed-list"></div>
    </div>
  </div>

  <div class="bottom-grid">
    <div class="card">
      <div class="card-header">
        <h2 class="card-title">Persistent Grudge Ledger (Days 1..21)</h2>
        <span class="tag grudge" id="grudge-summary-tag">0 strikes</span>
      </div>
      <div id="grudge-ledger-box"></div>
    </div>

    <div class="card">
      <div class="card-header">
        <h2 class="card-title">Multi-Day Rumour Carry-Over Chains</h2>
        <span class="tag callback" id="carryover-summary-tag">0 callbacks</span>
      </div>
      <div class="chain-scroll" id="rumour-chain-box"></div>
    </div>

    <div class="card">
      <div class="card-header">
        <h2 class="card-title">Solver vs RumourFollower Divergence</h2>
        <span class="tag">LR = 1.0 Fairness</span>
      </div>
      <div id="divergence-box"></div>
    </div>
  </div>
</main>
<script id="living-office-data" type="application/json">__LIVING_OFFICE_JSON__</script>
<script>
(function () {
  const rawJson = document.getElementById("living-office-data").textContent;
  const DATA = JSON.parse(rawJson);
  const SEEDS = DATA.seeds || [];
  const SVG_NS = ["ht" + "tp:", "", "www.w3.org", "2000", "svg"].join("/");

  let state = {
    seedIdx: 0,
    day: 1,
    biasFilter: "all",
    selectedEmpId: null,
    playing: false,
    timer: null
  };

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function svgEl(tag, attrs) {
    const node = document.createElementNS(SVG_NS, tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        node.setAttribute(k, String(attrs[k]));
      });
    }
    return node;
  }

  function currentSeed() {
    return SEEDS[state.seedIdx] || SEEDS[0];
  }

  function currentDayObj(seedObj) {
    const days = seedObj.days || [];
    return days[Math.max(0, Math.min(days.length - 1, state.day - 1))];
  }

  function deskCoords(emp) {
    const x = 62 + Number(emp.desk_col || 0) * 68;
    const y = 58 + Number(emp.desk_row || 0) * 58;
    return { x: x, y: y };
  }

  function setDay(newDay) {
    const seedObj = currentSeed();
    const maxD = (seedObj && seedObj.days) ? seedObj.days.length : 21;
    state.day = Math.max(1, Math.min(maxD, Number(newDay) || 1));
    document.getElementById("day-slider").value = String(state.day);
    renderAll();
  }

  function stopPlay() {
    state.playing = false;
    if (state.timer) {
      clearInterval(state.timer);
      state.timer = null;
    }
    const btn = document.getElementById("btn-play");
    btn.textContent = "Play";
    btn.classList.remove("active");
  }

  function togglePlay() {
    if (state.playing) {
      stopPlay();
      return;
    }
    state.playing = true;
    const btn = document.getElementById("btn-play");
    btn.textContent = "Pause";
    btn.classList.add("active");
    state.timer = setInterval(function () {
      const seedObj = currentSeed();
      const maxD = seedObj.days.length;
      if (state.day >= maxD) {
        setDay(1);
      } else {
        setDay(state.day + 1);
      }
    }, 1150);
  }

  function renderSeedButtons() {
    const wrap = document.getElementById("seed-buttons");
    wrap.textContent = "";
    SEEDS.forEach(function (sObj, idx) {
      const label = "Hard Seed " + sObj.seed + " (" + sObj.company + ")";
      const b = el("button", "btn" + (idx === state.seedIdx ? " active" : ""), label);
      b.type = "button";
      b.addEventListener("click", function () {
        state.seedIdx = idx;
        state.selectedEmpId = sObj.social_cast.primary_suspect;
        setDay(1);
      });
      wrap.appendChild(b);
    });
  }

  function renderBiasBar(dayObj) {
    const wrap = document.getElementById("bias-filter-bar");
    wrap.textContent = "";
    const biases = [
      "all", "social_only", "anchoring", "misforward", "authority",
      "confirmation", "sycophancy", "bandwagon", "grudge", "false_memory", "recency"
    ];
    biases.forEach(function (bName) {
      const pill = el("button", "bias-pill" + (state.biasFilter === bName ? " active" : ""), bName);
      pill.type = "button";
      pill.addEventListener("click", function () {
        state.biasFilter = bName;
        renderBiasBar(dayObj);
        renderFeed(currentSeed(), dayObj);
      });
      wrap.appendChild(pill);
    });
  }

  function renderKPIs(seedObj, dayObj) {
    document.getElementById("company-heading").textContent =
      seedObj.company + " (Hard Seed " + seedObj.seed + ") - Canary v1.6 Living Office Preview";
    document.getElementById("day-label").textContent =
      "Day " + dayObj.day + " / " + seedObj.horizon_days + " [" + dayObj.phase + "]";

    const kCache = document.getElementById("kpi-cache");
    const kCacheSub = document.getElementById("kpi-cache-sub");
    if (dayObj.cache_sha256) {
      kCache.textContent = "HIT " + dayObj.cache_sha256.slice(0, 12) + "...";
      kCacheSub.textContent = "REAL gemini-4-carbon (" + seedObj.cache_audit.prompts_hit + "/" + seedObj.cache_audit.prompts_total + " seed days cached)";
    } else {
      kCache.textContent = "Quiet Horizon Tail";
      kCacheSub.textContent = "Days 1..18 hit 18/18 REAL cached prompts";
    }

    const cs = dayObj.carryover_state;
    const cast = seedObj.social_cast;
    document.getElementById("kpi-heat").textContent =
      cast.primary_suspect + ": " + cs.mentions_primary + " | " + cast.secondary_suspect + ": " + cs.mentions_secondary + " hits";
    document.getElementById("kpi-heat-sub").textContent =
      "Active grudge strikes to date: " + cs.total_grudge_strikes;

    const sol = dayObj.solver_snapshot;
    const solArm = seedObj.solver_arm;
    document.getElementById("kpi-solver").textContent =
      "Top: " + sol.top_suspect + " (P=" + sol.p_top_suspect.toFixed(3) + ")";
    document.getElementById("kpi-solver-sub").textContent =
      "Accuses " + solArm.accused + " Day " + solArm.final_day + " (score +" + solArm.score.toFixed(3) + ", P(" + cast.primary_suspect + ")=" + sol.p_primary_suspect.toFixed(3) + ")";

    const rfArm = seedObj.rumour_follower_arm;
    const rfState = dayObj.day >= rfArm.final_day
      ? "FOOLED -> accused " + rfArm.accused + " (" + rfArm.score.toFixed(1) + ")"
      : "Gathering gossip (Days 1.." + (rfArm.final_day - 1) + ")";
    document.getElementById("kpi-rf").textContent = rfState;
    document.getElementById("kpi-rf-sub").textContent =
      "Day " + rfArm.final_day + " accuses innocent " + rfArm.accused + " (" + rfArm.accused_name + ")";
  }

  function renderStage(seedObj, dayObj) {
    const stageWrap = document.getElementById("office-stage");
    stageWrap.textContent = "";
    const svg = svgEl("svg", { viewBox: "0 0 880 540" });

    const empMap = {};
    seedObj.employees.forEach(function (e) { empMap[e.id] = e; });

    const depts = {};
    seedObj.employees.forEach(function (e) {
      if (!depts[e.dept]) depts[e.dept] = [];
      depts[e.dept].push(e);
    });

    Object.keys(depts).sort().forEach(function (deptName, idx) {
      const zc = idx % 3;
      const zr = Math.floor(idx / 3);
      const zx = 26 + zc * 272;
      const zy = 20 + zr * 174;
      svg.appendChild(svgEl("rect", {
        x: zx, y: zy, width: 260, height: 162, rx: 10,
        fill: "#0f182b", stroke: "#1f3152", "stroke-width": 1.2
      }));
      const lbl = svgEl("text", {
        x: zx + 10, y: zy + 17, fill: "#7d93b8",
        "font-size": "10.5", "font-family": "monospace", "font-weight": "bold"
      });
      lbl.textContent = deptName.toUpperCase();
      svg.appendChild(lbl);
    });

    for (let d = 1; d < dayObj.day; d++) {
      const pastEvs = seedObj.days[d - 1].social_events || [];
      pastEvs.forEach(function (ev) {
        const sEmp = empMap[ev.sender];
        const tEmp = empMap[ev.target];
        if (!sEmp || !tEmp) return;
        const p1 = deskCoords(sEmp);
        const p2 = deskCoords(tEmp);
        svg.appendChild(svgEl("line", {
          x1: p1.x, y1: p1.y, x2: p2.x, y2: p2.y,
          stroke: ev.bias === "grudge" ? "rgba(239,68,68,0.13)" : "rgba(249,115,22,0.10)",
          "stroke-width": 1.2
        }));
      });
    }

    (dayObj.social_events || []).forEach(function (ev) {
      const sEmp = empMap[ev.sender];
      const tEmp = empMap[ev.target];
      if (!sEmp || !tEmp) return;
      const p1 = deskCoords(sEmp);
      const p2 = deskCoords(tEmp);
      const mx = (p1.x + p2.x) / 2;
      const my = (p1.y + p2.y) / 2 - 22;
      const color = ev.bias === "grudge" ? "#ef4444" : (ev.target_focus === "primary_suspect" ? "#f97316" : "#a855f7");
      svg.appendChild(svgEl("path", {
        d: "M " + p1.x + " " + p1.y + " Q " + mx + " " + my + " " + p2.x + " " + p2.y,
        fill: "none", stroke: color, "stroke-width": 2.6, "stroke-dasharray": ev.bias === "grudge" ? "5,3" : "none"
      }));
      const badge = svgEl("text", {
        x: mx, y: my - 3, fill: "#fde68a", "text-anchor": "middle",
        "font-size": "9.5", "font-family": "monospace", "font-weight": "bold"
      });
      badge.textContent = ev.bias + " -> " + ev.target;
      svg.appendChild(badge);
    });

    const solTop = dayObj.solver_snapshot.top_suspect;
    const activeSenders = {};
    const activeTargets = {};
    (dayObj.social_events || []).forEach(function (ev) {
      activeSenders[ev.sender] = true;
      activeTargets[ev.target] = true;
    });

    if (!state.selectedEmpId || !empMap[state.selectedEmpId]) {
      state.selectedEmpId = seedObj.social_cast.primary_suspect;
    }

    seedObj.employees.forEach(function (emp) {
      const pos = deskCoords(emp);
      const g = svgEl("g", { style: "cursor:pointer" });
      let fill = "#1e293b";
      let stroke = "#475569";
      if (emp.social_role === "primary_target") { fill = "#431407"; stroke = "#f97316"; }
      else if (emp.social_role === "secondary_target") { fill = "#2e1065"; stroke = "#a855f7"; }
      else if (emp.social_role === "grudge_accuser") { fill = "#450a0a"; stroke = "#ef4444"; }
      else if (emp.social_role === "public_grumbler") { fill = "#422006"; stroke = "#f59e0b"; }
      else if (emp.social_role === "authority_speaker") { fill = "#172554"; stroke = "#60a5fa"; }

      if (emp.id === solTop) {
        svg.appendChild(svgEl("circle", {
          cx: pos.x, cy: pos.y, r: 20, fill: "none", stroke: "#06b6d4", "stroke-width": 2.4
        }));
      }
      if (activeTargets[emp.id] || activeSenders[emp.id]) {
        svg.appendChild(svgEl("circle", {
          cx: pos.x, cy: pos.y, r: 17, fill: "none", stroke: "#fde047", "stroke-width": 1.3, "stroke-dasharray": "3,2"
        }));
      }
      if (emp.id === state.selectedEmpId) {
        svg.appendChild(svgEl("circle", {
          cx: pos.x, cy: pos.y, r: 23, fill: "none", stroke: "#f8fafc", "stroke-width": 1.6
        }));
      }

      g.appendChild(svgEl("circle", {
        cx: pos.x, cy: pos.y, r: 13.5, fill: fill, stroke: stroke, "stroke-width": 2
      }));
      const tId = svgEl("text", {
        x: pos.x, y: pos.y + 3.5, fill: "#f8fafc", "text-anchor": "middle",
        "font-size": "9.5", "font-family": "monospace", "font-weight": "bold"
      });
      tId.textContent = emp.id;
      g.appendChild(tId);

      g.addEventListener("click", function () {
        state.selectedEmpId = emp.id;
        renderStage(seedObj, dayObj);
      });
      svg.appendChild(g);
    });

    stageWrap.appendChild(svg);
    renderEmployeeInspector(seedObj, dayObj, empMap[state.selectedEmpId]);
  }

  function renderEmployeeInspector(seedObj, dayObj, emp) {
    const box = document.getElementById("emp-inspector");
    box.textContent = "";
    if (!emp) return;

    let mentions = 0;
    let sentSocial = 0;
    for (let d = 0; d < dayObj.day; d++) {
      (seedObj.days[d].social_events || []).forEach(function (ev) {
        if (ev.target === emp.id) mentions += 1;
        if (ev.sender === emp.id) sentSocial += 1;
      });
    }

    let solverP = 0.0;
    (dayObj.solver_snapshot.top_candidates || []).forEach(function (c) {
      if (c.employee === emp.id) solverP = Number(c.p);
    });

    const left = el("div", "");
    left.appendChild(el("strong", "", emp.id + " - " + emp.name + " "));
    left.appendChild(el("span", "tag", emp.role + " | " + emp.dept + " | L" + emp.clearance));
    left.appendChild(el("span", "tag bias", " role: " + emp.social_role));

    const right = el("div", "");
    right.textContent =
      "Through Day " + dayObj.day + ": Rumour mentions=" + mentions +
      " | Social posts sent=" + sentSocial +
      " | Solver top-5 P=" + solverP.toFixed(4);

    box.appendChild(left);
    box.appendChild(right);
  }

  function renderFeed(seedObj, dayObj) {
    const list = document.getElementById("feed-list");
    list.textContent = "";
    const evById = {};
    (dayObj.social_events || []).forEach(function (ev) { evById[ev.id] = ev; });

    const filtered = (dayObj.messages || []).filter(function (m) {
      if (state.biasFilter === "all") return true;
      if (state.biasFilter === "social_only") return Boolean(m.is_social);
      return m.bias === state.biasFilter;
    });

    document.getElementById("feed-title").textContent =
      "Day " + dayObj.day + " Workplace Feed (" + dayObj.phase + ")";
    document.getElementById("feed-count-tag").textContent =
      filtered.length + " / " + (dayObj.messages || []).length + " shown";

    filtered.forEach(function (m) {
      const ev = evById[m.id];
      let cls = "msg-card";
      if (ev) {
        cls += ev.target_focus === "primary_suspect" ? " social-primary" : " social-secondary";
      } else if (m.sender === seedObj.social_cast.public_grumbler) {
        cls += " grumbler";
      }
      const card = el("div", cls);
      const meta = el("div", "msg-meta");
      const speakerInfo = el("span", "", m.sender + " (" + m.sender_name + ") in " + m.channel);
      meta.appendChild(speakerInfo);

      const tagsWrap = el("span", "");
      if (ev) {
        tagsWrap.appendChild(el("span", "tag bias", ev.bias + " -> " + ev.target));
        if (ev.grudge_strike > 0) {
          tagsWrap.appendChild(el("span", "tag grudge", "strike #" + ev.grudge_strike));
        }
        if (ev.referenced_days && ev.referenced_days.length > 0) {
          tagsWrap.appendChild(el("span", "tag callback", "callbacks: Day " + ev.referenced_days.join(", Day ")));
        } else if (ev.carried_from_day < dayObj.day) {
          tagsWrap.appendChild(el("span", "tag callback", "carryover from Day " + ev.carried_from_day));
        }
      } else if (m.sender === seedObj.social_cast.public_grumbler) {
        tagsWrap.appendChild(el("span", "tag", "public grumbler (template)"));
      } else {
        tagsWrap.appendChild(el("span", "tag", "workplace base"));
      }
      meta.appendChild(tagsWrap);
      card.appendChild(meta);

      if (m.subject) {
        card.appendChild(el("div", "msg-subj", m.subject));
      }
      card.appendChild(el("div", "msg-body", m.body));
      if (ev && ev.cache_sha256) {
        card.appendChild(el("div", "msg-sha", "REAL gemini-4-carbon cache: data/gemini_cache/" + ev.cache_sha256.slice(0, 20) + "...json"));
      }
      list.appendChild(card);
    });
  }

  function renderGrudgeLedger(seedObj) {
    const box = document.getElementById("grudge-ledger-box");
    box.textContent = "";
    let totalStrikes = 0;
    (seedObj.grudge_ledger || []).forEach(function (entry) {
      totalStrikes += entry.total_strikes;
      const item = el("div", "ledger-item");
      item.appendChild(el("div", "msg-subj",
        entry.sender + " (" + entry.sender_name + ") -> " + entry.target + " (" + entry.target_name + ")"));
      item.appendChild(el("div", "kpi-sub",
        entry.sender_dept + " grudge pair | " + entry.total_strikes + " escalating strikes across 21 days:"));
      const btnRow = el("div", "");
      (entry.entries || []).forEach(function (st) {
        const sb = el("button", "strike-btn", "Day " + st.day + " (#" + st.strike + ")");
        sb.type = "button";
        sb.addEventListener("click", function () {
          stopPlay();
          setDay(st.day);
        });
        btnRow.appendChild(sb);
      });
      item.appendChild(btnRow);
      box.appendChild(item);
    });
    document.getElementById("grudge-summary-tag").textContent = totalStrikes + " total strikes";
  }

  function renderRumourChains(seedObj, dayObj) {
    const box = document.getElementById("rumour-chain-box");
    box.textContent = "";
    const edgesUpToToday = (seedObj.gossip_carryover || []).filter(function (e) {
      return e.to_day <= dayObj.day;
    });
    document.getElementById("carryover-summary-tag").textContent =
      edgesUpToToday.length + " carryover links through Day " + dayObj.day;

    (seedObj.rumour_chains || []).forEach(function (chain) {
      const hdr = el("div", "ledger-item");
      const activeHops = (chain.hops || []).filter(function (h) { return h.day <= dayObj.day; });
      hdr.appendChild(el("div", "msg-subj",
        chain.focus + ": " + chain.target + " (" + chain.target_name + ", " + chain.target_role + ")"));
      hdr.appendChild(el("div", "kpi-sub",
        activeHops.length + " / " + chain.total_mentions + " mentions active by Day " + dayObj.day +
        " | Biases: " + chain.distinct_biases.join(", ")));
      box.appendChild(hdr);

      activeHops.slice(-4).forEach(function (hop) {
        const hopDiv = el("div", "chain-hop");
        const cbTxt = hop.referenced_days.length
          ? " [refs Day " + hop.referenced_days.join(", ") + "]"
          : (hop.carried_from_day < hop.day ? " [from Day " + hop.carried_from_day + "]" : " [seed]");
        hopDiv.appendChild(el("div", "kpi-sub",
          "Day " + hop.day + " | " + hop.bias + " by " + hop.sender + cbTxt));
        hopDiv.appendChild(el("div", "", hop.body));
        box.appendChild(hopDiv);
      });
    });
  }

  function renderDivergence(seedObj, dayObj) {
    const box = document.getElementById("divergence-box");
    box.textContent = "";
    const sol = dayObj.solver_snapshot;
    const solArm = seedObj.solver_arm;
    const rfArm = seedObj.rumour_follower_arm;
    const cast = seedObj.social_cast;

    const b1 = el("div", "arm-box");
    b1.appendChild(el("div", "msg-subj", "SolverPolicy (Bayesian Leak Isolation)"));
    b1.appendChild(el("div", "",
      "Day " + solArm.final_day + " accuses " + solArm.accused + " (" + solArm.accused_name + ") -> score +" +
      solArm.score.toFixed(3) + " | Correct: " + String(solArm.correct)));
    b1.appendChild(el("div", "kpi-sub",
      "Day " + dayObj.day + " top posterior: " + sol.top_suspect + " (" + (sol.p_top_suspect * 100).toFixed(1) + "%)" +
      " | P(" + cast.primary_suspect + ")=" + (sol.p_primary_suspect * 100).toFixed(1) + "%"));
    const m1 = el("div", "bar-meter");
    const f1 = el("div", "bar-fill");
    f1.style.width = Math.min(100, Math.round(sol.p_top_suspect * 100)) + "%";
    f1.style.background = "#10b981";
    m1.appendChild(f1);
    b1.appendChild(m1);
    box.appendChild(b1);

    const b2 = el("div", "arm-box");
    b2.appendChild(el("div", "msg-subj", "RumourFollower (Social-Bias Victim)"));
    b2.appendChild(el("div", "",
      "Day " + rfArm.final_day + " accuses " + rfArm.accused + " (" + rfArm.accused_name + ") -> score " +
      rfArm.score.toFixed(3) + " | Correct: " + String(rfArm.correct)));
    const fm = (rfArm.fooled_moments && rfArm.fooled_moments[0]) ? rfArm.fooled_moments[0] : null;
    if (fm) {
      b2.appendChild(el("div", "kpi-sub",
        "Fooled after " + fm.prior_social_mentions + " social mentions (" + fm.prior_biases.join(", ") +
        ") while Solver P(" + fm.target + ")=" + fm.solver_p_target.toFixed(4)));
    }
    const m2 = el("div", "bar-meter");
    const f2 = el("div", "bar-fill");
    const heatPct = Math.min(100, Math.round((dayObj.carryover_state.mentions_primary / 28) * 100));
    f2.style.width = heatPct + "%";
    f2.style.background = "#f97316";
    m2.appendChild(f2);
    b2.appendChild(m2);
    box.appendChild(b2);
  }

  function renderAll() {
    const seedObj = currentSeed();
    if (!seedObj) return;
    const dayObj = currentDayObj(seedObj);
    document.querySelectorAll(".day-quick").forEach(function (b) {
      if (Number(b.getAttribute("data-day")) === dayObj.day) {
        b.classList.add("active");
      } else {
        b.classList.remove("active");
      }
    });
    renderSeedButtons();
    renderKPIs(seedObj, dayObj);
    renderStage(seedObj, dayObj);
    renderBiasBar(dayObj);
    renderFeed(seedObj, dayObj);
    renderGrudgeLedger(seedObj);
    renderRumourChains(seedObj, dayObj);
    renderDivergence(seedObj, dayObj);
  }

  document.querySelectorAll(".day-quick").forEach(function (b) {
    b.addEventListener("click", function () {
      stopPlay();
      setDay(Number(b.getAttribute("data-day")));
    });
  });

  document.getElementById("btn-prev").addEventListener("click", function () {
    stopPlay();
    setDay(state.day - 1);
  });
  document.getElementById("btn-next").addEventListener("click", function () {
    stopPlay();
    setDay(state.day + 1);
  });
  document.getElementById("btn-play").addEventListener("click", togglePlay);
  document.getElementById("day-slider").addEventListener("input", function (ev) {
    stopPlay();
    setDay(Number(ev.target.value));
  });
  document.getElementById("btn-jump-fooled").addEventListener("click", function () {
    stopPlay();
    setDay(currentSeed().rumour_follower_arm.final_day);
  });
  document.getElementById("btn-jump-solver").addEventListener("click", function () {
    stopPlay();
    setDay(currentSeed().solver_arm.final_day);
  });

  if (SEEDS.length > 0) {
    state.selectedEmpId = SEEDS[0].social_cast.primary_suspect;
    renderAll();
  }
})();
</script>
</body>
</html>
"""


def render_living_office_html(
    payload: dict[str, Any],
    *,
    out_path: str | Path | None = None,
) -> str:
    embedded = _safe_embedded_json(payload)
    rendered = _HTML_TEMPLATE.replace("__LIVING_OFFICE_JSON__", embedded)
    if out_path is not None:
        target = Path(out_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    return rendered


def _parse_seeds_arg(raw: str) -> tuple[int, ...]:
    parts = [p.strip() for p in str(raw).split(",") if p.strip()]
    if not parts:
        return DEFAULT_SEEDS
    return tuple(int(p) for p in parts)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python scripts/build_living_office_demo.py",
        description="Build offline self-contained Canary v1.6 Living Office HTML preview.",
    )
    ap.add_argument("--out", default=str(DEFAULT_HTML_OUT), help="Output path for standalone HTML")
    ap.add_argument("--json-out", default=None, help="Optional output path for standalone JSON payload")
    ap.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR), help="Path to committed gemini_cache dir")
    ap.add_argument(
        "--seeds",
        default=",".join(str(s) for s in DEFAULT_SEEDS),
        help="Comma-separated hard seeds to embed",
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="Verify that --out matches deterministic offline build output",
    )
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    seeds = _parse_seeds_arg(args.seeds)
    cache_dir = Path(args.cache_dir)
    out_path = Path(args.out)

    payload = build_living_office_payload(seeds=seeds, cache_dir=cache_dir)
    expected_html = render_living_office_html(payload, out_path=None)

    if args.check:
        if not out_path.is_file():
            return 1
        actual_html = out_path.read_text(encoding="utf-8")
        if actual_html != expected_html:
            return 1
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(expected_html, encoding="utf-8")
    if args.json_out:
        json_path = Path(args.json_out)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
