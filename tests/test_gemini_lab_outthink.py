from __future__ import annotations

import ast
import copy
import gzip
import io
import json
import os
import shutil
import subprocess
import sys
import tokenize
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

import pytest

from canary.env import _SPECS as ENV_TOOL_SPECS
from canary.env import Env
from canary.gemini import outthink
from canary.rules import tier_params_for_episode
from canary.solver.policy import SolverPolicy
from canary.types import Step
from canary.world import HELDOUT_SEEDS, JUDGE_SEEDS

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "canary" / "gemini" / "outthink.py"
JSON_PATH = ROOT / "results" / "gemini" / "out_think_gemini.json"
CASES_JS_PATH = ROOT / "demo" / "out-think-gemini" / "cases.js"
LEDGER_GZ = ROOT / "results" / "gemini" / "ladder_ledger.jsonl.gz"
PROTECTED_PATHS_FILE = ROOT / ".github" / "protected-paths.txt"

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
HASH_CHAR = chr(35)
FORBIDDEN_NET = "fetch" + "("
SLASH = chr(47)
STAR = chr(42)
LINE_COMMENT = SLASH + SLASH
BLOCK_COMMENT_OPEN = SLASH + STAR


def _resolve_js_cmd() -> tuple[list[str], dict[str, str]]:
    clean_env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"}
    }
    for binary in ("node", "nodejs", "bun"):
        found = shutil.which(binary)
        if found:
            return [found, "-e"], clean_env
    for cand in (
        shutil.which("opencode"),
        str(Path.home() / "momin" / "bin" / "opencode"),
        str(Path.home() / ".opencode" / "bin" / "opencode"),
        str(Path.home() / ".local" / "bin" / "opencode"),
    ):
        if cand and Path(cand).is_file() and os.access(cand, os.X_OK):
            bun_env = dict(clean_env)
            bun_env["BUN_BE_BUN"] = "1"
            return [cand, "-e"], bun_env
    pytest.skip("no JavaScript runtime available")


def _find_js_comments(source: str) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    n = len(source)
    i = 0
    line = 1
    in_quote: str | None = None
    while i < n:
        ch = source[i]
        if in_quote is not None:
            if ch == "\\":
                if i + 1 < n and source[i + 1] == "\n":
                    line += 1
                i += 2
                continue
            if ch == "\n":
                line += 1
            elif ch == in_quote:
                in_quote = None
            i += 1
            continue
        if ch in ("'", '"', "`"):
            in_quote = ch
            i += 1
            continue
        if ch == "\n":
            line += 1
            i += 1
            continue
        if ch == SLASH and i + 1 < n:
            nxt = source[i + 1]
            if nxt == SLASH:
                hits.append((line, LINE_COMMENT))
                i += 2
                while i < n and source[i] != "\n":
                    i += 1
                continue
            if nxt == STAR:
                hits.append((line, BLOCK_COMMENT_OPEN))
                i += 2
                while i < n:
                    if source[i] == "\n":
                        line += 1
                    if source[i] == STAR and i + 1 < n and source[i + 1] == SLASH:
                        i += 2
                        break
                    i += 1
                continue
        i += 1
    return hits


def test_outthink_cli_check_and_artifacts_in_sync(capsys):
    assert JSON_PATH.is_file()
    assert CASES_JS_PATH.is_file()
    rc = outthink.main(["--check"])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert "OK:" in captured.out


