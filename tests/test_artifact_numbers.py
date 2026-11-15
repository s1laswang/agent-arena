from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import tokenize
from pathlib import Path
from typing import Any, Iterator

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "verify_artifact_numbers.py"
DOC_PATH = ROOT / "docs" / "NUMBER-PROVENANCE-INDEX.md"
SELF_PATH = Path(__file__).resolve()
OPENCODE_TMP = Path("/tmp/opencode")

H = chr(35)
H2 = H * 2
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
PLUS_MINUS = chr(0x00B1)


def _load_module():
    spec = importlib.util.spec_from_file_location("verify_artifact_numbers", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


van = _load_module()


@pytest.fixture()
def opencode_tmp() -> Iterator[Path]:
    OPENCODE_TMP.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=str(OPENCODE_TMP), prefix="test-artifact-numbers-"
    ) as tmp_str:
        yield Path(tmp_str)


def _write(root: Path, rel: str, content: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _paired_row_dict(
    *,
    label: str,
    group: str,
    agent: str,
    tier: str,
    n: int,
    mean: float,
    ci: float,
    sol: float,
    ratio: float,
    r_lo: float,
    r_hi: float,
    post: float,
    p_ratio: float,
    p_lo: float,
    p_hi: float,
) -> dict[str, Any]:
    return {
        "label": label,
        "group": group,
        "agent": agent,
        "tier": tier,
        "n": n,
        "mean": mean,
        "ci": ci,
        "solver_same_seeds": sol,
        "ratio": ratio,
        "ratio_lo": r_lo,
        "ratio_hi": r_hi,
        "post_expected": post,
        "post_expected_ratio": p_ratio,
        "post_expected_lo": p_lo,
        "post_expected_hi": p_hi,
    }


def _render_paired_md(rows: list[dict[str, Any]]) -> str:
    lines = [
        "| tier | run | n | score +/- 95% CI | solver, same seeds | **frontier / solver [95% CI]** | luck-adjusted score | **luck-adj. / solver's luck-adj. [95% CI]** |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        is_sol = r["agent"] == "solver"
        raw_s = (
            "-"
            if is_sol
            else f"{r['ratio']*100:.0f}% [{r['ratio_lo']*100:.0f}%, {r['ratio_hi']*100:.0f}%]"
        )
        la_s = (
            "-"
            if is_sol
            else f"**{r['post_expected_ratio']*100:.0f}% [{r['post_expected_lo']*100:.0f}%, {r['post_expected_hi']*100:.0f}%]**"
        )
        lines.append(
            f"| {r['tier']} | {r['label']} | {r['n']} | {r['mean']:.3f} +/- {r['ci']:.3f} | "
            f"{r['solver_same_seeds']:.3f} | {raw_s} | {r['post_expected']:.3f} | {la_s} |"
        )
    return "\n".join(lines) + "\n"


def _build_valid_fixture(root: Path, sha: str = "035105e9e131174a2a774bd4a58bd7693795d44b") -> None:
    pt_rows = [
        _paired_row_dict(
            label="OpenCode + gemini-4-carbon over MCP (judges' shape)",
            group="v1.4/opencode-gemini-4-carbon",
            agent="opencode:google/gemini-4-carbon",
            tier="hard",
            n=30,
            mean=0.322,
            ci=0.199,
            sol=0.499,
            ratio=0.65,
            r_lo=0.24,
            r_hi=0.98,
            post=0.360,
            p_ratio=0.72,
            p_lo=0.52,
            p_hi=0.91,
        ),
        _paired_row_dict(
            label="reference solver",
            group="v1.4/reference",
            agent="solver",
            tier="hard",
            n=30,
            mean=0.499,
            ci=0.119,
            sol=0.499,
            ratio=1.0,
            r_lo=float("nan"),
            r_hi=float("nan"),
            post=0.499,
            p_ratio=1.0,
            p_lo=float("nan"),
            p_hi=float("nan"),
        ),
    ]
    _write(
        root,
        "data/runs/committed/v1.4/paired_table_gemini.json",
        json.dumps(pt_rows, indent=2),
    )
    _write(
        root,
        "data/runs/committed/v1.4/paired_table_gemini.md",
        _render_paired_md(pt_rows),
    )

    pool_rows = [
        pt_rows[0],
        _paired_row_dict(
            label="OpenCode + gemini-4-carbon over MCP, pooled (primary + extension)",
            group="v1.4/opencode-gemini-4-carbon+ext",
            agent="opencode:google/gemini-4-carbon",
            tier="hard",
            n=32,
            mean=0.349,
            ci=0.190,
            sol=0.514,
            ratio=0.68,
            r_lo=0.32,
            r_hi=1.00,
            post=0.381,
            p_ratio=0.75,
            p_lo=0.56,
            p_hi=0.93,
        ),
        _paired_row_dict(
            label="reference solver",
            group="v1.4/reference",
            agent="solver",
            tier="hard",
            n=60,
            mean=0.498,
            ci=0.097,
            sol=0.498,
            ratio=1.0,
            r_lo=float("nan"),
            r_hi=float("nan"),
            post=0.521,
            p_ratio=1.0,
            p_lo=float("nan"),
            p_hi=float("nan"),
        ),
    ]
    _write(
        root,
        "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.json",
        json.dumps(pool_rows, indent=2),
    )
    _write(
        root,
        "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.md",
        _render_paired_md(pool_rows),
    )

    oracle_json = {
        "rows": [
            {
                "agent": "solver",
                "tier": "hard",
                "k2": {"mean": 0.533, "sd": 0.274, "p5": -0.211, "p50": 0.620, "p95": 0.745, "p_lt0": 0.105},
                "k3": {"mean": 0.547, "sd": 0.208, "p5": 0.047, "p50": 0.613, "p95": 0.723, "p_lt0": 0.015},
                "k10": {"mean": 0.569, "sd": 0.094, "p5": 0.393, "p50": 0.600, "p95": 0.678, "p_lt0": 0.0},
                "k20": {"mean": 0.568, "sd": 0.064, "p5": 0.454, "p50": 0.585, "p95": 0.656, "p_lt0": 0.0},
            },
            {
                "agent": "solver",
                "tier": "medium",
                "k10": {"mean": 0.623, "sd": 0.086, "p5": 0.469, "p50": 0.633, "p95": 0.742, "p_lt0": 0.0},
            },
        ]
    }
    _write(root, "results/oracle_range_v1.4.json", json.dumps(oracle_json, indent=2))
    _write(
        root,
        "results/oracle_range_v1.4.md",
        "\n".join(
            [
                "| agent | tier | k tasks | mean | sd | p5 | p50 | p95 | P(mean<0) |",
                "|---|---|---|---|---|---|---|---|---|",
                "| solver | hard | 2 | +0.533 | 0.274 | -0.211 | +0.620 | +0.745 | 10.5% |",
                "| solver | hard | 3 | +0.547 | 0.208 | +0.047 | +0.613 | +0.723 | 1.5% |",
                "| solver | hard | 10 | +0.569 | 0.094 | +0.393 | +0.600 | +0.678 | 0.0% |",
                "| solver | hard | 20 | +0.568 | 0.064 | +0.454 | +0.585 | +0.656 | 0.0% |",
                "| solver | medium | 10 | +0.623 | 0.086 | +0.469 | +0.633 | +0.742 | 0.0% |",
                "",
            ]
        ),
    )

    for stem, ag, tr, mn, sd, p5, med, p95 in (
        ("solver_easy_judge40", "solver", "easy", 0.774, 0.020, 0.74, 0.775, 0.80),
        ("solver_medium_judge40", "solver", "medium", 0.630, 0.040, 0.56, 0.635, 0.69),
        ("solver_hard_judge40", "solver", "hard", 0.567, 0.050, 0.49, 0.572, 0.64),
        ("guess_day1_easy_judge40", "guess_day1", "easy", -0.839, 0.090, -0.95, -0.850, -0.70),
        ("guess_day1_medium_judge40", "guess_day1", "medium", -0.906, 0.064, -1.00, -0.900, -0.80),
        ("guess_day1_hard_judge40", "guess_day1", "hard", -0.953, 0.045, -1.00, -0.950, -0.85),
    ):
        _write(
            root,
            f"results/solver_range/{stem}.json",
            json.dumps(
                {
                    "agent": ag,
                    "tier": tr,
                    "builds": 300,
                    "mean": mn,
                    "sd": sd,
                    "p": {"0.05": p5, "0.5": med, "0.95": p95},
                },
                indent=2,
            ),
        )
        _write(
            root,
            f"results/solver_range/{stem}.md",
            "\n".join(
                [
                    "300 simulated builds",
                    "",
                    "| statistic | mean |",
                    "|---|---:|",
                    f"| mean over builds | {mn:+.3f} |",
                    f"| standard deviation over builds | {sd:.3f} |",
                    f"| median | {med:+.3f} |",
                    f"| **90% range (5th-95th percentile)** | **[{p5:+.2f}, {p95:+.2f}]** |",
                    "",
                ]
            ),
        )

    ac_rows: list[dict[str, Any]] = []
    ac_md_lines = [
        "| tier | probe | kind | n | mean +/- 95% CI | max | episodes > 0 | blocked |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for tier_name in ("easy", "medium", "hard"):
        for idx in range(33):
            is_ref = idx == 0
            probe_name = "solver" if is_ref else f"probe_{idx:02d}"
            kind = "reference" if is_ref else "attack"
            mn_v = 0.545 if is_ref else 0.000
            ci_v = 0.098 if is_ref else 0.000
            mx_v = 0.840 if is_ref else 0.000
            pos_v = 37 if is_ref else 0
            ac_rows.append(
                {
                    "tier": tier_name,
                    "probe": probe_name,
                    "kind": kind,
                    "n": 40,
                    "mean": mn_v,
                    "ci95": ci_v,
                    "max": mx_v,
                    "positive": pos_v,
                    "blocked": True,
                }
            )
            blk_s = "-" if is_ref else "yes"
            ac_md_lines.append(
                f"| {tier_name} | `{probe_name}` | {kind} | 40 | {mn_v:+.3f} +/- {ci_v:.3f} | {mx_v:+.3f} | {pos_v} | {blk_s} |"
            )

    harbor_items = [
        {"kind": "trial", "consistent": True, "trial": f"t{i}"} for i in range(80)
    ] + [{"kind": "job", "consistent": True, "trial": f"j{i}"} for i in range(18)]

    exp_json = {
        "all_blocked": True,
        "rows": ac_rows,
        "replay_counts": {
            "replayed": 1051,
            "n": 1061,
            "consistent": 1051,
            "steps": 53889,
            "step_mismatches": 0,
        },
        "replay": [
            {"file": "a.jsonl", "replayed": 1051, "n": 1061, "consistent": 1051, "steps": 53889}
        ],
        "harbor": harbor_items,
    }
    _write(root, "results/anticheat/exploits.json", json.dumps(exp_json, indent=2))
    ac_md_lines.extend(
        [
            "",
            "**Replay coverage: 1051 of 1061 committed episodes re-played, 1051 consistent; 53889 recorded tool results compared step by step, 0 differ.**",
            "",
            "**80 of 80 trials and 18 of 18 job summaries consistent.**",
            "",
        ]
    )
    _write(root, "results/anticheat/exploits.md", "\n".join(ac_md_lines))

    fa_json = {
        "summary": {
            "opencode": {"score": 0.322, "canaries": 8.5, "accuse_day": 13.2, "wrong": 4, "abstain": 1},
            "solver": {"score": 0.499, "canaries": 14.1, "accuse_day": 10.6, "wrong": 1, "abstain": 0},
            "gap": {
                "penalty": 3.39,
                "abstain": 0.62,
                "leak": 1.75,
                "restrict": 0.12,
                "canary": -1.69,
                "la_gap": 4.19,
                "luck": 1.11,
                "raw_gap": 5.30,
            },
        }
    }
    _write(root, "results/failure_analysis_v1.4.json", json.dumps(fa_json, indent=2))
    _write(
        root,
        "docs/reports/failure_analysis_v1.4.md",
        "\n".join(
            [
                f"{H} Failure analysis",
                "",
                "| idx | mistake | V lost, 30 seeds | per episode |",
                "|---|---|---|---|",
                "| 1 | Accusing on unisolated evidence | +3.39 | +0.113 |",
                "| 2 | Never reaching accusable posterior | +0.62 | +0.021 |",
                "| 3 | Extra leak damage | +1.75 | +0.058 |",
                "| 4 | Restriction costs | +0.12 | +0.004 |",
                "| 5 | Canary costs saved | -1.69 | -0.056 |",
                "| | **luck-adjusted gap** | **+4.19** | +0.140 |",
                "| | bad luck | +1.11 | +0.037 |",
                "| | **raw gap** | **+5.30** | +0.177 |",
                "",
            ]
        ),
    )

    ladder_json = {
        "episodes": 587,
        "ledger": {"calls": 36164, "cost_usd_priced": 298.75},
        "rows": [
            {
                "tier": "medium",
                "model": "gemini-4-carbon",
                "level": "high",
                "n": 287,
                "mean": 0.639,
                "ci": 0.160,
                "solver_same_seeds": 0.730,
                "ratio": 0.88,
                "ratio_lo": 0.72,
                "ratio_hi": 0.99,
                "luck_adj_ratio": 0.66,
                "luck_adj_lo": 0.24,
                "luck_adj_hi": 0.97,
            },
            {
                "tier": "hard",
                "model": "gemini-4-carbon",
                "level": "high",
                "n": 300,
                "mean": 0.608,
                "ci": 0.100,
                "solver_same_seeds": 0.576,
                "ratio": 1.06,
                "ratio_lo": 0.94,
                "ratio_hi": 1.26,
                "luck_adj_ratio": 0.80,
                "luck_adj_lo": 0.45,
                "luck_adj_hi": 1.11,
            },
        ],
    }
    _write(root, "results/gemini/ladder.json", json.dumps(ladder_json, indent=2))
    _write(
        root,
        "results/gemini/ladder.md",
        "\n".join(
            [
                f"{H} Gemini Ladder",
                "",
                "587 valid Gemini episodes in 2 cells; ledger: 36164 calls, 618 run ids, list price $298.75.",
                "",
                f"{H2} medium",
                "",
                "| model | thinking | n | score +/- 95% CI | solver, same seeds | **score / solver [95% CI]** | luck-adj. / solver |",
                "|---|---|---|---|---|---|---|",
                "| gemini-4-carbon | high | 287 | +0.639 +/- 0.16 | +0.730 | **88% [72%, 99%]** | 66% [24%, 97%] |",
                "",
                f"{H2} hard",
                "",
                "| model | thinking | n | score +/- 95% CI | solver, same seeds | **score / solver [95% CI]** | luck-adj. / solver |",
                "|---|---|---|---|---|---|---|",
                "| gemini-4-carbon | high | 300 | +0.608 +/- 0.10 | +0.576 | **106% [94%, 126%]** | 80% [45%, 111%] |",
                "",
            ]
        ),
    )

    swarm_json = {
        "counts": {"attempts": 100, "exploits": 0, "tool_calls": 4325},
        "waves": [
            {"wave": "wave 1", "finished": 35},
            {"wave": "blackbox", "finished": 16},
            {"wave": "wave 2", "finished": 24},
            {"wave": "wave 2b", "finished": 16},
        ],
    }
    _write(root, "results/gemini/swarm.json", json.dumps(swarm_json, indent=2))
    _write(
        root,
        "results/gemini/swarm.md",
        "\n".join(
            [
                f"{H} Swarm",
                "- Verified exploits: **0**",
                "- Tool calls executed: 4325",
                "",
                "| wave | finished | tool calls | verified exploits |",
                "|---|---|---|---|",
                "| **all real waves** | 91 | 4325 | **0** |",
                "",
            ]
        ),
    )

    _write(
        root,
        "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/meta.json",
        json.dumps({"git_sha": sha, "git_shas": [sha]}, indent=2),
    )
    _write(
        root,
        "results/judge_table.md",
        "\n".join(
            [
                f"{H} Canary judge table",
                f"- git: `{sha[:12]}`",
                "",
                "| agent | kind | n | score +/- 95% CI | note |",
                "|---|---|---|---|---|",
                f"| opencode | reported | 30 | +0.322 +/- 0.199 | replayed, NON-judge seeds, 30 seeds, git {sha[:7]} (dir) |",
                "| grok | reported | 5 | +0.567 +/- 0.286 | replayed, judge seeds, 5 seeds, git unknown (dir) |",
                "",
            ]
        ),
    )

    _write(
        root,
        "README.md",
        "\n".join(
            [
                f"{H} Canary",
                "",
                f"{H2} Tiebreak: a small model trained on Canary experience (honest result)",
                "",
                "| model | held-out score +/- 95% CI | n |",
                "|---|---:|---:|",
                "| base (untrained) | 0.000 (it cannot play: 3% valid tool calls) | 36 |",
                f"| v2 (SFT on solver play) | -0.457 {PLUS_MINUS} 0.086 | 172 |",
                f"| v3-4k (GRPO) | -0.147 {PLUS_MINUS} 0.063 | 180 |",
                f"| v3-8k seed 2 (GRPO) | -0.050 {PLUS_MINUS} 0.049 | 90 |",
                "",
                f"- What was learned: (v3-4k vs v2: +0.310 {PLUS_MINUS} 0.107, two-sample).",
                "",
            ]
        ),
    )

    ws4_v3_md = "\n".join(
        [
            "| model | tier | n | score +/- 95% CI | valid calls | delta vs v2 |",
            "|---|---|---|---|---|---|",
            "| base | all | 36 | 0.000 +/- 0.000 | 0.03 | +0.457 +/- 0.086 |",
            "| v2 | all | 172 | -0.457 +/- 0.086 | 0.92 | - |",
            "| v3-4k-s0 | all | 180 | -0.147 +/- 0.063 | 1.00 | +0.310 +/- 0.107 |",
            "| v3-8k-s2 | easy | 30 | -0.067 +/- 0.091 | 0.92 | +0.665 +/- 0.184 |",
            "| v3-8k-s2 | medium | 30 | 0.000 +/- 0.000 | 1.00 | +0.039 +/- 0.081 |",
            "| v3-8k-s2 | hard | 30 | -0.083 +/- 0.116 | 0.96 | +0.514 +/- 0.173 |",
            "| v3-8k-s2 | all | 90 | -0.050 +/- 0.049 | 0.96 | +0.408 +/- 0.099 |",
            "",
        ]
    )
    _write(root, "fr8/analysis/out/ws4_table_v3.md", ws4_v3_md)

    ws4_8k_md = "\n".join(
        [
            "| model | tier | n | score +/- 95% CI | valid calls | delta vs v2 |",
            "|---|---|---|---|---|---|",
            "| v2 | all | 172 | -0.457 +/- 0.086 | 0.92 | - |",
            "| v3_4k_s0 | all | 180 | -0.147 +/- 0.063 | 1.00 | +0.310 +/- 0.107 |",
            "| v3_8k_s2_H100_693st | easy | 30 | -0.067 +/- 0.091 | 0.92 | +0.665 +/- 0.184 |",
            "| v3_8k_s2_H100_693st | medium | 30 | 0.000 +/- 0.000 | 1.00 | +0.039 +/- 0.081 |",
            "| v3_8k_s2_H100_693st | hard | 30 | -0.083 +/- 0.116 | 0.96 | +0.514 +/- 0.173 |",
            "| v3_8k_s2_H100_693st | all | 90 | -0.050 +/- 0.049 | 0.96 | +0.408 +/- 0.099 |",
            "",
        ]
    )
    _write(root, "fr8/analysis/out/ws4_table_8k_s1s2.md", ws4_8k_md)

    _write(
        root,
        "data/fr8/verda/h100spot-dbd0/runs/v3-verda-8k-s2/summary.json",
        json.dumps(
            {
                "by_tier": {
                    "easy": {"n": 30, "mean_score": -0.0667, "ci95": 0.0908},
                    "medium": {"n": 30, "mean_score": 0.0, "ci95": 0.0},
                    "hard": {"n": 30, "mean_score": -0.0827, "ci95": 0.1163},
                    "all": {"n": 90, "mean_score": -0.0498, "ci95": 0.0492},
                }
            },
            indent=2,
        ),
    )

    _write(
        root,
        "results/fresh_clone/macos_justSilas_09e7363.steps.txt",
        "clone exit=0 seconds=8\nsetup exit=0 seconds=2\nreproduce exit=0 seconds=52\naccept exit=0 seconds=142\ntest exit=0 seconds=905\n",
    )
    _write(
        root,
        "results/fresh_clone/linux_x86_64_justSilas_2b301cea.steps.txt",
        "clone exit=0 seconds=5\nreproduce_fast exit=0 seconds=83\nreproduce exit=0 seconds=159\naudit exit=0 seconds=202\ntest exit=0 seconds=263\n",
    )
    _write(
        root,
        "results/fresh_clone/linux_x86_64_afterquery_final_1bc3e281.steps.txt",
        "clone exit=0 seconds=3\nreproduce_table exit=0 seconds=27\nreproduce exit=0 seconds=118\naudit exit=0 seconds=4\ntest_core exit=0 seconds=175\n",
    )
    _write(
        root,
        "results/fresh_clone/linux_x86_64_afterquery_final_1bc3e281.log.txt",
        "\n".join(
            [
                "commit: 1bc3e281dbfaa494a11e783d0c98369b41b2f675",
                "=== clone: exit 0, 3 s",
                "=== reproduce_table: exit 0, 27 s",
                "=== reproduce: exit 0, 118 s",
                "SUMMARY: 3 PASS, 1 WARN, 0 FAIL",
                "=== audit: exit 0, 4 s",
                "100 passed in 174.42s",
                "=== test_core: exit 0, 175 s",
                "",
            ]
        ),
    )
    _write(
        root,
        "results/fresh_clone/README.md",
        "\n".join(
            [
                f"{H} Fresh-clone checks",
                "macOS 09e7363: 8 s, 2 s, 52 s, 142 s, 905 s, 967 passed, 7 skipped",
                "Linux 2b301cea: 5 s, 83 s, 159 s, 202 s, 263 s, 115 passed",
                "Linux afterquery-final 1bc3e281: 3 s, 27 s, 118 s, 4 s, 175 s, 100 passed",
                "",
            ]
        ),
    )

    _write(
        root,
        "Makefile",
        ".PHONY: reproduce anticheat-verify lab-replay hunt\nreproduce:\n\t@true\nanticheat-verify:\n\t@true\nlab-replay:\n\t@true\nhunt:\n\t@true\n",
    )
    _write(
        root,
        "scripts/paired_gemini.py",
        "import argparse\nap = argparse.ArgumentParser()\nap.add_argument('--version')\nap.add_argument('--seeds')\n",
    )

    idx_lines = [
        f"{H} Provenance Index",
        "",
        "Covers Frontier Gap, Causal Failure Analysis, Reward Integrity, Harbor Oracle, Craft, WS4 Tiebreak, Gemini Lab, and number_audit closures.",
        f"Tag `afterquery-final` -> `1bc3e281`. Commits: `8fd4dec`, `671ed96`, `09e7363`, `2b301cea`, `f9fb7a4a`, `dcd8c372`, `cf394894`, `bd535a45`, `edd4fe6d`, `8522baea`, `ca90d0b2`, `92708834`, `1bc3e281`, `58716742`.",
        "",
        "| Metric | Verified Value | Source Artifact | Producing Commit | Recompute Command |",
        "|---|---|---|---|---|",
        f"| OpenCode hard | +0.322 +/- 0.199; 65%; 72%; n=30 | `data/runs/committed/v1.4/paired_table_gemini.json` | `{sha[:8]}` | `uv run python scripts/paired_gemini.py --version v1.4 --seeds 0-29` |",
        f"| Pooled hard | +0.349 +/- 0.190; 68%; 75%; n=32 | `data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.json` | `{sha[:8]}` | `make reproduce` |",
        f"| Solver pooled | +0.498 +/- 0.097; n=60 | `data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.json` | `{sha[:8]}` | `make reproduce` |",
        f"| Failure total | +5.30 = +4.19 + +1.11 | `results/failure_analysis_v1.4.json` | `{sha[:8]}` | `make reproduce` |",
        f"| Failure penalty | +3.39; +0.62; +1.75; -1.69 | `results/failure_analysis_v1.4.json` | `{sha[:8]}` | `make reproduce` |",
        f"| Anticheat rows | 99; 1051; 1061; 53889 | `results/anticheat/exploits.json` | `{sha[:8]}` | `make anticheat-verify` |",
        f"| Harbor trials | 80; 18 | `results/anticheat/exploits.json` | `{sha[:8]}` | `make anticheat-verify` |",
        f"| Oracle k10 | +0.569; 0.094 | `results/oracle_range_v1.4.json` | `{sha[:8]}` | `make reproduce` |",
        f"| Solver spread | +0.567; 300 | `results/solver_range/solver_hard_judge40.json` | `{sha[:8]}` | `make reproduce` |",
        f"| Fresh clone macOS | 8 s, 2 s, 52 s, 142 s, 905 s (967) | `results/fresh_clone/README.md`, `results/fresh_clone/macos_justSilas_09e7363.steps.txt` | `{sha[:8]}` | `make reproduce` |",
        f"| Fresh clone Linux 2b301cea | 5 s, 83 s, 159 s, 202 s, 263 s (115) | `results/fresh_clone/README.md`, `results/fresh_clone/linux_x86_64_justSilas_2b301cea.steps.txt` | `{sha[:8]}` | `make reproduce` |",
        f"| Fresh clone Linux 1bc3e281 | 3 s, 27 s, 118 s, 4 s, 175 s (100) | `results/fresh_clone/README.md`, `results/fresh_clone/linux_x86_64_afterquery_final_1bc3e281.steps.txt` | `{sha[:8]}` | `make reproduce` |",
        f"| WS4 v3-8k | -0.050 +/- 0.049; n=90 | `fr8/analysis/out/ws4_table_v3.md` | `{sha[:8]}` | `make reproduce` |",
        f"| Gemini ladder | 587; 36164 | `results/gemini/ladder.json` | `{sha[:8]}` | `make lab-replay` |",
        f"| Gemini swarm | 91; 4325; 0 | `results/gemini/swarm.json` | `{sha[:8]}` | `make hunt` |",
        "",
        "| Item | Finding | Closing Commit |",
        "|---|---|---|",
    ]
    for m_num in range(1, 11):
        idx_lines.append(f"| M{m_num} | closed | `{sha[:8]}` |")
    _write(root, "docs/NUMBER-PROVENANCE-INDEX.md", "\n".join(idx_lines) + "\n")


def test_owned_files_exist_and_nonempty() -> None:
    for p in (SCRIPT_PATH, DOC_PATH, SELF_PATH):
        assert p.is_file(), f"missing owned file {p}"
        assert p.stat().st_size > 0, f"empty owned file {p}"


def test_no_hash_comments_in_python_files() -> None:
    for py_path in (SCRIPT_PATH, SELF_PATH):
        src = py_path.read_text(encoding="utf-8")
        assert H not in src, f"forbidden '{H}' character found in {py_path.name}"
        comment_toks = [
            tok
            for tok in tokenize.generate_tokens(io.StringIO(src).readline)
            if tok.type == tokenize.COMMENT
        ]
        assert comment_toks == [], f"tokenize.COMMENT found in {py_path.name}: {comment_toks}"


def test_no_em_or_en_dashes_and_pure_ascii() -> None:
    co_auth_marker = "Co-" + "Authored-" + "By"
    for p in (SCRIPT_PATH, DOC_PATH, SELF_PATH):
        txt = p.read_text(encoding="utf-8")
        assert EM_DASH not in txt, f"em dash found in {p.name}"
        assert EN_DASH not in txt, f"en dash found in {p.name}"
        assert co_auth_marker not in txt, f"co-author trailer found in {p.name}"
        assert all(ord(ch) < 128 for ch in txt), f"non-ASCII character found in {p.name}"


def test_live_repo_passes_all_four_checks_under_two_seconds() -> None:
    t0 = time.monotonic()
    results = van.verify_artifact_numbers(ROOT)
    elapsed = time.monotonic() - t0

    assert elapsed < 2.0, f"expected runtime < 2.0s, took {elapsed:.3f}s"
    assert [r.name for r in results] == list(van.CHECK_NAMES)
    for r in results:
        assert r.status == "PASS", f"{r.name} failed: {r.details}"
        assert r.details == []


def test_cli_json_and_text_modes_on_live_repo(capsys: pytest.CaptureFixture[str]) -> None:
    rc_json = van.main(["--root", str(ROOT), "--json"])
    out_json = capsys.readouterr().out
    assert rc_json == 0
    payload = json.loads(out_json)
    assert payload["passed"] is True
    assert payload["elapsed_s"] < 2.0
    assert len(payload["results"]) == 4

    rc_txt = van.main(["--root", str(ROOT)])
    out_txt = capsys.readouterr().out
    assert rc_txt == 0
    assert "SUMMARY: 4 PASS, 0 WARN, 0 FAIL" in out_txt

    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--root", str(ROOT), "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert proc.returncode == 0
    sub_payload = json.loads(proc.stdout)
    assert sub_payload["passed"] is True


def test_synthetic_fixture_passes_gitless_zip_mode(opencode_tmp: Path) -> None:
    _build_valid_fixture(opencode_tmp)
    results = van.verify_artifact_numbers(opencode_tmp)
    assert all(r.status == "PASS" for r in results), [r.details for r in results]
    git_res = results[1]
    assert "gitless zip fallback" in git_res.summary


def test_synthetic_fixture_with_real_git_and_tag(
    opencode_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    git_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    subprocess.run(["git", "init", "-q"], cwd=opencode_tmp, env=git_env, check=True)
    _write(opencode_tmp, "seed.txt", "init\n")
    subprocess.run(["git", "add", "seed.txt"], cwd=opencode_tmp, env=git_env, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=opencode_tmp, env=git_env, check=True)
    full_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=opencode_tmp,
        env=git_env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "tag", "afterquery-final", full_sha],
        cwd=opencode_tmp,
        env=git_env,
        check=True,
    )

    _build_valid_fixture(opencode_tmp, sha=full_sha)
    idx_file = opencode_tmp / "docs" / "NUMBER-PROVENANCE-INDEX.md"
    idx_txt = idx_file.read_text(encoding="utf-8")
    for old_s in (
        "8fd4dec",
        "671ed96",
        "09e7363",
        "2b301cea",
        "f9fb7a4a",
        "dcd8c372",
        "cf394894",
        "bd535a45",
        "edd4fe6d",
        "8522baea",
        "ca90d0b2",
        "92708834",
        "1bc3e281",
        "58716742",
    ):
        idx_txt = idx_txt.replace(f"`{old_s}`", f"`{full_sha[:8]}`")
    idx_file.write_text(idx_txt, encoding="utf-8")

    monkeypatch.setattr(van, "KEY_CITED_COMMITS", (full_sha[:8],))
    monkeypatch.setattr(van, "AUDIT_CLOSURE_COMMITS", (full_sha[:8],))
    monkeypatch.setattr(van, "TAG_AFTERQUERY_PREFIX", full_sha[:8])

    res_git = van.check_git_provenance(opencode_tmp)
    assert res_git.status == "PASS", res_git.details
    assert "afterquery-final ->" in res_git.summary

    res_idx = van.check_provenance_index(opencode_tmp)
    assert res_idx.status == "PASS", res_idx.details


def test_tamper_paired_table_gemini_ratio_and_mean(opencode_tmp: Path) -> None:
    _build_valid_fixture(opencode_tmp)
    md_path = opencode_tmp / "data/runs/committed/v1.4/paired_table_gemini.md"
    orig = md_path.read_text(encoding="utf-8")
    md_path.write_text(orig.replace("65% [24%, 98%]", "85% [24%, 98%]"), encoding="utf-8")
    res = van.check_companion_parity(opencode_tmp)
    assert res.status == "FAIL"
    assert any("raw ratio" in d for d in res.details)

    md_path.write_text(orig.replace("0.322 +/- 0.199", "0.410 +/- 0.199"), encoding="utf-8")
    res2 = van.check_companion_parity(opencode_tmp)
    assert res2.status == "FAIL"
    assert any("score/CI" in d for d in res2.details)


def test_tamper_pooled_ext_row(opencode_tmp: Path) -> None:
    _build_valid_fixture(opencode_tmp)
    md_path = opencode_tmp / "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.md"
    orig = md_path.read_text(encoding="utf-8")
    md_path.write_text(orig.replace("75% [56%, 93%]", "70% [56%, 93%]"), encoding="utf-8")
    res = van.check_companion_parity(opencode_tmp)
    assert res.status == "FAIL"
    assert any("pooled" in d or "luck-adj ratio" in d for d in res.details)


def test_tamper_oracle_range_and_solver_range(opencode_tmp: Path) -> None:
    _build_valid_fixture(opencode_tmp)
    or_md = opencode_tmp / "results/oracle_range_v1.4.md"
    orig_or = or_md.read_text(encoding="utf-8")
    or_md.write_text(orig_or.replace("+0.569", "+0.610"), encoding="utf-8")
    res = van.check_companion_parity(opencode_tmp)
    assert res.status == "FAIL"
    assert any("oracle_range_v1.4.md" in d for d in res.details)
    or_md.write_text(orig_or, encoding="utf-8")

    sr_json = opencode_tmp / "results/solver_range/solver_hard_judge40.json"
    obj = json.loads(sr_json.read_text(encoding="utf-8"))
    obj["builds"] = 200
    sr_json.write_text(json.dumps(obj), encoding="utf-8")
    res2 = van.check_companion_parity(opencode_tmp)
    assert res2.status == "FAIL"
    assert any("builds=300" in d for d in res2.details)


def test_tamper_anticheat_replay_and_harbor_counts(opencode_tmp: Path) -> None:
    _build_valid_fixture(opencode_tmp)
    md_path = opencode_tmp / "results/anticheat/exploits.md"
    orig = md_path.read_text(encoding="utf-8")

    md_path.write_text(orig.replace("53889", "53999"), encoding="utf-8")
    res1 = van.check_companion_parity(opencode_tmp)
    assert res1.status == "FAIL"
    assert any("replay summary" in d for d in res1.details)

    md_path.write_text(orig.replace("80 of 80 trials", "79 of 80 trials"), encoding="utf-8")
    res2 = van.check_companion_parity(opencode_tmp)
    assert res2.status == "FAIL"
    assert any("Harbor summary" in d for d in res2.details)


def test_tamper_failure_analysis_components(opencode_tmp: Path) -> None:
    _build_valid_fixture(opencode_tmp)
    fa_md = opencode_tmp / "docs/reports/failure_analysis_v1.4.md"
    orig = fa_md.read_text(encoding="utf-8")
    fa_md.write_text(orig.replace("+3.39", "+3.89"), encoding="utf-8")
    res = van.check_companion_parity(opencode_tmp)
    assert res.status == "FAIL"
    assert any("row1" in d for d in res.details)


def test_tamper_gemini_ladder_and_swarm(opencode_tmp: Path) -> None:
    _build_valid_fixture(opencode_tmp)
    lad_md = opencode_tmp / "results/gemini/ladder.md"
    orig_lad = lad_md.read_text(encoding="utf-8")
    lad_md.write_text(orig_lad.replace("587 valid Gemini episodes", "500 valid Gemini episodes"), encoding="utf-8")
    res1 = van.check_companion_parity(opencode_tmp)
    assert res1.status == "FAIL"
    assert any("ladder.md" in d for d in res1.details)
    lad_md.write_text(orig_lad, encoding="utf-8")

    sw_md = opencode_tmp / "results/gemini/swarm.md"
    orig_sw = sw_md.read_text(encoding="utf-8")
    sw_md.write_text(orig_sw.replace("Verified exploits: **0**", "Verified exploits: **1**"), encoding="utf-8")
    res2 = van.check_companion_parity(opencode_tmp)
    assert res2.status == "FAIL"
    assert any("swarm.md" in d for d in res2.details)


def test_tamper_git_sha_zip_and_git_modes(
    opencode_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _build_valid_fixture(opencode_tmp)
    meta_p = opencode_tmp / "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/meta.json"
    meta_p.write_text(json.dumps({"git_sha": "not-a-valid-hex-sha"}), encoding="utf-8")
    res_zip = van.check_git_provenance(opencode_tmp)
    assert res_zip.status == "FAIL"
    assert any("invalid git_sha" in d for d in res_zip.details)

    git_dir = opencode_tmp / "git_repo"
    git_dir.mkdir()
    git_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    subprocess.run(["git", "init", "-q"], cwd=git_dir, env=git_env, check=True)
    _write(git_dir, "f.txt", "x\n")
    subprocess.run(["git", "add", "f.txt"], cwd=git_dir, env=git_env, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "c1"], cwd=git_dir, env=git_env, check=True)

    _build_valid_fixture(git_dir, sha="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef")
    monkeypatch.setattr(van, "KEY_CITED_COMMITS", ("deadbeef",))
    res_git = van.check_git_provenance(git_dir)
    assert res_git.status == "FAIL"
    assert any("unresolved git commit" in d for d in res_git.details)
    assert any("missing git tag 'afterquery-final'" in d for d in res_git.details)
    assert van.main(["--root", str(git_dir)]) == 1


def test_tamper_ws4_tiebreak_readme_and_summary(opencode_tmp: Path) -> None:
    _build_valid_fixture(opencode_tmp)
    readme_p = opencode_tmp / "README.md"
    orig_rm = readme_p.read_text(encoding="utf-8")
    readme_p.write_text(orig_rm.replace("-0.147", "-0.247"), encoding="utf-8")
    res1 = van.check_ws4_tiebreak(opencode_tmp)
    assert res1.status == "FAIL"
    assert any("v3_4k" in d for d in res1.details)
    readme_p.write_text(orig_rm, encoding="utf-8")

    sum_p = opencode_tmp / "data/fr8/verda/h100spot-dbd0/runs/v3-verda-8k-s2/summary.json"
    sobj = json.loads(sum_p.read_text(encoding="utf-8"))
    sobj["by_tier"]["all"]["mean_score"] = -0.222
    sum_p.write_text(json.dumps(sobj), encoding="utf-8")
    res2 = van.check_ws4_tiebreak(opencode_tmp)
    assert res2.status == "FAIL"
    assert any("summary.json" in d for d in res2.details)


def test_tamper_provenance_index_paths_numbers_commands_and_dashes(opencode_tmp: Path) -> None:
    _build_valid_fixture(opencode_tmp)
    idx_p = opencode_tmp / "docs/NUMBER-PROVENANCE-INDEX.md"
    orig = idx_p.read_text(encoding="utf-8")

    idx_p.write_text(orig + "\nBroken ref: `results/nonexistent_artifact.json`\n", encoding="utf-8")
    r_path = van.check_provenance_index(opencode_tmp)
    assert r_path.status == "FAIL"
    assert any("nonexistent_artifact.json" in d for d in r_path.details)

    idx_p.write_text(orig.replace("+0.322 +/- 0.199", "+0.888 +/- 0.199"), encoding="utf-8")
    r_num = van.check_provenance_index(opencode_tmp)
    assert r_num.status == "FAIL"
    assert any("+0.888" in d or "0.888" in d for d in r_num.details)

    idx_p.write_text(
        orig.replace("--version v1.4", "--version v1.4 --bogus-nonexistent-flag"),
        encoding="utf-8",
    )
    r_flag = van.check_provenance_index(opencode_tmp)
    assert r_flag.status == "FAIL"
    assert any("--bogus-nonexistent-flag" in d for d in r_flag.details)

    idx_p.write_text(orig.replace("| M7 |", "| X7 |") + f"\nBad dash {EM_DASH}\n", encoding="utf-8")
    r_hyg = van.check_provenance_index(opencode_tmp)
    assert r_hyg.status == "FAIL"
    assert any("M7" in d for d in r_hyg.details)
    assert any("dash" in d for d in r_hyg.details)


def test_live_repo_in_gitless_zip_view(opencode_tmp: Path) -> None:
    zip_root = opencode_tmp / "zip_view"
    zip_root.mkdir()
    for entry in ROOT.iterdir():
        if entry.name == ".git":
            continue
        (zip_root / entry.name).symlink_to(entry)
    assert not (zip_root / ".git").exists()

    results = van.verify_artifact_numbers(zip_root)
    assert all(r.status == "PASS" for r in results), [r.details for r in results]
    assert "gitless zip fallback" in results[1].summary


def test_tamper_afterquery_final_tag_wrong_target(
    opencode_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    git_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    subprocess.run(["git", "init", "-q"], cwd=opencode_tmp, env=git_env, check=True)
    _write(opencode_tmp, "a.txt", "1\n")
    subprocess.run(["git", "add", "a.txt"], cwd=opencode_tmp, env=git_env, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "c1"], cwd=opencode_tmp, env=git_env, check=True)
    sha1 = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=opencode_tmp, env=git_env, capture_output=True, text=True, check=True
    ).stdout.strip()
    _write(opencode_tmp, "a.txt", "2\n")
    subprocess.run(["git", "add", "a.txt"], cwd=opencode_tmp, env=git_env, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "c2"], cwd=opencode_tmp, env=git_env, check=True)
    sha2 = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=opencode_tmp, env=git_env, capture_output=True, text=True, check=True
    ).stdout.strip()
    assert sha1[:8] != sha2[:8]
    subprocess.run(["git", "tag", "afterquery-final", sha2], cwd=opencode_tmp, env=git_env, check=True)

    _build_valid_fixture(opencode_tmp, sha=sha1)
    monkeypatch.setattr(van, "KEY_CITED_COMMITS", (sha1[:8],))
    monkeypatch.setattr(van, "TAG_AFTERQUERY_PREFIX", sha1[:8])

    res = van.check_git_provenance(opencode_tmp)
    assert res.status == "FAIL"
    assert any("afterquery-final" in d and "points to" in d for d in res.details)


