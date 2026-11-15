from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import logging
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary import rules, world
from canary.env import BAD, ERRORS, TOPICS, _SPECS, Env
from canary.eval import run_episode
from canary.solver.policy import SolverPolicy
from canary.types import ToolResult

TARGETS: tuple[str, ...] = ("easy", "medium", "hard", "hard_forge", "hard_rl")
DETERMINISTIC_AUDIT_SECRET = b"canary-w4-arena-engine-parity-deterministic-v14"
SCRATCH_ROOT = Path("/tmp/opencode")

CROSS_SQUAD_SPECS: tuple[tuple[str, str, str], ...] = (
    ("eval_arena", "origin/fr8/canary/eval-arena", "docs/arena/scoring_parity.py"),
    ("port_replay_engine", "origin/fr8/canary/canary-port-w3-arena", "docs/arena/replay_engine.js"),
    ("strategies_mole_mode", "origin/fr8/canary/canary-strategies-w2-arena", "docs/arena/mole_mode.py"),
    ("research_seeds_catalog", "origin/fr8/canary/research-arena", "docs/arena/SEEDS.md"),
    ("staffai_living_office", "origin/fr8/canary/canary-staffai-w5-arena", "docs/arena/data/living_office_pack.js"),
)

PRE_END_FORBIDDEN_KEYS: frozenset[str] = frozenset({
    "mole",
    "true_mole",
    "mole_id",
    "is_mole",
    "decoy",
    "true_decoy",
    "decoy_id",
    "is_decoy",
    "correct",
    "accused_correct",
    "true_v",
    "true_V",
    "world_seed",
    "_world",
    "leaking_sprite_employee",
    "mole_sprite",
    "culprit_sprite",
    "leaker_employee",
})

EMP_ID_RE = re.compile(r"^e\d{2,3}$")


def expected_known_v(env: Any) -> float:
    if not rules.KNOWN_V_MODE:
        return round(float(env.V), 10)
    surfaced = sum(1 for item in env._feed if item["surfaced_day"] <= env.day)
    return round(max(0.0, 1.0 - env.p.leak_damage * surfaced - env._costs), 10)


def expected_terminal_score(
    done: bool,
    accused: str | None,
    mole: str,
    true_v: float,
    wrong_accusation_score: float = -1.0,
) -> float:
    if not done or accused is None:
        return 0.0
    if accused == mole:
        return round(float(true_v), 10)
    return float(wrong_accusation_score)


def _find_node_binary() -> str | None:
    found = shutil.which("node")
    if found:
        return found
    for candidate in (
        Path.home() / "tools" / "node" / "bin" / "node",
        Path("/usr/local/bin/node"),
        Path("/usr/bin/node"),
    ):
        if candidate.is_file():
            return str(candidate)
    return None


def _load_module_from_source(mod_name: str, source_text: str, filename_hint: str = "mod.py") -> Any:
    SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(SCRATCH_ROOT), prefix="w4_mod_") as tmp:
        fp = Path(tmp) / filename_hint
        fp.write_text(source_text, encoding="utf-8")
        spec = importlib.util.spec_from_file_location(mod_name, fp)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"failed to create module spec for {mod_name}")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        try:
            spec.loader.exec_module(mod)
        finally:
            sys.modules.pop(mod_name, None)
        return mod


def _load_canary_game_module(root: Path = ROOT) -> Any:
    cg_path = root / "game" / "canary_game.py"
    spec = importlib.util.spec_from_file_location("w4_canary_game_ref", cg_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"missing {cg_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _scan_pre_end_payload_leaks(
    payload: Any,
    loc: str = "$",
    *,
    human_done: bool = False,
    mode: str = "investigator",
    allow_doc_is_canary: bool = False,
) -> list[str]:
    violations: list[str] = []
    if isinstance(payload, list):
        for idx, item in enumerate(payload):
            violations.extend(
                _scan_pre_end_payload_leaks(
                    item,
                    f"{loc}[{idx}]",
                    human_done=human_done,
                    mode=mode,
                    allow_doc_is_canary=allow_doc_is_canary,
                )
            )
        return violations
    if not isinstance(payload, dict):
        return violations

    node_done = payload.get("done") is True or payload.get("episode_over") is True
    effective_pre_end = (not human_done) and (not node_done)

    if effective_pre_end:
        for key in PRE_END_FORBIDDEN_KEYS:
            if key in payload and payload[key] is not None and payload[key] != "[SEALED]":
                if mode == "mole" and key == "mole_id":
                    continue
                violations.append(f"{loc}.{key}: pre-end hidden truth exposed ({payload[key]!r})")
        if "is_canary" in payload and not allow_doc_is_canary:
            violations.append(f"{loc}.is_canary: pre-end canary flag exposed ({payload['is_canary']!r})")
        if payload.get("tool") == "accuse" and not human_done:
            args_obj = payload.get("args") if isinstance(payload.get("args"), dict) else {}
            emp = args_obj.get("employee")
            if isinstance(emp, str) and EMP_ID_RE.match(emp):
                violations.append(f"{loc}.args.employee: unsealed pre-end accuse target {emp!r}")

    is_list_docs = (payload.get("tool") == "list_documents") and mode != "mole"
    for k, v in payload.items():
        ks = str(k)
        if ks == "sealed_reveal":
            continue
        if ks in {"final", "reveal", "verdict", "outcome"} and isinstance(v, dict) and v.get("sealed") is True:
            continue
        violations.extend(
            _scan_pre_end_payload_leaks(
                v,
                f"{loc}.{ks}",
                human_done=human_done,
                mode=mode,
                allow_doc_is_canary=allow_doc_is_canary or (is_list_docs and ks in {"result", "data", "documents"}),
            )
        )
    return violations


def check_step_state_parity(env: Any, tool: str, args: dict[str, Any], res: ToolResult) -> list[str]:
    problems: list[str] = []
    exp_kv = expected_known_v(env)
    got_kv = float(env.visible_V())
    true_v = round(float(env.V), 10)
    if abs(got_kv - exp_kv) > 1e-9:
        problems.append(f"visible_V_formula_mismatch:got={got_kv}:exp={exp_kv}")
    peek = env.peek_status()
    if abs(float(peek["V"]) - exp_kv) > 1e-9:
        problems.append(f"peek_status_V_mismatch:got={peek['V']}:exp={exp_kv}")
    if rules.KNOWN_V_MODE and any(f["surfaced_day"] > env.day for f in env._feed):
        if not (got_kv > true_v or got_kv == 0.0):
            problems.append(f"unsurfaced_leak_exposed_in_visible_V:vis={got_kv}:true={true_v}")
    if res.ok and tool in {"status", "advance_day"} and isinstance(res.data, dict) and "V" in res.data:
        shown_v = float(res.data["V"])
        if abs(shown_v - exp_kv) > 1e-9:
            problems.append(f"{tool}_shown_V_mismatch:got={shown_v}:exp={exp_kv}")
    if not res.ok and res.error not in ERRORS:
        problems.append(f"unexpected_error_constant:{res.error!r}")
    if not env.done:
        if env.score() != 0.0:
            problems.append(f"pre_done_nonzero_score:{env.score()}")
        step_leaks = _scan_pre_end_payload_leaks(
            {"tool": tool, "args": args, "result": {"ok": res.ok, "data": res.data, "error": res.error}, "done": False},
            human_done=True,
            mode="investigator",
        )
        problems.extend(step_leaks)
    return problems


