from __future__ import annotations

import ast
import gzip
import io
import json
import os
import shutil
import subprocess
import tokenize
from pathlib import Path

import pytest

from canary.env import Env
from canary.gemini import outthink

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
