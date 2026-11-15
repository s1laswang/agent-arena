from __future__ import annotations

import ast
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tokenize
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.env import Env
from canary.eval import run_episode
from canary.gemini import investigator_carbon as ic
from canary.solver.policy import SolverPolicy

ROLE_ROOT = ROOT / ic.DEFAULT_ROLE_DIR
DOC_PATH = ROOT / ic.DEFAULT_DOC_PATH
PROTECTED_PATHS_FILE = ROOT / ".github" / "protected-paths.txt"

BASELINE_FRONTIER_RUNS = frozenset({
    "easy-0-3",
    "medium-0-1",
    "medium-2-3",
    "medium-4-5",
    "medium-6-7",
    "medium-8-9",
    "medium-11",
    "hard-0",
    "hard-1",
    "hard-2",
    "hard-3",
    "hard-4",
    "hard-5",
    "hard-6",
    "hard-7",
    "hard-8",
    "hard-9",
    "hard-10",
    "hard-11",
    "hard-12",
    "hard-13",
    "hard-14",
    "hard-16",
    "hard-17",
    "hard-18",
    "hard-19",
})

BASELINE_ABLATION_RUNS = frozenset({
    "hint-ablation-carbon-med01",
    "thinking-ladder-carbon-hard0",
    "thinking-ladder-carbon-med01",
})

EXPECTED_WAVE1_RUNS = BASELINE_FRONTIER_RUNS | BASELINE_ABLATION_RUNS

SAMPLE_REPLAY_RUNS = (
    "easy-0-3",
    "medium-0-1",
    "medium-4-5",
    "medium-8-9",
    "medium-11",
    "hard-0",
    "hard-7",
    "hard-14",
    "hard-16",
    "hard-19",
    "hint-ablation-carbon-med01",
    "thinking-ladder-carbon-hard0",
    "thinking-ladder-carbon-med01",
)


@pytest.fixture(autouse=True)
def _keyless_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)


@pytest.fixture(scope="module")
def suite_report() -> dict[str, object]:
    return ic.audit_investigator_suite(ROOT)


