from __future__ import annotations

import importlib.util
import io
import json
import math
import re
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

LEGACY_NON_FROZEN_VERSIONS = frozenset({"v1.2"})

RETIRED_KEY_RESIGN_NOTICE = (
    "retired build ledger_key is public: HMAC verifies un-re-signed edits only "
    "and cannot rule out post-publication re-signing"
)

_OC_TRUNC_STRICT = re.compile(
    r"\A\s*\.\.\.(\d+) bytes truncated\.\.\.\s+The tool call succeeded but the output was "
    r"truncated\. Full output saved to: [^\n]+/tool-output/tool_[A-Za-z0-9_]+\n"
    r"Use Grep to search the full content or Read with offset/limit to view specific sections\.\s*\Z"
)

_BRACKET_TRUNC_SUFFIX = re.compile(r"\[\.\.\. truncated (\d+) bytes \.\.\.\]\Z")

_RERUN_SUFFIX = "-infra-rerun"


def classify_tiers_version(version: str, rules_mod: Any) -> str:
    if version in rules_mod.TIERS_HISTORY or version == rules_mod.TIERS_VERSION:
        return "replay"
    if version in LEGACY_NON_FROZEN_VERSIONS:
        return "historical_skip"
    return "forged"


def allows_opencode_quirks(episode: dict[str, Any], run_meta: dict[str, Any]) -> bool:
    prov = str(run_meta.get("provider") or "").strip()
    harness = str(run_meta.get("harness") or "").strip()
    agent = str(episode.get("agent") or run_meta.get("agent") or "").strip()
    emeta = episode.get("meta") if isinstance(episode.get("meta"), dict) else {}
    if prov == "opencode" or agent.startswith("opencode:") or "opencode" in harness:
        return True
    if prov or ":" in agent or emeta.get("api") or (harness and "opencode" not in harness):
        return False
    return True


def valid_client_only_step(
    step: dict[str, Any],
    episode: dict[str, Any],
    run_meta: dict[str, Any],
) -> bool:
    if not allows_opencode_quirks(episode, run_meta):
        return False
    res = step.get("result")
    if not isinstance(res, dict) or res.get("ok") is not False:
        return False
    err = res.get("error")
    return (
        isinstance(err, str)
        and err.startswith("Model tried to call unavailable tool")
        and "Available tools: canary_" in err
    )


def valid_bracket_truncated_suffix(recorded: str, full_text: str) -> bool:
    if not isinstance(recorded, str) or not isinstance(full_text, str):
        return False
    m = _BRACKET_TRUNC_SUFFIX.search(recorded)
    if not m:
        return False
    n_bytes = int(m.group(1))
    if n_bytes <= 0:
        return False
    prefix_bytes = recorded[: m.start()].encode("utf-8")
    full_bytes = full_text.encode("utf-8")
    if not full_bytes.startswith(prefix_bytes):
        return False
    return len(full_bytes) - len(prefix_bytes) == n_bytes


def valid_truncated_step(
    want: Any,
    got_payload: dict[str, Any],
    episode: dict[str, Any],
    run_meta: dict[str, Any],
) -> bool:
    if not (isinstance(want, dict) and set(want) == {"raw"} and isinstance(want.get("raw"), str)):
        return False
    raw = want["raw"]
    full_json = json.dumps(got_payload)
    if _BRACKET_TRUNC_SUFFIX.search(raw):
        return valid_bracket_truncated_suffix(raw, full_json)
    if not allows_opencode_quirks(episode, run_meta):
        return False
    m = _OC_TRUNC_STRICT.match(raw)
    if not m:
        return False
    return len(full_json.encode("utf-8")) == int(m.group(1))


def _is_valid_mcp_error_wrapper(
    want_raw: Any,
    want_norm: Any,
    episode: dict[str, Any] | None = None,
    run_meta: dict[str, Any] | None = None,
) -> bool:
    if want_norm is want_raw:
        return True
    if run_meta is not None and str(run_meta.get("harness") or "").strip().lower() == "inproc":
        return False
    return (
        isinstance(want_raw, dict)
        and set(want_raw) <= {"ok", "data", "error"}
        and want_raw.get("ok") is False
        and want_raw.get("data") in (None, {})
        and isinstance(want_raw.get("error"), str)
        and want_raw["error"].startswith("{")
    )


def _is_opencode_post_1bc_detail_step(
    want_raw: Any,
    want_norm: Any,
    r: Any,
    episode: dict[str, Any],
    run_meta: dict[str, Any],
) -> bool:
    if want_norm is want_raw or not allows_opencode_quirks(episode, run_meta):
        return False
    if not _is_valid_mcp_error_wrapper(want_raw, want_norm, episode, run_meta):
        return False
    if not (not r.ok and isinstance(r.data, dict) and set(r.data) == {"detail"}):
        return False
    return (
        isinstance(want_norm, dict)
        and set(want_norm) == {"ok", "data", "error"}
        and want_norm.get("ok") is False
        and isinstance(want_norm.get("data"), dict)
        and set(want_norm["data"]) == {"detail"}
    )


