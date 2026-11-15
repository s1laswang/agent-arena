"""Fast offline single-command verifier for all Canary tiebreak deliverables."""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import inspect
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
    (
        "tiebreak_delayed_leak_noise_audit",
        "scripts/tiebreak_delayed_leak_noise_audit.py",
        "scripts/tiebreak_delayed_leak_noise_audit.py --check",
    ),
    (
        "tiebreak_dagger_mechanism_audit",
        "scripts/tiebreak_dagger_mechanism_audit.py",
        "scripts/tiebreak_dagger_mechanism_audit.py --check",
    ),
    (
        "tiebreak_failure_taxonomy_matrix",
        "scripts/tiebreak_failure_taxonomy_matrix.py",
        "scripts/tiebreak_failure_taxonomy_matrix.py --check",
    ),
)

OPTIONAL_FILENAMES: tuple[str, ...] = (
    "tiebreak_learning_curve.py",
    "build_tiebreak_viewer.py",
    "tiebreak_calibration_stopping_audit.py",
    "tiebreak_multiseed_stability_audit.py",
    "tiebreak_state_externalization_audit.py",
    "run_tiebreak_policy.py",
    "tiebreak_working_memory_audit.py",
    "tiebreak_pareto_efficiency.py",
    "tiebreak_channel_ablation_audit.py",
    "tiebreak_framing_decoy_audit.py",
    "tiebreak_mcp_wire_parity.py",
    "tiebreak_cross_tier_transfer_audit.py",
    "tiebreak_harbor_shell_bridge.py",
    "tiebreak_stopping_counterfactual_audit.py",
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
        found_file: Path | None = None
        for folder in ("scripts", "train"):
            cand = root / folder / fname
            if cand.is_file():
                found_rel = f"{folder}/{fname}"
                found_file = cand
                break
        if found_rel is not None and found_file is not None:
            flag = "--check"
            try:
                src_txt = found_file.read_text(encoding="utf-8")
                if "--check" not in src_txt and "--verify" in src_txt:
                    flag = "--verify"
            except Exception:
                flag = "--check"
            cmd = (
                f"python -m train.{stem} {flag}"
                if found_rel.startswith("train/")
                else f"{found_rel} {flag}"
            )
            discovered.append((stem, found_rel, cmd))
        else:
            absent.append(fname)
    return discovered, absent


def _preload_core_modules(planned_ids: set[str] | None = None) -> None:
    def _want(gid: str) -> bool:
        return planned_ids is None or gid in planned_ids

    if _want("tiebreak_addendum_pack"):
        import scripts.tiebreak_addendum_pack as _tap

        _ = _tap
    if _want("tiebreak_context_confound_audit"):
        import scripts.tiebreak_context_confound_audit as _tcca

        _ = _tcca
    if _want("tiebreak_cross_mole_generalization"):
        import scripts.tiebreak_cross_mole_generalization as _tcmg

        _ = _tcmg
    if _want("tiebreak_dagger_mechanism_audit"):
        import scripts.tiebreak_dagger_mechanism_audit as _tdma

        _ = _tdma
    if _want("tiebreak_delayed_leak_noise_audit"):
        import scripts.tiebreak_delayed_leak_noise_audit as _tdlna

        _ = _tdlna
    if _want("tiebreak_experiment_ledger"):
        import scripts.tiebreak_experiment_ledger as _tel

        _ = _tel
    if _want("tiebreak_failure_taxonomy_matrix"):
        import scripts.tiebreak_failure_taxonomy_matrix as _tftm

        _ = _tftm
    if _want("tiebreak_forensics"):
        import scripts.tiebreak_forensics as _tf

        _ = _tf
    if _want("tiebreak_scaling_calibration"):
        import scripts.tiebreak_scaling_calibration as _tsc

        _ = _tsc
    if _want("tiebreak_verda_multiseed_audit"):
        import scripts.tiebreak_verda_multiseed_audit as _tvma

        _ = _tvma
    if _want("tiebreak_vs_frontier_comparison"):
        import scripts.tiebreak_vs_frontier_comparison as _tvfc

        _ = _tvfc
    if _want("verify_tiebreak_submission"):
        import scripts.verify_tiebreak_submission as _vts

        _ = _vts
    if _want("neural_mlp_tiebreak"):
        import train.neural_mlp_tiebreak as _nmt

        _ = _nmt


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


def _run_delayed_leak_noise_audit(root: Path) -> tuple[bool, str, list[str]]:
    import scripts.tiebreak_delayed_leak_noise_audit as tdlna

    out_json = root / tdlna.DEFAULT_OUT_JSON
    out_md = root / tdlna.DEFAULT_OUT_MD
    verdict = tdlna.verify_audit_artifacts(summary_path=out_json, report_path=out_md, repo_root=root)
    errs = list(verdict.get("errors") or [])
    n_ep = int(verdict.get("episodes_verified", 0))
    return bool(verdict.get("passed")), f"{n_ep} delayed-leak & hard-noise episodes verified", errs


def _run_dagger_mechanism_audit(root: Path) -> tuple[bool, str, list[str]]:
    import scripts.tiebreak_dagger_mechanism_audit as tdma

    out_json = root / tdma.DEFAULT_OUT_JSON
    out_md = root / tdma.DEFAULT_OUT_MD
    errs = tdma.verify_committed_artifacts(out_json, out_md, repo_root=root)
    n_tr = 0
    if out_json.is_file():
        data = json.loads(out_json.read_text(encoding="utf-8"))
        n_tr = int(data.get("train_seeds_unique_count", 0))
    return len(errs) == 0, f"{n_tr} TRAIN episodes, cap=96/256 & stopping contrast verified", errs


def _run_failure_taxonomy_matrix(root: Path) -> tuple[bool, str, list[str]]:
    import scripts.tiebreak_failure_taxonomy_matrix as tftm

    out_json = root / tftm.DEFAULT_OUT_JSON
    out_md = root / tftm.DEFAULT_OUT_MD
    errs = tftm.verify_committed_artifacts(out_json, out_md, repo_root=root)
    n_runs = 0
    n_buckets = 0
    if out_json.is_file():
        data = json.loads(out_json.read_text(encoding="utf-8"))
        ht = data.get("headline_totals") or {}
        n_runs = int(ht.get("historical_open_weight_runs", 0))
        n_buckets = int(ht.get("root_cause_bucket_count", 0))
    return len(errs) == 0, f"{n_runs}/19 runs across {n_buckets} MECE buckets verified", errs


def _invoke_optional_main(main_fn: Any, full_path: Path, argv: list[str]) -> tuple[int, str]:
    sig_params = list(inspect.signature(main_fn).parameters.values())
    takes_argv = any(
        p.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.VAR_POSITIONAL,
        )
        for p in sig_params
    )
    buf_out = io.StringIO()
    buf_err = io.StringIO()
    prev_argv = list(sys.argv)
    try:
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            if takes_argv:
                raw_rc = main_fn(argv)
            else:
                sys.argv = [str(full_path), *argv]
                raw_rc = main_fn()
        rc = 0 if raw_rc in (0, None) else int(raw_rc)
    except SystemExit as exc:
        if exc.code in (0, None):
            rc = 0
        elif isinstance(exc.code, int):
            rc = exc.code
        else:
            rc = 1
    finally:
        sys.argv = prev_argv
    out_txt = (buf_out.getvalue() + "\n" + buf_err.getvalue()).strip()
    return rc, out_txt