def test_source_files_have_zero_comments_hashes_dashes_or_secrets() -> None:
    for rel in ("canary/gemini/investigator_carbon.py", "tests/test_gemini_lab_investigator_carbon.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert chr(35) not in src
        for d in ic.FORBIDDEN_DASHES:
            assert d not in src
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [t for t in tokens if t.type == tokenize.COMMENT]
        assert comments == []
        assert ic.scan_text_hygiene(src) == []


def test_suite_all_folders_verified_replay_and_hygiene_clean(suite_report: dict[str, object]) -> None:
    assert suite_report["verified"] is True
    assert suite_report["errors"] == []
    assert suite_report["role"] == "investigators"
    assert suite_report["model_id"] == "gemini-4-carbon"
    assert suite_report["tiers_version"] == "v1.4"

    runs = suite_report["runs"]
    assert isinstance(runs, list)
    run_names = {r["run_name"] for r in runs}
    assert len(EXPECTED_WAVE1_RUNS) == 29
    assert run_names == EXPECTED_WAVE1_RUNS
    assert all(r["verified"] is True and r["errors"] == [] for r in runs)

    totals = suite_report["totals"]
    assert isinstance(totals, dict)
    assert totals["verified_runs"] == 29
    assert totals["frontier_runs"] == 26
    assert totals["thinking_ablation_runs"] == 2
    assert totals["hint_ablation_runs"] == 1
    assert totals["total_episodes"] == 42
    assert totals["unique_frontier_episodes"] == 34
    assert totals["replay_verified_episodes"] == totals["total_episodes"]
    assert totals["verified_transcripts"] == totals["total_episodes"]
    assert totals["verified_signature_parts"] == 3644
    assert totals["calls"] == 3649
    assert totals["tokens_in"] == 132698927
    assert totals["tokens_out"] == 1542560
    assert totals["thinking_tokens"] == 157797
    assert totals["cached_tokens"] == 123477915
    assert totals["cost_usd_est"] == pytest.approx(47.793381, abs=1e-6)
    assert totals["cost_usd_list"] == pytest.approx(282.401424, abs=1e-6)
    assert totals["hygiene_violations"] == 0


def test_paired_solver_comparison_and_bootstrap_cis(suite_report: dict[str, object]) -> None:
    slices = suite_report["frontier_paired_vs_solver"]
    assert isinstance(slices, dict)
    for key in ("easy", "medium", "hard", "medium_plus_hard", "all_tiers"):
        assert key in slices
        st = slices[key]
        assert st["n"] >= 4
        acc_lo, acc_hi = st["accuracy_ci95"]
        assert 0.0 <= acc_lo <= st["accuracy"] <= acc_hi <= 1.0
        r_lo, r_hi = st["frontier_over_solver_ci95"]
        assert r_lo <= st["frontier_over_solver_ratio"] <= r_hi
        d_lo, d_hi = st["paired_diff_boot_ci95"]
        assert d_lo <= st["paired_diff_mean"] <= d_hi
        if st["luck_adjusted_ratio"] is not None and st["luck_adjusted_ratio_ci95"] is not None:
            l_lo, l_hi = st["luck_adjusted_ratio_ci95"]
            assert l_lo <= st["luck_adjusted_ratio"] <= l_hi

    easy = slices["easy"]
    assert easy["n"] == 4
    expected_easy_solver = [run_episode(Env("easy", s), SolverPolicy()).score for s in range(4)]
    if easy["seeds"] == [0, 1, 2, 3]:
        assert easy["solver_mean_score"] == pytest.approx(sum(expected_easy_solver) / 4.0, abs=1e-6)
        assert easy["mean_score"] == pytest.approx(0.85, abs=1e-6)
        assert easy["accuracy"] == pytest.approx(1.0, abs=1e-6)

    assert slices["medium"]["n"] == 11
    assert slices["hard"]["n"] == 19
    assert slices["medium_plus_hard"]["n"] == 30
    assert slices["all_tiers"]["n"] == 34


def test_thinking_and_hint_ablations_integrity(suite_report: dict[str, object]) -> None:
    thinking = suite_report["thinking_ablations"]
    assert isinstance(thinking, dict)
    runs_by_name = {r["run_name"]: r for r in thinking["runs"]}
    assert "thinking-ladder-carbon-hard0" in runs_by_name
    assert "thinking-ladder-carbon-med01" in runs_by_name

    hard0 = runs_by_name["thinking-ladder-carbon-hard0"]
    assert set(hard0["levels"].keys()) == {"low", "high"}
    assert hard0["levels"]["low"]["mean_score"] == pytest.approx(0.78, abs=1e-6)
    assert hard0["levels"]["high"]["mean_score"] == pytest.approx(0.36, abs=1e-6)
    assert hard0["levels"]["high"]["regret_per_episode"] < hard0["levels"]["low"]["regret_per_episode"]

    med01 = runs_by_name["thinking-ladder-carbon-med01"]
    assert set(med01["levels"].keys()) == {"low", "high"}
    assert med01["levels"]["low"]["mean_score"] == pytest.approx(0.655, abs=1e-6)
    assert med01["levels"]["high"]["mean_score"] == pytest.approx(0.655, abs=1e-6)
    assert med01["levels"]["high"]["regret_per_episode"] < med01["levels"]["low"]["regret_per_episode"]

    med01_meta = json.loads((ROLE_ROOT / "thinking-ladder-carbon-med01" / "meta.json").read_text(encoding="utf-8"))
    assert (
        med01_meta["levels_summary"]["high"]["thinking_tokens_per_episode"]
        > med01_meta["levels_summary"]["low"]["thinking_tokens_per_episode"]
    )

    hints = suite_report["hint_ablations"]
    assert isinstance(hints, list) and len(hints) >= 1
    h0 = next(h for h in hints if h["run_name"] == "hint-ablation-carbon-med01")
    assert h0["hint"] == "premature_accusation,ignored_delay"
    assert h0["hinted"]["n"] == 2
    assert h0["unhinted_same_seeds"] is not None
    assert h0["delta_vs_unhinted"]["regret_per_episode_delta"] < 0.0


def test_transcript_signature_redaction_and_detection() -> None:
    raw_sig = "c2lnbmF0dXJlX3BheWxvYWRfZm9yX3Rlc3Rpbmc="
    expected_sha = hashlib.sha256(raw_sig.encode("utf-8")).hexdigest()
    sample_msgs = [
        {"role": "system", "content": "rules"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call_1", "name": "status", "args": {}}],
            "provider_items": [
                {
                    "role": "model",
                    "parts": [
                        {"thought": True, "text": "Checking status first."},
                        {
                            "function_call": {"id": "call_1", "name": "status", "args": {}},
                            "thought_signature": raw_sig,
                        },
                    ],
                }
            ],
        },
    ]

    unredacted_audit = ic.audit_transcript_data(sample_msgs)
    assert unredacted_audit["valid"] is False
    assert unredacted_audit["unredacted_signatures"] == 1

    redacted_msgs, stats = ic.redact_transcript_signatures(sample_msgs)
    assert stats == {"total_signatures": 1, "redacted_now": 1}
    part = redacted_msgs[1]["provider_items"][0]["parts"][1]
    assert part["thought_signature"] == f"<redacted_thought_signature_chars:{len(raw_sig)}>"
    assert part["thought_signature_sha256"] == expected_sha
    assert part["thought_signature_len"] == len(raw_sig)

    redacted_audit = ic.audit_transcript_data(redacted_msgs)
    assert redacted_audit["valid"] is True
    assert redacted_audit["signature_parts"] == 1
    assert redacted_audit["sha256_parts"] == 1
    assert redacted_audit["thought_parts"] == 1

    missing_sig_msgs = [
        {"role": "assistant", "content": "hi", "provider_items": [{"role": "model", "parts": [{"text": "hi"}]}]}
    ]
    missing_audit = ic.audit_transcript_data(missing_sig_msgs)
    assert missing_audit["valid"] is False
    assert "missing_thought_signatures" in missing_audit["errors"]


def test_synthetic_tampering_and_hygiene_failures_caught(tmp_path: Path) -> None:
    src_run = ROLE_ROOT / "hard-14"
    clean_copy = tmp_path / "roles_carbon" / "investigators" / "hard-14"
    shutil.copytree(src_run, clean_copy)
    ok_res = ic.inspect_investigator_run(clean_copy, tmp_path)
    assert ok_res["verified"] is True

    tampered = tmp_path / "roles_carbon" / "investigators" / "tampered-score"
    shutil.copytree(src_run, tampered)
    ep_path = tampered / "episodes.jsonl"
    ep = json.loads(ep_path.read_text(encoding="utf-8").strip())
    ep["score"] = 0.9999
    ep_path.write_text(json.dumps(ep) + "\n", encoding="utf-8")
    bad_rep = ic.inspect_investigator_run(tampered, tmp_path)
    assert bad_rep["verified"] is False
    assert any(err.startswith("replay_mismatch:") for err in bad_rep["errors"])

    leaked = tmp_path / "roles_carbon" / "investigators" / "secret-leak"
    shutil.copytree(src_run, leaked)
    fake_key = "AI" + "za" + "SyFakeFixtureKey1234567890abcd"
    (leaked / "summary.md").write_text(
        (leaked / "summary.md").read_text(encoding="utf-8") + f"\n{fake_key}\n",
        encoding="utf-8",
    )
    bad_leak = ic.inspect_investigator_run(leaked, tmp_path)
    assert bad_leak["verified"] is False
    assert "hygiene_violation" in bad_leak["errors"]

    stub_dir = tmp_path / "roles_carbon" / "investigators" / "stub-flagged"
    shutil.copytree(src_run, stub_dir)
    meta = json.loads((stub_dir / "meta.json").read_text(encoding="utf-8"))
    meta["stub"] = True
    (stub_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    bad_stub = ic.inspect_investigator_run(stub_dir, tmp_path)
    assert bad_stub["verified"] is False
    assert "disallowed_flag:stub" in bad_stub["errors"]


def test_cli_strict_json_and_consolidated_doc_clean(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert DOC_PATH.is_file()
    doc_txt = DOC_PATH.read_text(encoding="utf-8")
    assert ic.scan_text_hygiene(doc_txt) == []
    assert "SolverPolicy" in doc_txt
    assert "gemini-4-carbon" in doc_txt

    out_doc = tmp_path / "investigators.md"
    rc = ic.main(["--root", str(ROOT), "--strict", "--json", "--write-doc", str(out_doc)])
    assert rc == 0
    out_json = json.loads(capsys.readouterr().out)
    assert out_json["verified"] is True
    assert out_doc.is_file()
    assert out_doc.read_text(encoding="utf-8") == doc_txt
    assert ic.scan_text_hygiene(out_doc.read_text(encoding="utf-8")) == []

    clean_env = dict(os.environ)
    clean_env["GEMINI_API_KEY"] = ""
    clean_env["GOOGLE_API_KEY"] = ""
    clean_env["GOOGLE_GENERATIVE_AI_API_KEY"] = ""
    clean_env.pop("GEMINI_GATEWAY_URL", None)
    clean_env["PYTHONPATH"] = str(ROOT)

    sub_doc = tmp_path / "sub_investigators.md"
    sub_proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "canary.gemini.investigator_carbon",
            "--root",
            str(ROOT),
            "--strict",
            "--json",
            "--write-doc",
            str(sub_doc),
        ],
        cwd=ROOT,
        env=clean_env,
        capture_output=True,
        text=True,
        check=True,
    )
    sub_payload = json.loads(sub_proc.stdout)
    assert sub_payload["verified"] is True
    assert sub_payload["totals"]["verified_runs"] == 29
    assert sub_payload["totals"]["total_episodes"] == 42
    assert sub_payload["totals"]["calls"] == 3649
    assert sub_doc.read_text(encoding="utf-8") == doc_txt

    empty_role = tmp_path / "empty_role_dir"
    empty_role.mkdir()
    missing_proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "canary.gemini.investigator_carbon",
            "--root",
            str(ROOT),
            "--role-dir",
            str(empty_role),
            "--strict",
            "--json",
        ],
        cwd=ROOT,
        env=clean_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing_proc.returncode == 1
    assert json.loads(missing_proc.stdout)["verified"] is False