def check_terminal_and_post_end_parity(env: Any, expected_reason: str) -> list[str]:
    problems: list[str] = []
    mole = env._world.mole
    verdict = env.verdict()
    if not env.done or verdict["done"] is not True:
        return ["terminal_env_not_done"]
    if verdict["end_reason"] != expected_reason:
        problems.append(f"end_reason_mismatch:got={verdict['end_reason']}:exp={expected_reason}")
    exp_score = expected_terminal_score(
        done=True,
        accused=verdict["accused"],
        mole=mole,
        true_v=verdict["V"],
        wrong_accusation_score=env.p.wrong_accusation_score,
    )
    if abs(float(env.score()) - exp_score) > 1e-9 or abs(float(verdict["score"]) - exp_score) > 1e-9:
        problems.append(f"terminal_score_mismatch:got={verdict['score']}:exp={exp_score}")
    exp_correct = bool(verdict["accused"] is not None and verdict["accused"] == mole)
    if bool(verdict["correct"]) != exp_correct or bool(verdict["accused_correct"]) != exp_correct:
        problems.append(f"terminal_correct_mismatch:got={verdict['correct']}:exp={exp_correct}")

    snap_score = float(env.score())
    snap_v = float(env.V)
    snap_vis = float(env.visible_V())
    snap_accused = verdict["accused"]
    snap_correct = verdict["correct"]
    snap_reason = verdict["end_reason"]
    snap_ledger_len = len(env.ledger())

    for p_tool, p_args in (
        ("status", {}),
        ("plant_canary", {"doc_title": "PostEnd", "assignment": {env._ids[0]: "A"}}),
        ("restrict_access", {"employee": env._ids[0]}),
        ("advance_day", {}),
        ("accuse", {"employee": mole}),
    ):
        post_res = env.call(p_tool, p_args)
        after_verdict = env.verdict()
        if (
            post_res.ok
            or post_res.error != "episode over"
            or post_res.data != {}
            or float(env.score()) != snap_score
            or float(env.V) != snap_v
            or float(env.visible_V()) != snap_vis
            or after_verdict["accused"] != snap_accused
            or after_verdict["correct"] != snap_correct
            or after_verdict["end_reason"] != snap_reason
            or len(env.ledger()) != snap_ledger_len
        ):
            problems.append(f"post_end_mutation_on_{p_tool}")
    return problems


def check_detail_role_parity_on_env(env_factory: Any) -> dict[str, Any]:
    probe_env = env_factory()
    mole = probe_env._world.mole
    decoy = probe_env._world.decoy
    innocent = next(e for e in probe_env._ids if e != mole and e != decoy)
    roles: list[tuple[str, str]] = [("mole", mole), ("innocent", innocent)]
    if decoy is not None:
        roles.insert(1, ("decoy", decoy))

    role_sigs: dict[str, list[str]] = {}
    problems: list[str] = []
    checks = 0

    for role_name, emp in roles:
        e = env_factory()
        ws_str = str(e._world.world_seed)
        calls = [
            ("unrestrict_access", {"employee": emp}),
            ("interview", {"employee": emp, "topic": "not_valid_topic"}),
            ("read_access_logs", {"day_from": 4, "day_to": 2, "employee": emp}),
            ("plant_canary", {"doc_title": "RoleProbe", "assignment": {emp: "   "}}),
            ("plant_canary", {"doc_title": "RoleProbe", "assignment": {emp: "X" * 25}}),
            ("restrict_access", {"employee": emp, "extra_bad": 1}),
        ]
        norm_details: list[str] = []
        for tool, args in calls:
            res = e.call(tool, args)
            checks += 1
            det = res.data.get("detail") if isinstance(res.data, dict) else None
            if res.ok or res.error != BAD or not isinstance(det, str) or not det.strip():
                problems.append(f"{role_name}:{tool}:missing_bad_detail")
                norm_details.append("<ERR>")
                continue
            if ws_str in det:
                problems.append(f"{role_name}:{tool}:world_seed_leak")
            if mole != emp and mole in det:
                problems.append(f"{role_name}:{tool}:unprompted_mole_id_leak")
            norm_details.append(det.replace(emp, "<id>"))

        r_ok = e.call("restrict_access", {"employee": emp})
        if r_ok.ok:
            for tool, args in (
                ("restrict_access", {"employee": emp}),
                ("plant_canary", {"doc_title": "RoleProbe2", "assignment": {emp: "A"}}),
            ):
                res = e.call(tool, args)
                checks += 1
                det = res.data.get("detail") if isinstance(res.data, dict) else None
                if res.ok or res.error != BAD or not isinstance(det, str) or not det.strip():
                    problems.append(f"{role_name}:{tool}:missing_restricted_detail")
                    norm_details.append("<ERR>")
                else:
                    if ws_str in det:
                        problems.append(f"{role_name}:{tool}:world_seed_leak")
                    if mole != emp and mole in det:
                        problems.append(f"{role_name}:{tool}:unprompted_mole_id_leak")
                    norm_details.append(det.replace(emp, "<id>"))
        role_sigs[role_name] = norm_details

    base_sig = role_sigs["mole"]
    for other_role, sig in role_sigs.items():
        if sig != base_sig:
            problems.append(f"role_detail_asymmetry:mole_vs_{other_role}")

    return {
        "roles_checked": [r for r, _ in roles],
        "checks": checks,
        "mismatches": problems,
    }


def check_interactive_game_seed_firewall(game_cls: Any) -> dict[str, Any]:
    problems: list[str] = []
    judge_refused = 0
    for s in rules.JUDGE_SEEDS:
        try:
            game_cls(s)
        except ValueError:
            judge_refused += 1
        else:
            problems.append(f"accepted_judge_seed:{s}")

    heldout_refused = 0
    for s in rules.HELDOUT_SEEDS:
        try:
            game_cls(s)
        except ValueError:
            heldout_refused += 1
        else:
            problems.append(f"accepted_heldout_seed:{s}")

    low_dev_probes = list(range(0, 30)) + [30, 100, 999, 2999]
    low_dev_refused = 0
    for s in low_dev_probes:
        try:
            game_cls(s)
        except ValueError:
            low_dev_refused += 1
        else:
            problems.append(f"accepted_low_dev_seed:{s}")

    malformed_probes: list[Any] = [10000, 100000, -1, -900000, 3000.5, "3000.0", "3e3", "NaN", "abc", "", True, None]
    malformed_refused = 0
    for bad in malformed_probes:
        try:
            game_cls(bad)
        except ValueError:
            malformed_refused += 1
        else:
            problems.append(f"accepted_malformed_seed:{bad!r}")

    return {
        "judge_seeds_probed": len(rules.JUDGE_SEEDS),
        "judge_seeds_refused": judge_refused,
        "heldout_seeds_probed": len(rules.HELDOUT_SEEDS),
        "heldout_seeds_refused": heldout_refused,
        "low_dev_seeds_probed": len(low_dev_probes),
        "low_dev_seeds_refused": low_dev_refused,
        "malformed_seeds_probed": len(malformed_probes),
        "malformed_seeds_refused": malformed_refused,
        "violations": problems,
    }