def check_companion_transcript(
    run_dir: Path,
    seed: int,
    episode: dict[str, Any],
    is_invalid: bool,
) -> list[str]:
    tdir = run_dir / "transcripts"
    if not tdir.is_dir():
        return []
    txt_path = tdir / f"{seed}.txt"
    json_path = tdir / f"{seed}.json"
    rec_calls = [
        (st.get("tool"), st.get("args"))
        for st in (episode.get("steps") or [])
        if isinstance(st, dict)
    ]
    if txt_path.is_symlink():
        return [f"companion transcript {seed}.txt is a symlink"]
    if txt_path.is_file():
        from ..agents.frontier.common import steps_from_events

        raw = txt_path.read_text(encoding="utf-8", errors="replace")
        if "--- stdout\n" in raw:
            stdout = raw.split("--- stdout\n", 1)[1].rsplit("\n--- stderr", 1)[0]
        else:
            stdout = raw
        tr_steps = steps_from_events(stdout)
        tr_calls = [(s.tool, s.args) for s in tr_steps]
        probs: list[str] = []
        if tr_calls != rec_calls:
            probs.append(
                f"companion transcript {seed}.txt steps ({len(tr_calls)}) != recorded steps ({len(rec_calls)})"
            )
        tr_accused = [
            (s.args or {}).get("employee")
            for s in tr_steps
            if s.tool == "accuse" and isinstance(s.result, dict) and s.result.get("ok") is True
        ]
        if tr_accused and episode.get("accused") != tr_accused[-1]:
            probs.append(
                f"companion transcript {seed}.txt accused {tr_accused[-1]!r}, episode says {episode.get('accused')!r}"
            )
        return probs
    if json_path.is_symlink():
        return [f"companion transcript {seed}.json is a symlink"]
    if json_path.is_file():
        try:
            msgs = json.loads(json_path.read_text(encoding="utf-8"))
        except ValueError:
            return [f"companion transcript {seed}.json is not valid JSON"]
        if not isinstance(msgs, list):
            return [f"companion transcript {seed}.json is not a message list"]
        tr_calls = [
            (tc.get("name"), tc.get("args"))
            for m in msgs
            if isinstance(m, dict) and m.get("role") == "assistant"
            for tc in (m.get("tool_calls") or [])
            if isinstance(tc, dict)
        ]
        acc_indices = [i for i, (nm, _) in enumerate(tr_calls) if nm == "accuse"]
        if acc_indices and len(rec_calls) == acc_indices[0] + 1:
            tr_effective = tr_calls[: acc_indices[0] + 1]
        else:
            tr_effective = tr_calls
        probs = []
        if tr_effective != rec_calls:
            probs.append(
                f"companion transcript {seed}.json steps ({len(tr_effective)}) != recorded steps ({len(rec_calls)})"
            )
        if acc_indices:
            acc_args = tr_calls[acc_indices[0]][1]
            emp = acc_args.get("employee") if isinstance(acc_args, dict) else None
            if emp is not None and episode.get("accused") != emp:
                probs.append(
                    f"companion transcript {seed}.json accused {emp!r}, episode says {episode.get('accused')!r}"
                )
        return probs
    if not is_invalid and any(p.stem.isdigit() for p in tdir.iterdir()):
        return [f"missing companion transcript for seed {seed}"]
    return []


