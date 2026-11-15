"""Fast offline single-command verifier for all Canary tiebreak deliverables."""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import multiprocessing
import re
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
SCHEMA_ID = "canary.tiebreak.reproduce_all.v1"

CORE_GATE_SPECS: tuple[tuple[str, str, str], ...] = (
    ("verify_tiebreak_submission", "scripts/verify_tiebreak_submission.py", "scripts/verify_tiebreak_submission.py --strict"),
    ("tiebreak_experiment_ledger", "scripts/tiebreak_experiment_ledger.py", "scripts/tiebreak_experiment_ledger.py --check"),
    ("tiebreak_addendum_pack", "scripts/tiebreak_addendum_pack.py", "scripts/tiebreak_addendum_pack.py --check"),
    ("tiebreak_vs_frontier_comparison", "scripts/tiebreak_vs_frontier_comparison.py", "scripts/tiebreak_vs_frontier_comparison.py --check"),
    ("tiebreak_verda_multiseed_audit", "scripts/tiebreak_verda_multiseed_audit.py", "scripts/tiebreak_verda_multiseed_audit.py --check"),
    ("tiebreak_context_confound_audit", "scripts/tiebreak_context_confound_audit.py", "scripts/tiebreak_context_confound_audit.py --check"),
    ("tiebreak_cross_mole_generalization", "scripts/tiebreak_cross_mole_generalization.py", "scripts/tiebreak_cross_mole_generalization.py --check"),
    (
        "tiebreak_forensics",
        "scripts/tiebreak_forensics.py",
        "scripts/tiebreak_forensics.py --verify-json results/tiebreak/forensics_prior_runs.json --verify-md results/tiebreak/forensics_prior_runs.md",
    ),
    ("tiebreak_scaling_calibration", "scripts/tiebreak_scaling_calibration.py", "scripts/tiebreak_scaling_calibration.py --check"),
    ("neural_mlp_tiebreak", "train/neural_mlp_tiebreak.py", "python -m train.neural_mlp_tiebreak --check"),
)

OPTIONAL_FILENAMES: tuple[str, ...] = (
    "tiebreak_learning_curve.py",
    "build_tiebreak_viewer.py",
)

PREREG_RE = re.compile(r"\bpre[-\s]?regist(?:er(?:ed|ing|s)?|ration)\b", re.IGNORECASE)
NEGATED_PREREG_RE = re.compile(
    r"\b(?:not|never|no|neither|nor|without)\s+(?:a\s+|an\s+)?pre[-\s]?regist(?:er(?:ed|ing|s)?|ration)\b",
    re.IGNORECASE,
)
SEEDS_0_29_RE = re.compile(
    r"(?:\bseeds?\s*`?0\s*(?:\.\.|-|to)\s*29`?|`?0\s*(?:\.\.|-)\s*29`?\s*seeds?|\b0\.\.29\b|\b0-29\b)",
    re.IGNORECASE,
)


@dataclass
class GateOutcome:
    gate_id: str
    command: str
    optional: bool
    passed: bool
    wall_clock_ms: float
    summary: str
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def discover_optional_gates(root: Path = ROOT) -> tuple[list[tuple[str, str, str]], list[str]]:
    discovered: list[tuple[str, str, str]] = []
    absent: list[str] = []
    for fname in OPTIONAL_FILENAMES:
        stem = Path(fname).stem
        found_rel: str | None = None
        for folder in ("scripts", "train"):
            cand = root / folder / fname
            if cand.is_file():
                found_rel = f"{folder}/{fname}"
                break
        if found_rel is not None:
            cmd = (
                f"python -m train.{stem} --check"
                if found_rel.startswith("train/")
                else f"{found_rel} --check"
            )
            discovered.append((stem, found_rel, cmd))
        else:
            absent.append(fname)
    return discovered, absent


def _preload_core_modules() -> None:
    import scripts.tiebreak_addendum_pack as _tap
    import scripts.tiebreak_context_confound_audit as _tcca
    import scripts.tiebreak_cross_mole_generalization as _tcmg
    import scripts.tiebreak_experiment_ledger as _tel
    import scripts.tiebreak_forensics as _tf
    import scripts.tiebreak_scaling_calibration as _tsc
    import scripts.tiebreak_verda_multiseed_audit as _tvma
    import scripts.tiebreak_vs_frontier_comparison as _tvfc
    import scripts.verify_tiebreak_submission as _vts
    import train.neural_mlp_tiebreak as _nmt

    _ = (_tap, _tcca, _tcmg, _tel, _tf, _tsc, _tvma, _tvfc, _vts, _nmt)


