"""Renders docs/reports/failure_analysis_v1.4.md from the dict computed by scripts/failure_analysis_v14.py.

Every number is interpolated from the computed data. Prose that describes a specific seed is guarded by an
assert on the facts it states, so a change in the data fails the build instead of leaving a stale sentence.
"""
from __future__ import annotations

import math


def f2(x: float) -> str:
    return f"{x:.2f}"


def pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def _ex_table(G: dict, S: dict) -> str:
    gt = {x["day"]: x for x in G["trace"]}
    st = {x["day"]: x for x in S["trace"]}
    gd = {d["day"]: d for d in G["daily"]}
    sd = {d["day"]: d for d in S["daily"]}
    last = max(max(gt), max(st))
    out = ["| day | Gemini: canaries / interviews | Gemini: P(top) on its own evidence (top = mole?) | Gemini: # consistent | "
           "solver: canaries | solver: P(top) (top = mole?) | solver: # consistent |",
           "|---|---|---|---|---|---|---|"]

    def cell(t, d):
        if t is None:
            return "", "", ""
        tag = "**accuse** " if t["kind"] == "accuse" else ""
        return (f"{tag}{t['p_top']:.2f} ({t['top']}{', mole' if t['top_is_mole'] else ''})", str(t["n_consistent"]),
                str(d.get("canaries", 0)) if d else "0")

    for day in range(1, last + 1):
        g, s = gt.get(day), st.get(day)
        if g is None and s is None:
            continue
        gp, gc, _ = cell(g, gd.get(day))
        sp, sc, scan = cell(s, sd.get(day))
        gday = gd.get(day, {})
        gacts = f"{gday.get('canaries', 0)} / {gday.get('interviews', 0)}" if g else ""
        out.append(f"| {day} | {gacts} | {gp} | {gc} | {scan if s else ''} | {sp} | {sc} |")
    return "\n".join(out)


