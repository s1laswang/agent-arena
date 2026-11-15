"""Unit and hygiene tests for scripts/v14_replication_report.py."""
from __future__ import annotations

from dataclasses import asdict
import io
import json
from pathlib import Path
import tokenize
from typing import Any

import pytest

from canary.env import Env
from scripts.v14_replication_report import (
    DEFAULT_REPLICATION_ROOT,
    analyze_v14_root,
    boot_ratio,
    main,
    mean_ci,
)

ROOT = Path(__file__).resolve().parents[1]
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)


def _make_ep(
    tier: str,
    seed: int,
    agent: str,
    accuse_emp: str | None = "e00",
    plant: bool = False,
    list_staff: bool = True,
) -> dict[str, Any]:
    env = Env(tier, seed)
    env.call("status", {})
    if list_staff:
        env.call("list_employees", {})
    if plant:
        env.call("plant_canary", {"assignment": {"e00": "A", "e01": "B", "e02": "C"}})
        env.call("interview", {"employee": "e00"})
    if accuse_emp is not None:
        env.call("accuse", {"employee": accuse_emp})
    res = asdict(env.result(agent))
    res["meta"] = {"rc": 0, "valid": True, "V_final": float(env.V), "wall_s": 1200.5}
    return res


def _write_shard(
    base_root: Path,
    rel_dir: str,
    episodes: list[dict[str, Any]],
    extra_meta: dict[str, Any] | None = None,
    transcripts: dict[str, str] | None = None,
) -> None:
    d = base_root / rel_dir
    d.mkdir(parents=True, exist_ok=True)
    ep_lines = "\n".join(json.dumps(e) for e in episodes) + "\n"
    (d / "episodes.jsonl").write_text(ep_lines, encoding="utf-8")
    meta = {
        "tiers_version": "v1.4",
        "seeds": [int(e["seed"]) for e in episodes],
    }
    if extra_meta:
        meta.update(extra_meta)
    (d / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    if transcripts:
        tr = d / "transcripts"
        tr.mkdir(parents=True, exist_ok=True)
        for fname, content in transcripts.items():
            (tr / fname).write_text(content, encoding="utf-8")


def _build_split_fixture(repo_root: Path) -> tuple[Path, Path]:
    primary_root = repo_root / "data" / "runs" / "committed" / "v1.4"
    repl_root = repo_root / "results" / "selected_fleet_replication" / "v1.4"
    oc_agent = "opencode:google/gemini-4-carbon"

    prim_oc = [_make_ep("hard", s, oc_agent, accuse_emp="e00", plant=True) for s in (0, 1)]
    prim_sol = [
        _make_ep("hard", 0, "solver", accuse_emp=Env("hard", 0)._world.mole, plant=True),
        _make_ep("hard", 1, "solver", accuse_emp=Env("hard", 1)._world.mole, plant=True),
    ]
    ext_oc = [
        _make_ep("hard", 30, oc_agent, accuse_emp=Env("hard", 30)._world.mole, plant=True),
        _make_ep("hard", 31, oc_agent, accuse_emp="e00", plant=True),
    ]
    ext_sol = [
        _make_ep("hard", s, "solver", accuse_emp=Env("hard", s)._world.mole, plant=True)
        for s in (30, 31, 32)
    ]

    _write_shard(primary_root, "opencode-gemini-4-carbon/hard", prim_oc)
    _write_shard(primary_root, "reference/solver-hard-20261114-121126", prim_sol)
    _write_shard(
        repl_root,
        "opencode-gemini-4-carbon/hard-s30-32",
        ext_oc,
        extra_meta={
            "planned_seeds": [30, 31, 32],
            "git_sha": "abcdef0123456789",
            "usage": {"llm_calls": 90, "cost_usd_est": 1.85},
        },
        transcripts={"30.txt": "ok\n", "31.txt": "ok\n"},
    )
    _write_shard(repl_root, "reference/solver-hard-seeds30to59", ext_sol)
    return primary_root, repl_root


def test_mean_ci_and_boot_ratio_math() -> None:
    m0, h0 = mean_ci([])
    assert m0 != m0 and h0 != h0

    m1, h1 = mean_ci([0.5])
    assert m1 == pytest.approx(0.5)
    assert h1 == 0.0

    m2, h2 = mean_ci([0.2, 0.6, 0.4])
    assert m2 == pytest.approx(0.4)
    assert h2 > 0.0

    lo_a, hi_a = boot_ratio([0.3, 0.5, 0.4, 0.6], [0.6, 0.8, 0.5, 0.7])
    lo_b, hi_b = boot_ratio([0.3, 0.5, 0.4, 0.6], [0.6, 0.8, 0.5, 0.7])
    assert lo_a == lo_b and hi_a == hi_b
    assert 0.0 < lo_a <= hi_a < 1.5

    lo_neg, hi_neg = boot_ratio([0.1, 0.2], [-0.5, -0.5])
    assert lo_neg != lo_neg and hi_neg != hi_neg


def test_default_repo_layout_and_check_mode(tmp_path: Path) -> None:
    _build_split_fixture(tmp_path)
    out_md = tmp_path / "docs" / "reports" / "v14_seeds30to59_replication.md"
    out_json = tmp_path / "out" / "report.json"

    rc = main(["--repo", str(tmp_path), "--out-json", str(out_json)])
    assert rc == 0
    assert out_md.is_file()
    assert out_json.is_file()

    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["provenance"]["primary_root"] == "data/runs/committed/v1.4"
    assert payload["provenance"]["replication_root"] == "results/selected_fleet_replication/v1.4"
    assert payload["provenance"]["episodes_verified"] == 9
    assert len(payload["per_seed_extension"]) == 2
    assert [x["seed"] for x in payload["per_seed_extension"]] == [30, 31]
    assert payload["ext_shard_manifests"][0]["pending_seeds"] == [32]

    sched = {x["seed"]: x for x in payload["solver_30to59_schedule"]}
    assert sorted(sched) == [30, 31, 32]
    assert sched[30]["frontier"] is not None
    assert sched[31]["frontier"] is not None
    assert sched[32]["frontier"] is None

    pooled_oc = next(
        r for r in payload["pooled_rows"] if r["agent"] == "opencode:google/gemini-4-carbon"
    )
    assert pooled_oc["n"] == 4
    assert pooled_oc["seeds"] == [0, 1, 30, 31]

    rc_check_ok = main(["--repo", str(tmp_path), "--check"])
    assert rc_check_ok == 0

    out_md.write_text(out_md.read_text(encoding="utf-8") + "\nextra drift line\n", encoding="utf-8")
    rc_check_fail = main(["--repo", str(tmp_path), "--check"])
    assert rc_check_fail == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "tamper_score",
        "timeout_rc",
        "error_end",
        "invalid_flag",
        "duplicate_seed",
        "meta_mismatch",
        "orphan_transcript",
        "wrong_cohort_seed",
    ],
)
def test_fail_closed_on_hygiene_or_replay_violations(tmp_path: Path, mutation: str) -> None:
    primary_root, repl_root = _build_split_fixture(tmp_path)
    target_ep_file = repl_root / "opencode-gemini-4-carbon" / "hard-s30-32" / "episodes.jsonl"
    eps = [json.loads(ln) for ln in target_ep_file.read_text(encoding="utf-8").splitlines() if ln.strip()]

    if mutation == "tamper_score":
        eps[0]["score"] = 0.123456
        target_ep_file.write_text("\n".join(json.dumps(e) for e in eps) + "\n", encoding="utf-8")
    elif mutation == "timeout_rc":
        eps[0]["meta"]["rc"] = "timeout"
        target_ep_file.write_text("\n".join(json.dumps(e) for e in eps) + "\n", encoding="utf-8")
    elif mutation == "error_end":
        eps[0]["end_reason"] = "error"
        target_ep_file.write_text("\n".join(json.dumps(e) for e in eps) + "\n", encoding="utf-8")
    elif mutation == "invalid_flag":
        eps[0]["meta"]["valid"] = False
        target_ep_file.write_text("\n".join(json.dumps(e) for e in eps) + "\n", encoding="utf-8")
    elif mutation == "duplicate_seed":
        _write_shard(repl_root, "opencode-gemini-4-carbon/hard-dup", [eps[0]])
    elif mutation == "meta_mismatch":
        meta_path = repl_root / "opencode-gemini-4-carbon" / "hard-s30-32" / "meta.json"
        meta_obj = json.loads(meta_path.read_text(encoding="utf-8"))
        meta_obj["seeds"] = [30, 99]
        meta_path.write_text(json.dumps(meta_obj) + "\n", encoding="utf-8")
    elif mutation == "orphan_transcript":
        orphan = repl_root / "opencode-gemini-4-carbon" / "hard-s30-32" / "transcripts" / "32.txt"
        orphan.write_text("stale pending transcript\n", encoding="utf-8")
    elif mutation == "wrong_cohort_seed":
        bad_ep = _make_ep("hard", 5, "opencode:google/gemini-4-carbon", accuse_emp="e00")
        _write_shard(repl_root, "opencode-gemini-4-carbon/hard-wrong-cohort", [bad_ep])

    with pytest.raises(ValueError):
        analyze_v14_root(primary_root=primary_root, replication_root=repl_root)


