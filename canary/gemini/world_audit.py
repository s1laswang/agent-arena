from __future__ import annotations

import argparse
from collections import Counter
import json
import math
import random
import re
import statistics
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from canary.agents.world_builder import (
    DEFAULT_CHATTER,
    TONES,
    TRUTH_KEYS,
    GeminiWorldText,
    assert_no_truth,
    build_world_text,
    public_view,
)
from canary.env import Env, TOPICS
from canary.eval import parse_seeds, run_episode
from canary.gemini import lab_client
from canary.llm import MissingKeyError, get_client
from canary.redteam import text_probe as tp
from canary.rules import TIERS, TRACKS, tier_params
from canary.solver.policy import SolverPolicy
from canary.text.facts import PublicDayFacts
from canary.text.lint import lint_messages, lint_text
from canary.text.template import SIGNALS, TemplateProvider
from canary.world import world_seed

FEATURE = "world_audit"
DEFAULT_MODEL = "gemini-4-carbon"
DEFAULT_PROBE_ALPHA = 0.01
ALLOWED_PLACEHOLDERS = frozenset({"sender", "dept", "doc_title", "colleague", "when"})
MD_H1 = "\x23"
MD_H2 = "\x23\x23"


def normalize_seeds(seeds: Sequence[int] | Iterable[int] | str | int) -> list[int]:
    if isinstance(seeds, str):
        out = parse_seeds(seeds)
    elif isinstance(seeds, int) and not isinstance(seeds, bool):
        out = [int(seeds)]
    else:
        out = [int(s) for s in seeds]
    if not out:
        raise ValueError("seeds must not be empty")
    return out


def _all_keys(obj: Any) -> Iterable[str]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _all_keys(v)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            yield from _all_keys(item)