def check_episode_tamper(
    episode: dict[str, Any],
    env: Any,
    run_dir: Path,
    run_meta: dict[str, Any],
) -> list[str]:
    probs: list[str] = []
    vrd = env.verdict()
    acc = vrd["accused"]
    emeta = episode.get("meta") if isinstance(episode.get("meta"), dict) else {}
    is_invalid = (emeta.get("valid") is False) or (episode.get("valid") is False)
    killed_note = str(emeta.get("note") or "").startswith("agent_killed_server:")
    stopped_note = (
        emeta.get("rc") == 0
        and episode.get("accused") is None
        and str(emeta.get("note") or "").startswith("agent stopped without ending the episode")
    )
    er = episode.get("end_reason")

    raw_score = episode.get("score")
    if not (
        isinstance(raw_score, (int, float))
        and not isinstance(raw_score, bool)
        and math.isfinite(float(raw_score))
    ):
        probs.append("non-finite recorded score")
        score_val = float("nan")
    else:
        score_val = float(raw_score)

    if is_invalid:
        if not (
            er == "error"
            and not env.done
            and acc is None
            and math.isfinite(score_val)
            and abs(score_val) <= 1e-9
        ):
            probs.append(
                f"invalid episode mismatch (end_reason={er!r}, done={env.done}, accused={acc!r})"
            )
    elif er == "horizon":
        if not (env.done and acc is None and vrd.get("end_reason") == "horizon"):
            probs.append(
                f"end_reason='horizon' mismatch (done={env.done}, env_end={vrd.get('end_reason')!r}, accused={acc!r})"
            )
    elif er == "accused":
        if not (env.done and acc is not None and vrd.get("end_reason") == "accused"):
            probs.append(
                f"end_reason='accused' mismatch (done={env.done}, env_end={vrd.get('end_reason')!r}, accused={acc!r})"
            )
    elif er == "tool_cap":
        if not (env.done and acc is None and vrd.get("end_reason") == "tool_cap"):
            probs.append(
                f"end_reason='tool_cap' mismatch (done={env.done}, env_end={vrd.get('end_reason')!r}, accused={acc!r})"
            )
    elif er == "error" and (killed_note or stopped_note):
        if not (not env.done and acc is None and math.isfinite(score_val) and abs(score_val) <= 1e-9):
            probs.append("agent_killed_server episode state mismatch")
    else:
        probs.append(f"unexpected end_reason={er!r} for replayed state {vrd.get('end_reason')!r}")

    if not is_invalid and env.done and "final_day" in episode:
        fd = episode.get("final_day")
        if not isinstance(fd, int) or isinstance(fd, bool) or int(fd) != int(vrd["final_day"]):
            probs.append(f"final_day={fd!r} != replayed {vrd['final_day']!r}")

    if "correct" in episode:
        corr = episode.get("correct")
        if not isinstance(corr, bool) or bool(corr) != bool(vrd["correct"]):
            probs.append(f"correct={corr!r} != replayed {bool(vrd['correct'])!r}")

    if isinstance(emeta.get("ledger_events"), list):
        acc_evs = [
            ev
            for ev in emeta["ledger_events"]
            if isinstance(ev, dict) and ev.get("event") == "accused"
        ]
        ev_emp = (acc_evs[-1].get("detail") or {}).get("employee") if acc_evs else None
        if len(acc_evs) > 1 or ev_emp != acc:
            probs.append(f"meta.ledger_events accused={ev_emp!r} != replayed {acc!r}")

    for v_key in ("V_final", "V"):
        if v_key in emeta and emeta[v_key] is not None:
            vv = emeta[v_key]
            if not isinstance(vv, (int, float)) or isinstance(vv, bool) or not math.isfinite(float(vv)):
                probs.append(f"meta.{v_key} non-finite")
            elif abs(float(vv) - float(vrd["V"])) > 1e-6:
                probs.append(f"meta.{v_key}={vv!r} != replayed V={vrd['V']!r}")

    probs.extend(check_companion_transcript(run_dir, int(episode["seed"]), episode, is_invalid))
    return probs


