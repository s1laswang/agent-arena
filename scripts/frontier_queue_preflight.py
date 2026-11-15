from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary import rules
from canary.agents.frontier import common, opencode_run
from scripts.verify_replay import replay_episode

VENV_PYTHON = "/tmp/fleet-silas/shared/agent-arena-venv/bin/python"
MOMIN_PATH_PREFIX = "PATH=/home/silas/momin/bin:$PATH"
RUNNER_MODULE = "canary.agents.frontier.opencode_run"
DEFAULT_TIMEOUT_S = 3600
DEFAULT_JOBS = 1
MAX_WORKERS_PER_WAVE = 3

EXPECTED_PERMISSION = {"*": "deny", "canary_*": "allow"}
EXPECTED_CARBON_HARD_LANDED = [30, 34, 42, 45, 57]
EXPECTED_CARBON_HARD_MISSING = [
    31, 32, 33, 35, 36, 37, 38, 39, 40, 41,
    43, 44, 46, 47, 48, 49, 50, 51, 52, 53,
    54, 55, 56, 58, 59,
]
EXPECTED_FLASH_MEDIUM_LANDED = list(range(30))
EXPECTED_FLASH_MEDIUM_MISSING: list[int] = []
EXPECTED_FLASH_HARD_LANDED: list[int] = []
EXPECTED_FLASH_HARD_MISSING = list(range(30, 60))

TARGET_COHORTS: tuple[dict[str, Any], ...] = (
    {
        "cohort_id": "opencode-gemini-4-carbon-hard-30-59",
        "agent_dir": "opencode-gemini-4-carbon",
        "agent": "opencode:google/gemini-4-carbon",
        "model": "google/gemini-4-carbon",
        "tier": "hard",
        "seed_start": 30,
        "seed_end": 59,
        "baseline_landed_seeds": EXPECTED_CARBON_HARD_LANDED,
        "priority": 1,
    },
    {
        "cohort_id": "opencode-gemini-3.5-flash-medium-0-29",
        "agent_dir": "opencode-gemini-3.5-flash",
        "agent": "opencode:google/gemini-3.5-flash",
        "model": "google/gemini-3.5-flash",
        "tier": "medium",
        "seed_start": 0,
        "seed_end": 29,
        "baseline_landed_seeds": EXPECTED_FLASH_MEDIUM_LANDED,
        "priority": 2,
    },
    {
        "cohort_id": "opencode-gemini-3.5-flash-hard-30-59",
        "agent_dir": "opencode-gemini-3.5-flash",
        "agent": "opencode:google/gemini-3.5-flash",
        "model": "google/gemini-3.5-flash",
        "tier": "hard",
        "seed_start": 30,
        "seed_end": 59,
        "baseline_landed_seeds": EXPECTED_FLASH_HARD_LANDED,
        "priority": 3,
    },
)

STRIPPED_ENV_VARS: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "PYTHONPATH",
    "VIRTUAL_ENV",
    "OLDPWD",
    "CANARY_LEDGER_TOKEN",
    "CANARY_ADMIN_TOKEN",
    "CANARY_WORLD_SECRET",
    "CANARY_TOKEN",
    "OPENCODE_CONFIG",
)


def split_transcript(text: str) -> tuple[str, str]:
    marker_out = "\n--- stdout\n"
    marker_err = "\n--- stderr\n"
    if marker_out not in text:
        return text, ""
    _, _, after_out = text.partition(marker_out)
    if marker_err in after_out:
        stdout, _, stderr = after_out.rpartition(marker_err)
        return stdout, stderr
    if after_out.endswith("\n--- stderr"):
        return after_out[: -len("\n--- stderr")], ""
    return after_out, ""


def _with_dev_seeds_allowed():
    prev = os.environ.get("CANARY_ALLOW_DEV")
    os.environ["CANARY_ALLOW_DEV"] = "1"
    return prev


def _restore_dev_seeds(prev: str | None) -> None:
    if prev is None:
        os.environ.pop("CANARY_ALLOW_DEV", None)
    else:
        os.environ["CANARY_ALLOW_DEV"] = prev


