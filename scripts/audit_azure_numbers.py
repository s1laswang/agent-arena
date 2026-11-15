from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
import json
import math
from pathlib import Path
import re
import sys
import time
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.mole.ablation import check_ablation_artifacts
from canary.mole.discipline_curve import check_discipline_artifacts
from canary.mole.distill_rl_mole import check_distilled_artifacts
from canary.mole.dsl import MoleStrategy
from canary.mole.regret_portfolio import check_markdown_report as check_portfolio_report
from canary.mole.representation_pareto import check_representation_pareto_artifacts
from canary.mole.tier_robustness import check_tier_robustness_artifacts
from canary.mole.transfer_eval import check_transfer_artifacts
from canary.mole.worked_predicate import check_worked_predicate_artifacts
from scripts.eval_mole_strategies_v14 import check_report_matches_json as check_v14_eval_report
from scripts.run_v16_social_audit import render_markdown_report as render_v16_fairness_md

H1 = chr(35)
H2 = H1 * 2
H3 = H1 * 3
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)

SOLVER_PCT_SUBSTR = "% of " + "solver"
FLASH_35_SUBSTR = "gemini-3.5-" + "flash"
COAUTHOR_SUBSTR = "co-authored-" + "by"

SOLVER_PCT_RE = re.compile(
    r"\b\d+(?:\.\d+)?%\s*(?:\[[^\]]*\]\s*)?of\s+(?:the\s+)?(?:reference\s+)?solver(?:'s)?\b",
    re.IGNORECASE,
)

API_KEY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("google_api_key", re.compile(r"(?<![0-9A-Za-z+/_-])AIza[0-9A-Za-z_-]{20,}")),
    ("sk_api_key", re.compile(r"(?<![0-9A-Za-z+/_-])sk-(?:proj-|ant-|live-|test-|svcacct-)?[0-9A-Za-z_-]{16,}")),
    ("github_pat", re.compile(r"(?<![0-9A-Za-z+/_-])ghp_[0-9A-Za-z]{20,}")),
)

WORLD_SECRET_ASSIGN_RE = re.compile(
    r"CANARY_WORLD_SECRET\s*=\s*['\"]?([0-9A-Za-z_.-]+)['\"]?"
)
ALLOWED_DEMO_SECRETS = frozenset({"canary-demo-live", "demo", "test", "none", "placeholder"})

FORBIDDEN_JSON_SECRET_KEYS: frozenset[str] = frozenset({
    "true_mole",
    "mole_id",
    "canary_ids",
    "secret_mole",
    "world_secret",
    "ledger_token",
    "ledger_events",
})

FORBIDDEN_LOW_MAX = 59
FORBIDDEN_RESERVED_RANGE = range(30_000, 30_200)
FORBIDDEN_HIGH_MIN = 800_000

EMBEDDED_LEDGER_RE = re.compile(
    r"<!--\s*([A-Z0-9_]+_LEDGER_START)\s*-->\s*```json\s*(\{.*?\})\s*```\s*<!--\s*([A-Z0-9_]+_LEDGER_END)\s*-->",
    re.DOTALL,
)
FENCED_JSON_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


@dataclass
class CheckResult:
    name: str
    status: str
    summary: str
    details: list[str] = field(default_factory=list)


def _redact_token(val: str) -> str:
    if len(val) <= 8:
        return val[:3] + "..."
    return val[:6] + "..."


def _strict_json_loads(text: str) -> Any:
    def _bad_const(val: str) -> Any:
        raise ValueError(f"non-finite JSON constant {val!r} is forbidden")

    return json.loads(text, parse_constant=_bad_const)


def _ensure_finite_numbers(obj: Any, loc: str = "$") -> list[str]:
    errs: list[str] = []
    if isinstance(obj, bool) or obj is None or isinstance(obj, str):
        return errs
    if isinstance(obj, (int, float)):
        if not math.isfinite(float(obj)):
            errs.append(f"{loc}: non-finite number {obj!r}")
        return errs
    if isinstance(obj, dict):
        for k, v in obj.items():
            errs.extend(_ensure_finite_numbers(v, f"{loc}.{k}"))
        return errs
    if isinstance(obj, list):
        for idx, item in enumerate(obj):
            errs.extend(_ensure_finite_numbers(item, f"{loc}[{idx}]"))
        return errs
    return errs


def _find_forbidden_secret_keys(obj: Any, loc: str = "$") -> list[str]:
    hits: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            ks = str(k)
            cur = f"{loc}.{ks}"
            if ks in FORBIDDEN_JSON_SECRET_KEYS:
                hits.append(cur)
            elif ks == "mole" and isinstance(v, str) and re.fullmatch(r"e\d{2,3}", v):
                hits.append(cur)
            hits.extend(_find_forbidden_secret_keys(v, cur))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            hits.extend(_find_forbidden_secret_keys(item, f"{loc}[{idx}]"))
    return hits


def _validate_strategy_jsons_recursive(obj: Any, loc: str = "$") -> list[str]:
    errs: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            cur = f"{loc}.{k}"
            if k == "strategy_json":
                if not isinstance(v, dict):
                    errs.append(f"{cur}: strategy_json must be a JSON object")
                else:
                    try:
                        MoleStrategy.from_json(v)
                    except Exception as exc:
                        errs.append(f"{cur}: invalid MoleStrategy ({exc})")
            else:
                errs.extend(_validate_strategy_jsons_recursive(v, cur))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            errs.extend(_validate_strategy_jsons_recursive(item, f"{loc}[{idx}]"))
    return errs


def _validate_fresh_eval_seeds(seeds: Any, loc: str, expected_n: int | None = None) -> list[str]:
    errs: list[str] = []
    if not isinstance(seeds, list) or not seeds:
        return [f"{loc}: seeds must be a non-empty list"]
    seen: set[int] = set()
    for idx, raw in enumerate(seeds):
        if isinstance(raw, bool) or not isinstance(raw, int):
            errs.append(f"{loc}[{idx}]: non-integer seed {raw!r}")
            continue
        if raw in seen:
            errs.append(f"{loc}: duplicate seed {raw}")
        seen.add(raw)
        if 0 <= raw <= FORBIDDEN_LOW_MAX:
            errs.append(f"{loc}: seed {raw} falls in forbidden committed range 0..{FORBIDDEN_LOW_MAX}")
        elif raw in FORBIDDEN_RESERVED_RANGE:
            errs.append(f"{loc}: seed {raw} falls in forbidden reserved range 30000..30199")
        elif raw >= FORBIDDEN_HIGH_MIN:
            errs.append(f"{loc}: seed {raw} falls in forbidden heldout/judge range >= {FORBIDDEN_HIGH_MIN}")
    if expected_n is not None and len(seeds) != int(expected_n):
        errs.append(f"{loc}: len(seeds)={len(seeds)} != n_seeds={expected_n}")
    return errs


def _discover_azure_targets(root: Path) -> tuple[list[Path], list[Path], list[Path], list[Path]]:
    reports_dir = root / "docs" / "reports"
    mole_md = sorted(reports_dir.glob("mole_*.md")) if reports_dir.is_dir() else []
    v16_md = sorted(reports_dir.glob("v16_*.md")) if reports_dir.is_dir() else []
    mole_json_dir = root / "results" / "mole_strategies"
    mole_json = sorted(mole_json_dir.glob("*.json")) if mole_json_dir.is_dir() else []
    v16_json_dir = root / "results" / "v16_social"
    v16_json = sorted(v16_json_dir.glob("*.json")) if v16_json_dir.is_dir() else []
    return mole_md, v16_md, mole_json, v16_json


def _scan_text_hygiene(rel_path: str, text: str) -> list[str]:
    errs: list[str] = []
    if EM_DASH in text:
        lineno = text[: text.index(EM_DASH)].count("\n") + 1
        errs.append(f"{rel_path}:{lineno}: contains forbidden em dash (U+2014)")
    if EN_DASH in text:
        lineno = text[: text.index(EN_DASH)].count("\n") + 1
        errs.append(f"{rel_path}:{lineno}: contains forbidden en dash (U+2013)")

    low = text.lower()
    if COAUTHOR_SUBSTR in low:
        lineno = low[: low.index(COAUTHOR_SUBSTR)].count("\n") + 1
        errs.append(f"{rel_path}:{lineno}: contains forbidden {COAUTHOR_SUBSTR} trailer")

    if rel_path != "docs/reports/gap.md":
        if SOLVER_PCT_SUBSTR in low:
            lineno = low[: low.index(SOLVER_PCT_SUBSTR)].count("\n") + 1
            errs.append(f"{rel_path}:{lineno}: forbidden {SOLVER_PCT_SUBSTR!r} claim outside docs/reports/gap.md")
        else:
            m_pct = SOLVER_PCT_RE.search(text)
            if m_pct is not None:
                lineno = text[: m_pct.start()].count("\n") + 1
                errs.append(
                    f"{rel_path}:{lineno}: forbidden solver percentage claim {m_pct.group(0)!r} outside docs/reports/gap.md"
                )

    for kind, rx in API_KEY_PATTERNS:
        for match in rx.finditer(text):
            tok = match.group(0)
            lineno = text[: match.start()].count("\n") + 1
            errs.append(f"{rel_path}:{lineno}: leaked raw secret ({kind}: {_redact_token(tok)})")

    for match in WORLD_SECRET_ASSIGN_RE.finditer(text):
        secret_val = match.group(1)
        if secret_val.lower() not in ALLOWED_DEMO_SECRETS:
            lineno = text[: match.start()].count("\n") + 1
            errs.append(
                f"{rel_path}:{lineno}: leaked CANARY_WORLD_SECRET assignment ({_redact_token(secret_val)})"
            )
    return errs


def check_artifact_hygiene(root: Path) -> CheckResult:
    name = "Azure Report & JSON Hygiene"
    mole_md, v16_md, mole_json, v16_json = _discover_azure_targets(root)
    missing_groups: list[str] = []
    if not mole_md:
        missing_groups.append("docs/reports/mole_*.md matched 0 files")
    if not v16_md:
        missing_groups.append("docs/reports/v16_*.md matched 0 files")
    if not mole_json:
        missing_groups.append("results/mole_strategies/*.json matched 0 files")
    if missing_groups:
        return CheckResult(name, "FAIL", "missing required Azure report/JSON artifact group(s)", missing_groups)

    all_files = [*mole_md, *v16_md, *mole_json, *v16_json]
    violations: list[str] = []
    for fp in all_files:
        rel = fp.relative_to(root).as_posix()
        try:
            txt = fp.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            violations.append(f"{rel}: unreadable UTF-8 text ({exc})")
            continue
        if not txt.strip():
            violations.append(f"{rel}: file is empty")
            continue
        violations.extend(_scan_text_hygiene(rel, txt))

    if violations:
        return CheckResult(
            name,
            "FAIL",
            f"{len(violations)} hygiene violation(s) across {len(all_files)} file(s)",
            violations,
        )
    return CheckResult(
        name,
        "PASS",
        f"audited {len(mole_md)} mole_*.md, {len(v16_md)} v16_*.md, {len(mole_json)} mole_strategies/*.json "
        f"(+{len(v16_json)} v16_social/*.json); 0 solver-% claims, 0 em/en dashes, 0 secrets, 0 trailers",
    )