def replay_committed(root: Path = ROOT) -> list[dict[str, Any]]:
    from .. import rules
    from ..env import Env
    from ..reproduce import committed_files, run_meta, run_tiers_version
    from . import anticheat as ac

    base_rows = ac.replay_committed(root)
    base_by_file = {r["file"]: r for r in base_rows}
    secret_seeds = set(rules.JUDGE_SEEDS) | set(getattr(rules, "HELDOUT_SEEDS", ()))
    out: list[dict[str, Any]] = []

    for f in committed_files(root):
        rel = f.relative_to(root).as_posix()
        base = base_by_file.get(rel, {})
        base_mism_by_seed = {
            int(m["seed"]): dict(m)
            for m in (base.get("mismatches") or [])
            if isinstance(m, dict) and "seed" in m
        }
        meta = run_meta(f.parent)
        version = run_tiers_version(f.parent, root, meta)
        row: dict[str, Any] = {
            "file": rel,
            "tiers_version": version,
            "n": 0,
            "replayed": 0,
            "consistent": 0,
            "not_replayable": 0,
            "mismatches": [],
        }
        discounted_base_seeds: set[int] = set()

        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            row["n"] += 1
            seed, tier = int(e["seed"]), e["tier"]
            if seed in secret_seeds:
                row["not_replayable"] += 1
                continue
            ver_status = classify_tiers_version(version, rules)
            if ver_status == "historical_skip":
                row["not_replayable"] += 1
                row.setdefault("why", f"tier params for {version} are not frozen in rules.TIERS_HISTORY")
                continue
            if ver_status == "forged":
                row["mismatches"].append(
                    {
                        "seed": seed,
                        "recorded": e.get("score"),
                        "replayed": None,
                        "accused_recorded": e.get("accused"),
                        "accused_replayed": None,
                        "step_mismatches": 0,
                        "first_bad_step": None,
                        "tamper": [f"unknown tiers_version: {version}"],
                    }
                )
                continue

            step_bad, first_bad, n_trunc, n_client, n_oc_post_1bc_detail = 0, None, 0, 0, 0
            with rules.tiers_version(version):
                env = Env(tier, seed)
                for i, st in enumerate(e.get("steps", [])):
                    if ac._client_only_step(st):
                        if valid_client_only_step(st, e, meta):
                            n_client += 1
                        else:
                            step_bad += 1
                            first_bad = i if first_bad is None else first_bad
                        continue
                    r = env.call(st["tool"], st["args"])
                    got_payload = {"ok": r.ok, "data": r.data, "error": r.error}
                    want_raw = st.get("result")
                    want_norm = ac._norm_result(want_raw)
                    if (
                        not r.ok
                        and isinstance(r.data, dict)
                        and set(r.data) == {"detail"}
                        and not (
                            isinstance(want_norm, dict)
                            and isinstance(want_norm.get("data"), dict)
                            and "detail" in want_norm["data"]
                        )
                    ):
                        got_payload = {"ok": r.ok, "data": {}, "error": r.error}
                    is_bracket_trunc = (
                        isinstance(want_raw, dict)
                        and set(want_raw) == {"raw"}
                        and isinstance(want_raw.get("raw"), str)
                        and bool(_BRACKET_TRUNC_SUFFIX.search(want_raw["raw"]))
                    )
                    trunc = ac._client_truncated_bytes(want_raw)
                    if trunc is not None or is_bracket_trunc:
                        n_trunc += 1
                        ok = valid_truncated_step(want_raw, got_payload, e, meta)
                    else:
                        ok = (
                            want_norm is not None
                            and _is_valid_mcp_error_wrapper(want_raw, want_norm, e, meta)
                            and ac._canon(got_payload) == ac._canon(want_norm)
                        )
                        if ok and _is_opencode_post_1bc_detail_step(want_raw, want_norm, r, e, meta):
                            n_oc_post_1bc_detail += 1
                    if not ok:
                        step_bad += 1
                        first_bad = i if first_bad is None else first_bad
                got, acc = env.score(), env.verdict()["accused"]
                tamper_probs = check_episode_tamper(e, env, f.parent, meta)

            row["replayed"] += 1
            row["steps"] = row.get("steps", 0) + len(e.get("steps", []))
            row["step_mismatches"] = row.get("step_mismatches", 0) + step_bad
            if n_trunc or n_client:
                row["steps_truncated_checked"] = row.get("steps_truncated_checked", 0) + n_trunc
                row["steps_client_only"] = row.get("steps_client_only", 0) + n_client

            score_raw = e.get("score")
            score_ok = (
                isinstance(score_raw, (int, float))
                and not isinstance(score_raw, bool)
                and math.isfinite(float(score_raw))
                and abs(got - float(score_raw)) < 1e-6
            )
            upstream_mism = base_mism_by_seed.get(seed)
            discount_upstream = (
                upstream_mism is not None
                and step_bad == 0
                and score_ok
                and acc == e.get("accused")
                and not tamper_probs
                and n_oc_post_1bc_detail > 0
                and int(upstream_mism.get("step_mismatches") or 0) == n_oc_post_1bc_detail
            )
            if discount_upstream:
                discounted_base_seeds.add(seed)
                base_mism_by_seed.pop(seed, None)
            upstream_failed = seed in base_mism_by_seed
            if score_ok and acc == e.get("accused") and not step_bad and not tamper_probs and not upstream_failed:
                row["consistent"] += 1
            else:
                mism = base_mism_by_seed.get(
                    seed,
                    {
                        "seed": seed,
                        "recorded": e.get("score"),
                        "replayed": got,
                        "accused_recorded": e.get("accused"),
                        "accused_replayed": acc,
                        "step_mismatches": step_bad,
                        "first_bad_step": first_bad,
                    },
                )
                if step_bad > int(mism.get("step_mismatches") or 0):
                    mism["step_mismatches"] = step_bad
                    mism["first_bad_step"] = first_bad
                if tamper_probs:
                    mism["tamper"] = tamper_probs
                row["mismatches"].append(mism)

        rem_base_mism = [
            m
            for m in (base.get("mismatches") or [])
            if not (isinstance(m, dict) and "seed" in m and int(m["seed"]) in discounted_base_seeds)
        ]
        base_failed = (base.get("replay_consistent") is False) and bool(
            rem_base_mism or not (base.get("mismatches") and discounted_base_seeds)
        )
        if base_failed and not row["mismatches"]:
            row["mismatches"] = list(rem_base_mism or [{"tamper": ["upstream anticheat mismatch"]}])
        row["replay_consistent"] = False if row["mismatches"] else (None if row["replayed"] == 0 else True)
        out.append(row)
    return out


def _load_json_no_dup_keys(path: Path) -> tuple[Any, bool, bool]:
    dup = False

    def _hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        nonlocal dup
        keys = [k for k, _ in pairs]
        if len(keys) != len(set(keys)):
            dup = True
        return dict(pairs)

    try:
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_hook)
    except (OSError, ValueError):
        return None, False, False
    return data, True, dup