def _extract_ast_imports(source: str) -> list[str]:
    tree = ast.parse(source)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                found.append(node.module)
            for alias in node.names:
                found.append(alias.name)
                if node.module:
                    found.append(f"{node.module}.{alias.name}")
    return found


def _has_forbidden_sdk_import(imports: list[str]) -> bool:
    banned_tokens = {
        "".join(("goo", "gle")),
        "".join(("gen", "ai")),
        "".join(("generative", "ai")),
        "".join(("vertex", "ai")),
    }
    for name in imports:
        segments = {seg.lower() for seg in name.replace("-", "_").split(".")}
        if segments & banned_tokens:
            return True
    return False


def _load_protected_rules(path: Path) -> list[str]:
    rules: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        item = raw.strip()
        if not item or item.startswith(chr(35)):
            continue
        rules.append(item)
    return rules


def _matches_protected_path(rel_path: str, rules: list[str]) -> bool:
    for rule in rules:
        if rule.endswith("/"):
            if rel_path.startswith(rule):
                return True
        elif rel_path == rule:
            return True
    return False


def _extract_thought_summaries(messages: list[dict[str, Any]]) -> tuple[list[str], int]:
    summaries: list[str] = []
    invalid_thought_parts = 0
    for msg in messages:
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        for p_item in msg.get("provider_items") or []:
            if not isinstance(p_item, dict):
                continue
            for part in p_item.get("parts") or []:
                if not isinstance(part, dict) or part.get("thought") is not True:
                    continue
                txt = part.get("text")
                if isinstance(txt, str) and txt.strip():
                    summaries.append(txt.strip())
                else:
                    invalid_thought_parts += 1
    return summaries, invalid_thought_parts