def verify_episode_replay(ep: dict[str, Any]) -> bool:
    prev = _with_dev_seeds_allowed()
    try:
        r = replay_episode(ep)
    finally:
        _restore_dev_seeds(prev)
    return (
        abs(float(r["score"]) - float(ep["score"])) < 1e-9
        and r["accused"] == ep.get("accused")
        and bool(r["correct"]) == bool(ep.get("correct"))
        and int(r["final_day"]) == int(ep.get("final_day") or 0)
    )


def build_runner_command(agent_dir: str, model: str, tier: str, seed: int) -> tuple[str, str, str]:
    out_rel = f"results/frontier_replication/v1.4/{agent_dir}/{tier}-s{seed}"
    cmd = (
        f"{MOMIN_PATH_PREFIX} PYTHONPATH=. {VENV_PYTHON} -m {RUNNER_MODULE} "
        f"--model {model} --tier {tier} --seeds {seed} "
        f"--timeout {DEFAULT_TIMEOUT_S} --jobs {DEFAULT_JOBS} --out {out_rel}"
    )
    verify_cmd = f"PYTHONPATH=. {VENV_PYTHON} scripts/verify_replay.py {out_rel}"
    return out_rel, cmd, verify_cmd


def scan_replication_tree(
    root: Path,
    cohorts: tuple[dict[str, Any], ...] = TARGET_COHORTS,
    enforce_expected_baseline: bool = True,
) -> dict[str, Any]:
    rep_root = root / "results" / "frontier_replication" / "v1.4"
    errors: list[str] = []
    if not rep_root.is_dir():
        return {
            "replication_root": "results/frontier_replication/v1.4",
            "total_episodes": 0,
            "replay_verified_episodes": 0,
            "cohorts": [],
            "errors": [f"missing replication directory: {rep_root}"],
        }

    ep_files = sorted(rep_root.rglob("episodes.jsonl"))
    total_valid = 0
    total_replay_ok = 0
    by_agent_tier: dict[tuple[str, str], dict[int, dict[str, Any]]] = {}
    invalid_by_agent_tier: dict[tuple[str, str], list[int]] = {}

    for ep_file in ep_files:
        rel_file = ep_file.relative_to(root).as_posix()
        for line_no, raw_line in enumerate(ep_file.read_text(encoding="utf-8").splitlines(), start=1):
            if not raw_line.strip():
                continue
            ep = json.loads(raw_line)
            agent = str(ep.get("agent", ""))
            tier = str(ep.get("tier", ""))
            seed = int(ep["seed"])
            if (ep.get("meta") or {}).get("valid") is False:
                invalid_by_agent_tier.setdefault((agent, tier), []).append(seed)
                continue
            total_valid += 1
            if not verify_episode_replay(ep):
                errors.append(f"replay mismatch in {rel_file}:{line_no} ({agent} {tier} seed={seed})")
                continue
            total_replay_ok += 1
            bucket = by_agent_tier.setdefault((agent, tier), {})
            if seed in bucket:
                errors.append(
                    f"duplicate replay-verified seed {seed} for {agent} {tier}: "
                    f"{bucket[seed]['episode_file']} and {rel_file}"
                )
                continue
            tr_path = ep_file.parent / "transcripts" / f"{seed}.txt"
            bucket[seed] = {
                "episode": ep,
                "episode_file": rel_file,
                "transcript_file": tr_path.relative_to(root).as_posix() if tr_path.is_file() else None,
            }

    cohort_rows: list[dict[str, Any]] = []
    for spec in cohorts:
        key = (spec["agent"], spec["tier"])
        target_seeds = list(range(int(spec["seed_start"]), int(spec["seed_end"]) + 1))
        landed_map = by_agent_tier.get(key, {})
        landed_seeds = sorted(s for s in target_seeds if s in landed_map)
        missing_seeds = sorted(s for s in target_seeds if s not in landed_map)
        invalid_seeds = sorted(
            s for s in invalid_by_agent_tier.get(key, []) if spec["seed_start"] <= s <= spec["seed_end"]
        )
        baseline = list(spec.get("baseline_landed_seeds") or [])
        baseline_ok = set(baseline).issubset(set(landed_seeds))
        if enforce_expected_baseline and not baseline_ok:
            missing_base = sorted(set(baseline) - set(landed_seeds))
            errors.append(
                f"cohort {spec['cohort_id']} missing expected landed seeds: {missing_base}"
            )
        for s in landed_seeds:
            if landed_map[s]["transcript_file"] is None:
                errors.append(
                    f"cohort {spec['cohort_id']} seed {s} missing transcript file next to {landed_map[s]['episode_file']}"
                )
        cohort_rows.append(
            {
                "cohort_id": spec["cohort_id"],
                "priority": spec["priority"],
                "agent_dir": spec["agent_dir"],
                "agent": spec["agent"],
                "model": spec["model"],
                "tier": spec["tier"],
                "seed_range": [spec["seed_start"], spec["seed_end"]],
                "target_count": len(target_seeds),
                "landed_count": len(landed_seeds),
                "missing_count": len(missing_seeds),
                "landed_seeds": landed_seeds,
                "missing_seeds": missing_seeds,
                "invalid_seeds": invalid_seeds,
                "baseline_landed_verified": baseline_ok,
            }
        )

    return {
        "replication_root": "results/frontier_replication/v1.4",
        "total_episodes": total_valid,
        "replay_verified_episodes": total_replay_ok,
        "cohorts": cohort_rows,
        "records_by_agent_tier": by_agent_tier,
        "errors": errors,
    }