def test_json_and_cases_js_runtime_parity():
    payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    js_txt = CASES_JS_PATH.read_text(encoding="utf-8")
    assert "window.OUTTHINK_DATA =" in js_txt

    cmd_prefix, env = _resolve_js_cmd()
    run_env = dict(env)
    run_env["CASES_JS_PATH"] = str(CASES_JS_PATH)
    script = (
        "globalThis.window = {};\n"
        "const exported = require(process.env.CASES_JS_PATH);\n"
        "process.stdout.write(JSON.stringify({\n"
        "  sameRef: globalThis.window.OUTTHINK_DATA === exported,\n"
        "  isBootstrap: Boolean(exported.meta && exported.meta.isBootstrapFallback),\n"
        "  count: Array.isArray(exported.cases) ? exported.cases.length : -1,\n"
        "  ids: (exported.cases || []).map(c => c.id)\n"
        "}));\n"
    )
    proc = subprocess.run(
        [*cmd_prefix, script],
        cwd=ROOT,
        env=run_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    js_summary = json.loads(proc.stdout)
    assert js_summary["sameRef"] is True
    assert js_summary["isBootstrap"] is False
    assert js_summary["count"] == len(payload["cases"]) == 12
    assert js_summary["ids"] == [c["id"] for c in payload["cases"]]


def test_cases_schema_bayesian_posteriors_and_ledger_provenance():
    payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    meta = payload["meta"]
    cases = payload["cases"]

    assert meta["tiers_version"] == "v1.4"
    assert meta["isBootstrapFallback"] is False
    assert meta["total_episodes"] == 550
    assert meta["total_cost_usd"] > 50.0
    assert meta["case_count"] == len(cases) == 12
    assert set(meta["thinking_levels"]) == {"minimal", "low", "medium", "high", "xhigh"}
    assert set(meta["models"]) == {
        "gemini-3.1-flash-lite",
        "gemini-3.5-flash",
        "gemini-3.8-flash",
        "gemini-4-hydrogen",
        "gemini-4-argon",
        "gemini-4-carbon",
    }

    ledger_run_ids: set[str] = set()
    with gzip.open(LEDGER_GZ, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rid = json.loads(line).get("run_id")
                if rid:
                    ledger_run_ids.add(str(rid))

    tiers_seen: set[str] = set()
    calls_seen: set[str] = set()
    levels_seen: set[str] = set()

    for c in cases:
        tiers_seen.add(c["tier"])
        assert c["tier"] in {"medium", "hard"}
        assert isinstance(c["seed"], int)
        assert c["company"]
        assert c["decision_day"] >= 1
        assert c["decision_step"] == len(c["tool_steps"]) > 0
        assert 0.0 < c["value_at_decision"] <= 1.0

        env = Env(c["tier"], c["seed"])
        assert c["true_mole"] == env._world.mole

        suspect_ids = [s["id"] for s in c["suspects"]]
        assert len(suspect_ids) == len(set(suspect_ids)) == len(env._ids)
        assert c["true_mole"] in suspect_ids
        for s in c["suspects"]:
            assert s["name"] and s["dept"] and s["role"]
            assert isinstance(s["eliminated"], bool)
            assert isinstance(s["canary_hits"], int)
            assert isinstance(s["after_hours_count"], int)
            assert s["persona_note"]

        for lk in c["leaks"]:
            assert isinstance(lk["day"], int) and lk["day"] >= 1
            assert lk["doc_id"]
            assert lk["summary"]

        for cm in c["comms"]:
            assert cm["kind"] in {"chat", "interview"}
            assert isinstance(cm["day"], int) and cm["day"] >= 1
            assert "text" in cm and isinstance(cm["text"], str)

        for st in c["tool_steps"]:
            assert isinstance(st["t"], int)
            assert isinstance(st["day"], int)
            assert st["tool"]
            assert isinstance(st["args"], dict)
            assert st["summary"]

        solver = c["solver"]
        post = solver["posterior"]
        assert sum(post.values()) == pytest.approx(1.0, abs=1e-3)
        assert solver["top_suspect"] in suspect_ids
        assert solver["top_prob"] == pytest.approx(max(post.values()), abs=1e-3)
        expected_be = 1.0 / (1.0 + c["value_at_decision"])
        assert solver["break_even_prob"] == pytest.approx(expected_be, abs=1e-3)
        assert solver["recommended_call"] in {"accuse", "hold_fire"}
        calls_seen.add(solver["recommended_call"])
        if solver["recommended_call"] == "accuse":
            assert solver["top_prob"] >= solver["break_even_prob"]
        else:
            assert solver["top_prob"] < solver["break_even_prob"]

        t_levels = c["thinking_levels"]
        assert len(t_levels) >= 2
        seen_lv_keys: set[str] = set()
        for lv in t_levels:
            lv_name = lv["thinking_level"]
            assert lv_name not in seen_lv_keys
            seen_lv_keys.add(lv_name)
            levels_seen.add(lv_name)
            assert lv["call_at_t"] in {"accuse", "hold_fire"}
            assert lv["run_id"] in ledger_run_ids
            assert lv["ledger_calls"] > 0
            assert lv["cost_usd"] > 0.0
            assert lv["calls"] > 0
            assert lv["analyst_quote"]
            if not lv["correct"]:
                assert lv["failure_tag"] is not None

        assert len(c["cross_model_carbon"]) >= 1
        for cmc in c["cross_model_carbon"]:
            assert cmc["model"] == "gemini-4-carbon"
            assert cmc["cost_usd"] > 0.0

    assert tiers_seen == {"medium", "hard"}
    assert calls_seen == {"accuse", "hold_fire"}
    assert levels_seen == {"minimal", "low", "medium", "high", "xhigh"}


def test_deterministic_env_and_solver_step_by_step_replay():
    payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    cases = payload["cases"]
    assert len(cases) >= 4

    ladder_index = outthink.load_ladder_index()
    replayed_count = 0

    for c in cases:
        cid = c["id"]
        tier = c["tier"]
        seed = c["seed"]
        d_step = c["decision_step"]
        assert seed not in HELDOUT_SEEDS
        assert seed not in JUDGE_SEEDS
        assert 0 <= seed < 10_000

        anchor_ep = ladder_index[(c["model"], c["anchor_level"], tier, seed)]
        raw_steps = anchor_ep["steps"]
        ep_steps = [
            Step(**{k: s.get(k) for k in ("t", "day", "tool", "args", "result")})
            for s in raw_steps
        ]
        assert d_step < len(ep_steps)
        assert ep_steps[d_step].tool == "accuse"
        assert bool((ep_steps[d_step].result or {}).get("ok")) is True

        env = Env(tier, seed)
        sp = SolverPolicy(tier_params_for_episode(tier, ep_steps))

        canary_assignments: dict[str, dict[str, str]] = {}
        latest_feed: list[dict] = []
        seen_logs: set[tuple[int, str, str, bool]] = set()
        after_hours_by_emp: dict[str, int] = defaultdict(int)

        assert len(c["tool_steps"]) == d_step
        for idx, (case_st, ep_st) in enumerate(zip(c["tool_steps"], ep_steps[:d_step])):
            assert case_st["t"] == idx == ep_st.t
            assert case_st["day"] == env.day == ep_st.day
            assert case_st["tool"] == ep_st.tool.strip()

            live_res = env.call(ep_st.tool, ep_st.args or {})
            assert live_res.ok == bool((ep_st.result or {}).get("ok")), f"{cid} step {idx} ok mismatch"
            sp._ingest(
                Step(
                    t=ep_st.t,
                    day=ep_st.day,
                    tool=ep_st.tool,
                    args=ep_st.args,
                    result=asdict(live_res),
                )
            )

            if not live_res.ok:
                continue
            data = live_res.data or {}
            tool_name = ep_st.tool.strip()
            if tool_name == "plant_canary":
                can_id = str(data.get("canary_id") or "")
                if can_id:
                    canary_assignments[can_id] = {
                        str(k): str(v) for k, v in (ep_st.args or {}).get("assignment", {}).items()
                    }
            elif tool_name == "check_leak_feed":
                latest_feed = list(data.get("items") or [])
            elif tool_name == "read_access_logs":
                for lg in data.get("logs") or []:
                    log_key = (
                        int(lg.get("day", ep_st.day)),
                        str(lg.get("employee") or ""),
                        str(lg.get("doc_id") or ""),
                        bool(lg.get("after_hours", False)),
                    )
                    if log_key not in seen_logs and log_key[1]:
                        seen_logs.add(log_key)
                        if log_key[3]:
                            after_hours_by_emp[log_key[1]] += 1

        sp.seen = d_step
        sp.obs.leak_timing_known = sp.v_drops_reveal_leaks()
        live_post = sp.belief()

        live_v = float(env.V)
        assert c["value_at_decision"] == pytest.approx(live_v, abs=1e-4), cid
        assert c["decision_day"] == env.day == ep_steps[d_step].day, cid

        solver = c["solver"]
        assert set(solver["posterior"].keys()) == set(env._ids), cid
        for emp_id, live_prob in live_post.items():
            assert solver["posterior"][emp_id] == pytest.approx(float(live_prob), abs=1e-4), f"{cid}:{emp_id}"

        live_top_suspect = max(live_post, key=live_post.get)
        live_top_prob = float(live_post[live_top_suspect])
        live_be_prob = 1.0 / (1.0 + round(live_v, 4)) if live_v > 0 else 1.0
        live_ev_accuse = (live_top_prob * round(live_v, 4)) - (1.0 - live_top_prob)

        assert solver["top_suspect"] == live_top_suspect, cid
        assert solver["top_prob"] == pytest.approx(live_top_prob, abs=1e-4), cid
        assert solver["break_even_prob"] == pytest.approx(live_be_prob, abs=1e-4), cid
        assert solver["ev_accuse_top"] == pytest.approx(live_ev_accuse, abs=1e-4), cid

        live_consistent = set(env._ids)
        for item in latest_feed:
            doc_id = str(item.get("doc_id") or "")
            variant = item.get("variant")
            if variant is not None and doc_id in canary_assignments:
                asg = canary_assignments[doc_id]
                live_consistent &= {emp for emp, v_lbl in asg.items() if v_lbl == variant}
            elif doc_id in env._doc_by_id:
                recips = env._doc_by_id[doc_id].get("recipients") or []
                if recips:
                    live_consistent &= {str(r) for r in recips}

        canary_hits_by_emp: dict[str, int] = defaultdict(int)
        for item in latest_feed:
            doc_id = str(item.get("doc_id") or "")
            l_var = str(item["variant"]) if item.get("variant") is not None else None
            if doc_id in canary_assignments and l_var is not None:
                for emp_id, assigned_var in canary_assignments[doc_id].items():
                    if assigned_var == l_var:
                        canary_hits_by_emp[emp_id] += 1

        for s in c["suspects"]:
            sid = s["id"]
            assert s["eliminated"] is (sid not in live_consistent), f"{cid}:{sid} eliminated mismatch"
            assert s["canary_hits"] == canary_hits_by_emp[sid], f"{cid}:{sid} canary_hits mismatch"
            assert s["after_hours_count"] == after_hours_by_emp[sid], f"{cid}:{sid} after_hours mismatch"

        for st in ep_steps[d_step:]:
            if env.done:
                break
            env.call(st.tool, st.args or {})
        assert env.done is True
        assert env._accused == anchor_ep["accused"]
        assert float(env.score()) == pytest.approx(float(anchor_ep["score"]), abs=1e-6)
        replayed_count += 1

    assert replayed_count == len(cases) >= 4


def test_cli_check_tamper_detection_and_roundtrip(tmp_path: Path, capsys):
    json_out = tmp_path / "out_think_gemini.json"
    js_out = tmp_path / "cases.js"

    rc_missing_json = outthink.main(["--check", "--json-out", str(json_out), "--js-out", str(CASES_JS_PATH)])
    err_missing_json = capsys.readouterr().err
    assert rc_missing_json != 0
    assert "ERROR:" in err_missing_json

    rc_missing_js = outthink.main(["--check", "--json-out", str(JSON_PATH), "--js-out", str(js_out)])
    err_missing_js = capsys.readouterr().err
    assert rc_missing_js != 0
    assert "ERROR:" in err_missing_js

    rc_write = outthink.main(["--json-out", str(json_out), "--js-out", str(js_out)])
    out_write = capsys.readouterr().out
    assert rc_write == 0
    assert "Wrote" in out_write
    assert json_out.read_text(encoding="utf-8") == JSON_PATH.read_text(encoding="utf-8")
    assert js_out.read_text(encoding="utf-8") == CASES_JS_PATH.read_text(encoding="utf-8")

    rc_clean = outthink.main(["--check", "--json-out", str(json_out), "--js-out", str(js_out)])
    out_clean = capsys.readouterr().out
    assert rc_clean == 0
    assert "OK:" in out_clean

    clean_json_text = json_out.read_text(encoding="utf-8")
    tampered_doc = json.loads(clean_json_text)
    tampered_doc["cases"][0]["value_at_decision"] = 0.0123
    json_out.write_text(json.dumps(tampered_doc, indent=2) + "\n", encoding="utf-8")

    rc_json_drift = outthink.main(["--check", "--json-out", str(json_out), "--js-out", str(js_out)])
    err_json_drift = capsys.readouterr().err
    assert rc_json_drift != 0
    assert "out of date" in err_json_drift

    json_out.write_text(clean_json_text, encoding="utf-8")
    clean_js_text = js_out.read_text(encoding="utf-8")
    js_out.write_text(clean_js_text.replace("OUTTHINK_DATA", "OUTTHINK_DATA_TAMPERED", 1), encoding="utf-8")

    rc_js_drift = outthink.main(["--check", "--json-out", str(json_out), "--js-out", str(js_out)])
    err_js_drift = capsys.readouterr().err
    assert rc_js_drift != 0
    assert "out of date" in err_js_drift

    base_payload = json.loads(clean_json_text)
    assert outthink.validate_payload(base_payload) == []

    bad_mole = copy.deepcopy(base_payload)
    bad_mole["cases"][0]["true_mole"] = "e999"
    assert any("true_mole" in e for e in outthink.validate_payload(bad_mole))

    bad_post = copy.deepcopy(base_payload)
    first_emp = next(iter(bad_post["cases"][0]["solver"]["posterior"]))
    bad_post["cases"][0]["solver"]["posterior"][first_emp] += 0.5
    assert any("posterior sum" in e for e in outthink.validate_payload(bad_post))

    bad_step = copy.deepcopy(base_payload)
    bad_step["cases"][0]["decision_step"] = 9999
    assert any("decision_step" in e for e in outthink.validate_payload(bad_step))


def test_pre_decision_leakage_guard():
    payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    allowed_pre_tools = set(ENV_TOOL_SPECS.keys()) - {"accuse"}
    forbidden_obs_keys = {"true_mole", "mole", "is_mole", "decoy", "ground_truth_mole"}

    for c in payload["cases"]:
        cid = c["id"]
        d_day = c["decision_day"]
        d_step = c["decision_step"]
        assert isinstance(d_day, int) and d_day >= 1
        assert isinstance(d_step, int) and d_step == len(c["tool_steps"]) > 0

        for idx, lk in enumerate(c["leaks"]):
            assert lk["day"] <= d_day, f"{cid} leak[{idx}] day {lk['day']} > decision_day {d_day}"
            if "t" in lk and lk["t"] is not None:
                assert lk["t"] < d_step, f"{cid} leak[{idx}] t {lk['t']} >= decision_step {d_step}"
            assert forbidden_obs_keys.isdisjoint(lk.keys())

        for idx, can in enumerate(c["canaries"]):
            assert can["day_planted"] <= d_day, f"{cid} canary[{idx}] day_planted > decision_day {d_day}"
            if "day" in can and can["day"] is not None:
                assert can["day"] <= d_day, f"{cid} canary[{idx}] day > decision_day {d_day}"
            if "t" in can and can["t"] is not None:
                assert can["t"] < d_step, f"{cid} canary[{idx}] t >= decision_step {d_step}"
            assert forbidden_obs_keys.isdisjoint(can.keys())
            seen_recips: list[str] = []
            for var_entry in can["variants"]:
                assert var_entry["variant"]
                assert isinstance(var_entry["recipients"], list) and len(var_entry["recipients"]) >= 1
                seen_recips.extend(var_entry["recipients"])
            assert len(seen_recips) == len(set(seen_recips)), f"{cid} canary[{idx}] duplicate recipient across variants"

        for idx, lg in enumerate(c["access_logs"]):
            assert lg["day"] <= d_day, f"{cid} access_log[{idx}] day {lg['day']} > decision_day {d_day}"
            if "t" in lg and lg["t"] is not None:
                assert lg["t"] < d_step, f"{cid} access_log[{idx}] t >= decision_step {d_step}"
            assert forbidden_obs_keys.isdisjoint(lg.keys())

        for idx, cm in enumerate(c["comms"]):
            assert cm["day"] <= d_day, f"{cid} comm[{idx}] day {cm['day']} > decision_day {d_day}"
            if "t" in cm and cm["t"] is not None:
                assert cm["t"] < d_step, f"{cid} comm[{idx}] t >= decision_step {d_step}"
            assert forbidden_obs_keys.isdisjoint(cm.keys())

        prev_day = 1
        for idx, st in enumerate(c["tool_steps"]):
            assert 0 <= st["t"] < d_step, f"{cid} tool_step[{idx}] t {st['t']} >= decision_step {d_step}"
            assert st["t"] == idx, f"{cid} tool_step[{idx}] non-contiguous t {st['t']}"
            assert prev_day <= st["day"] <= d_day, f"{cid} tool_step[{idx}] day {st['day']} out of bounds"
            prev_day = st["day"]
            assert st["tool"] in allowed_pre_tools, f"{cid} tool_step[{idx}] disallowed tool {st['tool']}"
            assert st["tool"] != "accuse"
            assert st["tool"] != "read_document"
            assert forbidden_obs_keys.isdisjoint(st.keys())

        for s in c["suspects"]:
            assert forbidden_obs_keys.isdisjoint(s.keys())


def test_keyless_subprocess_check_without_api_keys():
    clean_env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"}
    }
    clean_env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.run(
        [sys.executable, "-m", "canary.gemini.outthink", "--check"],
        cwd=ROOT,
        env=clean_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert "OK:" in proc.stdout


def test_hygiene_zero_comments_dashes_network_keys_and_protected_paths():
    self_path = Path(__file__).resolve()
    py_files = (MODULE_PATH, self_path)
    all_files = (MODULE_PATH, JSON_PATH, CASES_JS_PATH, self_path)

    for pf in py_files:
        src = pf.read_text(encoding="utf-8")
        assert HASH_CHAR not in src, f"hash comment char in {pf}"
        comments = [
            tok for tok in tokenize.generate_tokens(io.StringIO(src).readline) if tok.type == tokenize.COMMENT
        ]
        assert comments == []
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "genai" not in alias.name and "google" not in alias.name
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert "genai" not in node.module and "google" not in node.module

    for fpath in all_files:
        txt = fpath.read_text(encoding="utf-8")
        assert EM_DASH not in txt, f"em dash in {fpath}"
        assert EN_DASH not in txt, f"en dash in {fpath}"
        assert FORBIDDEN_NET not in txt, f"forbidden network call in {fpath}"

    js_txt = CASES_JS_PATH.read_text(encoding="utf-8")
    assert _find_js_comments(js_txt) == []

    rules = [
        ln.strip()
        for ln in PROTECTED_PATHS_FILE.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith(HASH_CHAR)
    ]
    checked = {f.relative_to(ROOT).as_posix() for f in all_files}
    status_proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if status_proc.returncode == 0:
        for line in status_proc.stdout.splitlines():
            if len(line) > 3:
                entry = line[3:].strip()
                if " -> " in entry:
                    entry = entry.split(" -> ", 1)[1].strip()
                checked.add(entry)
    diff_proc = subprocess.run(
        ["git", "diff", "--name-only", "origin/justSilas..HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if diff_proc.returncode == 0:
        for rel in diff_proc.stdout.splitlines():
            if rel.strip():
                checked.add(rel.strip())
    for rel in checked:
        for rule in rules:
            if rule.endswith("/"):
                assert not rel.startswith(rule), f"protected dir touched: {rel}"
            else:
                assert rel != rule, f"protected file touched: {rel}"