def test_hostile_judge_zero_sdk_imports_and_zero_protected_path_touches() -> None:
    synthetic_bad = "".join(("from ", "goo", "gle import ", "gen", "ai\n"))
    assert _has_forbidden_sdk_import(_extract_ast_imports(synthetic_bad)) is True

    for rel in ("canary/gemini/investigator_carbon.py", "tests/test_gemini_lab_investigator_carbon.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        imports = _extract_ast_imports(src)
        assert len(imports) > 0
        assert _has_forbidden_sdk_import(imports) is False

    banned_mod_prefixes = (
        "".join(("goo", "gle.", "gen", "ai")),
        "".join(("goo", "gle.generative", "ai")),
    )
    probe_env = dict(os.environ)
    probe_env["GEMINI_API_KEY"] = ""
    probe_env["GOOGLE_API_KEY"] = ""
    probe_env["GOOGLE_GENERATIVE_AI_API_KEY"] = ""
    probe_env["PYTHONPATH"] = str(ROOT)
    mod_probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json, sys, canary.gemini.investigator_carbon; print(json.dumps(sorted(sys.modules)))",
        ],
        cwd=ROOT,
        env=probe_env,
        capture_output=True,
        text=True,
        check=True,
    )
    for loaded_name in json.loads(mod_probe.stdout):
        for prefix in banned_mod_prefixes:
            assert not loaded_name.startswith(prefix)

    assert PROTECTED_PATHS_FILE.is_file()
    rules = _load_protected_rules(PROTECTED_PATHS_FILE)
    assert len(rules) >= 10
    assert _matches_protected_path("canary/env.py", rules) is True
    assert _matches_protected_path("canary/solver/policy.py", rules) is True
    assert _matches_protected_path("data/runs/committed/v1.4/sample", rules) is True
    assert _matches_protected_path(".github/protected-paths.txt", rules) is True

    suite_files = [
        "canary/gemini/investigator_carbon.py",
        "tests/test_gemini_lab_investigator_carbon.py",
        "docs/gemini/roles_carbon/investigators.md",
    ]
    for fp in sorted(p for p in ROLE_ROOT.rglob("*") if p.is_file()):
        suite_files.append(fp.resolve().relative_to(ROOT.resolve()).as_posix())
    assert len(suite_files) >= 140
    assert [f for f in suite_files if _matches_protected_path(f, rules)] == []

    for base_ref in ("origin/justSilas", "justSilas"):
        chk = subprocess.run(
            ["git", "rev-parse", "--verify", base_ref],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if chk.returncode == 0:
            diff_proc = subprocess.run(
                ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            changed = [ln.strip() for ln in diff_proc.stdout.splitlines() if ln.strip()]
            assert [f for f in changed if _matches_protected_path(f, rules)] == []
            break

    status_proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    dirty_paths = [ln[3:].strip().split(" -> ")[-1] for ln in status_proc.stdout.splitlines() if len(ln) > 3]
    assert [f for f in dirty_paths if _matches_protected_path(f, rules)] == []


@pytest.mark.parametrize("run_name", SAMPLE_REPLAY_RUNS)
def test_hostile_judge_deterministic_env_replay_parity_across_sample_runs(run_name: str) -> None:
    assert "easy-0-3" in SAMPLE_REPLAY_RUNS
    assert any(r.startswith("medium-") for r in SAMPLE_REPLAY_RUNS)
    assert any(r.startswith("hard-") for r in SAMPLE_REPLAY_RUNS)
    assert "hint-ablation-carbon-med01" in SAMPLE_REPLAY_RUNS
    assert any(r.startswith("thinking-ladder-carbon-") for r in SAMPLE_REPLAY_RUNS)

    run_dir = ROLE_ROOT / run_name
    assert run_dir.is_dir()
    sources = ic._collect_run_episodes(run_dir, "")
    assert len(sources) >= 1
    if run_name.startswith("thinking-ladder-carbon-"):
        assert {lv for lv, _, _ in sources} == {"low", "high"}

    replayed_count = 0
    for level, ep_file, _ in sources:
        lines = [ln for ln in ep_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(lines) >= 1
        for raw_line in lines:
            ep = json.loads(raw_line)
            tier = str(ep["tier"])
            seed = int(ep["seed"])
            steps = ep["steps"]
            assert isinstance(steps, list) and len(steps) >= 1

            env_a = Env(tier, seed)
            env_b = Env(tier, seed)
            for idx, st in enumerate(steps):
                assert env_a.done is False
                assert env_b.done is False
                assert int(st["t"]) == idx
                assert int(st["day"]) == env_a.day
                tool_name = str(st["tool"])
                tool_args = st.get("args") or {}
                out_a = env_a.call(tool_name, tool_args)
                out_b = env_b.call(tool_name, tool_args)
                assert out_a == out_b
                rec_res = st["result"]
                assert out_a.ok is bool(rec_res["ok"])
                assert out_a.error == rec_res["error"]
                if out_a.ok:
                    assert out_a.data == rec_res["data"]

            assert env_a.verdict() == env_b.verdict()
            res = env_a.result("hostile_judge")
            assert res.score == pytest.approx(float(ep["score"]), abs=1e-9)
            assert res.accused == ep["accused"]
            assert bool(res.correct) is bool(ep["correct"])
            assert int(res.final_day) == int(ep["final_day"])
            assert res.end_reason == ep["end_reason"]

            if ep["accused"] is not None:
                assert ep["end_reason"] == "accused"
                assert steps[-1]["tool"] == "accuse"
                assert (steps[-1].get("args") or {}) == {"employee": ep["accused"]}
                if ep["correct"]:
                    assert 0.0 < float(ep["score"]) <= 1.0
                else:
                    assert float(ep["score"]) == pytest.approx(-1.0, abs=1e-9)
            else:
                assert ep["correct"] is False
                assert float(ep["score"]) == pytest.approx(0.0, abs=1e-9)
                assert all(s["tool"] != "accuse" for s in steps)

            if level is not None:
                assert level in {"low", "high"}
            replayed_count += 1

    assert replayed_count >= 1


def test_hostile_judge_all_42_episodes_transcript_tool_and_env_parity() -> None:
    run_dirs = sorted(p for p in ROLE_ROOT.iterdir() if p.is_dir())
    assert len(run_dirs) == 29

    episode_total = 0
    for run_dir in run_dirs:
        for _, ep_file, tx_dir in ic._collect_run_episodes(run_dir, ""):
            for raw_line in ep_file.read_text(encoding="utf-8").splitlines():
                if not raw_line.strip():
                    continue
                ep = json.loads(raw_line)
                rep = ic.replay_verify_episode(ep)
                assert rep["ok"] is True
                seed = int(ep["seed"])
                msgs = json.loads((tx_dir / f"{seed}.json").read_text(encoding="utf-8"))
                tx_calls = [
                    (tc.get("name"), tc.get("args") or {})
                    for m in msgs
                    if isinstance(m, dict) and m.get("role") == "assistant"
                    for tc in (m.get("tool_calls") or [])
                ]
                ep_calls = [(s["tool"], s.get("args") or {}) for s in ep["steps"]]
                assert tx_calls == ep_calls
                episode_total += 1

    assert episode_total == 42


def test_hostile_judge_transcript_thought_summaries_and_nonempty_reasoning() -> None:
    bad_msgs = [
        {
            "role": "assistant",
            "provider_items": [
                {"role": "model", "parts": [{"thought": True, "text": "   "}, {"thought": True, "text": ""}]}
            ],
        }
    ]
    bad_summaries, bad_invalid = _extract_thought_summaries(bad_msgs)
    assert bad_summaries == []
    assert bad_invalid == 2

    run_dirs = sorted(p for p in ROLE_ROOT.iterdir() if p.is_dir())
    assert len(run_dirs) == 29

    reasoning_tx_count = 0
    low_level_tx_count = 0
    total_thought_parts = 0

    for run_dir in run_dirs:
        for level, ep_file, tx_dir in ic._collect_run_episodes(run_dir, ""):
            for raw_line in ep_file.read_text(encoding="utf-8").splitlines():
                if not raw_line.strip():
                    continue
                ep = json.loads(raw_line)
                seed = int(ep["seed"])
                tx_path = tx_dir / f"{seed}.json"
                assert tx_path.is_file()
                msgs = json.loads(tx_path.read_text(encoding="utf-8"))
                assert isinstance(msgs, list) and len(msgs) >= 4
                assert msgs[0].get("role") == "system" and isinstance(msgs[0].get("content"), str) and msgs[0]["content"].strip()
                assert msgs[1].get("role") == "user" and isinstance(msgs[1].get("content"), str) and msgs[1]["content"].strip()

                tx_audit = ic.audit_transcript_data(msgs)
                assert tx_audit["valid"] is True
                assert tx_audit["unredacted_signatures"] == 0
                assert tx_audit["signature_parts"] >= 26

                summaries, invalid_parts = _extract_thought_summaries(msgs)
                assert invalid_parts == 0

                if level == "low":
                    assert summaries == []
                    assert tx_audit["signature_parts"] >= 39
                    low_level_tx_count += 1
                else:
                    assert len(summaries) >= 26
                    assert sum(len(s) for s in summaries) >= 20000
                    for s in summaries:
                        assert len(s) >= 100
                        assert len(s.split()) >= 15
                    reasoning_tx_count += 1
                    total_thought_parts += len(summaries)

    assert reasoning_tx_count == 39
    assert low_level_tx_count == 3
    assert reasoning_tx_count + low_level_tx_count == 42
    assert total_thought_parts == 3475


def test_hostile_judge_doc_exact_sums_match_29_run_directories(suite_report: dict[str, object]) -> None:
    run_dirs = sorted(p for p in ROLE_ROOT.iterdir() if p.is_dir())
    assert len(run_dirs) == 29
    assert {d.name for d in run_dirs} == EXPECTED_WAVE1_RUNS

    raw_by_run: dict[str, dict[str, Any]] = {}
    frontier_keys: set[tuple[str, int]] = set()
    subrole_counts = {"frontier": 0, "ladder": 0, "hint": 0}

    for d in run_dirs:
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        subrole = str(meta["subrole"])
        if subrole == "frontier_investigator":
            subrole_counts["frontier"] += 1
        elif subrole in {"thinking_level_ablation", "hard_thinking_ablation"}:
            subrole_counts["ladder"] += 1
        elif subrole == "hint_ablation":
            subrole_counts["hint"] += 1
        else:
            pytest.fail(f"unexpected subrole: {subrole}")

        ep_lines = 0
        for _, ep_file, _ in ic._collect_run_episodes(d, subrole):
            for ln in ep_file.read_text(encoding="utf-8").splitlines():
                if not ln.strip():
                    continue
                ep_obj = json.loads(ln)
                ep_lines += 1
                if subrole == "frontier_investigator":
                    frontier_keys.add((str(ep_obj["tier"]), int(ep_obj["seed"])))

        declared = meta.get("episode_count", meta.get("n_episodes"))
        assert declared == ep_lines

        usage = meta["usage"]
        raw_by_run[d.name] = {
            "subrole": subrole,
            "episodes": ep_lines,
            "calls": int(usage["calls"]),
            "in": int(usage.get("in", usage.get("in_tokens", 0))),
            "out": int(usage.get("out", usage.get("out_tokens", 0))),
            "thinking": int(usage.get("thinking", usage.get("thinking_tokens", 0) or 0)),
            "cached": int(usage.get("cached", usage.get("cached_in", usage.get("cached_tokens", 0)))),
            "cost_est": round(float(usage.get("cost_usd_est", usage["cost_usd"])), 6),
            "cost_list": round(float(usage["cost_usd"]), 6),
        }

    sum_episodes = sum(v["episodes"] for v in raw_by_run.values())
    sum_calls = sum(v["calls"] for v in raw_by_run.values())
    sum_in = sum(v["in"] for v in raw_by_run.values())
    sum_out = sum(v["out"] for v in raw_by_run.values())
    sum_thinking = sum(v["thinking"] for v in raw_by_run.values())
    sum_cached = sum(v["cached"] for v in raw_by_run.values())
    sum_cost_est = round(sum(v["cost_est"] for v in raw_by_run.values()), 6)
    sum_cost_list = round(sum(v["cost_list"] for v in raw_by_run.values()), 6)

    assert subrole_counts == {"frontier": 26, "ladder": 2, "hint": 1}
    assert sum_episodes == 42
    assert len(frontier_keys) == 34
    assert sum_calls == 3649
    assert sum_in == 132698927
    assert sum_out == 1542560
    assert sum_thinking == 157797
    assert sum_cached == 123477915
    assert f"{sum_cost_est:.4f}" == "47.7934"
    assert f"{sum_cost_list:.4f}" == "282.4014"

    doc_txt = DOC_PATH.read_text(encoding="utf-8")
    assert doc_txt == ic.render_suite_markdown(suite_report)
    assert (
        f"- Verified run folders: `{len(run_dirs)}` "
        f"(`{subrole_counts['frontier']}` frontier + `{subrole_counts['ladder']}` thinking-ladder + `{subrole_counts['hint']}` hint-ablation)"
    ) in doc_txt
    assert f"- Replay-verified episodes: `{sum_episodes} / {sum_episodes}` (`{len(frontier_keys)}` unique frontier episodes)" in doc_txt
    assert f"- Total Gemini API calls: `{sum_calls:,}`" in doc_txt
    assert (
        f"- Total tokens (in / out / thinking / cached): "
        f"`{sum_in:,}` / `{sum_out:,}` / `{sum_thinking:,}` / `{sum_cached:,}`"
    ) in doc_txt
    assert f"- Total cost (USD, cache-adjusted est / uncached list): `${sum_cost_est:.4f}` / `${sum_cost_list:.4f}`" in doc_txt

    inventory_section = doc_txt.split("4. Verified Run Folders Inventory", 1)[1]
    table_rows: dict[str, dict[str, Any]] = {}
    for line in inventory_section.splitlines():
        if not line.startswith("| `"):
            continue
        cols = [c.strip() for c in line.strip("|").split("|")]
        assert len(cols) == 10
        rname = cols[0].strip("`")
        assert rname not in table_rows
        table_rows[rname] = {
            "subrole": cols[1].strip("`"),
            "episodes": int(cols[2]),
            "calls": int(cols[3].replace(",", "")),
            "in": int(cols[4].replace(",", "")),
            "out": int(cols[5].replace(",", "")),
            "thinking": int(cols[6].replace(",", "")),
            "cached": int(cols[7].replace(",", "")),
            "cost_est_str": cols[8],
            "cost_est_val": float(cols[8].lstrip("$")),
            "verified": cols[9],
        }

    assert len(table_rows) == 29
    assert set(table_rows) == set(raw_by_run)
    for rname, tr in table_rows.items():
        rw = raw_by_run[rname]
        assert tr["subrole"] == rw["subrole"]
        assert tr["episodes"] == rw["episodes"]
        assert tr["calls"] == rw["calls"]
        assert tr["in"] == rw["in"]
        assert tr["out"] == rw["out"]
        assert tr["thinking"] == rw["thinking"]
        assert tr["cached"] == rw["cached"]
        assert tr["cost_est_str"] == f"${rw['cost_est']:.4f}"
        assert tr["verified"] == "yes"

    assert sum(tr["episodes"] for tr in table_rows.values()) == sum_episodes
    assert sum(tr["calls"] for tr in table_rows.values()) == sum_calls
    assert sum(tr["in"] for tr in table_rows.values()) == sum_in
    assert sum(tr["out"] for tr in table_rows.values()) == sum_out
    assert sum(tr["thinking"] for tr in table_rows.values()) == sum_thinking
    assert sum(tr["cached"] for tr in table_rows.values()) == sum_cached
    assert abs(sum(tr["cost_est_val"] for tr in table_rows.values()) - sum_cost_est) < 1e-3