def partition_into_waves(
    cohort_rows: list[dict[str, Any]],
    max_workers_per_wave: int = MAX_WORKERS_PER_WAVE,
) -> list[dict[str, Any]]:
    if max_workers_per_wave < 1 or max_workers_per_wave > MAX_WORKERS_PER_WAVE:
        raise ValueError(f"max_workers_per_wave must be in 1..{MAX_WORKERS_PER_WAVE}")
    waves: list[dict[str, Any]] = []
    ordered = sorted(cohort_rows, key=lambda c: int(c["priority"]))
    wave_id = 0
    for cohort in ordered:
        missing = list(cohort["missing_seeds"])
        cohort_wave = 0
        for idx in range(0, len(missing), max_workers_per_wave):
            batch = missing[idx : idx + max_workers_per_wave]
            wave_id += 1
            cohort_wave += 1
            jobs_list: list[dict[str, Any]] = []
            for slot, seed in enumerate(batch, start=1):
                out_rel, cmd, verify_cmd = build_runner_command(
                    cohort["agent_dir"],
                    cohort["model"],
                    cohort["tier"],
                    seed,
                )
                jobs_list.append(
                    {
                        "worker_slot": slot,
                        "cohort_id": cohort["cohort_id"],
                        "model": cohort["model"],
                        "tier": cohort["tier"],
                        "seed": seed,
                        "seeds": [seed],
                        "timeout_s": DEFAULT_TIMEOUT_S,
                        "jobs": DEFAULT_JOBS,
                        "out_dir": out_rel,
                        "command": cmd,
                        "verify_command": verify_cmd,
                    }
                )
            waves.append(
                {
                    "wave_id": wave_id,
                    "cohort_id": cohort["cohort_id"],
                    "cohort_wave": cohort_wave,
                    "model": cohort["model"],
                    "tier": cohort["tier"],
                    "worker_count": len(jobs_list),
                    "ram_safe": len(jobs_list) <= MAX_WORKERS_PER_WAVE,
                    "seeds": batch,
                    "jobs": jobs_list,
                }
            )
    return waves