def _fuzz_single_episode(
    tier: str,
    seed: int,
    rng: random.Random,
    terminal_mode: str,
) -> dict[str, Any]:
    env = Env(tier=tier, seed=seed)
    mole = env._world.mole
    decoy = env._world.decoy
    innocents = [e for e in env._ids if e != mole]
    wrong_target = decoy if (decoy is not None and rng.random() < 0.5) else rng.choice(innocents)

    violations: list[str] = []
    states_checked = 0
    unsurfaced_states = 0

    le_res = env.call("list_employees", {})
    states_checked += 1
    violations.extend(check_step_state_parity(env, "list_employees", {}, le_res))

    if terminal_mode == "tool_cap":
        while not env.done:
            st_res = env.call("status", {})
            states_checked += 1
            violations.extend(check_step_state_parity(env, "status", {}, st_res))
        violations.extend(check_terminal_and_post_end_parity(env, "tool_cap"))
        return {
            "states_checked": states_checked,
            "unsurfaced_states": unsurfaced_states,
            "violations": violations,
            "score": env.score(),
            "end_reason": env.verdict()["end_reason"],
        }

    target_days = env.p.n_days if terminal_mode == "abstain_horizon" else rng.randint(3, min(8, env.p.n_days - 1))

    for _ in range(target_days):
        if env.done:
            break
        picks = rng.sample(list(env._ids), min(3, len(env._ids)))
        unrestricted_picks = [e for e in picks if e not in env._restricted]
        if unrestricted_picks and env._canaries_today < env.p.canaries_per_day:
            labels = ["A", "B", "C"]
            asg = {emp: labels[idx % env.p.max_variants] for idx, emp in enumerate(unrestricted_picks)}
            c_args = {"doc_title": f"ArenaFuzz-{env.day}", "assignment": asg}
            c_res = env.call("plant_canary", c_args)
            states_checked += 1
            violations.extend(check_step_state_parity(env, "plant_canary", c_args, c_res))
            if any(f["surfaced_day"] > env.day for f in env._feed):
                unsurfaced_states += 1

        op_choice = rng.choice(("status", "check_leak_feed", "interview", "restrict_toggle", "bad_call"))
        if op_choice == "status":
            r = env.call("status", {})
            states_checked += 1
            violations.extend(check_step_state_parity(env, "status", {}, r))
        elif op_choice == "check_leak_feed":
            r = env.call("check_leak_feed", {})
            states_checked += 1
            violations.extend(check_step_state_parity(env, "check_leak_feed", {}, r))
        elif op_choice == "interview":
            iv_args = {"employee": rng.choice(list(env._ids)), "topic": rng.choice(TOPICS)}
            r = env.call("interview", iv_args)
            states_checked += 1
            violations.extend(check_step_state_parity(env, "interview", iv_args, r))
        elif op_choice == "restrict_toggle":
            cand = rng.choice(innocents)
            if cand in env._restricted:
                u_args = {"employee": cand}
                r = env.call("unrestrict_access", u_args)
                states_checked += 1
                violations.extend(check_step_state_parity(env, "unrestrict_access", u_args, r))
            else:
                r_args = {"employee": cand}
                r = env.call("restrict_access", r_args)
                states_checked += 1
                violations.extend(check_step_state_parity(env, "restrict_access", r_args, r))
        else:
            b_args = {"employee": rng.choice(list(env._ids)), "topic": "invalid_fuzz_topic"}
            r = env.call("interview", b_args)
            states_checked += 1
            violations.extend(check_step_state_parity(env, "interview", b_args, r))

        if any(f["surfaced_day"] > env.day for f in env._feed):
            unsurfaced_states += 1

        if terminal_mode != "abstain_horizon" and env.day >= target_days:
            break

        adv_res = env.call("advance_day", {})
        states_checked += 1
        violations.extend(check_step_state_parity(env, "advance_day", {}, adv_res))
        if any(f["surfaced_day"] > env.day for f in env._feed):
            unsurfaced_states += 1

        st_after = env.call("status", {})
        states_checked += 1
        violations.extend(check_step_state_parity(env, "status", {}, st_after))

    if terminal_mode == "correct_accuse" and not env.done:
        acc_args = {"employee": mole}
        acc_res = env.call("accuse", acc_args)
        states_checked += 1
        if not acc_res.ok or acc_res.data != {"accused": mole, "episode_over": True}:
            violations.append(f"accuse_response_shape_mismatch:{acc_res.data!r}")
        violations.extend(check_terminal_and_post_end_parity(env, "accused"))
    elif terminal_mode == "wrong_accuse" and not env.done:
        acc_args = {"employee": wrong_target}
        acc_res = env.call("accuse", acc_args)
        states_checked += 1
        if not acc_res.ok or acc_res.data != {"accused": wrong_target, "episode_over": True}:
            violations.append(f"accuse_response_shape_mismatch:{acc_res.data!r}")
        if float(env.score()) != -1.0:
            violations.append(f"wrong_accuse_not_minus_one:{env.score()}")
        violations.extend(check_terminal_and_post_end_parity(env, "accused"))
    elif terminal_mode == "abstain_horizon":
        while not env.done:
            adv_res = env.call("advance_day", {})
            states_checked += 1
            violations.extend(check_step_state_parity(env, "advance_day", {}, adv_res))
        if float(env.score()) != 0.0:
            violations.append(f"abstain_horizon_nonzero_score:{env.score()}")
        violations.extend(check_terminal_and_post_end_parity(env, "horizon"))

    return {
        "states_checked": states_checked,
        "unsurfaced_states": unsurfaced_states,
        "violations": violations,
        "score": env.score(),
        "end_reason": env.verdict()["end_reason"],
    }


