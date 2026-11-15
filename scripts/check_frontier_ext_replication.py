"""Fast keyless CLI verifier for v1.4 gemini-4-carbon hard seeds 30-59 replication artifacts."""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from multiprocessing import get_all_start_methods, get_context
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EXPECTED_FLEET_SEEDS = [30, 34, 42, 45, 48, 57, 58]
EXPECTED_COMMITTED_EXT_SEEDS = [34, 37]
EXPECTED_DEDUP_EXT8_SEEDS = [30, 34, 37, 42, 45, 48, 57, 58]
EXPECTED_REF_SEEDS = list(range(30, 60))
CARBON_AGENT = "opencode:google/gemini-4-carbon"

_WORK_EPS: list[dict[str, Any]] = []
_N_REPLAY = 0
_N_ATTR = 0


EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)


def _sanitize_dashes(text: str) -> str:
    return text.replace(EM_DASH, "--").replace(EN_DASH, "-")


def _read_jsonl_dir(dir_path: Path) -> list[dict[str, Any]]:
    eps: list[dict[str, Any]] = []
    if not dir_path.exists():
        return eps
    if dir_path.is_file():
        files = [dir_path]
    else:
        files = sorted(
            Path(root) / "episodes.jsonl"
            for root, _dirs, names in os.walk(dir_path, followlinks=True)
            if "episodes.jsonl" in names
        )
    for fpath in files:
        if dir_path.is_dir():
            rel = fpath.relative_to(dir_path).parts[:-1]
            if any(x == "superseded" or x.startswith("v1.") or x.endswith("-smoke") for x in rel):
                continue
        run_id = fpath.parent.name
        for line in fpath.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            ep = json.loads(line)
            if (ep.get("meta") or {}).get("valid") is False:
                continue
            ep.setdefault("meta", {})["run_id"] = run_id
            eps.append(ep)
    return eps


def _worker_episode(idx: int) -> tuple[int, tuple[float, Any, bool, int] | None, list[dict[str, Any]] | None, dict[str, Any] | None]:
    from canary import rules
    from canary.analysis.accuse import audit_episode
    from canary.analysis.tags import to_result
    from canary.env import Env
    from canary.solver.regret import attribute

    ep = _WORK_EPS[idx]
    rep: tuple[float, Any, bool, int] | None = None
    with rules.tiers_version("v1.4"):
        if idx < _N_REPLAY:
            env = Env(ep["tier"], ep["seed"])
            for step in ep.get("steps") or []:
                if env.done:
                    break
                env.call(step["tool"], step.get("args") or {})
            res = env.result("replay")
            rep = (res.score, res.accused, bool(res.correct), res.final_day)
        ep_res = to_result(ep)
        att = attribute(ep_res) if idx < _N_ATTR else None
        aud = audit_episode(ep_res) if (idx < _N_ATTR or ep.get("accused")) else None
    return idx, rep, att, aud


def _deep_diff(expected: Any, actual: Any, path: str = "$", tol: float = 1e-9) -> list[str]:
    if isinstance(expected, bool) or isinstance(actual, bool):
        if type(expected) is not type(actual) or expected != actual:
            return [f"{path}: expected {expected!r}, got {actual!r}"]
        return []
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        fe, fa = float(expected), float(actual)
        if math.isnan(fe) and math.isnan(fa):
            return []
        if math.isnan(fe) != math.isnan(fa) or abs(fe - fa) > tol:
            return [f"{path}: expected {expected!r}, got {actual!r}"]
        return []
    if type(expected) is not type(actual):
        return [f"{path}: type mismatch expected {type(expected).__name__}, got {type(actual).__name__}"]
    if isinstance(expected, dict):
        errs: list[str] = []
        exp_keys = set(expected.keys())
        act_keys = set(actual.keys())
        for missing in sorted(exp_keys - act_keys):
            errs.append(f"{path}.{missing}: missing key in file")
        for extra in sorted(act_keys - exp_keys):
            errs.append(f"{path}.{extra}: unexpected key in file")
        for key in sorted(exp_keys & act_keys):
            errs.extend(_deep_diff(expected[key], actual[key], f"{path}.{key}", tol))
            if len(errs) >= 10:
                break
        return errs
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return [f"{path}: length mismatch expected {len(expected)}, got {len(actual)}"]
        errs = []
        for idx, ( item_e, item_a ) in enumerate(zip(expected, actual)):
            errs.extend(_deep_diff(item_e, item_a, f"{path}[{idx}]", tol))
            if len(errs) >= 10:
                break
        return errs
    if expected != actual:
        return [f"{path}: expected {expected!r}, got {actual!r}"]
    return []