def _check_harbor_agent_logs(trial: Path, ledger_accused: Any) -> list[str]:
    probs: list[str] = []
    for rel in ("agent/solver.txt", "agent/oracle.txt"):
        p = trial / rel
        if p.is_symlink() or not p.is_file():
            continue
        txt = p.read_text(encoding="utf-8", errors="replace")
        matches = re.findall(r"accuse -> (\{[^\n]+\})", txt)
        if matches:
            try:
                obj = json.loads(matches[-1])
            except ValueError:
                obj = {}
            if isinstance(obj, dict) and obj.get("ok") is True:
                emp = (obj.get("data") or {}).get("accused")
                if emp != ledger_accused:
                    probs.append(f"{rel} accused {emp!r}, ledger says {ledger_accused!r}")

    oc_path = trial / "agent/opencode.txt"
    if not oc_path.is_symlink() and oc_path.is_file():
        oc_accs: list[Any] = []
        for ln in oc_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not ln.startswith("{"):
                continue
            try:
                ev = json.loads(ln)
            except ValueError:
                continue
            part = ev.get("part") if isinstance(ev, dict) else None
            if (
                isinstance(part, dict)
                and part.get("type") == "tool"
                and str(part.get("tool") or "").endswith("accuse")
            ):
                state = part.get("state") or {}
                if state.get("status") == "completed":
                    try:
                        out = json.loads(state.get("output") or "{}")
                    except ValueError:
                        out = {}
                    if isinstance(out, dict) and out.get("ok") is True:
                        oc_accs.append((state.get("input") or {}).get("employee"))
        if oc_accs and oc_accs[-1] != ledger_accused:
            probs.append(f"agent/opencode.txt accused {oc_accs[-1]!r}, ledger says {ledger_accused!r}")
        if not oc_accs and ledger_accused is not None:
            probs.append(
                f"ledger has an accusation ({ledger_accused!r}) not present in agent/opencode.txt"
            )
    return probs


def _check_verifier_stdout_fields(trial: Path, ledger: dict[str, Any]) -> list[str]:
    stdout_path = trial / "verifier/test-stdout.txt"
    if stdout_path.is_symlink() or not stdout_path.is_file():
        return []
    txt = stdout_path.read_text(encoding="utf-8", errors="replace")
    probs: list[str] = []
    m_done = re.search(r"\bdone=(True|False)\b", txt)
    if m_done and "done" in ledger:
        want_done = m_done.group(1) == "True"
        if bool(ledger.get("done")) != want_done:
            probs.append(f"verifier/test-stdout.txt done={want_done}, ledger says {ledger.get('done')!r}")
    m_end = re.search(r"\bend_reason=([A-Za-z_]+)\b", txt)
    if m_end and "end_reason" in ledger:
        want_end = None if m_end.group(1) == "None" else m_end.group(1)
        if ledger.get("end_reason") != want_end:
            probs.append(
                f"verifier/test-stdout.txt end_reason={want_end!r}, ledger says {ledger.get('end_reason')!r}"
            )
    m_day = re.search(r"\bfinal_day=(-?\d+)\b", txt)
    if m_day and ledger.get("final_day") is not None:
        if int(m_day.group(1)) != int(ledger["final_day"]):
            probs.append(
                f"verifier/test-stdout.txt final_day={int(m_day.group(1))}, ledger says {ledger.get('final_day')!r}"
            )
    return probs


def check_harbor_tamper(trial: Path, reward: float | None, policy: str | None) -> list[str]:
    probs: list[str] = []
    checked_paths = (
        "result.json",
        "config.json",
        "verifier/reward.txt",
        "verifier/reward.json",
        "verifier/test-stdout.txt",
        "artifacts/ledger.json",
        "verifier/ledger.json",
        "agent/cheat.json",
        "agent/isolation.txt",
        "agent/trajectory.json",
        "agent/opencode.txt",
        "agent/oracle.txt",
        "agent/solver.txt",
    )
    for rel in checked_paths:
        p = trial / rel
        if p.is_symlink():
            probs.append(f"{rel} is a symlink")

    cfg_path = trial / "config.json"
    if not cfg_path.is_symlink():
        if not cfg_path.is_file():
            probs.append("config.json is missing")
        else:
            _, ok_cfg, dup_cfg = _load_json_no_dup_keys(cfg_path)
            if not ok_cfg:
                probs.append("config.json is unreadable or not JSON")
            elif dup_cfg:
                probs.append("config.json contains duplicate JSON keys")

    json_artifacts = (
        "result.json",
        "verifier/reward.json",
        "artifacts/ledger.json",
        "verifier/ledger.json",
        "agent/cheat.json",
    )
    for rel in json_artifacts:
        p = trial / rel
        if not p.is_symlink() and p.is_file():
            _, ok_js, dup_js = _load_json_no_dup_keys(p)
            if ok_js and dup_js:
                probs.append(f"{rel} contains duplicate JSON keys")

    if reward is None:
        for rel in ("artifacts/ledger.json", "verifier/ledger.json"):
            p = trial / rel
            if p.is_symlink() or not p.is_file():
                continue
            d, ok_led, _ = _load_json_no_dup_keys(p)
            if not ok_led or not isinstance(d, dict):
                probs.append(f"{rel} is not a JSON object on null-reward trial")
                continue
            acc_evs = [
                ev
                for ev in (d.get("ledger") or [])
                if isinstance(ev, dict) and ev.get("event") == "accused"
            ]
            raw_sc = d.get("score")
            sc_ok = (
                raw_sc is None
                or (
                    isinstance(raw_sc, (int, float))
                    and not isinstance(raw_sc, bool)
                    and math.isfinite(float(raw_sc))
                    and abs(float(raw_sc)) <= 1e-9
                )
            )
            if d.get("accused") is not None or acc_evs or not sc_ok:
                probs.append(
                    f"{rel} has accusation or non-zero score ({raw_sc!r}) while verifier reward is None"
                )
    else:
        if policy is not None and policy != "opencode":
            iso = trial / "agent/isolation.txt"
            if not iso.is_file():
                probs.append("agent/isolation.txt is missing for non-opencode trial")
        led_path = trial / "artifacts/ledger.json"
        if not led_path.is_symlink() and led_path.is_file():
            led_data, ok_led, _ = _load_json_no_dup_keys(led_path)
            if ok_led and isinstance(led_data, dict):
                probs.extend(_check_harbor_agent_logs(trial, led_data.get("accused")))
                probs.extend(_check_verifier_stdout_fields(trial, led_data))

    return probs