def _run_verify_tiebreak_submission(root: Path) -> tuple[bool, str, list[str]]:
    import scripts.verify_tiebreak_submission as vts

    rep = vts.run_all_checks(root=root, strict=True)
    errs: list[str] = []
    for chk in rep["checks"].values():
        if not chk["passed"]:
            errs.extend(chk.get("errors") or [f"{chk['name']} failed"])
    errs.extend(rep.get("global_errors") or [])
    summary = f"{rep['checks_passed']}/{rep['checks_total']} strict checks passed"
    return bool(rep["passed"]), summary, errs


def _run_experiment_ledger(root: Path) -> tuple[bool, str, list[str]]:
    import scripts.tiebreak_experiment_ledger as tel

    out_json = root / "results" / "tiebreak" / "experiment_ledger.json"
    out_md = root / "docs" / "reports" / "tiebreak_small_model.md"
    ledger = tel.build_ledger(repo_root=root)
    md_text = tel.render_markdown_report(ledger)
    errs = tel.check_committed_artifacts(ledger, md_text, out_json, out_md)
    sc = ledger["summary_counts"]
    summary = (
        f"{sc['historical_runs']} historical, {sc['discovered_runs']} discovered, "
        f"{sc['verified_improvements']} verified"
    )
    return len(errs) == 0, summary, errs


def _run_addendum_pack(root: Path) -> tuple[bool, str, list[str]]:
    import scripts.tiebreak_addendum_pack as tap

    out_json = root / "results" / "tiebreak" / "addendum_readiness.json"
    out_md = root / "docs" / "reports" / "tiebreak_panel_e_addendum.md"
    readiness = tap.build_addendum_readiness(repo_root=root)
    md_text = tap.render_addendum_markdown(readiness)
    errs = tap.check_addendum_pack(readiness, md_text, out_json, out_md)
    rs = readiness["readiness_summary"]
    summary = (
        f"track1={rs['track1_passing_count']}/{rs['track1_discovered_count']}, "
        f"track2={rs['track2_passing_count']}/{rs['track2_discovered_count']}"
    )
    return len(errs) == 0, summary, errs


def _run_vs_frontier_comparison(root: Path, full: bool = False) -> tuple[bool, str, list[str]]:
    import scripts.tiebreak_vs_frontier_comparison as tvfc

    out_json = root / "results" / "tiebreak" / "frontier_comparison" / "comparison_summary.json"
    out_md = root / "docs" / "reports" / "tiebreak_vs_frontier.md"
    if not out_json.is_file():
        return False, "missing comparison_summary.json", [f"missing {out_json}"]
    if not out_md.is_file():
        return False, "missing tiebreak_vs_frontier.md", [f"missing {out_md}"]
    payload = (
        tvfc.build_comparison_summary(repo_root=root)
        if full
        else json.loads(out_json.read_text(encoding="utf-8"))
    )
    expected_md = tvfc.render_comparison_markdown(payload)
    errs = tvfc.check_comparison_artifacts(payload, expected_md, out_json, out_md)
    rat = payload.get("replay_audit_totals") or {}
    mode_tag = "live 990-trajectory" if full else "artifact"
    summary = (
        f"{rat.get('fresh_env_step_verified_episodes', 0)} env + "
        f"{rat.get('verda_transcript_belief_replayed_episodes', 0)} belief replays ({mode_tag}) verified"
    )
    return len(errs) == 0, summary, errs


def _run_verda_multiseed_audit(root: Path) -> tuple[bool, str, list[str]]:
    import scripts.tiebreak_verda_multiseed_audit as tvma

    out_json = root / "results" / "tiebreak" / "verda_multiseed" / "multiseed_summary.json"
    out_md = root / "docs" / "reports" / "tiebreak_verda_multiseed.md"
    errs = tvma.verify_committed_artifacts(out_json, out_md, repo_root=root, allow_git=False)
    py_file = root / "scripts" / "tiebreak_verda_multiseed_audit.py"
    if py_file.is_file():
        errs.extend(tvma.check_python_source_hygiene(py_file))
    tot = 0
    if out_json.is_file():
        data = json.loads(out_json.read_text(encoding="utf-8"))
        tot = int((data.get("totals") or {}).get("total_episodes_replayed", 0))
    return len(errs) == 0, f"{tot} episodes and 3 paired comparisons verified", errs