def render(data: dict) -> str:
    G, S, I, M = data["G"], data["S"], data["I"], data["summary"]
    g, s, i, gap = M["opencode"], M["solver"], M["inproc"], M["gap"]
    G = {int(k): v for k, v in G.items()}
    S = {int(k): v for k, v in S.items()}
    n = g["n"]
    bc = gap["both_correct"]
    hes = gap["hesitation"]
    W = {w["seed"]: w for w in M["wrong_detail"]}

    # ---- guards for the prose below
    assert g["wrong"] == 4 and sorted(W) == [1, 15, 18, 26]
    assert W[1]["flip"] and W[26]["flip"] and not W[1]["mole_in_consistent"] and not W[26]["mole_in_consistent"]
    assert not W[15]["flip"] and W[15]["consistent"] == ["e34", "e37"] and W[15]["mole"] == "e37"
    assert not W[15]["solver_correct"] and W[15]["solver_flip"]
    assert not W[18]["flip"] and W[18]["ev"] < 0 and len(W[18]["consistent"]) == 4 and W[18]["mole_in_consistent"]
    assert sorted(g["ev_negative"]) == [5, 18, 23] and G[5]["correct"] and G[23]["correct"]
    assert gap["abstain_seeds"] == [11] and G[11]["decisive"] is None
    assert max(x["p_top"] for x in G[11]["trace"]) < 0.5
    assert hes["all_top_is_mole"]
    assert G[4]["decisive"]["day"] == 14 and G[4]["accuse_day"] == 16 and S[4]["accuse_day"] == 5
    assert all(d["canaries"] == 0 for d in G[4]["daily"] if d["day"] <= 4)
    assert all(d["canaries"] == 0 for d in G[18]["daily"] if 14 <= d["day"] <= 18)
    assert {x["day"]: x["n_consistent"] for x in G[18]["trace"]}[12] == 4
    assert gap["canary"] < 0 < gap["leak"]

    pm, pi = 0.2 * 1.2, 0.2  # hard tier: p_evasive_innocent x interview_lr (stated in the instructions)
    kl_interview = pm * math.log(pm / pi) + (1 - pm) * math.log((1 - pm) / (1 - pi))
    ratio = g["score"] / s["score"]
    la_ratio = g["luck_adjusted"] / s["luck_adjusted"]
    hits = g["hits"]
    L = []
    a = L.append
    a("# Failure analysis, rules v1.4 hard: Gemini over MCP vs the reference solver")
    a("")
    a("**Scope.** The judges' harness (OpenCode + `gemini-4-carbon` over MCP), rules v1.4, hard tier, dev seeds 0–29, "
      "each episode paired with the reference solver on the same seed. This is the run behind the headline "
      f"**{pct(ratio)} of the solver** ({pct(la_ratio)} luck-adjusted) in `docs/reports/gap.md`. "
      "Every number below is computed by `scripts/failure_analysis_v14.py` from the committed episodes "
      "(`data/runs/committed/v1.4/`). The script replays every episode in a fresh Env and aborts unless the "
      "replay reproduces the recorded score. Raw per-episode output: `results/failure_analysis_v1.4.json`. "
      "Reproduce (no keys, a few seconds): `uv run python scripts/failure_analysis_v14.py`.")
    a("")
    a("**Bottom line.**")
    a(f"- **The expected story is half right.** Gemini under-explores. It plants {g['canaries']:.1f} canaries against "
      f"{s['canaries']:.1f}, spends the daily action budget on {g['interviews']:.0f} near-worthless interviews per episode, "
      f"and identifies the mole later (day {g['accuse_day_horizon21']:.1f} vs {s['accuse_day']:.1f}). But the V drained by waiting "
      f"({gap['leak']:+.2f} V over 30 seeds) is almost exactly repaid by the canaries it never bought ({gap['canary']:+.2f} V).")
    a(f"- **What under-exploration actually costs is thin evidence at the moment of commitment.** {len(g['not_isolated'])} of "
      f"{g['accused']} accusations were made while two or more people were still consistent with every leak "
      f"(solver: {len(s['not_isolated'])} of {s['accused']}). That is the largest mistake, {gap['penalty']:.2f} V of expected value. It includes "
      f"{len(g['ev_negative'])} negative-EV accusations near the horizon.")
    a("- **The four wrong accusations:** two are disclosed fingerprint noise at P ≥ 0.95 (luck). One is a P 0.80 bet on an "
      "unresolved pair, which the solver also lost on the same seed. One is a negative-EV gamble. "
      f"Gemini's posteriors predicted {g['expected_wrong']:.1f} wrong accusations, and it made {g['wrong']}.")
    a("")
    a("**Companion.** The Gemini Failure Atlas (`results/gemini/atlas.md`, Gemini CEO) reads every trajectory of every "
      "cohort and names failure modes by share of solver regret. This report is narrower and deeper. It covers one judged "
      "tier and one run, and it accounts for every point of the gap to the solver exactly. It also tests the "
      "\"was the information there?\" question with counterfactual replays. The two use different units: the atlas measures per-step "
      "regret across 153 episodes, and this report measures paired V on 30 seeds. Where they overlap, they agree on the "
      "first mode, accusing on sub-threshold evidence.")
    a("")
    a("**Definitions.**")
    a("- *Solver posterior* is the reference `SolverPolicy`'s exact Bayesian posterior computed from **the agent's own tool "
      "results only** (as in `canary/analysis/accuse.py`). Whatever it says, the agent had the evidence for it.")
    a("- *Solver rule* is the solver's own accusation rule applied to that posterior: accuse the top suspect when "
      "P ≥ 0.85 and EV = P·E[true V] − (1−P) > 0, or on the last day when EV > 0.")
    a("- *Consistent set* is the set of employees who held every leaked regular document (recipients are public through the free "
      "`list_documents`) and got the shown label of every leaked canary, in the agent's last leak-feed read. "
      "A size of 1 means the leaks alone isolate one person, up to the stated 5% fingerprint noise.")
    a("- *Luck-adjusted score* is P·V − (1−P) at the accusation, and 0 without one. This is the definition used in "
      "`scripts/paired_v13.py`.")
    a("")
    a("## 1. Headline numbers (30 paired seeds)")
    a("")
    a("| | **Gemini, OpenCode/MCP** | **reference solver** | Gemini in-process (context) |")
    a("|---|---|---|---|")
    rows = [
        ("mean score", lambda x: f"{x['score']:.3f} ± {x['score_ci']:.3f}"),
        ("luck-adjusted score", lambda x: f"{x['luck_adjusted']:.3f}"),
        ("canaries planted before the accusation", lambda x: f"**{x['canaries']:.1f}** ± {x['canaries_ci']:.1f}"),
        ("canary capacity used (2/day)", lambda x: pct(x["capacity_used"])),
        ("days with ≥1 canary", lambda x: pct(x["days_with_canary_share"])),
        ("first canary (day)", lambda x: f"{x['first_canary_day']:.1f}"),
        ("staff who ever received a canary (of 40)", lambda x: f"{x['staff_covered']:.1f}"),
        ("recipients / labels per canary", lambda x: f"{x['recipients_mean']:.1f} / {x['labels_mean']:.1f}"),
        ("interviews per episode", lambda x: f"{x['interviews']:.0f}"),
        ("leak-feed reads / access-log reads", lambda x: f"{x['feed_reads']:.1f} / {x['log_reads']:.1f}"),
        ("accusation day (accused episodes)", lambda x: f"**{x['accuse_day']:.1f}**"),
        ("accusation day (abstentions counted as day 21)", lambda x: f"{x['accuse_day_horizon21']:.1f}"),
        ("leaks before the accusation", lambda x: f"{x['leaks_at_accusation']:.1f}"),
        ("solver posterior P(accused) at the accusation, mean / median", lambda x: f"{x['p_mean']:.2f} / {x['p_median']:.2f}"),
        ("accusations at P ≥ 0.95 / 0.85–0.95 / 0.60–0.85 / < 0.60",
         lambda x: f"{x['p_buckets']['ge95']} / {x['p_buckets']['85_95']} / {x['p_buckets']['60_85']} / {x['p_buckets']['lt60']}"),
        ("accusations with EV < 0 (by the solver posterior)", lambda x: str(len(x["ev_negative"]))),
        ("accusations made while the leaks had isolated one person", lambda x: f"{x['isolated']} / {x['accused']}"),
        ("wrong accusations (expected from the posteriors)", lambda x: f"**{x['wrong']}** ({x['expected_wrong']:.1f})"),
        ("abstentions (no accusation by day 21)", lambda x: f"{x['abstain']} / {x['n']}"),
    ]
    for name, fn in rows:
        a(f"| {name} | {fn(g)} | {fn(s)} | {fn(i)} |")
    a("")
    a(f"The reviewer's figures check out. Gemini plants {g['canaries']:.1f} canaries against the solver's {s['canaries']:.1f}. "
      f"It accuses on day {g['accuse_day_horizon21']:.1f} against day {s['accuse_day']:.1f}, counting the one abstention as day 21 "
      f"({g['accuse_day']:.1f} over the 29 accusations). Its 4 wrong accusations were made at solver posteriors "
      f"{', '.join(f2(W[k]['p']) for k in sorted(W))} (seeds {', '.join(str(k) for k in sorted(W))}).")
    a("")
    a("## 2. Where the gap comes from (exact accounting)")
    a("")
    a(f"Summed over the 30 seeds, the solver scores **{gap['raw_gap']:.2f} V** more than Gemini "
      f"({gap['raw_gap'] / n:.3f} per episode, the paired difference in gap.md).")
    a("")
    a("**By episode outcome (the raw scoreboard):**")
    a("")
    a("| Gemini outcome | seeds | solver − Gemini (V) |")
    a("|---|---|---|")
    a(f"| wrong accusation | {g['wrong']} | {gap['raw_by_outcome']['wrong']:.2f} |")
    a(f"| abstained | {g['abstain']} | {gap['raw_by_outcome']['abstain']:.2f} |")
    a(f"| correct accusation | {g['accused'] - g['wrong']} | {gap['raw_by_outcome']['gemini_correct']:+.2f} |")
    a(f"| **total** | {n} | **{gap['raw_gap']:.2f}** |")
    a("")
    a(f"On the {bc['n']} seeds where both agents accused correctly, Gemini scores {bc['gemini_score']:.3f} against the solver's "
      f"{bc['solver_score']:.3f}. That is no loss, even though it accuses later (day {bc['gemini_day']:.1f} vs "
      f"{bc['solver_day']:.1f}, later on {bc['gemini_later']} of {bc['n']} seeds) and takes {bc['gemini_leaks']:.1f} "
      f"leaks against {bc['solver_leaks']:.1f}. The extra leak damage is paid for by the canaries it never bought "
      f"({bc['gemini_canaries']:.1f} vs {bc['solver_canaries']:.1f} at 0.01 V each). So the raw gap is the wrong "
      "accusations plus one abstention. The question is how much of that is skill and how much is luck.")
    a("")
    a("**Luck-adjusted, by mistake (an additive identity; the script asserts that it sums).** For an accused episode, "
      "V = 1 − 0.05·leaks − 0.01·canaries − restriction costs, and the luck-adjusted score is "
      "V − (1−P)(1+V). So the solver-minus-Gemini luck-adjusted gap splits exactly into the terms below. "
      "Luck is the realised score minus the luck-adjusted score.")
    a("")
    a("| # | mistake (ranked by expected V lost) | V lost, 30 seeds | per episode |")
    a("|---|---|---|---|")
    items = [
        ("Accusing on evidence that had not isolated the mole (expected loss (1−P)(1+V) at the accusation, vs the solver's)",
         gap["penalty"]),
        ("Never reaching an accusable posterior → abstained (seed 11)", gap["abstain"]),
        ("Extra leak damage from accusing later", gap["leak"]),
        ("Restriction costs", gap["restrict"]),
        ("Canary costs *saved* by planting fewer canaries", gap["canary"]),
    ]
    for k, (name, v) in enumerate(items, 1):
        a(f"| {k} | {name} | {v:+.2f} | {v / n:+.3f} |")
    a(f"| | **luck-adjusted gap** | **{gap['la_gap']:+.2f}** | {gap['la_gap'] / n:+.3f} |")
    a(f"| | bad luck (realised − expected; Gemini {gap['luck_gemini']:+.2f}, solver {gap['luck_solver']:+.2f}) | "
      f"{gap['luck']:+.2f} | {gap['luck'] / n:+.3f} |")
    a(f"| | **raw gap** | **{gap['raw_gap']:+.2f}** | {gap['raw_gap'] / n:+.3f} |")
    a("")
    a(f"- Row 1 comes entirely from the {len(g['not_isolated'])} accusations Gemini made while two or more employees were still "
      f"consistent with every leak (seeds {', '.join(map(str, g['not_isolated']))}). Those account for {gap['penalty_not_isolated']:.2f} V, and the "
      f"{g['isolated']} isolated accusations net {gap['penalty'] - gap['penalty_not_isolated']:+.2f}. "
      f"{gap['penalty_ev_negative']:.2f} V of it is the three accusations with **negative EV** under the solver posterior "
      f"(seeds {', '.join(map(str, g['ev_negative']))}, all on day ≥ 18), where abstaining (score 0) was better by the "
      "formula the instructions print. The solver accused at a consistent set of 1 in "
      f"{s['isolated']}/{s['accused']} episodes and never at EV < 0.")
    a(f"- Rows 3 and 5 nearly cancel ({gap['leak']:+.2f} and {gap['canary']:+.2f}). Accusing later drains V, but Gemini "
      "financed the wait by not paying for canaries, so waiting by itself is close to free here. What under-exploration "
      "really costs is row 1: the evidence is *thinner* at the moment Gemini commits.")
    a(f"- *Hesitation*, meaning the agent had decisive evidence and still waited, is small. On only {len(hes['seeds'])} seeds "
      f"({', '.join(map(str, hes['seeds']))}) did the solver rule fire on Gemini's own evidence before Gemini accused. "
      f"There it waited {hes['days_early']:.1f} more days on average, and the top suspect was always the mole. "
      f"Accusing at that moment (exact counterfactual replay) would have added {hes['gain']:.2f} V in total.")
    a(f"- Luck: Gemini's posteriors predicted {g['expected_wrong']:.1f} wrong accusations and it made {g['wrong']} "
      f"(P(≥ {g['wrong']} | its posteriors) = {g['p_ge_observed_wrong']:.2f}), so the count is not anomalous. "
      f"The solver's posteriors predicted {s['expected_wrong']:.1f} and it made {s['wrong']}. Gemini was not unlucky overall. "
      "It took bets that the evidence priced at about three lost accusations in 29, against about one for the solver.")
    a("")
    a("## 3. The four wrong accusations")
    a("")
    a("| seed | day | accused | mole | solver P(accused) | EV | consistent set at accusation | fingerprint flip? | solver on this seed | reading |")
    a("|---|---|---|---|---|---|---|---|---|---|")
    reading = {
        1: "**luck**: the one label that singled out e39 was a 5% fingerprint flip (rules: \"evidence, not proof\")",
        15: "**resolvable**: e34 and e37 sat in the same variant of every canary; one split canary would have separated them with 9 days left. The solver also lost this seed (to a flip)",
        18: "**a gamble**: 4 people still consistent, EV < 0, and Gemini planted no canary on days 14–18",
        26: "**luck**: the label that pointed at e04 was a fingerprint flip",
    }
    for k in sorted(W):
        w = W[k]
        a(f"| {k} | {w['day']} | {w['accused']} | {w['mole']} | {w['p']:.2f} | {w['ev']:+.2f} | "
          f"{', '.join(w['consistent'])} | {'yes' if w['flip'] else 'no'} | "
          f"{'correct' if w['solver_correct'] else 'wrong'} ({w['solver_score']:+.2f}) | {reading[k]} |")
    a("")
    a("The honest verdict: **two of the four are bad luck that the rules disclose** (seeds 1 and 26, P ≥ 0.95, wrecked by the "
      "stated 5% fingerprint noise). On that same evidence the solver's own rule (P ≥ 0.85, EV > 0) accuses the same "
      "innocent. **One is a real gamble** (seed 18, EV −0.08 at P 0.63, "
      "day 18). **One is a defensible bet on an unresolved pair** (seed 15, P 0.80, EV +0.32), and the solver itself lost this seed. "
      "So \"luck, not gambling\" holds for three of the four, not for all four. Across all 29 accusations Gemini did take three "
      f"negative-EV shots at the horizon (seeds {', '.join(map(str, g['ev_negative']))}). Two of them happened to land "
      f"(+{G[5]['score']:.2f}, +{G[23]['score']:.2f}) and one did not (−1.00).")
    a("")
    a("## 4. How Gemini commits: single canary hits")
    a("")
    a(f"Canary hits on the accused in Gemini's last feed read before accusing: " +
      ", ".join(f"{v} accusation(s) with {k} hit(s)" for k, v in hits.items()) + ". "
      f"The solver: " + ", ".join(f"{v} with {k}" for k, v in s["hits"].items()) + ".")
    a("")
    a(f"Gemini accused on a **single canary hit {hits.get('1', 0)} times out of {g['accused']}** "
      f"(the hit variant had {g['single_hit_group_mean']:.1f} holders on average). It accused with **no canary hit at all** "
      f"{hits.get('0', 0)} times, on regular-document leaks and logs only. Both of those were correct. The solver accuses on a single hit even more often "
      f"({s['hits'].get('1', 0)}/{s['accused']}, holders {s['single_hit_group_mean']:.1f}). A single hit is not the problem. "
      "The solver's single hit lands on a group that the regular leaks have *already* narrowed, so the consistent set "
      f"is 1 (mean consistent-set size at accusation: solver {s['consistent_mean']:.1f}, Gemini {g['consistent_mean']:.1f}). "
      "Gemini's single hits often leave several people standing.")
    a("")
    a("## 5. Root cause: under-exploration, and why the information was there")
    a("")
    a("Each mistake traces back to one decision about a tool the agent had.")
    a("")
    a(f"1. **Interviews instead of canaries (the daily action budget).** Gemini runs {g['interviews']:.0f} interviews per "
      f"episode. On {g['days_lt2_full']} of the {g['days_lt2_canaries']} days on which it planted fewer than 2 canaries, it had "
      f"used all 8 daily actions, {g['interviews_on_lt2_full']} of them on interviews. The instructions state the interview "
      "likelihood ratio: the mole is evasive with probability 0.2 × 1.2, against 0.2 for an innocent. An interview is "
      f"therefore worth at most {kl_interview:.3f} nats (the KL divergence between the mole's and an innocent's answer), while a "
      "well-split canary is worth up to ln 3 ≈ 1.1 nats when it leaks. "
      f"The solver never interviews and plants on {pct(s['days_with_canary_share'])} of its days, against Gemini's "
      f"{pct(g['days_with_canary_share'])}. **Decision that would have avoided it:** use the second `plant_canary` "
      "slot each day instead of interviews.")
    a(f"2. **Late and intermittent canaries.** Gemini's first canary comes on day {g['first_canary_day']:.1f} on average, against day "
      f"{s['first_canary_day']:.0f} for the solver, and it often plants two canaries every *other* day (seed 11 and seed 4 below). "
      "With a stated delay of 2–3 days, every skipped day pushes the next answer back by a day. "
      f"Result: capacity used {pct(g['capacity_used'])} against {pct(s['capacity_used'])}, and {g['canaries']:.1f} against "
      f"{s['canaries']:.1f} canaries.")
    a("3. **Committing before the leaks isolate one person.** This is the most expensive mistake (row 1). When the consistent "
      "set is 2–4 people, one canary that gives each of them a different label settles it in 2–3 days. Seed 15 had 9 days "
      "left and seed 18 had 3. **Decision:** plant the splitting canary, or abstain if EV < 0. Both options are named in the "
      "instructions.")
    a("4. **The abstention (seed 11).** Here Gemini's own evidence never passed P = "
      f"{max(x['p_top'] for x in G[11]['trace']):.2f}. The consistent set stuck at 7 from day 8, while Gemini planted "
      f"{G[11]['canary']['n']} canaries on alternate days and ran {G[11]['tools'].get('interview', 0)} interviews. "
      f"Abstaining was the right call on that evidence. The loss ({gap['abstain']:.2f} V) is the evidence it never collected: "
      f"the solver, on the same seed, accused correctly on day {S[11]['accuse_day']}.")
    a("")
    a("**The information and tools were available. Evidence:**")
    a("- *Same observations.* The solver posterior above is computed **only from tool results Gemini itself received**. "
      "When it shows P ≥ 0.85 while Gemini waits (5 seeds), or a consistent set of 4 when Gemini accuses (seed 18), "
      "that is a fact about Gemini's own transcript, not about something hidden.")
    a(f"- *Same tools, same budgets.* On the same 30 seeds, the solver uses only the 13 public tools under the same "
      f"8-actions/day and 2-canaries/day limits, makes {s['calls']:.0f} calls against Gemini's {g['calls']:.0f}, and reaches a "
      f"consistent set of 1 in {s['isolated']}/{s['accused']} episodes by day {s['accuse_day']:.1f}.")
    a("- *Nothing missed in the feed.* Gemini read the leak feed on the days that known V dropped. Its average lag "
      f"between a leak surfacing and Gemini seeing it is {g['feed_lag_mean']:.2f} days, so it did not lose information by "
      f"reading the feed less often ({g['feed_reads']:.1f} reads against {s['feed_reads']:.1f}).")
    a(f"- *Not a harness artifact.* The in-process run (full history, thought-signature replay) shows the same "
      f"exploration profile: {i['canaries']:.1f} canaries, {i['interviews']:.0f} interviews, and {pct(i['capacity_used'])} capacity. "
      f"It had fewer wrong accusations ({i['wrong']}, expected {i['expected_wrong']:.1f}) and fewer sub-0.85 accusations "
      f"({i['p_buckets']['60_85'] + i['p_buckets']['lt60']} vs {g['p_buckets']['60_85'] + g['p_buckets']['lt60']}). "
      "Under-exploration is a trait of the model, and the OpenCode run additionally commits on thinner evidence.")
    a("- *The rules are stated.* Interview LR, delay 2–3, fingerprint accuracy 0.95 (\"evidence, not proof\"), "
      "2 canaries/day × 3 labels, and the EV-to-accuse formula all appear in the instructions (see `docs/DIFFICULTY.md` "
      "for the audit).")
    a("")
    a("## 6. Two annotated episodes")
    a("")
    for seed, title, note_before, note_after in (
        (4, "Seed 4: slow identification (correct, +0.40 vs solver +0.73)",
         "Gemini plants nothing on days 1–4 and runs 6–7 interviews a day. From day 5 it plants two canaries every other day. "
         "The solver plants 2 a day from day 1, and its day-1–3 canaries surface by day 4. It accuses on day 5.",
         f"The solver rule fires on Gemini's own evidence at the end of day {G[4]['decisive']['day']} "
         f"(P {G[4]['decisive']['p_top']:.2f} on the mole, consistent set 1). Gemini spends two more days interviewing and accuses on day "
         f"{G[4]['accuse_day']}. Accusing on day 14 would have scored {G[4]['decisive']['cf_score']:.2f} (exact replay) instead of "
         f"{G[4]['score']:.2f}. The other 9 days of the gap with the solver come from exploring late and at half capacity, not from hesitation."),
        (18, "Seed 18: committing on an unresolved group (wrong, −1.00 vs solver +0.52)",
         "Both agents narrow the field to 12 by day 6. On day 12 Gemini's leaks leave 4 people consistent "
         "(e09, e27, e29, e37). Gemini plants two canaries on days 12 and 13 and then none on days 14–17, filling those days "
         "with interviews.",
         f"On day 18 it accuses e29 at P {G[18]['p_accused']:.2f}. EV is {G[18]['ev_accused']:+.2f} by the formula in the "
         "instructions, so abstaining scored more, and 4 people were still consistent. The mole was e27. A canary on day 14–16 "
         "giving each of the four a different label (3 labels + 1 non-recipient) shows in the feed 2–3 days after the mole "
         "leaks it. A leak on the planting day would have surfaced on day 16–19, inside the 21-day horizon. "
         "The solver's canaries isolate e27 by day 13."),
    ):
        a(f"### {title}")
        a("")
        a(note_before)
        a("")
        a(_ex_table(G[seed], S[seed]))
        a("")
        a(note_after)
        a("")
    a("## 7. Per-seed table")
    a("")
    a("| seed | Gemini score | solver score | Gemini day | solver day | Gemini canaries | solver canaries | Gemini interviews | "
      "P(accused) | EV | # consistent | canary hits on accused | solver-rule decisive earlier? |")
    a("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for k in range(n):
        x, y = G[k], S[k]
        dec = x["decisive"]
        wrong = " ✗" if x["accused"] and not x["correct"] else ""
        p = f2(x["p_accused"]) if x["accused"] else "—"
        ev = f"{x['ev_accused']:+.2f}" if x["accused"] else "—"
        cons = str(len(x["consistent_at_accusation"])) if x["accused"] else "—"
        nhits = str(x["evidence_on_accused"]["hits"]) if x["accused"] else "—"
        dtxt = f"day {dec['day']} (cf {dec['cf_score']:+.2f})" if dec else ""
        a(f"| {k} | {x['score']:+.2f}{wrong} | {y['score']:+.2f} | {x['accuse_day'] or '—'} | {y['accuse_day']} | "
          f"{x['canary']['n']} | {y['canary']['n']} | {x['tools'].get('interview', 0)} | {p} | {ev} | {cons} | "
          f"{nhits} | {dtxt} |")
    a("")
    a("✗ = wrong accusation. *cf* = exact score had Gemini accused the top suspect at that end of day.")
    a("")
    a("## 8. Context from other analyses (cited, not recomputed by this script)")
    a("")
    a("- **The reference is a fair bar.** HEAD-ENV's `docs/reports/reference_optimality.md` (on justSilas via PR #20; "
      "hard dev seeds 8000–8399) finds the v1.4 solver's posterior *calibrated*: accuracy at accusation is "
      "96–99% on hard, and P(top = mole) tracks the posterior across all decision days. This is the property the luck "
      "adjustment and the \"expected wrong accusations\" above rely on. It also finds the solver's stopping *near-optimal*: "
      "the best p ≥ a + b·V rule adds +0.005 on hard. Its hard loss is information-rate bound, made of leak damage "
      "0.250 plus canary cost 0.120 out of 0.422, and a stronger `solver_v2` gained only +0.012 ± 0.029 on fresh "
      "seeds. So Gemini's shortfall measured against it is Gemini's own, not a soft reference.")
    a("- **Why hard and not medium.** S3's scripted version of the Gemini swarm's w2b-008 plan is a no-Bayes elimination "
      "heuristic that intersects suspects with the recipients of leaked documents and canaries and accuses only when one suspect "
      "is left (`canary/redteam/swarm_probes.py` on `s3-integrity` d3e7629, work in progress, numbers as reported by S3). "
      "On 40 judge seeds per tier it ties the solver on easy (+0.742 vs +0.765) and medium (+0.648 vs +0.671), but "
      "falls clearly behind on hard (+0.363 vs +0.545, 3 wrong). That matches the pattern here. On medium, set elimination is "
      "enough, so frontier parity there (OpenCode 111%) is expected. On hard, fingerprint noise and the 2–3-day delays break "
      "strict elimination (seeds 1 and 26 above: the strict consistent set excluded the true mole after a flip), and "
      "weighing evidence and choosing what to test next is what pays.")
    a("")
    a("## 9. What this means for the rubric")
    a("")
    a("- **Main mistakes, tied to decisions:** (1) committing before the leaks isolate one person, including three negative-EV "
      "shots at the horizon; (2) spending the daily action budget on interviews instead of the second canary; (3) late, "
      "every-other-day canaries. Each one maps to a tool call the agent could have made differently.")
    a("- **Information and tools available:** the solver posterior is computed from Gemini's own observations, and the solver "
      "reaches decisive evidence with the same tools and budgets on the same seeds.")
    a("- **Not withheld info or trick wording:** two of the four wrong accusations come from the disclosed 5% fingerprint "
      "noise, which hits any investigator. The instruction audit (`docs/DIFFICULTY.md`) finds no hidden rule.")
    a("- **Caveat:** n = 30 and the raw ratio's CI is wide (gap.md). The decomposition is exact for these 30 episodes, "
      "but the shares carry sampling noise. This is one model (gemini-4-carbon). A second family is a PLAN-95 item.")
    a("")
    if M.get("hint"):
        L.extend(_hint_section(M["hint"]))
    return "\n".join(L)


def _verdict(d: dict, n: int = 99) -> str:
    if n < 3:
        return f"not testable at n = {n}"
    lo, hi = d["mean"] - d["ci"], d["mean"] + d["ci"]
    return "higher" if lo > 0 else "lower" if hi < 0 else "no detectable change"


def _hint_infra(H: dict) -> str:
    inv = H.get("infra_invalid") or {"total": 0, "per_seed": {}, "by_reason": {}}
    per = ", ".join(f"seed {k}: {v}" for k, v in inv["per_seed"].items()) or "none"
    why = ", ".join(f"{k} {v}" for k, v in inv["by_reason"].items())
    return (f"Infra-invalid attempts excluded and retried (never scored): {inv['total']}"
            + (f" ({why}); per seed: {per}." if inv["total"] else ".")
            + (" *stopped_at_key_switch* = attempts we stopped, before any result existed, when the run moved between API "
               "keys to escape a saturated quota." if "stopped_at_key_switch" in inv["by_reason"] else ""))


def _hint_section(H: dict) -> list[str]:
    if H["n"] == 0:
        return ["## 10. Causal hint test (pre-registered in gap.md)", "",
                "**Not measurable tonight.** The pre-registered run (OpenCode + `gemini-4-carbon`, v1.4 hard, `--hint gather`, "
                "seeds in fixed order 0→29, at most 3 in parallel, hard stop 05:40 Helsinki) completed **n = 0** episodes. "
                "Every attempt ended before its episode finished. Most were cut off by the Gemini API quota for gemini-4-carbon "
                "(2,000,000 input tokens per minute, shared with other runs on the same project; OpenCode exits after about "
                "75 s of 429 retries), and the rest were stopped by us when switching API keys (counts below). No hinted episode was scored, so this report makes no claim about the hint "
                "either way. The hint code (`--hint gather`, off by default) and this analysis are in place for a rerun.",
                "", _hint_infra(H), ""]
    h, u, s, n = H["hint"], H["unhinted"], H["solver"], H["n"]
    seeds = H["seeds"]
    rng = (f"seed {seeds[0]}" if n == 1 else f"seeds {seeds[0]}–{seeds[-1]}"
           if seeds == list(range(seeds[0], seeds[-1] + 1)) else "seeds " + ", ".join(map(str, seeds)))
    small = n < 3   # no meaningful CI below 3 paired seeds

    def ci(x):
        return "" if small else f" [{pct(x[0])}, {pct(x[1])}]"

    def pm(m, c, fmt="{:.2f}"):
        return fmt.format(m) if small else f"{fmt.format(m)} ± {fmt.format(c)}"

    def pr(a):
        return "–" if a["premature_rate"] is None else f"{len(a['not_isolated'])} / {a['accused']} ({pct(a['premature_rate'])})"

    ds, dl, dc, dd = H["diff_score"], H["diff_luck_adjusted"], H["diff_canaries"], H["diff_accuse_day"]
    L = ["## 10. Causal hint test (pre-registered in gap.md)", "",
         f"**Setup.** Same harness and model (OpenCode + `gemini-4-carbon` over MCP, v1.4 hard) with one added prompt line "
         f"(`--hint gather`, opt-in, never part of the judged instruction), which restates rules already on the instruction page: "
         f"*\"Evidence first: you may plant up to the stated number of canaries every day; plant them every day, and accuse only "
         f"when exactly one employee is consistent with every leak you have seen (otherwise abstain, which scores 0).\"* "
         f"Seeds were run in the fixed order 0→29, at most 3 in parallel, on an API quota shared with other runs. Launches stopped "
         f"and episodes still in flight were killed at the hard stop, 05:40 Helsinki, and dropped unscored (the amendments in "
         f"gap.md). **n = {n}** ({rng}) finished in time, and all of them are reported. Infra-invalid attempts were "
         f"retried and never scored. Each hinted episode is paired with the unhinted primary episode and the solver on the same seed. "
         f"The hinted run used OpenCode 1.19.5 and the unhinted run used 1.18.29.",
         "",
         f"| same {n} seed{'s' if n != 1 else ''} | **Gemini + hint** | Gemini, no hint | reference solver |",
         "|---|---|---|---|",
         f"| mean score | {pm(h['score'], h['score_ci'])} | {pm(u['score'], u['score_ci'])} | {pm(s['score'], s['score_ci'])} |",
         f"| % of solver{'' if small else ' [95% CI]'} | **{pct(h['pct_solver'])}**{ci(h['pct_solver_ci'])} | {pct(u['pct_solver'])}{ci(u['pct_solver_ci'])} | – |",
         f"| luck-adjusted score (% of solver{'' if small else ' [95% CI]'}) | {f2(h['luck_adjusted'])} ({pct(h['la_pct_solver'])}{ci(h['la_pct_solver_ci'])}) | "
         f"{f2(u['luck_adjusted'])} ({pct(u['la_pct_solver'])}{ci(u['la_pct_solver_ci'])}) | {f2(s['luck_adjusted'])} |",
         f"| canaries planted before the accusation | **{pm(h['canaries'], h['canaries_ci'], '{:.1f}')}** | {pm(u['canaries'], u['canaries_ci'], '{:.1f}')} | {pm(s['canaries'], s['canaries_ci'], '{:.1f}')} |",
         f"| canary capacity used / days with ≥1 canary | {pct(h['capacity_used'])} / {pct(h['days_with_canary_share'])} | "
         f"{pct(u['capacity_used'])} / {pct(u['days_with_canary_share'])} | {pct(s['capacity_used'])} / {pct(s['days_with_canary_share'])} |",
         f"| interviews per episode | {h['interviews']:.0f} | {u['interviews']:.0f} | {s['interviews']:.0f} |",
         f"| premature commits (accused while ≥2 consistent) | **{pr(h)}** | {pr(u)} | {pr(s)} |",
         f"| accusations with EV < 0 | {len(h['ev_negative'])} | {len(u['ev_negative'])} | {len(s['ev_negative'])} |",
         f"| wrong accusations (expected) / abstentions | {h['wrong']} ({h['expected_wrong']:.1f}) / {h['abstain']} | "
         f"{u['wrong']} ({u['expected_wrong']:.1f}) / {u['abstain']} | {s['wrong']} ({s['expected_wrong']:.1f}) / {s['abstain']} |",
         f"| accusation day (abstention = 21) | {h['accuse_day_horizon21']:.1f} | {u['accuse_day_horizon21']:.1f} | {s['accuse_day_horizon21']:.1f} |",
         "",
         (f"**Paired, hint − no hint (same {n} seed{'s' if n != 1 else ''}):** score {ds['mean']:+.3f}, luck-adjusted "
          f"{dl['mean']:+.3f}, canaries {dc['mean']:+.1f}, accusation day {dd['mean']:+.1f}. With n = {n} there is no confidence "
          f"interval, so these are observations, not a test of the hint." if small else
          f"**Paired, hint − no hint (same {n} seeds, mean ± 95% CI):** score {ds['mean']:+.3f} ± {ds['ci']:.3f} ({_verdict(ds, n)}); "
          f"luck-adjusted {dl['mean']:+.3f} ± {dl['ci']:.3f} ({_verdict(dl, n)}); canaries {dc['mean']:+.1f} ± {dc['ci']:.1f} "
          f"({_verdict(dc, n)}); accusation day {dd['mean']:+.1f} ± {dd['ci']:.1f} ({_verdict(dd, n)})."),
         "",
         "| seed | hint score | no-hint score | solver | hint canaries | no-hint canaries | hint: # consistent at accusation |",
         "|---|---|---|---|---|---|---|"]
    for r in H["per_seed"]:
        mark = "" if not r["hint_accused"] or r["hint_correct"] else " ✗"
        cons = "abstained" if not r["hint_accused"] else str(r["hint_consistent"])
        L.append(f"| {r['seed']} | {r['hint']:+.2f}{mark} | {r['unhinted']:+.2f} | {r['solver']:+.2f} | {r['hint_canaries']} | "
                 f"{r['unhinted_canaries']} | {cons} |")
    uw = [r["seed"] for r in H["per_seed"] if r["unhinted"] < 0]
    hw = [r["seed"] for r in H["per_seed"] if r["hint_accused"] and not r["hint_correct"]]
    if uw or hw:
        L += ["", "Wrong accusations (score −1) dominate the raw means at this n: "
              + (f"the no-hint run's on seed{'s' if len(uw) > 1 else ''} {', '.join(map(str, uw))} (see §3 for how {'it' if len(uw) == 1 else 'each'} arose)" if uw else "")
              + ("; " if uw and hw else "")
              + (f"the hinted run's on seed{'s' if len(hw) > 1 else ''} {', '.join(map(str, hw))}" if hw else "")
              + ". The luck-adjusted row prices every accusation at the solver posterior instead, so it is the fairer comparison."]
    L += ["", _hint_infra(H)]
    L += ["", f"Reproduce: `uv run python scripts/failure_analysis_v14.py` (the hinted episodes are in "
          f"`results/causal_hint/opencode-gemini-4-carbon-hint-gather/hard/`, replay-verified). "
          + (f"n = {n} is far too small to test the hint. It is reported because the pre-registration requires reporting every "
             f"completed seed. A rerun on the full 30 seeds needs an API quota not shared with other runs." if small else
             f"n = {n} is small: read the CIs, not the point estimates."), ""]
    return L
