from __future__ import annotations

import gzip
import json
from pathlib import Path
import re
import sys
import time
import tokenize

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.env import Env
from canary.mole.ladder_miner import (
    main,
    mine_ladder_episodes,
    render_ladder_report,
    stream_ladder_episodes,
)
from canary.rules import tier_params, tiers_version
from canary.world import generate_world

MINER_PATH = ROOT / "canary" / "mole" / "ladder_miner.py"
REPORT_PATH = ROOT / "docs" / "reports" / "mole_ladder_scale_analysis.md"
GEMMA_LADDER_PATH = ROOT / "results" / "gemini" / "ladder_gemma_episodes.jsonl.gz"
TEST_PATH = Path(__file__).resolve()


def _record_env_episode(
    *,
    tier: str,
    seed: int,
    model: str,
    level: str,
    canary_recipients: list[str],
    n_interviews: int,
    accuse_emp: str,
    thinking_tokens: int,
    include_run_id: bool = True,
) -> dict:
    with tiers_version("v1.4"):
        env = Env(tier, seed)
        steps: list[dict] = []

        def call(tool: str, args: dict) -> None:
            t_idx = len(steps)
            day_before = env.day
            res = env.call(tool, args)
            steps.append({
                "t": t_idx,
                "day": day_before,
                "tool": tool,
                "args": args,
                "result": {"ok": res.ok, "data": res.data, "error": res.error},
            })

        call("list_employees", {})
        call("status", {})
        if canary_recipients:
            assignment = {
                emp: ("A" if idx % 2 == 0 else "B")
                for idx, emp in enumerate(canary_recipients)
            }
            call("plant_canary", {"doc_title": "Q3 roadmap", "assignment": assignment})
        for idx in range(n_interviews):
            call("interview", {"employee": f"e{idx:02d}", "topic": "workload"})
        call("advance_day", {})
        call("check_leak_feed", {})
        call("accuse", {"employee": accuse_emp})

        verdict = env.verdict()
        meta: dict = {
            "valid": True,
            "model_id": model,
            "thinking_level": level,
            "ladder": {
                "model": model,
                "level": level,
                "tier": tier,
                "seed": seed,
                "tokens": {"thinking": thinking_tokens},
            },
        }
        if include_run_id:
            meta["run_id"] = f"ladder:v14:{model}/{level}/{tier}/{seed}"
        return {
            "tier": tier,
            "seed": seed,
            "agent": f"gemini:{model}+think:{level}",
            "steps": steps,
            "score": float(env.score()),
            "accused": verdict["accused"],
            "correct": bool(verdict["correct"]),
            "final_day": int(env.day),
            "end_reason": "accused",
            "meta": meta,
        }


def test_real_gemma_ladder_slice_matches_committed_report() -> None:
    t0 = time.perf_counter()
    data = mine_ladder_episodes(
        episode_paths=[GEMMA_LADDER_PATH],
        cf_seeds=range(0, 10),
        cf_tier="hard",
        solver_ref_dir=None,
        run_solver=False,
        workers=1,
    )
    elapsed = time.perf_counter() - t0
    assert elapsed < 4.0

    assert data["total_episodes"] == 5
    assert data["n_cells"] == 1
    assert data["n_hard_episodes"] == 5
    assert data["n_medium_episodes"] == 0

    cell = data["cells"][0]
    assert cell["model"] == "gemma-4-31b-it"
    assert cell["display_model"] == "gemma-4-31b-it (hosted)"
    assert cell["thinking_level"] == "default"
    assert cell["tier"] == "hard"
    assert cell["n_episodes"] == 5
    assert cell["canaries_per_episode"] == pytest.approx(8.20, abs=1e-2)
    assert cell["le_3_share"] == pytest.approx(0.1707, abs=1e-3)
    assert cell["decoy_dismissal_rate"] == pytest.approx(1.0)
    assert cell["below_breakeven_accusations"] == 5
    assert cell["below_breakeven_rate"] == pytest.approx(1.0)
    assert int(round(cell["thinking_tokens_mean"])) == 16936

    cf_cell = data["counterfactual"]["cells"][0]
    assert cf_cell["n_seeds"] == 5
    assert cf_cell["p_true_mole_default"] == pytest.approx(0.089, abs=1e-3)
    assert cf_cell["p_true_mole_candidate"] == pytest.approx(0.058, abs=1e-3)
    assert cf_cell["p_true_mole_drop"] == pytest.approx(0.031, abs=1e-3)

    slice_md = render_ladder_report(data)
    committed_md = REPORT_PATH.read_text(encoding="utf-8")
    for line in slice_md.splitlines():
        if line.startswith("| gemma-4-31b-it (hosted) |") or line.startswith("| Gemma 4 31B (open-weight) |"):
            assert line in committed_md