def check_harbor_trial(trial: Path) -> dict[str, Any]:
    from . import anticheat as ac

    if (trial / "result.json").is_symlink():
        return {
            "trial": trial.as_posix(),
            "kind": "trial",
            "reward": None,
            "consistent": False,
            "problems": ["result.json is a symlink"],
            "trajectory_checked": False,
            "exception": False,
        }

    row = dict(ac.check_harbor_trial(trial))
    row["problems"] = list(row.get("problems") or [])
    policy = row.get("policy") or ac._trial_policy(trial)
    row["problems"].extend(check_harbor_tamper(trial, row.get("reward"), policy))

    key_file = trial.parent / "ledger_key"
    if key_file.is_symlink():
        row["problems"].append("ledger_key is a symlink")
    elif key_file.is_file():
        row["retired_key_published"] = True
        if row.get("hmac_verified") is True:
            row["retired_key_resign_notice"] = RETIRED_KEY_RESIGN_NOTICE

    if row["problems"]:
        row["consistent"] = False
    return row


def _has_opencode_cli_error(trial: Path) -> bool:
    oc_path = trial / "agent/opencode.txt"
    if oc_path.is_symlink() or not oc_path.is_file():
        return False
    for line in oc_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if '"type":"error"' in line.replace(" ", ""):
            return True
    return False


def _trial_task_meta(trial: Path) -> dict[str, Any]:
    res_data, ok_res, _ = _load_json_no_dup_keys(trial / "result.json")
    if not ok_res or not isinstance(res_data, dict):
        return {}
    task_name = str(res_data.get("task_name") or trial.name).split("/")[-1]
    checksum = res_data.get("task_checksum")
    rew = ((res_data.get("verifier_result") or {}).get("rewards") or {}).get("reward")
    exc = res_data.get("exception_info")
    exc_t = exc.get("exception_type") if isinstance(exc, dict) else (str(exc)[:60] if exc else None)
    led_data, ok_led, _ = _load_json_no_dup_keys(trial / "artifacts/ledger.json")
    done = bool(led_data.get("done")) if (ok_led and isinstance(led_data, dict)) else False
    is_infra = (not done) and (
        exc_t in {"ApiRateLimitError", "AgentSetupTimeoutError"}
        or _has_opencode_cli_error(trial)
        or rew is None
    )
    return {
        "task": task_name,
        "task_checksum": checksum,
        "done": done,
        "reward": rew,
        "exc_type": exc_t,
        "is_infra": is_infra,
    }