def _audit_v14_fresh_json_schema(payload: dict[str, Any], rel: str) -> list[str]:
    errs: list[str] = []
    if payload.get("schema_version") != "mole_strategies_v14_eval.v1":
        errs.append(f"{rel}: unexpected schema_version {payload.get('schema_version')!r}")
    if payload.get("tiers_version") != "v1.4" or payload.get("tier") != "hard":
        errs.append(f"{rel}: expected tiers_version='v1.4' and tier='hard'")
    n_seeds = payload.get("n_seeds")
    if not isinstance(n_seeds, int) or n_seeds < 30:
        errs.append(f"{rel}: expected integer n_seeds >= 30, got {n_seeds!r}")
    errs.extend(_validate_fresh_eval_seeds(payload.get("seeds"), f"{rel}.seeds", expected_n=n_seeds if isinstance(n_seeds, int) else None))

    gates = payload.get("gates")
    if not isinstance(gates, dict) or gates.get("all_passed") is not True:
        errs.append(f"{rel}: gates.all_passed must be True")
    min_sa = float((gates or {}).get("min_solver_acc", 0.85))
    max_la = float((gates or {}).get("max_logs_acc", 0.10))

    order = payload.get("strategy_order")
    strats = payload.get("strategies")
    if not isinstance(order, list) or len(order) < 7 or not isinstance(strats, dict):
        errs.append(f"{rel}: missing strategy_order/strategies")
        return errs

    bhashes: set[str] = set()
    for sname in order:
        if sname not in strats or not isinstance(strats[sname], dict):
            errs.append(f"{rel}: missing strategy object for {sname!r}")
            continue
        s = strats[sname]
        bh = str(s.get("behavior_hash") or "")
        if len(bh) < 16:
            errs.append(f"{rel}.{sname}: invalid behavior_hash {bh!r}")
        bhashes.add(bh)
        sol = s.get("solver") or {}
        bl = s.get("baselines") or {}
        if s.get("passed") is not True or sol.get("passed") is not True:
            errs.append(f"{rel}.{sname}: strategy/solver passed != True")
        if float(sol.get("accuracy", 0.0)) < min_sa - 1e-9:
            errs.append(f"{rel}.{sname}: solver accuracy {sol.get('accuracy')} < {min_sa}")
        if float((bl.get("logs_only") or {}).get("accuracy", 1.0)) > max_la + 1e-9:
            errs.append(f"{rel}.{sname}: logs_only accuracy > {max_la}")
        if float((bl.get("accuse_most_logs") or {}).get("accuracy", 1.0)) > max_la + 1e-9:
            errs.append(f"{rel}.{sname}: accuse_most_logs accuracy > {max_la}")
        if abs(float((bl.get("do_nothing") or {}).get("max_abs_score", 1.0))) > 1e-9:
            errs.append(f"{rel}.{sname}: do_nothing max_abs_score != 0.0")
        if abs(float((bl.get("stop_early_quit") or {}).get("max_abs_score", 1.0))) > 1e-9:
            errs.append(f"{rel}.{sname}: stop_early_quit max_abs_score != 0.0")
        sol_score = float(sol.get("score", 0.0))
        invs = s.get("investigators") or {}
        for inv_name in payload.get("investigator_order", []):
            iv = invs.get(inv_name)
            if not isinstance(iv, dict):
                errs.append(f"{rel}.{sname}: missing investigator {inv_name!r}")
                continue
            exp_reg = sol_score - float(iv["score"])
            if abs(float(iv["regret"]) - exp_reg) > 1e-9:
                errs.append(f"{rel}.{sname}.{inv_name}: regret {iv['regret']} != solver-inv {exp_reg}")
        cf = s.get("counterfactual") or {}
        if int(cf.get("n_transcripts", 0)) != 60:
            errs.append(f"{rel}.{sname}: counterfactual.n_transcripts expected 60, got {cf.get('n_transcripts')!r}")
    if len(bhashes) != len(order):
        errs.append(f"{rel}: expected unique behavior_hash across {len(order)} strategies, got {len(bhashes)}")
    return errs


def _audit_lever_ablation_json_schema(payload: dict[str, Any], rel: str) -> list[str]:
    errs: list[str] = []
    if payload.get("anchor_strategy") != "frontier_synthesis_v14":
        errs.append(f"{rel}: expected anchor_strategy='frontier_synthesis_v14'")
    n_seeds = payload.get("n_seeds")
    if not isinstance(n_seeds, int) or n_seeds < 30:
        errs.append(f"{rel}: expected integer n_seeds >= 30, got {n_seeds!r}")
    errs.extend(_validate_fresh_eval_seeds(payload.get("seeds"), f"{rel}.seeds", expected_n=n_seeds if isinstance(n_seeds, int) else None))

    gs = payload.get("gates_summary")
    if not isinstance(gs, dict) or gs.get("all_arms_passed") is not True:
        errs.append(f"{rel}: gates_summary.all_arms_passed must be True")
    else:
        if int(gs.get("n_passed", -1)) != int(gs.get("n_arms", -2)):
            errs.append(f"{rel}: n_passed != n_arms")
        if float(gs.get("min_solver_acc_observed", 0.0)) < float(gs.get("min_solver_acc_threshold", 0.85)) - 1e-9:
            errs.append(f"{rel}: min_solver_acc_observed below threshold")
        if float(gs.get("max_logs_only_acc_observed", 1.0)) > float(gs.get("max_logs_acc_threshold", 0.10)) + 1e-9:
            errs.append(f"{rel}: max_logs_only_acc_observed above threshold")
        if abs(float(gs.get("max_do_nothing_abs_score", 1.0))) > 1e-9:
            errs.append(f"{rel}: max_do_nothing_abs_score != 0.0")
        if abs(float(gs.get("max_stop_early_quit_abs_score", 1.0))) > 1e-9:
            errs.append(f"{rel}: max_stop_early_quit_abs_score != 0.0")
        if gs.get("unique_canonical_strategies") is not True:
            errs.append(f"{rel}: unique_canonical_strategies must be True")

    arms = payload.get("arms")
    if not isinstance(arms, dict) or len(arms) != 12:
        errs.append(f"{rel}: expected 12 arms, got {len(arms) if isinstance(arms, dict) else None}")
    else:
        for arm_name, arm in arms.items():
            if not isinstance(arm, dict) or (arm.get("gates") or {}).get("passed_all") is not True:
                errs.append(f"{rel}.arms.{arm_name}: gates.passed_all != True")
    return errs


def _audit_transfer_json_schema(payload: dict[str, Any], rel: str, root: Path, byte_len: int) -> list[str]:
    errs: list[str] = []
    if byte_len >= 150 * 1024:
        errs.append(f"{rel}: size {byte_len} bytes exceeds 150 KB cap")
    if payload.get("schema_version") != "1.0":
        errs.append(f"{rel}: expected schema_version='1.0', got {payload.get('schema_version')!r}")
    if payload.get("api_calls") != 0:
        errs.append(f"{rel}: expected api_calls == 0, got {payload.get('api_calls')!r}")

    catalog = payload.get("catalog")
    if not isinstance(catalog, dict) or len(catalog) != 11:
        errs.append(f"{rel}: expected 11 catalog entries, got {len(catalog) if isinstance(catalog, dict) else None}")

    cf = payload.get("counterfactual")
    if not isinstance(cf, dict):
        errs.append(f"{rel}: missing counterfactual block")
    else:
        tot = int(cf.get("total_episodes", 0))
        if tot != 99 or int(cf.get("transcript_verified_total", -1)) != tot or int(cf.get("baseline_audit_match_total", -1)) != tot:
            errs.append(f"{rel}: counterfactual 99/99 verification/audit parity invariant failed")

    fm = payload.get("fresh_seed_transfer")
    if not isinstance(fm, dict):
        errs.append(f"{rel}: missing fresh_seed_transfer block")
    else:
        n_s = fm.get("n_seeds")
        if not isinstance(n_s, int) or n_s < 30:
            errs.append(f"{rel}: fresh_seed_transfer.n_seeds expected >= 30, got {n_s!r}")
        errs.extend(_validate_fresh_eval_seeds(fm.get("seeds"), f"{rel}.fresh_seed_transfer.seeds", expected_n=n_s if isinstance(n_s, int) else None))
        if fm.get("all_gates_passed") is not True:
            errs.append(f"{rel}: fresh_seed_transfer.all_gates_passed != True")
        min_sa = float(fm.get("min_solver_acc", 0.85))
        max_la = float(fm.get("max_logs_acc", 0.10))
        for skey, row in (fm.get("strategies") or {}).items():
            if row.get("gates_passed") is not True:
                errs.append(f"{rel}.fresh_seed_transfer.{skey}: gates_passed != True")
            if float(row.get("solver_acc", 0.0)) < min_sa - 1e-9:
                errs.append(f"{rel}.fresh_seed_transfer.{skey}: solver_acc < {min_sa}")
            if float(row.get("logs_only_acc", 1.0)) > max_la + 1e-9:
                errs.append(f"{rel}.fresh_seed_transfer.{skey}: logs_only_acc > {max_la}")

    hof_path = root / "data" / "forge" / "hall_of_fame_v1.4.jsonl"
    if hof_path.is_file() and isinstance(catalog, dict):
        hof_entries = [
            _strict_json_loads(ln)
            for ln in hof_path.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        for idx, h_entry in enumerate(hof_entries[:4], 1):
            ckey = f"hof_v14_r{idx}"
            if ckey not in catalog:
                errs.append(f"{rel}: missing HOF catalog entry {ckey}")
                continue
            src_strat = h_entry.get("strategy") if isinstance(h_entry.get("strategy"), dict) else h_entry
            if isinstance(src_strat, dict) and "name" in src_strat:
                if catalog[ckey].get("hof_survivor_name") != src_strat["name"]:
                    errs.append(
                        f"{rel}.{ckey}: hof_survivor_name {catalog[ckey].get('hof_survivor_name')!r} != {src_strat['name']!r}"
                    )
    return errs


def _audit_generic_mole_json_schema(payload: dict[str, Any], rel: str) -> list[str]:
    errs: list[str] = []
    if not payload:
        return [f"{rel}: JSON object is empty"]
    if "seeds" in payload and isinstance(payload["seeds"], list):
        exp_n = payload.get("n_seeds") if isinstance(payload.get("n_seeds"), int) else None
        errs.extend(_validate_fresh_eval_seeds(payload["seeds"], f"{rel}.seeds", expected_n=exp_n))
    for gate_key in ("all_passed", "all_gates_passed", "gates_passed", "overall_passed"):
        if gate_key in payload and payload[gate_key] is not True:
            errs.append(f"{rel}: top-level {gate_key}={payload[gate_key]!r} (expected True)")
    if isinstance(payload.get("gates"), dict):
        g = payload["gates"]
        for gk in ("all_passed", "all_gates_passed", "passed_all"):
            if gk in g and g[gk] is not True:
                errs.append(f"{rel}.gates.{gk}={g[gk]!r} (expected True)")
    return errs


def check_mole_json_schemas(root: Path) -> CheckResult:
    name = "Mole Strategy JSON Schemas & Gates"
    _, _, mole_json, _ = _discover_azure_targets(root)
    if not mole_json:
        return CheckResult(name, "FAIL", "no results/mole_strategies/*.json files found")

    failures: list[str] = []
    for jp in mole_json:
        rel = jp.relative_to(root).as_posix()
        try:
            raw_text = jp.read_text(encoding="utf-8")
            byte_len = len(raw_text.encode("utf-8"))
            if byte_len > 512 * 1024:
                failures.append(f"{rel}: JSON file size {byte_len} bytes exceeds 512 KB workspace cap")
            payload = _strict_json_loads(raw_text)
        except Exception as exc:
            failures.append(f"{rel}: invalid JSON ({exc})")
            continue
        if not isinstance(payload, dict):
            failures.append(f"{rel}: root JSON value must be an object, got {type(payload).__name__}")
            continue

        failures.extend(_ensure_finite_numbers(payload, rel))
        for bad_key in _find_forbidden_secret_keys(payload, rel):
            failures.append(f"{bad_key}: forbidden secret/answer-key field in JSON")
        failures.extend(_validate_strategy_jsons_recursive(payload, rel))

        if jp.name == "v14_fresh_6000_6199.json":
            failures.extend(_audit_v14_fresh_json_schema(payload, rel))
        elif jp.name == "lever_ablation_v14.json":
            failures.extend(_audit_lever_ablation_json_schema(payload, rel))
        elif jp.name == "cross_model_transfer.json":
            failures.extend(_audit_transfer_json_schema(payload, rel, root, byte_len))
        else:
            failures.extend(_audit_generic_mole_json_schema(payload, rel))

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} schema/gate failure(s) across {len(mole_json)} JSON file(s)",
            failures,
        )
    return CheckResult(
        name,
        "PASS",
        f"validated {len(mole_json)} JSON schema(s) ({', '.join(p.name for p in mole_json)}); "
        "all finite, secret-free, seed-hygienic, DSL-valid, and gate-passing",
    )


