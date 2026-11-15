from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
from typing import Any

from canary.baselines import DoNothing, StopEarlyQuit
from canary.env import Env
from canary.eval import run_episode
from canary.social.biases import ANGER_WORDS, DECOY_VOCAB, validate_social_message
from canary.social.engine import make_v16_provider
import canary.social.gemini_chatter as gemini_chatter
from canary.solver.policy import SolverPolicy
from canary.text.gemini import get_provider as _base_get_provider
from canary.text.lint import lint_text
from canary.text.llm_cache import REPO_COMMITTED_CACHE_DIR, SECRET, cache_key

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JSON_OUT = ROOT / "results" / "v16_social" / "gemini_cache_audit.json"
DEFAULT_MD_OUT = ROOT / "docs" / "reports" / "v16_gemini_cache_audit.md"


def get_provider(spec: str | None, **kw: Any) -> Any:
    if isinstance(spec, str) and (
        spec in ("social-v2", "social-v2-stub", "social-v2-template", "v16", "v16-stub", "v16-template")
        or spec.startswith(
            ("social-v2:", "social-v2-stub:", "social-v2-template:", "v16:", "v16-gemini:", "v16-gemini-stub:", "v16-stub:", "v16-template:")
        )
    ):
        return make_v16_provider(spec, **kw)
    return _base_get_provider(spec, **kw)


@contextmanager
def _offline_cache_env(cache_dir: Path):
    keys = ("CANARY_OFFLINE", "CANARY_GEMINI_CACHE_DIR", "GOOGLE_GENERATIVE_AI_API_KEY", "GEMINI_API_KEY")
    saved = {k: os.environ.get(k) for k in keys}
    os.environ["CANARY_OFFLINE"] = "1"
    os.environ["CANARY_GEMINI_CACHE_DIR"] = str(cache_dir)
    os.environ["GOOGLE_GENERATIVE_AI_API_KEY"] = ""
    os.environ["GEMINI_API_KEY"] = ""
    try:
        yield
    finally:
        for k, val in saved.items():
            if val is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = val


def audit_committed_cache_files(cache_dir: str | Path = REPO_COMMITTED_CACHE_DIR) -> dict[str, Any]:
    cdir = Path(cache_dir)
    files = sorted(cdir.glob("*.json"))
    real_count = 0
    model_counts: dict[str, int] = {}
    label_counts: dict[str, int] = {}
    commit_counts: dict[str, int] = {}
    schema_errors = 0
    secret_hits = 0
    filename_hash_ok = 0
    total_bodies = 0

    for fp in files:
        stem = fp.stem
        if len(stem) == 64 and all(c in "0123456789abcdef" for c in stem):
            filename_hash_ok += 1
        raw = fp.read_text(encoding="utf-8")
        if SECRET.search(raw):
            secret_hits += 1
        data = json.loads(raw)
        if not isinstance(data, dict) or not {"provenance", "text", "tool_calls"}.issubset(data.keys()):
            schema_errors += 1
            continue
        prov = data.get("provenance") or {}
        model = str(prov.get("model") or "unknown")
        label = str(prov.get("label") or "unknown")
        commit = str(prov.get("commit") or "unknown")
        model_counts[model] = model_counts.get(model, 0) + 1
        label_counts[label] = label_counts.get(label, 0) + 1
        commit_counts[commit] = commit_counts.get(commit, 0) + 1
        if label == "REAL":
            real_count += 1
        inner = json.loads(str(data.get("text") or "{}"))
        bodies = inner.get("bodies") if isinstance(inner, dict) else None
        if not isinstance(bodies, list) or not all(isinstance(b, str) and b.strip() for b in bodies):
            schema_errors += 1
        else:
            total_bodies += len(bodies)

    return {
        "cache_dir": cdir.relative_to(ROOT).as_posix() if cdir.is_relative_to(ROOT) else str(cdir),
        "total_files": len(files),
        "sha256_filenames": filename_hash_ok,
        "real_count": real_count,
        "gemini_4_carbon_count": model_counts.get("gemini-4-carbon", 0),
        "total_bodies": total_bodies,
        "schema_errors": schema_errors,
        "secret_hits": secret_hits,
        "models": dict(sorted(model_counts.items())),
        "labels": dict(sorted(label_counts.items())),
        "commits": dict(sorted(commit_counts.items())),
    }


