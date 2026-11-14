"""Text-leak probe (owner: HEAD-INTEGRITY / props-probe).

A text-only "investigator" that sees ONLY message texts and interview answers (no logs, no
canaries, no leak feed) and names the mole. If its accuracy is significantly above the fair
bar, the world text leaks the truth and examples are dumped for HEAD-ENV.

Fair bar: interviews legitimately carry a weak, documented signal (P(evasive|mole) =
p_evasive_innocent * interview_lr). The bar is the Bayes-optimal accuracy of "pick the
employee with the most evasive answers" given the number of interviews per employee we
could afford, NOT pure chance 1/N.

    python -m canary.redteam.text_probe --backend stub --tier medium --seeds 0-49
    python -m canary.redteam.text_probe --backend openai:gpt-4o-mini --tier medium --seeds 0-49
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

from canary.rules import TIERS

TOPICS = ["recent_documents", "contacts_outside", "workload", "access_needs"]
MAX_LLM_CALLS = 50
MSGS_READ_PER_DAY = 3

EVASIVE = set("""
not sure dont don't can't cannot rather prefer later busy why private personal no comment
remember recall maybe perhaps whatever unclear hmm um uh well actually honestly nothing
nobody none anyway sorry unsure vague depends
""".split())
NEGATIVE = set("""
angry unfair hate quit tired fed up ridiculous stupid useless terrible awful sick leaving
resign underpaid ignored frustrated annoyed worst never again blame
""".split())


# ------------------------------------------------------------------ collection
def _rows(data: Any, key: str) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in (key, "items", "rows", "results"):
            if isinstance(data.get(k), list):
                return data[k]
    return []


def _text(x: Any) -> str:
    if isinstance(x, str):
        return x
    if isinstance(x, dict):
        if isinstance(x.get("message"), dict):
            m = x["message"]
            return f"{m.get('subject', '')}: {m.get('body', '')}"
        for k in ("answer", "text", "body", "content"):
            if isinstance(x.get(k), str):
                return x[k]
    return json.dumps(x, default=str)


def collect(tier: str, seed: int) -> dict:
    """Play a text-only investigation through the public tools. Never accuses."""
    from canary.env import Env
    env = Env(tier=tier, seed=seed)
    p = TIERS[tier]
    r = env.call("list_employees", {})
    ids = [e["id"] for e in _rows(r.data, "employees")]
    days = p.n_days - 1  # stop before the horizon
    slots = p.actions_per_day - 1 - MSGS_READ_PER_DAY
    k = max(1, min(len(TOPICS), (slots * days) // len(ids)))
    todo = [(e, t) for t in TOPICS[:k] for e in ids]
    messages: dict[str, dict] = {}
    interviews: dict[str, list[str]] = {e: [] for e in ids}
    for d in range(1, days + 1):
        used = 0
        hits = []
        # a day's messages are rendered when it closes: read yesterday's
        for q in ("e", "a", "the"):
            if d == 1:
                break
            sr = env.call("search_messages", {"query": q, "day_from": d - 1, "day_to": d - 1})
            used += 1
            if sr.ok:
                hits = _rows(sr.data, "messages")
                break
        for m in hits[:MSGS_READ_PER_DAY]:
            mr = env.call("read_message", {"id": m["id"]})
            used += 1
            if mr.ok:
                messages[str(m["id"])] = {"day": d - 1, "sender": m.get("sender"),
                                          "text": _text(mr.data)}
        for m in hits[MSGS_READ_PER_DAY:]:
            messages.setdefault(str(m["id"]), {"day": d - 1, "sender": m.get("sender"),
                                               "text": m.get("snippet", "")})
        while todo and used < p.actions_per_day:
            e, t = todo.pop(0)
            ir = env.call("interview", {"employee": e, "topic": t})
            used += 1
            if ir.ok:
                interviews[e].append(_text(ir.data))
        env.call("advance_day", {})
        if env.done:
            break
    mole = env._world.mole  # server-side truth: used for scoring the probe only
    return {"tier": tier, "seed": seed, "ids": ids, "k_interviews": k, "messages": messages,
            "interviews": interviews, "mole": mole}


# ------------------------------------------------------------------ backends
def _words(s: str) -> list[str]:
    return re.findall(r"[a-z']+", s.lower())


def stub_guess(obs: dict) -> str:
    score: Counter = Counter()
    for e, answers in obs["interviews"].items():
        for a in answers:
            w = _words(a)
            score[e] += 2 * sum(x in EVASIVE for x in w) / max(1, len(w)) * 10
    for m in obs["messages"].values():
        s = m.get("sender")
        if s in obs["interviews"]:
            w = _words(m["text"])
            score[s] += sum(x in NEGATIVE or x in EVASIVE for x in w) / max(1, len(w))
    return max(obs["ids"], key=lambda e: (score[e], -obs["ids"].index(e)))


PROMPT = """You are given internal company messages and HR interview answers. Exactly one
employee secretly leaks documents. From the TEXT ALONE, name the single most likely employee.
Reply with JSON {{"employee": "<id>"}} only.

Employees: {ids}

Messages:
{msgs}