def _run_context_confound_audit(root: Path) -> tuple[bool, str, list[str]]:
    import scripts.tiebreak_context_confound_audit as tcca

    out_json = root / "results" / "tiebreak" / "context_confound" / "audit_summary.json"
    out_md = root / "results" / "tiebreak" / "context_confound" / "report.md"
    errs: list[str] = []
    if not out_json.is_file():
        return False, "missing audit_summary.json", [f"missing {out_json}"]
    if not out_md.is_file():
        return False, "missing context_confound/report.md", [f"missing {out_md}"]
    if (out_json.parent / "summary.json").exists():
        errs.append(f"colliding legacy summary.json present in {out_json.parent}")
    raw_json = out_json.read_text(encoding="utf-8")
    md_text = out_md.read_text(encoding="utf-8")
    payload = json.loads(raw_json)
    if raw_json != json.dumps(payload, indent=2) + "\n":
        errs.append("audit_summary.json formatting differs from canonical serialization")
    errs.extend(tcca.validate_audit_artifacts(payload, md_text=md_text))
    n_ep = int(payload.get("n", 0))
    n_runs = len(payload.get("runs") or {})
    return len(errs) == 0, f"{n_ep} episodes across {n_runs} Verda runs verified", errs


def _run_cross_mole_generalization(root: Path) -> tuple[bool, str, list[str]]:
    import scripts.tiebreak_cross_mole_generalization as tcmg

    out_json = root / "results" / "tiebreak" / "cross_mole_generalization" / "generalization_summary.json"
    out_md = root / "docs" / "reports" / "tiebreak_cross_mole_generalization.md"
    verdict = tcmg.verify_artifacts(summary_path=out_json, report_path=out_md, repo_root=root)
    errs = list(verdict.get("errors") or [])
    n_reg = int(verdict.get("regimes_verified", 0))
    return bool(verdict.get("passed")), f"{n_reg} mole regimes + 4 live spot replays verified", errs


def _run_forensics(root: Path) -> tuple[bool, str, list[str]]:
    import scripts.tiebreak_forensics as tf

    out_json = root / "results" / "tiebreak" / "forensics_prior_runs.json"
    out_md = root / "results" / "tiebreak" / "forensics_prior_runs.md"
    errs = tf.verify_committed_artifacts(out_json, md_path=out_md)
    return len(errs) == 0, "J4/WS4/Verda forensics JSON and Markdown verified", errs


def _run_scaling_calibration(root: Path) -> tuple[bool, str, list[str]]:
    import scripts.tiebreak_scaling_calibration as tsc
    import scripts.verify_tiebreak_submission as vts

    out_json = root / "results" / "tiebreak" / "scaling" / "scaling_summary.json"
    out_md = root / "results" / "tiebreak" / "scaling" / "table.md"
    errs: list[str] = []
    if not out_json.is_file():
        return False, "missing scaling_summary.json", [f"missing {out_json}"]
    if not out_md.is_file():
        return False, "missing scaling/table.md", [f"missing {out_md}"]
    if (out_json.parent / "summary.json").exists():
        errs.append("colliding legacy scaling/summary.json present")

    raw_json = out_json.read_text(encoding="utf-8")
    md_text = out_md.read_text(encoding="utf-8")
    for lbl, txt in (("scaling_summary.json", raw_json), ("scaling/table.md", md_text)):
        if EM_DASH in txt or EN_DASH in txt:
            errs.append(f"{lbl}: contains em or en dash")

    payload = json.loads(raw_json)
    expected_md = tsc.render_markdown_report(payload)
    if md_text != expected_md:
        errs.append("scaling/table.md differs from render_markdown_report(scaling_summary.json)")

    curve = payload.get("scaling_curve") or []
    for row in curve:
        n_ev = int((row.get("metrics") or {}).get("n", -1))
        if int(row.get("replay_verified", -2)) != n_ev:
            errs.append(f"scaling budget {row.get('n_train')}: replay_verified != n ({n_ev})")
    sol = payload.get("solver_reference") or {}
    sol_n = int((sol.get("metrics") or {}).get("n", -1))
    if int(sol.get("replay_verified", -2)) != sol_n:
        errs.append("scaling solver_reference: replay_verified != n")

    vts._audit_scaling_table(out_md, out_json, errs)
    return len(errs) == 0, f"{len(curve)} scaling budgets + calibration taxonomy verified", errs