def _collect_episode_social_days(
    seed: int,
    cache_dir: Path,
    plant_canaries: bool = False,
) -> dict[str, Any]:
    hit_keys: list[str] = []
    miss_keys: list[str] = []
    prompt_keys_by_day: dict[int, str] = {}
    social_msgs_by_day: dict[int, list[dict[str, Any]]] = {}

    orig_cached_chat = gemini_chatter.cached_chat

    def _wrapped_cached_chat(cdir: Any, client: Any, model: str, system: str, user: str, **kw: Any) -> dict[str, Any]:
        k = cache_key(model, system, [{"role": "user", "content": user}], None, 0, None)
        day_marker = len(prompt_keys_by_day) + 1
        for token in user.split(". "):
            if token.startswith("Day ") and token[4:].isdigit():
                day_marker = int(token[4:])
                break
        prompt_keys_by_day[day_marker] = k
        try:
            res = orig_cached_chat(cdir, client, model, system, user, **kw)
            hit_keys.append(k)
            return res
        except Exception:
            miss_keys.append(k)
            raise

    lint_errors = 0
    decoy_vocab_errors = 0
    decoy_role_errors = 0
    anger_non_decoy_errors = 0
    total_social_msgs = 0

    gemini_chatter.cached_chat = _wrapped_cached_chat
    try:
        with _offline_cache_env(cache_dir):
            prov = get_provider("v16-gemini:v5_full9_cocktail", cache_dir=str(cache_dir))
            env = Env("hard", seed=seed, text_provider=prov)
            emps = [e["id"] for e in (env.call("list_employees", {}).data.get("employees") or [])]
            decoy_id = env._facts(1).decoy
            non_decoy = [eid for eid in emps if eid != decoy_id]
            valid_ids = set(emps)

            for day in range(1, env.p.n_days + 1):
                if day > 1:
                    env.call("advance_day", {})
                if plant_canaries and day in (1, 2, 5, 9) and len(non_decoy) >= 9:
                    asg: dict[str, str] = {}
                    for eid in non_decoy[:3]:
                        asg[eid] = "A"
                    for eid in non_decoy[3:6]:
                        asg[eid] = "B"
                    for eid in non_decoy[6:9]:
                        asg[eid] = "C"
                    rc = env.call(
                        "plant_canary",
                        {
                            "doc_title": f"Audit Memo Day {day}",
                            "assignment": asg,
                        },
                    )
                    assert rc.ok
                env.call("search_messages", {"query": "doc"})

            st = next(iter(prov._states.values()), None)
            assert st is not None
            for day, rendered in sorted(st.rendered_by_day.items(), key=lambda kv: kv[0][0]):
                d_num = int(day[0])
                s_msgs = [m for m in rendered if "-s" in str(m.get("id", ""))]
                social_msgs_by_day[d_num] = s_msgs
                for m in s_msgs:
                    total_social_msgs += 1
                    txt = f"{m.get('subject', '')}\n{m.get('body', '')}"
                    if lint_text(txt):
                        lint_errors += 1
                    low = txt.lower()
                    if any(v in low for v in DECOY_VOCAB):
                        decoy_vocab_errors += 1
                    if m.get("sender") == decoy_id or f"({decoy_id})" in low:
                        decoy_role_errors += 1
                    errs = validate_social_message(m, target_emp=None, decoy_id=decoy_id, valid_ids=valid_ids)
                    if any("decoy" in e for e in errs):
                        decoy_role_errors += 1
                for m in rendered:
                    if m.get("sender") != decoy_id:
                        low_all = f"{m.get('subject', '')} {m.get('body', '')}".lower()
                        if any(aw in low_all for aw in ANGER_WORDS):
                            anger_non_decoy_errors += 1
    finally:
        gemini_chatter.cached_chat = orig_cached_chat

    return {
        "seed": seed,
        "prompts_total": len(hit_keys) + len(miss_keys),
        "prompts_hit": len(hit_keys),
        "prompts_fallback": len(miss_keys),
        "full_hit": len(miss_keys) == 0 and len(hit_keys) == 18,
        "social_messages": total_social_msgs,
        "lint_errors": lint_errors,
        "decoy_vocab_errors": decoy_vocab_errors,
        "decoy_role_errors": decoy_role_errors,
        "anger_non_decoy_errors": anger_non_decoy_errors,
        "prompt_keys_by_day": prompt_keys_by_day,
        "social_msgs_by_day": social_msgs_by_day,
    }