def validate_wave_commands(waves: list[dict[str, Any]]) -> dict[str, Any]:
    parser = common.base_args("OpenCode frontier runner", opencode_run.DEFAULT_MODEL)
    errors: list[str] = []
    checked = 0
    for wave in waves:
        if wave["worker_count"] > MAX_WORKERS_PER_WAVE or wave["worker_count"] != len(wave["jobs"]):
            errors.append(f"wave {wave['wave_id']} violates <=3 worker constraint: {wave['worker_count']}")
        for job in wave["jobs"]:
            checked += 1
            cmd = job["command"]
            if not cmd.startswith(f"{MOMIN_PATH_PREFIX} "):
                errors.append(f"wave {wave['wave_id']} seed {job['seed']} missing {MOMIN_PATH_PREFIX}")
            tokens = shlex.split(cmd)
            try:
                mod_idx = tokens.index(RUNNER_MODULE)
            except ValueError:
                errors.append(f"wave {wave['wave_id']} seed {job['seed']} missing {RUNNER_MODULE}")
                continue
            if mod_idx < 1 or tokens[mod_idx - 1] != "-m":
                errors.append(f"wave {wave['wave_id']} seed {job['seed']} missing -m before {RUNNER_MODULE}")
                continue
            cli_argv = tokens[mod_idx + 1 :]
            try:
                parsed, unknown = parser.parse_known_args(cli_argv)
            except SystemExit as exc:
                errors.append(f"wave {wave['wave_id']} seed {job['seed']} failed arg parse: {exc}")
                continue
            if unknown:
                errors.append(f"wave {wave['wave_id']} seed {job['seed']} has invalid flags: {unknown}")
                continue
            norm_model = opencode_run.normalize_model(parsed.model)
            spec = common.spec_from(parsed, f"opencode:{norm_model}")
            if parsed.timeout != DEFAULT_TIMEOUT_S:
                errors.append(f"wave {wave['wave_id']} seed {job['seed']} timeout={parsed.timeout} != {DEFAULT_TIMEOUT_S}")
            if parsed.jobs != DEFAULT_JOBS:
                errors.append(f"wave {wave['wave_id']} seed {job['seed']} jobs={parsed.jobs} != {DEFAULT_JOBS}")
            if parsed.tier not in rules.TIERS:
                errors.append(f"wave {wave['wave_id']} seed {job['seed']} unknown tier={parsed.tier}")
            if spec.seeds != [job["seed"]]:
                errors.append(f"wave {wave['wave_id']} seed {job['seed']} parsed seeds={spec.seeds}")
            if parsed.out != job["out_dir"]:
                errors.append(f"wave {wave['wave_id']} seed {job['seed']} parsed out={parsed.out}")
            if parsed.smoke or parsed.hint is not None or parsed.dry_run:
                errors.append(f"wave {wave['wave_id']} seed {job['seed']} unexpected optional flag enabled")
    return {
        "passed": not errors,
        "commands_validated": checked,
        "max_workers_per_wave": MAX_WORKERS_PER_WAVE,
        "timeout_s": DEFAULT_TIMEOUT_S,
        "jobs_per_worker": DEFAULT_JOBS,
        "errors": errors,
    }


def check_tiers_gate() -> dict[str, Any]:
    errors: list[str] = []
    if rules.TIERS_VERSION != "v1.4":
        errors.append(f"expected TIERS_VERSION == 'v1.4', got {rules.TIERS_VERSION!r}")
    if set(rules.TIERS.keys()) != {"easy", "medium", "hard"}:
        errors.append(f"unexpected active tiers: {sorted(rules.TIERS.keys())}")
    return {
        "passed": not errors,
        "tiers_version": rules.TIERS_VERSION,
        "active_tiers": sorted(rules.TIERS.keys()),
        "errors": errors,
    }


def check_opencode_config_isolation() -> dict[str, Any]:
    errors: list[str] = []
    if opencode_run.PERMISSION != EXPECTED_PERMISSION:
        errors.append(f"PERMISSION mismatch: {opencode_run.PERMISSION!r}")
    test_url = "http://127.0.0.1:43210/mcp"
    cfg = opencode_run.opencode_config(test_url)
    if cfg.get("permission") != EXPECTED_PERMISSION:
        errors.append(f"opencode_config permission mismatch: {cfg.get('permission')!r}")
    cfg["permission"]["*"] = "allow"
    if opencode_run.PERMISSION != EXPECTED_PERMISSION:
        errors.append("opencode_config aliased module PERMISSION dict")
    if cfg.get("autoupdate") is not False:
        errors.append(f"expected autoupdate=False, got {cfg.get('autoupdate')!r}")
    if cfg.get("share") != "disabled":
        errors.append(f"expected share='disabled', got {cfg.get('share')!r}")
    servers = cfg.get("mcp", {}).get("servers", cfg.get("mcp", {}))
    canary_srv = servers.get("canary", {})
    if canary_srv.get("url") != test_url or canary_srv.get("enabled") is not True:
        errors.append(f"unexpected mcp canary config: {canary_srv!r}")
    carbon_settings = opencode_run.opencode_google_settings("google/gemini-4-carbon")
    flash_settings = opencode_run.opencode_google_settings("google/gemini-3.5-flash")
    if "gemini-4-carbon: medium" not in carbon_settings.get("thinking", ""):
        errors.append(f"unexpected carbon thinking settings: {carbon_settings!r}")
    if "thinkingLevel=high" not in flash_settings.get("thinking", ""):
        errors.append(f"unexpected flash thinking settings: {flash_settings!r}")
    return {
        "passed": not errors,
        "permission": dict(EXPECTED_PERMISSION),
        "autoupdate": False,
        "share": "disabled",
        "errors": errors,
    }


