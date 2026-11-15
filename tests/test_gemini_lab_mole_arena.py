from __future__ import annotations

import io
import json
from pathlib import Path
import re
import statistics
import sys
import tokenize
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.env import Env
from canary.mole.dsl import MoleStrategy
from canary.rules import JUDGE_SEEDS

ADAPTIVE_MOLE_DIR = ROOT / "results" / "gemini" / "roles_carbon" / "adaptive_mole"
EXPECTED_SCOPE = "arena mode, not the judged v1.4 environment"
MAX_CATCHABILITY_BYTES = 300 * 1024

EXPECTED_ARENA_RUNS: tuple[tuple[str, str, tuple[int, ...]], ...] = (
    ("arena-live-carbon-med012", "medium", (0, 1, 2)),
    ("arena-live-carbon-med345", "medium", (3, 4, 5)),
    ("arena-live-carbon-med678", "medium", (6, 7, 8)),
    ("arena-live-carbon-med9_10_11", "medium", (9, 10, 11)),
    ("arena-live-carbon-hard012", "hard", (0, 1, 2)),
    ("arena-live-carbon-hard345", "hard", (3, 4, 5)),
    ("arena-live-carbon-hard678", "hard", (6, 7, 8)),
    ("arena-live-carbon-hard9_10_11", "hard", (9, 10, 11)),
)

ARENA_FILES = frozenset({"meta.json", "episodes.json", "mole_decisions.jsonl", "summary.md"})
CATCHABILITY_DIR_NAME = "catchability-audit-carbon"
CATCHABILITY_FILES = frozenset({"meta.json", "audit_report.json", "summary.md"})
INVESTIGATORS = ("solver", "grok_tactics", "obvious_heuristic")

ALLOWED_LOG_KEYS = frozenset(
    {"day", "error", "frame", "investigator", "leak", "mole_view", "reason", "rejected", "seed", "tier"}
)
ALLOWED_VIEW_KEYS = frozenset(
    {
        "can_leak",
        "day",
        "days_since_last_leak",
        "decoy",
        "docs",
        "held_docs",
        "i_am_restricted",
        "leakable",
        "n_restricted_colleagues",
        "peers",
        "recent_low_recipient_docs",
        "restricted_peers",
        "select_weights",
    }
)
ALLOWED_DOC_KEYS = frozenset({"age_days", "doc_id", "recipient_count", "title"})
FORBIDDEN_PRIVILEGED_KEYS = frozenset(
    {
        "is_canary",
        "canary",
        "canary_id",
        "variant",
        "variants",
        "true_variant",
        "belief",
        "beliefs",
        "posterior",
        "posteriors",
        "investigator_belief",
        "world_secret",
        "ledger_token",
        "api_key",
    }
)

FORBIDDEN_DASHES: tuple[str, ...] = (
    chr(0x2014),
    chr(0x2013),
    chr(0x2012),
    chr(0x2015),
)

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<![0-9A-Za-z+/_-])" + "AI" + "za" + r"[0-9A-Za-z_-]{16,}"),
    re.compile(r"(?<![0-9A-Za-z+/_-])" + "s" + "k-" + r"(?:proj-|ant-|live-|test-|svcacct-)?[0-9A-Za-z_-]{12,}"),
    re.compile(r"(?<![0-9A-Za-z_])" + "ya" + r"29\.[0-9A-Za-z_-]{12,}"),
    re.compile(
        r"\b(?:GEMINI_API_KEY|GOOGLE_API_KEY|GOOGLE_GENERATIVE_AI_API_KEY|"
        r"OPENAI_API_KEY|ANTHROPIC_API_KEY|XAI_API_KEY|"
        r"CANARY_WORLD_SECRET|CANARY_LEDGER_TOKEN)\b"
        r"[\"']?[ \t]*[:=][ \t]*[^\s\"',}\]]{4,}"
    ),
)


@pytest.fixture(autouse=True)
def _keyless_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)