def test_tamper_judge_table_header_and_row_shas(opencode_tmp: Path) -> None:
    _build_valid_fixture(opencode_tmp)
    jt_p = opencode_tmp / "results/judge_table.md"
    orig = jt_p.read_text(encoding="utf-8")

    jt_p.write_text(orig.replace("- git: `", "- git: `xyz_bad_"), encoding="utf-8")
    res1 = van.check_git_provenance(opencode_tmp)
    assert res1.status == "FAIL"
    assert any("invalid header git SHA" in d for d in res1.details)

    jt_p.write_text(orig.replace(", git ", ", git zzzzzzz_"), encoding="utf-8")
    res2 = van.check_git_provenance(opencode_tmp)
    assert res2.status == "FAIL"
    assert any("invalid row git SHA" in d for d in res2.details)


def test_tamper_ws4_delta_and_8k_table(opencode_tmp: Path) -> None:
    _build_valid_fixture(opencode_tmp)
    rm_p = opencode_tmp / "README.md"
    orig_rm = rm_p.read_text(encoding="utf-8")
    rm_p.write_text(orig_rm.replace("+0.310", "+0.410"), encoding="utf-8")
    res1 = van.check_ws4_tiebreak(opencode_tmp)
    assert res1.status == "FAIL"
    assert any("v3-4k vs v2" in d for d in res1.details)
    rm_p.write_text(orig_rm, encoding="utf-8")

    t8_p = opencode_tmp / "fr8/analysis/out/ws4_table_8k_s1s2.md"
    orig_t8 = t8_p.read_text(encoding="utf-8")
    t8_p.write_text(orig_t8.replace("| v3_8k_s2_H100_693st | all | 90 | -0.050", "| v3_8k_s2_H100_693st | all | 90 | -0.095"), encoding="utf-8")
    res2 = van.check_ws4_tiebreak(opencode_tmp)
    assert res2.status == "FAIL"
    assert any("ws4_table_8k_s1s2.md" in d for d in res2.details)