def _walk_strings(obj: Any) -> Iterable[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _walk_strings(v)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            yield from _walk_strings(item)


def _templates_valid(templates: Any) -> bool:
    if not isinstance(templates, list):
        return False
    for tpl in templates:
        if not isinstance(tpl, str) or not tpl.strip():
            return False
        try:
            fields = {m.group(1) for m in re.finditer(r"\{(\w*)\}", tpl)}
            tpl.format(sender="A", dept="Eng", doc_title="Doc", colleague="B", when="Monday")
        except Exception:
            return False
        if not (fields <= ALLOWED_PLACEHOLDERS):
            return False
    return True


class PrerenderedDaysProvider:
    def __init__(self, payload: dict[str, Any], name: str = "prerendered-world"):
        self.name = name
        self.days = {str(k): list(v) for k, v in (payload.get("days") or {}).items() if isinstance(v, list)}
        self.interviews = {str(k): str(v) for k, v in (payload.get("interviews") or {}).items()}
        self._fallback = TemplateProvider()

    def day_messages(self, facts: PublicDayFacts) -> list[dict[str, Any]]:
        key = str(facts.day)
        if key in self.days:
            return [dict(m, recipients=list(m.get("recipients") or [])) for m in self.days[key]]
        return self._fallback.day_messages(facts)

    def interview_answer(self, facts: PublicDayFacts, employee: str, topic: str, signal: str) -> str:
        for key in (
            f"{employee}|{topic}|{signal}|{facts.day}",
            f"{employee}|{topic}|{signal}",
            f"{employee}|{signal}",
            employee,
        ):
            if key in self.interviews:
                return self.interviews[key]
        return self._fallback.interview_answer(facts, employee, topic, signal)


class SampleMessagesProvider:
    def __init__(self, payload: dict[str, Any], name: str = "sample-messages"):
        self.name = name
        raw_msgs = payload.get("messages") if isinstance(payload.get("messages"), list) else []
        by_day: dict[int, list[dict[str, Any]]] = {}
        default_day = int(payload.get("day", 1) or 1)
        for idx, m in enumerate(raw_msgs):
            if not isinstance(m, dict):
                continue
            d = int(m.get("day", default_day) or default_day)
            entry = {
                "id": str(m.get("id") or f"sm{d}-{idx}"),
                "day": d,
                "channel": str(m.get("channel") or "email"),
                "sender": str(m.get("sender") or ""),
                "recipients": [str(r) for r in (m.get("recipients") or [])],
                "subject": str(m.get("subject") or ""),
                "body": str(m.get("body") or ""),
            }
            by_day.setdefault(d, []).append(entry)
        self._by_day = by_day
        self._fallback = TemplateProvider()

    def day_messages(self, facts: PublicDayFacts) -> list[dict[str, Any]]:
        if facts.day in self._by_day:
            return [dict(m, recipients=list(m["recipients"])) for m in self._by_day[facts.day]]
        return self._fallback.day_messages(facts)

    def interview_answer(self, facts: PublicDayFacts, employee: str, topic: str, signal: str) -> str:
        return self._fallback.interview_answer(facts, employee, topic, signal)


class SafeWorldTextProvider:
    def __init__(self, world_text: dict[str, Any], name: str = "gemini-world-safe"):
        safe_copy = dict(world_text)
        raw_tpls = world_text.get("chatter_templates")
        if isinstance(raw_tpls, list):
            good = [t for t in raw_tpls if _templates_valid([t])]
            safe_copy["chatter_templates"] = good or list(DEFAULT_CHATTER)
        else:
            safe_copy["chatter_templates"] = list(DEFAULT_CHATTER)
        self.name = name
        self.wt = world_text
        self._inner = GeminiWorldText(safe_copy, name=name)

    def day_messages(self, facts: PublicDayFacts) -> list[dict[str, Any]]:
        return self._inner.day_messages(facts)

    def interview_answer(self, facts: PublicDayFacts, employee: str, topic: str, signal: str) -> str:
        return self._inner.interview_answer(facts, employee, topic, signal)


def provider_from_payload(payload: dict[str, Any], name: str = "gemini-world") -> Any:
    if isinstance(payload.get("days"), dict):
        prov_name = str(payload.get("provider") or name)
        return PrerenderedDaysProvider(payload, name=prov_name)
    if (
        isinstance(payload.get("messages"), list)
        and "personas" not in payload
        and "chatter_templates" not in payload
    ):
        prov_name = str(payload.get("source") or name)
        return SampleMessagesProvider(payload, name=prov_name)
    raw_tpls = payload.get("chatter_templates")
    if raw_tpls is None or _templates_valid(raw_tpls):
        return GeminiWorldText(payload, name=name)
    return SafeWorldTextProvider(payload, name=name)


def public_world_facts(tier: str, seed: int) -> dict[str, Any]:
    env = Env(tier, seed)
    emps = env.call("list_employees", {}).data["employees"]
    docs = env.call("list_documents", {"day_from": 1, "day_to": 1}).data["documents"]
    company = env._facts(1).company
    pub = public_view({
        "company": company,
        "tier": tier,
        "employees": emps,
        "docs": docs,
    })
    assert_no_truth(pub, {})
    return pub


def _resolve_llm_client(
    model: str = "stub",
    client: Any = None,
    *,
    require_live: bool = False,
    run_id: str = "",
) -> Any:
    if client is not None:
        return client
    if not model or model == "stub" or model.startswith("stub:"):
        return get_client(model or "stub")
    spec = model if ":" in model else f"gemini:{model}"
    try:
        return lab_client(spec, feature=FEATURE, run_id=run_id)
    except MissingKeyError:
        if require_live:
            raise
        return get_client("stub")


def _ensure_shared_tones(wt: dict[str, Any], seed: int) -> dict[str, Any]:
    personas = wt.get("personas")
    if not isinstance(personas, list) or len(personas) < 4:
        return wt
    counts = Counter(str(p.get("tone") or "") for p in personas if isinstance(p, dict))
    shared = [t for t, c in counts.items() if t and c >= 2]
    rng = random.Random(f"world_audit:tones:{seed}")
    for idx, p in enumerate(personas):
        if not isinstance(p, dict):
            continue
        cur = str(p.get("tone") or "")
        if not cur or counts[cur] < 2:
            if cur in counts:
                counts[cur] -= 1
            target = rng.choice(shared) if shared else TONES[(idx // 2) % len(TONES)]
            p["tone"] = target
            if cur and f"; {cur} on chat" in str(p.get("bio", "")):
                p["bio"] = str(p["bio"]).replace(f"; {cur} on chat", f"; {target} on chat")
            counts[target] = counts.get(target, 0) + 1
            if target not in shared and counts[target] >= 2:
                shared.append(target)
    return wt


def build_world_text_dir(
    worlds_dir: str | Path,
    tier: str = "medium",
    seeds: Sequence[int] | Iterable[int] | str | int = range(10),
    *,
    model: str = "stub",
    client: Any = None,
    require_live: bool = False,
) -> list[Path]:
    seed_list = normalize_seeds(seeds)
    out_root = Path(worlds_dir)
    tier_dir = out_root / tier
    tier_dir.mkdir(parents=True, exist_ok=True)
    llm = _resolve_llm_client(model=model, client=client, require_live=require_live)
    written: list[Path] = []
    for s in seed_list:
        pub = public_world_facts(tier, s)
        wt = _ensure_shared_tones(build_world_text(pub, llm, seed=s), s)
        dest = tier_dir / f"{s}.worldtext.json"
        dest.write_text(json.dumps(wt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(dest)
    return written


def resolve_world_file(
    worlds_dir: str | Path,
    tier: str,
    seed: int,
) -> tuple[Path | None, dict[str, Any] | None, str | None]:
    root = Path(worlds_dir)
    if not root.exists():
        return None, None, None
    ws = world_seed(tier, seed)
    candidates = (
        root / tier / f"{seed}.worldtext.json",
        root / tier / f"{ws}.worldtext.json",
        root / tier / f"{seed}.text.json",
        root / tier / f"{ws}.text.json",
        root / tier / f"{seed}.json",
        root / tier / f"{ws}.json",
        root / f"{seed}.worldtext.json",
        root / f"{ws}.worldtext.json",
        root / f"{seed}.text.json",
        root / f"{ws}.text.json",
        root / f"{seed}.json",
        root / f"{ws}.json",
    )
    for fp in candidates:
        if fp.is_file():
            try:
                parsed = json.loads(fp.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                return fp, None, f"invalid JSON in {fp}: {exc}"
            if not isinstance(parsed, dict):
                return fp, None, f"expected JSON object in {fp}"
            return fp, parsed, None

    samples_fp = root / "chatter_samples.json"
    if samples_fp.is_file():
        try:
            doc = json.loads(samples_fp.read_text(encoding="utf-8"))
            if isinstance(doc, dict) and isinstance(doc.get("samples"), list):
                for item in doc["samples"]:
                    if (
                        isinstance(item, dict)
                        and int(item.get("seed", -1)) == seed
                        and str(item.get("tier", tier)) == tier
                    ):
                        return samples_fp, item, None
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            return samples_fp, None, f"invalid JSON in {samples_fp}: {exc}"

    return None, None, None


def _audit_seed_non_leak(
    tier: str,
    seed: int,
    raw_payload: dict[str, Any] | None,
    provider: Any,
) -> dict[str, Any]:
    ref_env = Env(tier, seed)
    mole_id = ref_env._world.mole
    emps = ref_env.call("list_employees", {}).data["employees"]
    world_truth = {"mole": mole_id, "employees": emps}

    truth_violations: list[dict[str, Any]] = []
    lint_violations: list[dict[str, Any]] = []

    if isinstance(raw_payload, dict):
        bad_keys = sorted(TRUTH_KEYS & set(_all_keys(raw_payload)))
        if bad_keys:
            truth_violations.append({
                "seed": seed,
                "stage": "world_payload",
                "detail": f"truth keys in payload: {bad_keys}",
            })
        payload_body = {k: v for k, v in raw_payload.items() if k != "meta"}
        try:
            assert_no_truth(payload_body, world_truth)
        except AssertionError as exc:
            truth_violations.append({
                "seed": seed,
                "stage": "world_payload",
                "detail": str(exc),
            })
        for text_val in _walk_strings(payload_body):
            for prob in lint_text(text_val):
                lint_violations.append({
                    "seed": seed,
                    "stage": "world_payload",
                    "detail": prob,
                })
        raw_tpls = raw_payload.get("chatter_templates")
        if raw_tpls is not None and not _templates_valid(raw_tpls):
            lint_violations.append({
                "seed": seed,
                "stage": "world_payload",
                "detail": "invalid chatter_templates placeholder or empty template",
            })

    sim_env = Env(tier, seed, text_provider=provider)
    while not sim_env.done:
        res = sim_env.call("advance_day", {})
        if not res.ok:
            break
    rendered_msgs = [sim_env._messages[mid] for mid in sim_env._msg_order]
    for prob in lint_messages(rendered_msgs):
        lint_violations.append({
            "seed": seed,
            "stage": "day_messages",
            "detail": prob,
        })
    try:
        assert_no_truth(rendered_msgs, world_truth)
    except AssertionError as exc:
        truth_violations.append({
            "seed": seed,
            "stage": "day_messages",
            "detail": str(exc),
        })

    facts_d1 = ref_env._facts(1)
    n_interviews = 0
    for emp in emps:
        eid = str(emp["id"])
        for topic in TOPICS:
            for signal in SIGNALS:
                ans = provider.interview_answer(facts_d1, eid, topic, signal)
                n_interviews += 1
                for prob in lint_text(ans):
                    lint_violations.append({
                        "seed": seed,
                        "stage": "interview",
                        "employee": eid,
                        "topic": topic,
                        "signal": signal,
                        "detail": prob,
                    })
                try:
                    assert_no_truth(ans, world_truth)
                except AssertionError as exc:
                    truth_violations.append({
                        "seed": seed,
                        "stage": "interview",
                        "employee": eid,
                        "topic": topic,
                        "signal": signal,
                        "detail": str(exc),
                    })

    return {
        "truth_violations": truth_violations,
        "lint_violations": lint_violations,
        "n_messages": len(rendered_msgs),
        "n_interviews": n_interviews,
    }


def collect_probe_observations(tier: str, seed: int, provider: Any) -> dict[str, Any]:
    env = Env(tier=tier, seed=seed, text_provider=provider)
    p = tier_params(tier)
    r = env.call("list_employees", {})
    ids = [e["id"] for e in tp._rows(r.data, "employees")]
    days = p.n_days - 1
    slots = p.actions_per_day - 1 - tp.MSGS_READ_PER_DAY
    k = max(1, min(len(tp.TOPICS), (slots * days) // len(ids)))
    todo = [(e, t) for t in tp.TOPICS[:k] for e in ids]
    messages: dict[str, dict[str, Any]] = {}
    interviews: dict[str, list[str]] = {e: [] for e in ids}
    for d in range(1, days + 1):
        used = 0
        hits: list[dict[str, Any]] = []
        for q in ("e", "a", "the"):
            if d == 1:
                break
            sr = env.call("search_messages", {"query": q, "day_from": d - 1, "day_to": d - 1})
            used += 1
            if sr.ok:
                hits = tp._rows(sr.data, "messages")
                break
        for m in hits[:tp.MSGS_READ_PER_DAY]:
            mr = env.call("read_message", {"id": m["id"]})
            used += 1
            if mr.ok:
                messages[str(m["id"])] = {
                    "day": d - 1,
                    "sender": m.get("sender"),
                    "text": tp._text(mr.data),
                }
        for m in hits[tp.MSGS_READ_PER_DAY:]:
            messages.setdefault(
                str(m["id"]),
                {"day": d - 1, "sender": m.get("sender"), "text": m.get("snippet", "")},
            )
        while todo and used < p.actions_per_day:
            e, t = todo.pop(0)
            ir = env.call("interview", {"employee": e, "topic": t})
            used += 1
            if ir.ok:
                interviews[e].append(tp._text(ir.data))
        env.call("advance_day", {})
        if env.done:
            break
    return {
        "tier": tier,
        "seed": seed,
        "ids": ids,
        "k_interviews": k,
        "messages": messages,
        "interviews": interviews,
        "target": env._world.mole,
    }


def run_text_probe_audit(
    tier: str,
    seeds: Sequence[int],
    providers: Mapping[int, Any],
    *,
    backend: str = "stub",
    alpha: float = DEFAULT_PROBE_ALPHA,
) -> dict[str, Any]:
    base_tier = TRACKS.get(tier, tier)
    p = tier_params(tier)
    rows: list[dict[str, Any]] = []
    hits = 0
    k_interviews = 0
    for s in seeds:
        obs = collect_probe_observations(tier, s, providers[s])
        k_interviews = obs["k_interviews"]
        guess = tp.stub_guess(obs) if backend == "stub" else tp.llm_guess(backend, obs)
        ok = bool(guess == obs["target"])
        hits += int(ok)
        rows.append({
            "seed": int(s),
            "guess": guess,
            "correct": ok,
        })
    n = len(seeds)
    chance = 1.0 / p.n_employees
    bar = tp.fair_bar(base_tier, k_interviews) if n > 0 else chance
    lo, hi = tp.wilson(hits, n)
    pv_bar = tp.p_value_above(hits, n, bar)
    pv_chance = tp.p_value_above(hits, n, chance)
    leak = bool(pv_bar < alpha)
    if leak and n < 5 and backend == "stub":
        tpl = TemplateProvider()
        tpl_hits = 0
        for s in seeds:
            tpl_obs = collect_probe_observations(tier, s, tpl)
            tpl_hits += int(tp.stub_guess(tpl_obs) == tpl_obs["target"])
        leak = bool(hits > tpl_hits)
    return {
        "backend": backend,
        "n": n,
        "correct": hits,
        "accuracy": hits / max(1, n),
        "ci95": [round(lo, 6), round(hi, 6)],
        "chance": round(chance, 6),
        "interviews_per_employee": k_interviews,
        "fair_bar": round(bar, 6),
        "p_value_vs_bar": round(pv_bar, 6),
        "p_value_vs_chance": round(pv_chance, 6),
        "alpha": alpha,
        "text_leak": leak,
        "rows": rows,
    }


def _paired_ci95(values: Sequence[float]) -> list[float]:
    n = len(values)
    if n == 0:
        return [0.0, 0.0]
    mean_v = statistics.mean(values)
    if n == 1:
        return [round(mean_v, 6), round(mean_v, 6)]
    sd = statistics.stdev(values)
    half = 1.96 * sd / math.sqrt(n)
    return [round(mean_v - half, 6), round(mean_v + half, 6)]


def check_solver_parity(
    tier: str,
    seeds: Sequence[int],
    providers: Mapping[int, Any],
    *,
    max_catch_diff: float | None = None,
    max_score_diff: float | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    t_scores: list[float] = []
    w_scores: list[float] = []
    t_catches: list[int] = []
    w_catches: list[int] = []
    score_diffs: list[float] = []
    exact_matches = 0

    for s in seeds:
        ep_t = run_episode(Env(tier, s, text_provider=TemplateProvider()), SolverPolicy())
        ep_w = run_episode(Env(tier, s, text_provider=providers[s]), SolverPolicy())
        t_scores.append(float(ep_t.score))
        w_scores.append(float(ep_w.score))
        t_catches.append(int(bool(ep_t.correct)))
        w_catches.append(int(bool(ep_w.correct)))
        diff = float(ep_w.score) - float(ep_t.score)
        score_diffs.append(diff)
        exact = bool(
            ep_t.score == ep_w.score
            and bool(ep_t.correct) == bool(ep_w.correct)
            and ep_t.accused == ep_w.accused
        )
        exact_matches += int(exact)
        rows.append({
            "seed": int(s),
            "template_score": round(float(ep_t.score), 6),
            "world_score": round(float(ep_w.score), 6),
            "score_diff": round(diff, 6),
            "template_correct": bool(ep_t.correct),
            "world_correct": bool(ep_w.correct),
            "template_accused": ep_t.accused,
            "world_accused": ep_w.accused,
            "exact_match": exact,
        })

    n = len(seeds)
    t_catch_rate = sum(t_catches) / max(1, n)
    w_catch_rate = sum(w_catches) / max(1, n)
    catch_diff = w_catch_rate - t_catch_rate
    t_mean = statistics.mean(t_scores) if t_scores else 0.0
    w_mean = statistics.mean(w_scores) if w_scores else 0.0
    score_diff = w_mean - t_mean

    tol_catch = (
        float(max_catch_diff)
        if max_catch_diff is not None
        else (0.0 if n == 1 else max(0.15, 1.0 / max(1, n)))
    )
    tol_score = (
        float(max_score_diff)
        if max_score_diff is not None
        else (0.20 if n == 1 else max(0.15, 0.65 / max(1, n)))
    )
    parity_ok = bool(
        abs(catch_diff) <= tol_catch + 1e-9
        and abs(score_diff) <= tol_score + 1e-9
    )

    return {
        "ok": parity_ok,
        "n": n,
        "template_catch_rate": round(t_catch_rate, 6),
        "world_catch_rate": round(w_catch_rate, 6),
        "catch_rate_diff": round(catch_diff, 6),
        "max_catch_diff": round(tol_catch, 6),
        "template_mean_score": round(t_mean, 6),
        "world_mean_score": round(w_mean, 6),
        "mean_score_diff": round(score_diff, 6),
        "score_diff_ci95": _paired_ci95(score_diffs),
        "max_score_diff": round(tol_score, 6),
        "exact_match_rate": round(exact_matches / max(1, n), 6),
        "rows": rows,
    }


def audit_world_text_dir(
    worlds_dir: str | Path | None,
    tier: str = "medium",
    seeds: Sequence[int] | Iterable[int] | str | int = range(10),
    *,
    build_missing: bool = True,
    model: str = "stub",
    client: Any = None,
    require_live: bool = False,
    probe_backend: str = "stub",
    probe_alpha: float = DEFAULT_PROBE_ALPHA,
    max_catch_diff: float | None = None,
    max_score_diff: float | None = None,
) -> dict[str, Any]:
    if tier not in TIERS and tier not in TRACKS:
        raise ValueError(f"unknown tier {tier!r}")
    seed_list = normalize_seeds(seeds)
    worlds_path = Path(worlds_dir) if worlds_dir is not None else None

    providers: dict[int, Any] = {}
    raw_payloads: dict[int, dict[str, Any] | None] = {}
    source_paths: dict[int, str | None] = {}
    missing_files: list[int] = []
    truth_violations: list[dict[str, Any]] = []
    lint_violations: list[dict[str, Any]] = []
    llm_client: Any = None

    for s in seed_list:
        fp: Path | None = None
        payload: dict[str, Any] | None = None
        load_err: str | None = None
        if worlds_path is not None:
            fp, payload, load_err = resolve_world_file(worlds_path, tier, s)
        if load_err is not None:
            truth_violations.append({
                "seed": s,
                "stage": "world_payload",
                "detail": load_err,
            })
            providers[s] = TemplateProvider()
            raw_payloads[s] = None
            source_paths[s] = str(fp) if fp is not None else None
            continue
        if payload is None:
            if not build_missing:
                missing_files.append(s)
                providers[s] = TemplateProvider()
                raw_payloads[s] = None
                source_paths[s] = None
                continue
            if llm_client is None:
                llm_client = _resolve_llm_client(
                    model=model,
                    client=client,
                    require_live=require_live,
                )
            pub = public_world_facts(tier, s)
            payload = _ensure_shared_tones(build_world_text(pub, llm_client, seed=s), s)
            if worlds_path is not None:
                dest = worlds_path / tier / f"{s}.worldtext.json"
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                fp = dest
        providers[s] = provider_from_payload(payload, name=f"gemini-world:{tier}:{s}")
        raw_payloads[s] = payload
        source_paths[s] = str(fp) if fp is not None else None

    total_messages = 0
    total_interviews = 0
    seed_non_leak: dict[int, dict[str, Any]] = {}
    for s in seed_list:
        nl = _audit_seed_non_leak(tier, s, raw_payloads[s], providers[s])
        seed_non_leak[s] = nl
        truth_violations.extend(nl["truth_violations"])
        lint_violations.extend(nl["lint_violations"])
        total_messages += int(nl["n_messages"])
        total_interviews += int(nl["n_interviews"])

    probe_report = run_text_probe_audit(
        tier,
        seed_list,
        providers,
        backend=probe_backend,
        alpha=probe_alpha,
    )
    parity_report = check_solver_parity(
        tier,
        seed_list,
        providers,
        max_catch_diff=max_catch_diff,
        max_score_diff=max_score_diff,
    )

    probe_by_seed = {r["seed"]: r for r in probe_report["rows"]}
    parity_by_seed = {r["seed"]: r for r in parity_report["rows"]}
    per_seed: list[dict[str, Any]] = []
    for s in seed_list:
        nl = seed_non_leak[s]
        pr = probe_by_seed[s]
        pa = parity_by_seed[s]
        per_seed.append({
            "seed": s,
            "source_path": source_paths[s],
            "provider": getattr(providers[s], "name", type(providers[s]).__name__),
            "truth_ok": len(nl["truth_violations"]) == 0,
            "lint_ok": len(nl["lint_violations"]) == 0,
            "n_messages": nl["n_messages"],
            "n_interviews": nl["n_interviews"],
            "probe_guess": pr["guess"],
            "probe_correct": pr["correct"],
            "template_score": pa["template_score"],
            "world_score": pa["world_score"],
            "template_correct": pa["template_correct"],
            "world_correct": pa["world_correct"],
        })

    non_leak_ok = bool(
        len(truth_violations) == 0
        and len(lint_violations) == 0
        and len(missing_files) == 0
        and not probe_report["text_leak"]
    )
    overall_ok = bool(non_leak_ok and parity_report["ok"])

    return {
        "ok": overall_ok,
        "passed": overall_ok,
        "worlds_dir": str(worlds_path) if worlds_path is not None else None,
        "tier": tier,
        "seeds": seed_list,
        "n_seeds": len(seed_list),
        "non_leak": {
            "ok": non_leak_ok,
            "truth_violations": truth_violations,
            "lint_violations": lint_violations,
            "missing_files": missing_files,
            "n_truth_violations": len(truth_violations),
            "n_lint_violations": len(lint_violations),
            "n_messages_checked": total_messages,
            "n_interviews_checked": total_interviews,
            "text_probe": probe_report,
        },
        "solver_parity": parity_report,
        "per_seed": per_seed,
    }


def render_audit_markdown(report: dict[str, Any]) -> str:
    status = "PASS" if report["ok"] else "FAIL"
    nl = report["non_leak"]
    pr = nl["text_probe"]
    sp = report["solver_parity"]
    lines = [
        f"{MD_H1} World-Text Non-Leak and Solver Parity Audit",
        "",
        f"- Status: **{status}**",
        f"- Tier: `{report['tier']}`",
        f"- Seeds (`{report['n_seeds']}`): `{report['seeds']}`",
        f"- Worlds directory: `{report['worlds_dir'] or 'in-memory'}`",
        "",
        f"{MD_H2} Non-Leak Verification",
        "",
        f"- Non-leak status: `{'pass' if nl['ok'] else 'fail'}`",
        f"- Truth violations (`assert_no_truth`): `{nl['n_truth_violations']}`",
        f"- Lint violations (`lint_messages` / `lint_text`): `{nl['n_lint_violations']}`",
        f"- Messages checked: `{nl['n_messages_checked']}`, interviews checked: `{nl['n_interviews_checked']}`",
        f"- Text probe (`{pr['backend']}`): `{pr['correct']}/{pr['n']}` = `{pr['accuracy']:.3f}` "
        f"(chance `{pr['chance']:.3f}`, fair bar `{pr['fair_bar']:.3f}`, p=`{pr['p_value_vs_bar']:.4f}`, "
        f"leak=`{pr['text_leak']}`)",
        "",
        f"{MD_H2} Paired SolverPolicy Parity",
        "",
        f"- Solver parity status: `{'pass' if sp['ok'] else 'fail'}`",
        f"- Catch rate: TemplateProvider `{sp['template_catch_rate']:.3f}` vs GeminiWorldText `{sp['world_catch_rate']:.3f}` "
        f"(diff `{sp['catch_rate_diff']:+.3f}`, max `{sp['max_catch_diff']:.3f}`)",
        f"- Mean score: TemplateProvider `{sp['template_mean_score']:.3f}` vs GeminiWorldText `{sp['world_mean_score']:.3f}` "
        f"(diff `{sp['mean_score_diff']:+.3f}`, 95% CI `{sp['score_diff_ci95']}`, max `{sp['max_score_diff']:.3f}`)",
        f"- Exact episode match rate: `{sp['exact_match_rate']:.3f}`",
        "",
    ]
    return "\n".join(lines)


def write_audit_outputs(report: dict[str, Any], out_target: str | Path) -> tuple[Path, Path]:
    target = Path(out_target)
    if target.suffix == ".json":
        json_path = target
        md_path = target.with_suffix(".md")
    elif target.suffix == ".md":
        md_path = target
        json_path = target.with_suffix(".json")
    else:
        target.mkdir(parents=True, exist_ok=True)
        json_path = target / "audit_report.json"
        md_path = target / "audit_summary.md"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_audit_markdown(report), encoding="utf-8")
    return json_path, md_path


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m canary.gemini.world_audit")
    ap.add_argument("--worlds-dir", default=None)
    ap.add_argument("--tier", default="medium", choices=sorted([*TIERS, *TRACKS]))
    ap.add_argument("--seeds", default="0-9")
    ap.add_argument("--model", default="stub")
    ap.add_argument("--probe-backend", default="stub")
    ap.add_argument("--probe-alpha", type=float, default=DEFAULT_PROBE_ALPHA)
    ap.add_argument("--max-catch-diff", type=float, default=None)
    ap.add_argument("--max-score-diff", type=float, default=None)
    ap.add_argument("--no-build-missing", action="store_true")
    ap.add_argument("--require-live", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(list(argv) if argv is not None else None)

    report = audit_world_text_dir(
        args.worlds_dir,
        tier=args.tier,
        seeds=args.seeds,
        build_missing=not args.no_build_missing,
        model=args.model,
        require_live=args.require_live,
        probe_backend=args.probe_backend,
        probe_alpha=args.probe_alpha,
        max_catch_diff=args.max_catch_diff,
        max_score_diff=args.max_score_diff,
    )
    if args.out:
        write_audit_outputs(report, args.out)
    summary = {
        "ok": report["ok"],
        "tier": report["tier"],
        "n_seeds": report["n_seeds"],
        "truth_violations": report["non_leak"]["n_truth_violations"],
        "lint_violations": report["non_leak"]["n_lint_violations"],
        "probe_accuracy": report["non_leak"]["text_probe"]["accuracy"],
        "probe_chance": report["non_leak"]["text_probe"]["chance"],
        "probe_fair_bar": report["non_leak"]["text_probe"]["fair_bar"],
        "probe_p_value": report["non_leak"]["text_probe"]["p_value_vs_bar"],
        "text_leak": report["non_leak"]["text_probe"]["text_leak"],
        "template_catch_rate": report["solver_parity"]["template_catch_rate"],
        "world_catch_rate": report["solver_parity"]["world_catch_rate"],
        "catch_rate_diff": report["solver_parity"]["catch_rate_diff"],
        "template_mean_score": report["solver_parity"]["template_mean_score"],
        "world_mean_score": report["solver_parity"]["world_mean_score"],
        "mean_score_diff": report["solver_parity"]["mean_score_diff"],
        "solver_parity_ok": report["solver_parity"]["ok"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
