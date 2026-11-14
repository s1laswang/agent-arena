from __future__ import annotations

from collections import Counter
from typing import Any, Callable
import random
import re

from canary.baselines import TOPICS, employee_ids
from canary.forge.fitness import ClassFactory, default_investigators
from canary.types import INVESTIGATIVE_TOOLS, Step

__all__ = [
    "GeminiCarbonProxy",
    "CodexHorizonProxy",
    "CodexProxy",
    "frontier_proxy_investigators",
]

LABELS = ("A", "B", "C", "D")
GEMINI_LABELS = ("v1", "v2", "v3", "v4")

ANGRY_QUERY_WORDS = frozenset({
    "angry", "unfair", "furious", "sick of", "quit", "ridiculous", "fed up", "hate", "frustrated",
})

ANGRY_PHRASES = (
    "flat' raise",
    "moving the goalposts",
    "burn out",
    "deserve me",
    "updating my cv",
    "skipped for promotion",
    "pretending this is fine",
    "nobody asks us",
    "pay here is a joke",
    "fed up",
    "frustrated",
    "angry",
    "unfair",
    "furious",
    "sick of",
    "ridiculous",
    "hate",
)

EVASIVE_PHRASES = (
    "couldn't tell you",
    "something missing",
    "don't really keep track",
    "skim most of it",
    "nothing worth mentioning",
    "depends what you count",
    "rather not",
    "keep a list",
    "busy. it's fine",
    "same as always",
    "some days are late",
    "another time",
    "whatever access i need",
    "haven't really looked",
    "more than i use",
    "evasive",
)