def test_tamper_anticheat_row_count_and_failure_json_sum(opencode_tmp: Path) -> None:
    _build_valid_fixture(opencode_tmp)
    exp_p = opencode_tmp / "results/anticheat/exploits.json"
    orig_exp = exp_p.read_text(encoding="utf-8")
    obj = json.loads(orig_exp)
    obj["rows"] = obj["rows"][:-1]
    exp_p.write_text(json.dumps(obj), encoding="utf-8")
    res1 = van.check_companion_parity(opencode_tmp)
    assert res1.status == "FAIL"
    assert any("expected 99 anti-cheat rows" in d for d in res1.details)
    exp_p.write_text(orig_exp, encoding="utf-8")

    fa_p = opencode_tmp / "results/failure_analysis_v1.4.json"
    fa_obj = json.loads(fa_p.read_text(encoding="utf-8"))
    fa_obj["summary"]["gap"]["penalty"] = 2.00
    fa_p.write_text(json.dumps(fa_obj), encoding="utf-8")
    res2 = van.check_companion_parity(opencode_tmp)
    assert res2.status == "FAIL"
    assert any("sum of 5 mistake components" in d for d in res2.details)


def test_fresh_clone_afterquery_final_1bc3e281_grounded_and_tamper_detected(
    opencode_tmp: Path,
) -> None:
    doc_txt = DOC_PATH.read_text(encoding="utf-8")
    for required_needle in (
        "results/fresh_clone/macos_justSilas_09e7363.steps.txt",
        "results/fresh_clone/linux_x86_64_justSilas_2b301cea.steps.txt",
        "results/fresh_clone/linux_x86_64_afterquery_final_1bc3e281.steps.txt",
        "3 s, 27 s, 118 s, 4 s, 175 s",
        "100 passed",
    ):
        assert required_needle in doc_txt, f"missing {required_needle!r} in {DOC_PATH.name}"

    _build_valid_fixture(opencode_tmp)
    af_steps = opencode_tmp / "results/fresh_clone/linux_x86_64_afterquery_final_1bc3e281.steps.txt"
    orig_steps = af_steps.read_text(encoding="utf-8")
    af_steps.write_text(orig_steps.replace("seconds=118", "seconds=999"), encoding="utf-8")
    res_step = van.check_companion_parity(opencode_tmp)
    assert res_step.status == "FAIL"
    assert any("linux_x86_64_afterquery_final_1bc3e281.steps.txt" in d for d in res_step.details)
    af_steps.write_text(orig_steps, encoding="utf-8")

    af_log = opencode_tmp / "results/fresh_clone/linux_x86_64_afterquery_final_1bc3e281.log.txt"
    orig_log = af_log.read_text(encoding="utf-8")
    af_log.write_text(orig_log.replace("100 passed", "99 passed"), encoding="utf-8")
    res_log = van.check_companion_parity(opencode_tmp)
    assert res_log.status == "FAIL"
    assert any("100 passed" in d for d in res_log.details)