Interviews:
{ivs}
"""


def _prompt(obs: dict) -> str:
    msgs = "\n".join(f"[day {m['day']}] {m.get('sender')}: {m['text'][:400]}"
                     for m in list(obs["messages"].values())[:120])
    ivs = "\n".join(f"{e}: " + " | ".join(a[:300] for a in ans)
                    for e, ans in obs["interviews"].items())
    return PROMPT.format(ids=", ".join(obs["ids"]), msgs=msgs, ivs=ivs)


def _load_dotenv():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass


def llm_guess(backend: str, obs: dict) -> str:
    provider, model = backend.split(":", 1)
    prompt = _prompt(obs)
    try:  # prefer the shared client when AGENTS has landed it
        from canary.llm import get_client
        text = get_client(backend).complete(prompt)  # type: ignore[attr-defined]
    except Exception:
        _load_dotenv()
        if provider == "openai":
            from openai import OpenAI
            out = OpenAI().chat.completions.create(
                model=model, messages=[{"role": "user", "content": prompt}],
                temperature=0, max_tokens=30)
            text = out.choices[0].message.content or ""
        elif provider == "gemini":
            from google import genai
            text = genai.Client().models.generate_content(model=model, contents=prompt).text or ""
        else:
            raise ValueError(backend)
    m = re.search(r"e\d{2,3}", text)
    return m.group(0) if m else ""


# ------------------------------------------------------------------ statistics
def binom_pmf(n: int, k: int, p: float) -> float:
    return math.comb(n, k) * p ** k * (1 - p) ** (n - k)


def fair_bar(tier: str, k: int) -> float:
    """P(mole has strictly the most evasive answers, ties broken uniformly) with k
    interviews each: the best accuracy the documented interview signal permits."""
    p = TIERS[tier]
    n = p.n_employees
    q0 = p.p_evasive_innocent
    q1 = min(1.0, q0 * p.interview_lr)
    acc = 0.0
    cdf0 = [sum(binom_pmf(k, j, q0) for j in range(c + 1)) for c in range(k + 1)]
    for c in range(k + 1):
        pm = binom_pmf(k, c, q1)
        below = cdf0[c - 1] if c > 0 else 0.0
        eq = binom_pmf(k, c, q0)
        # others: each < c (prob below) or == c (prob eq); tie among j others -> 1/(j+1)
        s = sum(math.comb(n - 1, j) * eq ** j * below ** (n - 1 - j) / (j + 1) for j in range(n))
        acc += pm * s
    return acc


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    ph = k / n
    d = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / d
    h = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def p_value_above(k: int, n: int, p: float) -> float:
    return sum(binom_pmf(n, j, p) for j in range(k, n + 1))


def parse_seeds(s: str) -> list[int]:
    out: list[int] = []
    for part in s.split(","):
        if "-" in part:
            a, b = part.split("-")
            out += range(int(a), int(b) + 1)
        else:
            out.append(int(part))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="stub")
    ap.add_argument("--tier", default="medium", choices=sorted(TIERS))
    ap.add_argument("--seeds", default="0-49")
    a = ap.parse_args(argv)
    seeds = parse_seeds(a.seeds)
    if a.backend != "stub" and len(seeds) > MAX_LLM_CALLS:
        print(f"capping to {MAX_LLM_CALLS} LLM calls")
        seeds = seeds[:MAX_LLM_CALLS]
    try:
        obs_all = [collect(a.tier, s) for s in seeds]
    except NotImplementedError:
        print("canary.env.Env not implemented yet; nothing to probe")
        return 2
    hits, rows = 0, []
    for obs in obs_all:
        g = stub_guess(obs) if a.backend == "stub" else llm_guess(a.backend, obs)
        ok = g == obs["mole"]
        hits += ok
        rows.append({"seed": obs["seed"], "guess": g, "mole": obs["mole"], "correct": ok})
    n = len(obs_all)
    k = obs_all[0]["k_interviews"] if obs_all else 0
    chance = 1 / TIERS[a.tier].n_employees
    bar = fair_bar(a.tier, k)
    lo, hi = wilson(hits, n)
    pv = p_value_above(hits, n, bar)
    leak = pv < 0.01
    summary = {"backend": a.backend, "tier": a.tier, "n": n, "correct": hits,
               "accuracy": hits / max(1, n), "ci95": [lo, hi], "chance": chance,
               "interviews_per_employee": k, "fair_bar": bar, "p_value_vs_bar": pv,
               "text_leak": leak}
    print(json.dumps(summary, indent=2))
    if leak:
        out = Path("data/runs") / f"redteam-textprobe-{time.strftime('%Y%m%d-%H%M%S')}"
        out.mkdir(parents=True, exist_ok=True)
        (out / "summary.json").write_text(json.dumps(summary, indent=2))
        with (out / "examples.jsonl").open("w") as f:
            for obs, row in zip(obs_all, rows):
                if row["correct"]:
                    f.write(json.dumps({**row, "messages": obs["messages"],
                                        "interviews": obs["interviews"]}) + "\n")
        print(f"TEXT LEAK: examples for HEAD-ENV in {out}")
    return 1 if leak else 0


if __name__ == "__main__":
    raise SystemExit(main())
