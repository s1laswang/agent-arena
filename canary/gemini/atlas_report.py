"""Failure Atlas: judge-facing markdown from atlas.json (pure function, no Gemini)."""
from __future__ import annotations


def _pct(x) -> str:
    return "-" if x is None else f"{100 * x:.0f}%"


def _q(q: dict) -> str:
    quote = " ".join(str(q.get("quote", "")).split())
    if len(quote) > 260:
        quote = quote[:257] + "..."
    mark = "verified at step" if q.get("step_verified") else "verified in episode"
    return f"> `{q['episode']}` t={q.get('t')}: \"{quote}\" *({mark})*"


def render_md(r: dict) -> str:
    c, v, sp = r["corpus"], r["verification"], r.get("spend", {})
    ha = r.get("human_agreement") or {}
    loc = r.get("localisation") or {}
    lab = r.get("labels") or {}
    out = ["# Canary Failure Atlas", "",
           f"*Gemini read every trajectory our agents produced and explained why they fail. Generated "
           f"{r['generated_at']} at `{r.get('git_sha', '')}`.*", "",
           "## At a glance", "",
           f"- **Corpus:** {c['episodes']} episodes from {len(c.get('cohorts', []))} agent cohorts, "
           f"**{c['tokens']:,} tokens in one long-context prompt** to `{r['models']['long_context']}`; "
           f"the same corpus held in an explicit **context cache** on `{r['models']['cache']}` "
           f"({c.get('cache_size_tokens', 0):,} tokens) and queried {sp.get('by_kind', {}).get('generate', 0)} times; "
           f"**{c.get('cached_tokens', 0):,} input tokens served from cache**.",
           f"- **Every claim checked in code:** {v['quotes_checked']} Gemini quotes checked, "
           f"**{_pct(v['pass_rate'])} verbatim in the named episode** ({_pct(v['step_pass_rate'])} at the named step); "
           f"{v['dropped']} unverifiable quotes dropped. Regret shares and episode counts are computed from the "
           f"reference solver's per-step regret, never taken from Gemini.",
           f"- **Per-decision labels:** {lab.get('n', 0)} high-regret decisions (regret >= {c['high_regret_threshold']}, "
           f"{_pct(c.get('high_regret_share'))} of all regret) labelled with a closed taxonomy "
           f"(source: {lab.get('source')}"
           + (f"; Batch API vs cached labels agree on {_pct(lab['batch_vs_cached']['rate'])} of "
              f"{lab['batch_vs_cached']['n']}" if lab.get("batch_vs_cached") else "") + ").",
           f"- **Multimodal:** Gemini read belief-trace charts and localised the divergence step within 3 steps of "
           f"the code's own estimate in {loc.get('agree_within_3_steps', 0)}/{loc.get('n', 0)} episodes.",
           f"- **Human agreement:** " + (f"{_pct(ha.get('score'))} of {ha.get('n_labelled')} claims agreed by a human "
                                        f"labeller" if ha.get("status") == "done" else "pending (docs/gemini/validation.md)"),
           ""]
    if r.get("summary"):
        out += ["## What Gemini found", "", r["summary"], ""]
    out += ["## Failure modes (by share of all solver regret)", "",
            "| # | failure mode | decision | share of regret | episodes | steps |", "|---|---|---|---|---|---|"]
    for i, m in enumerate(r["modes"], 1):
        out.append(f"| {i} | **{m['name']}** (`{m['id']}`) | {m['decision']} | {_pct(m['regret_share'])} | "
                   f"{m['episodes']} | {m['steps']} |")
    out.append("")
    for m in r["modes"]:
        if not m.get("quotes") and not m.get("description"):
            continue
        out += [f"### {m['name']}", "", m["description"], ""]
        if m.get("mechanism"):
            out += [f"**Why the agent does it:** {m['mechanism']}", ""]
        if m.get("solver_would"):
            out += [f"**What the solver does instead:** {m['solver_would']}", ""]
        out += [f"*{_pct(m['regret_share'])} of all regret, {m['episodes']} episodes, {m['steps']} decisions "
                f"(tools: {', '.join(f'{k} {n}' for k, n in m.get('tools', {}).items()) or '-'}).*", ""]
        out += [_q(q) for q in m.get("quotes", [])[:3]]
        if m.get("chart"):
            out += ["", f"![belief trace]({m['chart']})"]
        out.append("")
    cm = r.get("cohort_mode_share") or {}
    comp = r.get("comparison")
    out += ["## Gemini vs GPT vs Grok (never pooled across rule versions)", "",
            "| cohort (model/harness/rules) | episodes | mean score | accuracy | mean regret | top modes (share of the cohort's regret) |",
            "|---|---|---|---|---|---|"]
    for row in c.get("cohorts", []):
        top = ", ".join(f"{k} {_pct(x)}" for k, x in list(cm.get(row["cohort"], {}).items())[:3]) or "-"
        out.append(f"| {row['cohort']} | {row['episodes']} | {row['score_mean']:.3f} | {_pct(row['accuracy'])} | "
                   f"{row['regret_mean']:.3f} | {top} |")
    out.append("")
    if comp:
        out += [f"**Cross-family finding (Gemini's reading, checked against the table above):** "
                f"{comp['cross_family_finding']}", "", f"*Caveats:* {comp['caveats']}", ""]
        for co in comp["cohorts"]:
            out += [f"- **{co['cohort']}**: {co['behaviour']}"]
            out += ["  " + _q(q) for q in co["quotes"][:1]]
        out.append("")
    if r.get("thinking"):
        t = r["thinking"]
        out += ["## Does more thinking help?", "", t["summary"], ""]
        for f in t["findings"]:
            out += [f"- **{f['model']}**: {f['effect']} Reduced: {', '.join(f['modes_reduced']) or '-'}; "
                    f"unchanged: {', '.join(f['modes_unchanged']) or '-'}."]
            out += ["  " + _q(q) for q in f["quotes"][:1]]
        out.append("")
    if r.get("counterfactuals"):
        out += ["## What would the solver have done? (highest-regret decisions)", "",
                "| episode | t | regret | agent did | solver would | why the agent diverged |", "|---|---|---|---|---|---|"]
        for cf in r["counterfactuals"][:10]:
            out.append(f"| `{cf['episode']}` | {cf['t']} | {cf['regret']:.3f} | {cf['agent_did']} | {cf['solver_would']} | "
                       f"{cf['why_diverged']}{' ✔' if cf['verified'] else ''} |")
        out.append("")
    if loc.get("rows"):
        out += ["## Belief traces: where did it go wrong? (multimodal)", "",
                "Each chart is the reference solver's posterior before every step (blue: true mole, orange: the "
                "innocent the agent accused, gray: the solver's top suspect). Gemini was shown the image plus the key "
                "steps and asked to localise the divergence; the code's estimate is the highest-regret step.", ""]
        for row in loc["rows"]:
            g = row.get("gemini_t")
            out += [f"**`{row['episode']}`** ({row['cohort']}, {'correct' if row['correct'] else 'wrong/none'}, "
                    f"score {row['score']:.2f}): Gemini t={g}, code t={row['code_t']}"
                    f"{' (agree)' if row.get('agrees') else ''}. {row.get('what_chart_shows', '')}", "",
                    f"![{row['episode']}]({row['chart']})", ""]
    cl = r.get("clusters")
    if cl:
        out += ["## The agents' own words, clustered (embeddings)", "",
                f"{cl['n']} rationale snippets at high-regret steps, embedded with `{cl['model']}`, k-means k={cl['k']}, "
                f"clusters named by Gemini. Purity vs taxonomy labels {cl['purity_vs_modes']:.2f} (NMI "
                f"{cl['nmi_vs_modes']:.2f}); vs regret tags {cl['purity_vs_tags']:.2f} (NMI {cl['nmi_vs_tags']:.2f}).", "",
                "| cluster | size | regret | top modes | cohorts |", "|---|---|---|---|---|"]
        for k in cl["clusters"]:
            out.append(f"| **{k['name']}**: {k['description']} | {k['size']} | {k['regret']:.3f} | "
                       f"{', '.join(f'{a} {b}' for a, b in k['top_modes'].items())} | "
                       f"{', '.join(f'{a} {b}' for a, b in k['cohorts'].items())} |")
        out.append("")
    out += ["## Method and reproducibility", "",
            "- Corpus: every committed frontier-agent episode (in-process, OpenCode, Codex, replayed), each step with "
            "a one-line result summary, the agent's own words (Gemini thought summaries, Codex/OpenCode messages), "
            "the reference solver's per-step regret, tags and top-suspect belief (`canary.solver.regret`).",
            "- Quotes are kept only if every fragment appears verbatim (whitespace/quote marks normalised) in the "
            "named episode; step-level claims are also checked against that step's lines.",
            f"- Spend: {sp.get('calls', 0)} live Gemini calls, ${sp.get('cost_usd', 0):.2f} (ledger run ids "
            f"{', '.join(r.get('ledger_run_ids', [])) or '-'}); {sp.get('replayed', 0)} responses replayed from cache.",
            "- Reproduce offline, no key: `python -m canary.gemini.atlas --replay` (responses in "
            "`results/gemini/atlas_cache/`).", ""]
    if r.get("errors"):
        out += ["<details><summary>Run notes</summary>", ""] + [f"- {e}" for e in r["errors"][:20]] + ["", "</details>", ""]
    return "\n".join(out)