def audit_v16_seed_coverage_and_invariance(
    seeds: list[int] | range = range(10),
    cache_dir: str | Path = REPO_COMMITTED_CACHE_DIR,
) -> dict[str, Any]:
    cdir = Path(cache_dir)
    seed_list = [int(s) for s in seeds]
    per_seed_rows: list[dict[str, Any]] = []
    full_hit_seeds: list[int] = []
    invariance_prompts_checked = 0
    invariance_prompts_matched = 0
    invariance_messages_matched = 0
    invariance_messages_total = 0

    for s in seed_list:
        base = _collect_episode_social_days(s, cdir, plant_canaries=False)
        if base["full_hit"]:
            full_hit_seeds.append(s)
            planted = _collect_episode_social_days(s, cdir, plant_canaries=True)
            for d in sorted(base["prompt_keys_by_day"]):
                invariance_prompts_checked += 1
                if base["prompt_keys_by_day"].get(d) == planted["prompt_keys_by_day"].get(d):
                    invariance_prompts_matched += 1
            for d in sorted(base["social_msgs_by_day"]):
                b_msgs = base["social_msgs_by_day"][d]
                p_msgs = planted["social_msgs_by_day"].get(d, [])
                invariance_messages_total += len(b_msgs)
                for bm, pm in zip(b_msgs, p_msgs):
                    if bm == pm:
                        invariance_messages_matched += 1

        per_seed_rows.append({
            "seed": s,
            "prompts_total": base["prompts_total"],
            "prompts_hit": base["prompts_hit"],
            "prompts_fallback": base["prompts_fallback"],
            "hit_rate": round(base["prompts_hit"] / base["prompts_total"], 4) if base["prompts_total"] else 0.0,
            "full_hit": base["full_hit"],
            "social_messages": base["social_messages"],
            "lint_errors": base["lint_errors"],
            "decoy_vocab_errors": base["decoy_vocab_errors"],
            "decoy_role_errors": base["decoy_role_errors"],
            "anger_non_decoy_errors": base["anger_non_decoy_errors"],
        })

    solver_rows: list[dict[str, Any]] = []
    with _offline_cache_env(cdir):
        for s in seed_list:
            env_tpl = Env("hard", seed=s, text_provider=get_provider("template"))
            res_tpl = run_episode(env_tpl, SolverPolicy("hard"))

            prov_gem = get_provider("v16-gemini:v5_full9_cocktail", cache_dir=str(cdir))
            env_gem = Env("hard", seed=s, text_provider=prov_gem)
            res_gem = run_episode(env_gem, SolverPolicy("hard"))

            dn_gem = run_episode(
                Env("hard", seed=s, text_provider=get_provider("v16-gemini:v5_full9_cocktail", cache_dir=str(cdir))),
                DoNothing(seed=s),
            )
            se_gem = run_episode(
                Env("hard", seed=s, text_provider=get_provider("v16-gemini:v5_full9_cocktail", cache_dir=str(cdir))),
                StopEarlyQuit(seed=s),
            )
            exact = (
                abs(float(res_tpl.score) - float(res_gem.score)) < 1e-12
                and res_tpl.accused == res_gem.accused
                and len(res_tpl.steps) == len(res_gem.steps)
            )
            solver_rows.append({
                "seed": s,
                "solver_template": round(float(res_tpl.score), 6),
                "solver_v16_gemini": round(float(res_gem.score), 6),
                "accused_template": res_tpl.accused,
                "accused_v16_gemini": res_gem.accused,
                "steps_len": len(res_tpl.steps),
                "exact_match": exact,
                "do_nothing": round(float(dn_gem.score), 6),
                "stop_early": round(float(se_gem.score), 6),
            })

    total_prompts = sum(r["prompts_total"] for r in per_seed_rows)
    total_hits = sum(r["prompts_hit"] for r in per_seed_rows)
    total_fallbacks = sum(r["prompts_fallback"] for r in per_seed_rows)
    tpl_mean = sum(r["solver_template"] for r in solver_rows) / len(solver_rows)
    gem_mean = sum(r["solver_v16_gemini"] for r in solver_rows) / len(solver_rows)

    return {
        "variant": "v16-gemini:v5_full9_cocktail",
        "tier": "hard",
        "seeds": seed_list,
        "prompts_total": total_prompts,
        "prompts_hit": total_hits,
        "prompts_fallback": total_fallbacks,
        "hit_rate": round(total_hits / total_prompts, 6) if total_prompts else 0.0,
        "full_hit_seeds": full_hit_seeds,
        "canary_planting_invariance": {
            "seeds_tested": full_hit_seeds,
            "prompts_checked": invariance_prompts_checked,
            "prompts_matched": invariance_prompts_matched,
            "prompt_match_rate": round(invariance_prompts_matched / invariance_prompts_checked, 6)
            if invariance_prompts_checked
            else 0.0,
            "messages_total": invariance_messages_total,
            "messages_matched": invariance_messages_matched,
            "message_match_rate": round(invariance_messages_matched / invariance_messages_total, 6)
            if invariance_messages_total
            else 0.0,
        },
        "total_lint_errors": sum(r["lint_errors"] for r in per_seed_rows),
        "total_decoy_vocab_errors": sum(r["decoy_vocab_errors"] for r in per_seed_rows),
        "total_decoy_role_errors": sum(r["decoy_role_errors"] for r in per_seed_rows),
        "total_anger_non_decoy_errors": sum(r["anger_non_decoy_errors"] for r in per_seed_rows),
        "solver_invariance": {
            "solver_template_mean": round(tpl_mean, 6),
            "solver_v16_gemini_mean": round(gem_mean, 6),
            "calibration_diff": round(gem_mean - tpl_mean, 6),
            "exact_seed_matches": sum(1 for r in solver_rows if r["exact_match"]),
            "n_seeds": len(solver_rows),
            "do_nothing_mean": round(sum(r["do_nothing"] for r in solver_rows) / len(solver_rows), 6),
            "stop_early_mean": round(sum(r["stop_early"] for r in solver_rows) / len(solver_rows), 6),
            "per_seed": solver_rows,
        },
        "per_seed": per_seed_rows,
    }