def _audit_portfolio_cross_parity(root: Path, md_path: Path) -> list[str]:
    errs: list[str] = []
    ok, msg = check_portfolio_report(md_path)
    if not ok:
        return [f"{md_path.relative_to(root).as_posix()}: {msg}"]

    text = md_path.read_text(encoding="utf-8")
    m = EMBEDDED_LEDGER_RE.search(text)
    if m is None:
        return [f"{md_path.relative_to(root).as_posix()}: missing embedded JSON ledger"]
    ledger = _strict_json_loads(m.group(2))
    errs.extend(_ensure_finite_numbers(ledger, md_path.name))

    tp = ledger["train"]["portfolio"]
    cands = ledger["train"]["candidates"]
    weights = tp["weights"]
    exp_sol_score = sum(float(weights[k]) * float(cands[k]["solver_score"]) for k in weights)
    exp_sol_acc = sum(float(weights[k]) * float(cands[k]["solver_accuracy"]) for k in weights)
    if abs(exp_sol_score - float(tp["expected_solver_score"])) > 1e-9:
        errs.append(f"{md_path.name}: expected_solver_score mismatch with w^T solver_score")
    if abs(exp_sol_acc - float(tp["expected_solver_accuracy"])) > 1e-9:
        errs.append(f"{md_path.name}: expected_solver_accuracy mismatch with w^T solver_accuracy")
    for inv in ledger["train"]["investigator_order"]:
        w_reg = sum(float(weights[k]) * float(cands[k]["investigator_regrets"][inv]) for k in weights)
        if abs(w_reg - float(tp["expected_regrets"][inv])) > 1e-9:
            errs.append(f"{md_path.name}: expected_regrets[{inv}] mismatch with w^T investigator_regrets")
    min_exp_reg = min(float(v) for v in tp["expected_regrets"].values())
    if abs(min_exp_reg - float(tp["min_regret"])) > 1e-9:
        errs.append(f"{md_path.name}: portfolio min_regret {tp['min_regret']} != min(expected_regrets) {min_exp_reg}")

    v14_path = root / "results" / "mole_strategies" / "v14_fresh_6000_6199.json"
    if v14_path.is_file():
        v14 = _strict_json_loads(v14_path.read_text(encoding="utf-8"))
        for sname, cdict in cands.items():
            ref_s = (v14.get("strategies") or {}).get(sname)
            if ref_s is None:
                errs.append(f"{md_path.name}: candidate {sname!r} absent from v14_fresh_6000_6199.json")
                continue
            if abs(float(cdict["solver_score"]) - float(ref_s["solver"]["score"])) > 1e-9:
                errs.append(f"{md_path.name}: {sname} solver_score differs from v14_fresh_6000_6199.json")
            if abs(float(cdict["solver_accuracy"]) - float(ref_s["solver"]["accuracy"])) > 1e-9:
                errs.append(f"{md_path.name}: {sname} solver_accuracy differs from v14_fresh_6000_6199.json")
            if abs(float(cdict["min_regret"]) - float(ref_s["regret_summary"]["min_regret"])) > 1e-9:
                errs.append(f"{md_path.name}: {sname} min_regret differs from v14_fresh_6000_6199.json")
    return errs


def _parse_md_tables_by_heading(md_text: str) -> list[tuple[str, list[str], list[list[str]]]]:
    tables: list[tuple[str, list[str], list[list[str]]]] = []
    heading = ""
    cur_header: list[str] | None = None
    cur_rows: list[list[str]] = []
    in_fence = False

    for raw in md_text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if stripped.startswith(H1):
            if cur_header is not None:
                tables.append((heading, cur_header, cur_rows))
                cur_header = None
                cur_rows = []
            heading = stripped.lstrip(H1).strip()
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped[1:-1].split("|")]
            if cur_header is None:
                cur_header = cells
                cur_rows = []
            elif all(set(c) <= {"-", ":", " "} and "-" in c for c in cells):
                continue
            else:
                cur_rows.append(cells)
        else:
            if cur_header is not None:
                tables.append((heading, cur_header, cur_rows))
                cur_header = None
                cur_rows = []
    if cur_header is not None:
        tables.append((heading, cur_header, cur_rows))
    return tables