def fuzz_arena_env_and_game_parity(
    root: Path = ROOT,
    quick: bool = False,
    rng_seed: int = 20261115,
    targets: tuple[str, ...] = TARGETS,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    rng = random.Random(rng_seed)
    violations: list[str] = []

    if rules.TIERS_VERSION != "v1.4":
        violations.append(f"unexpected_tiers_version:{rules.TIERS_VERSION}")
    if rules.KNOWN_V_MODE is not True:
        violations.append("KNOWN_V_MODE_is_not_True")

    modes_per_target = (
        ("correct_accuse", "wrong_accuse", "abstain_horizon", "correct_accuse")
        if quick
        else (
            "correct_accuse",
            "wrong_accuse",
            "abstain_horizon",
            "correct_accuse",
            "wrong_accuse",
            "abstain_horizon",
        )
    )

    total_states = 0
    total_unsurfaced_states = 0
    episodes_fuzzed = 0
    per_target: dict[str, dict[str, Any]] = {}
    outcome_counts = {"correct_accuse": 0, "wrong_accuse": 0, "abstain_horizon": 0, "tool_cap": 0}

    for t_idx, target in enumerate(targets):
        t_states = 0
        t_unsurf = 0
        t_eps = 0
        t_viols: list[str] = []
        for m_idx, mode in enumerate(modes_per_target):
            seed = 4100 + t_idx * 100 + m_idx
            ep_out = _fuzz_single_episode(target, seed, rng, mode)
            t_states += ep_out["states_checked"]
            t_unsurf += ep_out["unsurfaced_states"]
            t_eps += 1
            outcome_counts[mode] += 1
            t_viols.extend(f"{target}:{seed}:{v}" for v in ep_out["violations"])

        if target == "easy":
            cap_out = _fuzz_single_episode(target, 4999, rng, "tool_cap")
            t_states += cap_out["states_checked"]
            t_unsurf += cap_out["unsurfaced_states"]
            t_eps += 1
            outcome_counts["tool_cap"] += 1
            t_viols.extend(f"{target}:4999:{v}" for v in cap_out["violations"])

        role_res = check_detail_role_parity_on_env(lambda t=target, s=4200 + t_idx: Env(t, s))
        t_viols.extend(f"{target}:detail:{v}" for v in role_res["mismatches"])

        per_target[target] = {
            "episodes": t_eps,
            "states_checked": t_states,
            "unsurfaced_states": t_unsurf,
            "detail_role_checks": role_res["checks"],
            "detail_roles": role_res["roles_checked"],
            "violations": len(t_viols),
        }
        total_states += t_states
        total_unsurfaced_states += t_unsurf
        episodes_fuzzed += t_eps
        violations.extend(t_viols)

    cg_mod = _load_canary_game_module(root)
    firewall = check_interactive_game_seed_firewall(cg_mod.Game)
    violations.extend(f"canary_game:{v}" for v in firewall["violations"])

    game_role_res = check_detail_role_parity_on_env(lambda: cg_mod.Game(3000).env)
    violations.extend(f"canary_game_3000:detail:{v}" for v in game_role_res["mismatches"])

    game_parity_seeds = (3000, 3003) if quick else (3000, 3001, 3002, 3003)
    game_replay_checks = 0
    for g_seed in game_parity_seeds:
        sol_ep = run_episode(Env("medium", g_seed), SolverPolicy())
        actions = [[st.tool, copy.deepcopy(st.args)] for st in sol_ep.steps]
        g = cg_mod.Game(g_seed)
        if len(g.env.history) != 0 or len(g.actions) != 0:
            violations.append(f"canary_game:{g_seed}:nonzero_init_history")
        spec_payload = json.loads(g.spec_json())
        ref_other_env = Env("medium", g_seed + 1)
        if (
            spec_payload.get("instruction") != ref_other_env.instruction()
            or spec_payload.get("tools") != ref_other_env.tools_spec()
            or _scan_pre_end_payload_leaks(spec_payload, f"spec:{g_seed}", human_done=False)
        ):
            violations.append(f"canary_game:{g_seed}:spec_json_not_seed_invariant_or_leaked")
        pre_rev = json.loads(g.reveal_json())
        if pre_rev != {"error": "the episode is not over yet"}:
            violations.append(f"canary_game:{g_seed}:unsealed_initial_reveal")
        for st_idx, (tool, args) in enumerate(actions):
            out = json.loads(g.call_json(tool, json.dumps(args)))
            exp_st = json.loads(json.dumps(sol_ep.steps[st_idx].result, default=str))
            if out["ok"] != exp_st["ok"] or out["data"] != exp_st["data"] or out["error"] != exp_st["error"]:
                violations.append(f"canary_game:{g_seed}:step_mismatch:{st_idx}")
            total_states += 1
            if not g.env.done:
                mid_rev = json.loads(g.reveal_json())
                if mid_rev != {"error": "the episode is not over yet"}:
                    violations.append(f"canary_game:{g_seed}:mid_episode_reveal_leak:{st_idx}")
        post_rev = json.loads(g.reveal_json())
        rep_verdict = cg_mod.replay(g_seed, actions)
        if (
            post_rev["you"]["score"] != sol_ep.score
            or post_rev["you"]["correct"] != sol_ep.correct
            or post_rev["you"]["accused"] != sol_ep.accused
            or post_rev["you"]["final_day"] != sol_ep.final_day
            or post_rev["you"]["tool_calls"] != len(actions)
            or post_rev["mole"] != g.env._world.mole
            or post_rev["solver"]["score"] != sol_ep.score
            or rep_verdict["score"] != sol_ep.score
        ):
            violations.append(f"canary_game:{g_seed}:post_reveal_parity_mismatch")
        game_replay_checks += 1

    detail_checks_total = sum(v["detail_role_checks"] for v in per_target.values()) + game_role_res["checks"]

    return {
        "passed": len(violations) == 0 and total_states >= 200,
        "targets": list(targets),
        "tiers_version": rules.TIERS_VERSION,
        "known_v_mode": rules.KNOWN_V_MODE,
        "episodes_fuzzed": episodes_fuzzed,
        "states_checked": total_states,
        "unsurfaced_leak_states_checked": total_unsurfaced_states,
        "outcome_counts": outcome_counts,
        "detail_role_parity_checks": detail_checks_total,
        "game_seed_firewall": firewall,
        "game_solver_replays_verified": game_replay_checks,
        "per_target": per_target,
        "violations_count": len(violations),
        "violations": violations[:10],
        "elapsed_s": round(time.perf_counter() - t0, 4),
    }


def run_planted_bug_controls() -> dict[str, Any]:
    t0 = time.perf_counter()
    controls: list[dict[str, Any]] = []
    failures: list[str] = []

    base_env = Env("medium", 3000)
    while not any(f["surfaced_day"] > base_env.day for f in base_env._feed) and not base_env.done:
        base_env.call("advance_day", {})
    clean_res = base_env.call("status", {})
    clean_problems = check_step_state_parity(base_env, "status", {}, clean_res)
    if clean_problems:
        failures.append(f"clean_control_false_positive:{clean_problems}")

    class _TrueVLeakyEnvProxy:
        def __init__(self, inner: Env):
            self._inner = inner

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

        def visible_V(self) -> float:
            return round(float(self._inner.V), 10)

    c1 = check_step_state_parity(
        _TrueVLeakyEnvProxy(base_env),
        "status",
        {},
        ToolResult(True, {"day": base_env.day, "V": round(float(base_env.V), 10)}, None),
    )
    ok1 = any("visible_V_formula_mismatch" in x or "unsurfaced_leak_exposed" in x for x in c1)
    controls.append({"control": "planted_visible_v_uses_true_v", "caught": ok1, "signals": c1[:2]})
    if not ok1:
        failures.append("missed:planted_visible_v_uses_true_v")

    wrong_env = Env("easy", 3000)
    innocent = next(e for e in wrong_env._ids if e != wrong_env._world.mole)
    wrong_env.call("accuse", {"employee": innocent})

    class _SoftWrongPenaltyProxy:
        def __init__(self, inner: Env):
            self._inner = inner

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

        def score(self) -> float:
            return 0.0

        def verdict(self) -> dict[str, Any]:
            v = dict(self._inner.verdict())
            v["score"] = 0.0
            return v

    c2 = check_terminal_and_post_end_parity(_SoftWrongPenaltyProxy(wrong_env), "accused")
    ok2 = any("terminal_score_mismatch" in x for x in c2)
    controls.append({"control": "planted_wrong_accuse_zero_penalty", "caught": ok2, "signals": c2[:2]})
    if not ok2:
        failures.append("missed:planted_wrong_accuse_zero_penalty")

    abs_env = Env("easy", 3001)
    while not abs_env.done:
        abs_env.call("advance_day", {})

    class _NonzeroAbstainProxy:
        def __init__(self, inner: Env):
            self._inner = inner

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

        def score(self) -> float:
            return 0.55

        def verdict(self) -> dict[str, Any]:
            v = dict(self._inner.verdict())
            v["score"] = 0.55
            return v

    c3 = check_terminal_and_post_end_parity(_NonzeroAbstainProxy(abs_env), "horizon")
    ok3 = any("terminal_score_mismatch" in x for x in c3)
    controls.append({"control": "planted_abstain_nonzero_score", "caught": ok3, "signals": c3[:2]})
    if not ok3:
        failures.append("missed:planted_abstain_nonzero_score")

    class _PostEndMutableProxy:
        def __init__(self, inner: Env):
            self._inner = inner
            self._overwritten = False

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

        def call(self, tool: str, args: dict[str, Any]) -> ToolResult:
            if tool == "accuse":
                self._overwritten = True
                return ToolResult(True, {"accused": args.get("employee"), "episode_over": True}, None)
            return self._inner.call(tool, args)

        def score(self) -> float:
            return 0.95 if self._overwritten else self._inner.score()

    c4 = check_terminal_and_post_end_parity(_PostEndMutableProxy(wrong_env), "accused")
    ok4 = any("post_end_mutation_on_accuse" in x for x in c4)
    controls.append({"control": "planted_post_end_accuse_overwrite", "caught": ok4, "signals": c4[:2]})
    if not ok4:
        failures.append("missed:planted_post_end_accuse_overwrite")

    class _RoleLeakyDetailProxy:
        def __init__(self, inner: Env):
            self._inner = inner

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

        def call(self, tool: str, args: dict[str, Any]) -> ToolResult:
            res = self._inner.call(tool, args)
            if not res.ok and res.error == BAD and args.get("employee") == self._inner._world.mole:
                return ToolResult(False, {"detail": "mole guard blocked " + str(args.get("employee"))}, BAD)
            return res

    c5_res = check_detail_role_parity_on_env(lambda: _RoleLeakyDetailProxy(Env("medium", 3000)))
    ok5 = any("role_detail_asymmetry" in x for x in c5_res["mismatches"])
    controls.append({"control": "planted_detail_role_asymmetry", "caught": ok5, "signals": c5_res["mismatches"][:2]})
    if not ok5:
        failures.append("missed:planted_detail_role_asymmetry")

    class _PermissiveSeedGame:
        def __init__(self, seed: Any):
            if not isinstance(seed, int) or isinstance(seed, bool):
                raise ValueError("bad seed")
            self.seed = seed

    c6_res = check_interactive_game_seed_firewall(_PermissiveSeedGame)
    ok6 = (
        any("accepted_judge_seed:900000" in x for x in c6_res["violations"])
        and any("accepted_heldout_seed:800000" in x for x in c6_res["violations"])
        and any("accepted_low_dev_seed:6" in x for x in c6_res["violations"])
    )
    controls.append({"control": "planted_game_seed_gate_bypass", "caught": ok6, "signals": c6_res["violations"][:3]})
    if not ok6:
        failures.append("missed:planted_game_seed_gate_bypass")

    c7 = _scan_pre_end_payload_leaks(
        {
            "tier": "hard",
            "seed": 6,
            "human_done": False,
            "mole": "e34",
            "steps": [{"day": 6, "tool": "accuse", "args": {"employee": "e34"}, "done": False}],
        },
        human_done=False,
        mode="duel",
    )
    ok7 = any(".mole" in x for x in c7) and any("unsealed pre-end accuse target" in x for x in c7)
    controls.append({"control": "planted_pre_end_mole_and_accuse_leak", "caught": ok7, "signals": c7[:2]})
    if not ok7:
        failures.append("missed:planted_pre_end_mole_and_accuse_leak")

    c8 = _scan_pre_end_payload_leaks(
        {
            "tier": "medium",
            "seed": 3000,
            "done": False,
            "leakable_docs": [{"doc_id": "doc-d1-1", "is_canary": True}],
        },
        human_done=False,
        mode="mole",
    )
    ok8 = any("is_canary" in x for x in c8)
    controls.append({"control": "planted_mole_mode_is_canary_leak", "caught": ok8, "signals": c8[:2]})
    if not ok8:
        failures.append("missed:planted_mole_mode_is_canary_leak")

    caught_count = sum(1 for c in controls if c["caught"])
    return {
        "passed": len(failures) == 0 and caught_count == len(controls),
        "clean_control_false_positives": len(clean_problems),
        "controls_total": len(controls),
        "controls_caught": caught_count,
        "controls": controls,
        "failures": failures,
        "elapsed_s": round(time.perf_counter() - t0, 4),
    }


def _git_show_blob(root: Path, ref: str, rel_path: str) -> str | None:
    spec = f"{ref}:{rel_path}"
    chk = subprocess.run(
        ["git", "cat-file", "-e", spec],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if chk.returncode != 0:
        return None
    out = subprocess.run(
        ["git", "show", spec],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if out.returncode != 0:
        return None
    return out.stdout


def audit_eval_scoring_parity_source(source_text: str, ref_label: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    mod = _load_module_from_source("w4_eval_scoring_parity", source_text, "scoring_parity.py")
    issues: list[dict[str, Any]] = []
    hard_leaks: list[str] = []

    parity_runs = 0
    for tier, seed in (("easy", 3000), ("medium", 3000), ("hard", 6)):
        sol_ep = run_episode(Env(tier, seed), SolverPolicy())
        actions = mod.actions_from_episode(sol_ep)
        res = mod.verify_action_list_parity(tier, seed, actions)
        if not res.get("ok") or res.get("score") != sol_ep.score or res.get("correct") != sol_ep.correct:
            hard_leaks.append(f"{tier}:{seed}:verify_action_list_parity_mismatch")
        parity_runs += 1

    wrong_env = Env("easy", 3001)
    inn = next(e for e in wrong_env._ids if e != wrong_env._world.mole)
    wrong_actions = [["status", {}], ["accuse", {"employee": inn}]]
    w_res = mod.verify_action_list_parity("easy", 3001, wrong_actions)
    if w_res["score"] != -1.0 or w_res["correct"] is not False:
        hard_leaks.append("wrong_accuse_parity_failed")
    parity_runs += 1

    abs_actions = [["advance_day", {}] for _ in range(14)]
    a_res = mod.verify_action_list_parity("easy", 3002, abs_actions)
    if a_res["score"] != 0.0 or a_res["accused"] is not None:
        hard_leaks.append("abstain_horizon_parity_failed")
    parity_runs += 1

    session_cls = getattr(mod, "ArenaSession", None)
    unbounded_accepted: list[int] = []
    if session_cls is not None:
        for probe_seed in (6, 800000, 900000):
            try:
                sess = session_cls("medium", probe_seed)
            except ValueError:
                pass
            else:
                unbounded_accepted.append(probe_seed)
                pre_rev = json.loads(sess.reveal_json())
                if "error" not in pre_rev or "mole" in pre_rev:
                    hard_leaks.append(f"ArenaSession_pre_end_reveal_leak:{probe_seed}")

    if unbounded_accepted:
        issues.append({
            "id": "ISSUE-ARENA-ENGINE-EVAL-SESSION-UNBOUNDED-SEED",
            "severity": "low",
            "target_ref": ref_label,
            "locations": ["docs/arena/scoring_parity.py:334-340,407"],
            "summary": (
                f"ArenaSession (aliased as ArenaGame) validates seeds only with _parse_int_seed rather than "
                f"canary_game.check_seed (3000..9999), accepting benchmark seeds {unbounded_accepted} directly "
                f"if exposed to interactive browser callers without canary_game.Game."
            ),
        })

    duel_tie_summary = mod.duel_end_screen_summary(
        "hard",
        6,
        {"accused": None, "correct": False, "final_day": 21, "tool_calls": 21, "score": 0.0},
        {"accused": "e34", "correct": True, "final_day": 6, "tool_calls": 50, "score": 0.73},
        {"accused": "e34", "correct": True, "final_day": 6, "tool_calls": 52, "score": 0.71},
    )

    return {
        "status": "PASS" if not hard_leaks else "FAIL",
        "ref": ref_label,
        "present": True,
        "parity_runs_verified": parity_runs,
        "arena_session_unbounded_seeds": unbounded_accepted,
        "duel_same_day_fewer_calls_caught_first": duel_tie_summary["caught_first"],
        "pre_end_leaks": hard_leaks,
    }, issues


def audit_port_replay_engine_source(
    js_source: str,
    ref_label: str,
    root: Path = ROOT,
    quick: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    hard_leaks: list[str] = []

    for req_token in ("FORBIDDEN_PRE_END_KEYS", "[SEALED]", "scrubPreEndObject", "CanaryReplayEngine"):
        if req_token not in js_source:
            hard_leaks.append(f"missing_js_guard_token:{req_token}")

    comm_file = root / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-4-carbon" / "hard" / "episodes.jsonl"
    seeds_to_check = (6, 26) if quick else (6, 26, 4, 11)
    eps_by_seed: dict[int, dict[str, Any]] = {}
    if comm_file.is_file():
        for ln in comm_file.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            obj = json.loads(ln)
            if int(obj.get("seed", -1)) in seeds_to_check:
                eps_by_seed[int(obj["seed"])] = obj

    node_bin = _find_node_binary()
    node_executed = False
    step_v_checks = 0
    causal_clamp_checks = 0

    if node_bin is not None:
        SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(SCRATCH_ROOT), prefix="w4_replay_js_") as tmp:
            tmp_p = Path(tmp)
            (tmp_p / "replay_engine.mjs").write_text(js_source, encoding="utf-8")
            pack_list = [eps_by_seed[s] for s in seeds_to_check if s in eps_by_seed]
            (tmp_p / "pack.json").write_text(json.dumps(pack_list), encoding="utf-8")
            probe_js = (
                'import fs from "node:fs";\n'
                'import { CanaryReplayEngine } from "./replay_engine.mjs";\n'
                'const pack = JSON.parse(fs.readFileSync("./pack.json", "utf8"));\n'
                'const eng = new CanaryReplayEngine(pack);\n'
                'const views = {};\n'
                'for (const ep of pack) {\n'
                '  const s = ep.seed;\n'
                '  const dMid = Math.max(1, Math.floor(ep.final_day / 2));\n'
                '  views[String(s)] = {\n'
                '    mid: eng.getDuelView({ tier: ep.tier, seed: s, humanDay: dMid, humanDone: false, agent: "gemini" }),\n'
                '    atEndPre: eng.getDuelView({ tier: ep.tier, seed: s, humanDay: ep.final_day, humanDone: false, agent: "gemini" }),\n'
                '    post: eng.getDuelView({ tier: ep.tier, seed: s, humanDay: ep.final_day, humanDone: true, agent: "gemini" }),\n'
                '  };\n'
                '}\n'
                'const compactEng = new CanaryReplayEngine([{\n'
                '  tier: "medium", seed: 3000, agent: "gemini",\n'
                '  steps: [\n'
                '    { day: 1, tool: "restrict_access", args: { employee: "e00" }, ok: true },\n'
                '    { day: 1, tool: "advance_day", args: {}, ok: true }\n'
                '  ]\n'
                '}]);\n'
                'const compactView = compactEng.getDuelView({ tier: "medium", seed: 3000, humanDay: 2, humanDone: false, agent: "gemini" });\n'
                'const zeroVEng = new CanaryReplayEngine([{\n'
                '  tier: "easy", seed: 3000, agent: "gemini", score: 0.0, accused: "e01",\n'
                '  steps: [{ day: 14, tool: "accuse", args: { employee: "e01" }, ok: true }]\n'
                '}]);\n'
                'const zeroVPost = zeroVEng.getDuelView({ tier: "easy", seed: 3000, humanDay: 14, humanDone: true, agent: "gemini" });\n'
                'const tieEng = new CanaryReplayEngine([\n'
                '  { tier: "hard", seed: 6, agent: "gemini", score: 0.73, correct: true, accused: "e34", final_day: 6, tool_calls: 50, steps: [] },\n'
                '  { tier: "hard", seed: 6, agent: "solver", score: 0.71, correct: true, accused: "e34", final_day: 6, tool_calls: 52, steps: [] }\n'
                ']);\n'
                'tieEng.selectEpisode("hard", 6);\n'
                'const tieCmp = tieEng.compareWithHuman({ tier: "hard", seed: 6, done: true, score: 0.0, accused: null, correct: false, final_day: 21, tool_calls: 21 }, true);\n'
                'console.log(JSON.stringify({ views, compactKnownV: compactView.known_v, zeroVCorrect: zeroVPost.final.correct, tieFirstCatch: tieCmp.firstCatch }));\n'
            )
            (tmp_p / "probe.mjs").write_text(probe_js, encoding="utf-8")
            proc = subprocess.run(
                [node_bin, str(tmp_p / "probe.mjs")],
                cwd=tmp_p,
                capture_output=True,
                text=True,
                timeout=15,
            )
            if proc.returncode != 0:
                hard_leaks.append(f"node_probe_failed:{proc.stderr.strip()[:200]}")
            else:
                node_executed = True
                parsed = json.loads(proc.stdout)
                for s_key, bundle in parsed["views"].items():
                    seed_num = int(s_key)
                    ep = eps_by_seed[seed_num]
                    mid_v = bundle["mid"]
                    pre_v = bundle["atEndPre"]
                    post_v = bundle["post"]
                    d_mid = max(1, ep["final_day"] // 2)
                    if any(int(st["day"]) > d_mid for st in mid_v["steps"]):
                        hard_leaks.append(f"hard:{seed_num}:causal_day_clamp_violated")
                    causal_clamp_checks += 2
                    hard_leaks.extend(_scan_pre_end_payload_leaks(mid_v, f"replay_mid:{seed_num}", human_done=False, mode="duel"))
                    hard_leaks.extend(_scan_pre_end_payload_leaks(pre_v, f"replay_end_pre:{seed_num}", human_done=False, mode="duel"))

                    shadow = Env("hard", seed_num)
                    for idx, raw_st in enumerate(ep["steps"]):
                        shadow.call(raw_st["tool"], raw_st.get("args") or {})
                        exp_kv = shadow.visible_V()
                        got_kv = float(post_v["steps"][idx]["known_v"])
                        step_v_checks += 1
                        if abs(got_kv - exp_kv) > 1e-9:
                            hard_leaks.append(f"hard:{seed_num}:step_{idx}_known_v_mismatch:got={got_kv}:exp={exp_kv}")
                    if abs(float(post_v["final"]["score"]) - float(ep["score"])) > 1e-9:
                        hard_leaks.append(f"hard:{seed_num}:post_score_mismatch")

                if abs(float(parsed["compactKnownV"]) - 0.99) > 1e-9 or parsed["zeroVCorrect"] is False:
                    issues.append({
                        "id": "ISSUE-ARENA-ENGINE-REPLAY-COMPACT-RESTRICT-AND-ZEROV",
                        "severity": "low",
                        "target_ref": ref_label,
                        "locations": ["docs/arena/replay_engine.js:356-360,708-714"],
                        "summary": (
                            f"In normalizeTrackSteps, compact step objects omitting result and explicit known_v skip "
                            f"restrict_cost_per_day deduction on advance_day (known_v={parsed['compactKnownV']} vs "
                            f"expected 0.99), and extractPostEndMetaFromRaw fallback (score > 0) infers "
                            f"correct={parsed['zeroVCorrect']} when a mole is correctly accused at V=0.0 (score=0.0) "
                            f"without explicit correct/mole metadata."
                        ),
                    })
                if str(parsed["tieFirstCatch"]).lower() != "gemini":
                    issues.append({
                        "id": "ISSUE-ARENA-ENGINE-DUEL-TIEBREAK-ORDER-DIVERGENCE",
                        "severity": "advisory",
                        "target_ref": ref_label,
                        "locations": [
                            "docs/arena/replay_engine.js:758-814",
                            "docs/arena/scoring_parity.py:954-1001",
                        ],
                        "summary": (
                            f"On same-day catches (e.g. Day 6 where Gemini uses 50 calls at +0.73 and Solver uses "
                            f"52 calls at +0.71), replay_engine.js computeFirstCatchFromContenders returns "
                            f"{parsed['tieFirstCatch']!r} (fixed You > Solver > Gemini priority ignoring tool_calls "
                            f"and score), whereas eval-arena scoring_parity.duel_end_screen_summary returns 'gemini' "
                            f"via (correct, -final_day, -tool_calls, score)."
                        ),
                    })

    return {
        "status": "PASS" if not hard_leaks else "FAIL",
        "ref": ref_label,
        "present": True,
        "node_executed": node_executed,
        "committed_episodes_replayed": len(eps_by_seed),
        "step_known_v_checks": step_v_checks,
        "causal_clamp_checks": causal_clamp_checks,
        "pre_end_leaks": hard_leaks,
    }, issues


def audit_strategies_mole_mode_source(
    py_source: str,
    ref_label: str,
    quick: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    mod = _load_module_from_source("w4_mole_mode", py_source, "mole_mode.py")
    issues: list[dict[str, Any]] = []
    hard_leaks: list[str] = []

    firewall = check_interactive_game_seed_firewall(lambda s: mod.MoleModeSession(s, "medium"))
    if firewall["violations"]:
        hard_leaks.extend(f"mole_mode_firewall:{v}" for v in firewall["violations"])

    seeds = (3000, 3001, 3002) if quick else tuple(range(3000, 3010))
    days_attempted = 0
    pleak_bypass_days = 0
    recipient_list_docs = 0
    terminal_score_checks = 0

    for s in seeds:
        sess = mod.MoleModeSession(s, "medium")
        pre_debrief = sess.get_mole_debrief()
        if pre_debrief.get("ok") is not False or "posterior_curve" in pre_debrief:
            hard_leaks.append(f"mole_mode:{s}:pre_end_debrief_unlocked")
        while not sess.done:
            dv = sess.get_mole_day_view()
            hard_leaks.extend(_scan_pre_end_payload_leaks(dv, f"mole_day_view:{s}:d{dv['day']}", human_done=False, mode="mole"))
            if "posterior_curve" in dv or "post" in dv:
                hard_leaks.append(f"mole_mode:{s}:solver_posterior_exposed_pre_end")
            for doc_entry in dv.get("leakable_docs") or ():
                if isinstance(doc_entry.get("recipients"), list):
                    recipient_list_docs += 1
            if dv["leakable_docs"]:
                doc0 = dv["leakable_docs"][0]["doc_id"]
                sess.step_mole_day({"type": "leak", "doc_id": doc0})
                days_attempted += 1
                last_app = sess._strategy.last_applied
                if last_app and last_app.get("can_leak_gate") is False and last_app.get("leak") is not None:
                    pleak_bypass_days += 1
            else:
                sess.step_mole_day({"type": "hold"})

        deb = sess.get_mole_debrief()
        env_score = sess._env.score()
        if abs(float(deb["solver_score"]) - float(env_score)) > 1e-9:
            hard_leaks.append(f"mole_mode:{s}:solver_score_mismatch")
        terminal_score_checks += 1

    if pleak_bypass_days > 0:
        issues.append({
            "id": "ISSUE-ARENA-ENGINE-MOLE-PLEAK-GATE-BYPASS",
            "severity": "medium",
            "target_ref": ref_label,
            "locations": ["docs/arena/mole_mode.py:51-69", "canary/mole/dsl.py:135-138"],
            "summary": (
                f"_HumanMoleStrategy.decide records view.can_leak in last_applied without gating leak=None when "
                f"view.can_leak is False: across {len(seeds)} medium seeds ({days_attempted} leak-action days), "
                f"{pleak_bypass_days} days with can_leak_gate=False still leaked (effective p_leak=1.00 vs tier "
                f"p_leak=0.75, miscalibrating SolverPolicy likelihoods)."
            ),
        })

    if recipient_list_docs > 0:
        issues.append({
            "id": "ISSUE-ARENA-ENGINE-MOLE-RECIPIENT-LIST-EXPOSURE",
            "severity": "low",
            "target_ref": ref_label,
            "locations": ["docs/arena/mole_mode.py:232,236", "canary/mole/dsl.py:30-35"],
            "summary": (
                f"MoleModeSession.get_mole_day_view includes full recipients lists on {recipient_list_docs} "
                f"leakable_docs entries alongside peer_roster department labels, exceeding canonical MoleView "
                f"observability (which exposes only recipient_count and age_days) and allowing cross-department "
                f"canary recipient fingerprinting."
            ),
        })

    return {
        "status": "PASS" if not hard_leaks else "FAIL",
        "ref": ref_label,
        "present": True,
        "seed_firewall_judge_refused": f"{firewall['judge_seeds_refused']}/{firewall['judge_seeds_probed']}",
        "seed_firewall_heldout_refused": f"{firewall['heldout_seeds_refused']}/{firewall['heldout_seeds_probed']}",
        "episodes_stepped": len(seeds),
        "leak_attempt_days": days_attempted,
        "pleak_gate_bypass_days": pleak_bypass_days,
        "recipient_list_docs_exposed": recipient_list_docs,
        "terminal_score_checks": terminal_score_checks,
        "pre_end_leaks": hard_leaks,
    }, issues


def audit_research_seeds_catalog_source(
    md_source: str,
    ref_label: str,
    root: Path = ROOT,
    quick: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    hard_leaks: list[str] = []

    fence = "```json"
    if fence not in md_source:
        return {
            "status": "FAIL",
            "ref": ref_label,
            "present": True,
            "pre_end_leaks": ["missing_json_manifest_fence"],
        }, issues

    j_start = md_source.index(fence) + len(fence)
    j_end = md_source.index("```", j_start)
    manifest = json.loads(md_source[j_start:j_end])

    m1 = manifest["mode_1_solo_investigator"]
    curated = list(m1["curated_public_seeds"])
    if any(not (3000 <= int(s) <= 9999) for s in curated):
        hard_leaks.append("mode_1_curated_seed_outside_3000_9999")
    if m1["default_seed_solver_benchmark"].get("live_mole_id") != "[SEALED]":
        hard_leaks.append("mode_1_default_seed_live_mole_not_sealed")

    for s in curated:
        mole_id = Env("medium", int(s))._world.mole
        row_pat = re.compile(rf"\|\s*`{s}`\s*\|[^\n]*")
        m_row = row_pat.search(md_source)
        if m_row and mole_id in m_row.group(0):
            hard_leaks.append(f"mode_1_table_leaks_mole_id:{s}:{mole_id}")

    m1_seeds_to_run = [3000, 3003] if quick else curated
    solver_checks = 0
    for s in m1_seeds_to_run:
        ep = run_episode(Env("medium", int(s)), SolverPolicy())
        solver_checks += 1
        if int(s) == 3000:
            b = m1["default_seed_solver_benchmark"]
            if (
                abs(float(b["score"]) - ep.score) > 1e-9
                or int(b["final_day"]) != ep.final_day
                or int(b["tool_calls"]) != len(ep.steps)
                or bool(b["correct"]) != ep.correct
            ):
                hard_leaks.append("mode_1_seed_3000_solver_benchmark_mismatch")

    comm_hard_file = root / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-4-carbon" / "hard" / "episodes.jsonl"
    comm_hard: dict[int, dict[str, Any]] = {}
    if comm_hard_file.is_file():
        for ln in comm_hard_file.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                obj = json.loads(ln)
                comm_hard[int(obj["seed"])] = obj

    headline_checked = 0
    for h in manifest["mode_2_ai_duel"]["headline_seeds"]:
        s = int(h["seed"])
        t = str(h["tier"])
        if h.get("live_accuse_target_while_playing") != "[SEALED]":
            hard_leaks.append(f"headline_{t}_{s}_live_accuse_not_sealed")
        env = Env(t, s)
        if h.get("post_game_culprit_when_humanDone") != env._world.mole:
            hard_leaks.append(f"headline_{t}_{s}_culprit_mismatch")
        sol_ep = run_episode(Env(t, s), SolverPolicy())
        solver_checks += 1
        hs = h["solver"]
        if (
            abs(float(hs["score"]) - sol_ep.score) > 1e-9
            or int(hs["final_day"]) != sol_ep.final_day
            or int(hs["tool_calls"]) != len(sol_ep.steps)
            or bool(hs["correct"]) != sol_ep.correct
        ):
            hard_leaks.append(f"headline_{t}_{s}_solver_stats_mismatch")
        if s in comm_hard:
            gep = comm_hard[s]
            hg = h["gemini_4_carbon_opencode"]
            if (
                abs(float(hg["score"]) - float(gep["score"])) > 1e-9
                or int(hg["final_day"]) != int(gep["final_day"])
                or int(hg["tool_calls"]) != len(gep["steps"])
                or bool(hg["correct"]) != bool(gep["correct"])
            ):
                hard_leaks.append(f"headline_{t}_{s}_gemini_stats_mismatch")
        headline_checked += 1

    if comm_hard and 15 in comm_hard and "| Featured Hard | `hard` | `15` |" in md_source:
        ep15 = comm_hard[15]
        ok_ivs = sum(1 for st in ep15["steps"] if st["tool"] == "interview" and st["result"].get("ok"))
        all_ivs = sum(1 for st in ep15["steps"] if st["tool"] == "interview")
        if ok_ivs != all_ivs and f"`{all_ivs}` interviews" in md_source:
            issues.append({
                "id": "ISSUE-ARENA-ENGINE-SEEDS-DOC-REJECTED-INTERVIEW-COUNT",
                "severity": "advisory",
                "target_ref": ref_label,
                "locations": ["docs/arena/SEEDS.md:45"],
                "summary": (
                    f"SEEDS.md Featured Hard seed 15 table lists {all_ivs} interviews (all attempted interview calls, "
                    f"including 1 rejected call), whereas replay_engine.js summarizePublicStepCounts counts only "
                    f"ok=True interviews ({ok_ivs})."
                ),
            })

    return {
        "status": "PASS" if not hard_leaks else "FAIL",
        "ref": ref_label,
        "present": True,
        "schema_version": manifest.get("schema_version"),
        "curated_public_seeds_count": len(curated),
        "solver_rollouts_verified": solver_checks,
        "headline_seeds_verified": headline_checked,
        "pre_end_leaks": hard_leaks,
    }, issues


def audit_staffai_living_office_source(
    js_source: str,
    ref_label: str,
    quick: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    hard_leaks: list[str] = []

    prefix = "export const CANARY_LIVING_OFFICE_PACK = "
    if not js_source.startswith(prefix):
        return {
            "status": "FAIL",
            "ref": ref_label,
            "present": True,
            "pre_end_leaks": ["missing_canonical_export_prefix"],
        }, issues

    pack, _ = json.JSONDecoder().raw_decode(js_source, len(prefix))
    if pack.get("default_enabled") is not False or pack.get("off_by_default") is not True:
        hard_leaks.append("living_office_not_off_by_default")
    if pack.get("gateBPassed") is not False or pack.get("gate_b_passed") is not False:
        hard_leaks.append("living_office_gate_b_flag_not_false")

    prov = pack.get("provenance") or {}
    if prov.get("offline_only") is not True or int(prov.get("live_api_calls", -1)) != 0:
        hard_leaks.append("living_office_provenance_not_offline_zero_calls")

    hard_leaks.extend(_scan_pre_end_payload_leaks(pack, "CANARY_LIVING_OFFICE_PACK", human_done=False, mode="living"))

    episodes = pack.get("episodes") or {}
    days_scanned = 0
    solver_verified = 0
    for ep_key, ep in sorted(episodes.items()):
        seed = int(ep["seed"])
        if seed in rules.JUDGE_SEEDS or seed in rules.HELDOUT_SEEDS:
            hard_leaks.append(f"living_office_forbidden_benchmark_seed:{seed}")
        days = ep.get("days") or []
        days_scanned += len(days)
        live_env = Env("hard", seed)
        sr = ep.get("sealed_reveal") or {}
        if sr.get("mole") != live_env._world.mole or sr.get("decoy") != live_env._world.decoy:
            hard_leaks.append(f"{ep_key}:sealed_reveal_mole_or_decoy_mismatch")
        if not quick or seed == 6:
            sol = run_episode(Env("hard", seed), SolverPolicy())
            solver_verified += 1
            if (
                sr.get("solver_accused") != sol.accused
                or bool(sr.get("solver_correct")) != bool(sol.correct)
                or int(sr.get("solver_final_day", -1)) != sol.final_day
                or abs(float(sr.get("solver_score", -999.0)) - round(float(sol.score), 4)) > 1e-6
            ):
                hard_leaks.append(f"{ep_key}:sealed_reveal_solver_parity_mismatch")

    return {
        "status": "PASS" if not hard_leaks else "FAIL",
        "ref": ref_label,
        "present": True,
        "episodes_checked": len(episodes),
        "days_scanned": days_scanned,
        "solver_reveals_verified": solver_verified,
        "cache_prompts_hit": int(prov.get("cache_prompts_hit", 0)),
        "pre_end_leaks": hard_leaks,
    }, issues


def audit_cross_squad_refs(
    root: Path = ROOT,
    quick: bool = False,
    ref_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    results: dict[str, dict[str, Any]] = {}
    all_issues: list[dict[str, Any]] = []
    present_count = 0
    skipped_count = 0
    hard_failures = 0

    for key, default_ref, rel_path in CROSS_SQUAD_SPECS:
        ref = (ref_overrides or {}).get(key, default_ref)
        blob = _git_show_blob(root, ref, rel_path)
        if blob is None:
            skipped_count += 1
            results[key] = {
                "status": "SKIPPED_ABSENT_REF",
                "ref": ref,
                "path": rel_path,
                "present": False,
                "pre_end_leaks": [],
            }
            continue

        present_count += 1
        if key == "eval_arena":
            res, iss = audit_eval_scoring_parity_source(blob, f"{ref}:{rel_path}")
        elif key == "port_replay_engine":
            res, iss = audit_port_replay_engine_source(blob, f"{ref}:{rel_path}", root=root, quick=quick)
        elif key == "strategies_mole_mode":
            res, iss = audit_strategies_mole_mode_source(blob, f"{ref}:{rel_path}", quick=quick)
        elif key == "research_seeds_catalog":
            res, iss = audit_research_seeds_catalog_source(blob, f"{ref}:{rel_path}", root=root, quick=quick)
        elif key == "staffai_living_office":
            res, iss = audit_staffai_living_office_source(blob, f"{ref}:{rel_path}", quick=quick)
        else:
            raise ValueError(f"unknown cross-squad key {key}")

        results[key] = res
        all_issues.extend(iss)
        if res["status"] == "FAIL":
            hard_failures += 1

    return {
        "passed": hard_failures == 0,
        "targets_configured": len(CROSS_SQUAD_SPECS),
        "refs_present": present_count,
        "refs_skipped_absent": skipped_count,
        "hard_failures": hard_failures,
        "surfaces": results,
        "issues": all_issues,
        "elapsed_s": round(time.perf_counter() - t0, 4),
    }


def check_report_hygiene(report_path: Path) -> dict[str, Any]:
    if not report_path.is_file():
        return {"ok": False, "problems": [f"missing_report:{report_path}"]}
    txt = report_path.read_text(encoding="utf-8")
    low = txt.lower()
    problems: list[str] = []
    for ch, label in ((chr(0x2014), "em_dash"), (chr(0x2013), "en_dash"), (chr(0x2212), "unicode_minus")):
        if ch in txt:
            problems.append(label)
    for banned in ("pre-" + "reg", "pre" + "reg"):
        if banned in low:
            problems.append(f"banned_term:{banned}")
    co_author = "-".join(("Co", "Authored", "By")).lower()
    if co_author in low:
        problems.append("co_authored_by")
    for req in (
        "KNOWN_V_MODE",
        "1bc3e281",
        "900000-900039",
        "800000-800199",
        "ISSUE-ARENA-ENGINE-",
    ):
        if req not in txt:
            problems.append(f"missing_token:{req}")
    return {"ok": not problems, "problems": problems}


def run_all(
    root: Path = ROOT,
    quick: bool = False,
    rng_seed: int = 20261115,
    ref_overrides: dict[str, str] | None = None,
    out_json: Path | None = None,
) -> dict[str, Any]:
    world_logger = logging.getLogger("canary.world")
    solver_logger = logging.getLogger("canary.solver")
    prev_world_lvl = world_logger.level
    prev_solver_lvl = solver_logger.level
    world_logger.setLevel(logging.ERROR)
    solver_logger.setLevel(logging.ERROR)

    prev_secret = world._SET_SECRET
    salt_file = root / "data" / "worlds" / "judge" / "SALT"
    use_det_secret = prev_secret is None and not os.environ.get("CANARY_WORLD_SECRET") and not salt_file.exists()
    if use_det_secret:
        world.set_world_secret(DETERMINISTIC_AUDIT_SECRET)

    t0 = time.perf_counter()
    try:
        fuzz_res = fuzz_arena_env_and_game_parity(root=root, quick=quick, rng_seed=rng_seed)
        controls_res = run_planted_bug_controls()
        cross_res = audit_cross_squad_refs(root=root, quick=quick, ref_overrides=ref_overrides)
    finally:
        if use_det_secret:
            world.set_world_secret(prev_secret)
        world_logger.setLevel(prev_world_lvl)
        solver_logger.setLevel(prev_solver_lvl)

    all_passed = bool(fuzz_res["passed"] and controls_res["passed"] and cross_res["passed"])
    summary: dict[str, Any] = {
        "schema_version": "canary.integrity.arena_engine_parity.v1",
        "tiers_version": rules.TIERS_VERSION,
        "known_v_mode": rules.KNOWN_V_MODE,
        "quick": quick,
        "live_api_calls": 0,
        "all_passed": all_passed,
        "fuzz_parity": fuzz_res,
        "planted_controls": controls_res,
        "cross_squad": cross_res,
        "report_only_issues": cross_res["issues"],
        "elapsed_s": round(time.perf_counter() - t0, 4),
    }

    if out_json is not None:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="audit_arena_engine_parity")
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--rng", type=int, default=20261115)
    ap.add_argument("--simulate-missing-refs", action="store_true")
    ap.add_argument("--check-report", type=Path, default=None)
    ap.add_argument("--out-json", type=Path, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    overrides = (
        {k: f"refs/nonexistent/w4_absent_{k}" for k, _, _ in CROSS_SQUAD_SPECS}
        if args.simulate_missing_refs
        else None
    )
    summary = run_all(
        root=args.root.resolve(),
        quick=args.quick,
        rng_seed=args.rng,
        ref_overrides=overrides,
        out_json=args.out_json,
    )
    if args.check_report is not None:
        rep_chk = check_report_hygiene(args.check_report)
        summary["report_check"] = rep_chk
        summary["all_passed"] = bool(summary["all_passed"] and rep_chk["ok"])

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        fp = summary["fuzz_parity"]
        pc = summary["planted_controls"]
        cs = summary["cross_squad"]
        print(
            f"arena_engine_parity quick={summary['quick']} all_passed={summary['all_passed']} "
            f"states={fp['states_checked']} detail_checks={fp['detail_role_parity_checks']} "
            f"controls={pc['controls_caught']}/{pc['controls_total']} "
            f"cross_refs={cs['refs_present']}/{cs['targets_configured']} "
            f"issues={len(summary['report_only_issues'])} elapsed={summary['elapsed_s']}s"
        )
    return 0 if summary["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