def test_git_ceiling_directories_and_nested_gitless_archive_support(
    opencode_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outer_git = opencode_tmp / "outer_git"
    outer_git.mkdir()
    git_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    subprocess.run(["git", "init", "-q"], cwd=outer_git, env=git_env, check=True)
    _write(outer_git, "outer.txt", "outer\n")
    subprocess.run(["git", "add", "outer.txt"], cwd=outer_git, env=git_env, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "outer"], cwd=outer_git, env=git_env, check=True)

    nested_export = outer_git / "export"
    nested_export.mkdir()
    for entry in ROOT.iterdir():
        if entry.name in {".git", "scripts"}:
            continue
        (nested_export / entry.name).symlink_to(entry)
    nested_scripts = nested_export / "scripts"
    nested_scripts.mkdir()
    for s_entry in (ROOT / "scripts").iterdir():
        if s_entry.name == "verify_artifact_numbers.py":
            (nested_scripts / s_entry.name).write_bytes(s_entry.read_bytes())
        else:
            (nested_scripts / s_entry.name).symlink_to(s_entry)

    proc = subprocess.run(
        [sys.executable, "scripts/verify_artifact_numbers.py"],
        cwd=nested_export,
        env={
            **os.environ,
            "PYTHONPATH": str(nested_export),
            "GIT_CEILING_DIRECTORIES": str(nested_export.parent),
        },
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "0 FAIL" in proc.stdout
    assert "[FAIL]" not in proc.stdout
    assert "gitless zip fallback" in proc.stdout

    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(ROOT.resolve()))
    results_blocked = van.verify_artifact_numbers(ROOT)
    assert all(r.status in {"PASS", "WARN"} for r in results_blocked), [
        r.details for r in results_blocked
    ]
    assert "GIT_CEILING_DIRECTORIES" in results_blocked[1].summary

    broken_git = opencode_tmp / "broken_git"
    broken_git.mkdir()
    _build_valid_fixture(broken_git)
    _write(broken_git, ".git", "gitdir: /tmp/opencode/nonexistent-gitdir-w9\n")
    monkeypatch.delenv("GIT_CEILING_DIRECTORIES", raising=False)
    results_broken = van.verify_artifact_numbers(broken_git)
    assert all(r.status == "PASS" for r in results_broken), [r.details for r in results_broken]
    assert "git rev-parse blocked" in results_broken[1].summary