def _run_neural_mlp_tiebreak(root: Path) -> tuple[bool, str, list[str]]:
    import train.neural_mlp_tiebreak as nmt

    out_json = root / "results" / "tiebreak" / "neural_mlp_dagger" / "mlp_summary.json"
    out_md = root / "docs" / "reports" / "tiebreak_neural_mlp_dagger.md"
    verdict = nmt.verify_artifacts(summary_path=out_json, report_path=out_md)
    errs = list(verdict.get("errors") or [])
    delta = float(verdict.get("paired_mean_delta", 0.0))
    n_val = int(verdict.get("n", 0))
    return bool(verdict.get("passed")), f"n={n_val} paired delta {delta:+.4f} verified", errs


def _run_optional_module_gate(root: Path, gate_id: str, rel_path: str) -> tuple[bool, str, list[str]]:
    full_path = root / rel_path
    if not full_path.is_file():
        return False, f"missing optional script {rel_path}", [f"missing {full_path}"]

    mod_name = f"_tiebreak_opt_{gate_id}_{abs(hash(str(full_path)))}"
    spec = importlib.util.spec_from_file_location(mod_name, full_path)
    if spec is None or spec.loader is None:
        return False, f"unable to load {rel_path}", [f"spec_from_file_location failed for {full_path}"]

    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    try:
        spec.loader.exec_module(mod)
        main_fn = getattr(mod, "main", None)
        if callable(main_fn):
            argv = ["--check"]
            parser_fn = getattr(mod, "build_arg_parser", None)
            if callable(parser_fn):
                try:
                    opt_map = getattr(parser_fn(), "_option_string_actions", {})
                    if "--check" not in opt_map and "--strict" in opt_map:
                        argv = ["--strict"]
                    if root.resolve() != ROOT.resolve():
                        if "--repo-root" in opt_map:
                            argv.extend(["--repo-root", str(root)])
                        elif "--root" in opt_map:
                            argv.extend(["--root", str(root)])
                except Exception:
                    argv = ["--check"]

            buf_out = io.StringIO()
            buf_err = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
                    raw_rc = main_fn(argv)
                rc = 0 if raw_rc in (0, None) else int(raw_rc)
            except SystemExit as exc:
                if exc.code in (0, None):
                    rc = 0
                elif isinstance(exc.code, int):
                    rc = exc.code
                else:
                    rc = 1

            out_txt = (buf_out.getvalue() + "\n" + buf_err.getvalue()).strip()
            first_line = out_txt.splitlines()[0].strip() if out_txt else "ok"
            if rc == 0:
                return True, f"optional check passed ({first_line[:90]})", []
            err_lines = [ln.strip() for ln in out_txt.splitlines() if ln.strip()] or [f"exited with {rc}"]
            return False, f"optional check exited {rc}", err_lines[:5]

        verify_fn = getattr(mod, "verify_artifacts", None)
        if callable(verify_fn):
            res = verify_fn()
            if isinstance(res, dict):
                ok = bool(res.get("passed", res.get("ok", False)))
                errs = [str(e) for e in (res.get("errors") or [])]
                return ok, "optional verify_artifacts passed" if ok else "optional verify_artifacts failed", errs
            if isinstance(res, list):
                ok = len(res) == 0
                return ok, "optional verify_artifacts passed" if ok else "optional verify_artifacts failed", [str(e) for e in res]

        proc = subprocess.run(
            [sys.executable, str(full_path), "--check"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=15,
        )
        combined = (proc.stdout + "\n" + proc.stderr).strip()
        if proc.returncode == 0:
            first_ln = combined.splitlines()[0] if combined else "ok"
            return True, f"optional subprocess passed ({first_ln[:90]})", []
        return False, f"optional subprocess exited {proc.returncode}", [combined[:240] or f"rc={proc.returncode}"]
    finally:
        sys.modules.pop(mod_name, None)


def execute_single_gate(
    root: Path,
    gate_id: str,
    rel_path: str,
    command: str,
    optional: bool = False,
    full: bool = False,
) -> GateOutcome:
    t0 = time.perf_counter()
    script_file = root / rel_path
    if not script_file.is_file():
        dt_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return GateOutcome(
            gate_id=gate_id,
            command=command,
            optional=optional,
            passed=False,
            wall_clock_ms=dt_ms,
            summary=f"missing script {rel_path}",
            errors=[f"missing required gate script: {rel_path}"],
        )

    dispatch = {
        "verify_tiebreak_submission": _run_verify_tiebreak_submission,
        "tiebreak_experiment_ledger": _run_experiment_ledger,
        "tiebreak_addendum_pack": _run_addendum_pack,
        "tiebreak_vs_frontier_comparison": lambda r: _run_vs_frontier_comparison(r, full=full),
        "tiebreak_verda_multiseed_audit": _run_verda_multiseed_audit,
        "tiebreak_context_confound_audit": _run_context_confound_audit,
        "tiebreak_cross_mole_generalization": _run_cross_mole_generalization,
        "tiebreak_forensics": _run_forensics,
        "tiebreak_scaling_calibration": _run_scaling_calibration,
        "neural_mlp_tiebreak": _run_neural_mlp_tiebreak,
    }
    try:
        if optional or gate_id not in dispatch:
            passed, summary, errs = _run_optional_module_gate(root, gate_id, rel_path)
        else:
            passed, summary, errs = dispatch[gate_id](root)
    except Exception as exc:
        passed = False
        summary = f"{type(exc).__name__}: {exc}"
        errs = [summary]

    dt_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    return GateOutcome(
        gate_id=gate_id,
        command=command,
        optional=optional,
        passed=passed,
        wall_clock_ms=dt_ms,
        summary=summary,
        errors=errs,
    )


def _worker_run_batch(batch: tuple[str, bool, list[tuple[str, str, str, bool]]]) -> list[dict[str, Any]]:
    root_str, full, items = batch
    root = Path(root_str)
    return [
        execute_single_gate(root, gid, rel, cmd, optional=opt, full=full).to_dict()
        for gid, rel, cmd, opt in items
    ]


def verify_tiebreak_index(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    idx_path = root / "docs" / "reports" / "TIEBREAK_INDEX.md"
    if not idx_path.is_file():
        return [f"missing {idx_path}"]

    txt = idx_path.read_text(encoding="utf-8")
    if EM_DASH in txt:
        errors.append("TIEBREAK_INDEX.md contains forbidden em dash")
    if EN_DASH in txt:
        errors.append("TIEBREAK_INDEX.md contains forbidden en dash")

    for lineno, raw_line in enumerate(txt.splitlines(), start=1):
        if PREREG_RE.search(raw_line) and SEEDS_0_29_RE.search(raw_line):
            scrubbed = NEGATED_PREREG_RE.sub("", raw_line)
            if PREREG_RE.search(scrubbed):
                errors.append(f"TIEBREAK_INDEX.md line {lineno}: Panel Fix A violation on seeds 0..29")

    if "post-hoc locked" not in txt.lower():
        errors.append("TIEBREAK_INDEX.md missing post-hoc locked DEV_SEEDS 0..29 disclosure")

    required_tokens = (
        "0 / 19",
        "+0.607",
        "+0.614",
        "+0.627",
        "+0.611",
        "100000",
        "200000",
        "800000",
        "800200",
        "scripts/reproduce_tiebreak_all.py",
    )
    for tok in required_tokens:
        if tok not in txt:
            errors.append(f"TIEBREAK_INDEX.md missing required token {tok!r}")

    for m in re.finditer(r"`((?:docs|results|scripts|train)/[A-Za-z0-9_./-]+\.(?:md|json|py))`", txt):
        rel_ref = m.group(1)
        if any(opt_name in rel_ref for opt_name in OPTIONAL_FILENAMES):
            continue
        if not (root / rel_ref).is_file():
            errors.append(f"TIEBREAK_INDEX.md references missing file {rel_ref}")

    return errors


def run_all_gates(
    root: Path = ROOT,
    only_gates: list[str] | None = None,
    allow_partial_root: bool = False,
    workers: int = 3,
    full: bool = False,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    resolved_root = root.resolve()
    only_set = {g.strip() for g in (only_gates or []) if g.strip()}

    opt_specs, opt_absent = discover_optional_gates(resolved_root)

    planned: list[tuple[str, str, str, bool]] = []
    for gid, rel, cmd in CORE_GATE_SPECS:
        if only_set and gid not in only_set:
            continue
        if allow_partial_root and not (resolved_root / rel).is_file():
            continue
        planned.append((gid, rel, cmd, False))

    for gid, rel, cmd in opt_specs:
        if only_set and gid not in only_set:
            continue
        planned.append((gid, rel, cmd, True))

    outcomes_by_id: dict[str, GateOutcome] = {}
    use_fork = (
        workers > 1
        and len(planned) >= 4
        and resolved_root == ROOT.resolve()
        and "fork" in multiprocessing.get_all_start_methods()
    )

    if use_fork:
        _preload_core_modules()
        remaining: list[tuple[str, str, str, bool]] = []
        for item in planned:
            if item[0] == "verify_tiebreak_submission":
                outcomes_by_id[item[0]] = execute_single_gate(
                    resolved_root, item[0], item[1], item[2], optional=item[3], full=full
                )
            else:
                remaining.append(item)

        heavy_a = [it for it in remaining if it[0] == "tiebreak_addendum_pack"]
        heavy_b = [it for it in remaining if it[0] == "tiebreak_cross_mole_generalization"]
        rest = [
            it
            for it in remaining
            if it[0] not in ("tiebreak_addendum_pack", "tiebreak_cross_mole_generalization")
        ]
        batches = [
            (str(resolved_root), full, grp)
            for grp in (heavy_a, heavy_b, rest)
            if grp
        ]
        ctx = multiprocessing.get_context("fork")
        with ProcessPoolExecutor(max_workers=min(workers, len(batches)), mp_context=ctx) as pool:
            for batch_dicts in pool.map(_worker_run_batch, batches):
                for d in batch_dicts:
                    outcomes_by_id[str(d["gate_id"])] = GateOutcome(**d)
    else:
        for gid, rel, cmd, opt in planned:
            outcomes_by_id[gid] = execute_single_gate(
                resolved_root, gid, rel, cmd, optional=opt, full=full
            )

    ordered_outcomes = [outcomes_by_id[gid] for gid, _, _, _ in planned]
    total_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    passed_count = sum(1 for o in ordered_outcomes if o.passed)
    all_passed = (len(ordered_outcomes) > 0 or allow_partial_root) and all(o.passed for o in ordered_outcomes)

    return {
        "schema": SCHEMA_ID,
        "passed": all_passed,
        "check_mode": True,
        "full_mode": bool(full),
        "gates_passed": passed_count,
        "gates_total": len(ordered_outcomes),
        "wall_clock_ms": total_ms,
        "elapsed_seconds": round(total_ms / 1000.0, 4),
        "optional_discovered": [gid for gid, _, _ in opt_specs],
        "optional_absent": opt_absent,
        "gates": [o.to_dict() for o in ordered_outcomes],
    }


def format_human_report(report: dict[str, Any]) -> str:
    verdict = "PASS" if report["passed"] else "FAIL"
    lines = [
        f"TIEBREAK UNIFIED REPRO VERIFIER: {verdict} "
        f"({report['gates_passed']}/{report['gates_total']} gates in {report['wall_clock_ms']:.1f} ms)"
    ]
    for gate in report["gates"]:
        tag = "PASS" if gate["passed"] else "FAIL"
        opt_suffix = " [optional]" if gate.get("optional") else ""
        lines.append(
            f"  [{tag}] {gate['command']}{opt_suffix} ({gate['wall_clock_ms']:.1f} ms) - {gate['summary']}"
        )
        for err in gate.get("errors") or []:
            lines.append(f"         ERROR: {err}")
    return "\n".join(lines)


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Fast offline single-command verifier executing all Canary tiebreak gates."
    )
    ap.add_argument("--check", action="store_true", default=True, help="Run fast offline verification gates (default).")
    ap.add_argument("--full", action="store_true", help="Include 990-trajectory live frontier vs tiebreak replay.")
    ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON verdict.")
    ap.add_argument("--root", type=Path, default=ROOT, help="Repository root directory.")
    ap.add_argument("--only", action="append", default=[], help="Run only selected gate_id value(s).")
    ap.add_argument("--allow-partial-root", action="store_true", help="Skip absent core scripts under custom root.")
    ap.add_argument("--workers", type=int, default=3, help="Max worker processes for parallel gate batches.")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    report = run_all_gates(
        root=args.root,
        only_gates=list(args.only),
        allow_partial_root=bool(args.allow_partial_root),
        workers=int(args.workers),
        full=bool(args.full),
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_human_report(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