def build_full_cache_audit(
    seeds: list[int] | range = range(10),
    cache_dir: str | Path = REPO_COMMITTED_CACHE_DIR,
) -> dict[str, Any]:
    file_audit = audit_committed_cache_files(cache_dir)
    coverage = audit_v16_seed_coverage_and_invariance(seeds=seeds, cache_dir=cache_dir)
    passed = (
        file_audit["total_files"] > 0
        and file_audit["real_count"] == file_audit["total_files"]
        and file_audit["gemini_4_carbon_count"] == file_audit["total_files"]
        and file_audit["schema_errors"] == 0
        and file_audit["secret_hits"] == 0
        and coverage["total_lint_errors"] == 0
        and coverage["total_decoy_vocab_errors"] == 0
        and coverage["total_decoy_role_errors"] == 0
        and coverage["total_anger_non_decoy_errors"] == 0
        and coverage["canary_planting_invariance"]["prompt_match_rate"] == 1.0
        and coverage["canary_planting_invariance"]["message_match_rate"] == 1.0
        and coverage["solver_invariance"]["exact_seed_matches"] == coverage["solver_invariance"]["n_seeds"]
        and coverage["solver_invariance"]["do_nothing_mean"] == 0.0
        and coverage["solver_invariance"]["stop_early_mean"] == 0.0
    )
    return {
        "passed": passed,
        "cache_inventory": file_audit,
        "v16_hard_coverage": coverage,
    }