def test_provenance_index_passes_craft_consistency_hygiene_and_commands() -> None:
    for script_name, extra_args in (
        ("check_craft_consistency.py", ["--json"]),
        ("audit_doc_hygiene.py", ["--json"]),
        ("verify_doc_commands.py", ["--doc", "docs/NUMBER-PROVENANCE-INDEX.md", "--json"]),
    ):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / script_name), *extra_args],
            cwd=ROOT,
            env={**os.environ, "PYTHONPATH": str(ROOT)},
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        assert proc.returncode == 0, f"{script_name} failed: {proc.stdout}\n{proc.stderr}"
        payload = json.loads(proc.stdout)
        assert payload["passed"] is True
        for item in payload["results"]:
            assert item["status"] != "FAIL", item
            for detail in item.get("details", []):
                assert "NUMBER-PROVENANCE-INDEX.md" not in detail, detail


def test_no_leftover_fixture_dirs_after_cleanup() -> None:
    temp_dir: Path | None = None
    OPENCODE_TMP.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=str(OPENCODE_TMP), prefix="test-artifact-numbers-cleanup-"
    ) as tmp_str:
        temp_dir = Path(tmp_str)
        (temp_dir / "probe.txt").write_text("ok", encoding="utf-8")
        assert temp_dir.exists()
    assert temp_dir is not None and not temp_dir.exists()