def check_child_env_stripping() -> dict[str, Any]:
    errors: list[str] = []
    saved = dict(os.environ)
    wd: Path | None = None
    cleanup_paths: list[Path] = []
    cleanup_other: list[Path] = []
    try:
        synthetic_values: dict[str, str] = {}
        for idx, key in enumerate(STRIPPED_ENV_VARS):
            val = f"synthetic-preflight-secret-{idx}-{key.lower()}"
            synthetic_values[key] = val
            os.environ[key] = val
        env = common.child_env()
        leaked_keys = sorted(k for k in STRIPPED_ENV_VARS if k in env)
        if leaked_keys:
            errors.append(f"child_env leaked stripped keys: {leaked_keys}")
        leaked_vals = sorted(
            k for k, v in synthetic_values.items() if any(v == str(ev_val) for ev_val in env.values())
        )
        if leaked_vals:
            errors.append(f"child_env leaked synthetic values for: {leaked_vals}")
        if env.get("PWD") != "":
            errors.append(f"expected child_env PWD=='', got {env.get('PWD')!r}")

        wd = common.make_clean_workdir()
        extra_env, cleanup_paths = opencode_run.child_env_extra("google/gemini-4-carbon")(wd)
        if extra_env.get("GOOGLE_GENERATIVE_AI_API_KEY") != synthetic_values["GEMINI_API_KEY"]:
            errors.append("child_env_extra failed to map GEMINI_API_KEY to GOOGLE_GENERATIVE_AI_API_KEY")
        if "GEMINI_API_KEY" in extra_env:
            errors.append("child_env_extra exposed raw GEMINI_API_KEY")
        for flag_key in ("OPENCODE_DISABLE_CLAUDE_CODE", "OPENCODE_DISABLE_AUTOUPDATE", "OPENCODE_DISABLE_SHARE"):
            if extra_env.get(flag_key) != "1":
                errors.append(f"expected {flag_key}=='1', got {extra_env.get(flag_key)!r}")
        oc_home = Path(extra_env["XDG_DATA_HOME"]).resolve().parent
        if common.REPO_ROOT.resolve() in oc_home.parents or oc_home == common.REPO_ROOT.resolve():
            errors.append("opencode per-episode XDG home is inside REPO_ROOT")
        if wd.resolve() in oc_home.parents or oc_home == wd.resolve():
            errors.append("opencode per-episode XDG home is inside agent workdir")

        extra_other, cleanup_other = opencode_run.child_env_extra("openai/unused-model")(wd)
        if "GOOGLE_GENERATIVE_AI_API_KEY" in extra_other:
            errors.append("non-google model unexpectedly received GOOGLE_GENERATIVE_AI_API_KEY")
    finally:
        os.environ.clear()
        os.environ.update(saved)
        if wd is not None:
            shutil.rmtree(wd, ignore_errors=True)
        for p in cleanup_paths + cleanup_other:
            shutil.rmtree(p, ignore_errors=True)

    return {
        "passed": not errors,
        "stripped_vars_verified": list(STRIPPED_ENV_VARS),
        "isolated_xdg_home_verified": True,
        "errors": errors,
    }