def _audit_transcript_mining_report(root: Path, md_path: Path) -> list[str]:
    rel = md_path.relative_to(root).as_posix()
    errs: list[str] = []
    txt = md_path.read_text(encoding="utf-8")
    tables = _parse_md_tables_by_heading(txt)
    if len(tables) < 4:
        return [f"{rel}: expected >= 4 markdown tables, found {len(tables)}"]

    dsl_blocks = FENCED_JSON_RE.findall(txt)
    if len(dsl_blocks) < 5:
        errs.append(f"{rel}: expected 5 Mole DSL JSON blocks in Section 5, found {len(dsl_blocks)}")
    for idx, blk in enumerate(dsl_blocks, 1):
        try:
            obj = _strict_json_loads(blk)
            st = MoleStrategy.from_json(obj)
            if not st.rules:
                errs.append(f"{rel}: DSL snippet {idx} has 0 rules")
        except Exception as exc:
            errs.append(f"{rel}: invalid DSL JSON block {idx} ({exc})")

    _, _, s2_rows = tables[0]
    _, _, s3_rows = tables[1]
    _, _, s4_rows = tables[2]
    _, _, s41_rows = tables[3]

    if len(s2_rows) != 12 or len(s3_rows) != 12 or len(s4_rows) != 12:
        errs.append(f"{rel}: expected 12 cohort rows in Sections 2/3/4, got {len(s2_rows)}/{len(s3_rows)}/{len(s4_rows)}")
        return errs

    frontier_n = sum(int(r[2]) for r in s2_rows if not r[0].startswith("Reference Solver"))
    solver_n = sum(int(r[2]) for r in s2_rows if r[0].startswith("Reference Solver"))
    if frontier_n != 159 or solver_n != 100:
        errs.append(f"{rel}: cohort episode totals frontier={frontier_n} (exp 159), solver={solver_n} (exp 100)")
    if "159 valid primary frontier episodes" not in txt or "100 reference `solver` episodes" not in txt:
        errs.append(f"{rel}: Section 1 headline episode counts out of sync with Section 2 table")

    s2_by_cohort: dict[tuple[str, str], list[str]] = {}
    for r in s2_rows:
        s2_by_cohort[(r[0], r[1])] = r
        m_surf = re.fullmatch(r"(\d+\.\d+)%\s*\((\d+)/(\d+)\)", r[9])
        if m_surf is None:
            errs.append(f"{rel}: malformed Surfaced% cell {r[9]!r} for {r[0]} ({r[1]})")
        else:
            pct, hits, planted = float(m_surf.group(1)), int(m_surf.group(2)), int(m_surf.group(3))
            if planted > 0 and abs(pct - 100.0 * hits / planted) > 0.15:
                errs.append(f"{rel}: Surfaced% {pct}% != {hits}/{planted} for {r[0]} ({r[1]})")
            exp_planted = round(int(r[2]) * float(r[5]))
            if abs(planted - exp_planted) > 1:
                errs.append(f"{rel}: planted total {planted} != n*Canaries/Ep ({exp_planted}) for {r[0]} ({r[1]})")
        rec_sum = sum(float(r[i].rstrip("%")) for i in (10, 11, 12))
        if abs(rec_sum - 100.0) > 0.25:
            errs.append(f"{rel}: recipient shares sum to {rec_sum:.2f}% != 100% for {r[0]} ({r[1]})")
        var_sum = sum(int(x.strip().rstrip("%")) for x in r[13].split("/"))
        if abs(var_sum - 100) > 2:
            errs.append(f"{rel}: variant shares sum to {var_sum}% != 100% for {r[0]} ({r[1]})")

    s3_by_cohort = {(r[0], r[1]): r for r in s3_rows}
    s4_by_cohort = {(r[0], r[1]): r for r in s4_rows}

    frontier_s4 = [r for r in s4_rows if not r[0].startswith("Reference Solver")]
    wrong_sum = sum(int(r[2].split("/")[0].strip()) for r in frontier_s4)
    gambles_sum = 0
    horiz_sum = 0
    for r in frontier_s4:
        mg = re.fullmatch(r"(\d+)\s*\((\d+)\)", r[7])
        if mg is None:
            errs.append(f"{rel}: malformed Gambles cell {r[7]!r}")
        else:
            gambles_sum += int(mg.group(1))
            horiz_sum += int(mg.group(2))
        if not r[8].endswith("100%"):
            errs.append(f"{rel}: expected 100% decoy dismissal in {r[0]} ({r[1]}), got {r[8]!r}")
    tiebreak_sum = sum(int(r[9]) for r in frontier_s4)
    if (wrong_sum, gambles_sum, horiz_sum, tiebreak_sum) != (10, 22, 13, 5):
        errs.append(
            f"{rel}: Section 4 frontier sums (wrong={wrong_sum}, gambles={gambles_sum}, "
            f"horizon={horiz_sum}, tiebreak={tiebreak_sum}) != (10, 22, 13, 5)"
        )

    fa_path = root / "results" / "failure_analysis_v1.4.json"
    if fa_path.is_file():
        fa = _strict_json_loads(fa_path.read_text(encoding="utf-8")).get("summary", {})
        for cohort_label, fa_key in (
            ("Gemini-4-carbon (OpenCode MCP)", "opencode"),
            ("Gemini-4-carbon (In-Proc)", "inproc"),
            ("Reference Solver (v1.4, seeds 0-29)", "solver"),
        ):
            ref = fa.get(fa_key)
            if not isinstance(ref, dict):
                continue
            r2 = s2_by_cohort[(cohort_label, "hard")]
            r3 = s3_by_cohort[(cohort_label, "hard")]
            r4 = s4_by_cohort[(cohort_label, "hard")]
            sc, ci = [float(x.strip()) for x in r2[3].split("+/-")]
            if abs(sc - float(ref["score"])) > 0.002 or abs(ci - float(ref["score_ci"])) > 0.002:
                errs.append(f"{rel}: {cohort_label} hard score/CI {r2[3]} != failure_analysis_v1.4.json")
            if abs(float(r2[5]) - float(ref["canaries"])) > 0.02:
                errs.append(f"{rel}: {cohort_label} hard Canaries/Ep {r2[5]} != {ref['canaries']:.2f}")
            d1 = float(r2[7].split("(")[0].strip())
            if abs(d1 - float(ref["first_canary_day"])) > 0.02:
                errs.append(f"{rel}: {cohort_label} hard First Canary Day {d1} != {ref['first_canary_day']:.2f}")
            if abs(float(r3[3]) - float(ref["interviews"])) > 0.02:
                errs.append(f"{rel}: {cohort_label} hard interview calls {r3[3]} != {ref['interviews']:.2f}")
            if abs(float(r3[4]) - float(ref["log_reads"])) > 0.02:
                errs.append(f"{rel}: {cohort_label} hard log reads {r3[4]} != {ref['log_reads']:.2f}")
            if abs(float(r3[9]) - float(ref["feed_reads"])) > 0.02:
                errs.append(f"{rel}: {cohort_label} hard feed reads {r3[9]} != {ref['feed_reads']:.2f}")
            w_cnt, a_cnt = [int(x.strip()) for x in r4[2].split("/")]
            if w_cnt != int(ref["wrong"]) or a_cnt != int(ref["abstain"]):
                errs.append(f"{rel}: {cohort_label} hard wrong/abstain {w_cnt}/{a_cnt} != {ref['wrong']}/{ref['abstain']}")

    paired_v14 = root / "data" / "runs" / "committed" / "v1.4" / "paired_table_gemini.md"
    if paired_v14.is_file():
        pv14_rows: dict[tuple[str, str], tuple[int, float, float, float]] = {}
        for ln in paired_v14.read_text(encoding="utf-8").splitlines():
            if not ln.startswith("|") or ln.startswith("|---") or ln.startswith("| tier"):
                continue
            c = [x.strip() for x in ln.strip("|").split("|")]
            run_name = c[1]
            sc_parts = [float(x.strip()) for x in re.split(r"\+/-|\u00b1", c[3])]
            if "OpenCode + gemini-4-carbon" in run_name:
                pv14_rows[("Gemini-4-carbon (OpenCode MCP)", c[0])] = (int(c[2]), sc_parts[0], sc_parts[1], float(c[4]))
            elif "in-process gemini-4-carbon" in run_name:
                pv14_rows[("Gemini-4-carbon (In-Proc)", c[0])] = (int(c[2]), sc_parts[0], sc_parts[1], float(c[4]))
            elif run_name == "reference solver":
                pv14_rows[("Reference Solver (v1.4, seeds 0-29)", c[0])] = (int(c[2]), sc_parts[0], sc_parts[1], float(c[4]))
        for key, (exp_n, exp_sc, exp_ci, exp_acc) in pv14_rows.items():
            r2 = s2_by_cohort[key]
            sc, ci = [float(x.strip()) for x in r2[3].split("+/-")]
            if int(r2[2]) != exp_n or abs(sc - exp_sc) > 0.002 or abs(ci - exp_ci) > 0.002:
                errs.append(f"{rel}: {key} n/score/CI differs from paired_table_gemini.md")
            if abs(float(r2[4].rstrip("%")) / 100.0 - exp_acc) > 0.01:
                errs.append(f"{rel}: {key} accuracy differs from paired_table_gemini.md")

    paired_v13 = root / "data" / "runs" / "committed" / "v1.3" / "paired_table.md"
    if paired_v13.is_file():
        pv13_rows: dict[tuple[str, str], tuple[int, float, float, float]] = {}
        for ln in paired_v13.read_text(encoding="utf-8").splitlines():
            if not ln.startswith("|") or ln.startswith("|---") or ln.startswith("| tier"):
                continue
            c = [x.strip() for x in ln.strip("|").split("|")]
            run_name = c[1]
            sc_parts = [float(x.strip()) for x in re.split(r"\+/-|\u00b1", c[3])]
            if "Codex gpt-5.5 over MCP" in run_name and "full run" in run_name:
                pv13_rows[("Codex GPT-5.5 (MCP)", c[0])] = (int(c[2]), sc_parts[0], sc_parts[1], float(c[4]))
            elif "in-process gpt-5.5, fixed loop" in run_name:
                pv13_rows[("GPT-5.5 (In-Proc)", c[0])] = (int(c[2]), sc_parts[0], sc_parts[1], float(c[4]))
            elif run_name == "reference solver":
                pv13_rows[("Reference Solver (v1.3, seeds 0-19)", c[0])] = (int(c[2]), sc_parts[0], sc_parts[1], float(c[4]))
        for key, (exp_n, exp_sc, exp_ci, exp_acc) in pv13_rows.items():
            r2 = s2_by_cohort[key]
            sc, ci = [float(x.strip()) for x in r2[3].split("+/-")]
            if int(r2[2]) != exp_n or abs(sc - exp_sc) > 0.002 or abs(ci - exp_ci) > 0.002:
                errs.append(f"{rel}: {key} n/score/CI differs from v1.3/paired_table.md")
            if abs(float(r2[4].rstrip("%")) / 100.0 - exp_acc) > 0.01:
                errs.append(f"{rel}: {key} accuracy differs from v1.3/paired_table.md")

    accuse_sources = (
        ("v1.4/opencode-gemini-4-carbon/accuse.md", "v1.4_gemini_opencode"),
        ("v1.4/inproc-gemini-4-carbon/accuse.md", "v1.4_gemini_inproc"),
        ("v1.3/codex-gpt-5.5-full/accuse.md", "v1.3_codex_gpt55"),
        ("v1.3/gpt-5.5-full/accuse.md", "v1.3_inproc_gpt55"),
    )
    accuse_map: dict[tuple[str, str, int], dict[str, Any]] = {}
    for rel_acc, cid in accuse_sources:
        ap = root / "data" / "runs" / "committed" / rel_acc
        if not ap.is_file():
            continue
        for ln in ap.read_text(encoding="utf-8").splitlines():
            if not ln.startswith("|") or ln.startswith("|---") or ln.startswith("| tier"):
                continue
            c = [x.strip() for x in ln.strip("|").split("|")]
            accuse_map[(cid, c[0], int(c[2]))] = {
                "day": int(c[3]),
                "accused": c[4],
                "score": float(c[6]),
                "p_acc": None if c[7] == "None" else float(c[7]),
            }

    if accuse_map:
        for r in s41_rows:
            cid = r[0].strip("`")
            tier = r[1]
            seed = int(r[2])
            ref_ep = accuse_map.get((cid, tier, seed))
            if ref_ep is None:
                errs.append(f"{rel}: Section 4.1 episode ({cid}, {tier}, seed={seed}) absent from committed accuse.md")
                continue
            m_day = re.fullmatch(r"(\d+)\s*\((\d+)\)", r[3])
            m_sc = re.fullmatch(r"([+-]?\d+\.\d+)\s*\(([+-]?\d+\.\d+)\)", r[5])
            m_p = re.fullmatch(r"(n/a|\d+\.\d+)\s+vs\s+(\d+\.\d+)", r[6])
            if m_day is None or m_sc is None or m_p is None:
                errs.append(f"{rel}: malformed Section 4.1 row for ({cid}, {tier}, seed={seed})")
                continue
            if int(m_day.group(1)) != ref_ep["day"]:
                errs.append(f"{rel}: ({cid}, {tier}, seed={seed}) day {m_day.group(1)} != accuse.md {ref_ep['day']}")
            if r[4] != ref_ep["accused"]:
                errs.append(f"{rel}: ({cid}, {tier}, seed={seed}) accused {r[4]!r} != accuse.md {ref_ep['accused']!r}")
            if abs(float(m_sc.group(1)) - float(ref_ep["score"])) > 0.011:
                errs.append(f"{rel}: ({cid}, {tier}, seed={seed}) score {m_sc.group(1)} != accuse.md {ref_ep['score']}")
            p_tok = m_p.group(1)
            if p_tok == "n/a":
                if ref_ep["p_acc"] is not None:
                    errs.append(f"{rel}: ({cid}, {tier}, seed={seed}) P(acc) n/a != {ref_ep['p_acc']}")
            elif ref_ep["p_acc"] is None or abs(float(p_tok) - float(ref_ep["p_acc"])) > 0.002:
                errs.append(f"{rel}: ({cid}, {tier}, seed={seed}) P(acc) {p_tok} != accuse.md {ref_ep['p_acc']}")

    expected_anchors: dict[str, float] = {
        "codex_medium_le3_share": float(s2_by_cohort[("Codex GPT-5.5 (MCP)", "medium")][10].rstrip("%")) / 100.0,
        "codex_hard_le3_share": float(s2_by_cohort[("Codex GPT-5.5 (MCP)", "hard")][10].rstrip("%")) / 100.0,
        "gpt55_medium_le3_share": float(s2_by_cohort[("GPT-5.5 (In-Proc)", "medium")][10].rstrip("%")) / 100.0,
        "gpt55_hard_le3_share": float(s2_by_cohort[("GPT-5.5 (In-Proc)", "hard")][10].rstrip("%")) / 100.0,
        "gemini_opencode_hard_le3_share": float(s2_by_cohort[("Gemini-4-carbon (OpenCode MCP)", "hard")][10].rstrip("%")) / 100.0,
        "gemini_opencode_hard_4_to_8_share": float(s2_by_cohort[("Gemini-4-carbon (OpenCode MCP)", "hard")][11].rstrip("%")) / 100.0,
        "gemini_inproc_hard_4_to_8_share": float(s2_by_cohort[("Gemini-4-carbon (In-Proc)", "hard")][11].rstrip("%")) / 100.0,
        "gemini_inproc_medium_4_to_8_share": float(s2_by_cohort[("Gemini-4-carbon (In-Proc)", "medium")][11].rstrip("%")) / 100.0,
        "gemini_opencode_hard_first_canary_day": float(s2_by_cohort[("Gemini-4-carbon (OpenCode MCP)", "hard")][7].split("(")[0]),
        "gemini_inproc_hard_first_canary_day": float(s2_by_cohort[("Gemini-4-carbon (In-Proc)", "hard")][7].split("(")[0]),
        "solver_hard_first_canary_day": float(s2_by_cohort[("Reference Solver (v1.4, seeds 0-29)", "hard")][7].split("(")[0]),
        "frontier_decoy_dismissal_rate": 1.0,
        "frontier_decoy_accused_total": 0.0,
        "wrong_non_decoy_framed_tiebreak": float(tiebreak_sum),
        "gemini_opencode_hard_log_calls": float(s3_by_cohort[("Gemini-4-carbon (OpenCode MCP)", "hard")][4]),
        "gemini_opencode_hard_interviews": float(s3_by_cohort[("Gemini-4-carbon (OpenCode MCP)", "hard")][3]),
        "gemini_inproc_hard_interviews": float(s3_by_cohort[("Gemini-4-carbon (In-Proc)", "hard")][3]),
        "frontier_below_breakeven_gambles_total": float(gambles_sum),
        "frontier_horizon_gambles_total": float(horiz_sum),
    }
    found_anchors = {
        m.group(1): float(m.group(2))
        for m in re.finditer(r"`([a-z0-9_]+)=(-?\d+(?:\.\d+)?)`", txt)
    }
    for akey, aval in expected_anchors.items():
        if akey not in found_anchors:
            errs.append(f"{rel}: missing Section 5 measured anchor {akey!r}")
        elif abs(found_anchors[akey] - aval) > 1e-6:
            errs.append(f"{rel}: Section 5 anchor {akey}={found_anchors[akey]} != table value {aval}")

    return errs


