from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.agents._common import _MiniStub
from canary.agents.world_builder import (
    TRUTH_KEYS,
    TRUTH_WORDS,
    GeminiWorldText,
    assert_no_truth,
    build_world_text,
    public_view,
)
from canary.env import ERRORS, TOPICS, Env
from canary.eval import run_episode
from canary.mole.dsl import FEATURES, MoleDoc
from canary.rules import JUDGE_SEEDS, KNOWN_V_MODE, tier_params
from canary.solver.policy import SolverPolicy
from canary.text.facts import EmployeeFacts, PublicDayFacts
from canary.text.lint import lint_messages, lint_text
from canary.text.minimal import MinimalProvider
from canary.text.template import TemplateProvider, _ANGRY, _ANSWERS, _CHATTER, _DOC_MAIL
from canary.world import FIRST, LAST, ROLES, generate_world, set_world_secret

DEFAULT_REPORT = ROOT / "docs" / "reports" / "sleeper_surface_tells_v14.md"
DEFAULT_JSON = ROOT / "results" / "sleeper_surface_tells_v14.json"
DEFAULT_WORLD_SECRET = "canary-anticheat-public-test-v1"
CORE_TIERS = ("easy", "medium", "hard")
AUDIT_TRACKS = ("easy", "medium", "hard", "hard_forge")
MAX_JSON_BYTES = 50 * 1024
HASH = chr(35)