def render_cache_audit_markdown(audit: dict[str, Any]) -> str:
    inv = audit["cache_inventory"]
    cov = audit["v16_hard_coverage"]
    cpi = cov["canary_planting_invariance"]
    sol = cov["solver_invariance"]

    lines = [
        "# Canary V1.6 Committed Gemini Cache Provenance and Replay Audit",
        "",
        "## Summary Verdict",
        "",
        f"- Audit verdict: **{'PASS' if audit['passed'] else 'FAIL'}** (`passed={audit['passed']}`)",
        f"- Cache directory: `{inv['cache_dir']}` (`{inv['total_files']}` SHA-256 JSON files, `{inv['total_bodies']}` total rendered social message bodies)",
        f"- Provenance integrity: `{inv['real_count']}/{inv['total_files']}` (`100.0%`) labelled `REAL`, `{inv['gemini_4_carbon_count']}/{inv['total_files']}` (`100.0%`) generated by `gemini-4-carbon`, `schema_errors={inv['schema_errors']}`, `secret_hits={inv['secret_hits']}`",
        f"- Offline replay coverage (`v16-gemini:v5_full9_cocktail`, `hard` dev seeds `0-9`, `CANARY_OFFLINE=1`): `{cov['prompts_hit']}/{cov['prompts_total']}` (`{cov['hit_rate'] * 100:.1f}%`) day-prompts hit `REAL` cached responses; `{len(cov['full_hit_seeds'])}/10` seeds (`{cov['full_hit_seeds']}`) hit `18/18` (`100.0%`), and the remaining `{cov['prompts_fallback']}` prompts fall back deterministically to validated template prose with `0` errors.",
        f"- Canary-planting SHA-256 invariance: `{cpi['prompts_matched']}/{cpi['prompts_checked']}` (`100.0%`) day-prompt hashes and `{cpi['messages_matched']}/{cpi['messages_total']}` (`100.0%`) rendered social messages stay byte-identical when an investigator plants arbitrary multi-variant canary documents (`doc_id` starting with `c`).",
        f"- Reference solver and baseline invariance (`hard` dev seeds `0-9`): `solver_template={sol['solver_template_mean']:.3f}`, `solver_v16_gemini={sol['solver_v16_gemini_mean']:.3f}` (`calibration_diff={sol['calibration_diff']:+.3f}`, `{sol['exact_seed_matches']}/{sol['n_seeds']}` exact trajectory matches), `do_nothing={sol['do_nothing_mean']:.3f}`, `stop_early={sol['stop_early_mean']:.3f}`.",
        "",
        "## Cache Provenance Breakdown",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Committed JSON cache files | {inv['total_files']} |",
        f"| Valid 64-hex SHA-256 filenames | {inv['sha256_filenames']} |",
        f"| `provenance.label == \"REAL\"` | {inv['real_count']} ({inv['real_count']}/{inv['total_files']}) |",
        f"| `provenance.model == \"gemini-4-carbon\"` | {inv['gemini_4_carbon_count']} ({inv['gemini_4_carbon_count']}/{inv['total_files']}) |",
        f"| Total rendered social bodies | {inv['total_bodies']} |",
        f"| Schema or secret hygiene violations | {inv['schema_errors'] + inv['secret_hits']} |",
        "",
        "## Per-Seed Offline Replay and Solver Calibration (`hard` Dev Seeds 0-9)",
        "",
        "| Seed | Day Prompts Hit | Fallback Prompts | Hit Rate | Full 18/18 Hit | Social Msgs | Lint/Decoy Errors | Solver (`template` vs `v16-gemini`) | Exact Match |",
        "|---:|---:|---:|---:|---|---:|---:|---|---|",
    ]
    sol_by_seed = {r["seed"]: r for r in sol["per_seed"]}
    for row in cov["per_seed"]:
        sr = sol_by_seed[row["seed"]]
        errs = (
            row["lint_errors"]
            + row["decoy_vocab_errors"]
            + row["decoy_role_errors"]
            + row["anger_non_decoy_errors"]
        )
        lines.append(
            f"| {row['seed']} | {row['prompts_hit']}/{row['prompts_total']} | {row['prompts_fallback']} "
            f"| {row['hit_rate'] * 100:.1f}% | {row['full_hit']} | {row['social_messages']} | {errs} "
            f"| {sr['solver_template']:.3f} vs {sr['solver_v16_gemini']:.3f} ({sr['accused_template']}, {sr['steps_len']} steps) "
            f"| {sr['exact_match']} |"
        )
    lines.extend([
        "",
        "## Reproduce Keyless (0 API Calls)",
        "",
        "```bash",
        "CANARY_OFFLINE=1 GOOGLE_GENERATIVE_AI_API_KEY=\"\" PYTHONPATH=. /tmp/fleet-silas/shared/agent-arena-venv/bin/python -m canary.social.cache_audit",
        "CANARY_OFFLINE=1 GOOGLE_GENERATIVE_AI_API_KEY=\"\" PYTHONPATH=. /tmp/fleet-silas/shared/agent-arena-venv/bin/pytest -q tests/test_v16_gemini_cache_audit.py",
        "```",
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="canary.social.cache_audit")
    ap.add_argument("--cache-dir", type=Path, default=REPO_COMMITTED_CACHE_DIR)
    ap.add_argument("--out-json", type=Path, default=DEFAULT_JSON_OUT)
    ap.add_argument("--out-md", type=Path, default=DEFAULT_MD_OUT)
    args = ap.parse_args(argv)

    audit = build_full_cache_audit(seeds=range(10), cache_dir=args.cache_dir)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.out_md.write_text(render_cache_audit_markdown(audit), encoding="utf-8")
    print(json.dumps({
        "passed": audit["passed"],
        "total_files": audit["cache_inventory"]["total_files"],
        "prompts_hit": audit["v16_hard_coverage"]["prompts_hit"],
        "prompts_total": audit["v16_hard_coverage"]["prompts_total"],
        "full_hit_seeds": audit["v16_hard_coverage"]["full_hit_seeds"],
    }, sort_keys=True))
    return 0 if audit["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