def _check_rerun_job_pair(rerun_job: Path) -> list[str]:
    probs: list[str] = []
    if not rerun_job.name.endswith(_RERUN_SUFFIX):
        return probs
    base_name = rerun_job.name[: -len(_RERUN_SUFFIX)]
    base_job = rerun_job.parent / base_name
    if not base_job.is_dir() or not (base_job / "result.json").is_file():
        return [f"rerun job {rerun_job.name} has no sibling base job {base_name}"]

    rerun_key = rerun_job / "ledger_key"
    base_key = base_job / "ledger_key"
    if rerun_key.is_file() or base_key.is_file():
        if not (rerun_key.is_file() and base_key.is_file()):
            probs.append(f"ledger_key mismatch between {base_name} and {rerun_job.name}")
        elif rerun_key.read_text(encoding="utf-8").strip() != base_key.read_text(encoding="utf-8").strip():
            probs.append(f"ledger_key differs between {base_name} and {rerun_job.name}")

    base_tasks: dict[str, dict[str, Any]] = {}
    for rf in sorted(base_job.glob("*/result.json")):
        meta = _trial_task_meta(rf.parent)
        if not meta:
            continue
        t = meta["task"]
        if t in base_tasks:
            probs.append(f"duplicate task {t} inside base job {base_name}")
        base_tasks[t] = meta

    seen_rerun: set[str] = set()
    for rf in sorted(rerun_job.glob("*/result.json")):
        meta = _trial_task_meta(rf.parent)
        if not meta:
            continue
        t = meta["task"]
        if t in seen_rerun:
            probs.append(f"duplicate task {t} inside rerun job {rerun_job.name}")
        seen_rerun.add(t)
        if t not in base_tasks:
            probs.append(f"rerun task {t} in {rerun_job.name} does not exist in {base_name}")
            continue
        bmeta = base_tasks[t]
        if bmeta["done"] or not bmeta["is_infra"]:
            probs.append(
                f"rerun task {t} in {rerun_job.name} replaces non-infra trial in {base_name} (done={bmeta['done']})"
            )
        if (
            meta.get("task_checksum")
            and bmeta.get("task_checksum")
            and meta["task_checksum"] != bmeta["task_checksum"]
        ):
            probs.append(f"task_checksum mismatch on {t} between {base_name} and {rerun_job.name}")
    return probs


def harbor_consistency(root: Path = ROOT) -> list[dict[str, Any]]:
    from . import anticheat as ac

    base = root / "results" / "harbor"
    if not base.is_dir():
        return []
    ac_rows = ac.harbor_consistency(root)
    ac_by_id = {r["trial"]: r for r in ac_rows}
    rows: list[dict[str, Any]] = []

    for job_res in sorted([*base.glob("*/result.json"), *base.glob("*/*/result.json")]):
        if not list(job_res.parent.glob("*/result.json")):
            continue
        if (job_res.parent / "config.json").exists() and (job_res.parent / "agent").is_dir():
            continue
        job = job_res.parent
        trows: list[dict[str, Any]] = []
        seen_tasks: set[str] = set()
        dup_task_probs: list[str] = []

        for res_p in sorted(job.glob("*/result.json")):
            r = check_harbor_trial(res_p.parent)
            rel_trial = res_p.parent.relative_to(root).as_posix()
            r["trial"] = rel_trial
            trows.append(r)
            tmeta = _trial_task_meta(res_p.parent)
            tname = tmeta.get("task")
            if tname:
                if tname in seen_tasks:
                    dup_task_probs.append(f"duplicate task {tname} in job {job.name}")
                seen_tasks.add(tname)

        job_id = job.relative_to(root).as_posix() + "/ (job)"
        base_jrow = dict(ac_by_id.get(job_id) or ac.check_harbor_job(job, trows))
        jprobs = list(base_jrow.get("problems") or [])

        fresh_jrow = ac.check_harbor_job(job, trows)
        for p in fresh_jrow.get("problems") or []:
            if p not in jprobs:
                jprobs.append(p)

        if job_res.is_symlink():
            jprobs.append("job result.json is a symlink")
        else:
            _, ok_jr, dup_jr = _load_json_no_dup_keys(job_res)
            if ok_jr and dup_jr:
                jprobs.append("job result.json contains duplicate JSON keys")

        jprobs.extend(dup_task_probs)
        jprobs.extend(_check_rerun_job_pair(job))

        bad_children = [t["trial"] for t in trows if t["consistent"] is False]
        if bad_children:
            jprobs.append(f"{len(bad_children)} inconsistent trial(s) in job")

        resign_count = sum(1 for t in trows if t.get("retired_key_resign_notice"))
        base_jrow["trial"] = job_id
        base_jrow["problems"] = jprobs
        base_jrow["consistent"] = not jprobs
        if resign_count:
            base_jrow["retired_key_resign_notices"] = resign_count
            base_jrow["retired_key_resign_notice"] = RETIRED_KEY_RESIGN_NOTICE

        rows.extend(trows)
        rows.append(base_jrow)

    return rows