def _collect_keys(obj: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            found.add(str(k))
            found.update(_collect_keys(v))
    elif isinstance(obj, list):
        for item in obj:
            found.update(_collect_keys(item))
    return found


def test_arena_test_file_has_zero_comments_and_zero_forbidden_dashes() -> None:
    src = Path(__file__).read_text(encoding="utf-8")
    assert chr(0x23) not in src
    tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    assert not [tok for tok in tokens if tok.type == tokenize.COMMENT]
    for dash in FORBIDDEN_DASHES:
        assert dash not in src


def test_eight_live_arena_runs_provenance_and_paired_scores() -> None:
    assert len(EXPECTED_ARENA_RUNS) == 8
    judge_set = set(JUDGE_SEEDS)

    adaptive_all: list[dict[str, Any]] = []
    default_all: list[dict[str, Any]] = []
    total_calls = 0
    total_decisions = 0

    for run_name, expected_tier, expected_seeds in EXPECTED_ARENA_RUNS:
        run_dir = ADAPTIVE_MOLE_DIR / run_name
        assert run_dir.is_dir(), f"missing run dir: {run_dir}"
        files = frozenset(p.name for p in run_dir.iterdir() if p.is_file())
        assert files == ARENA_FILES

        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        assert meta["role"] == "adaptive_mole"
        assert meta["model_id"] == "gemini-4-carbon"
        assert meta["llm_spec"] == "gemini:gemini-4-carbon"
        assert meta["environment_scope"] == EXPECTED_SCOPE
        assert meta["tier"] == expected_tier
        assert tuple(meta["seeds"]) == expected_seeds
        assert not (set(expected_seeds) & judge_set)
        assert COMMIT_RE.fullmatch(meta["commit"])
        assert meta["solvability_verified"] is True
        assert meta["mole_llm_errors"] == 0

        usage = meta["usage"]
        assert usage["calls"] == meta["mole_decisions_count"] > 0
        assert usage["in"] > 0
        assert usage["out"] > 0
        assert usage["thinking"] > 0
        assert usage["cost_usd"] > 0.0
        total_calls += int(usage["calls"])

        ep_doc = json.loads((run_dir / "episodes.json").read_text(encoding="utf-8"))
        assert ep_doc["model_id"] == "gemini-4-carbon"
        assert ep_doc["tier"] == expected_tier
        assert tuple(ep_doc["seeds"]) == expected_seeds

        adaptive_eps = ep_doc["adaptive_mole"]
        default_eps = ep_doc["default_mole"]
        assert len(adaptive_eps) == 9
        assert len(default_eps) == 9
        adaptive_all.extend(adaptive_eps)
        default_all.extend(default_eps)

        decisions = [
            json.loads(line)
            for line in (run_dir / "mole_decisions.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(decisions) == meta["mole_decisions_count"]
        total_decisions += len(decisions)

        summary_text = (run_dir / "summary.md").read_text(encoding="utf-8")
        assert EXPECTED_SCOPE in summary_text
        assert meta["commit"] in summary_text

    assert total_calls == 696
    assert total_decisions == 696
    assert len(adaptive_all) == 72
    assert len(default_all) == 72

    for inv in INVESTIGATORS:
        a_rows = [r for r in adaptive_all if r["investigator"] == inv]
        d_rows = [r for r in default_all if r["investigator"] == inv]
        assert len(a_rows) == 24
        assert len(d_rows) == 24

    sol_adapt = [float(r["score"]) for r in adaptive_all if r["investigator"] == "solver"]
    sol_def = [float(r["score"]) for r in default_all if r["investigator"] == "solver"]
    grok_adapt = [float(r["score"]) for r in adaptive_all if r["investigator"] == "grok_tactics"]
    grok_def = [float(r["score"]) for r in default_all if r["investigator"] == "grok_tactics"]
    heur_adapt = [float(r["score"]) for r in adaptive_all if r["investigator"] == "obvious_heuristic"]

    assert round(statistics.mean(sol_adapt), 4) == pytest.approx(0.4825, abs=1e-4)
    assert round(statistics.mean(sol_def), 4) == pytest.approx(0.6008, abs=1e-4)
    assert sum(1 for r in adaptive_all if r["investigator"] == "solver" and r["correct"]) == 20
    assert round(statistics.mean(grok_adapt), 4) == pytest.approx(0.0, abs=1e-4)
    assert round(statistics.mean(grok_def), 4) == pytest.approx(0.4938, abs=1e-3)
    assert round(statistics.mean(heur_adapt), 4) == pytest.approx(-0.9233, abs=1e-3)
    assert statistics.mean(sol_adapt) > statistics.mean(grok_adapt) > statistics.mean(heur_adapt)


def test_live_arena_mole_decisions_enforce_view_isolation_and_env_parity() -> None:
    checked_views = 0
    env_peers_cache: dict[tuple[str, int], tuple[set[str], str]] = {}

    for run_name, expected_tier, _ in EXPECTED_ARENA_RUNS:
        dec_path = ADAPTIVE_MOLE_DIR / run_name / "mole_decisions.jsonl"
        rows = [json.loads(line) for line in dec_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert rows

        for row in rows:
            assert set(row.keys()) <= ALLOWED_LOG_KEYS
            assert not (_collect_keys(row) & FORBIDDEN_PRIVILEGED_KEYS)
            assert row["tier"] == expected_tier
            assert row["investigator"] in INVESTIGATORS
            assert row["error"] is None
            assert row["rejected"] == []

            view = row["mole_view"]
            assert isinstance(view, dict)
            assert set(view.keys()) <= ALLOWED_VIEW_KEYS
            held_docs = view["held_docs"]
            assert isinstance(held_docs, list)
            held_ids: set[str] = set()
            for doc in held_docs:
                assert set(doc.keys()) == ALLOWED_DOC_KEYS
                assert isinstance(doc["recipient_count"], int) and doc["recipient_count"] >= 1
                held_ids.add(doc["doc_id"])

            peers = set(view["peers"])
            assert isinstance(view["can_leak"], bool)
            if row["leak"] is not None:
                assert row["leak"] in held_ids
            if row["frame"] is not None:
                assert row["frame"] in peers

            env_key = (expected_tier, int(row["seed"]))
            if env_key not in env_peers_cache:
                env = Env(tier=expected_tier, seed=int(row["seed"]))
                emp_ids = set(env._world.ids)
                mole_id = env._world.mole
                assert mole_id not in peers
                env_peers_cache[env_key] = (emp_ids - {mole_id}, env._world.decoy)
            expected_peers, expected_decoy = env_peers_cache[env_key]
            assert peers == expected_peers
            assert view["decoy"] == expected_decoy
            checked_views += 1

    assert checked_views == 696


def test_catchability_audit_budget_isolation_and_dsl_strategies() -> None:
    audit_dir = ADAPTIVE_MOLE_DIR / CATCHABILITY_DIR_NAME
    assert audit_dir.is_dir()
    files = frozenset(p.name for p in audit_dir.iterdir() if p.is_file())
    assert files == CATCHABILITY_FILES

    folder_bytes = sum(p.stat().st_size for p in audit_dir.rglob("*") if p.is_file())
    assert folder_bytes <= MAX_CATCHABILITY_BYTES

    meta = json.loads((audit_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["role"] == "adaptive_mole"
    assert meta["subrole"] == "catchability_isolation_audit"
    assert meta["model_id"] == "gemini-4-carbon"
    assert meta["environment_scope"] == EXPECTED_SCOPE
    assert COMMIT_RE.fullmatch(meta["commit"])
    assert meta["confirmation_seeds"] == list(range(20, 40))
    assert not (set(meta["confirmation_seeds"]) & set(JUDGE_SEEDS))
    assert meta["isolation_violations"] == 0
    assert meta["file_secret_leaks"] == 0
    assert meta["data_hygiene_violations"] == 0
    assert meta["n_runs_audited"] == 14
    assert meta["n_strategies_audited"] == 42
    assert meta["n_decisions_audited"] == 573
    assert meta["n_views_checked"] == 8783
    assert meta["n_catchability_passed"] == 45
    assert meta["n_catchability_targets"] == 50
    assert meta["catchability_compliance_rate"] == pytest.approx(0.9)
    assert meta["live_solvability_compliance_rate"] == pytest.approx(1.0)
    assert meta["forensic_cross_check_agreement_rate"] == pytest.approx(1.0)
    assert meta["zero_privileged_canary_awareness_confirmed"] is True
    assert meta["usage"]["calls"] == 7
    assert meta["usage"]["cost_usd"] > 0.0

    report = json.loads((audit_dir / "audit_report.json").read_text(encoding="utf-8"))
    totals = report["totals"]
    assert totals["isolation_violations"] == 0
    assert totals["file_secret_leaks"] == 0
    assert totals["data_hygiene_violations"] == 0
    assert totals["n_catchability_passed"] == 45
    assert totals["n_catchability_targets"] == 50
    assert len(report["runs"]) == 14
    assert len(report["strategies"]) == 42
    assert report["forensic_audit"]["zero_privileged_canary_awareness_confirmed"] is True
    assert report["forensic_audit"]["model_id"] == "gemini-4-carbon"

    for strat_row in report["strategies"]:
        assert strat_row["isolation_passed"] is True
        assert strat_row["isolation_violations"] == []
        parsed = MoleStrategy.from_json(strat_row["strategy_json"])
        assert isinstance(parsed, MoleStrategy)

    summary_text = (audit_dir / "summary.md").read_text(encoding="utf-8")
    assert EXPECTED_SCOPE in summary_text
    assert meta["commit"] in summary_text


def test_exported_arena_and_catchability_files_have_no_secrets_or_forbidden_dashes() -> None:
    target_dirs = [ADAPTIVE_MOLE_DIR / name for name, _, _ in EXPECTED_ARENA_RUNS] + [
        ADAPTIVE_MOLE_DIR / CATCHABILITY_DIR_NAME
    ]
    files_checked = 0
    for folder in target_dirs:
        for path in sorted(p for p in folder.rglob("*") if p.is_file()):
            text = path.read_text(encoding="utf-8")
            for dash in FORBIDDEN_DASHES:
                assert dash not in text, f"forbidden dash in {path}"
            for pattern in SECRET_PATTERNS:
                assert not pattern.search(text), f"secret match in {path}"
            files_checked += 1
    assert files_checked == 35