def _parse_params(instruction: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in (instruction or "").splitlines():
        line = raw.strip()
        if line.startswith("- ") and ": " in line:
            k, v = line[2:].split(": ", 1)
            if k.replace("_", "").isalnum():
                out.setdefault(k, v.strip())
    return out


def _fallback_employees(instruction: str) -> list[str]:
    m = re.search(r"\be00\b(?:\s*(?:to|\.\.)\s*)\be(\d{2,3})\b", instruction or "")
    if m:
        hi = int(m.group(1))
        width = len(m.group(1))
        return [f"e{i:0{width}d}" for i in range(hi + 1)]
    m = re.search(r"with (\d+) employees", instruction or "")
    if m:
        n = int(m.group(1))
        return [f"e{i:02d}" for i in range(n)]
    return []


class _FrontierProxyBase:
    name = "frontier_proxy"

    def __init__(self, seed: int = 0):
        self.seed = seed
        self.reset([], "")

    def reset(self, tools_spec: list[dict], instruction: str) -> None:
        self.tools_spec = list(tools_spec or [])
        self.instruction = instruction or ""
        p = _parse_params(self.instruction)
        low = self.instruction.lower()

        m_days = re.search(r"at most (\d+) days", self.instruction)
        self.n_days = int(p["n_days"]) if "n_days" in p else (int(m_days.group(1)) if m_days else 14)

        m_var = re.search(r"at most (\d+) (?:different|distinct) (?:variant|label)", self.instruction)
        self.max_variants = int(p["max_variants"]) if "max_variants" in p else (int(m_var.group(1)) if m_var else 3)
        self.max_variants = max(2, self.max_variants)

        self.canaries_per_day = int(float(p.get("canaries_per_day", 1)))
        self.actions_per_day = int(float(p.get("actions_per_day", 8)))
        self.tool_call_cap = int(float(p.get("tool_call_cap", 300)))
        self.wrong_accusation_score = float(p.get("wrong_accusation_score", -1.0))

        if "delay_choices" in p:
            delays = [int(x.strip()) for x in p["delay_choices"].split(",") if x.strip().isdigit()]
            self.min_delay = min(delays) if delays else 1
        else:
            m_del = re.search(r"after a delay of ([0-9]+)", self.instruction)
            self.min_delay = int(m_del.group(1)) if m_del else 1

        m_fp = re.search(r"variant label the mole received with probability ([0-9]*\.?[0-9]+)", self.instruction)
        if "fingerprint_accuracy" in p:
            self.fingerprint_accuracy = float(p["fingerprint_accuracy"])
        elif m_fp:
            self.fingerprint_accuracy = float(m_fp.group(1))
        else:
            self.fingerprint_accuracy = 1.0

        if "decoy" in p:
            self.has_decoy = p["decoy"].lower() in ("on", "true", "1", "yes")
        elif "there is no decoy" in low:
            self.has_decoy = False
        elif "there is a decoy" in low:
            self.has_decoy = True
        else:
            self.has_decoy = True

        self.rng = random.Random(f"{self.name}:{self.seed}")
        self.seen = 0
        self.emps: list[str] = []
        self.tie_order: dict[str, float] = {}
        self.list_emps_called = False
        self.day = 1
        self.V = 1.0
        self.actions_left = self.actions_per_day
        self.restricted: set[str] = set()
        self.docs: dict[str, dict[str, Any]] = {}
        self.planted_variants: dict[str, dict[str, list[str]]] = {}
        self.feed_seen: set[tuple[Any, ...]] = set()
        self.regular_leaks: list[set[str]] = []
        self.canary_leaks: list[tuple[set[str], dict[str, set[str]], str]] = []
        self.decoy: str | None = None
        self.angry_counts: Counter[str] = Counter()
        self.seen_msg_ids: set[str] = set()
        self.after_hours: Counter[str] = Counter()
        self.total_logs: Counter[str] = Counter()
        self.last_log_day = 0
        self.evasive_counts: Counter[str] = Counter()
        self.coop_counts: Counter[str] = Counter()
        self.interviewed_today: set[str] = set()
        self.interview_cursor = 0
        self.canaries_planted_total = 0
        self.canaries_today = 0
        self.canary_exposures: Counter[str] = Counter()
        self.day_tools_done: set[str] = set()
        self.planned_day = 0
        self.queue: list[tuple[str, dict[str, Any]]] = []

    def _init_employees(self, ids: list[str]) -> None:
        self.emps = list(ids)
        for e in self.emps:
            if e not in self.tie_order:
                self.tie_order[e] = self.rng.random()

    def _ingest(self, step: Step) -> None:
        res = step.result or {}
        ok = bool(res.get("ok"))
        err = str(res.get("error") or "")
        if step.tool == "list_employees":
            self.list_emps_called = True
        if not ok:
            if "daily action limit" in err:
                self.actions_left = 0
                self.queue = [(t, a) for t, a in self.queue if t not in INVESTIGATIVE_TOOLS and not t.startswith("__")]
            return

        if step.tool in INVESTIGATIVE_TOOLS:
            self.actions_left = max(0, self.actions_left - 1)

        data = res.get("data")
        if not isinstance(data, dict):
            data = {}

        if step.day and step.day > self.day and step.tool != "advance_day":
            self.day = int(step.day)
            self.canaries_today = 0
            self.interviewed_today.clear()
            self.day_tools_done.clear()

        if step.tool == "list_employees":
            ids = employee_ids(res) or _fallback_employees(self.instruction)
            if ids:
                self._init_employees(ids)
        elif step.tool == "status":
            new_day = int(data.get("day", self.day))
            if new_day != self.day:
                self.day = new_day
                self.canaries_today = 0
                self.interviewed_today.clear()
                self.day_tools_done.clear()
            self.V = float(data.get("V", data.get("value", self.V)))
            if "actions_left_today" in data:
                self.actions_left = int(data["actions_left_today"])
            if "restricted" in data:
                self.restricted = set(data.get("restricted") or [])
        elif step.tool == "advance_day":
            self.day = int(data.get("day", self.day + 1))
            if "V" in data:
                self.V = float(data["V"])
            self.actions_left = self.actions_per_day
            self.canaries_today = 0
            self.interviewed_today.clear()
            self.day_tools_done.clear()
        elif step.tool == "list_documents":
            for doc in data.get("documents") or []:
                if isinstance(doc, dict) and "doc_id" in doc:
                    self.docs[str(doc["doc_id"])] = doc
        elif step.tool == "plant_canary":
            cid = str(data.get("canary_id") or data.get("doc_id") or f"c{self.day}")
            asg = dict(step.args.get("assignment") or {})
            variants: dict[str, list[str]] = {}
            for emp, lab in sorted(asg.items()):
                variants.setdefault(str(lab), []).append(str(emp))
            self.planted_variants[cid] = variants
            self.docs.setdefault(cid, {
                "doc_id": cid,
                "day": step.day,
                "recipients": sorted(asg),
                "is_canary": True,
                "variants": variants,
            })
            self.canaries_planted_total += 1
            self.canaries_today += 1
            for emp in asg:
                self.canary_exposures[str(emp)] += 1
        elif step.tool == "check_leak_feed":
            for it in data.get("items") or []:
                if not isinstance(it, dict):
                    continue
                did = str(it.get("doc_id") or "")
                var = it.get("variant")
                key = (did, it.get("surfaced_day"), var)
                if key in self.feed_seen:
                    continue
                self.feed_seen.add(key)
                doc = self.docs.get(did) or {}
                vmap = doc.get("variants") or self.planted_variants.get(did)
                if var and isinstance(vmap, dict) and vmap:
                    groups = {str(lab): {str(x) for x in ms} for lab, ms in vmap.items()}
                    recips = set().union(*groups.values()) if groups else {str(x) for x in doc.get("recipients") or []}
                    self.canary_leaks.append((recips, groups, str(var)))
                elif doc.get("recipients") and not doc.get("is_canary"):
                    self.regular_leaks.append({str(x) for x in doc["recipients"]})
        elif step.tool == "search_messages":
            q = str(step.args.get("query") or "").strip().lower()
            pure_angry = q in ANGRY_QUERY_WORDS
            for m in data.get("messages") or []:
                if not isinstance(m, dict):
                    continue
                snd = m.get("sender")
                if not isinstance(snd, str):
                    continue
                mid = m.get("id")
                txt = f"{m.get('subject', '')} {m.get('snippet', '')} {m.get('body', '')}".lower()
                if pure_angry or any(p in txt for p in ANGRY_PHRASES):
                    if mid is None or str(mid) not in self.seen_msg_ids:
                        if mid is not None:
                            self.seen_msg_ids.add(str(mid))
                        self.angry_counts[snd] += 1
            if self.has_decoy and self.angry_counts:
                ranked = sorted(self.angry_counts.items(), key=lambda kv: (-kv[1], kv[0]))
                self.decoy = ranked[0][0]
        elif step.tool == "read_access_logs":
            d_to = int(step.args.get("day_to", self.last_log_day))
            self.last_log_day = max(self.last_log_day, d_to)
            for entry in data.get("logs") or []:
                if not isinstance(entry, dict):
                    continue
                emp = entry.get("employee")
                if isinstance(emp, str):
                    self.total_logs[emp] += 1
                    if entry.get("after_hours"):
                        self.after_hours[emp] += 1
        elif step.tool == "interview":
            emp = step.args.get("employee")
            ans = f"{data.get('signal', '')} {data.get('answer', '')}".lower()
            if isinstance(emp, str):
                self.interviewed_today.add(emp)
                if any(p in ans for p in EVASIVE_PHRASES):
                    self.evasive_counts[emp] += 1
                else:
                    self.coop_counts[emp] += 1

        if step.tool != "advance_day":
            self.day_tools_done.add(step.tool)

    def _suspect_pool(self) -> set[str]:
        pool = set(self.emps)
        if self.has_decoy and self.decoy in pool and len(pool) > 1:
            pool.discard(self.decoy)
        for recips in self.regular_leaks:
            if pool & recips:
                pool &= recips
        for crecips, _, _ in self.canary_leaks:
            if pool & crecips:
                pool &= crecips
        if not pool and self.emps:
            pool = {e for e in self.emps if e != self.decoy} or set(self.emps)
        return pool

    def _posterior(self, pool: set[str], q_canary: float) -> dict[str, float]:
        w = {e: (1.0 if e in pool else 0.0) for e in self.emps}
        for crecips, groups, shown in self.canary_leaks:
            k_var = max(2, len(groups))
            hit_group = groups.get(shown, set())
            other_w = (1.0 - q_canary) / (k_var - 1)
            for e in pool:
                if e in hit_group:
                    w[e] *= q_canary
                elif e in crecips:
                    w[e] *= other_w
        tot = sum(w.values())
        if tot <= 0.0:
            u = 1.0 / max(1, len(pool))
            return {e: (u if e in pool else 0.0) for e in self.emps}
        return {e: val / tot for e, val in w.items()}

    def act(self, history: list[Step]) -> tuple[str, dict[str, Any]]:
        if len(history) < self.seen:
            self.reset(self.tools_spec, self.instruction)
        for st in history[self.seen:]:
            self._ingest(st)
        self.seen = len(history)

        if not self.list_emps_called:
            return ("list_employees", {})
        if not self.emps:
            fb = _fallback_employees(self.instruction)
            if fb:
                self._init_employees(fb)
            else:
                if self.day >= self.n_days:
                    return ("accuse", {"employee": "e00"})
                return ("advance_day", {})

        if self.planned_day != self.day:
            self.planned_day = self.day
            raw_q = self._build_day_queue()
            self.queue = [
                (t, a)
                for t, a in raw_q
                if t.startswith("__") or t not in self.day_tools_done
            ]

        while self.queue:
            tool, args = self.queue.pop(0)
            if tool.startswith("__"):
                self._handle_marker(tool)
                continue
            if tool in INVESTIGATIVE_TOOLS and self.actions_left <= 0:
                continue
            return (tool, args)
        return ("advance_day", {})

    def _build_day_queue(self) -> list[tuple[str, dict[str, Any]]]:
        return [("advance_day", {})]

    def _handle_marker(self, marker: str) -> None:
        return None


class GeminiCarbonProxy(_FrontierProxyBase):
    name = "gemini_carbon_proxy"

    def __init__(self, seed: int = 0, flip_underweight: float = 0.05, accuse_p: float = 0.88):
        self.flip_underweight = flip_underweight
        self.accuse_p = accuse_p
        super().__init__(seed=seed)

    def _build_day_queue(self) -> list[tuple[str, dict[str, Any]]]:
        q: list[tuple[str, dict[str, Any]]] = [("status", {})]
        d_from = 1 if self.day == 1 else max(1, self.day - 2)
        q.append(("list_documents", {"day_from": d_from, "day_to": self.day}))
        if self.day == 1:
            q.append(("search_messages", {"query": "unfair"}))
        elif self.has_decoy and self.decoy is None and self.day <= 3:
            q.append(("search_messages", {"query": "e", "day_from": self.day - 1, "day_to": self.day - 1}))
        q.append(("check_leak_feed", {}))
        if self.day > 1 and self.last_log_day < self.day - 1:
            if self.day % 3 == 0 or self.day >= self.n_days - 2:
                q.append(("read_access_logs", {"day_from": self.last_log_day + 1, "day_to": self.day - 1}))
        q.append(("__decide__", {}))
        return q

    def _subjective_q(self) -> float:
        if self.fingerprint_accuracy >= 1.0:
            return 1.0
        flip = max(0.0, 1.0 - self.fingerprint_accuracy)
        return min(0.999, 1.0 - self.flip_underweight * flip)

    def _non_decoy_ah(self, emp: str) -> tuple[int, int]:
        if self.has_decoy and emp == self.decoy:
            return (-1, -1)
        return (self.after_hours[emp], self.total_logs[emp])

    def _handle_marker(self, marker: str) -> None:
        if marker != "__decide__":
            return
        pool = self._suspect_pool()
        subj_post = self._posterior(pool, self._subjective_q())
        live = sorted([e for e in pool if subj_post[e] > 1e-4]) or sorted(pool)

        best = max(live, key=lambda e: (round(subj_post[e], 6), self._non_decoy_ah(e), self.tie_order[e]))
        pb = subj_post[best]
        ev = pb * self.V + (1.0 - pb) * self.wrong_accusation_score

        if pb >= self.accuse_p and ev > 0.0:
            self.queue = [("accuse", {"employee": best})]
            return

        if self.day >= self.n_days:
            top_p = max(subj_post[e] for e in live)
            tied = [e for e in live if subj_post[e] >= top_p - 0.10]
            winner = max(tied, key=lambda e: (self._non_decoy_ah(e), round(subj_post[e], 6), self.tie_order[e]))
            if top_p >= 0.25 or len(live) <= 4:
                self.queue = [("accuse", {"employee": winner})]
            else:
                self.queue = [("advance_day", {})]
            return

        should_plant = self.day >= 2 and ((self.day + (self.seed % 2)) % 2 == 0 or self.day == 3)
        cand = [e for e in live if e not in self.restricted]
        nxt: list[tuple[str, dict[str, Any]]] = []
        if self.actions_left >= 3 and len(live) >= 2:
            iv_cands = [e for e in live if e not in self.interviewed_today]
            if iv_cands:
                e0 = iv_cands[(self.day + self.seed) % len(iv_cands)]
                topic = TOPICS[self.interview_cursor % len(TOPICS)]
                self.interview_cursor += 1
                nxt.append(("interview", {"employee": e0, "topic": topic}))

        if should_plant and self.canaries_per_day >= 1 and self.actions_left - len(nxt) >= 1 and len(cand) >= 2:
            cand.sort(key=lambda e: (
                -round(subj_post[e], 5),
                -self._non_decoy_ah(e)[0],
                self.canary_exposures[e] // 4,
                -self.tie_order[e],
            ))
            if len(cand) <= 6:
                subset = cand
            else:
                target_n = self.rng.randint(4, 6)
                subset = cand[:target_n]
            k_var = min(self.max_variants, 3, len(subset))
            labels = GEMINI_LABELS[:k_var]
            asg = {emp: labels[i % k_var] for i, emp in enumerate(subset)}
            nxt.append(("plant_canary", {"doc_title": f"Security review brief d{self.day}", "assignment": asg}))

        nxt.append(("advance_day", {}))
        self.queue = nxt


class CodexHorizonProxy(_FrontierProxyBase):
    name = "codex_horizon_proxy"

    def __init__(self, seed: int = 0, accuse_p: float = 0.88, spike_min_ah: int = 2, spike_gap: int = 1):
        self.accuse_p = accuse_p
        self.spike_min_ah = spike_min_ah
        self.spike_gap = spike_gap
        super().__init__(seed=seed)

    def _build_day_queue(self) -> list[tuple[str, dict[str, Any]]]:
        q: list[tuple[str, dict[str, Any]]] = [("status", {})]
        d_from = 1 if self.day == 1 else max(1, self.day - 2)
        q.append(("list_documents", {"day_from": d_from, "day_to": self.day}))
        if self.has_decoy:
            if self.day == 1:
                q.append(("search_messages", {"query": "angry"}))
            elif self.decoy is None and self.day <= 3:
                q.append(("search_messages", {"query": "e", "day_from": self.day - 1, "day_to": self.day - 1}))
        q.append(("check_leak_feed", {}))
        if self.day > 1 and self.last_log_day < self.day - 1:
            q.append(("read_access_logs", {"day_from": self.last_log_day + 1, "day_to": self.day - 1}))
        q.append(("__post_obs__", {}))
        return q

    def _behav_score(self, emp: str) -> float:
        if self.has_decoy and emp == self.decoy:
            return -10.0
        return (
            2.0 * self.after_hours[emp]
            + 0.2 * self.total_logs[emp]
            + 1.8 * self.evasive_counts[emp]
            - 0.25 * self.coop_counts[emp]
        )

    def _check_accuse(self, live: list[str], true_post: dict[str, float]) -> str | None:
        best = max(live, key=lambda e: (round(true_post[e], 6), self._behav_score(e), self.tie_order[e]))
        threshold = 1.0 / (1.0 + max(self.V, 1e-6))
        if len(live) == 1:
            return live[0]
        if true_post[best] >= self.accuse_p and true_post[best] > threshold:
            return best

        if len(live) <= 3 and self.day >= 3:
            by_ah = sorted(
                live,
                key=lambda e: (
                    0 if (self.has_decoy and e == self.decoy) else self.after_hours[e],
                    self._behav_score(e),
                    true_post[e],
                    self.tie_order[e],
                ),
                reverse=True,
            )
            top_e = by_ah[0]
            sec_e = by_ah[1]
            top_ah = 0 if (self.has_decoy and top_e == self.decoy) else self.after_hours[top_e]
            sec_ah = 0 if (self.has_decoy and sec_e == self.decoy) else self.after_hours[sec_e]
            if top_ah >= self.spike_min_ah and top_ah - sec_ah >= self.spike_gap:
                return top_e

        if self.day >= self.n_days:
            return max(
                live,
                key=lambda e: (round(true_post[e], 4) + 0.05 * self._behav_score(e), self._behav_score(e), self.tie_order[e]),
            )
        return None

    def _handle_marker(self, marker: str) -> None:
        pool = self._suspect_pool()
        true_post = self._posterior(pool, self.fingerprint_accuracy)
        live = sorted([e for e in pool if true_post[e] > 1e-4]) or sorted(pool)

        if marker == "__post_obs__":
            target = self._check_accuse(live, true_post)
            if target is not None:
                self.queue = [("accuse", {"employee": target})]
                return

            reserve = 1 if (self.canaries_per_day >= 1 and len(live) >= 2 and self.day >= 2) else 0
            iv_budget = min(2, max(0, self.actions_left - reserve))
            iv_cands = sorted(
                [e for e in live if e not in self.interviewed_today],
                key=lambda e: (
                    -round(true_post[e], 4),
                    -self._behav_score(e),
                    self.evasive_counts[e] + self.coop_counts[e],
                    -self.tie_order[e],
                ),
            )
            nxt: list[tuple[str, dict[str, Any]]] = []
            for e in iv_cands[:iv_budget]:
                topic = TOPICS[self.interview_cursor % len(TOPICS)]
                self.interview_cursor += 1
                nxt.append(("interview", {"employee": e, "topic": topic}))
            nxt.append(("__plant__", {}))
            self.queue = nxt
            return

        if marker == "__plant__":
            target = self._check_accuse(live, true_post)
            if target is not None:
                self.queue = [("accuse", {"employee": target})]
                return

            cand = [e for e in live if e not in self.restricted]
            late = self.day >= max(4, self.n_days // 2) or len(cand) <= 6
            if self.day >= 2 and self.canaries_per_day >= 1 and self.actions_left >= 1 and len(cand) >= 2:
                cand.sort(key=lambda e: (
                    -round(true_post[e], 4),
                    -self._behav_score(e),
                    self.canary_exposures[e],
                    -self.tie_order[e],
                ))
                k_var = min(self.max_variants, len(cand))
                per_var = 1 if late else (2 if len(cand) >= 2 * k_var else 1)
                chosen = cand[: per_var * k_var]
                asg = {emp: LABELS[i // per_var] for i, emp in enumerate(chosen)}
                self.queue = [
                    ("plant_canary", {"doc_title": f"Executive delta d{self.day}", "assignment": asg}),
                    ("advance_day", {}),
                ]
                return

            self.queue = [("advance_day", {})]


CodexProxy = CodexHorizonProxy


def frontier_proxy_investigators(include_defaults: bool = True) -> dict[str, Callable]:
    inv: dict[str, Callable] = default_investigators() if include_defaults else {}
    inv["gemini_carbon_proxy"] = ClassFactory("canary.forge.frontier_proxies", "GeminiCarbonProxy")
    inv["codex_horizon_proxy"] = ClassFactory("canary.forge.frontier_proxies", "CodexHorizonProxy")
    return inv