def verify_frontier_ext_replication(repo: Path | str = ROOT, procs: int | None = None) -> dict[str, Any]:
    global _WORK_EPS, _N_REPLAY, _N_ATTR
    t0 = time.perf_counter()
    os.environ.setdefault("CANARY_ALLOW_DEV", "1")

    from canary.analysis.accuse import to_md as accuse_to_md
    from canary.analysis.gap import mean_ci
    from canary.analysis.tags import tag_report
    from scripts.paired_gemini import ALT_LABEL, empty_reply_seeds, groups
    from scripts.paired_v13 import boot_ratio

    repo_path = Path(repo).resolve()
    ext_root = repo_path / "results" / "frontier_replication" / "v1.4" / "opencode-gemini-4-carbon-ext"
    comm_root = repo_path / "data" / "runs" / "committed"
    comm_ext_dir = comm_root / "v1.4" / "opencode-gemini-4-carbon-ext"
    ref_30_59_dir = comm_root / "v1.4" / "reference" / "solver-hard-seeds30to59"

    checks: list[dict[str, Any]] = []

    manifest_errs: list[str] = []
    fleet_ep_file = ext_root / "hard" / "episodes.jsonl"
    fleet_meta_file = ext_root / "hard" / "meta.json"
    comm_ep_file = comm_ext_dir / "hard" / "episodes.jsonl"
    ref_ep_file = ref_30_59_dir / "episodes.jsonl"

    for req in (fleet_ep_file, fleet_meta_file, comm_ep_file, ref_ep_file):
        if not req.is_file():
            manifest_errs.append(f"missing required file: {req.relative_to(repo_path)}")

    fleet_eps = _read_jsonl_dir(fleet_ep_file) if fleet_ep_file.is_file() else []
    comm_ext_eps = _read_jsonl_dir(comm_ep_file) if comm_ep_file.is_file() else []
    ref_30_59 = _read_jsonl_dir(ref_ep_file) if ref_ep_file.is_file() else []

    fleet_seeds = [ep.get("seed") for ep in fleet_eps]
    comm_seeds = [ep.get("seed") for ep in comm_ext_eps]
    ref_seeds = [ep.get("seed") for ep in ref_30_59]

    if fleet_seeds != EXPECTED_FLEET_SEEDS:
        manifest_errs.append(f"fleet seeds {fleet_seeds} != expected {EXPECTED_FLEET_SEEDS}")
    if comm_seeds not in (EXPECTED_COMMITTED_EXT_SEEDS, EXPECTED_DEDUP_EXT8_SEEDS):
        manifest_errs.append(
            f"committed ext seeds {comm_seeds} not in ({EXPECTED_COMMITTED_EXT_SEEDS}, {EXPECTED_DEDUP_EXT8_SEEDS})"
        )
    comm_g1_eps = [ep for ep in comm_ext_eps if ep.get("seed") in EXPECTED_COMMITTED_EXT_SEEDS]
    comm_g1_seeds = [ep.get("seed") for ep in comm_g1_eps]
    if comm_g1_seeds != EXPECTED_COMMITTED_EXT_SEEDS:
        manifest_errs.append(f"committed G1 seeds {comm_g1_seeds} != expected {EXPECTED_COMMITTED_EXT_SEEDS}")
    if ref_seeds != EXPECTED_REF_SEEDS:
        manifest_errs.append(f"solver 30-59 seeds {ref_seeds} != expected 30..59")

    for label, eps, exp_agent in (
        ("fleet", fleet_eps, CARBON_AGENT),
        ("committed_ext", comm_ext_eps, CARBON_AGENT),
        ("ref_30_59", ref_30_59, "solver"),
    ):
        for ep in eps:
            if ep.get("tier") != "hard" or ep.get("agent") != exp_agent:
                manifest_errs.append(
                    f"{label} seed={ep.get('seed')}: unexpected tier={ep.get('tier')!r} agent={ep.get('agent')!r}"
                )

    if fleet_meta_file.is_file():
        meta_obj = json.loads(fleet_meta_file.read_text(encoding="utf-8"))
        if meta_obj.get("tier") != "hard" or meta_obj.get("tiers_version") != "v1.4":
            manifest_errs.append("fleet hard/meta.json tier or tiers_version mismatch")
        if meta_obj.get("seeds") != EXPECTED_FLEET_SEEDS:
            manifest_errs.append(f"fleet hard/meta.json seeds {meta_obj.get('seeds')} != {EXPECTED_FLEET_SEEDS}")

    tr_dir = ext_root / "hard" / "transcripts"
    if not tr_dir.is_dir():
        manifest_errs.append("missing fleet hard/transcripts directory")
    else:
        tr_names = sorted(p.name for p in tr_dir.iterdir() if p.is_file() and p.stat().st_size > 0)
        exp_tr = sorted(f"{s}.txt" for s in EXPECTED_FLEET_SEEDS)
        if tr_names != exp_tr:
            manifest_errs.append(f"transcript files {tr_names} != expected {exp_tr}")

    comm_g1_by_seed = {int(ep["seed"]): ep for ep in comm_g1_eps if isinstance(ep.get("seed"), int)}
    dedup_by_seed = {int(ep["seed"]): ep for ep in fleet_eps if isinstance(ep.get("seed"), int)}
    for seed, ep in comm_g1_by_seed.items():
        dedup_by_seed[seed] = ep
    ext8_eps = [dedup_by_seed[s] for s in sorted(dedup_by_seed)]
    ext8_seeds = [ep["seed"] for ep in ext8_eps]
    if ext8_seeds != EXPECTED_DEDUP_EXT8_SEEDS:
        manifest_errs.append(f"deduplicated ext8 seeds {ext8_seeds} != expected {EXPECTED_DEDUP_EXT8_SEEDS}")
    if comm_seeds == EXPECTED_DEDUP_EXT8_SEEDS:
        for ep in comm_ext_eps:
            seed = ep.get("seed")
            ref_ep = dedup_by_seed.get(seed) if isinstance(seed, int) else None
            if (
                ref_ep is None
                or abs(float(ep["score"]) - float(ref_ep["score"])) > 1e-9
                or ep.get("accused") != ref_ep.get("accused")
                or bool(ep.get("correct", False)) != bool(ref_ep.get("correct", False))
                or ep.get("final_day") != ref_ep.get("final_day")
            ):
                manifest_errs.append(f"committed ext8 seed={seed} mismatch vs dedup_by_seed[{seed}]")
    overlap = sorted(set(fleet_seeds) & set(EXPECTED_COMMITTED_EXT_SEEDS))
    if overlap != [34]:
        manifest_errs.append(f"expected overlap [34] between fleet and committed G1, got {overlap}")
    elif 34 not in comm_g1_by_seed or dedup_by_seed.get(34) is not comm_g1_by_seed[34]:
        manifest_errs.append("deduplication did not keep committed G1 episode on overlapping seed 34")

    checks.append({
        "name": "manifests_and_dedup",
        "passed": not manifest_errs,
        "summary": (
            f"fleet={len(fleet_eps)}, committed_ext={len(comm_ext_eps)} (g1={len(comm_g1_eps)}), "
            f"solver_ref={len(ref_30_59)}, dedup_ext8={ext8_seeds}"
        ),
        "errors": manifest_errs,
    })

    oc_primary = _read_jsonl_dir(comm_root / "v1.4" / "opencode-gemini-4-carbon")
    ip_primary = _read_jsonl_dir(comm_root / "v1.4" / "inproc-gemini-4-carbon")
    fl_primary = _read_jsonl_dir(comm_root / "v1.4" / "opencode-gemini-3.5-flash")
    ref_other: list[dict[str, Any]] = []
    ref_parent = comm_root / "v1.4" / "reference"
    if ref_parent.is_dir():
        for sub_dir in sorted(ref_parent.iterdir()):
            if not sub_dir.is_dir() or sub_dir.name == "solver-hard-seeds30to59":
                continue
            if any(sub_dir.name.startswith(prefix + "-") for prefix in ("solver", "heuristic", "do_nothing", "stop_early")):
                ref_other.extend(_read_jsonl_dir(sub_dir))

    comm_g1_ids = {id(ep) for ep in comm_g1_eps}
    comm_extra_eps = [ep for ep in comm_ext_eps if id(ep) not in comm_g1_ids]
    _N_ATTR = len(fleet_eps) + len(comm_g1_eps)
    _N_REPLAY = _N_ATTR + len(comm_extra_eps) + len(ref_30_59)
    _WORK_EPS = fleet_eps + comm_g1_eps + comm_extra_eps + ref_30_59 + oc_primary + ip_primary + fl_primary + ref_other

    needed_indices = [
        idx for idx in range(len(_WORK_EPS))
        if idx < _N_REPLAY or bool(_WORK_EPS[idx].get("accused"))
    ]

    n_workers = procs if procs is not None else min(12, os.cpu_count() or 1)
    mod_self = sys.modules.get(__name__)
    use_fork = (
        n_workers > 1
        and "fork" in get_all_start_methods()
        and getattr(mod_self, "_worker_episode", None) is _worker_episode
    )

    pool = None
    if use_fork:
        try:
            pool = get_context("fork").Pool(n_workers)
        except OSError:
            pool = None

    try:
        if pool is not None:
            ep_outputs = pool.map(_worker_episode, needed_indices, chunksize=1)
        else:
            ep_outputs = [_worker_episode(idx) for idx in needed_indices]

        rep_by_id: dict[int, tuple[float, Any, bool, int]] = {}
        att_by_id: dict[int, list[dict[str, Any]]] = {}
        aud_by_id: dict[int, dict[str, Any]] = {}
        for idx, rep, att, aud in ep_outputs:
            eid = id(_WORK_EPS[idx])
            if rep is not None:
                rep_by_id[eid] = rep
            if att is not None:
                att_by_id[eid] = att
            if aud is not None:
                aud_by_id[eid] = aud

        replay_errs: list[str] = []
        replayed_n = 0
        for label, eps in (("fleet", fleet_eps), ("committed_ext", comm_ext_eps), ("solver_30_59", ref_30_59)):
            for ep in eps:
                replayed_n += 1
                rep = rep_by_id.get(id(ep))
                if rep is None:
                    replay_errs.append(f"{label} seed={ep.get('seed')}: missing replay result")
                    continue
                r_score, r_accused, r_correct, r_day = rep
                if (
                    abs(r_score - float(ep["score"])) > 1e-9
                    or r_accused != ep.get("accused")
                    or r_correct != bool(ep.get("correct", False))
                    or r_day != ep.get("final_day")
                ):
                    replay_errs.append(
                        f"{label} seed={ep.get('seed')}: recorded=({ep.get('score')}, {ep.get('accused')}, "
                        f"{ep.get('correct')}, {ep.get('final_day')}) != replay={rep}"
                    )

        expected_replays = (
            len(EXPECTED_FLEET_SEEDS)
            + (
                len(EXPECTED_DEDUP_EXT8_SEEDS)
                if comm_seeds == EXPECTED_DEDUP_EXT8_SEEDS
                else len(EXPECTED_COMMITTED_EXT_SEEDS)
            )
            + len(EXPECTED_REF_SEEDS)
        )
        checks.append({
            "name": "env_replay",
            "passed": not replay_errs and replayed_n == expected_replays,
            "summary": f"{replayed_n - len(replay_errs)}/{replayed_n} episodes replay-verified in canary.env.Env",
            "errors": replay_errs
            if replay_errs
            else ([] if replayed_n == expected_replays else [f"expected {expected_replays} replays, got {replayed_n}"]),
        })

        def _p_acc(ep: dict[str, Any]) -> float | None:
            aud = aud_by_id.get(id(ep))
            return aud["p_accused"] if aud is not None else None

        def _post_expected(ep: dict[str, Any]) -> float | None:
            if not ep.get("accused"):
                return 0.0
            p_val = _p_acc(ep)
            meta = ep.get("meta") or {}
            v_val = meta.get("V", meta.get("V_final"))
            if p_val is None or v_val is None:
                return None
            return p_val * float(v_val) - (1.0 - p_val)

        boot_job_map: dict[tuple[tuple[float, ...], tuple[float, ...]], int] = {}
        boot_job_list: list[tuple[list[float], list[float]]] = []

        def _register_boot(arr_f: list[float], arr_s: list[float]) -> int:
            key = (tuple(arr_f), tuple(arr_s))
            if key not in boot_job_map:
                boot_job_map[key] = len(boot_job_list)
                boot_job_list.append((arr_f, arr_s))
            return boot_job_map[key]

        def _prepare_table(dir_map: dict[str, list[dict[str, Any]]], ref_eps: list[dict[str, Any]], seed_set: set[int]) -> list[tuple[Any, ...]]:
            solver = {(e["tier"], e["seed"]): e for e in ref_eps if e["agent"] == "solver"}
            specs: list[tuple[Any, ...]] = []
            for label, sub, agent in groups("v1.4", "gemini-4-carbon"):
                parts = sub.split("+")
                if not all(part in dir_map for part in parts):
                    continue
                by_dir = [[e for e in dir_map[part] if e["agent"] == agent and e["seed"] in seed_set] for part in parts]
                for tier in ("medium", "hard"):
                    if len(parts) > 1 and not all(any(e["tier"] == tier for e in eps) for eps in by_dir):
                        continue
                    es = sorted((e for eps in by_dir for e in eps if e["tier"] == tier), key=lambda e: e["seed"])
                    if label == ALT_LABEL:
                        zero: set[int] = set()
                        for part in parts:
                            if part == "v1.4/opencode-gemini-4-carbon":
                                zero |= empty_reply_seeds(comm_root / part, tier)
                        if not zero:
                            continue
                        es = [dict(e, score=0.0, correct=False, accused=None) if e["seed"] in zero else e for e in es]
                        have = {e["seed"] for e in es}
                        es += [
                            {
                                "tier": tier,
                                "seed": z,
                                "agent": agent,
                                "score": 0.0,
                                "correct": False,
                                "accused": None,
                                "final_day": 0,
                                "steps": [],
                                "meta": {},
                            }
                            for z in sorted(zero - have)
                            if z in seed_set
                        ]
                        es.sort(key=lambda e: e["seed"])
                    if not es:
                        continue
                    paired = [e for e in es if (tier, e["seed"]) in solver]
                    f_scores = [e["score"] for e in paired]
                    s_scores = [solver[(tier, e["seed"])]["score"] for e in paired]
                    pe_vals = [_post_expected(e) for e in paired]
                    pe_s_vals = [_post_expected(solver[(tier, e["seed"])]) for e in paired]
                    pe_ok = bool(pe_vals) and None not in pe_vals + pe_s_vals
                    pe_bi = _register_boot(pe_vals, pe_s_vals) if (pe_ok and len(pe_vals) > 1 and agent != "solver") else None
                    r_bi = _register_boot(f_scores, s_scores) if (len(f_scores) > 1 and agent != "solver") else None
                    specs.append((label, sub, agent, tier, es, f_scores, s_scores, pe_vals, pe_s_vals, pe_ok, pe_bi, r_bi))
            return specs

        ref_all = ref_other + ref_30_59
        specs_fleet7 = _prepare_table(
            {"v1.4/opencode-gemini-4-carbon-ext": fleet_eps, "v1.4/reference": ref_30_59},
            ref_30_59,
            set(range(30, 60)),
        )
        specs_ext8 = _prepare_table(
            {"v1.4/opencode-gemini-4-carbon-ext": ext8_eps, "v1.4/reference": ref_30_59},
            ref_30_59,
            set(range(30, 60)),
        )
        specs_pooled38 = _prepare_table(
            {
                "v1.4/opencode-gemini-4-carbon": oc_primary,
                "v1.4/opencode-gemini-4-carbon-ext": ext8_eps,
                "v1.4/inproc-gemini-4-carbon": ip_primary,
                "v1.4/opencode-gemini-3.5-flash": fl_primary,
                "v1.4/reference": ref_all,
            },
            ref_all,
            set(range(0, 60)),
        )

        if pool is not None:
            boot_results = pool.starmap(boot_ratio, boot_job_list, chunksize=1)
        else:
            boot_results = [boot_ratio(a, b) for a, b in boot_job_list]
    finally:
        if pool is not None:
            pool.close()
            pool.join()

    def _finalize_table(specs: list[tuple[Any, ...]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for label, sub, agent, tier, es, f_scores, s_scores, pe_vals, pe_s_vals, pe_ok, pe_bi, r_bi in specs:
            mean_val, ci_val = mean_ci([e["score"] for e in es])
            ms = sum(s_scores) / len(s_scores) if s_scores else float("nan")
            dm, dh = mean_ci([x - y for x, y in zip(f_scores, s_scores)]) if f_scores else (float("nan"), float("nan"))
            ps = [x for x in (_p_acc(e) for e in es if e.get("accused")) if x is not None]
            pe_ratio = (sum(pe_vals) / sum(pe_s_vals)) if pe_ok and sum(pe_s_vals) > 0 else float("nan")
            pe_lo, pe_hi = boot_results[pe_bi] if pe_bi is not None else (float("nan"), float("nan"))
            lo, hi = boot_results[r_bi] if r_bi is not None else (float("nan"), float("nan"))
            rows.append({
                "label": label,
                "group": sub,
                "agent": agent,
                "tier": tier,
                "n": len(es),
                "seeds": [e["seed"] for e in es],
                "mean": mean_val,
                "ci": ci_val,
                "accuracy": sum(bool(e["correct"]) for e in es) / len(es),
                "accused_rate": sum(1 for e in es if e.get("accused")) / len(es),
                "p_accused": (sum(ps) / len(ps)) if ps else float("nan"),
                "n_p": len(ps),
                "accuse_day": (
                    sum(e["final_day"] for e in es if e.get("accused"))
                    / max(1, sum(1 for e in es if e.get("accused")))
                ),
                "solver_same_seeds": ms,
                "ratio": (sum(f_scores) / len(f_scores) / ms) if f_scores and ms > 0 else float("nan"),
                "ratio_lo": lo,
                "ratio_hi": hi,
                "diff": dm,
                "diff_ci": dh,
                "post_expected": (sum(pe_vals) / len(pe_vals)) if pe_vals and None not in pe_vals else float("nan"),
                "post_expected_ratio": pe_ratio,
                "post_expected_lo": pe_lo,
                "post_expected_hi": pe_hi,
                "solver_post_expected": (sum(pe_s_vals) / len(pe_s_vals)) if pe_ok else float("nan"),
            })
        return rows

    table_checks = (
        ("paired_table_fleet7.json", _finalize_table(specs_fleet7)),
        ("paired_table_ext8_combined.json", _finalize_table(specs_ext8)),
        ("paired_table_pooled38.json", _finalize_table(specs_pooled38)),
    )
    table_errs: list[str] = []
    for fname, expected_rows in table_checks:
        fpath = ext_root / fname
        if not fpath.is_file():
            table_errs.append(f"missing {fpath.relative_to(repo_path)}")
            continue
        try:
            actual_rows = json.loads(fpath.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            table_errs.append(f"{fname}: invalid JSON ({exc})")
            continue
        diffs = _deep_diff(expected_rows, actual_rows, path=fname)
        table_errs.extend(diffs)

    checks.append({
        "name": "paired_tables",
        "passed": not table_errs,
        "summary": "paired_table_fleet7.json, paired_table_ext8_combined.json, paired_table_pooled38.json verified",
        "errors": table_errs,
    })

    tags_errs: list[str] = []
    for fname, eps_in in (
        ("tags.json", fleet_eps),
        ("tags_ext8_combined.json", ext8_eps),
    ):
        fpath = ext_root / fname
        if not fpath.is_file():
            tags_errs.append(f"missing {fpath.relative_to(repo_path)}")
            continue
        try:
            act_tags = json.loads(fpath.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            tags_errs.append(f"{fname}: invalid JSON ({exc})")
            continue
        ep_iter = iter(eps_in)
        exp_tags = tag_report(eps_in, attribute=lambda _er: att_by_id[id(next(ep_iter))])
        tags_errs.extend(_deep_diff(exp_tags, act_tags, path=fname))

    for fname, eps_in in (
        ("accuse.md", fleet_eps),
        ("accuse_ext8_combined.md", ext8_eps),
    ):
        fpath = ext_root / fname
        if not fpath.is_file():
            tags_errs.append(f"missing {fpath.relative_to(repo_path)}")
            continue
        raw_md = fpath.read_text(encoding="utf-8")
        if fname == "accuse_ext8_combined.md" and (EM_DASH in raw_md or EN_DASH in raw_md):
            tags_errs.append(f"{fname}: contains unicode em/en dash")
        exp_md = _sanitize_dashes(accuse_to_md([aud_by_id[id(ep)] for ep in eps_in])).strip()
        if raw_md.strip() != exp_md:
            tags_errs.append(f"{fname}: content does not match deterministic canary.analysis.accuse output")

    checks.append({
        "name": "tags_and_accuse",
        "passed": not tags_errs,
        "summary": "tags.json, tags_ext8_combined.json, accuse.md, accuse_ext8_combined.md verified",
        "errors": tags_errs,
    })

    elapsed_s = round(time.perf_counter() - t0, 3)
    ok = all(c["passed"] for c in checks)
    return {
        "ok": ok,
        "elapsed_s": elapsed_s,
        "dedup_seeds": ext8_seeds,
        "replayed_episodes": replayed_n,
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verify v1.4 frontier extension replication replays, dedup, paired tables, and tags.")
    ap.add_argument("--repo", default=str(ROOT))
    ap.add_argument("--procs", type=int, default=None)
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args(argv)

    report = verify_frontier_ext_replication(repo=args.repo, procs=args.procs)
    if args.as_json:
        print(json.dumps(report, indent=2))
    else:
        for chk in report["checks"]:
            status = "PASS" if chk["passed"] else "FAIL"
            print(f"[{status}] {chk['name']}: {chk['summary']}")
            for err in chk["errors"][:10]:
                print(f"  - {err}")
        verdict = "PASS" if report["ok"] else "FAIL"
        print(f"OVERALL: {verdict} ({report['elapsed_s']:.3f}s)")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