def check_workdir_isolation(root: Path) -> dict[str, Any]:
    errors: list[str] = []
    wd = common.make_clean_workdir()
    bad_wd = common.make_clean_workdir()
    try:
        repo_resolved = common.REPO_ROOT.resolve()
        root_resolved = root.resolve()
        wd_resolved = wd.resolve()
        if repo_resolved in wd_resolved.parents or wd_resolved == repo_resolved:
            errors.append(f"workdir {wd_resolved} is inside REPO_ROOT {repo_resolved}")
        if root_resolved in wd_resolved.parents or wd_resolved == root_resolved:
            errors.append(f"workdir {wd_resolved} is inside target root {root_resolved}")
        if list(wd.iterdir()):
            errors.append("fresh make_clean_workdir was not empty")
        cmd = opencode_run.build_cmd(wd, "PROMPT", "gemini-4-carbon", "http://127.0.0.1:18765/mcp")
        expected_cmd = ["opencode", "run", "--model", "google/gemini-4-carbon", "--format", "json", "--dir", str(wd), "PROMPT"]
        if cmd != expected_cmd:
            errors.append(f"unexpected build_cmd output: {cmd!r}")
        common.assert_clean(wd, opencode_run.FILES)

        (bad_wd / "opencode.json").write_text("{}", encoding="utf-8")
        (bad_wd / "leak.py").write_text("x = 1\n", encoding="utf-8")
        caught = False
        try:
            common.assert_clean(bad_wd, opencode_run.FILES)
        except AssertionError:
            caught = True
        if not caught:
            errors.append("assert_clean failed to reject unexpected .py file in workdir")
    finally:
        shutil.rmtree(wd, ignore_errors=True)
        shutil.rmtree(bad_wd, ignore_errors=True)

    if wd.exists() or bad_wd.exists():
        errors.append("temporary workdir cleanup failed")
    return {
        "passed": not errors,
        "outside_repo_root": True,
        "allowed_files": sorted(opencode_run.FILES),
        "cleaned_up": True,
        "errors": errors,
    }