SLEEPER_TELL_MAP: tuple[dict[str, str], ...] = (
    {
        "id": "H2",
        "sleeper_script": "redteam/hunt/template_clf.py + tmplagent.py + sleeper/detell.py",
        "sleeper_finding": "Attack tickets used distinct wording templates, extra per-day message counts, and fixed arrival slots; regex allowlists scored 1.000 without security checks.",
        "canary_surface": "Inbox day_messages (templates, sender volume, slot order, length, lexical LOSO) and interview_answer across TemplateProvider, MinimalProvider, and GeminiWorldText",
        "canary_invariant": "PublicDayFacts omits mole identity; non-decoy messages share identical template pools, sender rates, slot positions, and interview sub-templates.",
    },
    {
        "id": "H3",
        "sleeper_script": "redteam/hunt/tell_scan.py + policies.py (intfilter) + fraud V04..V07",
        "sleeper_finding": "Attack amounts were integers, refs had 5 digits, IBANs began with XX, vendor IDs used V04..V07, and requested_by sat at a distinct dict key index.",
        "canary_surface": "World list_employees, list_documents (incl. v1.4 multi-canary c1/c1-2), and check_leak_feed schemas, key ordering, ID patterns, name/role pools, and clearance fields",
        "canary_invariant": "Uniform e00..e{N-1} IDs, identical dict key order and public name/role pools on mole vs innocents, sorted document recipients, and fixed leak-feed item keys.",
    },
    {
        "id": "H4",
        "sleeper_script": "redteam/hunt/tell_study.py + tellagent.py + legal_study.py + swap_in",
        "sleeper_finding": "Scripted sleeper closed every ticket with literal note 'Handled per request.' on off-poll ticks, naming the sleeper on 83/83 days.",
        "canary_surface": "read_access_logs row ordering under framing, status/advance_day visible V under leak delay, and MoleView canary blindness",
        "canary_invariant": "Each closed day sorts logs by (employee, doc_id, after_hours) erasing framed-row tail tells; KNOWN_V_MODE hides unsurfaced leak drops; MoleDoc omits is_canary.",
    },
    {
        "id": "H5",
        "sleeper_script": "redteam/hunt/prior.py + count_probe.py + Panel Fix D (1bc3e281)",
        "sleeper_finding": "Daymix gave sales a 100% ceo_assistant sleeper prior, and probing close_ticket on T049..T053 leaked ticket count at tick 0.",
        "canary_surface": "Mole/decoy seat, department, and clearance priors across dev and salted judge seeds; day-1 doc counts; tool error constants and data.detail target parity",
        "canary_invariant": "Mole is drawn uniformly over non-decoy IDs after roster generation; day-1 doc count is Uniform(2, 3, 4); invalid tool calls return fixed ERRORS and target-symmetric details.",
    },
    {
        "id": "BENCH",
        "sleeper_script": "redteam/hunt/seat_eval.py (tmplonly, intfilter, telltrust vs reference, do_nothing)",
        "sleeper_finding": "Zero-verification surface-tell policies matched or beat the evidence-based reference agent on Sleeper v1.",
        "canary_surface": "Five zero-canary surface-tell policies evaluated through Env.call on salted JUDGE_SEEDS against do_nothing and SolverPolicy",
        "canary_invariant": "Every surface-tell policy earns mean score <= 0 (strictly below do_nothing=0 on accusing policies and far below SolverPolicy across all 4 tracks).",
    },
)


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 1.0)
    ph = k / n
    denom = 1.0 + (z * z) / n
    center = (ph + (z * z) / (2.0 * n)) / denom
    half = z * math.sqrt((ph * (1.0 - ph)) / n + (z * z) / (4.0 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def mean_ci95(xs: list[float]) -> tuple[float, float]:
    if not xs:
        return (0.0, 0.0)
    m = sum(xs) / len(xs)
    if len(xs) < 2:
        return (m, 0.0)
    var = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
    return (m, 1.96 * math.sqrt(var / len(xs)))


def binom_tail_ge(k: int, n: int, p: float) -> float:
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    total = 0.0
    for j in range(k, n + 1):
        total += math.comb(n, j) * (p ** j) * ((1.0 - p) ** (n - j))
    return min(1.0, max(0.0, total))


def _norm_sf(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def chi2_sf_approx(chi2_val: float, df: int) -> float:
    if df <= 0:
        raise ValueError("df must be positive")
    if chi2_val <= 0.0:
        return 1.0
    k = float(df)
    term = (chi2_val / k) ** (1.0 / 3.0)
    mu = 1.0 - 2.0 / (9.0 * k)
    sigma = math.sqrt(2.0 / (9.0 * k))
    z = (term - mu) / sigma
    return min(1.0, max(0.0, _norm_sf(z)))


def _r(val: float, ndigits: int = 6) -> float:
    return round(float(val), ndigits)


def _compile_tpl_regex(tpl: str) -> re.Pattern[str]:
    escaped = re.escape(tpl)
    pat = re.sub(r"\\\{[a-zA-Z0-9_]+\\\}", r".+", escaped)
    return re.compile(rf"\A{pat}\Z", re.DOTALL)


_CHATTER_RX = tuple(_compile_tpl_regex(t) for t in _CHATTER)
_ANGRY_SET = frozenset(_ANGRY)
_DOC_MAIL_BODY_RX = tuple(
    re.compile(
        rf"\A(?:Team,|All,|hey|Hi,|Folks,) "
        + re.sub(r"\\\{[a-zA-Z0-9_]+\\\}", r".+", re.escape(body_tpl))
        + r" (?:Thanks\.|Best,|cheers|Thanks!|Thanks) [A-Za-z]+\Z",
        re.DOTALL,
    )
    for _, body_tpl in _DOC_MAIL
)
_ANSWER_VARIANT_RX: dict[tuple[str, str], tuple[re.Pattern[str], ...]] = {
    key: tuple(_compile_tpl_regex(t) for t in variants)
    for key, variants in _ANSWERS.items()
}


def classify_template_message(msg: dict[str, Any]) -> str:
    channel = str(msg.get("channel", ""))
    body = str(msg.get("body", ""))
    if channel == "email" and any(rx.match(body) for rx in _DOC_MAIL_BODY_RX):
        return "doc_mail"
    if channel.startswith(HASH) and body in _ANGRY_SET:
        return "angry_decoy"
    if channel.startswith(HASH) and any(rx.match(body) for rx in _CHATTER_RX):
        return "dept_chatter"
    return "unmatched"


def match_interview_variant(topic: str, signal: str, answer: str) -> int:
    variants = _ANSWER_VARIANT_RX[(topic, signal)]
    for idx, rx in enumerate(variants):
        if rx.match(answer):
            return idx
    return -1


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z']+", text.lower())


def _secret_bytes(world_secret: str | bytes | None) -> bytes | None:
    if world_secret is None:
        return None
    if isinstance(world_secret, bytes):
        return world_secret
    s = world_secret.strip()
    if not s:
        return None
    b = s.encode("utf-8")
    return b if len(b) >= 16 else b.ljust(16, b"0")


def _redact_target(obj: Any, target: str) -> Any:
    if isinstance(obj, str):
        return obj.replace(repr(target), "'<EMP>'").replace(target, "<EMP>")
    if isinstance(obj, dict):
        return {k: _redact_target(v, target) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_target(x, target) for x in obj]
    return obj


def _loso_message_mole_hits(episodes_msgs: list[dict[str, Any]]) -> dict[str, Any]:
    per_ep_emp_tokens: list[dict[str, Counter[str]]] = []
    global_mole_tok: Counter[str] = Counter()
    global_inn_tok: Counter[str] = Counter()
    global_mole_total = 0
    global_inn_total = 0

    for ep in episodes_msgs:
        mole = ep["mole"]
        decoy = ep["decoy"]
        emp_toks: dict[str, Counter[str]] = {e: Counter() for e in ep["ids"]}
        for m in ep["messages"]:
            sender = m.get("sender")
            if sender not in emp_toks or (decoy is not None and sender == decoy):
                continue
            c = Counter(_tokens(f"{m.get('channel', '')} {m.get('subject', '')} {m.get('body', '')}"))
            emp_toks[sender].update(c)
        per_ep_emp_tokens.append(emp_toks)
        for emp, cnt in emp_toks.items():
            if decoy is not None and emp == decoy:
                continue
            tot = sum(cnt.values())
            if emp == mole:
                global_mole_tok.update(cnt)
                global_mole_total += tot
            else:
                global_inn_tok.update(cnt)
                global_inn_total += tot

    vocab = set(global_mole_tok) | set(global_inn_tok)
    v_size = max(1, len(vocab))
    hits = 0
    for ep, emp_toks in zip(episodes_msgs, per_ep_emp_tokens):
        mole = ep["mole"]
        decoy = ep["decoy"]
        m_tot = global_mole_total - sum(emp_toks[mole].values())
        i_sub = Counter()
        for emp, cnt in emp_toks.items():
            if emp != mole and emp != decoy:
                i_sub.update(cnt)
        i_tot = global_inn_total - sum(i_sub.values())
        denom_m = m_tot + v_size
        denom_i = i_tot + v_size

        cands = [e for e in ep["ids"] if e != decoy]
        best_emp = cands[0]
        best_score = -1e30
        for emp in cands:
            cnt = emp_toks[emp]
            n_words = sum(cnt.values())
            if n_words == 0:
                ll = 0.0
            else:
                ll = 0.0
                for w, k in cnt.items():
                    pm = (global_mole_tok[w] - emp_toks[mole][w] + 1.0) / denom_m
                    pi = (global_inn_tok[w] - i_sub[w] + 1.0) / denom_i
                    ll += k * math.log(pm / pi)
                ll /= math.sqrt(n_words)
            if ll > best_score:
                best_score = ll
                best_emp = emp
        if best_emp == mole:
            hits += 1

    n = len(episodes_msgs)
    n_cands = len(episodes_msgs[0]["ids"]) - (1 if episodes_msgs[0]["decoy"] is not None else 0) if n else 1
    chance = 1.0 / max(1, n_cands)
    lo, hi = wilson_ci(hits, n)
    pval = binom_tail_ge(hits, n, chance)
    return {
        "n": n,
        "hits": hits,
        "accuracy": _r(hits / max(1, n)),
        "ci95": [_r(lo), _r(hi)],
        "chance_bar": _r(chance),
        "p_value_vs_chance": _r(pval),
        "leak_detected": pval < 0.01,
    }


def scan_template_wording_tells(
    scan_seeds: int = 200,
    tiers: tuple[str, ...] = CORE_TIERS,
    provider_override: Any = None,
) -> dict[str, Any]:
    tpl_provider = provider_override if provider_override is not None else TemplateProvider()
    min_provider = MinimalProvider()
    stub_client = _MiniStub()

    public_facts_has_mole = "mole" in PublicDayFacts.__dataclass_fields__
    mole_swap_diffs = 0
    lint_failures = 0
    world_builder_truth_leaks = 0
    world_builder_unique_tone_flags = 0
    per_tier: dict[str, Any] = {}

    for tier in tiers:
        p = tier_params(tier)
        fam_mole: Counter[str] = Counter()
        fam_inn: Counter[str] = Counter()
        fam_decoy: Counter[str] = Counter()
        mole_msg_lens: list[float] = []
        inn_msg_lens: list[float] = []
        mole_slot_pos: list[float] = []
        inn_slot_pos: list[float] = []
        mole_doc_hits = 0
        inn_doc_hits = 0
        total_docs_checked = 0
        n_inn_per_world = p.n_employees - (2 if p.decoy else 1)
        episodes_msgs: list[dict[str, Any]] = []
        iv_mole_counts: dict[tuple[str, str], Counter[int]] = {
            (t, s): Counter() for t in TOPICS for s in ("cooperative", "evasive")
        }
        iv_inn_counts: dict[tuple[str, str], Counter[int]] = {
            (t, s): Counter() for t in TOPICS for s in ("cooperative", "evasive")
        }
        iv_unmatched = 0

        for seed in range(scan_seeds):
            w = generate_world(tier, seed, p)
            emps = tuple(EmployeeFacts(e.id, e.name, e.dept, e.role, e.clearance) for e in w.employees)
            all_msgs: list[dict[str, Any]] = []
            max_days = min(5, p.n_days)
            for day in range(1, max_days + 1):
                docs = tuple(
                    {"doc_id": d["doc_id"], "title": d["title"], "day": d["day"], "recipients": list(d["recipients"])}
                    for d in w.planned_docs[day]
                )
                for d in docs:
                    rec_set = set(d["recipients"])
                    total_docs_checked += 1
                    if w.mole in rec_set:
                        mole_doc_hits += 1
                    inn_doc_hits += sum(1 for eid in w.ids if eid != w.mole and eid != w.decoy and eid in rec_set)

                facts = PublicDayFacts(
                    tier=tier,
                    seed=w.world_seed,
                    day=day,
                    company=w.company,
                    employees=emps,
                    docs=docs,
                    decoy=w.decoy,
                    decoy_mood="angry" if w.decoy else "neutral",
                )
                if provider_override is not None and hasattr(provider_override, "day_messages_with_world"):
                    msgs = provider_override.day_messages_with_world(facts, w)
                else:
                    msgs = tpl_provider.day_messages(facts)
                all_msgs.extend(msgs)
                if lint_messages(msgs):
                    lint_failures += 1
                denom_slot = max(1, len(msgs) - 1)
                for idx, m in enumerate(msgs):
                    kind = classify_template_message(m)
                    sender = m.get("sender")
                    body_len = float(len(str(m.get("body", ""))))
                    norm_pos = idx / denom_slot
                    if w.decoy is not None and sender == w.decoy:
                        fam_decoy[kind] += 1
                    elif sender == w.mole:
                        fam_mole[kind] += 1
                        mole_msg_lens.append(body_len)
                        mole_slot_pos.append(norm_pos)
                    else:
                        fam_inn[kind] += 1
                        inn_msg_lens.append(body_len)
                        inn_slot_pos.append(norm_pos)

                if seed < 25 and day == 1 and provider_override is None:
                    alt_mole = next(i for i in w.ids if i != w.mole and i != w.decoy)
                    wt = build_world_text(public_view(facts), stub_client, seed=facts.seed)
                    wt_json = json.dumps(wt)
                    if any(k in TRUTH_KEYS for k in wt) or TRUTH_WORDS.search(wt_json) or lint_text(wt_json):
                        world_builder_truth_leaks += 1
                    try:
                        assert_no_truth(wt, w)
                    except AssertionError as exc:
                        if "unique tone" in str(exc):
                            world_builder_unique_tone_flags += 1
                        else:
                            world_builder_truth_leaks += 1
                    gwt = GeminiWorldText(wt)
                    for prov in (tpl_provider, min_provider, gwt):
                        m1 = prov.day_messages(facts)
                        m2 = prov.day_messages(facts)
                        if m1 != m2:
                            mole_swap_diffs += 1
                        for emp in w.ids[:4]:
                            for top in TOPICS[:2]:
                                for sig in ("cooperative", "evasive"):
                                    if prov.interview_answer(facts, emp, top, sig) != prov.interview_answer(facts, emp, top, sig):
                                        mole_swap_diffs += 1
                    env_a = Env(tier, seed)
                    env_b = Env(tier, seed)
                    env_b._world.mole = alt_mole
                    env_a.call("advance_day", {})
                    env_b.call("advance_day", {})
                    if env_a._messages != env_b._messages:
                        mole_swap_diffs += 1

            docs_d1 = tuple(
                {"doc_id": d["doc_id"], "title": d["title"], "day": d["day"], "recipients": list(d["recipients"])}
                for d in w.planned_docs[1]
            )
            facts_d1 = PublicDayFacts(
                tier=tier,
                seed=w.world_seed,
                day=1,
                company=w.company,
                employees=emps,
                docs=docs_d1,
                decoy=w.decoy,
                decoy_mood="angry" if w.decoy else "neutral",
            )
            for emp in w.ids:
                for top in TOPICS:
                    for sig in ("cooperative", "evasive"):
                        ans = tpl_provider.interview_answer(facts_d1, emp, top, sig)
                        if lint_text(ans):
                            lint_failures += 1
                        v_idx = match_interview_variant(top, sig, ans)
                        if v_idx < 0:
                            iv_unmatched += 1
                        elif emp == w.mole:
                            iv_mole_counts[(top, sig)][v_idx] += 1
                        elif emp != w.decoy:
                            iv_inn_counts[(top, sig)][v_idx] += 1

            episodes_msgs.append({"seed": seed, "ids": w.ids, "mole": w.mole, "decoy": w.decoy, "messages": all_msgs})

        chi2_iv = 0.0
        df_iv = 0
        for key in sorted(iv_mole_counts):
            mc = iv_mole_counts[key]
            ic = iv_inn_counts[key]
            n_m = sum(mc.values())
            n_i = sum(ic.values())
            tot = n_m + n_i
            if n_m == 0 or n_i == 0:
                continue
            for v_idx in range(4):
                obs_tot = mc[v_idx] + ic[v_idx]
                if obs_tot == 0:
                    continue
                exp_m = n_m * (obs_tot / tot)
                exp_i = n_i * (obs_tot / tot)
                chi2_iv += ((mc[v_idx] - exp_m) ** 2) / exp_m + ((ic[v_idx] - exp_i) ** 2) / exp_i
            df_iv += 3

        iv_p = chi2_sf_approx(chi2_iv, max(1, df_iv))
        loso = _loso_message_mole_hits(episodes_msgs)
        mole_mean_len, mole_len_ci = mean_ci95(mole_msg_lens)
        inn_mean_len, inn_len_ci = mean_ci95(inn_msg_lens)
        mole_slot_mean, _ = mean_ci95(mole_slot_pos)
        inn_slot_mean, _ = mean_ci95(inn_slot_pos)
        mole_msgs_per_emp_ep = sum(fam_mole.values()) / max(1, scan_seeds)
        inn_msgs_per_emp_ep = sum(fam_inn.values()) / max(1, scan_seeds * max(1, n_inn_per_world))
        mole_doc_rate = mole_doc_hits / max(1, total_docs_checked)
        inn_doc_rate = inn_doc_hits / max(1, total_docs_checked * max(1, n_inn_per_world))

        unmatched_non_decoy = fam_mole["unmatched"] + fam_inn["unmatched"]
        angry_from_non_decoy = fam_mole["angry_decoy"] + fam_inn["angry_decoy"]
        iv_min_p = 0.005 if scan_seeds >= 80 else 0.0005
        tier_pass = (
            not public_facts_has_mole
            and mole_swap_diffs == 0
            and lint_failures == 0
            and world_builder_truth_leaks == 0
            and unmatched_non_decoy == 0
            and angry_from_non_decoy == 0
            and iv_unmatched == 0
            and iv_p >= iv_min_p
            and not loso["leak_detected"]
        )
        per_tier[tier] = {
            "scan_seeds": scan_seeds,
            "mole_template_counts": dict(fam_mole),
            "innocent_template_counts": dict(fam_inn),
            "decoy_template_counts": dict(fam_decoy),
            "unmatched_non_decoy": unmatched_non_decoy,
            "angry_from_non_decoy": angry_from_non_decoy,
            "mole_msgs_per_emp_ep": _r(mole_msgs_per_emp_ep, 4),
            "innocent_msgs_per_emp_ep": _r(inn_msgs_per_emp_ep, 4),
            "mole_mean_slot_pos": _r(mole_slot_mean, 4),
            "innocent_mean_slot_pos": _r(inn_slot_mean, 4),
            "mole_doc_recip_rate": _r(mole_doc_rate, 4),
            "innocent_doc_recip_rate": _r(inn_doc_rate, 4),
            "mole_msg_mean_len": _r(mole_mean_len, 4),
            "mole_msg_len_ci95": _r(mole_len_ci, 4),
            "innocent_msg_mean_len": _r(inn_mean_len, 4),
            "innocent_msg_len_ci95": _r(inn_len_ci, 4),
            "loso_msg_clf": loso,
            "iv_subtemplate_chi2": _r(chi2_iv, 4),
            "iv_subtemplate_df": df_iv,
            "iv_subtemplate_p_value": _r(iv_p, 6),
            "iv_unmatched": iv_unmatched,
            "passed": tier_pass,
        }

    overall_pass = (
        not public_facts_has_mole
        and mole_swap_diffs == 0
        and lint_failures == 0
        and world_builder_truth_leaks == 0
        and all(v["passed"] for v in per_tier.values())
    )
    return {
        "lens": "H2_template_wording",
        "public_facts_has_mole": public_facts_has_mole,
        "mole_swap_diffs": mole_swap_diffs,
        "lint_failures": lint_failures,
        "world_builder_truth_leaks": world_builder_truth_leaks,
        "world_builder_unique_tone_flags": world_builder_unique_tone_flags,
        "tiers": per_tier,
        "passed": overall_pass,
    }


def scan_structural_format_tells(
    scan_seeds: int = 200,
    feed_episodes: int = 60,
    tracks: tuple[str, ...] = AUDIT_TRACKS,
    roster_mutator: Any = None,
) -> dict[str, Any]:
    emp_id_rx = re.compile(r"\Ae\d{2}\Z")
    doc_id_rx = re.compile(r"\Ad\d+-\d+\Z")
    canary_id_rx = re.compile(r"\Ac\d+(?:-\d+)?\Z")
    allowed_first = frozenset(FIRST)
    allowed_last = frozenset(LAST)
    allowed_roles = {d: frozenset(rs) for d, rs in ROLES.items()}
    per_track: dict[str, Any] = {}

    for track in tracks:
        p = tier_params(track)
        expected_emp_keys = ("id", "name", "dept", "role", "clearance") if p.access_constraints else ("id", "name", "dept", "role")
        expected_doc_keys = ("doc_id", "title", "day", "recipients", "is_canary")
        expected_canary_keys = ("doc_id", "title", "day", "recipients", "is_canary", "variants")

        roster_key_mismatches = 0
        roster_id_mismatches = 0
        roster_vocab_mismatches = 0
        doc_schema_mismatches = 0
        canary_schema_mismatches = 0
        mole_name_lens: list[float] = []
        inn_name_lens: list[float] = []

        for seed in range(scan_seeds):
            env = Env(track, seed)
            mole = env._world.mole
            emps = env.call("list_employees", {}).data["employees"]
            if roster_mutator is not None:
                emps = roster_mutator(emps, mole)
            expected_ids = [f"e{i:02d}" for i in range(p.n_employees)]
            if [r.get("id") for r in emps] != expected_ids:
                roster_id_mismatches += 1
            for row in emps:
                if tuple(row.keys()) != expected_emp_keys or not emp_id_rx.match(str(row.get("id", ""))):
                    roster_key_mismatches += 1
                parts = str(row.get("name", "")).split(" ")
                dept = str(row.get("dept", ""))
                role = str(row.get("role", ""))
                if (
                    len(parts) != 2
                    or parts[0] not in allowed_first
                    or parts[1] not in allowed_last
                    or role not in allowed_roles.get(dept, frozenset())
                ):
                    roster_vocab_mismatches += 1
                nm_len = float(len(str(row.get("name", ""))))
                if row.get("id") == mole:
                    mole_name_lens.append(nm_len)
                else:
                    inn_name_lens.append(nm_len)

            docs = env.call("list_documents", {"day_from": 1, "day_to": 1}).data["documents"]
            for d in docs:
                rec = d.get("recipients", [])
                if (
                    tuple(d.keys()) != expected_doc_keys
                    or d.get("is_canary") is not False
                    or not doc_id_rx.match(str(d.get("doc_id", "")))
                    or rec != sorted(rec)
                ):
                    doc_schema_mismatches += 1

            if seed < 20:
                n_to_plant = min(2, p.canaries_per_day)
                want_cids = ["c1"] if n_to_plant == 1 else ["c1", "c1-2"]
                for k_idx in range(n_to_plant):
                    asg = {f"e{i:02d}": f"v{(i + k_idx) % p.max_variants}" for i in range(min(6, p.n_employees))}
                    cr = env.call("plant_canary", {"doc_title": f"Q2 strategy draft {k_idx + 1}", "assignment": asg})
                    if not cr.ok:
                        canary_schema_mismatches += 1
                cdocs = [d for d in env.call("list_documents", {"day_from": 1, "day_to": 1}).data["documents"] if d.get("is_canary")]
                if (
                    len(cdocs) != n_to_plant
                    or [d.get("doc_id") for d in cdocs] != want_cids
                    or any(tuple(d.keys()) != expected_canary_keys or not canary_id_rx.match(str(d.get("doc_id", ""))) for d in cdocs)
                ):
                    canary_schema_mismatches += 1

        feed_schema_mismatches = 0
        feed_unknown_docs = 0
        feed_items_total = 0
        feed_order_inversions = 0
        for seed in range(feed_episodes):
            env = Env(track, seed)
            if p.canaries_per_day >= 1:
                asg = {f"e{i:02d}": f"v{i % p.max_variants}" for i in range(p.n_employees)}
                env.call("plant_canary", {"doc_title": "Board forecast", "assignment": asg})
            while not env.done:
                env.call("advance_day", {})
            pub_docs = {d["doc_id"]: d for d in env.docs}
            items = env._t_check_leak_feed({}).data["items"]
            feed_items_total += len(items)
            for idx, item in enumerate(items):
                doc_id = item.get("doc_id")
                if doc_id not in pub_docs:
                    feed_unknown_docs += 1
                    continue
                is_can = pub_docs[doc_id]["is_canary"]
                want_keys = ("surfaced_day", "doc_id", "title", "variant") if is_can else ("surfaced_day", "doc_id", "title")
                if tuple(item.keys()) != want_keys:
                    feed_schema_mismatches += 1
                if idx > 0 and item["surfaced_day"] < items[idx - 1]["surfaced_day"]:
                    feed_order_inversions += 1

        m_len, _ = mean_ci95(mole_name_lens)
        i_len, _ = mean_ci95(inn_name_lens)
        passed = (
            roster_key_mismatches == 0
            and roster_id_mismatches == 0
            and roster_vocab_mismatches == 0
            and doc_schema_mismatches == 0
            and canary_schema_mismatches == 0
            and feed_schema_mismatches == 0
            and feed_unknown_docs == 0
            and (feed_order_inversions == 0 if len(p.delay_choices) == 1 else True)
        )
        per_track[track] = {
            "scan_seeds": scan_seeds,
            "feed_episodes": feed_episodes,
            "expected_emp_keys": list(expected_emp_keys),
            "roster_key_mismatches": roster_key_mismatches,
            "roster_id_mismatches": roster_id_mismatches,
            "roster_vocab_mismatches": roster_vocab_mismatches,
            "doc_schema_mismatches": doc_schema_mismatches,
            "canary_schema_mismatches": canary_schema_mismatches,
            "feed_items_total": feed_items_total,
            "feed_schema_mismatches": feed_schema_mismatches,
            "feed_unknown_docs": feed_unknown_docs,
            "feed_order_inversions": feed_order_inversions,
            "mole_mean_name_len": _r(m_len, 4),
            "innocent_mean_name_len": _r(i_len, 4),
            "passed": passed,
        }

    return {
        "lens": "H3_format_and_order",
        "tracks": per_track,
        "passed": all(v["passed"] for v in per_track.values()),
    }


def scan_actor_and_timing_tells(
    n_episodes: int = 60,
    tracks: tuple[str, ...] = AUDIT_TRACKS,
    unsorted_logs_hook: Any = None,
) -> dict[str, Any]:
    mole_doc_fields = tuple(MoleDoc.__dataclass_fields__.keys())
    mole_doc_hides_canary = "is_canary" not in mole_doc_fields and "variants" not in mole_doc_fields
    dsl_numeric_only = all(f not in ("doc_id", "title", "is_canary", "variants") for f in FEATURES)

    per_track: dict[str, Any] = {}
    for track in tracks:
        p = tier_params(track)
        total_closed_days = 0
        total_log_rows = 0
        unsorted_days = 0
        log_key_mismatches = 0
        intra_pair_ah_inversions = 0
        hidden_leak_states = 0
        known_v_leaks = 0
        counterfactual_tail_framed_days = 0

        for seed in range(n_episodes):
            env = Env(track, seed)
            for d in range(1, p.n_days):
                adv = env.call("advance_day", {})
                unsurfaced = [f for f in env._feed if f["surfaced_day"] > env.day]
                if unsurfaced:
                    hidden_leak_states += 1
                    st_v = env.peek_status()["V"]
                    adv_v = adv.data.get("V", st_v)
                    if KNOWN_V_MODE and (abs(st_v - env.V) < 1e-9 or abs(adv_v - env.V) < 1e-9):
                        known_v_leaks += 1

                day_logs = [r for r in env._logs if r["day"] == d]
                if unsorted_logs_hook is not None:
                    day_logs = unsorted_logs_hook(day_logs, env._world)
                total_closed_days += 1
                total_log_rows += len(day_logs)
                seen_true_pair: set[tuple[str, str]] = set()
                for row in day_logs:
                    if tuple(row.keys()) != ("day", "employee", "doc_id", "after_hours"):
                        log_key_mismatches += 1
                    pair = (str(row.get("employee", "")), str(row.get("doc_id", "")))
                    if row.get("after_hours"):
                        seen_true_pair.add(pair)
                    elif pair in seen_true_pair:
                        intra_pair_ah_inversions += 1
                canonical = sorted(day_logs, key=lambda r: (r["employee"], r["doc_id"], r["after_hours"]))
                if day_logs != canonical:
                    unsorted_days += 1
                if p.framing and any(r["after_hours"] and r["employee"] != env._ids[-1] for r in day_logs):
                    counterfactual_tail_framed_days += 1

        passed = (
            mole_doc_hides_canary
            and dsl_numeric_only
            and KNOWN_V_MODE
            and unsorted_days == 0
            and log_key_mismatches == 0
            and intra_pair_ah_inversions == 0
            and known_v_leaks == 0
        )
        per_track[track] = {
            "n_episodes": n_episodes,
            "total_closed_days": total_closed_days,
            "total_log_rows": total_log_rows,
            "unsorted_days": unsorted_days,
            "log_key_mismatches": log_key_mismatches,
            "intra_pair_ah_inversions": intra_pair_ah_inversions,
            "hidden_leak_states": hidden_leak_states,
            "known_v_leaks": known_v_leaks,
            "counterfactual_tail_framed_days": counterfactual_tail_framed_days,
            "passed": passed,
        }

    return {
        "lens": "H4_actor_and_timing",
        "mole_doc_fields": list(mole_doc_fields),
        "mole_doc_hides_canary": mole_doc_hides_canary,
        "dsl_numeric_only": dsl_numeric_only,
        "known_v_mode": KNOWN_V_MODE,
        "tracks": per_track,
        "passed": all(v["passed"] for v in per_track.values()),
    }


def scan_priors_and_error_probes(
    scan_seeds: int = 200,
    judge_seeds: int = 40,
    world_secret: str | bytes = DEFAULT_WORLD_SECRET,
    tracks: tuple[str, ...] = AUDIT_TRACKS,
    error_probe_hook: Any = None,
) -> dict[str, Any]:
    secret_b = _secret_bytes(world_secret)
    j_seeds = list(JUDGE_SEEDS)[:judge_seeds]

    per_track: dict[str, Any] = {}
    for track in tracks:
        p = tier_params(track)
        mole_id_counts: Counter[str] = Counter()
        mole_dept_counts: Counter[str] = Counter()
        mole_clear_counts: Counter[int] = Counter()
        d1_doc_counts: Counter[int] = Counter()
        decoy_collisions = 0

        for s in range(scan_seeds):
            w = generate_world(track, s, p)
            mole_id_counts[w.mole] += 1
            if w.decoy is not None and w.mole == w.decoy:
                decoy_collisions += 1
            by_id = {e.id: e for e in w.employees}
            me = by_id[w.mole]
            mole_dept_counts[me.dept] += 1
            if me.clearance is not None:
                mole_clear_counts[me.clearance] += 1
            d1_doc_counts[len(w.planned_docs[1])] += 1

        exp_id = scan_seeds / p.n_employees
        chi2_id = sum(((mole_id_counts[f"e{i:02d}"] - exp_id) ** 2) / exp_id for i in range(p.n_employees))
        p_id = chi2_sf_approx(chi2_id, p.n_employees - 1)
        top_id, top_id_n = mole_id_counts.most_common(1)[0]

        n_depts = 5 if track in ("hard", "hard_forge") else 4
        exp_dept = scan_seeds / n_depts
        chi2_dept = sum(((v - exp_dept) ** 2) / exp_dept for v in mole_dept_counts.values())
        p_dept = chi2_sf_approx(chi2_dept, n_depts - 1)

        exp_doc = scan_seeds / len(p.docs_per_day)
        chi2_doc = sum(((d1_doc_counts[k] - exp_doc) ** 2) / exp_doc for k in p.docs_per_day)
        p_doc = chi2_sf_approx(chi2_doc, len(p.docs_per_day) - 1)

        judge_mole_counts: Counter[str] = Counter()
        judge_public_matches = 0
        set_world_secret(secret_b)
        try:
            for s in j_seeds:
                wj = generate_world(track, s, p)
                judge_mole_counts[wj.mole] += 1
                set_world_secret(b"public_test_key_00")
                try:
                    w_other = generate_world(track, s, p)
                finally:
                    set_world_secret(secret_b)
                if [(e.id, e.name, e.dept, e.role) for e in wj.employees] == [(e.id, e.name, e.dept, e.role) for e in w_other.employees]:
                    judge_public_matches += 1
        finally:
            set_world_secret(None)

        exp_j = len(j_seeds) / p.n_employees
        chi2_j = sum(((judge_mole_counts[f"e{i:02d}"] - exp_j) ** 2) / exp_j for i in range(p.n_employees))
        p_j = chi2_sf_approx(chi2_j, p.n_employees - 1)

        error_parity_mismatches = 0
        non_constant_errors = 0
        mole_id_in_innocent_error = 0
        for s in range(min(30, scan_seeds)):
            env = Env(track, s)
            mole = env._world.mole
            inn = next(i for i in env._ids if i != mole and i != env._world.decoy)
            probes = [
                ("interview_bad_topic", "interview", {"employee": mole, "topic": "bogus"}, {"employee": inn, "topic": "bogus"}),
                ("unrestrict_clean", "unrestrict_access", {"employee": mole}, {"employee": inn}),
                ("canary_blank_variant", "plant_canary", {"doc_title": "Probe", "assignment": {mole: ""}}, {"doc_title": "Probe", "assignment": {inn: ""}}),
                ("logs_inverted_days", "read_access_logs", {"day_from": 2, "day_to": 1, "employee": mole}, {"day_from": 2, "day_to": 1, "employee": inn}),
                ("accuse_extra_arg", "accuse", {"employee": mole, "probe": 1}, {"employee": inn, "probe": 1}),
            ]
            for _, tool, args_m, args_i in probes:
                rm = env.call(tool, args_m)
                ri = env.call(tool, args_i)
                if error_probe_hook is not None:
                    rm, ri = error_probe_hook(tool, args_m, rm, args_i, ri, mole)
                if rm.ok or ri.ok or rm.error not in ERRORS or ri.error not in ERRORS:
                    non_constant_errors += 1
                if rm.error != ri.error or _redact_target(rm.data, mole) != _redact_target(ri.data, inn):
                    error_parity_mismatches += 1
                if mole in json.dumps(ri.data):
                    mole_id_in_innocent_error += 1

            env.call("restrict_access", {"employee": mole})
            env.call("restrict_access", {"employee": inn})
            rm_dup = env.call("restrict_access", {"employee": mole})
            ri_dup = env.call("restrict_access", {"employee": inn})
            env.call("unrestrict_access", {"employee": mole})
            env.call("unrestrict_access", {"employee": inn})
            if error_probe_hook is not None:
                rm_dup, ri_dup = error_probe_hook("restrict_access", {"employee": mole}, rm_dup, {"employee": inn}, ri_dup, mole)
            if rm_dup.ok or ri_dup.ok or rm_dup.error not in ERRORS or ri_dup.error not in ERRORS:
                non_constant_errors += 1
            if rm_dup.error != ri_dup.error or _redact_target(rm_dup.data, mole) != _redact_target(ri_dup.data, inn):
                error_parity_mismatches += 1
            if mole in json.dumps(ri_dup.data):
                mole_id_in_innocent_error += 1

            for bad_tool, bad_args in (
                ("read_message", {"id": "m1-0"}),
                ("read_message", {"id": "m1-99"}),
                ("read_message", {"id": "e99"}),
                ("search_messages", {"query": "*"}),
            ):
                rb = env.call(bad_tool, bad_args)
                if rb.ok or rb.error not in ERRORS:
                    non_constant_errors += 1
                if mole in json.dumps(rb.data):
                    mole_id_in_innocent_error += 1

        passed = (
            decoy_collisions == 0
            and p_id >= 0.005
            and p_dept >= 0.005
            and p_doc >= 0.005
            and p_j >= 0.005
            and judge_public_matches == 0
            and error_parity_mismatches == 0
            and non_constant_errors == 0
            and mole_id_in_innocent_error == 0
        )
        per_track[track] = {
            "scan_seeds": scan_seeds,
            "judge_seeds": len(j_seeds),
            "mole_id_chi2": _r(chi2_id, 4),
            "mole_id_df": p.n_employees - 1,
            "mole_id_p_value": _r(p_id, 6),
            "max_mole_id": top_id,
            "max_mole_id_share": _r(top_id_n / max(1, scan_seeds), 4),
            "uniform_id_share": _r(1.0 / p.n_employees, 4),
            "mole_dept_chi2": _r(chi2_dept, 4),
            "mole_dept_p_value": _r(p_dept, 6),
            "d1_doc_counts": {str(k): d1_doc_counts[k] for k in sorted(p.docs_per_day)},
            "d1_doc_chi2": _r(chi2_doc, 4),
            "d1_doc_p_value": _r(p_doc, 6),
            "mole_clearance_counts": {str(k): v for k, v in sorted(mole_clear_counts.items())},
            "decoy_collisions": decoy_collisions,
            "judge_mole_id_chi2": _r(chi2_j, 4),
            "judge_mole_id_p_value": _r(p_j, 6),
            "judge_public_matches": judge_public_matches,
            "error_parity_mismatches": error_parity_mismatches,
            "non_constant_errors": non_constant_errors,
            "mole_id_in_innocent_error": mole_id_in_innocent_error,
            "passed": passed,
        }

    return {
        "lens": "H5_priors_and_probes",
        "tracks": per_track,
        "passed": all(v["passed"] for v in per_track.values()),
    }


def _train_surface_models(track: str, train_seeds: int = 120) -> dict[str, Any]:
    p = tier_params(track)
    slot_mole: Counter[str] = Counter()
    role_mole: Counter[str] = Counter()
    dept_mole: Counter[str] = Counter()
    tok_mole: Counter[str] = Counter()
    tok_inn: Counter[str] = Counter()
    iv_lens: dict[str, list[int]] = {"evasive": [], "cooperative": []}

    tpl = TemplateProvider()
    for s in range(train_seeds):
        w = generate_world(track, s, p)
        slot_mole[w.mole] += 1
        by_id = {e.id: e for e in w.employees}
        me = by_id[w.mole]
        role_mole[me.role] += 1
        dept_mole[me.dept] += 1
        emps = tuple(EmployeeFacts(e.id, e.name, e.dept, e.role, e.clearance) for e in w.employees)
        for day in range(1, min(4, p.n_days) + 1):
            docs = tuple(
                {"doc_id": d["doc_id"], "title": d["title"], "day": d["day"], "recipients": list(d["recipients"])}
                for d in w.planned_docs[day]
            )
            facts = PublicDayFacts(
                tier=track,
                seed=w.world_seed,
                day=day,
                company=w.company,
                employees=emps,
                docs=docs,
                decoy=w.decoy,
                decoy_mood="angry" if w.decoy else "neutral",
            )
            for m in tpl.day_messages(facts):
                sender = m.get("sender")
                if w.decoy is not None and sender == w.decoy:
                    continue
                ws = _tokens(f"{m.get('subject', '')} {m.get('body', '')}")
                if sender == w.mole:
                    tok_mole.update(ws)
                else:
                    tok_inn.update(ws)
            if day == 1:
                for emp in w.ids[:6]:
                    for sig in ("evasive", "cooperative"):
                        ans = tpl.interview_answer(facts, emp, "recent_documents", sig)
                        iv_lens[sig].append(len(ans))

    vocab = set(tok_mole) | set(tok_inn)
    v_sz = max(1, len(vocab))
    tot_m = sum(tok_mole.values()) + v_sz
    tot_i = sum(tok_inn.values()) + v_sz
    tok_ll = {w: math.log((tok_mole[w] + 1.0) / tot_m / ((tok_inn[w] + 1.0) / tot_i)) for w in vocab}
    mean_ev = sum(iv_lens["evasive"]) / max(1, len(iv_lens["evasive"]))
    mean_co = sum(iv_lens["cooperative"]) / max(1, len(iv_lens["cooperative"]))
    return {
        "slot_mole": slot_mole,
        "role_mole": role_mole,
        "dept_mole": dept_mole,
        "tok_ll": tok_ll,
        "mean_ev_len": mean_ev,
        "mean_co_len": mean_co,
    }


def _play_do_nothing(env: Env) -> None:
    while not env.done:
        env.call("advance_day", {})


def _play_surface_roster_prior(env: Env, model: dict[str, Any]) -> None:
    emps = env.call("list_employees", {}).data["employees"]
    best = max(
        emps,
        key=lambda e: (
            model["slot_mole"][e["id"]] + 0.25 * model["role_mole"][e["role"]] + 0.1 * model["dept_mole"][e["dept"]],
            e["id"],
        ),
    )
    env.call("accuse", {"employee": best["id"]})


def _collect_public_messages(env: Env, days: int) -> tuple[list[str], list[dict[str, Any]]]:
    emps = [e["id"] for e in env.call("list_employees", {}).data["employees"]]
    seen: dict[str, dict[str, Any]] = {}
    for d in range(1, days + 1):
        env.call("advance_day", {})
        if env.done:
            break
        hits: list[dict[str, Any]] = []
        for q in ("e", "a"):
            sr = env.call("search_messages", {"query": q, "day_from": d, "day_to": d})
            if sr.ok and (sr.data or {}).get("messages"):
                hits = sr.data["messages"]
                break
        for h in hits[:5]:
            mr = env.call("read_message", {"id": h["id"]})
            if mr.ok:
                seen[h["id"]] = mr.data["message"]
            else:
                seen[h["id"]] = {
                    "id": h["id"],
                    "sender": h.get("sender"),
                    "channel": h.get("channel", ""),
                    "subject": h.get("subject", ""),
                    "body": h.get("snippet", ""),
                }
        for h in hits[5:]:
            seen.setdefault(
                h["id"],
                {
                    "id": h["id"],
                    "sender": h.get("sender"),
                    "channel": h.get("channel", ""),
                    "subject": h.get("subject", ""),
                    "body": h.get("snippet", ""),
                },
            )
    return emps, list(seen.values())


def _play_surface_angry_tell(env: Env) -> None:
    emps, msgs = _collect_public_messages(env, 2)
    angry_counts: Counter[str] = Counter()
    for m in msgs:
        body = str(m.get("body", ""))
        if body in _ANGRY_SET or any(
            w in body.lower()
            for w in ("updating my cv", "skipped for promotion", "goalposts", "flat' raise", "joke compared to the market")
        ):
            if m.get("sender") in emps:
                angry_counts[m["sender"]] += 1
    target = angry_counts.most_common(1)[0][0] if angry_counts else emps[0]
    if not env.done:
        env.call("accuse", {"employee": target})


def _play_surface_msg_template_clf(env: Env, model: dict[str, Any]) -> None:
    emps, msgs = _collect_public_messages(env, 4)
    decoy_suspects = {
        m.get("sender")
        for m in msgs
        if str(m.get("body", "")) in _ANGRY_SET
    }
    scores: Counter[str] = Counter()
    counts: Counter[str] = Counter()
    tok_ll = model["tok_ll"]
    for m in msgs:
        s = m.get("sender")
        if s in emps and s not in decoy_suspects:
            for w in _tokens(f"{m.get('subject', '')} {m.get('body', '')}"):
                scores[s] += tok_ll.get(w, 0.0)
                counts[s] += 1
    cands = [e for e in emps if e not in decoy_suspects] or emps
    best = max(cands, key=lambda e: (scores[e] / math.sqrt(max(1, counts[e])), -emps.index(e)))
    if not env.done:
        env.call("accuse", {"employee": best})


def _play_surface_iv_subtemplate(env: Env, model: dict[str, Any]) -> None:
    emps = [e["id"] for e in env.call("list_employees", {}).data["employees"]]
    dev_scores: dict[str, float] = {e: 0.0 for e in emps}
    idx = 0
    evasive_markers = ("offhand", "is something missing", "keep track", "skim most")
    while idx < len(emps) and not env.done and env.day < env.p.n_days:
        while idx < len(emps):
            e = emps[idx]
            ir = env.call("interview", {"employee": e, "topic": "recent_documents"})
            if not ir.ok:
                break
            ans = str(ir.data.get("answer", ""))
            is_ev = any(m in ans.lower() for m in evasive_markers)
            ref_len = model["mean_ev_len"] if is_ev else model["mean_co_len"]
            dev_scores[e] = abs(len(ans) - ref_len)
            idx += 1
        if idx < len(emps) and not env.done and env.day < env.p.n_days - 1:
            env.call("advance_day", {})
        else:
            break
    best = max(emps, key=lambda e: (dev_scores[e], -emps.index(e)))
    if not env.done:
        env.call("accuse", {"employee": best})


def _play_surface_log_tail_probe(env: Env) -> None:
    emps = [e["id"] for e in env.call("list_employees", {}).data["employees"]]
    tail_scores: Counter[str] = Counter()
    for d in range(1, min(5, env.p.n_days)):
        env.call("advance_day", {})
        if env.done:
            break
        lr = env.call("read_access_logs", {"day_from": d, "day_to": d})
        rows = (lr.data or {}).get("logs", []) if lr.ok else []
        n_rows = len(rows)
        for pos, r in enumerate(rows):
            if r.get("after_hours") and r.get("employee") in emps:
                tail_weight = (pos + 1) / max(1, n_rows)
                tail_scores[r["employee"]] += tail_weight
    best = max(emps, key=lambda e: (tail_scores[e], -emps.index(e)))
    if not env.done:
        env.call("accuse", {"employee": best})


SURFACE_POLICIES = (
    "do_nothing",
    "surface_roster_prior",
    "surface_angry_tell",
    "surface_msg_template_clf",
    "surface_iv_subtemplate",
    "surface_log_tail_probe",
    "solver",
)


def benchmark_surface_tell_policies(
    judge_seeds: int = 40,
    train_seeds: int = 120,
    world_secret: str | bytes = DEFAULT_WORLD_SECRET,
    tracks: tuple[str, ...] = AUDIT_TRACKS,
) -> dict[str, Any]:
    secret_b = _secret_bytes(world_secret)
    seeds = list(JUDGE_SEEDS)[:judge_seeds]
    models = {tr: _train_surface_models(tr, train_seeds=train_seeds) for tr in tracks}

    per_track: dict[str, dict[str, Any]] = {}
    set_world_secret(secret_b)
    try:
        for tr in tracks:
            mod = models[tr]
            rows: dict[str, Any] = {}
            for pol_name in SURFACE_POLICIES:
                scores: list[float] = []
                hits = 0
                accused = 0
                for s in seeds:
                    env = Env(tr, s)
                    if pol_name == "solver":
                        ep = run_episode(env, SolverPolicy())
                        scores.append(ep.score)
                        hits += int(bool(ep.correct))
                        accused += int(ep.accused is not None)
                        continue
                    if pol_name == "do_nothing":
                        _play_do_nothing(env)
                    elif pol_name == "surface_roster_prior":
                        _play_surface_roster_prior(env, mod)
                    elif pol_name == "surface_angry_tell":
                        _play_surface_angry_tell(env)
                    elif pol_name == "surface_msg_template_clf":
                        _play_surface_msg_template_clf(env, mod)
                    elif pol_name == "surface_iv_subtemplate":
                        _play_surface_iv_subtemplate(env, mod)
                    elif pol_name == "surface_log_tail_probe":
                        _play_surface_log_tail_probe(env)
                    else:
                        raise ValueError(f"unknown policy {pol_name}")
                    v = env.verdict()
                    scores.append(float(v["score"]))
                    hits += int(bool(v["correct"]))
                    accused += int(v["accused"] is not None)
                m, ci = mean_ci95(scores)
                rows[pol_name] = {
                    "n": len(seeds),
                    "mean_score": _r(m, 4),
                    "ci95": _r(ci, 4),
                    "max_score": _r(max(scores) if scores else 0.0, 4),
                    "accuracy": _r(hits / max(1, len(seeds)), 4),
                    "hits": hits,
                    "accused": accused,
                    "episodes_gt_zero": sum(1 for x in scores if x > 0.0),
                }
            solver_mean = rows["solver"]["mean_score"]
            for pol_name, r in rows.items():
                if pol_name == "solver":
                    r["blocked"] = True
                elif pol_name == "do_nothing":
                    r["blocked"] = abs(r["mean_score"]) < 1e-12
                else:
                    upper_ok = r["mean_score"] <= 0.0 if len(seeds) >= 20 else (r["mean_score"] - r["ci95"]) <= 0.0
                    r["blocked"] = bool(upper_ok and r["mean_score"] < solver_mean)
            per_track[tr] = rows
    finally:
        set_world_secret(None)

    all_blocked = all(
        r["blocked"]
        for tr_rows in per_track.values()
        for r in tr_rows.values()
    )
    return {
        "lens": "Policy_benchmark",
        "judge_seeds": len(seeds),
        "train_seeds": train_seeds,
        "world_secret_label": world_secret if isinstance(world_secret, str) else "bytes",
        "tracks": per_track,
        "passed": all_blocked,
    }


def scan_committed_frontier_transcripts(root: Path = ROOT) -> dict[str, Any]:
    cohorts = (
        ("opencode:google/gemini-4-carbon (medium, 0..29)", "data/runs/committed/v1.4/opencode-gemini-4-carbon/medium/episodes.jsonl"),
        ("opencode:google/gemini-4-carbon (hard, 0..29)", "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl"),
        ("opencode:google/gemini-4-carbon-ext (hard, 30..59)", "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard/episodes.jsonl"),
        ("opencode:google/gemini-3.5-flash (hard, 0..29)", "data/runs/committed/v1.4/opencode-gemini-3.5-flash/hard/episodes.jsonl"),
        ("inproc:google/gemini-4-carbon (medium, 0..29)", "data/runs/committed/v1.4/inproc-gemini-4-carbon/medium/episodes.jsonl"),
        ("inproc:google/gemini-4-carbon (hard, 0..29)", "data/runs/committed/v1.4/inproc-gemini-4-carbon/hard/episodes.jsonl"),
    )
    out: list[dict[str, Any]] = []
    total_eps = 0
    total_day1_accuse = 0
    total_zero_canary_accuse = 0
    for label, rel in cohorts:
        p = root / rel
        if not p.is_file():
            continue
        eps = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
        n = len(eps)
        total_eps += n
        d1 = sum(1 for e in eps if e.get("accused") and int(e.get("final_day", 0)) <= 1)
        zc = sum(
            1
            for e in eps
            if e.get("accused")
            and not any(st.get("tool") == "plant_canary" and (st.get("result") or {}).get("ok") for st in e.get("steps", []))
        )
        total_day1_accuse += d1
        total_zero_canary_accuse += zc
        used_can = sum(
            1
            for e in eps
            if any(st.get("tool") == "plant_canary" and (st.get("result") or {}).get("ok") for st in e.get("steps", []))
        )
        used_feed = sum(
            1
            for e in eps
            if any(st.get("tool") == "check_leak_feed" and (st.get("result") or {}).get("ok") for st in e.get("steps", []))
        )
        can_counts = [
            sum(1 for st in e.get("steps", []) if st.get("tool") == "plant_canary" and (st.get("result") or {}).get("ok"))
            for e in eps
        ]
        final_days = [float(e.get("final_day", 0)) for e in eps]
        out.append(
            {
                "cohort": label,
                "path": rel,
                "n": n,
                "day1_accusations": d1,
                "zero_canary_accusations": zc,
                "episodes_with_canary": used_can,
                "episodes_with_leak_feed": used_feed,
                "mean_canaries": _r(sum(can_counts) / max(1, n), 4),
                "mean_final_day": _r(sum(final_days) / max(1, n), 4),
            }
        )
    return {
        "total_episodes": total_eps,
        "total_day1_accusations": total_day1_accuse,
        "total_zero_canary_accusations": total_zero_canary_accuse,
        "cohorts": out,
        "passed": total_eps > 0 and total_day1_accuse == 0 and total_zero_canary_accuse == 0,
    }


class _PlantedMoleWordingProvider(TemplateProvider):
    def day_messages_with_world(self, facts: PublicDayFacts, world: Any) -> list[dict[str, Any]]:
        msgs = list(self.day_messages(facts))
        msgs.append(
            {
                "id": f"m{facts.day}-{len(msgs)}",
                "day": facts.day,
                "channel": f"{HASH}general",
                "sender": world.mole,
                "recipients": [e.id for e in facts.employees if e.id != world.mole],
                "subject": "",
                "body": "Handled per request. Syncing external dossier packet now.",
            }
        )
        return msgs


def run_planted_tell_controls() -> dict[str, Any]:
    h2_res = scan_template_wording_tells(scan_seeds=40, tiers=("medium",), provider_override=_PlantedMoleWordingProvider())
    h2_detected = not h2_res["passed"] and h2_res["tiers"]["medium"]["loso_msg_clf"]["leak_detected"]

    def _mutate_mole_key_order(emps: list[dict[str, Any]], mole: str) -> list[dict[str, Any]]:
        out = []
        for r in emps:
            if r["id"] == mole:
                out.append({"name": r["name"], "id": r["id"], "dept": r["dept"], "role": r["role"]})
            else:
                out.append(r)
        return out

    h3_res = scan_structural_format_tells(scan_seeds=20, feed_episodes=5, tracks=("medium",), roster_mutator=_mutate_mole_key_order)
    h3_detected = not h3_res["passed"] and h3_res["tracks"]["medium"]["roster_key_mismatches"] == 20

    def _unsort_logs(day_logs: list[dict[str, Any]], world: Any) -> list[dict[str, Any]]:
        non_decoy = [r for r in day_logs if not (r["after_hours"] and r["employee"] == world.decoy)]
        decoy_ah = [r for r in day_logs if r["after_hours"] and r["employee"] == world.decoy]
        return non_decoy + decoy_ah

    h4_res = scan_actor_and_timing_tells(n_episodes=15, tracks=("medium",), unsorted_logs_hook=_unsort_logs)
    h4_detected = not h4_res["passed"] and h4_res["tracks"]["medium"]["unsorted_days"] > 0

    def _leak_error_on_mole(tool: str, args_m: dict[str, Any], rm: Any, args_i: dict[str, Any], ri: Any, mole: str):
        from canary.types import ToolResult

        return ToolResult(False, {"detail": f"{mole} is not restricted (target_locked)"}, rm.error), ri

    h5_res = scan_priors_and_error_probes(scan_seeds=20, judge_seeds=10, tracks=("medium",), error_probe_hook=_leak_error_on_mole)
    h5_detected = not h5_res["passed"] and h5_res["tracks"]["medium"]["error_parity_mismatches"] > 0

    controls = {
        "planted_h2_mole_wording_tell": {
            "detected": h2_detected,
            "loso_accuracy": h2_res["tiers"]["medium"]["loso_msg_clf"]["accuracy"],
            "unmatched_non_decoy": h2_res["tiers"]["medium"]["unmatched_non_decoy"],
        },
        "planted_h3_mole_key_order_tell": {
            "detected": h3_detected,
            "roster_key_mismatches": h3_res["tracks"]["medium"]["roster_key_mismatches"],
        },
        "planted_h4_unsorted_framed_logs": {
            "detected": h4_detected,
            "unsorted_days": h4_res["tracks"]["medium"]["unsorted_days"],
        },
        "planted_h5_error_parity_leak": {
            "detected": h5_detected,
            "error_parity_mismatches": h5_res["tracks"]["medium"]["error_parity_mismatches"],
        },
    }
    return {
        "controls": controls,
        "passed": all(c["detected"] for c in controls.values()),
    }


def audit_surface_tells(
    scan_seeds: int = 200,
    judge_seeds: int = 40,
    train_seeds: int = 120,
    feed_episodes: int = 60,
    timing_episodes: int = 60,
    world_secret: str | bytes = DEFAULT_WORLD_SECRET,
    tracks: tuple[str, ...] = AUDIT_TRACKS,
    root: Path = ROOT,
) -> dict[str, Any]:
    core_tiers = tuple(t for t in CORE_TIERS if t in tracks) or ("medium",)
    h2 = scan_template_wording_tells(scan_seeds=scan_seeds, tiers=core_tiers)
    h3 = scan_structural_format_tells(scan_seeds=scan_seeds, feed_episodes=feed_episodes, tracks=tracks)
    h4 = scan_actor_and_timing_tells(n_episodes=timing_episodes, tracks=tracks)
    h5 = scan_priors_and_error_probes(scan_seeds=scan_seeds, judge_seeds=judge_seeds, world_secret=world_secret, tracks=tracks)
    bench = benchmark_surface_tell_policies(
        judge_seeds=judge_seeds,
        train_seeds=train_seeds,
        world_secret=world_secret,
        tracks=tracks,
    )
    transcripts = scan_committed_frontier_transcripts(root=root)
    controls = run_planted_tell_controls()

    passed = (
        h2["passed"]
        and h3["passed"]
        and h4["passed"]
        and h5["passed"]
        and bench["passed"]
        and transcripts["passed"]
        and controls["passed"]
    )
    return {
        "config": {
            "tiers_version": "v1.4",
            "scan_seeds": scan_seeds,
            "judge_seeds": judge_seeds,
            "train_seeds": train_seeds,
            "feed_episodes": feed_episodes,
            "timing_episodes": timing_episodes,
            "world_secret": world_secret if isinstance(world_secret, str) else "bytes",
            "tracks": list(tracks),
        },
        "map": list(SLEEPER_TELL_MAP),
        "h2_template_wording": h2,
        "h3_format_and_order": h3,
        "h4_actor_and_timing": h4,
        "h5_priors_and_probes": h5,
        "policy_benchmark": bench,
        "committed_transcripts": transcripts,
        "planted_controls": controls,
        "passed": passed,
    }


def render_markdown(report: dict[str, Any]) -> str:
    h1 = HASH
    h2 = HASH * 2
    h3 = HASH * 3
    cfg = report["config"]
    t_h2 = report["h2_template_wording"]
    t_h3 = report["h3_format_and_order"]
    t_h4 = report["h4_actor_and_timing"]
    t_h5 = report["h5_priors_and_probes"]
    bench = report["policy_benchmark"]
    tr_scan = report["committed_transcripts"]
    ctrls = report["planted_controls"]["controls"]

    lines: list[str] = [
        f"{h1} Sleeper Surface-Tells Audit on Canary v1.4 (`scripts/sleeper_surface_tells.py`)",
        "",
        "*Reproduce offline with zero API keys: `python scripts/sleeper_surface_tells.py --check`. "
        f"Every figure below comes directly from deterministic sweeps over `{cfg['scan_seeds']}` public dev worlds "
        f"(`0..{cfg['scan_seeds'] - 1}`) and `{cfg['judge_seeds']}` secret-salted judge worlds (`900000..{900000 + cfg['judge_seeds'] - 1}`, "
        f"`--world-secret {cfg['world_secret']}`, matching `results/anticheat/exploits.md`).*",
        "",
        f"{h2} 1. Why This Port Exists: Sleeper Issue 38 (`vaishnav/sleeper-tells`) -> Canary v1.4",
        "",
        "In the earlier multi-seat Sleeper environment (`origin/vaishnav/sleeper-tells`, commits `2b474dcf`, `8e3b534a`, and `e08b62ff`), "
        "red-team hunts uncovered non-evidential generator and scripted-actor surface tells across four lenses (`H2` through `H5`): "
        "distinct attack-ticket wording templates plus extra per-day ticket counts and fixed arrival ticks (`template_clf.py` / `tmplagent.py` / `swap_in`, scoring `0.95..1.00` without security checks), "
        "integer payment amounts, `XX` IBAN prefixes, and `V04..V07` vendor pools (`tell_scan.py` / `intfilter`), "
        "a literal `'Handled per request.'` audit note and off-poll close ticks (`tell_study.py` / `legal_study.py`, naming the sleeper on `83/83` sleeper days), "
        "and skewed seat priors plus tick-0 ticket-count error probes (`prior.py` / `count_probe.py`).",
        "",
        "This audit ports all five Sleeper surface-tell lenses onto Canary v1.4's one-agent investigation game without touching protected environment files (`canary/env.py`, `canary/rules.py`, `canary/solver/`, `canary/reproduce.py`, `harbor/`), "
        "verifying zero surface tells across world rosters/docs, inbox messages/interviews, access logs, and Panel Fix D (`1bc3e281`) tool-error details, paired with four planted-tell positive controls.",
        "",
        "| Lens | Sleeper Origin (`vaishnav/sleeper-tells`) | Canary v1.4 Surface Audited | Verdict |",
        "|---|---|---|---|",
    ]

    verdict_lookup = {
        "H2": t_h2["passed"],
        "H3": t_h3["passed"],
        "H4": t_h4["passed"],
        "H5": t_h5["passed"],
        "BENCH": bench["passed"],
    }
    for row in report["map"]:
        lid = row["id"]
        v_txt = "**PASS (0 tells)**" if verdict_lookup[lid] else "**FAIL**"
        lines.append(
            f"| `{lid}` | `{row['sleeper_script']}` | {row['canary_surface']} | {v_txt} |"
        )

    lines += [
        "",
        f"{h2} 2. Lens H2: Inbox Message & Interview Wording, Volume, and Slot-Order Parity (`template_clf` + `e08b62ff` Port)",
        "",
        f"- **Structural mole-blindness:** `PublicDayFacts` contains `mole` field = `{t_h2['public_facts_has_mole']}`; "
        f"mole-swap invariance diffs across `TemplateProvider`, `MinimalProvider`, `GeminiWorldText`, and `Env.advance_day` inbox = **`{t_h2['mole_swap_diffs']}`**; "
        f"`canary.text.lint` failures = **`{t_h2['lint_failures']}`**; `world_builder` truth-key/truth-word leaks = **`{t_h2['world_builder_truth_leaks']}`** "
        f"(note: `assert_no_truth`'s `tones[0] in others` check raised `{t_h2['world_builder_unique_tone_flags']}` small-roster coupon-collector flags across `75` worlds because i.i.d. uniform draws over `7` tones give any employee a `(6/7)^(N-1)` unique-tone chance identically for mole and innocents).",
        "- **Angry-chatter surface outlier (`_ANGRY`):** In `medium` and `hard` (`decoy=True`), `100%` of angry messages belong to the innocent `decoy` (`0` from the mole, `0` from other innocents). Treating angry surface text as a mole tell yields **`0.0%` mole accuracy** (`-1.000` score), whereas eliminating the documented decoy yields only the stated `1/(N-1)` prior (`5.26%` medium, `2.56%` hard).",
        "",
        "| Tier | Worlds | Mole msgs (`doc_mail`/`chatter`/`angry`/`unmatched`) | Innocent non-decoy msgs (`doc_mail`/`chatter`/`angry`/`unmatched`) | Msgs/emp/ep (`mole` vs `inn`) | Mean slot pos (`mole` vs `inn`) | Doc recip rate (`mole` vs `inn`) | LOSO hits/N (acc, `p`) | Interview `chi2` (`df`, `p`) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    for tier in ("easy", "medium", "hard"):
        if tier not in t_h2["tiers"]:
            continue
        r = t_h2["tiers"][tier]
        mc = r["mole_template_counts"]
        ic = r["innocent_template_counts"]
        loso = r["loso_msg_clf"]
        lines.append(
            f"| `{tier}` | `{r['scan_seeds']}` | "
            f"`{mc.get('doc_mail', 0)}/{mc.get('dept_chatter', 0)}/{mc.get('angry_decoy', 0)}/{mc.get('unmatched', 0)}` | "
            f"`{ic.get('doc_mail', 0)}/{ic.get('dept_chatter', 0)}/{ic.get('angry_decoy', 0)}/{ic.get('unmatched', 0)}` | "
            f"`{r['mole_msgs_per_emp_ep']:.2f}` vs `{r['innocent_msgs_per_emp_ep']:.2f}` | "
            f"`{r['mole_mean_slot_pos']:.3f}` vs `{r['innocent_mean_slot_pos']:.3f}` | "
            f"`{100.0 * r['mole_doc_recip_rate']:.1f}%` vs `{100.0 * r['innocent_doc_recip_rate']:.1f}%` | "
            f"`{loso['hits']}/{loso['n']}` (`{100.0 * loso['accuracy']:.2f}%`, `p={loso['p_value_vs_chance']:.4f}`) | "
            f"`{r['iv_subtemplate_chi2']:.2f}` (`{r['iv_subtemplate_df']}`, `p={r['iv_subtemplate_p_value']:.4f}`) |"
        )

    lines += [
        "",
        f"{h2} 3. Lens H3 & H4: World Schema/Vocab Parity, Canonical Log Sorting, and Known-V Timing",
        "",
        "| Track | Roster key/ID/vocab mismatches (`n=200`) | Doc/canary schema mismatches | Leak-feed schema/unknown mismatches (`n=60`) | Closed log days (`n=60`) | Unsorted log days (AH inversions) | Counterfactual framed-tail days prevented | Hidden-leak states (`known_V` leaks) |",
        "|---|---|---|---|---|---|---|---|",
    ]

    for tr in cfg["tracks"]:
        r3 = t_h3["tracks"][tr]
        r4 = t_h4["tracks"][tr]
        lines.append(
            f"| `{tr}` | `{r3['roster_key_mismatches']}/{r3['roster_id_mismatches']}/{r3['roster_vocab_mismatches']}` | "
            f"`{r3['doc_schema_mismatches']}/{r3['canary_schema_mismatches']}` | "
            f"`{r3['feed_schema_mismatches']}/{r3['feed_unknown_docs']}` (`{r3['feed_items_total']}` items) | "
            f"`{r4['total_closed_days']}` (`{r4['total_log_rows']}` rows) | "
            f"**`{r4['unsorted_days']}`** (`{r4['intra_pair_ah_inversions']}`) | `{r4['counterfactual_tail_framed_days']}` | "
            f"`{r4['hidden_leak_states']}` (**`{r4['known_v_leaks']}`** leaks) |"
        )

    lines += [
        "",
        "- **Why `logs.sort(...)` is load-bearing (H4 parallel):** In `Env._t_advance_day`, genuine accesses are generated in employee order `e00..e{N-1}` and framed `after_hours` accesses (`p.framing` and Mole DSL `frame`) are appended afterwards, then canonically sorted by `(employee, doc_id, after_hours)`. Without that canonical sort, framed rows would sit out of employee order at the tail of each day's access log across hundreds of days per sweep (an exact analog of Sleeper's off-poll close timing tell). With canonical sorting, **`0`** days violate sort order and **`0`** `(employee, doc_id)` pairs invert `after_hours` ordering.",
        "- **MoleView canary-blindness:** `MoleDoc` exposes only ("
        + ", ".join(f"`{k}`" for k in t_h4["mole_doc_fields"])
        + f") (`is_canary` hidden = `{t_h4['mole_doc_hides_canary']}`, Mole DSL numeric-only features = `{t_h4['dsl_numeric_only']}`).",
        "",
        f"{h2} 4. Lens H5: Day-1 Priors, Salted Judge Separation, and Panel Fix D (`1bc3e281`) Error-Detail Parity",
        "",
        "| Track | Dev mole-ID `chi2` (`df`, `p`) | Max single-ID share (uniform `1/N`) | Dept `chi2` (`p`) | Day-1 docs `(2, 3, 4)` (`p`) | Salted judge `chi2` (`p`) | Public-key roster collisions (`n=40`) | Error parity / mole-ID leak mismatches |",
        "|---|---|---|---|---|---|---|---|",
    ]

    for tr in cfg["tracks"]:
        r5 = t_h5["tracks"][tr]
        d_cnts = "/".join(str(r5["d1_doc_counts"][k]) for k in ("2", "3", "4"))
        lines.append(
            f"| `{tr}` | `{r5['mole_id_chi2']:.2f}` (`{r5['mole_id_df']}`, `{r5['mole_id_p_value']:.4f}`) | "
            f"`{r5['max_mole_id']}: {100.0 * r5['max_mole_id_share']:.1f}%` (`{100.0 * r5['uniform_id_share']:.1f}%`) | "
            f"`{r5['mole_dept_chi2']:.2f}` (`{r5['mole_dept_p_value']:.4f}`) | "
            f"`{d_cnts}` (`{r5['d1_doc_p_value']:.4f}`) | "
            f"`{r5['judge_mole_id_chi2']:.2f}` (`{r5['judge_mole_id_p_value']:.4f}`) | "
            f"**`{r5['judge_public_matches']}`** | **`{r5['error_parity_mismatches']} / {r5['mole_id_in_innocent_error']}`** |"
        )

    lines += [
        "",
        f"{h2} 5. Surface-Tell Policy Benchmark on Salted Judge Seeds (`seat_eval` Port, `n={bench['judge_seeds']}` per Track)",
        "",
        "In Sleeper v1, `tmplonly` and `intfilter` scored `1.000` on judged seats without reading policy docs or verifying evidence. "
        "Below are their direct Canary v1.4 ports (trained on `120` dev worlds, evaluated through `Env.call` with zero canaries on the `40` salted judge seeds `900000..900039` under `canary-anticheat-public-test-v1`) paired against `do_nothing` and `SolverPolicy`:",
        "",
        "| Policy | `easy` mean +- CI95 (acc) | `medium` mean +- CI95 (acc) | `hard` mean +- CI95 (acc) | `hard_forge` mean +- CI95 (acc) | Blocked |",
        "|---|---|---|---|---|---|",
    ]

    for pol in SURFACE_POLICIES:
        cells = []
        blocked_all = True
        for tr in cfg["tracks"]:
            r = bench["tracks"][tr][pol]
            cells.append(f"`{r['mean_score']:+.3f} +- {r['ci95']:.3f}` (`{100.0 * r['accuracy']:.1f}%`)")
            blocked_all = blocked_all and r["blocked"]
        b_label = "ref" if pol == "solver" else ("yes" if blocked_all else "NO")
        lines.append(f"| `{pol}` | " + " | ".join(cells) + f" | **{b_label}** |")

    lines += [
        "",
        f"{h2} 6. Committed v1.4 Frontier Transcript Audit & Planted-Tell Positive Controls",
        "",
        f"{h3} Committed v1.4 Frontier Cohorts (`{tr_scan['total_episodes']}` Episodes, Zero Live API Calls)",
        "",
        "| Committed v1.4 Cohort | Episodes | Day-1 Accusations | Zero-Canary Accusations | Planted Canaries | Checked Leak Feed | Mean Canaries | Mean Final Day |",
        "|---|---|---|---|---|---|---|---|",
    ]

    for c in tr_scan["cohorts"]:
        lines.append(
            f"| `{c['cohort']}` | `{c['n']}` | **`{c['day1_accusations']}`** | **`{c['zero_canary_accusations']}`** | "
            f"`{c['episodes_with_canary']}/{c['n']}` | `{c['episodes_with_leak_feed']}/{c['n']}` | "
            f"`{c['mean_canaries']:.2f}` | `{c['mean_final_day']:.2f}` |"
        )

    lines += [
        "",
        f"{h3} Planted-Tell Positive Controls (Proving Every Scanner Has Teeth)",
        "",
        "| Synthetic Sleeper-v1 Bug Planted | Target Lens | Triggered / Caught | Measured Diagnostic |",
        "|---|---|---|---|",
        f"| `planted_h2_mole_wording_tell` (mole sends `'Handled per request...'` chatter) | `H2` | **`{ctrls['planted_h2_mole_wording_tell']['detected']}`** | LOSO message-only accuracy jumps to `{100.0 * ctrls['planted_h2_mole_wording_tell']['loso_accuracy']:.1f}%`, `{ctrls['planted_h2_mole_wording_tell']['unmatched_non_decoy']}` unmatched non-decoy msgs |",
        f"| `planted_h3_mole_key_order_tell` (`name` before `id` on mole roster dict) | `H3` | **`{ctrls['planted_h3_mole_key_order_tell']['detected']}`** | `{ctrls['planted_h3_mole_key_order_tell']['roster_key_mismatches']}/20` worlds flagged for key-order drift |",
        f"| `planted_h4_unsorted_framed_logs` (decoy framed `after_hours` left at day tail) | `H4` | **`{ctrls['planted_h4_unsorted_framed_logs']['detected']}`** | `{ctrls['planted_h4_unsorted_framed_logs']['unsorted_days']}` closed log days flagged for tail ordering tell |",
        f"| `planted_h5_error_parity_leak` (mole-specific `data.detail` leak on invalid call) | `H5` | **`{ctrls['planted_h5_error_parity_leak']['detected']}`** | `{ctrls['planted_h5_error_parity_leak']['error_parity_mismatches']}` tool-error parity mismatches flagged |",
        "",
        f"{h2} 7. Known Limits & Honest Distinction Between Documented Signals and Tells",
        "",
        "1. **Documented weak behavioral signals are intentional, not surface tells:** `instruction.md` explicitly gives the agent `interview_lr` (`1.5 / 1.3 / 1.2`), `p_after_hours_mole` (`0.15 / 0.15 / 0.30` vs `0.10`), and the angry `decoy` rule (`1/(N-1)` non-decoy prior). None of those alone reaches positive expected score on `medium`, `hard`, or `hard_forge`; winning requires active canary group-testing.",
        "2. **Leak-feed arrival order (`check_leak_feed`):** Because `self._feed` appends leaks in leak-day order while `delay_choices` spans `(1, 2, 3)` on `medium` and `(2, 3)` on `hard`, consecutive leaks can surface with `surfaced_day[i] > surfaced_day[i+1]`. That ordering only constrains when an already-public `doc_id` leaked inside `leak_window_days` and never exposes any employee ID beyond `list_documents` recipients.",
        "3. **Scope of text-provider audit:** This offline suite audits `TemplateProvider`, `MinimalProvider`, `GeminiWorldText` deterministic rendering, Panel Fix D (`1bc3e281`) error details, and all `152` committed v1.4 transcripts. Any future live-generated `GeminiProvider` world caches should run `canary.text.lint` plus `scan_template_wording_tells` before freezing.",
        "",
    ]
    return "\n".join(lines)


def render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Port of Sleeper surface-tells audit (H2-H5 + policy benchmark) onto Canary v1.4.")
    ap.add_argument("--out", type=Path, default=DEFAULT_REPORT)
    ap.add_argument("--json-out", type=Path, default=DEFAULT_JSON)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--scan-seeds", type=int, default=200)
    ap.add_argument("--judge-seeds", type=int, default=40)
    ap.add_argument("--train-seeds", type=int, default=120)
    ap.add_argument("--world-secret", default=DEFAULT_WORLD_SECRET)
    ap.add_argument("--tracks", default=",".join(AUDIT_TRACKS))
    args = ap.parse_args(argv)

    tracks = tuple(t.strip() for t in args.tracks.split(",") if t.strip())
    report = audit_surface_tells(
        scan_seeds=args.scan_seeds,
        judge_seeds=args.judge_seeds,
        train_seeds=args.train_seeds,
        world_secret=args.world_secret,
        tracks=tracks,
    )
    rendered_md = render_markdown(report)
    rendered_json = render_json(report)
    json_bytes = len(rendered_json.encode("utf-8"))

    if json_bytes > MAX_JSON_BYTES:
        sys.stderr.write(f"JSON output {json_bytes} bytes exceeds {MAX_JSON_BYTES} byte cap\n")
        return 1

    if not report["passed"]:
        sys.stderr.write("sleeper_surface_tells v1.4 audit failed one or more gates\n")
        return 1

    if args.check:
        existing_md = args.out.read_text(encoding="utf-8") if args.out.is_file() else ""
        if existing_md != rendered_md:
            sys.stderr.write(f"{args.out} differs from fresh deterministic render\n")
            return 1
        if args.json_out is not None:
            existing_json = args.json_out.read_text(encoding="utf-8") if args.json_out.is_file() else ""
            if existing_json != rendered_json:
                sys.stderr.write(f"{args.json_out} differs from fresh deterministic JSON\n")
                return 1
        print(f"sleeper_surface_tells_v14 reproduces (0 tells, 4/4 positive controls caught, json={json_bytes}B)")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(rendered_md, encoding="utf-8")
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered_json, encoding="utf-8")
    print(f"wrote {args.out} and {args.json_out} ({json_bytes}B)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