def _load_rehearsal_table_module(repo_root: Path) -> Any:
    script_path = repo_root / "scripts" / "rehearsal_table.py"
    spec = importlib.util.spec_from_file_location("rehearsal_table", script_path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def verify_rehearsal_run(rehearsal_dir: Path, repo_root: Path = ROOT) -> dict[str, Any]:
    problems: list[str] = []
    if not rehearsal_dir.is_dir():
        return {"passed": False, "problems": [f"{rehearsal_dir} is not a directory"]}

    try:
        rel_prefix = rehearsal_dir.resolve().relative_to(repo_root.resolve()).as_posix() + "/"
        hb_root = repo_root
    except ValueError:
        hb_root = rehearsal_dir.parent.parent
        rel_prefix = rehearsal_dir.relative_to(hb_root).as_posix() + "/"

    all_hb = harbor_consistency(hb_root)
    sub_rows = [r for r in all_hb if str(r.get("trial") or "").startswith(rel_prefix)]
    trial_rows = [r for r in sub_rows if r.get("kind") == "trial"]
    job_rows = [r for r in sub_rows if r.get("kind") == "job"]

    if not job_rows or not trial_rows:
        problems.append("no Harbor jobs or trials discovered in rehearsal directory")

    bad_rows = [r for r in sub_rows if r.get("consistent") is False]
    for br in bad_rows:
        problems.append(f"inconsistent {br.get('kind')}: {br['trial']}: {br.get('problems')}")

    job_dirs = sorted(
        p for p in rehearsal_dir.iterdir() if p.is_dir() and (p / "result.json").is_file()
    )
    job_names = [p.name for p in job_dirs]
    for req in ("oracle", "do_nothing", "stop_early"):
        if req not in job_names:
            problems.append(f"missing required baseline job {req}")
    if not any(n.startswith("opencode") and not n.endswith(_RERUN_SUFFIX) for n in job_names):
        problems.append("missing opencode run job")

    published_keys: dict[str, str] = {}
    for jd in job_dirs:
        kf = jd / "ledger_key"
        if kf.is_symlink():
            problems.append(f"{jd.name}/ledger_key is a symlink")
        elif kf.is_file():
            published_keys[jd.name] = kf.read_text(encoding="utf-8").strip()
        else:
            problems.append(f"{jd.name}/ledger_key is missing")

    unique_keys = sorted(set(published_keys.values()))
    if len(unique_keys) != 1:
        problems.append(f"expected 1 shared retired ledger_key across jobs, found {len(unique_keys)}")

    checksums_by_task: dict[str, set[str]] = {}
    for jd in job_dirs:
        for rf in sorted(jd.glob("*/result.json")):
            tmeta = _trial_task_meta(rf.parent)
            if tmeta.get("task") and tmeta.get("task_checksum"):
                checksums_by_task.setdefault(tmeta["task"], set()).add(str(tmeta["task_checksum"]))
    for task_id, cset in sorted(checksums_by_task.items()):
        if len(cset) != 1:
            problems.append(f"task_checksum mismatch across jobs for {task_id}: {sorted(cset)}")

    for zero_job in ("do_nothing", "stop_early"):
        zdir = rehearsal_dir / zero_job
        if zdir.is_dir():
            for rf in sorted(zdir.glob("*/result.json")):
                led_d, ok_l, _ = _load_json_no_dup_keys(rf.parent / "artifacts/ledger.json")
                if not ok_l or not isinstance(led_d, dict):
                    problems.append(f"{zero_job}/{rf.parent.name}: missing ledger.json")
                    continue
                if led_d.get("accused") is not None or abs(float(led_d.get("score") or 0.0)) > 1e-9:
                    problems.append(
                        f"{zero_job}/{rf.parent.name}: expected score=0 and accused=None, got score={led_d.get('score')!r}, accused={led_d.get('accused')!r}"
                    )

    table_match: bool | None = None
    job_means: dict[str, float] = {}
    rt_mod = _load_rehearsal_table_module(repo_root)
    if rt_mod is not None:
        loaded_jobs = rt_mod.load(rehearsal_dir)
        for jname, jtasks in sorted(loaded_jobs.items()):
            valid_rewards = [x["reward"] for x in jtasks.values() if rt_mod.valid(x)]
            if valid_rewards:
                job_means[jname] = round(sum(valid_rewards) / len(valid_rewards), 6)
        table_path = rehearsal_dir / "TABLE.md"
        if table_path.is_file():
            buf = io.StringIO()
            with redirect_stdout(buf):
                rt_mod.main([str(rehearsal_dir)])
            recomputed = buf.getvalue().rstrip("\n") + "\n"
            committed_table = table_path.read_text(encoding="utf-8").rstrip("\n") + "\n"
            table_match = recomputed == committed_table
            if not table_match:
                problems.append("TABLE.md does not match recomputed scripts/rehearsal_table.py output")

    resign_notices = sum(1 for r in trial_rows if r.get("retired_key_resign_notice"))
    return {
        "passed": len(problems) == 0,
        "rehearsal_dir": rehearsal_dir.as_posix(),
        "jobs": job_names,
        "n_jobs": len(job_rows),
        "n_trials": len(trial_rows),
        "n_consistent_trials": sum(1 for r in trial_rows if r.get("consistent") is True),
        "n_hmac_verified": sum(1 for r in trial_rows if r.get("hmac_verified") is True),
        "n_trajectory_checked": sum(1 for r in trial_rows if r.get("trajectory_checked") is True),
        "n_retired_key_resign_notices": resign_notices,
        "retired_key_resign_notice": RETIRED_KEY_RESIGN_NOTICE if resign_notices else None,
        "shared_retired_key_count": len(unique_keys),
        "n_distinct_tasks": len(checksums_by_task),
        "job_means": job_means,
        "table_md_matches": table_match,
        "problems": problems,
    }