def test_committed_report_and_script_hygiene() -> None:
    forbidden_scratch = "/" + "local" + "scratch"
    forbidden_tmp = "/" + "tmp" + "/" + "opencode"

    for py_rel in ("scripts/v14_replication_report.py", "tests/test_v14_replication_report.py"):
        raw = (ROOT / py_rel).read_bytes()
        comments = [
            tok for tok in tokenize.tokenize(io.BytesIO(raw).readline)
            if tok.type == tokenize.COMMENT
        ]
        assert comments == [], f"unexpected comments in {py_rel}: {comments}"
        py_text = raw.decode("utf-8")
        assert EM_DASH not in py_text
        assert EN_DASH not in py_text
        assert forbidden_scratch not in py_text
        assert forbidden_tmp not in py_text

    report_path = ROOT / "docs" / "reports" / "v14_seeds30to59_replication.md"
    if not report_path.is_file():
        pytest.skip("committed replication report not staged on this branch")
    text = report_path.read_text(encoding="utf-8")
    assert EM_DASH not in text
    assert EN_DASH not in text
    assert forbidden_scratch not in text
    assert forbidden_tmp not in text
    assert "data/runs/committed/v1.4" in text
    assert "results/selected_fleet_replication/v1.4" in text
    assert "Selected Fleet Replication (Non-Primary, Incomplete 30-59 Cohort)" in text
    assert "+0.322 +/- 0.199" in text
    assert "65% [24%, 98%]" in text
    assert "72% [52%, 91%]" in text
    assert "solver-hard-seeds30to59" in text
    assert "Exploratory Pooled Hard Cohort" in text


def test_live_replication_shards_reproduce_when_present() -> None:
    repl_dir = ROOT / DEFAULT_REPLICATION_ROOT
    prim_dir = ROOT / "data" / "runs" / "committed" / "v1.4"
    report_path = ROOT / "docs" / "reports" / "v14_seeds30to59_replication.md"
    if not repl_dir.is_dir() or not prim_dir.is_dir() or not report_path.is_file():
        pytest.skip("selected fleet replication shards not staged on this branch")
    assert main(["--repo", str(ROOT), "--check"]) == 0
