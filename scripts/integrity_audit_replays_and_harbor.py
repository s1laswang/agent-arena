from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EMP_ID_RE = re.compile(r"^e\d{2,}$")


def _default_tmp_root() -> Path:
    scratch_job = Path("/localscratch/job_44578")
    if scratch_job.is_dir():
        return scratch_job / "w8"
    return Path(tempfile.gettempdir()) / "canary-w8-tmp"


def _load_audit_submission():
    spec = importlib.util.spec_from_file_location(
        "audit_submission", ROOT / "scripts" / "audit_submission.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _is_finite_num(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val))


def _in_score_domain(score: float) -> bool:
    return score == -1.0 or score == 0.0 or (0.0 < score <= 1.0)


def _harbor_timeout_cap(root: Path) -> float:
    toml_path = root / "harbor" / "template" / "task.toml"
    if not toml_path.is_file():
        return 10800.0
    raw = toml_path.read_text(encoding="utf-8")
    cleaned = "\n".join(ln for ln in raw.splitlines() if "${" not in ln)
    parsed = tomllib.loads(cleaned)
    return float(((parsed.get("agent") or {}).get("timeout_sec")) or 10800.0)


def _audit_episode_record(
    ep: dict[str, Any], loc: str, timeout_cap_s: float, *, summary_only: bool = False
) -> dict[str, Any]:
    meta = ep.get("meta") if isinstance(ep.get("meta"), dict) else {}
    is_valid = not ((meta.get("valid") is False) or (ep.get("valid") is False))
    violations: list[str] = []

    raw_score = ep.get("score")
    if not _is_finite_num(raw_score):
        violations.append(f"{loc}: non-finite score {raw_score!r}")
        return {"valid": is_valid, "violations": violations, "wall_s": None, "accused": ep.get("accused")}

    score = float(raw_score)
    accused = ep.get("accused")
    correct = ep.get("correct")
    end_reason = ep.get("end_reason")
    rc = meta.get("rc")
    wall_raw = meta.get("wall_s")
    wall_s = float(wall_raw) if _is_finite_num(wall_raw) else None

    if not is_valid:
        if score != 0.0:
            violations.append(f"{loc}: invalid episode has non-zero score {score}")
        if end_reason == "accused" or accused is not None:
            violations.append(
                f"{loc}: invalid episode has completed accusation (accused={accused!r}, end={end_reason!r})"
            )
        return {"valid": False, "violations": violations, "wall_s": wall_s, "accused": accused}

    if not _in_score_domain(score):
        violations.append(f"{loc}: score {score!r} outside {{-1.0, 0.0}} U (0.0, 1.0]")

    agent_stopped = (
        rc == 0
        and accused is None
        and score == 0.0
        and str(meta.get("note") or "").startswith("agent stopped without ending the episode")
    )
    if end_reason == "error" and not agent_stopped:
        violations.append(f"{loc}: valid episode has end_reason == 'error'")

    if rc == "timeout" or end_reason == "timeout":
        violations.append(f"{loc}: valid episode has timeout (rc={rc!r}, end_reason={end_reason!r})")

    if wall_s is not None and wall_s >= timeout_cap_s and accused is None:
        violations.append(f"{loc}: wall_s={wall_s} >= timeout_cap={timeout_cap_s} without accusation")

    if not isinstance(correct, bool):
        violations.append(f"{loc}: correct field is not bool ({correct!r})")
    correct_bool = bool(correct)

    v_candidates: list[tuple[str, float]] = []
    if _is_finite_num(meta.get("V_final")):
        v_candidates.append(("meta.V_final", float(meta["V_final"])))
    if _is_finite_num(meta.get("V")):
        v_candidates.append(("meta.V", float(meta["V"])))

    ledger_events = meta.get("ledger_events")
    if isinstance(ledger_events, list):
        acc_events = [ev for ev in ledger_events if isinstance(ev, dict) and ev.get("event") == "accused"]
        if len(acc_events) > 1:
            violations.append(f"{loc}: {len(acc_events)} accused events in meta.ledger_events")
        if acc_events:
            det = acc_events[-1].get("detail") or {}
            if det.get("employee") != accused:
                violations.append(
                    f"{loc}: ledger_events employee {det.get('employee')!r} != accused {accused!r}"
                )
            if _is_finite_num(det.get("V")):
                v_candidates.append(("ledger_events.accused.V", float(det["V"])))

    if accused is None:
        if score != 0.0:
            violations.append(f"{loc}: accused is None but score == {score!r}")
        if correct_bool:
            violations.append(f"{loc}: accused is None but correct is True")
        if end_reason == "accused":
            violations.append(f"{loc}: accused is None but end_reason == 'accused'")
    else:
        if not (isinstance(accused, str) and EMP_ID_RE.match(accused)):
            violations.append(f"{loc}: malformed accused id {accused!r}")
        if end_reason != "accused":
            violations.append(f"{loc}: accused={accused!r} but end_reason={end_reason!r}")
        if correct_bool:
            has_zero_v = any(v == 0.0 for _, v in v_candidates)
            if score == 0.0 and not has_zero_v and not summary_only:
                violations.append(f"{loc}: correct accusation has score 0.0 without V==0.0")
            elif score < 0.0:
                violations.append(f"{loc}: correct accusation has negative score {score!r}")
            for v_src, v_val in v_candidates:
                if abs(score - round(v_val, 10)) > 1e-6:
                    violations.append(f"{loc}: score {score!r} != {v_src} {v_val!r}")
        else:
            if score != -1.0:
                violations.append(f"{loc}: wrong accusation has score {score!r} != -1.0")

    return {"valid": True, "violations": violations, "wall_s": wall_s, "accused": accused}


def audit_data_rules(root: Path = ROOT) -> dict[str, Any]:
    from canary import reproduce as R

    harbor_cap_s = _harbor_timeout_cap(root)
    repro_cap_s = float(R.EPISODE_TIMEOUT_S)

    committed_root = root / "data" / "runs" / "committed"
    all_committed_files = sorted(committed_root.rglob("episodes.jsonl")) if committed_root.is_dir() else []
    active_files = R.committed_files(root)
    active_set = {p.resolve() for p in active_files}
    superseded_files = [p for p in all_committed_files if p.resolve() not in active_set]

    cohorts: dict[tuple[str, str, str], dict[str, Any]] = {}
    violations: list[str] = []
    advisory_notes: list[str] = []

    total_active_episodes = 0
    total_active_valid = 0
    total_active_invalid = 0

    for f in active_files:
        run_meta = R.run_meta(f.parent)
        version = R.run_tiers_version(f.parent, root, run_meta)
        cap_raw = run_meta.get("timeout_s") or run_meta.get("timeout")
        cap_s = float(cap_raw) if _is_finite_num(cap_raw) else harbor_cap_s
        rel = f.relative_to(root).as_posix()
        seen_in_file: set[tuple[str, str, int]] = set()

        for lineno, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            loc = f"{rel}:{lineno}"
            ep = json.loads(line)
            total_active_episodes += 1
            tier = str(ep.get("tier") or "")
            agent = str(ep.get("agent") or "")
            seed = int(ep["seed"])

            ckey = (version, tier, agent)
            c = cohorts.setdefault(
                ckey,
                {
                    "source": "committed_active",
                    "tiers_version": version,
                    "tier": tier,
                    "agent": agent,
                    "files": [],
                    "n_total": 0,
                    "n_valid": 0,
                    "n_invalid": 0,
                    "n_accused": 0,
                    "n_correct": 0,
                    "n_wrong": 0,
                    "n_abstain": 0,
                    "dup_in_file": 0,
                    "dup_in_cohort": 0,
                    "end_error_valid": 0,
                    "rc_timeout_valid": 0,
                    "wall_ge_cap_no_accuse": 0,
                    "score_domain_bad": 0,
                    "score_v_mismatch": 0,
                    "max_wall_s": 0.0,
                    "seeds_seen": set(),
                    "valid_scores": [],
                },
            )
            if rel not in c["files"]:
                c["files"].append(rel)
            c["n_total"] += 1

            fkey = (tier, agent, seed)
            if fkey in seen_in_file:
                c["dup_in_file"] += 1
                violations.append(f"{loc}: duplicate seed {seed} within single run file")
            seen_in_file.add(fkey)

            if seed in c["seeds_seen"]:
                c["dup_in_cohort"] += 1
                violations.append(f"{loc}: duplicate seed {seed} across active cohort {ckey}")
            c["seeds_seen"].add(seed)

            res = _audit_episode_record(ep, loc, cap_s)
            if res["wall_s"] is not None and res["wall_s"] > c["max_wall_s"]:
                c["max_wall_s"] = res["wall_s"]
            if res["valid"] and res["wall_s"] is not None and res["wall_s"] >= 3600.0 and res["accused"] is None:
                advisory_notes.append(
                    f"{loc}: wall_s={res['wall_s']}s (< Harbor {cap_s:.0f}s cap, >= 3600s CLI default), "
                    f"end_reason={ep.get('end_reason')!r}, final_day={ep.get('final_day')}, rc={(ep.get('meta') or {}).get('rc')!r}"
                )

            if res["valid"]:
                total_active_valid += 1
                c["n_valid"] += 1
                sc = float(ep["score"])
                c["valid_scores"].append(sc)
                if ep.get("accused") is not None:
                    c["n_accused"] += 1
                    if ep.get("correct"):
                        c["n_correct"] += 1
                    else:
                        c["n_wrong"] += 1
                else:
                    c["n_abstain"] += 1
            else:
                total_active_invalid += 1
                c["n_invalid"] += 1

            for v in res["violations"]:
                violations.append(v)
                if "end_reason == 'error'" in v:
                    c["end_error_valid"] += 1
                elif "timeout" in v and "wall_s" not in v:
                    c["rc_timeout_valid"] += 1
                elif "wall_s=" in v:
                    c["wall_ge_cap_no_accuse"] += 1
                elif "outside {-1.0, 0.0}" in v or "non-finite" in v:
                    c["score_domain_bad"] += 1
                else:
                    c["score_v_mismatch"] += 1

    try:
        loaded_rows, _ = R.load_committed(root)
    except Exception as exc:
        violations.append(f"reproduce.load_committed raised {type(exc).__name__}: {exc}")
        loaded_rows = []
    if loaded_rows:
        loaded_map = {(r.extra.get("tiers_version"), r.tier, r.agent): r for r in loaded_rows}
        for ckey, c in cohorts.items():
            r = loaded_map.get(ckey)
            if r is None:
                violations.append(f"reproduce.load_committed missing cohort {ckey}")
                continue
            if len(r.scores) != c["n_valid"]:
                violations.append(
                    f"reproduce.load_committed valid count {len(r.scores)} != {c['n_valid']} for {ckey}"
                )
            if len(r.extra.get("invalid") or []) != c["n_invalid"]:
                violations.append(
                    f"reproduce.load_committed invalid count {len(r.extra.get('invalid') or [])} != {c['n_invalid']} for {ckey}"
                )

    superseded_summary = {
        "n_files": len(superseded_files),
        "n_episodes": 0,
        "n_valid": 0,
        "n_invalid": 0,
        "violations": [],
    }
    for f in superseded_files:
        rel = f.relative_to(root).as_posix()
        seen_sup: set[int] = set()
        for lineno, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            loc = f"{rel}:{lineno}"
            ep = json.loads(line)
            superseded_summary["n_episodes"] += 1
            sd = int(ep["seed"])
            if sd in seen_sup:
                superseded_summary["violations"].append(f"{loc}: duplicate seed {sd} in superseded file")
            seen_sup.add(sd)
            res = _audit_episode_record(ep, loc, harbor_cap_s)
            if res["valid"]:
                superseded_summary["n_valid"] += 1
            else:
                superseded_summary["n_invalid"] += 1
            superseded_summary["violations"].extend(res["violations"])

    judge_path = root / "results" / "judge_episodes.jsonl"
    judge_cohorts: dict[tuple[str, str], dict[str, Any]] = {}
    judge_violations: list[str] = []
    total_judge_episodes = 0
    if judge_path.is_file():
        for lineno, line in enumerate(judge_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            total_judge_episodes += 1
            loc = f"results/judge_episodes.jsonl:{lineno}"
            ep = json.loads(line)
            tier = str(ep.get("tier") or "")
            agent = str(ep.get("agent") or "")
            seed = int(ep["seed"])
            jkey = (tier, agent)
            jc = judge_cohorts.setdefault(
                jkey,
                {
                    "source": "judge_episodes",
                    "tiers_version": "v1.4",
                    "tier": tier,
                    "agent": agent,
                    "n_total": 0,
                    "n_valid": 0,
                    "n_accused": 0,
                    "n_correct": 0,
                    "n_wrong": 0,
                    "n_abstain": 0,
                    "dup_in_cohort": 0,
                    "violations": 0,
                    "seeds_seen": set(),
                    "valid_scores": [],
                },
            )
            jc["n_total"] += 1
            if seed in jc["seeds_seen"]:
                jc["dup_in_cohort"] += 1
                judge_violations.append(f"{loc}: duplicate seed {seed} in {jkey}")
            jc["seeds_seen"].add(seed)
            res = _audit_episode_record(ep, loc, repro_cap_s, summary_only=True)
            if res["valid"]:
                jc["n_valid"] += 1
                jc["valid_scores"].append(float(ep["score"]))
                if ep.get("accused") is not None:
                    jc["n_accused"] += 1
                    if ep.get("correct"):
                        jc["n_correct"] += 1
                    else:
                        jc["n_wrong"] += 1
                else:
                    jc["n_abstain"] += 1
            if res["violations"]:
                jc["violations"] += len(res["violations"])
                judge_violations.extend(res["violations"])

    cohort_rows = []
    for k in sorted(cohorts):
        c = dict(cohorts[k])
        scores = c.pop("valid_scores")
        c["n_distinct_seeds"] = len(c.pop("seeds_seen"))
        c["mean_score"] = round(sum(scores) / len(scores), 4) if scores else None
        cohort_rows.append(c)

    judge_rows = []
    for k in sorted(judge_cohorts):
        jc = dict(judge_cohorts[k])
        scores = jc.pop("valid_scores")
        jc["n_distinct_seeds"] = len(jc.pop("seeds_seen"))
        jc["mean_score"] = round(sum(scores) / len(scores), 4) if scores else None
        judge_rows.append(jc)

    all_violations = violations + superseded_summary["violations"] + judge_violations
    return {
        "passed": len(all_violations) == 0,
        "harbor_timeout_cap_s": harbor_cap_s,
        "reproduce_timeout_cap_s": repro_cap_s,
        "active_files": len(active_files),
        "active_episodes": total_active_episodes,
        "active_valid": total_active_valid,
        "active_invalid": total_active_invalid,
        "superseded": superseded_summary,
        "judge_episodes_total": total_judge_episodes,
        "cohorts": cohort_rows,
        "judge_cohorts": judge_rows,
        "violations": all_violations,
        "advisory_notes": advisory_notes,
    }


def _write_synthetic_committed(
    case_root: Path,
    rel_dir: str,
    raw_lines: list[str],
    meta: dict[str, Any] | None = None,
) -> Path:
    run_dir = case_root / "data" / "runs" / "committed" / rel_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "episodes.jsonl").write_text("\n".join(raw_lines) + "\n", encoding="utf-8")
    if meta is not None:
        (run_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return run_dir


def _eval_replay_case(case_root: Path, audit_mod: Any) -> dict[str, Any]:
    from canary import reproduce as R
    from canary.redteam import anticheat as ac
    from canary.redteam import tamper_guard as tg

    up_rep = ac.replay_committed(case_root)
    up_consistent = all(r["replay_consistent"] is not False for r in up_rep)

    tg_rep = tg.replay_committed(case_root)
    tg_consistent = all(r["replay_consistent"] is not False for r in tg_rep)
    step_mismatches = sum(r.get("step_mismatches", 0) for r in tg_rep)

    repro_rows, repro_labels = R.load_committed(case_root)
    sub_res = audit_mod.check_committed_runs(
        case_root, load_committed_fn=lambda _: (repro_rows, repro_labels)
    )
    repro_scores = [sc for r in repro_rows for sc in r.scores]
    raw_mean = sum(repro_scores) / len(repro_scores) if repro_scores else None
    clean_mean = round(raw_mean, 6) if (raw_mean is not None and math.isfinite(raw_mean)) else None
    return {
        "upstream_anticheat_caught": not up_consistent,
        "tamper_guard_caught": not tg_consistent,
        "anticheat_caught": not tg_consistent,
        "step_mismatches": step_mismatches,
        "audit_submission_status": sub_res.status,
        "audit_submission_caught": sub_res.status == "FAIL",
        "repro_n_scored": len(repro_scores),
        "repro_mean": clean_mean,
    }


def fuzz_replay_checker(root: Path = ROOT, tmp_base: Path | None = None) -> list[dict[str, Any]]:
    audit_mod = _load_audit_submission()

    oc_flash_file = root / "data/runs/committed/v1.4/opencode-gemini-3.5-flash/hard/episodes.jsonl"
    inproc_med_file = root / "data/runs/committed/v1.4/inproc-gemini-4-carbon/medium/episodes.jsonl"
    v13_med_file = root / "data/runs/committed/v1.3/codex-gpt-5.5-full/medium/episodes.jsonl"

    def _pick_seeds(path: Path, target_seeds: set[int]) -> dict[int, dict[str, Any]]:
        picked: dict[int, dict[str, Any]] = {}
        for ln in path.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            obj = json.loads(ln)
            sd = int(obj["seed"])
            if sd in target_seeds:
                picked[sd] = obj
                if len(picked) == len(target_seeds):
                    break
        return picked

    flash_map = _pick_seeds(oc_flash_file, {2})
    med_map = _pick_seeds(inproc_med_file, {0, 3, 18})
    v13_med_ep0 = json.loads(v13_med_file.read_text(encoding="utf-8").splitlines()[0])

    ep_trunc = flash_map[2]
    trunc_idx = next(
        i
        for i, st in enumerate(ep_trunc["steps"])
        if isinstance(st.get("result"), dict) and "raw" in st["result"]
    )
    ep_win = med_map[0]
    ep_wrong = med_map[18]
    ep_horizon = med_map[3]

    created_base = False
    if tmp_base is None:
        base_root = _default_tmp_root()
        base_root.mkdir(parents=True, exist_ok=True)
        work_dir = Path(tempfile.mkdtemp(prefix="replay-fuzz-", dir=str(base_root)))
        created_base = True
    else:
        tmp_base.mkdir(parents=True, exist_ok=True)
        work_dir = tmp_base / "replay_fuzz"
        work_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    try:

        def run_case(
            mut_id: str,
            name: str,
            category: str,
            description: str,
            rel_dir: str,
            raw_lines: list[str],
            meta: dict[str, Any],
            tamper_goal_achieved_if_uncaught: bool,
            location: str,
            impact_note: str,
        ) -> None:
            cdir = work_dir / mut_id
            _write_synthetic_committed(cdir, rel_dir, raw_lines, meta)
            ev = _eval_replay_case(cdir, audit_mod)
            bypass = tamper_goal_achieved_if_uncaught and (not ev["tamper_guard_caught"])
            results.append(
                {
                    "id": mut_id,
                    "name": name,
                    "category": category,
                    "description": description,
                    "upstream_anticheat_caught": ev["upstream_anticheat_caught"],
                    "tamper_guard_caught": ev["tamper_guard_caught"],
                    "anticheat_caught": ev["anticheat_caught"],
                    "audit_submission_status": ev["audit_submission_status"],
                    "audit_submission_caught": ev["audit_submission_caught"],
                    "step_mismatches": ev["step_mismatches"],
                    "repro_n_scored": ev["repro_n_scored"],
                    "repro_mean": ev["repro_mean"],
                    "bypass": bypass,
                    "location": location,
                    "impact": impact_note,
                }
            )

        e1 = copy.deepcopy(ep_trunc)
        orig_raw = e1["steps"][trunc_idx]["result"]["raw"]
        e1["steps"][trunc_idx]["result"]["raw"] = '{"forged":true}' + orig_raw[15:]
        run_case(
            "R01",
            "oc_trunc_prefix_injected",
            "opencode_truncation",
            "Inject non-whitespace prefix before ...N bytes truncated... keeping raw byte length and N equal",
            "v1.4/fuzz/hard",
            [json.dumps(e1)],
            {"tiers_version": "v1.4"},
            True,
            "canary/redteam/anticheat.py:601",
            "Blocked: _OC_TRUNC anchors at \\A\\s* so non-whitespace prefix falls through to _canon mismatch",
        )

        e2 = copy.deepcopy(ep_trunc)
        e2["steps"][trunc_idx]["result"]["raw"] = orig_raw.replace(
            "62295 bytes truncated", "62296 bytes truncated"
        )
        run_case(
            "R02",
            "oc_trunc_wrong_byte_count",
            "opencode_truncation",
            "Perturb byte count N -> N+1 inside OpenCode ...N bytes truncated... marker",
            "v1.4/fuzz/hard",
            [json.dumps(e2)],
            {"tiers_version": "v1.4"},
            True,
            "canary/redteam/anticheat.py:557",
            "Blocked: len(json.dumps(got_payload).encode()) == trunc catches any N byte-length mismatch",
        )

        e3 = copy.deepcopy(ep_trunc)
        marker = "Full output saved to: "
        pos = orig_raw.index(marker) + len(marker)
        tail_len = len(orig_raw) - pos
        forged_tail = ("/tmp/FORGED_MOLE_HINT_E25_" + ("X" * tail_len))[:tail_len]
        e3["steps"][trunc_idx]["result"]["raw"] = orig_raw[:pos] + forged_tail
        assert len(e3["steps"][trunc_idx]["result"]["raw"].encode()) == len(orig_raw.encode())
        run_case(
            "R03",
            "oc_trunc_tail_same_length_edit",
            "opencode_truncation",
            "Edit recorded text after 'Full output saved to: ' keeping N and raw byte length identical",
            "v1.4/fuzz/hard",
            [json.dumps(e3)],
            {"tiers_version": "v1.4", "provider": "opencode"},
            True,
            "canary/redteam/tamper_guard.py; canary/redteam/anticheat.py:601",
            "Blocked in tamper_guard (_OC_TRUNC_STRICT verifies full path and footer); bypasses upstream _OC_TRUNC prefix-only regex",
        )

        e4 = copy.deepcopy(ep_win)
        st0_bytes = len(json.dumps(e4["steps"][0]["result"]).encode())
        e4["steps"][0]["result"] = {
            "raw": (
                f"\n\n...{st0_bytes} bytes truncated...\n\nThe tool call succeeded but the output was truncated. "
                "Full output saved to: /tmp/forged_small_step"
            )
        }
        run_case(
            "R04",
            "oc_trunc_forged_on_small_step",
            "opencode_truncation",
            f"Replace un-truncated {st0_bytes}-byte step result with forged OpenCode truncation marker",
            "v1.4/fuzz/hard",
            [json.dumps(e4)],
            {"tiers_version": "v1.4"},
            True,
            "canary/redteam/tamper_guard.py; canary/redteam/anticheat.py:554-557",
            "Blocked in tamper_guard (allows_opencode_quirks and _OC_TRUNC_STRICT); bypasses upstream anticheat",
        )

        e5 = copy.deepcopy(ep_win)
        fake_refused = {
            "t": 1,
            "day": 1,
            "tool": "bash",
            "args": {"command": "cat /etc/passwd"},
            "result": {
                "ok": False,
                "error": "Model tried to call unavailable tool 'bash'. Available tools: canary_status.",
            },
        }
        e5["steps"].insert(1, fake_refused)
        run_case(
            "R05",
            "client_refused_fake_injected",
            "client_refused",
            "Inject synthetic OpenCode _OC_NO_TOOL call (tool='bash') into a non-OpenCode run",
            "v1.4/fuzz/hard",
            [json.dumps(e5)],
            {"tiers_version": "v1.4", "provider": "gemini"},
            True,
            "canary/redteam/tamper_guard.py; canary/redteam/anticheat.py:615",
            "Blocked in tamper_guard (rejects _OC_NO_TOOL quirks on non-OpenCode runs and checks companion transcripts)",
        )

        e6 = copy.deepcopy(ep_win)
        e6["steps"][1] = {
            "t": 1,
            "day": e6["steps"][1]["day"],
            "tool": "bash",
            "args": {"command": "ls"},
            "result": {"ok": False, "error": "Model tried to call unavailable tool 'bash'."},
        }
        run_case(
            "R06",
            "client_refused_disguised_mid_call",
            "client_refused",
            "Disguise a mid-episode real Env call as OpenCode _OC_NO_TOOL to skip server execution",
            "v1.4/fuzz/hard",
            [json.dumps(e6)],
            {"tiers_version": "v1.4"},
            True,
            "canary/redteam/anticheat.py:615; canary/redteam/tamper_guard.py",
            "Blocked: skipping a mid-episode Env call shifts subsequent server state, and valid_client_only_step rejects spoof",
        )

        e7 = copy.deepcopy(ep_horizon)
        e7["steps"][-1] = {
            "t": len(e7["steps"]) - 1,
            "day": e7["steps"][-1]["day"],
            "tool": "bash",
            "args": {"command": "ls"},
            "result": {"ok": False, "error": "Model tried to call unavailable tool 'bash'."},
        }
        run_case(
            "R07",
            "client_refused_disguised_final_call",
            "client_refused",
            "Disguise the final non-accusing Env call of an episode as OpenCode _OC_NO_TOOL",
            "v1.4/fuzz/hard",
            [json.dumps(e7)],
            {"tiers_version": "v1.4"},
            True,
            "canary/redteam/tamper_guard.py; canary/redteam/anticheat.py:549-551",
            "Blocked in tamper_guard (valid_client_only_step and end_reason/env.done check); bypasses upstream anticheat",
        )

        e8_bad = copy.deepcopy(ep_wrong)
        e8_bad["meta"] = {
            **(e8_bad.get("meta") or {}),
            "valid": False,
            "error": "infra:provider_unavailable",
        }
        run_case(
            "R08",
            "flip_valid_false_wrong_accusation",
            "selective_dropping",
            "Flip meta.valid: true -> false on a completed -1.0 wrong accusation alongside a winning episode",
            "v1.4/fuzz/hard",
            [json.dumps(ep_win), json.dumps(e8_bad)],
            {"tiers_version": "v1.4"},
            True,
            "canary/redteam/tamper_guard.py; canary/reproduce.py:305-309",
            "Blocked in tamper_guard (rejects invalid flag on completed episode); upstream anticheat passes and audit_submission only WARNs",
        )

        e9 = copy.deepcopy(ep_win)
        for st in e9["steps"]:
            st["result"] = None
        run_case(
            "R09",
            "null_step_results_wiped",
            "step_tamper",
            "Set result=null on every recorded step in episodes.jsonl",
            "v1.4/fuzz/hard",
            [json.dumps(e9)],
            {"tiers_version": "v1.4"},
            True,
            "canary/redteam/tamper_guard.py; canary/redteam/anticheat.py:560",
            "Blocked in tamper_guard (requires non-null recorded step result); upstream anticheat allows want is None",
        )

        e10 = copy.deepcopy(ep_win)
        e10["score"] = round(float(ep_win["score"]) + 5e-7, 10)
        run_case(
            "R10",
            "float_perturb_5e_7",
            "numeric_perturbation",
            "Perturb recorded score by +5e-7 (inside 1e-6 replay tolerance)",
            "v1.4/fuzz/hard",
            [json.dumps(e10)],
            {"tiers_version": "v1.4"},
            True,
            "canary/redteam/anticheat.py:571",
            "Sub-1e-6 rounding tolerance band: abs(got - score) < 1e-6 allows +-9.99e-7 drift (+1e-5 is caught)",
        )

        e11 = copy.deepcopy(ep_win)
        e11["score"] = float(ep_win["score"]) + 1e-12
        run_case(
            "R11",
            "float_perturb_1e_12",
            "numeric_perturbation",
            "Perturb recorded score by +1e-12 (IEEE float rounding tolerance probe)",
            "v1.4/fuzz/hard",
            [json.dumps(e11)],
            {"tiers_version": "v1.4"},
            False,
            "canary/redteam/anticheat.py:571",
            "Accepted within 1e-6 float rounding band (harmless at 1e-12)",
        )

        e12 = copy.deepcopy(ep_win)
        e12["score"] = "__NAN_PLACEHOLDER__"
        nan_line = json.dumps(e12).replace('"__NAN_PLACEHOLDER__"', "NaN")
        run_case(
            "R12",
            "score_nan",
            "numeric_perturbation",
            "Set recorded score to JSON literal NaN",
            "v1.4/fuzz/hard",
            [nan_line],
            {"tiers_version": "v1.4"},
            True,
            "canary/redteam/anticheat.py:571; scripts/audit_submission.py:171",
            "Blocked: IEEE NaN < 1e-6 is False in anticheat and non-finite check fails in tamper_guard and audit_submission",
        )

        e13 = copy.deepcopy(ep_wrong)
        e13["correct"] = True
        e13_neg0 = copy.deepcopy(ep_horizon)
        neg0_line = json.dumps(e13_neg0).replace('"score": 0.0', '"score": -0.0')
        run_case(
            "R13",
            "neg_zero_and_flipped_correct_flag",
            "metadata_verdict_mismatch",
            "Set -0.0 on abstention and flip correct=true on a -1.0 wrong accusation without changing score/accused",
            "v1.4/fuzz/hard",
            [neg0_line, json.dumps(e13)],
            {"tiers_version": "v1.4"},
            True,
            "canary/redteam/tamper_guard.py; scripts/audit_submission.py:197",
            "Blocked in tamper_guard and audit_submission (verifies bool(e['correct']) == env.verdict()['correct'])",
        )

        e14 = copy.deepcopy(ep_win)
        e14["accused"] = "e00" if ep_win["accused"] != "e00" else "e01"
        run_case(
            "R14",
            "swapped_accused_id",
            "verdict_tamper",
            "Swap top-level accused employee ID without matching env verdict",
            "v1.4/fuzz/hard",
            [json.dumps(e14)],
            {"tiers_version": "v1.4"},
            True,
            "canary/redteam/anticheat.py:571",
            "Blocked: acc == e.get('accused') catches mismatched accused employee ID",
        )

        e15 = copy.deepcopy(ep_wrong)
        e15["steps"] = e15["steps"][:-1]
        e15["score"] = 0.0
        e15["accused"] = None
        e15["correct"] = False
        e15["end_reason"] = "horizon"
        run_case(
            "R15",
            "truncated_steps_drop_wrong_accuse",
            "step_truncation",
            "Truncate final -1.0 wrong accuse step and rewrite episode as score=0.0, accused=null, end_reason='horizon'",
            "v1.4/fuzz/hard",
            [json.dumps(e15)],
            {"tiers_version": "v1.4"},
            True,
            "canary/redteam/tamper_guard.py; canary/redteam/anticheat.py:564-571",
            "Blocked in tamper_guard (verifies end_reason/env.done/final_day and companion transcripts); bypasses upstream anticheat",
        )

        e16_unver = copy.deepcopy(v13_med_ep0)
        e16_unver["score"] = 0.99
        e16_unver["accused"] = "e01"
        e16_unver["correct"] = True
        run_case(
            "R16",
            "forged_meta_tiers_version",
            "version_spoofing",
            "Forge meta.tiers_version='v9.9' with fabricated score=0.99",
            "v9.9/fuzz/medium",
            [json.dumps(e16_unver)],
            {"tiers_version": "v9.9"},
            True,
            "canary/redteam/tamper_guard.py; canary/redteam/anticheat.py:541-544",
            "Blocked in tamper_guard (unknown tiers_version marks replay_consistent=False); upstream anticheat skips as not_replayable",
        )

        e17 = copy.deepcopy(ep_win)
        full_st0 = json.dumps(e17["steps"][0]["result"])
        rem17 = len(full_st0.encode("utf-8")) - 24
        e17["steps"][0]["result"] = {"raw": ("X" * 24) + f"[... truncated {rem17} bytes ...]"}
        run_case(
            "R17",
            "bracket_truncated_suffix_spoof",
            "bracket_truncation",
            "Replace step result with forged [... truncated N bytes ...] suffix on altered prefix",
            "v1.4/fuzz/hard",
            [json.dumps(e17)],
            {"tiers_version": "v1.4"},
            True,
            "canary/redteam/tamper_guard.py; canary/redteam/anticheat.py:560",
            "Blocked: valid_bracket_truncated_suffix verifies exact UTF-8 prefix and exact remaining byte count N",
        )

        return results
    finally:
        if created_base:
            shutil.rmtree(work_dir, ignore_errors=True)


def _verifier_python_src(tmp_dir: Path) -> str:
    sh = (ROOT / "harbor" / "template" / "tests" / "test.sh").read_text(encoding="utf-8")
    m = re.search(r"python3[^\n]*<<'PY'\n(.*?)\nPY", sh, re.S)
    assert m is not None
    py = m.group(1)
    return (
        py.replace("/logs/verifier", (tmp_dir / "logs").as_posix())
        .replace("/evidence", (tmp_dir / "evidence").as_posix())
        .replace("/tests/ledger_key", (tmp_dir / "tests/ledger_key").as_posix())
    )


def _run_harbor_verifier_py(tmp_dir: Path, raw_ledger: str | None, key_hex: str) -> dict[str, Any]:
    for sub in ("logs", "evidence", "tests"):
        (tmp_dir / sub).mkdir(parents=True, exist_ok=True)
    (tmp_dir / "tests/ledger_key").write_text(key_hex + "\n", encoding="utf-8")
    if raw_ledger is not None:
        (tmp_dir / "evidence/ledger.json").write_text(raw_ledger, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("CANARY_")}
    proc = subprocess.run(
        [sys.executable, "-I", "-S", "-c", _verifier_python_src(tmp_dir)],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    r_txt = (
        (tmp_dir / "logs/reward.txt").read_text(encoding="utf-8")
        if (tmp_dir / "logs/reward.txt").exists()
        else None
    )
    r_json = (
        json.loads((tmp_dir / "logs/reward.json").read_text(encoding="utf-8"))
        if (tmp_dir / "logs/reward.json").exists()
        else None
    )
    return {
        "rc": proc.returncode,
        "reward_txt": r_txt,
        "reward_json": r_json,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def fuzz_harbor_verifier(root: Path = ROOT, tmp_base: Path | None = None) -> list[dict[str, Any]]:
    from canary.mcp_server import sign_ledger
    from canary.redteam import anticheat as ac
    from canary.redteam import tamper_guard as tg

    key_hex = "ab" * 32
    base_ledger = {
        "score": 0.0,
        "done": True,
        "end_reason": "horizon",
        "accused": None,
        "final_day": 14,
        "V": 0.72,
        "tier": "medium",
        "episode": "0123456789abcdef",
        "ledger": [],
    }
    signed_zero = sign_ledger(base_ledger, key_hex)

    created_base = False
    if tmp_base is None:
        base_root = _default_tmp_root()
        base_root.mkdir(parents=True, exist_ok=True)
        work_dir = Path(tempfile.mkdtemp(prefix="harbor-fuzz-", dir=str(base_root)))
        created_base = True
    else:
        tmp_base.mkdir(parents=True, exist_ok=True)
        work_dir = tmp_base / "harbor_fuzz"
        work_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    try:

        def copy_job(case_id: str, job_name: str, single_trial: bool = True) -> tuple[Path, Path]:
            src_job = root / "results" / "harbor" / job_name
            dst_root = work_dir / case_id
            dst_job = dst_root / "results" / "harbor" / job_name
            if not single_trial:
                shutil.copytree(src_job, dst_job)
                trials = sorted(p.parent for p in dst_job.glob("*/result.json"))
                return dst_root, trials[0]
            dst_job.mkdir(parents=True, exist_ok=True)
            if (src_job / "ledger_key").is_file():
                shutil.copy2(src_job / "ledger_key", dst_job / "ledger_key")
            src_trial = sorted(p.parent for p in src_job.glob("*/result.json"))[0]
            dst_trial = dst_job / src_trial.name
            shutil.copytree(src_trial, dst_trial)
            return dst_root, dst_trial

        h1_vdir = work_dir / "H01_verifier"
        raw_dup_after = json.dumps(signed_zero)[:-1] + ', "score": 1.0}'
        v1 = _run_harbor_verifier_py(h1_vdir, raw_dup_after, key_hex)
        _, t1 = copy_job("H01_ac", "signed-stop_early")
        ret_key = (t1.parent / "ledger_key").read_text(encoding="utf-8").strip()
        orig_led = json.loads((t1 / "artifacts/ledger.json").read_text(encoding="utf-8"))
        signed_orig = sign_ledger({k: v for k, v in orig_led.items() if k != "sig"}, ret_key)
        dup_after_trial = json.dumps(signed_orig)[:-1] + ', "score": 1.0}'
        for nm in ("artifacts/ledger.json", "verifier/ledger.json"):
            (t1 / nm).write_text(dup_after_trial, encoding="utf-8")
        up1 = ac.check_harbor_trial(t1)
        tg1 = tg.check_harbor_trial(t1)
        results.append(
            {
                "id": "H01",
                "name": "ledger_dup_key_after_sig",
                "category": "json_duplicate_keys",
                "description": "Append duplicate 'score': 1.0 key AFTER 'sig' in HMAC-signed ledger.json",
                "verifier_caught": v1["rc"] != 0 and v1["reward_txt"] == "0",
                "upstream_anticheat_caught": up1["consistent"] is False,
                "tamper_guard_caught": tg1["consistent"] is False,
                "anticheat_caught": tg1["consistent"] is False,
                "bypass": False,
                "location": "harbor/template/tests/test.sh:106-109; canary/redteam/anticheat.py:742,776",
                "impact": "Blocked: Python json.loads last-key-wins sets body['score']=1.0, breaking HMAC verification",
            }
        )

        h2_vdir = work_dir / "H02_verifier"
        body_rest = json.dumps(signed_zero)[1:]
        raw_dup_before = '{"score": 1.0, ' + body_rest
        v2 = _run_harbor_verifier_py(h2_vdir, raw_dup_before, key_hex)
        written_ver_led = (h2_vdir / "logs/ledger.json").read_text(encoding="utf-8")
        _, t2 = copy_job("H02_ac", "cheat-probe")
        t2_raw = (t2 / "artifacts/ledger.json").read_text(encoding="utf-8").strip()
        dup_before_trial = '{"score": 1.0, ' + t2_raw[1:]
        for nm in ("artifacts/ledger.json", "verifier/ledger.json"):
            (t2 / nm).write_text(dup_before_trial, encoding="utf-8")
        up2 = ac.check_harbor_trial(t2)
        tg2 = tg.check_harbor_trial(t2)
        results.append(
            {
                "id": "H02",
                "name": "ledger_dup_key_before_score",
                "category": "json_duplicate_keys",
                "description": "Prepend duplicate 'score': 1.0 key BEFORE signed 'score': 0.0 and 'sig' in ledger.json",
                "verifier_caught": v2["rc"] != 0,
                "upstream_anticheat_caught": up2["consistent"] is False,
                "tamper_guard_caught": tg2["consistent"] is False,
                "anticheat_caught": tg2["consistent"] is False,
                "bypass": (v2["rc"] == 0 and written_ver_led.startswith('{"score": 1.0,'))
                and (tg2["consistent"] is True),
                "location": "canary/redteam/tamper_guard.py; harbor/template/tests/test.sh:95,118",
                "impact": "Blocked in tamper_guard (rejects duplicate JSON keys); Report-Only in protected test.sh",
            }
        )

        h3_vdir = work_dir / "H03_verifier"
        raw_trailing_garbage = json.dumps(signed_zero) + '\n{"score": 1.0}'
        v3 = _run_harbor_verifier_py(h3_vdir, raw_trailing_garbage, key_hex)
        _, t3 = copy_job("H03_ac", "cheat-probe")
        (t3 / "artifacts/ledger.json").write_text(
            (t3 / "artifacts/ledger.json").read_text(encoding="utf-8") + '\n{"score": 1.0}',
            encoding="utf-8",
        )
        up3 = ac.check_harbor_trial(t3)
        tg3 = tg.check_harbor_trial(t3)
        results.append(
            {
                "id": "H03",
                "name": "ledger_trailing_garbage_bytes",
                "category": "trailing_data",
                "description": "Append trailing second JSON object / garbage bytes after signed ledger.json",
                "verifier_caught": v3["rc"] != 0 and v3["reward_txt"] == "0",
                "upstream_anticheat_caught": up3["consistent"] is False,
                "tamper_guard_caught": tg3["consistent"] is False,
                "anticheat_caught": tg3["consistent"] is False,
                "bypass": False,
                "location": "harbor/template/tests/test.sh:95-97; canary/redteam/anticheat.py:733-736",
                "impact": "Blocked: json.loads raises JSONDecodeError (Extra data); verifier fails closed to reward 0",
            }
        )

        h4_vdir = work_dir / "H04_verifier"
        raw_trailing_nl = json.dumps(signed_zero) + "\n\n   \n"
        v4 = _run_harbor_verifier_py(h4_vdir, raw_trailing_nl, key_hex)
        _, t4 = copy_job("H04_ac", "cheat-probe")
        for nm in ("artifacts/ledger.json", "verifier/ledger.json"):
            (t4 / nm).write_text((t4 / nm).read_text(encoding="utf-8") + "\n\n  \n", encoding="utf-8")
        up4 = ac.check_harbor_trial(t4)
        tg4 = tg.check_harbor_trial(t4)
        results.append(
            {
                "id": "H04",
                "name": "ledger_trailing_newlines",
                "category": "trailing_data",
                "description": "Append trailing newlines and ASCII whitespace after signed ledger.json",
                "verifier_caught": v4["rc"] != 0,
                "upstream_anticheat_caught": up4["consistent"] is False,
                "tamper_guard_caught": tg4["consistent"] is False,
                "anticheat_caught": tg4["consistent"] is False,
                "bypass": False,
                "location": "harbor/template/tests/test.sh:95,107; canary/redteam/anticheat.py:680",
                "impact": "Benign whitespace accepted cleanly: canonical JSON HMAC re-serializes body with exact score",
            }
        )

        h5_vdir = work_dir / "H05_verifier"
        (h5_vdir / "logs").mkdir(parents=True, exist_ok=True)
        ext_txt = h5_vdir / "external_reward.txt"
        ext_json = h5_vdir / "external_reward.json"
        ext_txt.write_text("UNTOUCHED", encoding="utf-8")
        ext_json.write_text('{"untouched": true}', encoding="utf-8")
        (h5_vdir / "logs/reward.txt").symlink_to(ext_txt)
        (h5_vdir / "logs/reward.json").symlink_to(ext_json)
        _run_harbor_verifier_py(h5_vdir, json.dumps(signed_zero), key_hex)
        verifier_followed_symlink = (
            (h5_vdir / "logs/reward.txt").is_symlink()
            and ext_txt.read_text(encoding="utf-8") == "0.0"
        )

        _, t5 = copy_job("H05_ac", "signed-stop_early")
        outside_txt = work_dir / "H05_outside_reward.txt"
        outside_json = work_dir / "H05_outside_reward.json"
        outside_txt.write_text((t5 / "verifier/reward.txt").read_text(encoding="utf-8"), encoding="utf-8")
        outside_json.write_text((t5 / "verifier/reward.json").read_text(encoding="utf-8"), encoding="utf-8")
        (t5 / "verifier/reward.txt").unlink()
        (t5 / "verifier/reward.json").unlink()
        (t5 / "verifier/reward.txt").symlink_to(outside_txt)
        (t5 / "verifier/reward.json").symlink_to(outside_json)
        up5 = ac.check_harbor_trial(t5)
        tg5 = tg.check_harbor_trial(t5)
        results.append(
            {
                "id": "H05",
                "name": "symlinked_reward_txt_and_json",
                "category": "symlink_hygiene",
                "description": "Replace verifier/reward.txt and verifier/reward.json with symlinks to external files",
                "verifier_caught": not verifier_followed_symlink,
                "upstream_anticheat_caught": up5["consistent"] is False,
                "tamper_guard_caught": tg5["consistent"] is False,
                "anticheat_caught": tg5["consistent"] is False,
                "bypass": verifier_followed_symlink and (tg5["consistent"] is True),
                "location": "canary/redteam/tamper_guard.py; harbor/template/tests/test.sh:41,68-69,119-120",
                "impact": "Blocked in tamper_guard (rejects symlinked trial artifacts); Report-Only in protected test.sh",
            }
        )

        _, t6 = copy_job("H06_ac", "signed-stop_early")
        (t6 / "verifier/reward.json").write_text('{"reward": 1.0}', encoding="utf-8")
        up6 = ac.check_harbor_trial(t6)
        tg6 = tg.check_harbor_trial(t6)
        results.append(
            {
                "id": "H06",
                "name": "mismatch_reward_txt_vs_reward_json",
                "category": "reward_disagreement",
                "description": "Set verifier/reward.json={'reward': 1.0} while verifier/reward.txt and ledger stay -1.0",
                "verifier_caught": None,
                "upstream_anticheat_caught": up6["consistent"] is False,
                "tamper_guard_caught": tg6["consistent"] is False,
                "anticheat_caught": tg6["consistent"] is False,
                "bypass": False,
                "location": "canary/redteam/anticheat.py:717-743",
                "impact": "Blocked: check_harbor_trial compares result.json, reward.txt, reward.json, test-stdout, and ledgers",
            }
        )

        _, t7 = copy_job("H07_ac", "cheat-probe")
        (t7 / "agent/isolation.txt").unlink()
        up7 = ac.check_harbor_trial(t7)
        tg7 = tg.check_harbor_trial(t7)
        results.append(
            {
                "id": "H07",
                "name": "missing_isolation_txt",
                "category": "isolation_report",
                "description": "Delete agent/isolation.txt from an ORACLE_POLICY=cheat_probe solve.sh trial",
                "verifier_caught": None,
                "upstream_anticheat_caught": up7["consistent"] is False,
                "tamper_guard_caught": tg7["consistent"] is False,
                "anticheat_caught": tg7["consistent"] is False,
                "bypass": tg7["consistent"] is True,
                "location": "canary/redteam/tamper_guard.py; canary/redteam/anticheat.py:798-800",
                "impact": "Blocked in tamper_guard (requires agent/isolation.txt for non-opencode trials); upstream only checks if file exists",
            }
        )

        _, t8 = copy_job("H08_ac", "cheat-probe")
        rep8 = json.loads((t8 / "agent/cheat.json").read_text(encoding="utf-8"))
        rep8["holes"] = ["x"]
        (t8 / "agent/cheat.json").write_text(json.dumps(rep8), encoding="utf-8")
        up8 = ac.check_harbor_trial(t8)
        tg8 = tg.check_harbor_trial(t8)
        results.append(
            {
                "id": "H08",
                "name": "cheat_probe_with_holes",
                "category": "cheat_probe",
                "description": "Set holes=['x'] inside agent/cheat.json on a cheat_probe trial",
                "verifier_caught": None,
                "upstream_anticheat_caught": up8["consistent"] is False,
                "tamper_guard_caught": tg8["consistent"] is False,
                "anticheat_caught": tg8["consistent"] is False,
                "bypass": False,
                "location": "canary/redteam/anticheat.py:792-793",
                "impact": "Blocked: check_harbor_trial flags any non-empty holes list in agent/cheat.json",
            }
        )

        _, t9 = copy_job("H09_ac", "cheat-probe")
        (t9 / "agent/cheat.json").unlink()
        up9 = ac.check_harbor_trial(t9)
        tg9 = tg.check_harbor_trial(t9)
        results.append(
            {
                "id": "H09",
                "name": "cheat_probe_missing_cheat_json",
                "category": "cheat_probe",
                "description": "Delete agent/cheat.json from a cheat_probe trial while config.json remains intact",
                "verifier_caught": None,
                "upstream_anticheat_caught": up9["consistent"] is False,
                "tamper_guard_caught": tg9["consistent"] is False,
                "anticheat_caught": tg9["consistent"] is False,
                "bypass": False,
                "location": "canary/redteam/anticheat.py:781-782",
                "impact": "Blocked when config.json is intact: policy=='cheat_probe' requires agent/cheat.json",
            }
        )

        _, t10 = copy_job("H10_ac", "cheat-probe")
        (t10 / "agent/cheat.json").unlink()
        (t10 / "config.json").unlink()
        up10 = ac.check_harbor_trial(t10)
        tg10 = tg.check_harbor_trial(t10)
        results.append(
            {
                "id": "H10",
                "name": "cheat_probe_missing_config_and_cheat_json",
                "category": "cheat_probe",
                "description": "Delete both config.json and agent/cheat.json on a cheat_probe trial",
                "verifier_caught": None,
                "upstream_anticheat_caught": up10["consistent"] is False,
                "tamper_guard_caught": tg10["consistent"] is False,
                "anticheat_caught": tg10["consistent"] is False,
                "bypass": tg10["consistent"] is True,
                "location": "canary/redteam/tamper_guard.py; canary/redteam/anticheat.py:662-669,781",
                "impact": "Blocked in tamper_guard (requires readable JSON config.json on every trial); bypasses upstream _trial_policy",
            }
        )

        r11_root, _ = copy_job("H11_ac", "oracle", single_trial=False)
        job11 = r11_root / "results" / "harbor" / "oracle"
        j11_data = json.loads((job11 / "result.json").read_text(encoding="utf-8"))
        ev11 = next(iter(j11_data["stats"]["evals"].values()))
        ev11["metrics"][0]["mean"] = 0.99
        ev11["n_errors"] = 3
        (job11 / "result.json").write_text(json.dumps(j11_data), encoding="utf-8")
        up11 = next(r for r in ac.harbor_consistency(r11_root) if r["kind"] == "job")
        tg11 = next(r for r in tg.harbor_consistency(r11_root) if r["kind"] == "job")
        results.append(
            {
                "id": "H11",
                "name": "tampered_job_result_mean_and_n_errors",
                "category": "job_summary",
                "description": "Tamper job-level result.json metrics[0].mean=0.99 and n_errors=3",
                "verifier_caught": None,
                "upstream_anticheat_caught": up11["consistent"] is False,
                "tamper_guard_caught": tg11["consistent"] is False,
                "anticheat_caught": tg11["consistent"] is False,
                "bypass": False,
                "location": "canary/redteam/anticheat.py:834-841",
                "impact": "Blocked: check_harbor_job recomputes n_errors and mean from trial rows",
            }
        )

        r12_root, _ = copy_job("H12_ac", "signed-cheat", single_trial=False)
        job12 = r12_root / "results" / "harbor" / "signed-cheat"
        trial_dirs = sorted(p.parent for p in job12.glob("*/result.json"))
        neg_trial = next(
            td
            for td in trial_dirs
            if float(
                json.loads((td / "result.json").read_text(encoding="utf-8"))["verifier_result"]["rewards"][
                    "reward"
                ]
            )
            < 0
        )
        tr_res = json.loads((neg_trial / "result.json").read_text(encoding="utf-8"))
        tr_res["verifier_result"] = {"rewards": {"reward": None}}
        tr_res["exception_info"] = {
            "exception_type": "AgentTimeoutError",
            "exception_message": "forged timeout",
        }
        (neg_trial / "result.json").write_text(json.dumps(tr_res), encoding="utf-8")

        j12_data = json.loads((job12 / "result.json").read_text(encoding="utf-8"))
        ev12 = next(iter(j12_data["stats"]["evals"].values()))
        kept_rewards: list[float] = []
        new_buckets: dict[str, list[str]] = defaultdict(list)
        n_exc12 = 0
        for td in trial_dirs:
            d = json.loads((td / "result.json").read_text(encoding="utf-8"))
            if d.get("exception_info"):
                n_exc12 += 1
            rw = ((d.get("verifier_result") or {}).get("rewards") or {}).get("reward")
            if rw is not None:
                kept_rewards.append(float(rw))
                new_buckets[str(rw)].append(td.name)
        ev12["n_errors"] = n_exc12
        ev12["metrics"][0]["mean"] = sum(kept_rewards) / len(kept_rewards) if kept_rewards else 0.0
        ev12["reward_stats"]["reward"] = dict(new_buckets)
        (job12 / "result.json").write_text(json.dumps(j12_data), encoding="utf-8")

        up12_all_ok = all(r["consistent"] is not False for r in ac.harbor_consistency(r12_root))
        tg12_all_ok = all(r["consistent"] is not False for r in tg.harbor_consistency(r12_root))
        results.append(
            {
                "id": "H12",
                "name": "null_trial_reward_hides_signed_wrong_accuse",
                "category": "selective_trial_dropping",
                "description": "Null out verifier_result.rewards.reward + set exception_info on a -1.0 trial while leaving ledger.json=-1.0 intact",
                "verifier_caught": None,
                "upstream_anticheat_caught": not up12_all_ok,
                "tamper_guard_caught": not tg12_all_ok,
                "anticheat_caught": not tg12_all_ok,
                "bypass": tg12_all_ok,
                "location": "canary/redteam/tamper_guard.py; canary/redteam/anticheat.py:698-711",
                "impact": "Blocked in tamper_guard (inspects sidecar/verifier ledgers when reward is None); bypasses upstream anticheat",
            }
        )

        h13_root = work_dir / "H13_ac"
        dst_reh = h13_root / "results" / "harbor" / "rehearsal-dry"
        src_reh = root / "results" / "harbor" / "rehearsal-dry"
        for jname in ("opencode", "opencode-infra-rerun"):
            src_j = src_reh / jname
            dst_j = dst_reh / jname
            dst_j.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_j / "ledger_key", dst_j / "ledger_key")
            for tr_res in sorted(src_j.glob("*/result.json")):
                if "900005" in tr_res.parent.name or "900006" in tr_res.parent.name:
                    shutil.copytree(tr_res.parent, dst_j / tr_res.parent.name)
            shutil.copy2(src_j / "result.json", dst_j / "result.json")

        fake_rerun = dst_reh / "opencode-infra-rerun" / "canary-hard-900005__forged"
        shutil.copytree(
            next((dst_reh / "opencode-infra-rerun").glob("canary-hard-900006*")),
            fake_rerun,
        )
        fr_res = json.loads((fake_rerun / "result.json").read_text(encoding="utf-8"))
        fr_res["task_name"] = "canary/hard-900005"
        fr_res["trial_name"] = "canary-hard-900005__forged"
        (fake_rerun / "result.json").write_text(json.dumps(fr_res), encoding="utf-8")

        for jdir in (dst_reh / "opencode", dst_reh / "opencode-infra-rerun"):
            j_obj = json.loads((jdir / "result.json").read_text(encoding="utf-8"))
            ev_obj = next(iter(j_obj["stats"]["evals"].values()))
            t_dirs = sorted(p.parent for p in jdir.glob("*/result.json"))
            exc_map: dict[str, list[str]] = defaultdict(list)
            rew_map: dict[str, list[str]] = defaultdict(list)
            scored_vals: list[float] = []
            for td in t_dirs:
                td_res = json.loads((td / "result.json").read_text(encoding="utf-8"))
                et = (td_res.get("exception_info") or {}).get("exception_type")
                if et:
                    exc_map[et].append(td.name)
                if et in {"ApiRateLimitError", "AgentSetupTimeoutError"}:
                    continue
                rw = float(td_res["verifier_result"]["rewards"]["reward"])
                scored_vals.append(rw)
                rew_map[str(rw)].append(td.name)
            ev_obj["n_trials"] = len(scored_vals)
            ev_obj["n_errors"] = sum(len(v) for v in exc_map.values())
            ev_obj["metrics"][0]["mean"] = sum(scored_vals) / len(scored_vals)
            ev_obj["reward_stats"]["reward"] = dict(rew_map)
            ev_obj["exception_stats"] = dict(exc_map)
            (jdir / "result.json").write_text(json.dumps(j_obj), encoding="utf-8")

        up13_all_ok = all(r["consistent"] is not False for r in ac.harbor_consistency(h13_root))
        tg13_all_ok = all(r["consistent"] is not False for r in tg.harbor_consistency(h13_root))
        results.append(
            {
                "id": "H13",
                "name": "rehearsal_rerun_cherry_picks_valid_loss",
                "category": "rehearsal_rerun_integrity",
                "description": "Add forged opencode-infra-rerun entry replacing completed -1.0 trial hard-900005 and update job stats",
                "verifier_caught": None,
                "upstream_anticheat_caught": not up13_all_ok,
                "tamper_guard_caught": not tg13_all_ok,
                "anticheat_caught": not tg13_all_ok,
                "bypass": tg13_all_ok,
                "location": "canary/redteam/tamper_guard.py; scripts/rehearsal_table.py:99-103",
                "impact": "Blocked in tamper_guard (_check_rerun_job_pair rejects rerun tasks whose base trial was completed/non-infra)",
            }
        )

        _, t14 = copy_job("H14_ac", "signed-stop_early")
        ret_key14 = (t14.parent / "ledger_key").read_text(encoding="utf-8").strip()
        for rel in ("artifacts/ledger.json", "verifier/ledger.json"):
            d14 = json.loads((t14 / rel).read_text(encoding="utf-8"))
            ev14 = next(x for x in d14["ledger"] if x["event"] == "accused")
            ev14["detail"]["employee"] = "e00"
            d14["accused"] = "e00"
            signed14 = sign_ledger({k: v for k, v in d14.items() if k != "sig"}, ret_key14)
            (t14 / rel).write_text(json.dumps(signed14), encoding="utf-8")
        up14 = ac.check_harbor_trial(t14)
        tg14 = tg.check_harbor_trial(t14)
        results.append(
            {
                "id": "H14",
                "name": "retired_key_resigned_accused_swap",
                "category": "retired_key_resigning",
                "description": "Swap accused employee in ledger.json and re-sign with published retired ledger_key while agent/solver.txt stays original",
                "verifier_caught": None,
                "upstream_anticheat_caught": up14["consistent"] is False,
                "tamper_guard_caught": tg14["consistent"] is False,
                "anticheat_caught": tg14["consistent"] is False,
                "bypass": tg14["consistent"] is True,
                "location": "canary/redteam/tamper_guard.py; canary/redteam/anticheat.py:774-779",
                "impact": "Blocked in tamper_guard (_check_harbor_agent_logs catches solver.txt/opencode.txt mismatch and emits retired_key_resign_notice)",
            }
        )

        return results
    finally:
        if created_base:
            shutil.rmtree(work_dir, ignore_errors=True)


def run_full_audit(root: Path = ROOT, tmp_base: Path | None = None) -> dict[str, Any]:
    from canary.redteam import anticheat as ac
    from canary.redteam import tamper_guard as tg

    t0 = time.monotonic()
    data_audit = audit_data_rules(root)
    replay_matrix = fuzz_replay_checker(root, tmp_base=tmp_base)
    harbor_matrix = fuzz_harbor_verifier(root, tmp_base=tmp_base)

    live_replay = tg.replay_committed(root)
    live_replay_counts = ac.replay_counts(live_replay)
    live_harbor = tg.harbor_consistency(root)
    live_trials = [r for r in live_harbor if r.get("kind") == "trial"]
    live_jobs = [r for r in live_harbor if r.get("kind") == "job"]

    rehearsal_dir = root / "results" / "harbor" / "rehearsal-dry"
    rehearsal_dry = (
        tg.verify_rehearsal_run(rehearsal_dir, repo_root=root)
        if rehearsal_dir.is_dir()
        else {"passed": None, "problems": []}
    )
    elapsed_s = round(time.monotonic() - t0, 3)

    replay_bypasses = [r for r in replay_matrix if r["bypass"]]
    harbor_bypasses = [r for r in harbor_matrix if r["bypass"]]
    return {
        "elapsed_s": elapsed_s,
        "data_rule_audit": data_audit,
        "live_tamper_guard": {
            "replay_files": len(live_replay),
            "replay_all_consistent": all(r["replay_consistent"] is not False for r in live_replay),
            "replay_counts": live_replay_counts,
            "harbor_jobs": len(live_jobs),
            "harbor_trials": len(live_trials),
            "harbor_all_consistent": all(r["consistent"] is not False for r in live_harbor),
            "harbor_retired_key_resign_notices": sum(
                1 for r in live_trials if r.get("retired_key_resign_notice")
            ),
        },
        "rehearsal_dry_audit": rehearsal_dry,
        "replay_mutations": replay_matrix,
        "harbor_mutations": harbor_matrix,
        "summary": {
            "data_rule_passed": data_audit["passed"],
            "rehearsal_dry_passed": rehearsal_dry["passed"],
            "replay_mutations_total": len(replay_matrix),
            "replay_mutations_caught_by_upstream_anticheat": sum(
                1 for r in replay_matrix if r["upstream_anticheat_caught"]
            ),
            "replay_mutations_caught_by_anticheat": sum(
                1 for r in replay_matrix if r["tamper_guard_caught"]
            ),
            "replay_bypasses_found": len(replay_bypasses),
            "replay_bypass_ids": [r["id"] for r in replay_bypasses],
            "harbor_mutations_total": len(harbor_matrix),
            "harbor_mutations_caught_by_upstream_anticheat": sum(
                1 for r in harbor_matrix if r["upstream_anticheat_caught"]
            ),
            "harbor_mutations_caught_by_anticheat": sum(
                1 for r in harbor_matrix if r["tamper_guard_caught"]
            ),
            "harbor_bypasses_found": len(harbor_bypasses),
            "harbor_bypass_ids": [r["id"] for r in harbor_bypasses],
            "total_mutations": len(replay_matrix) + len(harbor_matrix),
            "total_bypasses": len(replay_bypasses) + len(harbor_bypasses),
        },
    }


def format_markdown_summary(report: dict[str, Any]) -> str:
    da = report["data_rule_audit"]
    lt = report["live_tamper_guard"]
    rd = report["rehearsal_dry_audit"]
    sm = report["summary"]
    lines: list[str] = []
    lines.append(f"DATA-RULE Audit: {'PASS' if da['passed'] else 'FAIL'}")
    lines.append(
        f"Active committed files: {da['active_files']} | episodes: {da['active_episodes']} "
        f"(valid={da['active_valid']}, invalid={da['active_invalid']}) | violations={len(da['violations'])}"
    )
    lines.append(
        f"Superseded files: {da['superseded']['n_files']} | episodes: {da['superseded']['n_episodes']} "
        f"| Judge table episodes: {da['judge_episodes_total']}"
    )
    lines.append(
        f"Live Tamper-Guard: replay {lt['replay_counts']['consistent']}/{lt['replay_counts']['replayed']} "
        f"consistent ({lt['replay_counts']['steps']} steps, 0 mismatches); "
        f"Harbor {lt['harbor_jobs']} jobs / {lt['harbor_trials']} trials consistent "
        f"({lt['harbor_retired_key_resign_notices']} retired-key re-sign notices); "
        f"rehearsal-dry={'PASS' if rd['passed'] else 'FAIL'}"
    )
    lines.append(
        f"Mutation Fuzzing ({sm['total_mutations']} classes in {report['elapsed_s']}s): "
        f"Replay {sm['replay_mutations_caught_by_anticheat']}/{sm['replay_mutations_total']} caught by tamper_guard "
        f"(upstream anticheat {sm['replay_mutations_caught_by_upstream_anticheat']}/{sm['replay_mutations_total']}, "
        f"{sm['replay_bypasses_found']} residual tolerance: {', '.join(sm['replay_bypass_ids'])}); "
        f"Harbor {sm['harbor_mutations_caught_by_anticheat']}/{sm['harbor_mutations_total']} caught by tamper_guard "
        f"(upstream anticheat {sm['harbor_mutations_caught_by_upstream_anticheat']}/{sm['harbor_mutations_total']}, "
        f"{sm['harbor_bypasses_found']} bypasses)"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Lane C1 DATA-RULE audit and replay/Harbor tamper-resistance fuzzing."
    )
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    report = run_full_audit(root=args.root.resolve())
    if args.json:
        print(json.dumps(report, indent=2, allow_nan=False))
    else:
        print(format_markdown_summary(report))
    ok = report["data_rule_audit"]["passed"] and (report["rehearsal_dry_audit"]["passed"] is not False)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