def _map_ladder_display_model(disp: str) -> str:
    if disp.startswith("gemma-4-31b-it"):
        return "gemma-4-31b-it"
    if disp.startswith("gemini-3.5-flash"):
        return "gemini-3.5-flash"
    return disp


def _map_ladder_family(model: str) -> str:
    if model.startswith("gemma"):
        return "Gemma 4 31B (open-weight)"
    if "flash-lite" in model:
        return "Gemini 3.1 Flash-Lite"
    if "flash" in model:
        return "Gemini 3.5/3.6 & 3.8 Flash"
    return "Gemini 4 (Hydrogen/Argon/Carbon)"


def _audit_ladder_scale_report(root: Path, md_path: Path) -> list[str]:
    rel = md_path.relative_to(root).as_posix()
    errs: list[str] = []
    txt = md_path.read_text(encoding="utf-8")
    tables = _parse_md_tables_by_heading(txt)
    if len(tables) < 5:
        return [f"{rel}: expected >= 5 markdown tables, found {len(tables)}"]

    _, _, fam_rows = tables[0]
    _, _, hard_rows = tables[1]
    _, _, med_rows = tables[2]
    _, _, delta_rows = tables[3]
    _, _, cf_rows = tables[4]

    if len(hard_rows) != 21 or len(med_rows) != 20:
        errs.append(f"{rel}: expected 21 Hard + 20 Medium cells, got {len(hard_rows)} + {len(med_rows)}")
        return errs

    n_hard = sum(int(r[2]) for r in hard_rows)
    n_med = sum(int(r[2]) for r in med_rows)
    if n_hard != 297 or n_med != 258 or (n_hard + n_med) != 555:
        errs.append(f"{rel}: cell episode totals hard={n_hard}, medium={n_med}, sum={n_hard + n_med} (expected 297, 258, 555)")
    if "**555** valid exported ladder episodes across **41**" not in txt:
        errs.append(f"{rel}: Section 1 corpus count headline out of sync with cell tables")

    lad_json_path = root / "results" / "gemini" / "ladder.json"
    lad_lookup: dict[tuple[str, str, str], dict[str, Any]] = {}
    if lad_json_path.is_file():
        lad_json = _strict_json_loads(lad_json_path.read_text(encoding="utf-8"))
        for r in lad_json.get("rows", []):
            if r.get("source") == "ladder":
                lad_lookup[(r["model"], r["level"], r["tier"])] = r
        for r in (lad_json.get("gemma") or {}).get("rows", []):
            lad_lookup[(r["model"], r["level"], r["tier"])] = r

    cell_metrics: dict[tuple[str, str, str], dict[str, Any]] = {}
    for tier, rows in (("hard", hard_rows), ("medium", med_rows)):
        for r in rows:
            disp_m, lvl = r[0], r[1]
            m = _map_ladder_display_model(disp_m)
            n = int(r[2])
            sc, ci = [float(x.strip()) for x in r[3].split("+/-")]
            acc_pct = float(r[4].rstrip("%"))
            ttok = int(r[5])
            can_ep = float(r[6])
            le3 = float(r[7].rstrip("%"))
            r48 = float(r[8].rstrip("%"))
            ge9 = float(r[9].rstrip("%"))
            if abs((le3 + r48 + ge9) - 100.0) > 0.25:
                errs.append(f"{rel}: ({m}, {lvl}, {tier}) recipient buckets sum to {le3 + r48 + ge9:.2f}% != 100%")
            m_lag = re.fullmatch(r"(\d+\.\d+)\s*\(([+-]\d+\.\d+)d\)", r[10])
            if m_lag is None:
                errs.append(f"{rel}: ({m}, {lvl}, {tier}) malformed 1st Can cell {r[10]!r}")
                d1_lag = 0.0
            else:
                d1_day, d1_lag = float(m_lag.group(1)), float(m_lag.group(2))
                if abs((d1_day - 1.0) - d1_lag) > 0.02:
                    errs.append(f"{rel}: ({m}, {lvl}, {tier}) 1st Can lag {d1_lag} != {d1_day} - 1.00")
            iv_pct = float(r[11].rstrip("%"))
            m_bbe = re.fullmatch(r"(\d+)/(\d+)\s*\((\d+\.\d+)%\)", r[13])
            if m_bbe is None:
                errs.append(f"{rel}: ({m}, {lvl}, {tier}) malformed Below-BE cell {r[13]!r}")
                bbe_num, bbe_den, bbe_pct = 0, 1, 0.0
            else:
                bbe_num, bbe_den, bbe_pct = int(m_bbe.group(1)), int(m_bbe.group(2)), float(m_bbe.group(3))
                if bbe_den > 0 and abs(bbe_pct - 100.0 * bbe_num / bbe_den) > 0.15:
                    errs.append(f"{rel}: ({m}, {lvl}, {tier}) Below-BE% {bbe_pct}% != {bbe_num}/{bbe_den}")

            if lad_lookup:
                ref = lad_lookup.get((m, lvl, tier))
                if ref is None:
                    errs.append(f"{rel}: ({m}, {lvl}, {tier}) missing in results/gemini/ladder.json")
                else:
                    if n != int(ref["n"]):
                        errs.append(f"{rel}: ({m}, {lvl}, {tier}) n={n} != ladder.json {ref['n']}")
                    if abs(sc - float(ref["mean"])) > 0.002 or abs(ci - float(ref["ci"])) > 0.002:
                        errs.append(f"{rel}: ({m}, {lvl}, {tier}) score/CI {sc}+/-{ci} != ladder.json")
                    if abs(acc_pct / 100.0 - float(ref["accuracy"])) > 0.002:
                        errs.append(f"{rel}: ({m}, {lvl}, {tier}) acc {acc_pct}% != ladder.json")
                    if abs(ttok - round(float(ref["thinking_per_ep"]))) > 1:
                        errs.append(f"{rel}: ({m}, {lvl}, {tier}) thinking tokens {ttok} != {ref['thinking_per_ep']}")

            cell_metrics[(disp_m, lvl, tier)] = {
                "model": m,
                "family": _map_ladder_family(m),
                "n": n,
                "score": sc,
                "acc_pct": acc_pct,
                "can_ep": can_ep,
                "le3": le3,
                "r48": r48,
                "lag": d1_lag,
                "iv_pct": iv_pct,
                "bbe_num": bbe_num,
                "bbe_den": bbe_den,
                "bbe_pct": bbe_pct,
            }

    for r in fam_rows:
        fam_label, tier = r[0], r[1]
        n_fam = int(r[2])
        sc_fam = float(r[3].split("+/-")[0].strip())
        acc_fam = float(r[4].rstrip("%"))
        can_fam = float(r[5])
        m_bbe = re.fullmatch(r"(\d+)/(\d+)\s*\((\d+\.\d+)%\)", r[12])
        sub = [v for (_, _, t), v in cell_metrics.items() if t == tier and v["family"] == fam_label]
        exp_n = sum(v["n"] for v in sub)
        if n_fam != exp_n or exp_n == 0:
            errs.append(f"{rel}: Family ({fam_label}, {tier}) n={n_fam} != cell sum {exp_n}")
            continue
        exp_sc = sum(v["n"] * v["score"] for v in sub) / exp_n
        exp_acc = sum(v["n"] * v["acc_pct"] for v in sub) / exp_n
        exp_can = sum(v["n"] * v["can_ep"] for v in sub) / exp_n
        if abs(sc_fam - exp_sc) > 0.003:
            errs.append(f"{rel}: Family ({fam_label}, {tier}) score {sc_fam} != weighted cell mean {exp_sc:.3f}")
        if abs(acc_fam - exp_acc) > 0.15:
            errs.append(f"{rel}: Family ({fam_label}, {tier}) acc {acc_fam}% != weighted cell mean {exp_acc:.1f}%")
        if abs(can_fam - exp_can) > 0.02:
            errs.append(f"{rel}: Family ({fam_label}, {tier}) Can/Ep {can_fam} != weighted cell mean {exp_can:.2f}")
        if m_bbe is not None:
            if int(m_bbe.group(1)) != sum(v["bbe_num"] for v in sub) or int(m_bbe.group(2)) != sum(v["bbe_den"] for v in sub):
                errs.append(f"{rel}: Family ({fam_label}, {tier}) Below-BE counts mismatch cell sum")

    for r in delta_rows:
        disp_m, tier = r[0], r[1]
        lo = cell_metrics.get((disp_m, "low", tier))
        hi = cell_metrics.get((disp_m, "high", tier))
        if lo is None or hi is None:
            errs.append(f"{rel}: Section 5 row ({disp_m}, {tier}) missing low/high cell")
            continue
        if r[2] != f"{lo['n']}/{hi['n']}":
            errs.append(f"{rel}: Section 5 ({disp_m}, {tier}) n={r[2]} != {lo['n']}/{hi['n']}")
        dsc = float(r[3])
        if abs(dsc - (hi["score"] - lo["score"])) > 0.003:
            errs.append(f"{rel}: Section 5 ({disp_m}, {tier}) dScore={dsc} != high-low {hi['score'] - lo['score']:.3f}")
        dacc = float(r[4].rstrip("%"))
        if abs(dacc - (hi["acc_pct"] - lo["acc_pct"])) > 0.2:
            errs.append(f"{rel}: Section 5 ({disp_m}, {tier}) dAcc={dacc}% != high-low")

    cf_cell_list: list[dict[str, Any]] = []
    for r in cf_rows:
        clean = [c.replace("**", "").strip() for c in r]
        disp_m, lvl = clean[0], clean[1]
        n_c = int(clean[2])
        p_def, p_syn = [float(x.strip()) for x in clean[3].split("->")]
        p_drop = float(clean[4].split("+/-")[0].strip())
        ev_def, ev_syn = [float(x.strip()) for x in clean[5].split("->")]
        ev_drop = float(clean[6].split("+/-")[0].strip())
        m_sc = re.fullmatch(r"(\d+\.\d+)\s*->\s*(\d+\.\d+)\s*\(([+-]\d+\.\d+)\)", clean[7])
        if abs((p_def - p_syn) - p_drop) > 0.003:
            errs.append(f"{rel}: Section 6 ({disp_m}, {lvl}) P(mole) drop {p_drop} != {p_def} - {p_syn}")
        if abs((ev_def - ev_syn) - ev_drop) > 0.003:
            errs.append(f"{rel}: Section 6 ({disp_m}, {lvl}) opt_EV drop {ev_drop} != {ev_def} - {ev_syn}")
        if m_sc is not None:
            sc_d, sc_s, sc_del = float(m_sc.group(1)), float(m_sc.group(2)), float(m_sc.group(3))
            if abs((sc_s - sc_d) - sc_del) > 0.02:
                errs.append(f"{rel}: Section 6 ({disp_m}, {lvl}) surfaced canary delta {sc_del} != {sc_s} - {sc_d}")
        if disp_m == "Capable Gemini Pooled":
            cap = [x for x in cf_cell_list if not x["disp"].startswith("gemma") and "flash-lite" not in x["disp"]]
            if n_c != sum(x["n"] for x in cap) or n_c == 0:
                errs.append(f"{rel}: Capable Gemini Pooled n={n_c} != {sum(x['n'] for x in cap)}")
            else:
                w_p_def = sum(x["n"] * x["p_def"] for x in cap) / n_c
                w_p_syn = sum(x["n"] * x["p_syn"] for x in cap) / n_c
                w_ev_def = sum(x["n"] * x["ev_def"] for x in cap) / n_c
                w_ev_syn = sum(x["n"] * x["ev_syn"] for x in cap) / n_c
                if abs(p_def - w_p_def) > 0.003 or abs(p_syn - w_p_syn) > 0.003:
                    errs.append(f"{rel}: Capable Gemini Pooled P(mole) differs from n-weighted cell mean")
                if abs(ev_def - w_ev_def) > 0.003 or abs(ev_syn - w_ev_syn) > 0.003:
                    errs.append(f"{rel}: Capable Gemini Pooled opt_EV differs from n-weighted cell mean")
                if f"**{p_def:.3f}** to **{p_syn:.3f}**" not in txt or f"**{ev_def:.3f}** to **{ev_syn:.3f}**" not in txt:
                    errs.append(f"{rel}: Section 1 counterfactual pooled headline out of sync with Section 6")
        elif disp_m == "All Hard Cells Pooled":
            if n_c != sum(x["n"] for x in cf_cell_list) or n_c == 0:
                errs.append(f"{rel}: All Hard Cells Pooled n={n_c} != {sum(x['n'] for x in cf_cell_list)}")
            else:
                w_p_def = sum(x["n"] * x["p_def"] for x in cf_cell_list) / n_c
                w_p_syn = sum(x["n"] * x["p_syn"] for x in cf_cell_list) / n_c
                w_ev_def = sum(x["n"] * x["ev_def"] for x in cf_cell_list) / n_c
                w_ev_syn = sum(x["n"] * x["ev_syn"] for x in cf_cell_list) / n_c
                if abs(p_def - w_p_def) > 0.003 or abs(p_syn - w_p_syn) > 0.003:
                    errs.append(f"{rel}: All Hard Cells Pooled P(mole) differs from n-weighted cell mean")
                if abs(ev_def - w_ev_def) > 0.003 or abs(ev_syn - w_ev_syn) > 0.003:
                    errs.append(f"{rel}: All Hard Cells Pooled opt_EV differs from n-weighted cell mean")
        else:
            cf_cell_list.append({
                "disp": disp_m,
                "n": n_c,
                "p_def": p_def,
                "p_syn": p_syn,
                "ev_def": ev_def,
                "ev_syn": ev_syn,
                "ev_drop": ev_drop,
            })

    return errs