def test_streaming_dedup_invalid_filter_deltas_and_solver_gate(tmp_path: Path) -> None:
    with tiers_version("v1.4"):
        w0 = generate_world("hard", 0, tier_params("hard"))
    decoy0 = str(w0.decoy)
    non_decoy = next(f"e{i:02d}" for i in range(10) if f"e{i:02d}" not in {decoy0, str(w0.mole)})

    ep_lite_low = _record_env_episode(
        tier="hard",
        seed=0,
        model="gemini-3.1-flash-lite",
        level="low",
        canary_recipients=["e00", "e01"],
        n_interviews=0,
        accuse_emp=decoy0,
        thinking_tokens=400,
    )
    ep_lite_high = _record_env_episode(
        tier="hard",
        seed=0,
        model="gemini-3.1-flash-lite",
        level="high",
        canary_recipients=["e00", "e01", "e02", "e03", "e04"],
        n_interviews=1,
        accuse_emp=non_decoy,
        thinking_tokens=1500,
    )
    ep_carbon_low = _record_env_episode(
        tier="hard",
        seed=0,
        model="gemini-4-carbon",
        level="low",
        canary_recipients=["e00", "e01", "e02"],
        n_interviews=0,
        accuse_emp=non_decoy,
        thinking_tokens=300,
    )
    ep_carbon_high = _record_env_episode(
        tier="hard",
        seed=0,
        model="gemini-4-carbon",
        level="high",
        canary_recipients=["e00", "e01", "e02", "e03", "e04", "e05"],
        n_interviews=3,
        accuse_emp=str(w0.mole),
        thinking_tokens=9000,
        include_run_id=False,
    )

    invalid_flag = dict(ep_carbon_low, seed=2, meta={**ep_carbon_low["meta"], "valid": False})
    invalid_err = dict(ep_carbon_low, seed=3, end_reason="error")

    gz_path = tmp_path / "batch1.jsonl.gz"
    with gzip.open(gz_path, "wt", encoding="utf-8") as fh:
        for row in (ep_lite_low, ep_carbon_low, invalid_flag, invalid_err):
            fh.write(json.dumps(row) + "\n")

    plain_path = tmp_path / "batch2.jsonl"
    plain_path.write_text(
        "\n".join(
            json.dumps(r)
            for r in (
                ep_carbon_low,
                ep_carbon_high,
                dict(ep_carbon_high),
                ep_lite_high,
            )
        )
        + "\n",
        encoding="utf-8",
    )

    ref_dir = tmp_path / "ref"
    (ref_dir / "solver-hard").mkdir(parents=True)
    solver_row = {
        "tier": "hard",
        "seed": 0,
        "agent": "solver",
        "steps": [],
        "score": 0.62,
        "accused": str(w0.mole),
        "correct": True,
        "final_day": 9,
        "end_reason": "accused",
        "meta": {"valid": True},
    }
    (ref_dir / "solver-hard" / "episodes.jsonl").write_text(
        json.dumps(solver_row) + "\n",
        encoding="utf-8",
    )
    sup_dir = ref_dir / "superseded"
    sup_dir.mkdir(parents=True)
    (sup_dir / "episodes.jsonl").write_text(
        json.dumps(dict(solver_row, score=0.99, final_day=1)) + "\n",
        encoding="utf-8",
    )

    data = mine_ladder_episodes(
        episode_paths=[f"{gz_path},{plain_path}"],
        cf_seeds=[0],
        cf_tier="hard",
        solver_ref_dir=ref_dir,
        run_solver=True,
        workers=1,
    )

    assert data["total_episodes"] == 4
    assert data["n_cells"] == 4
    assert data["files"] == [
        {"path": gz_path.as_posix(), "valid_episodes": 2, "distinct_added": 2},
        {"path": plain_path.as_posix(), "valid_episodes": 4, "distinct_added": 2},
    ]

    ds = data["decoy_split"]
    assert ds["flash_lite_decoy_episodes"] == 2
    assert ds["flash_lite_decoy_accused"] == 1
    assert ds["flash_lite_dismissal_rate"] == pytest.approx(0.5)
    assert ds["above_flash_lite_decoy_episodes"] == 2
    assert ds["above_flash_lite_decoy_accused"] == 0
    assert ds["above_flash_lite_dismissal_rate"] == pytest.approx(1.0)

    deltas = {d["model"]: d for d in data["thinking_deltas"]}
    c_delta = deltas["gemini-4-carbon"]
    assert c_delta["le_3_share_low"] == pytest.approx(1.0)
    assert c_delta["le_3_share_high"] == pytest.approx(0.0)
    assert c_delta["le_3_share_delta"] == pytest.approx(-1.0)
    assert c_delta["4_to_8_share_delta"] == pytest.approx(1.0)
    assert c_delta["interview_share_delta"] > 0.4

    by_cell = {(c["model"], c["thinking_level"]): c for c in data["cells"]}
    assert by_cell[("gemini-4-carbon", "low")]["accuse_day_lag_vs_solver"] == pytest.approx(-7.0)

    sol_cf = data["counterfactual"]["solver_catchability"]
    assert sol_cf is not None
    assert sol_cf["n_seeds"] == 1
    assert sol_cf["default_score"] == pytest.approx(0.62)
    assert 0.0 <= sol_cf["candidate_accuracy"] <= 1.0

    md = render_ladder_report(data)
    assert "Reference `SolverPolicy` Catchability Gate" in md
    assert all(ord(ch) < 128 for ch in md)