def _run_optional_module_gate(root: Path, gate_id: str, rel_path: str) -> tuple[bool, str, list[str]]:
    full_path = root / rel_path
    if not full_path.is_file():
        return False, f"missing optional script {rel_path}", [f"missing {full_path}"]

    src_text = full_path.read_text(encoding="utf-8")
    mod_name = f"_tiebreak_opt_{gate_id}_{abs(hash(str(full_path)))}"
    spec = importlib.util.spec_from_file_location(mod_name, full_path)
    if spec is None or spec.loader is None:
        return False, f"unable to load {rel_path}", [f"spec_from_file_location failed for {full_path}"]

    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    try:
        spec.loader.exec_module(mod)
        if root.resolve() != ROOT.resolve() and isinstance(getattr(mod, "ROOT", None), Path):
            setattr(mod, "ROOT", root.resolve())

        main_fn = getattr(mod, "main", None)
        if callable(main_fn):
            flag_candidates: list[str] = []
            root_args: list[str] = []
            parser_fn = (
                getattr(mod, "build_arg_parser", None)
                or getattr(mod, "build_parser", None)
                or getattr(mod, "_build_parser", None)
            )
            if callable(parser_fn):
                try:
                    opt_map = getattr(parser_fn(), "_option_string_actions", {})
                    if "--check" in opt_map:
                        flag_candidates.append("--check")
                    elif "--verify" in opt_map:
                        flag_candidates.append("--verify")
                    elif "--strict" in opt_map:
                        flag_candidates.append("--strict")
                    if root.resolve() != ROOT.resolve():
                        if "--repo-root" in opt_map:
                            root_args = ["--repo-root", str(root)]
                        elif "--root" in opt_map:
                            root_args = ["--root", str(root)]
                except Exception:
                    flag_candidates = []

            if not flag_candidates:
                if "--check" in src_text:
                    flag_candidates = ["--check", "--verify"]
                elif "--verify" in src_text:
                    flag_candidates = ["--verify", "--check"]
                elif "--strict" in src_text:
                    flag_candidates = ["--strict", "--check"]
                else:
                    flag_candidates = ["--check", "--verify"]
                if root.resolve() != ROOT.resolve() and not root_args:
                    if "--repo-root" in src_text:
                        root_args = ["--repo-root", str(root)]
                    elif "--root" in src_text:
                        root_args = ["--root", str(root)]

            rc = 1
            out_txt = ""
            for idx, flag in enumerate(flag_candidates):
                rc, out_txt = _invoke_optional_main(main_fn, full_path, [flag, *root_args])
                if rc == 0:
                    break
                if idx + 1 < len(flag_candidates) and rc == 2 and "unrecognized arguments" in out_txt:
                    continue
                break

            first_line = out_txt.splitlines()[0].strip() if out_txt else "ok"
            if first_line == "{":
                try:
                    parsed_json = json.loads(out_txt)
                    if isinstance(parsed_json, dict):
                        first_line = json.dumps(parsed_json, separators=(",", ":"))
                except Exception:
                    first_line = "ok"
            if rc == 0:
                return True, f"optional check passed ({first_line[:90]})", []
            err_lines = [ln.strip() for ln in out_txt.splitlines() if ln.strip()] or [f"exited with {rc}"]
            return False, f"optional check exited {rc}", err_lines[:5]

        verify_fn = getattr(mod, "verify_artifacts", None)
        if callable(verify_fn):
            v_params = inspect.signature(verify_fn).parameters
            if root.resolve() != ROOT.resolve() and "root" in v_params:
                res = verify_fn(root=root)
            elif root.resolve() != ROOT.resolve() and "repo_root" in v_params:
                res = verify_fn(repo_root=root)
            else:
                res = verify_fn()
            if isinstance(res, dict):
                ok = bool(res.get("passed", res.get("ok", False)))
                errs = [str(e) for e in (res.get("errors") or [])]
                return ok, "optional verify_artifacts passed" if ok else "optional verify_artifacts failed", errs
            if isinstance(res, list):
                ok = len(res) == 0
                return ok, "optional verify_artifacts passed" if ok else "optional verify_artifacts failed", [str(e) for e in res]

        sub_flag = "--verify" if ("--check" not in src_text and "--verify" in src_text) else "--check"
        proc = subprocess.run(
            [sys.executable, str(full_path), sub_flag],
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
        "tiebreak_delayed_leak_noise_audit": _run_delayed_leak_noise_audit,
        "tiebreak_dagger_mechanism_audit": _run_dagger_mechanism_audit,
        "tiebreak_failure_taxonomy_matrix": _run_failure_taxonomy_matrix,
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


GATE_COST_ESTIMATE_MS: dict[str, int] = {
    "tiebreak_addendum_pack": 900,
    "_vts_rest": 650,
    "_vts_ast_opt": 620,
    "run_tiebreak_policy": 480,
    "tiebreak_cross_mole_generalization": 460,
    "_vts_ast_req": 420,
    "tiebreak_working_memory_audit": 200,
    "tiebreak_channel_ablation_audit": 160,
    "tiebreak_framing_decoy_audit": 160,
    "tiebreak_dagger_mechanism_audit": 130,
    "build_tiebreak_viewer": 120,
    "tiebreak_delayed_leak_noise_audit": 115,
    "tiebreak_experiment_ledger": 110,
    "tiebreak_context_confound_audit": 95,
    "tiebreak_failure_taxonomy_matrix": 45,
    "tiebreak_verda_multiseed_audit": 40,
    "tiebreak_vs_frontier_comparison": 30,
    "tiebreak_forensics": 12,
    "tiebreak_scaling_calibration": 8,
    "neural_mlp_tiebreak": 8,
}

VTS_SPLIT_IDS: frozenset[str] = frozenset({"_vts_ast_req", "_vts_ast_opt", "_vts_rest"})


def _run_vts_part(root: Path, part: str) -> dict[str, Any]:
    import scripts.verify_tiebreak_submission as vts

    t0 = time.perf_counter()
    if part in ("_vts_ast_req", "_vts_ast_opt"):
        errs: list[str] = []
        mods: list[str] = []
        classes: list[str] = []
        target_list = (
            vts.REQUIRED_INFERENCE_MODULES if part == "_vts_ast_req" else vts.OPTIONAL_INFERENCE_MODULES
        )
        req_mode = part == "_vts_ast_req"
        for rel in target_list:
            p = root / rel
            if not p.is_file():
                if req_mode:
                    errs.append(f"missing required inference module: {rel}")
                continue
            mods.append(rel)
            m_errs, m_cls = vts._audit_policy_module_ast(rel, p)
            errs.extend(m_errs)
            classes.extend(m_cls)
        dt_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return {"gate_id": part, "wall_clock_ms": dt_ms, "ast_errors": errs, "ast_mods": mods, "ast_classes": classes}

    items = [
        vts.check_protected_and_frozen_paths(root=root, strict=True).to_dict(),
        vts.check_seed_and_secret_provenance(root=root, strict=True).to_dict(),
        vts.check_claim_number_audit(root=root, strict=True).to_dict(),
        vts.check_hygiene_and_panel_fix_a(root=root, strict=True).to_dict(),
    ]
    dt_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    return {"gate_id": part, "wall_clock_ms": dt_ms, "checks": items}


def _worker_run_batch(batch: tuple[str, bool, list[tuple[str, str, str, bool]]]) -> list[dict[str, Any]]:
    root_str, full, items = batch
    root = Path(root_str)
    results: list[dict[str, Any]] = []
    for gid, rel, cmd, opt in items:
        if gid in VTS_SPLIT_IDS:
            results.append(_run_vts_part(root, gid))
        else:
            results.append(execute_single_gate(root, gid, rel, cmd, optional=opt, full=full).to_dict())
    return results


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
        "13/13",
        "scripts/reproduce_tiebreak_all.py",
        "docs/reports/tiebreak_delayed_leak_noise.md",
        "docs/reports/tiebreak_dagger_mechanism.md",
        "docs/reports/tiebreak_failure_taxonomy.md",
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
        and not multiprocessing.current_process().daemon
        and "fork" in multiprocessing.get_all_start_methods()
    )

    if use_fork:
        _preload_core_modules({gid for gid, _, _, _ in planned if gid != "tiebreak_vs_frontier_comparison"})
        work_units: list[tuple[str, str, str, bool]] = []
        vts_spec: tuple[str, str, str, bool] | None = None
        for it in planned:
            if it[0] == "verify_tiebreak_submission" and (resolved_root / it[1]).is_file():
                vts_spec = it
                work_units.append(("_vts_ast_req", it[1], it[2], it[3]))
                work_units.append(("_vts_ast_opt", it[1], it[2], it[3]))
                work_units.append(("_vts_rest", it[1], it[2], it[3]))
            else:
                work_units.append(it)

        n_bins = min(workers, len(work_units))
        bins: list[list[tuple[str, str, str, bool]]] = [[] for _ in range(n_bins)]
        bin_loads = [0 for _ in range(n_bins)]

        def _est_cost(it: tuple[str, str, str, bool]) -> int:
            if full and it[0] == "tiebreak_vs_frontier_comparison":
                return 2200
            return GATE_COST_ESTIMATE_MS.get(it[0], 90)

        for item in sorted(work_units, key=_est_cost, reverse=True):
            target_idx = min(range(n_bins), key=lambda idx: bin_loads[idx])
            bins[target_idx].append(item)
            bin_loads[target_idx] += _est_cost(item)

        batches = [(str(resolved_root), full, grp) for grp in bins if grp]
        vts_parts: dict[str, dict[str, Any]] = {}
        ctx = multiprocessing.get_context("fork")
        with ProcessPoolExecutor(max_workers=len(batches), mp_context=ctx) as pool:
            for batch_dicts in pool.map(_worker_run_batch, batches):
                for d in batch_dicts:
                    gid_str = str(d["gate_id"])
                    if gid_str in VTS_SPLIT_IDS:
                        vts_parts[gid_str] = d
                    else:
                        outcomes_by_id[gid_str] = GateOutcome(**d)

        if vts_spec is not None:
            import scripts.verify_tiebreak_submission as vts

            req_p = vts_parts.get("_vts_ast_req", {})
            opt_p = vts_parts.get("_vts_ast_opt", {})
            ast_errs = list(req_p.get("ast_errors", [])) + list(opt_p.get("ast_errors", []))
            ast_classes = list(req_p.get("ast_classes", [])) + list(opt_p.get("ast_classes", []))
            if len(ast_classes) < 3:
                ast_errs.append(f"expected >= 3 audited inference policy classes, found {len(ast_classes)}")
            ast_chk = {
                "name": "ast_inference_isolation",
                "passed": len(ast_errs) == 0,
                "errors": ast_errs,
            }
            merged_checks = {
                "ast_inference_isolation": ast_chk,
                **{
                    c["name"]: c
                    for c in vts_parts.get("_vts_rest", {}).get("checks", [])
                },
            }
            ordered_checks = [merged_checks[nm] for nm in vts.CHECK_NAMES if nm in merged_checks]
            vts_wall_ms = round(max((float(p["wall_clock_ms"]) for p in vts_parts.values()), default=0.0), 2)
            vts_errs: list[str] = []
            for chk in ordered_checks:
                if not chk["passed"]:
                    vts_errs.extend(chk.get("errors") or [f"{chk['name']} failed"])
            if vts_wall_ms / 1000.0 > vts.MAX_RUNTIME_SECONDS:
                vts_errs.append(
                    f"verifier runtime {vts_wall_ms / 1000.0:.4f}s exceeded {vts.MAX_RUNTIME_SECONDS:.1f}s offline budget"
                )
            passed_cnt = sum(1 for chk in ordered_checks if chk["passed"])
            vts_ok = passed_cnt == len(vts.CHECK_NAMES) and len(vts_errs) == 0
            outcomes_by_id["verify_tiebreak_submission"] = GateOutcome(
                gate_id="verify_tiebreak_submission",
                command=vts_spec[2],
                optional=vts_spec[3],
                passed=vts_ok,
                wall_clock_ms=vts_wall_ms,
                summary=f"{passed_cnt}/{len(vts.CHECK_NAMES)} strict checks passed",
                errors=vts_errs,
            )
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
