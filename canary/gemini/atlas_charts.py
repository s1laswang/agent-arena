"""Failure Atlas: per-episode "belief trace" charts (PNG), used in the atlas and sent to Gemini (multimodal) to
localise the step where the agent diverges from what the solver's belief supports.

Top panel: the reference solver's posterior P(true mole) and P(eventual accusee) before every step, with the
solver's top-suspect probability as a faint guide; canary plants, restrictions and the accusation marked.
Bottom panel (same x axis, its own scale): per-step regret. No dual axes.
"""
from __future__ import annotations

import io
from pathlib import Path

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
GRID = "#e4e3df"
BLUE = "#2a78d6"     # P(true mole)
ORANGE = "#eb6834"   # P(accusee)
GRAY = "#a3a29c"     # solver's top suspect
VIOLET = "#6250d6"   # canary plants


def render_belief_chart(ep, path: Path | None = None, dpi: int = 100, show_regret: bool = True) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ts = [s.t for s in ep.steps]
    if show_regret:
        fig, (ax, axr) = plt.subplots(2, 1, figsize=(8.0, 4.2), sharex=True, dpi=dpi,
                                      gridspec_kw={"height_ratios": [3, 1], "hspace": 0.08})
    else:  # belief only (the copy Gemini localises from: no regret given away)
        fig, ax = plt.subplots(1, 1, figsize=(8.0, 3.4), dpi=dpi)
        axr = None
    fig.patch.set_facecolor(SURFACE)
    for a in (x for x in (ax, axr) if x is not None):
        a.set_facecolor(SURFACE)
        for side in ("top", "right"):
            a.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            a.spines[side].set_color(GRID)
        a.tick_params(colors=INK2, labelsize=8)
        a.grid(axis="y", color=GRID, linewidth=0.6)
    # day boundaries
    for s in ep.steps:
        if s.tool == "advance_day":
            for a in (x for x in (ax, axr) if x is not None):
                a.axvline(s.t, color=GRID, linewidth=0.6, zorder=0)
    top = [s.p_top if s.p_top is not None else float("nan") for s in ep.steps]
    ax.plot(ts, top, color=GRAY, linewidth=1.2, label="solver's top suspect", zorder=1)
    if ep.mole and ep.accused and ep.accused != ep.mole:
        pa = [s.p_accusee if s.p_accusee is not None else float("nan") for s in ep.steps]
        ax.plot(ts, pa, color=ORANGE, linewidth=2, label=f"P({ep.accused}) accused (innocent)", zorder=3)
    if ep.mole:
        pm = [s.p_mole if s.p_mole is not None else float("nan") for s in ep.steps]
        ax.plot(ts, pm, color=BLUE, linewidth=2, label=f"P({ep.mole}) true mole", zorder=2)
    elif ep.accused:
        pa = [s.p_accusee if s.p_accusee is not None else float("nan") for s in ep.steps]
        ax.plot(ts, pa, color=ORANGE, linewidth=2, label=f"P({ep.accused}) accused", zorder=3)
    ax.axhline(0.6, color=INK2, linewidth=0.8, linestyle=(0, (3, 3)))
    ax.text(ts[0] if ts else 0, 0.62, "0.6 = solver's commit bar (approx.)", fontsize=7, color=INK2)
    can = [s.t for s in ep.steps if s.tool == "plant_canary" and s.ok]
    ax.scatter(can, [0.02] * len(can), marker="^", s=36, color=VIOLET, label="canary planted", zorder=4,
               edgecolors=SURFACE, linewidths=0.8)
    rst = [s.t for s in ep.steps if s.tool == "restrict_access" and s.ok]
    if rst:
        ax.scatter(rst, [0.08] * len(rst), marker="x", s=36, color=INK2, label="restrict_access", zorder=4)
    for s in ep.steps:
        if s.tool == "accuse":
            y = s.p_accusee if s.p_accusee is not None else 0.5
            ax.scatter([s.t], [y], marker="*", s=180, color=ORANGE if not ep.correct else BLUE, zorder=5,
                       edgecolors=SURFACE, linewidths=1.0)
            ax.annotate(f"accuse {s.args.get('employee')}", (s.t, y), textcoords="offset points", xytext=(-8, 8),
                        ha="right", fontsize=8, color=INK)
    ax.set_ylim(-0.02, 1.05)
    ax.set_ylabel("solver posterior", fontsize=8, color=INK2)
    verdict = "correct" if ep.correct else ("WRONG" if ep.accused else "no accusation")
    ax.set_title(f"{ep.id}  ·  {ep.agent}  ·  {ep.tier} {ep.tiers_version}  ·  {verdict}, score {ep.score:.2f}",
                 fontsize=9, color=INK, loc="left")
    ax.legend(fontsize=7, frameon=False, loc="upper left", ncol=2)
    if axr is not None:
        axr.bar(ts, [s.regret for s in ep.steps], width=0.8, color=INK2)
        axr.set_ylabel("regret", fontsize=8, color=INK2)
        axr.set_xlabel("step t (vertical lines = day boundaries)", fontsize=8, color=INK2)
    else:
        ax.set_xlabel("step t (vertical lines = day boundaries)", fontsize=8, color=INK2)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    data = buf.getvalue()
    if path is not None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(data)
    return data


def pick_showcase(eps: list, n: int = 8) -> list:
    """Wrong accusations first (most informative), then the highest-regret correct episodes, spread over
    cohorts; only episodes whose true mole is known."""
    known = [e for e in eps if e.mole]
    wrong = sorted([e for e in known if e.accused and not e.correct], key=lambda e: -e.total_regret)
    rest = sorted([e for e in known if e.correct or not e.accused], key=lambda e: -e.total_regret)
    out, cohorts = [], {}
    for pool, cap in ((wrong, max(1, n // 2)), (rest, n)):
        for e in pool:
            if len(out) >= n or sum(1 for o in out if o in pool) >= cap:
                break
            if cohorts.get(e.cohort, 0) >= 2:
                continue
            out.append(e)
            cohorts[e.cohort] = cohorts.get(e.cohort, 0) + 1
    return out