def check_transcript_redaction_and_infra(
    root: Path,
    records_by_agent_tier: dict[tuple[str, str], dict[int, dict[str, Any]]],
    enforce_expected_baseline: bool = True,
) -> dict[str, Any]:
    errors: list[str] = []
    long_sig = "T" * 240
    short_sig = "s" * 24
    synthetic_line = json.dumps(
        {
            "type": "tool_use",
            "part": {
                "type": "tool",
                "tool": "canary_status",
                "state": {"status": "completed", "input": {}, "output": '{"ok": true}'},
                "metadata": {
                    "google": {"thoughtSignature": long_sig},
                    "short": {"thoughtSignature": short_sig},
                },
            },
        }
    )
    compacted = common.compact_transcript(synthetic_line)
    if long_sig in compacted or '"thoughtSignature":"<240 chars>"' not in compacted:
        errors.append("compact_transcript failed to redact 240-char thoughtSignature blob")
    if short_sig not in compacted:
        errors.append("compact_transcript unexpectedly altered short <64-char thoughtSignature")

    empty_stop = "\n".join(
        [
            json.dumps({"type": "step_start", "part": {"type": "step-start"}}),
            json.dumps({"type": "step_finish", "part": {"type": "step-finish", "reason": "stop", "tokens": {}}}),
        ]
    )
    normal_stop = "\n".join(
        [
            json.dumps({"type": "step_start", "part": {"type": "step-start"}}),
            json.dumps({"type": "text", "part": {"type": "text", "text": "Accused e05."}}),
            json.dumps({"type": "step_finish", "part": {"type": "step-finish", "reason": "stop", "tokens": {}}}),
        ]
    )
    tool_env_noise = "\n".join(
        [
            json.dumps({"type": "step_start", "part": {"type": "step-start"}}),
            json.dumps(
                {
                    "type": "tool_use",
                    "part": {
                        "type": "tool",
                        "tool": "canary_read_message",
                        "state": {
                            "status": "completed",
                            "input": {"id": "m1-0"},
                            "output": "UNAVAILABLE RESOURCE_EXHAUSTED database is locked usage limit has been reached",
                        },
                    },
                }
            ),
            json.dumps({"type": "step_finish", "part": {"type": "step-finish", "reason": "tool-calls", "tokens": {}}}),
        ]
    )
    quota_err = json.dumps({"type": "error", "error": {"data": {"message": "usage limit has been reached"}}})
    rate_err = json.dumps({"type": "error", "error": {"data": {"message": "RESOURCE_EXHAUSTED"}}})
    unavail_err = json.dumps({"type": "error", "error": {"data": {"message": "The model is overloaded"}}})
    generic_err = json.dumps({"type": "error", "error": {"name": "SyntheticError"}})

    if not common.empty_final_response(empty_stop):
        errors.append("empty_final_response missed synthetic empty stop turn")
    if common.classify_infra(empty_stop, "") != "empty_model_response":
        errors.append("classify_infra missed empty_model_response")
    if common.empty_final_response(normal_stop) or common.classify_infra(normal_stop, "") is not None:
        errors.append("normal stop turn misclassified as infra/empty")
    if common.classify_infra(tool_env_noise, "") is not None:
        errors.append("tool output text misclassified as infra error")
    if common.classify_infra(quota_err, "") != "provider_quota":
        errors.append("classify_infra missed provider_quota")
    if common.classify_infra(rate_err, "") != "provider_rate_limit":
        errors.append("classify_infra missed provider_rate_limit")
    if common.classify_infra(unavail_err, "") != "provider_unavailable":
        errors.append("classify_infra missed provider_unavailable")
    if common.classify_infra("", "Error: database is locked") != "opencode_db_locked":
        errors.append("classify_infra missed opencode_db_locked")
    if common.classify_infra(generic_err, "") != "cli_error_event":
        errors.append("classify_infra missed cli_error_event")

    unredacted_rx = re.compile(r'"thoughtSignature":\s?"[^"<]{64,}"')
    real_transcripts_checked = 0
    carbon_step_counts: dict[str, int] = {}

    carbon_records = records_by_agent_tier.get(("opencode:google/gemini-4-carbon", "hard"), {})
    if enforce_expected_baseline:
        for req_seed in EXPECTED_CARBON_HARD_LANDED:
            if req_seed not in carbon_records:
                errors.append(f"missing verified carbon hard replication record for seed {req_seed}")

    for (agent, tier), seed_map in sorted(records_by_agent_tier.items()):
        if not agent.startswith("opencode:"):
            continue
        for seed, rec in sorted(seed_map.items()):
            tr_rel = rec["transcript_file"]
            if not tr_rel:
                continue
            real_transcripts_checked += 1
            raw_txt = (root / tr_rel).read_text(encoding="utf-8")
            if unredacted_rx.search(raw_txt):
                errors.append(f"unredacted thoughtSignature in {tr_rel}")
            stdout, stderr = split_transcript(raw_txt)
            if common.empty_final_response(stdout):
                errors.append(f"verified transcript {tr_rel} flagged empty_final_response")
            infra_tag = common.classify_infra(stdout, stderr)
            if infra_tag is not None:
                errors.append(f"verified transcript {tr_rel} flagged infra={infra_tag}")
            rebuilt = common.steps_from_events(stdout)
            recorded_steps = rec["episode"].get("steps") or []
            if len(rebuilt) != len(recorded_steps):
                errors.append(
                    f"steps_from_events count mismatch on {tr_rel}: "
                    f"rebuilt={len(rebuilt)} != recorded={len(recorded_steps)}"
                )
            elif [s.tool for s in rebuilt] != [s["tool"] for s in recorded_steps]:
                errors.append(f"steps_from_events tool sequence mismatch on {tr_rel}")
            elif [s.day for s in rebuilt] != [s["day"] for s in recorded_steps]:
                errors.append(f"steps_from_events day sequence mismatch on {tr_rel}")
            elif [s.args for s in rebuilt] != [s["args"] for s in recorded_steps]:
                errors.append(f"steps_from_events args mismatch on {tr_rel}")

            if agent == "opencode:google/gemini-4-carbon" and tier == "hard" and 30 <= seed <= 59:
                carbon_step_counts[str(seed)] = len(rebuilt)

    return {
        "passed": not errors,
        "synthetic_cases_verified": 9,
        "real_transcripts_checked": real_transcripts_checked,
        "carbon_hard_step_counts": carbon_step_counts,
        "errors": errors,
    }