def _audit_cross_mole_json_parity(root: Path) -> list[str]:
    errs: list[str] = []
    v14_p = root / "results" / "mole_strategies" / "v14_fresh_6000_6199.json"
    abl_p = root / "results" / "mole_strategies" / "lever_ablation_v14.json"
    trf_p = root / "results" / "mole_strategies" / "cross_model_transfer.json"
    if not (v14_p.is_file() and abl_p.is_file() and trf_p.is_file()):
        return errs

    v14 = _strict_json_loads(v14_p.read_text(encoding="utf-8"))
    abl = _strict_json_loads(abl_p.read_text(encoding="utf-8"))
    trf = _strict_json_loads(trf_p.read_text(encoding="utf-8"))

    for sname in v14.get("strategy_order", []):
        tkey = "default" if sname == "default_v0" else sname
        s_v14 = v14["strategies"][sname]
        cat_t = (trf.get("catalog") or {}).get(tkey)
        if cat_t is None:
            errs.append(f"cross-parity: {tkey!r} missing in cross_model_transfer.json catalog")
            continue
        if s_v14["behavior_hash"] != cat_t["behavior_hash"]:
            errs.append(f"cross-parity: behavior_hash mismatch for {sname} between v14_fresh and cross_model_transfer")
        cf1 = s_v14["counterfactual"]
        cf2 = trf["counterfactual"]["strategies"][tkey]["rollups"]["gemini_4_carbon_hard"]
        for metric in ("p_true_mole", "p_true_mole_drop", "optimal_ev", "optimal_ev_drop", "surfaced_canaries"):
            if abs(float(cf1[metric]) - float(cf2[metric])) > 1e-3:
                errs.append(
                    f"cross-parity: {sname} counterfactual.{metric} {cf1[metric]} != transfer {cf2[metric]}"
                )

    for sname in ("default_v0", "frontier_synthesis_v14"):
        if sname in v14.get("strategies", {}) and sname in abl.get("arms", {}):
            if v14["strategies"][sname]["behavior_hash"] != abl["arms"][sname]["behavior_hash"]:
                errs.append(f"cross-parity: {sname} behavior_hash mismatch between v14_fresh and lever_ablation_v14")
            cf1 = v14["strategies"][sname]["counterfactual"]
            cfa = abl["arms"][sname]["counterfactual"]
            if abs(float(cf1["optimal_ev"]) - float(cfa["optimal_ev"])) > 1e-5:
                errs.append(f"cross-parity: {sname} counterfactual.optimal_ev mismatch between v14_fresh and ablation")
            if abs(float(cf1["p_true_mole"]) - float(cfa["p_true_mole"])) > 1e-5:
                errs.append(f"cross-parity: {sname} counterfactual.p_true_mole mismatch between v14_fresh and ablation")
    return errs


def _audit_generic_markdown_report(root: Path, md_path: Path) -> list[str]:
    rel = md_path.relative_to(root).as_posix()
    errs: list[str] = []
    txt = md_path.read_text(encoding="utf-8")

    for m in EMBEDDED_LEDGER_RE.finditer(txt):
        try:
            ledger = _strict_json_loads(m.group(2))
            if not isinstance(ledger, dict):
                errs.append(f"{rel}: embedded ledger {m.group(1)} must be a JSON object")
            else:
                errs.extend(_ensure_finite_numbers(ledger, f"{rel}:{m.group(1)}"))
                for bad_k in _find_forbidden_secret_keys(ledger, f"{rel}:{m.group(1)}"):
                    errs.append(f"{bad_k}: forbidden secret key in embedded ledger")
        except Exception as exc:
            errs.append(f"{rel}: invalid embedded ledger JSON ({exc})")

    for idx, blk in enumerate(FENCED_JSON_RE.findall(txt), 1):
        try:
            obj = _strict_json_loads(blk)
            if isinstance(obj, dict) and {"name", "rules", "default"} <= set(obj.keys()):
                MoleStrategy.from_json(obj)
        except Exception as exc:
            errs.append(f"{rel}: invalid fenced JSON block {idx} ({exc})")

    for heading, header, rows in _parse_md_tables_by_heading(txt):
        for r_idx, row in enumerate(rows, 1):
            if len(row) != len(header):
                errs.append(
                    f"{rel}: table {heading!r} row {r_idx} has {len(row)} column(s), expected {len(header)}"
                )
            for cell in row:
                low_c = cell.lower()
                if low_c in {"nan", "+nan", "-nan", "inf", "+inf", "-inf", "infinity", "-infinity"}:
                    errs.append(f"{rel}: table {heading!r} row {r_idx} contains non-finite cell {cell!r}")

    for ref_match in re.finditer(r"results/mole_strategies/([A-Za-z0-9_.-]+\.json)", txt):
        ref_jp = root / "results" / "mole_strategies" / ref_match.group(1)
        if not ref_jp.is_file():
            errs.append(f"{rel}: references missing JSON file results/mole_strategies/{ref_match.group(1)}")
    return errs


def check_mole_ledger_and_report_parity(root: Path) -> CheckResult:
    name = "Mole Reports Ledger & Numerical Parity"
    mole_md, _, _, _ = _discover_azure_targets(root)
    if not mole_md:
        return CheckResult(name, "FAIL", "no docs/reports/mole_*.md files found")

    failures: list[str] = []
    for mp in mole_md:
        rel = mp.relative_to(root).as_posix()
        failures.extend(_audit_generic_markdown_report(root, mp))

        if mp.name == "mole_strategies_v14.md":
            jp = root / "results" / "mole_strategies" / "v14_fresh_6000_6199.json"
            ok, msg = check_v14_eval_report(json_path=jp, md_path=mp)
            if not ok:
                failures.append(f"{rel}: {msg}")
        elif mp.name == "mole_lever_ablation_v14.md":
            jp = root / "results" / "mole_strategies" / "lever_ablation_v14.json"
            ok, msg = check_ablation_artifacts(json_path=jp, md_path=mp)
            if not ok:
                failures.append(f"{rel}: {msg}")
        elif mp.name == "mole_cross_model_transfer.md":
            jp = root / "results" / "mole_strategies" / "cross_model_transfer.json"
            ok, msg = check_transfer_artifacts(json_path=jp, md_path=mp)
            if not ok:
                failures.append(f"{rel}: {msg}")
        elif mp.name == "mole_regret_portfolio_v14.md":
            failures.extend(_audit_portfolio_cross_parity(root, mp))
        elif mp.name == "mole_discipline_curve_v14.md":
            jp = root / "results" / "mole_strategies" / "discipline_curve_v14.json"
            ok, msg = check_discipline_artifacts(json_path=jp, md_path=mp)
            if not ok:
                failures.append(f"{rel}: {msg}")
        elif mp.name == "mole_tier_robustness_v14.md":
            jp = root / "results" / "mole_strategies" / "tier_robustness_v14.json"
            ok, msg = check_tier_robustness_artifacts(json_path=jp, md_path=mp)
            if not ok:
                failures.append(f"{rel}: {msg}")
        elif mp.name == "mole_worked_predicate_v14.md":
            jp = root / "results" / "mole_strategies" / "worked_predicate_v14.json"
            ok, msg = check_worked_predicate_artifacts(json_path=jp, md_path=mp)
            if not ok:
                failures.append(f"{rel}: {msg}")
        elif mp.name == "mole_representation_pareto_v14.md":
            jp = root / "results" / "mole_strategies" / "representation_pareto_v14.json"
            ok, msg = check_representation_pareto_artifacts(json_path=jp, md_path=mp)
            if not ok:
                failures.append(f"{rel}: {msg}")
        elif mp.name == "mole_transcript_mining.md":
            failures.extend(_audit_transcript_mining_report(root, mp))
        elif mp.name == "mole_ladder_scale_analysis.md":
            failures.extend(_audit_ladder_scale_report(root, mp))

    rl_md = root / "docs" / "reports" / "rl_mole_frontier_v14.md"
    rl_pol = root / "data" / "forge" / "rl_mole_frontier_v14.json"
    if rl_md.is_file() or rl_pol.is_file():
        ok, msg = check_distilled_artifacts(policy_path=rl_pol, report_path=rl_md)
        if not ok:
            failures.append(f"docs/reports/rl_mole_frontier_v14.md: {msg}")

    failures.extend(_audit_cross_mole_json_parity(root))

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} numerical/ledger parity mismatch(es) across {len(mole_md)} mole report(s)",
            failures,
        )
    return CheckResult(
        name,
        "PASS",
        f"verified {len(mole_md)} mole_*.md report(s) ({', '.join(p.name for p in mole_md)}) "
        "and cross-JSON counterfactual/behavior-hash parity",
    )


