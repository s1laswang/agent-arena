from __future__ import annotations

import io
import json
import shutil
import subprocess
import tokenize
from pathlib import Path
from typing import Any

import pytest

from canary.env import Env
from canary.rules import DEV_SEEDS, HELDOUT_SEEDS, JUDGE_SEEDS
from scripts import build_tiebreak_arena_traces as builder

ROOT = Path(__file__).resolve().parents[1]
BUILDER_PY = ROOT / "scripts" / "build_tiebreak_arena_traces.py"
DATA_JS = ROOT / "docs" / "arena" / "data" / "tiebreak_traces.js"
SHIM_JS = ROOT / "docs" / "arena" / "tiebreak_traces.js"
SELF_PY = Path(__file__).resolve()


def _find_node() -> str:
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
    raise AssertionError("node binary is required for Arena ESM contract tests")


def _assert_zero_python_comments(py_path: Path) -> None:
    src = py_path.read_text(encoding="utf-8")
    assert src.isascii(), f"{py_path} contains non-ASCII characters"
    for dch in builder.DASH_CHARS:
        assert dch not in src, f"{py_path} contains unicode dash {ord(dch):04x}"
    tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
    assert not comments, f"{py_path} contains Python comments at line {comments[0].start[0]}"


def _collect_all_keys(obj: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            found.add(str(k))
            found.update(_collect_all_keys(v))
    elif isinstance(obj, list):
        for item in obj:
            found.update(_collect_all_keys(item))
    return found


def test_bundle_size_and_zero_comment_emdash_hygiene() -> None:
    assert DATA_JS.is_file()
    assert SHIM_JS.is_file()
    data_bytes = DATA_JS.read_bytes()
    shim_bytes = SHIM_JS.read_bytes()
    assert 10_000 < len(data_bytes) < builder.MAX_BUNDLE_BYTES
    assert len(data_bytes) < 250_000
    assert 0 < len(shim_bytes) < 4096

    _assert_zero_python_comments(BUILDER_PY)
    _assert_zero_python_comments(SELF_PY)

    data_txt = data_bytes.decode("utf-8")
    shim_txt = shim_bytes.decode("utf-8")
    assert not builder._audit_js_text_hygiene(data_txt, "docs/arena/data/tiebreak_traces.js", 250_000)
    assert not builder._audit_js_text_hygiene(shim_txt, "docs/arena/tiebreak_traces.js", 4096)


def test_check_determinism_and_train_seed_firewall() -> None:
    report = builder.verify_shipped_arena_traces()
    assert report["passed"] is True
    assert report["data_js_bytes"] < 250_000
    assert report["shipped_traces_count"] == 21

    expected_traces = builder.build_traces_payload(builder.LOCKED_TRAIN_FITTED_PARAMS)
    expected_ledger = builder.build_ledger_summary_payload()
    assert DATA_JS.read_text(encoding="utf-8") == builder.render_data_js(expected_traces, expected_ledger)
    assert SHIM_JS.read_text(encoding="utf-8") == builder.render_shim_js()

    for forbidden_seed in (0, 6, 26, 3000, 800_000, 900_000):
        with pytest.raises(ValueError):
            builder.assert_strict_train_seed(forbidden_seed)
    assert builder.assert_strict_train_seed(102_000) == 102_000


def test_esm_exports_and_globalthis_arena_boot_contract() -> None:
    node_bin = _find_node()
    script = f"""
const dataUrl = {json.dumps(DATA_JS.as_uri())};
const shimUrl = {json.dumps(SHIM_JS.as_uri())};

delete globalThis.CANARY_TIEBREAK_TRACES;
delete globalThis.CANARY_TIEBREAK_LEDGER_SUMMARY;

const dataMod = await import(dataUrl);
const bootResolvedData = dataMod.CANARY_TIEBREAK_TRACES || dataMod.tiebreakTraces || dataMod.default;
const globalAfterData = globalThis.CANARY_TIEBREAK_TRACES;
const ledgerAfterData = globalThis.CANARY_TIEBREAK_LEDGER_SUMMARY;

delete globalThis.CANARY_TIEBREAK_TRACES;
delete globalThis.CANARY_TIEBREAK_LEDGER_SUMMARY;

const shimMod = await import(shimUrl);
const bootResolvedShim = shimMod.CANARY_TIEBREAK_TRACES || shimMod.tiebreakTraces || shimMod.default;
const globalAfterShim = globalThis.CANARY_TIEBREAK_TRACES;
const ledgerAfterShim = globalThis.CANARY_TIEBREAK_LEDGER_SUMMARY;

const preEarly = bootResolvedData.getTiebreakDuelView(6, 2, false, "hard");
const preSealed = bootResolvedData.getTiebreakDuelView(6, 10, false, "hard");
const postUnlocked = bootResolvedData.getTiebreakDuelView(6, 10, true, "hard");
const heldoutBlocked = bootResolvedData.getTiebreakDuelView(800000, 5, true, "hard");
const cmpPre = bootResolvedData.getCaseComparison(26, 4, false, "hard");
const cmpPost = bootResolvedData.getCaseComparison(26, 21, true, "hard");

console.log(JSON.stringify({{
  dataKeys: Object.keys(dataMod).sort(),
  shimKeys: Object.keys(shimMod).sort(),
  sameApi:
    Boolean(bootResolvedData) &&
    bootResolvedData === dataMod.tiebreakTraces &&
    bootResolvedData === dataMod.default &&
    bootResolvedData === globalAfterData &&
    bootResolvedData === bootResolvedShim &&
    bootResolvedShim === shimMod.tiebreakTraces &&
    bootResolvedShim === shimMod.default &&
    bootResolvedShim === globalAfterShim,
  sameLedger:
    Boolean(ledgerAfterData) &&
    ledgerAfterData === dataMod.CANARY_TIEBREAK_LEDGER_SUMMARY &&
    ledgerAfterData === shimMod.CANARY_TIEBREAK_LEDGER_SUMMARY &&
    ledgerAfterData === ledgerAfterShim,
  hardSeeds: bootResolvedData.listSeeds("hard"),
  mediumSeeds: bootResolvedData.listSeeds("medium"),
  easySeeds: bootResolvedData.listSeeds("easy"),
  preEarly,
  preSealed,
  postUnlocked,
  heldoutBlocked,
  cmpPre,
  cmpPost
}}));
"""
    proc = subprocess.run(
        [node_bin, "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert proc.returncode == 0, f"node failed: {proc.stderr}\n{proc.stdout}"
    out = json.loads(proc.stdout.strip())

    expected_keys = [
        "CANARY_TIEBREAK_LEDGER_SUMMARY",
        "CANARY_TIEBREAK_TRACES",
        "default",
        "tiebreakTraces",
    ]
    assert out["dataKeys"] == expected_keys
    assert out["shimKeys"] == expected_keys
    assert out["sameApi"] is True
    assert out["sameLedger"] is True
    assert out["hardSeeds"] == [6, 26, 4, 18]
    assert out["mediumSeeds"] == [0, 12]
    assert out["easySeeds"] == [3000]

    pre_early = out["preEarly"]
    assert pre_early["available"] is True
    assert pre_early["final"] is None
    assert pre_early["status"] == "hunting"
    assert all(st["day"] <= 2 for st in pre_early["steps"])
    assert not (_collect_all_keys(pre_early) & set(builder.FORBIDDEN_STEP_KEYS))

    pre_sealed = out["preSealed"]
    assert pre_sealed["available"] is True
    assert pre_sealed["final"] is None
    assert pre_sealed["status"] == "sealed_accusation"
    assert pre_sealed["sealed_day"] == 7
    accuse_steps = [st for st in pre_sealed["steps"] if st["tool"] == "accuse"]
    assert len(accuse_steps) == 1
    assert accuse_steps[0]["sealed"] is True
    assert accuse_steps[0]["args"] == {"employee_id": "[SEALED]"}
    assert accuse_steps[0]["summary"] == "accuse([SEALED])"
    assert not (_collect_all_keys(pre_sealed) & set(builder.FORBIDDEN_STEP_KEYS))

    post_unlocked = out["postUnlocked"]
    assert post_unlocked["status"] == "unlocked"
    assert post_unlocked["final"]["accused"] == "e34"
    assert post_unlocked["final"]["correct"] is True
    unlocked_acc = [st for st in post_unlocked["steps"] if st["tool"] == "accuse"]
    assert len(unlocked_acc) == 1
    assert unlocked_acc[0]["sealed"] is False
    assert unlocked_acc[0]["args"] == {"employee": "e34"}

    assert out["heldoutBlocked"]["available"] is False
    assert out["heldoutBlocked"]["steps"] == []
    assert out["heldoutBlocked"]["final"] is None

    for ag_view in out["cmpPre"]["agents"].values():
        assert ag_view["final"] is None
        assert not (_collect_all_keys(ag_view) & set(builder.FORBIDDEN_STEP_KEYS))
    for ag_view in out["cmpPost"]["agents"].values():
        assert ag_view["final"] is not None


def test_zero_pre_end_truth_leaks_and_seed_split_disclosure() -> None:
    data_txt = DATA_JS.read_text(encoding="utf-8")
    traces_obj = builder._extract_const_payload(data_txt, "TIEBREAK_TRACES_PAYLOAD")
    ledger_obj = builder._extract_const_payload(data_txt, "TIEBREAK_LEDGER_SUMMARY_PAYLOAD")

    assert not builder._scan_recursive_invariants(traces_obj, "TIEBREAK_TRACES_PAYLOAD")
    assert not builder._scan_recursive_invariants(ledger_obj, "TIEBREAK_LEDGER_SUMMARY_PAYLOAD")

    assert traces_obj["seed_split_note"] == "dev_diagnostic_post_hoc_locked"
    disclosure = traces_obj["seed_split_disclosure"]
    assert "DEV_SEEDS only" in disclosure
    assert "post-hoc lock" in disclosure
    assert "671ed96 landed 28 s after 8fd4dec" in disclosure
    assert "not pre-registered" in disclosure
    assert "HELDOUT_SEEDS" in disclosure
    assert "JUDGE_SEEDS" in disclosure

    for tr in traces_obj["traces"]:
        seed = tr["seed"]
        assert seed in DEV_SEEDS
        assert seed not in HELDOUT_SEEDS
        assert seed not in JUDGE_SEEDS
        assert tr["seed_split_note"] == "dev_diagnostic_post_hoc_locked"
        for st in tr["steps"]:
            step_keys = _collect_all_keys(st)
            leaked = step_keys & set(builder.FORBIDDEN_STEP_KEYS)
            assert not leaked, f"pre-end leak keys {leaked} on {tr['tier']}:{seed}:{tr['agent']}"
            if st["tool"] == "accuse":
                assert st["args"] == {"employee_id": "[SEALED]"}
                assert st["summary"] == "accuse([SEALED])"

    ow = ledger_obj["open_weight_llm_summary"]
    eb = ledger_obj["compact_non_llm_empirical_bayes"]
    assert ow["bar_met"] is False
    assert ow["verified_improvements"] == 0
    run_ids = {r["run_id"] for r in ow["runs"]}
    assert {"WS4-v3-verda-s0-eval", "WS4-v3-8k-s0-3bb7", "WS4-base-backup-18ac", "X2-dagger-r1-e9ea"} <= run_ids
    assert eb["strictly_separated_from_open_weight_llm"] is True
    assert eb["paired_summary"] == "+1.028 [+0.915, +1.141]"


def test_shadow_env_and_in_memory_heldout_replay_parity() -> None:
    data_txt = DATA_JS.read_text(encoding="utf-8")
    traces_obj = builder._extract_const_payload(data_txt, "TIEBREAK_TRACES_PAYLOAD")

    assert len(traces_obj["traces"]) == 21
    for tr in traces_obj["traces"]:
        env = Env(tr["tier"], tr["seed"])
        for idx, st in enumerate(tr["steps"]):
            assert st["call_idx"] == idx
            assert st["day"] == env.day
            if st["tool"] == "accuse":
                res = env.call("accuse", {"employee": tr["final"]["accused"]})
            else:
                res = env.call(st["tool"], st["args"])
            assert bool(res.ok) is bool(st["ok"])
            assert abs(float(st["V"]) - env.visible_V()) <= 1e-9
        verdict = env.result(tr["agent"])
        assert abs(round(float(verdict.score), 4) - float(tr["final"]["score"])) <= 1e-9
        assert verdict.accused == tr["final"]["accused"]
        assert bool(verdict.correct) is bool(tr["final"]["correct"])
        assert int(verdict.final_day) == int(tr["final"]["final_day"])
        assert str(verdict.end_reason) == str(tr["final"]["end_reason"])

    parity = builder.verify_in_memory_heldout_parity(builder.LOCKED_TRAIN_FITTED_PARAMS)
    assert parity["episodes_verified"] == 27
    assert all(s in HELDOUT_SEEDS for s in parity["seeds_verified"])
    assert parity["after_mean_score"] > parity["before_mean_score"]
    assert parity["paired_mean_delta"] > 0.5