def build_manifest(
    root: Path = ROOT,
    max_workers_per_wave: int = MAX_WORKERS_PER_WAVE,
    enforce_expected_baseline: bool = True,
) -> dict[str, Any]:
    scan = scan_replication_tree(root, TARGET_COHORTS, enforce_expected_baseline=enforce_expected_baseline)
    waves = partition_into_waves(scan["cohorts"], max_workers_per_wave=max_workers_per_wave)

    tiers_check = check_tiers_gate()
    config_check = check_opencode_config_isolation()
    env_check = check_child_env_stripping()
    workdir_check = check_workdir_isolation(root)
    transcript_check = check_transcript_redaction_and_infra(
        root,
        scan.get("records_by_agent_tier", {}),
        enforce_expected_baseline=enforce_expected_baseline,
    )
    cmd_check = validate_wave_commands(waves)

    checks = {
        "tiers_v14_gate": tiers_check,
        "opencode_config_permission": config_check,
        "child_env_isolation": env_check,
        "clean_workdir_isolation": workdir_check,
        "transcript_redaction_infra_and_steps": transcript_check,
        "cli_command_validation": cmd_check,
    }
    all_errors = list(scan["errors"])
    for chk in checks.values():
        all_errors.extend(chk["errors"])

    total_target = sum(c["target_count"] for c in scan["cohorts"])
    total_landed = sum(c["landed_count"] for c in scan["cohorts"])
    total_missing = sum(c["missing_count"] for c in scan["cohorts"])

    return {
        "schema_version": 1,
        "tiers_version": rules.TIERS_VERSION,
        "replication_root": scan["replication_root"],
        "runner": {
            "module": RUNNER_MODULE,
            "python": VENV_PYTHON,
            "path_prefix": MOMIN_PATH_PREFIX,
            "timeout_s": DEFAULT_TIMEOUT_S,
            "jobs_per_worker": DEFAULT_JOBS,
            "max_workers_per_wave": max_workers_per_wave,
        },
        "summary": {
            "passed": not all_errors,
            "replication_total_episodes": scan["total_episodes"],
            "replication_replay_verified_episodes": scan["replay_verified_episodes"],
            "target_frontier_episodes": total_target,
            "landed_frontier_episodes": total_landed,
            "missing_frontier_episodes": total_missing,
            "wave_count": len(waves),
            "max_workers_in_any_wave": max((w["worker_count"] for w in waves), default=0),
        },
        "cohorts": scan["cohorts"],
        "preflight": {
            "passed": not all_errors,
            "zero_live_llm_calls": True,
            "checks": checks,
            "errors": all_errors,
        },
        "waves": waves,
    }


def render_manifest(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, indent=2) + "\n"


def default_manifest_path(root: Path) -> Path:
    return root / "results" / "frontier_replication" / "v1.4" / "queue_manifest.json"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Offline frontier runner preflight and 30-59 replication queue manifest.")
    ap.add_argument("--root", default=str(ROOT), help="repository root directory")
    ap.add_argument("--manifest", default=None, help="override output/check manifest path")
    ap.add_argument("--write", action="store_true", help="write queue_manifest.json")
    ap.add_argument("--check", action="store_true", help="verify preflight passes and queue_manifest.json is up to date")
    ap.add_argument("--json", action="store_true", help="print full manifest JSON to stdout")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    manifest_path = Path(args.manifest).resolve() if args.manifest else default_manifest_path(root)
    manifest = build_manifest(root=root)
    rendered = render_manifest(manifest)

    if not manifest["summary"]["passed"]:
        for err in manifest["preflight"]["errors"]:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1

    if args.write:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(rendered, encoding="utf-8")

    if args.check:
        if not manifest_path.is_file():
            print(f"FAIL: manifest missing at {manifest_path}", file=sys.stderr)
            return 1
        existing = manifest_path.read_text(encoding="utf-8")
        if existing != rendered:
            print(f"FAIL: manifest out of date at {manifest_path}; re-run with --write", file=sys.stderr)
            return 1

    if args.json:
        sys.stdout.write(rendered)
    else:
        s = manifest["summary"]
        cohort_bits = ", ".join(
            f"{c['cohort_id']}: landed={c['landed_count']}/{c['target_count']} missing={c['missing_count']}"
            for c in manifest["cohorts"]
        )
        print(
            f"OK preflight=PASS verified={s['replication_replay_verified_episodes']}/{s['replication_total_episodes']} "
            f"landed={s['landed_frontier_episodes']}/{s['target_frontier_episodes']} "
            f"missing={s['missing_frontier_episodes']} waves={s['wave_count']} "
            f"max_workers={s['max_workers_in_any_wave']} ({cohort_bits})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