def _audit_v16_fairness_pair(root: Path, md_path: Path) -> list[str]:
    rel = md_path.relative_to(root).as_posix()
    jp = root / "results" / "v16_social" / "social_audit_report.json"
    if not jp.is_file():
        return [f"{rel}: missing backing JSON {jp.relative_to(root).as_posix()}"]
    try:
        report = _strict_json_loads(jp.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"results/v16_social/social_audit_report.json: invalid JSON ({exc})"]
    if not isinstance(report, dict):
        return ["results/v16_social/social_audit_report.json: root must be a JSON object"]

    errs = _ensure_finite_numbers(report, "social_audit_report.json")
    for bad_k in _find_forbidden_secret_keys(report, "social_audit_report.json"):
        errs.append(f"{bad_k}: forbidden secret key")
    if report.get("overall_passed") is not True:
        errs.append("social_audit_report.json: overall_passed != True")
    if report.get("all_v16_providers_passed") is not True:
        errs.append("social_audit_report.json: all_v16_providers_passed != True")
    if report.get("all_episode_replays_passed") is not True:
        errs.append("social_audit_report.json: all_episode_replays_passed != True")
    if int(report.get("live_api_calls", -1)) != 0 or int(report.get("blocked_api_attempts", -1)) != 0:
        errs.append("social_audit_report.json: expected live_api_calls==0 and blocked_api_attempts==0")
    if report.get("offline_enforced") is not True:
        errs.append("social_audit_report.json: offline_enforced != True")
    n_aud = int(report.get("n_providers_audited", 0))
    n_pass = int(report.get("n_providers_passed", -1))
    if n_aud < 16 or n_aud != n_pass or len(report.get("provider_audits", [])) != n_aud:
        errs.append(f"social_audit_report.json: provider audit count mismatch ({n_pass}/{n_aud})")
    for p_entry in report.get("provider_audits", []):
        par = ((p_entry.get("six_fairness_checks") or {}).get("bit_exact_solver_parity") or {})
        if abs(float(par.get("max_abs_score_diff", 1.0))) > 1e-12:
            errs.append(f"social_audit_report.json: {p_entry.get('spec')} max_abs_score_diff != 0.0")

    expected_md = render_v16_fairness_md(report)
    actual_md = md_path.read_text(encoding="utf-8")
    if actual_md.rstrip("\n") != expected_md.rstrip("\n"):
        errs.append(f"{rel}: markdown content differs from render_markdown_report(social_audit_report.json)")
    return errs


def _parse_ratio_cell(cell: str) -> tuple[float | None, float | None]:
    clean = cell.strip()
    if clean.startswith("n/a"):
        return None, None
    m = re.fullmatch(r"([+-]?\d+\.\d+)\s*\(([+-]?\d+\.\d+)%\)", clean)
    if m is None:
        raise ValueError(f"unrecognized ratio cell {cell!r}")
    return float(m.group(1)), float(m.group(2))