def test_cli_json_markdown_and_missing_episode_path(tmp_path: Path, capsys) -> None:
    ep = _record_env_episode(
        tier="medium",
        seed=0,
        model="gemini-3.5-flash",
        level="high",
        canary_recipients=["e00", "e01"],
        n_interviews=0,
        accuse_emp="e00",
        thinking_tokens=500,
    )
    ep_file = tmp_path / "mini.jsonl"
    ep_file.write_text(json.dumps(ep) + "\n", encoding="utf-8")

    rc_json = main([
        "--episodes",
        str(ep_file),
        "--cf-seeds",
        "",
        "--solver-ref-dir",
        str(tmp_path / "no_ref"),
        "--json",
    ])
    assert rc_json == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["total_episodes"] == 1
    assert payload["cells"][0]["display_model"] == "gemini-3.5-flash (served 3.6-flash)"

    md_out = tmp_path / "out" / "report.md"
    rc_md = main([
        "--episodes",
        str(ep_file),
        "--cf-seeds",
        "",
        "--solver-ref-dir",
        str(tmp_path / "no_ref"),
        "--out",
        str(md_out),
    ])
    assert rc_md == 0
    capsys.readouterr()
    assert md_out.is_file()
    assert "gemini-3.5-flash (served 3.6-flash)" in md_out.read_text(encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        list(stream_ladder_episodes([tmp_path / "does_not_exist.jsonl.gz"]))


def _section_table_rows(md_text: str, heading_prefix: str) -> list[list[str]]:
    lines = md_text.splitlines()
    in_sec = False
    rows: list[list[str]] = []
    h2_prefix = chr(35) * 2 + " "
    for line in lines:
        if line.startswith(h2_prefix):
            if in_sec:
                break
            if line.startswith(heading_prefix):
                in_sec = True
                continue
        if in_sec and line.startswith("|"):
            cols = [c.strip() for c in line.strip("|").split("|")]
            if cols and cols[0] not in {"Family", "Model", "---"} and not set(cols[0]) <= {"-"}:
                rows.append(cols)
    return rows


def test_committed_report_integrity_and_pr_gates() -> None:
    assert REPORT_PATH.is_file()
    md = REPORT_PATH.read_text(encoding="utf-8")
    h2 = chr(35) * 2

    for sec in (
        f"{h2} 1. Corpus Provenance and Headline Scaling Findings",
        f"{h2} 2. Family-Level Vulnerability Scaling",
        f"{h2} 3. Per-(Model, Thinking, Tier) Mole-Evasion Vulnerabilities (Hard Tier)",
        f"{h2} 4. Per-(Model, Thinking, Tier) Mole-Evasion Vulnerabilities (Medium Tier)",
        f"{h2} 5. Thinking-Budget Scaling Shifts",
        f"{h2} 6. Counterfactual Schedule Replay",
        f"{h2} 7. Implications for Fair Mole Design Across Model Scales",
    ):
        assert sec in md

    fam_rows = _section_table_rows(md, f"{h2} 2.")
    hard_rows = _section_table_rows(md, f"{h2} 3.")
    med_rows = _section_table_rows(md, f"{h2} 4.")
    cf_rows = _section_table_rows(md, f"{h2} 6.")

    assert len(hard_rows) == 21
    assert len(med_rows) == 20
    assert sum(int(r[2]) for r in hard_rows) == 297
    assert sum(int(r[2]) for r in med_rows) == 258
    assert sum(int(r[2]) for r in fam_rows if r[1] == "hard") == 297
    assert sum(int(r[2]) for r in fam_rows if r[1] == "medium") == 258

    cf_cell_rows = [r for r in cf_rows if not r[0].startswith("**")]
    assert len(cf_cell_rows) == 21
    assert sum(int(r[2]) for r in cf_cell_rows) == 198

    forbidden_gap_re = re.compile(
        r"(?:%\s+of\s+(?:the\s+)?solver|(?:score|frontier|luck-adj\.?)\s*/\s*solver)",
        re.IGNORECASE,
    )
    for target in (MINER_PATH, REPORT_PATH):
        txt = target.read_text(encoding="utf-8")
        assert forbidden_gap_re.search(txt) is None, f"forbidden solver gap ratio claim in {target}"

    for py_file in (MINER_PATH, TEST_PATH):
        with py_file.open("rb") as fh:
            comments = [tok for tok in tokenize.tokenize(fh.readline) if tok.type == tokenize.COMMENT]
        assert comments == [], f"comment token found in {py_file}"
        assert chr(35) not in py_file.read_text(encoding="utf-8"), f"raw hash character in {py_file}"

    for p in (MINER_PATH, REPORT_PATH, TEST_PATH):
        txt = p.read_text(encoding="utf-8")
        assert "\u2014" not in txt, f"em-dash found in {p}"
        assert "\u2013" not in txt, f"en-dash found in {p}"
        assert "\u2212" not in txt, f"unicode minus found in {p}"
        assert all(ord(ch) < 128 for ch in txt), f"non-ASCII character found in {p}"