def _audit_v16_eval_pair(root: Path, md_path: Path) -> list[str]:
    rel = md_path.relative_to(root).as_posix()
    jp = root / "results" / "v16_social" / "partial_summary.json"
    if not jp.is_file():
        return [f"{rel}: missing backing JSON {jp.relative_to(root).as_posix()}"]
    try:
        ps = _strict_json_loads(jp.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"results/v16_social/partial_summary.json: invalid JSON ({exc})"]
    if not isinstance(ps, dict):
        return ["results/v16_social/partial_summary.json: root must be a JSON object"]

    errs = _ensure_finite_numbers(ps, "partial_summary.json")
    for bad_k in _find_forbidden_secret_keys(ps, "partial_summary.json"):
        errs.append(f"{bad_k}: forbidden secret key")
    if ps.get("schema_version") != "v16_compare_30_44.v1":
        errs.append(f"partial_summary.json: unexpected schema_version {ps.get('schema_version')!r}")
    gates = ps.get("gates") or {}
    if gates.get("all_passed") is not True:
        errs.append("partial_summary.json: gates.all_passed != True")
    if ps.get("gap_widening_gate_met") is not False or ps.get("sample_size_gate_met") is not False:
        errs.append("partial_summary.json: expected gap_widening_gate_met=False and sample_size_gate_met=False")

    seed_table = ps.get("per_variant_seed_table") or []
    var_table = ps.get("variant_table") or []
    if len(seed_table) != 10 or len(var_table) != 6:
        errs.append(f"partial_summary.json: expected 10 seed rows and 6 variant rows, got {len(seed_table)} and {len(var_table)}")
        return errs

    ref_p = root / "results" / "v16_social" / "reference_seeds_30_49.json"
    if ref_p.is_file():
        ref_json = _strict_json_loads(ref_p.read_text(encoding="utf-8"))
        ref_seeds = {int(r["seed"]): r for r in ref_json.get("seeds", [])}
        for row in seed_table:
            sref = ref_seeds.get(int(row["seed"]))
            if sref is None:
                errs.append(f"partial_summary.json: seed {row['seed']} missing in reference_seeds_30_49.json")
                continue
            if abs(float(row["solver_score"]) - float(sref["solver_score"])) > 1e-9:
                errs.append(f"partial_summary.json: ({row['variant']}, {row['seed']}) solver_score != reference")
            if abs(float(row["solver_luck_adj"]) - float(sref["solver_luck_adj"])) > 1e-6:
                errs.append(f"partial_summary.json: ({row['variant']}, {row['seed']}) solver_luck_adj != reference")
            if int(row["solver_final_day"]) != int(sref["solver_day"]):
                errs.append(f"partial_summary.json: ({row['variant']}, {row['seed']}) solver_final_day != reference")

    partial_dir = root / "results" / "v16_social" / "partial"
    if partial_dir.is_dir():
        raw_eps: dict[tuple[str, int], dict[str, Any]] = {}
        for ep_file in sorted(partial_dir.glob("*/hard/episodes.jsonl")):
            vname = ep_file.parts[-3]
            for ln in ep_file.read_text(encoding="utf-8").splitlines():
                if not ln.strip():
                    continue
                ep = _strict_json_loads(ln)
                raw_eps[(vname, int(ep["seed"]))] = ep
        if len(raw_eps) != len(seed_table):
            errs.append(f"partial_summary.json: {len(seed_table)} rows != {len(raw_eps)} episodes in results/v16_social/partial")
        for row in seed_table:
            ep = raw_eps.get((row["variant"], int(row["seed"])))
            if ep is None:
                errs.append(f"partial_summary.json: missing raw episode for ({row['variant']}, {row['seed']})")
                continue
            if abs(float(row["gemini_score"]) - float(ep["score"])) > 1e-9:
                errs.append(f"partial_summary.json: ({row['variant']}, {row['seed']}) score != episodes.jsonl")
            if int(row["gemini_final_day"]) != int(ep["final_day"]):
                errs.append(f"partial_summary.json: ({row['variant']}, {row['seed']}) final_day != episodes.jsonl")

    sa_p = root / "results" / "v16_social" / "social_audit_report.json"
    if sa_p.is_file():
        sa_json = _strict_json_loads(sa_p.read_text(encoding="utf-8"))
        sa_seeds: dict[tuple[str, int], dict[str, Any]] = {}
        for f_entry in (sa_json.get("shared_runs_replay_audit") or {}).get("files", []):
            for sr in f_entry.get("per_seed", []):
                sa_seeds[(f_entry["variant"], int(sr["seed"]))] = sr
        if sa_seeds:
            for row in seed_table:
                sr = sa_seeds.get((row["variant"], int(row["seed"])))
                if sr is None:
                    errs.append(f"partial_summary.json: ({row['variant']}, {row['seed']}) absent from social_audit_report.json")
                    continue
                if abs(float(row["gemini_score"]) - float(sr["score"])) > 1e-9:
                    errs.append(f"partial_summary.json: ({row['variant']}, {row['seed']}) score != social_audit_report.json")
                if abs(float(row["gemini_luck_adj"]) - float(sr["luck_adjusted_score"])) > 1e-4:
                    errs.append(f"partial_summary.json: ({row['variant']}, {row['seed']}) luck_adj != social_audit_report.json")
                if abs(float(row["gemini_p_accused"]) - float(sr["p_accused"])) > 1e-4:
                    errs.append(f"partial_summary.json: ({row['variant']}, {row['seed']}) p_accused != social_audit_report.json")

    txt = md_path.read_text(encoding="utf-8")
    vt_head = {r["variant"]: r for r in var_table}
    v5h = vt_head["v5_full9_cocktail"]
    v3h = vt_head["v3_grudge_falsemem_misforward"]
    v1h = vt_head["v1_anchoring_authority_confirmation"]
    for snippet in (
        f"`{v5h['gemini_mean']:.3f}` raw mean",
        f"`{v5h['v0_control_mean_on_paired']:.3f}` raw mean",
        f"`{100.0 * v5h['ratio_vs_v0_control']:.1f}%`",
        f"`{v5h['paired_delta_vs_v0_raw']:+.3f}`",
        f"`{v3h['gemini_mean']:.3f}` vs `{v3h['v0_control_mean_on_paired']:.3f}`",
        f"`{v1h['gemini_mean']:.3f}` vs `{v1h['v0_control_mean_on_paired']:.3f}`",
    ):
        if snippet not in txt:
            errs.append(f"{rel}: headline prose missing expected value {snippet} from partial_summary.json")
    tables = _parse_md_tables_by_heading(txt)
    if len(tables) < 2:
        errs.append(f"{rel}: expected 2 markdown tables, found {len(tables)}")
        return errs

    _, _, t1_rows = tables[0]
    _, _, t2_rows = tables[1]
    if len(t1_rows) != 7 or len(t2_rows) != 10:
        errs.append(f"{rel}: expected 7 summary rows and 10 seed rows, got {len(t1_rows)} and {len(t2_rows)}")
        return errs

    vt_map = {r["variant"]: r for r in var_table}
    v5_paired = vt_map["v5_full9_cocktail"]
    for r in t1_rows:
        label = r[0]
        n_val = int(r[1])
        if label == "`v0_v14_control` (seeds 30..32)":
            if n_val != 3 or r[2] != "30,31,32":
                errs.append(f"{rel}: v0_v14_control (seeds 30..32) row n/seeds mismatch")
            if abs(float(r[3]) - float(v5_paired["v0_control_mean_on_paired"])) > 0.002:
                errs.append(f"{rel}: v0_v14_control (30..32) raw mean mismatch")
            if abs(float(r[4]) - float(v5_paired["v0_control_luck_adj_mean_on_paired"])) > 0.002:
                errs.append(f"{rel}: v0_v14_control (30..32) luck-adj mean mismatch")
            continue

        m_v = re.match(r"`([a-z0-9_]+)`", label)
        if m_v is None or m_v.group(1) not in vt_map:
            errs.append(f"{rel}: unrecognized Table 1 variant row {label!r}")
            continue
        vref = vt_map[m_v.group(1)]
        if n_val != int(vref["n_valid"]):
            errs.append(f"{rel}: {vref['variant']} n_valid {n_val} != {vref['n_valid']}")
        if n_val == 0:
            if r[2] != "none" or r[3] != "n/a" or r[12] != "0/0":
                errs.append(f"{rel}: {vref['variant']} n=0 row cells malformed")
            continue
        exp_seeds = ",".join(str(s) for s in vref["valid_seeds"])
        if r[2] != exp_seeds:
            errs.append(f"{rel}: {vref['variant']} valid seeds {r[2]!r} != {exp_seeds!r}")
        if abs(float(r[3]) - float(vref["gemini_mean"])) > 0.002:
            errs.append(f"{rel}: {vref['variant']} gemini_mean {r[3]} != {vref['gemini_mean']}")
        if abs(float(r[4]) - float(vref["gemini_luck_adj_mean"])) > 0.002:
            errs.append(f"{rel}: {vref['variant']} gemini_luck_adj_mean {r[4]} != {vref['gemini_luck_adj_mean']}")
        if abs(float(r[5]) - float(vref["solver_mean"])) > 0.002:
            errs.append(f"{rel}: {vref['variant']} solver_mean {r[5]} != {vref['solver_mean']}")
        if abs(float(r[6]) - float(vref["solver_luck_adj_mean"])) > 0.002:
            errs.append(f"{rel}: {vref['variant']} solver_luck_adj_mean {r[6]} != {vref['solver_luck_adj_mean']}")
        if abs(float(r[7]) - float(vref["v0_control_mean_on_paired"])) > 0.002:
            errs.append(f"{rel}: {vref['variant']} v0_control_mean {r[7]} != {vref['v0_control_mean_on_paired']}")
        if abs(float(r[8]) - float(vref["v0_control_luck_adj_mean_on_paired"])) > 0.002:
            errs.append(f"{rel}: {vref['variant']} v0_control_luck_adj {r[8]} != {vref['v0_control_luck_adj_mean_on_paired']}")
        try:
            rat_v0, pct_v0 = _parse_ratio_cell(r[9])
            rat_sr, _ = _parse_ratio_cell(r[10])
            rat_sl, pct_sl = _parse_ratio_cell(r[11])
        except ValueError as exc:
            errs.append(f"{rel}: {vref['variant']} {exc}")
            continue
        if rat_v0 is None or abs(rat_v0 - float(vref["ratio_vs_v0_control"])) > 0.002 or abs(pct_v0 - 100.0 * float(vref["ratio_vs_v0_control"])) > 0.15:
            errs.append(f"{rel}: {vref['variant']} ratio_vs_v0_control mismatch")
        if vref["ratio_vs_solver_raw"] is None:
            if rat_sr is not None:
                errs.append(f"{rel}: {vref['variant']} expected n/a ratio_vs_solver_raw when solver<=0")
        elif rat_sr is None or abs(rat_sr - float(vref["ratio_vs_solver_raw"])) > 0.002:
            errs.append(f"{rel}: {vref['variant']} ratio_vs_solver_raw mismatch")
        if rat_sl is None or abs(rat_sl - float(vref["ratio_vs_solver_luck_adj"])) > 0.002 or abs(pct_sl - 100.0 * float(vref["ratio_vs_solver_luck_adj"])) > 0.15:
            errs.append(f"{rel}: {vref['variant']} ratio_vs_solver_luck_adj mismatch")
        if r[12] != f"{vref['replay_verified_count']}/{n_val}":
            errs.append(f"{rel}: {vref['variant']} replay_verified cell {r[12]!r} mismatch")

    seed_lookup = {(r["variant"], int(r["seed"])): r for r in seed_table}
    for r in t2_rows:
        vname = r[0].strip("`")
        n_v = int(r[1])
        sd = int(r[2])
        sref = seed_lookup.get((vname, sd))
        if sref is None:
            errs.append(f"{rel}: Table 2 row ({vname}, seed={sd}) missing in partial_summary.json")
            continue
        if n_v != int(sref["n_valid"]):
            errs.append(f"{rel}: Table 2 ({vname}, {sd}) n_valid mismatch")
        if abs(float(r[3]) - float(sref["gemini_score"])) > 0.002:
            errs.append(f"{rel}: Table 2 ({vname}, {sd}) gemini_score {r[3]} != {sref['gemini_score']}")
        if abs(float(r[4]) - float(sref["gemini_luck_adj"])) > 0.002:
            errs.append(f"{rel}: Table 2 ({vname}, {sd}) gemini_luck_adj {r[4]} != {sref['gemini_luck_adj']}")
        if int(r[5]) != int(sref["gemini_final_day"]):
            errs.append(f"{rel}: Table 2 ({vname}, {sd}) gemini_day {r[5]} != {sref['gemini_final_day']}")
        if abs(float(r[6]) - float(sref["gemini_p_accused"])) > 0.002:
            errs.append(f"{rel}: Table 2 ({vname}, {sd}) P(acc) {r[6]} != {sref['gemini_p_accused']}")
        if abs(float(r[7]) - float(sref["solver_score"])) > 0.002:
            errs.append(f"{rel}: Table 2 ({vname}, {sd}) solver_score {r[7]} != {sref['solver_score']}")
        if abs(float(r[8]) - float(sref["solver_luck_adj"])) > 0.002:
            errs.append(f"{rel}: Table 2 ({vname}, {sd}) solver_luck_adj {r[8]} != {sref['solver_luck_adj']}")
        if int(r[9]) != int(sref["solver_final_day"]):
            errs.append(f"{rel}: Table 2 ({vname}, {sd}) solver_day {r[9]} != {sref['solver_final_day']}")
        if abs(float(r[10]) - float(sref["v0_control_score"])) > 0.002:
            errs.append(f"{rel}: Table 2 ({vname}, {sd}) v0_control_score {r[10]} != {sref['v0_control_score']}")
        try:
            rv0, _ = _parse_ratio_cell(r[11])
            rsr, _ = _parse_ratio_cell(r[12])
            rsl, _ = _parse_ratio_cell(r[13])
        except ValueError as exc:
            errs.append(f"{rel}: Table 2 ({vname}, {sd}) {exc}")
            continue
        if rv0 is None or abs(rv0 - float(sref["ratio_vs_v0_control"])) > 0.002:
            errs.append(f"{rel}: Table 2 ({vname}, {sd}) ratio_vs_v0_control mismatch")
        if sref["ratio_vs_solver_raw"] is None:
            if rsr is not None:
                errs.append(f"{rel}: Table 2 ({vname}, {sd}) expected n/a ratio_vs_solver_raw")
        elif rsr is None or abs(rsr - float(sref["ratio_vs_solver_raw"])) > 0.002:
            errs.append(f"{rel}: Table 2 ({vname}, {sd}) ratio_vs_solver_raw mismatch")
        if rsl is None or abs(rsl - float(sref["ratio_vs_solver_luck_adj"])) > 0.002:
            errs.append(f"{rel}: Table 2 ({vname}, {sd}) ratio_vs_solver_luck_adj mismatch")
        if r[14] != str(bool(sref["replay_verified"])):
            errs.append(f"{rel}: Table 2 ({vname}, {sd}) replay_verified {r[14]!r} != True")

    return errs


def check_v16_reports_and_ledgers(root: Path) -> CheckResult:
    name = "V1.6 Social Reports & Ledger Parity"
    _, v16_md, _, _ = _discover_azure_targets(root)
    if not v16_md:
        return CheckResult(name, "FAIL", "no docs/reports/v16_*.md files found")

    failures: list[str] = []
    for mp in v16_md:
        failures.extend(_audit_generic_markdown_report(root, mp))
        if mp.name == "v16_social_fairness_audit.md":
            failures.extend(_audit_v16_fairness_pair(root, mp))
        elif mp.name == "v16_social_eval.md":
            failures.extend(_audit_v16_eval_pair(root, mp))

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} V1.6 parity/schema mismatch(es) across {len(v16_md)} report(s)",
            failures,
        )
    return CheckResult(
        name,
        "PASS",
        f"verified {len(v16_md)} v16_*.md report(s) ({', '.join(p.name for p in v16_md)}) "
        "against social_audit_report.json, partial_summary.json, reference_seeds_30_49.json, and checkpoints",
    )


def audit_azure_repo(root: Path = ROOT) -> list[CheckResult]:
    resolved = root.resolve()
    return [
        check_artifact_hygiene(resolved),
        check_mole_json_schemas(resolved),
        check_mole_ledger_and_report_parity(resolved),
        check_v16_reports_and_ledgers(resolved),
    ]


def format_report(results: Sequence[CheckResult], elapsed_s: float) -> str:
    lines: list[str] = []
    counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
        lines.append(f"[{r.status}] {r.name}: {r.summary}")
        for detail in r.details:
            lines.append(f"       - {detail}")
    lines.append(
        f"SUMMARY: {counts['PASS']} PASS, {counts['WARN']} WARN, {counts['FAIL']} FAIL ({elapsed_s:.3f}s)"
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Keyless numerical/ledger parity and hygiene audit for Azure mole_*/v16_* reports and JSONs."
    )
    ap.add_argument("--root", type=Path, default=ROOT, help="Repository root to audit")
    ap.add_argument("--json", action="store_true", help="Emit JSON audit payload")
    args = ap.parse_args(argv)

    t0 = time.perf_counter()
    results = audit_azure_repo(args.root)
    elapsed = time.perf_counter() - t0
    passed = not any(r.status == "FAIL" for r in results)

    if args.json:
        payload = {
            "results": [asdict(r) for r in results],
            "elapsed_s": round(elapsed, 4),
            "passed": passed,
        }
        print(json.dumps(payload, indent=2))
    else:
        print(format_report(results, elapsed))

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
