from __future__ import annotations

import io
import json
from pathlib import Path
import tokenize
from typing import Any

import pytest

from canary.agents._common import inline_schema
from canary.agents.world_builder import WorldText, assert_no_truth
from canary.env import Env
from canary.eval import run_episode
from canary.gemini import read_ledger
from canary.gemini.leak_encodings import (
    SUPPORTED_ENCODINGS,
    audit_env_outputs,
    extract_env_secrets,
    scan_text_for_secret,
)
from canary.gemini.provenance import _inspect_run, scan_file_secrets
from canary.gemini.roles_dashboard import _scan_run_for_secrets
from canary.gemini import worldtext_thinking_eval as wte
from canary.llm.base import LLMResponse, MissingKeyError
from canary.solver.policy import SolverPolicy
from canary.text.lint import lint_messages, lint_text

ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "results" / "gemini_roles" / "world_text" / "thinking-calibration-carbon"
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
EXPECTED_LEVELS: tuple[str, ...] = ("low", "medium", "high")
EXPECTED_SEEDS: tuple[int, ...] = (6, 7)


@pytest.fixture(autouse=True)
def _hermetic_keyless_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    ledger_path = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(ledger_path))
    monkeypatch.setattr("canary.llm.base.load_env", lambda: None)
    return ledger_path


def test_clean_helpers_and_normalizers() -> None:
    dirty = {
        f"alpha {EM_DASH} beta": [
            f"one{EM_DASH}two",
            f"three {EN_DASH} four",
            f"five{EN_DASH}six",
        ]
    }
    cleaned = wte.clean_obj(dirty)
    dumped = json.dumps(cleaned)
    assert EM_DASH not in dumped
    assert EN_DASH not in dumped
    assert cleaned["alpha, beta"][0] == "one - two"
    assert cleaned["alpha, beta"][1] == "three - four"
    assert cleaned["alpha, beta"][2] == "five-six"

    assert wte.normalize_seeds("6,7") == [6, 7]
    assert wte.normalize_seeds("0") == [0]
    assert wte.normalize_seeds("n:3") == [0, 1, 2]
    assert wte.normalize_seeds("2-4") == [2, 3, 4]
    assert wte.normalize_seeds(5) == [5]
    with pytest.raises(ValueError):
        wte.normalize_seeds([])

    assert wte.normalize_levels("Low, medium, HIGH, low") == ["low", "medium", "high"]
    with pytest.raises(ValueError):
        wte.normalize_levels("invalid_level")
    with pytest.raises(ValueError):
        wte.normalize_levels("")


def test_lexical_diversity_and_tone_entropy_math() -> None:
    empty_lex = wte.compute_lexical_diversity([])
    assert empty_lex["type_token_ratio"] == 0.0
    assert empty_lex["distinct_bigrams"] == 0
    assert empty_lex["total_words"] == 0

    lex = wte.compute_lexical_diversity([
        "Alpha beta gamma delta.",
        "Alpha beta epsilon zeta.",
    ])
    assert lex["total_words"] == 8
    assert lex["unique_words"] == 6
    assert lex["type_token_ratio"] == pytest.approx(6 / 8)
    assert lex["total_bigrams"] == 6
    assert lex["distinct_bigrams"] == 5

    ent_zero, counts_zero = wte.compute_tone_shannon_entropy([])
    assert ent_zero == 0.0
    assert counts_zero == {}

    ent_single, counts_single = wte.compute_tone_shannon_entropy(["dry", "dry", "dry"])
    assert ent_single == 0.0
    assert counts_single == {"dry": 3}

    personas = [
        {"employee_id": "e00", "tone": "dry"},
        {"employee_id": "e01", "tone": "dry"},
        {"employee_id": "e02", "tone": "warm"},
        {"employee_id": "e03", "tone": "warm"},
        {"employee_id": "e04", "tone": "formal"},
        {"employee_id": "e05", "tone": "formal"},
        {"employee_id": "e06", "tone": "upbeat"},
        {"employee_id": "e07", "tone": "upbeat"},
    ]
    ent_uniform, counts_uniform = wte.compute_tone_shannon_entropy(personas)
    assert ent_uniform == pytest.approx(2.0)
    assert counts_uniform == {"dry": 2, "formal": 2, "upbeat": 2, "warm": 2}


def test_ensure_shared_tones_eliminates_singletons() -> None:
    wt = {
        "personas": [
            {"employee_id": "e00", "bio": "a", "tone": "dry"},
            {"employee_id": "e01", "bio": "b", "tone": "dry"},
            {"employee_id": "e02", "bio": "c", "tone": "warm"},
            {"employee_id": "e03", "bio": "d", "tone": "warm"},
            {"employee_id": "e04", "bio": "e", "tone": "blunt"},
            {"employee_id": "e05", "bio": "f", "tone": "unknown_tone"},
        ]
    }
    fixed = wte._ensure_shared_tones(wt, seed=6)
    _, counts = wte.compute_tone_shannon_entropy(fixed["personas"])
    assert all(c >= 2 for c in counts.values())


def test_keyless_client_resolution_and_monotonic_stub_thinking(_hermetic_keyless_env: Path) -> None:
    c_fallback = wte.resolve_thinking_client(
        "gemini:gemini-4-carbon",
        thinking_level="medium",
        run_id="test:fallback",
        require_live=False,
    )
    assert c_fallback.provider == "stub"

    with pytest.raises(MissingKeyError):
        wte.resolve_thinking_client(
            "gemini:gemini-4-carbon",
            thinking_level="medium",
            run_id="test:strict",
            require_live=True,
        )

    sim_thinking: dict[str, int] = {}
    ans_schema = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}
    for lvl in EXPECTED_LEVELS:
        cli = wte.resolve_thinking_client("stub", thinking_level=lvl, run_id=f"test:{lvl}")
        resp = cli.chat(
            [{"role": "user", "content": "cooperative interview"}],
            response_schema=ans_schema,
        )
        parsed = json.loads(resp.text)
        assert parsed["answer"]
        sim_thinking[lvl] = cli.usage_totals["thinking"]

    assert sim_thinking["low"] < sim_thinking["medium"] < sim_thinking["high"]
    entries = read_ledger([_hermetic_keyless_env])
    assert len(entries) == 3
    assert all(e["feature"] == "worldtext_thinking" for e in entries)


def test_metered_thinking_client_validation_and_fence_unwrapping() -> None:
    class ScriptedClient:
        provider = "gemini"
        model = "gemini-4-carbon"

        def __init__(self, payloads: list[str]):
            self.payloads = list(payloads)
            self.calls = 0

        def chat(self, messages: list[dict[str, Any]], **kw: Any) -> LLMResponse:
            idx = min(self.calls, len(self.payloads) - 1)
            self.calls += 1
            return LLMResponse(
                text=self.payloads[idx],
                tool_calls=[],
                usage={"in": 40, "out": 20, "thinking": 15, "cached": 0, "cost_usd": 0.001},
                raw=None,
            )

    ans_schema = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}
    bad_leak = json.dumps({"answer": "Maybe a mole leaked the Q4 sheet."})
    fenced_good = (
        "```json\n"
        + json.dumps({"answer": f"Reviewed Q4 forecast {EM_DASH} logged timestamps {EN_DASH} happy to help."})
        + "\n```"
    )
    scripted = ScriptedClient([bad_leak, fenced_good])
    metered = wte.MeteredThinkingClient(scripted, thinking_level="high")
    resp = metered.chat([{"role": "user", "content": "Ask about recent docs."}], response_schema=ans_schema)
    data = json.loads(resp.text)
    assert scripted.calls == 2
    assert metered.validation_retries == 1
    assert EM_DASH not in data["answer"]
    assert EN_DASH not in data["answer"]
    assert "mole" not in data["answer"].lower()
    assert metered.usage_totals["calls"] == 2
    assert metered.usage_totals["thinking"] == 30

    wt_schema = inline_schema(WorldText)
    assert "$defs" not in json.dumps(wt_schema)


def test_stub_end_to_end_cli_and_cache_reuse(tmp_path: Path) -> None:
    out_dir = tmp_path / "stub_calibration"
    rc = wte.main([
        "--llm",
        "stub",
        "--tier",
        "easy",
        "--seeds",
        "0",
        "--levels",
        "low,medium,high",
        "--jobs",
        "2",
        "--out",
        str(out_dir),
    ])
    assert rc == 0

    for fname in ("meta.json", "levels_comparison.json", "summary.md"):
        fp = out_dir / fname
        assert fp.is_file()
        txt = fp.read_text(encoding="utf-8")
        assert txt.strip()
        assert EM_DASH not in txt
        assert EN_DASH not in txt
        assert scan_file_secrets(fp, ROOT) == []

    meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    comp = json.loads((out_dir / "levels_comparison.json").read_text(encoding="utf-8"))
    assert meta["role"] == "world_text"
    assert meta["subrole"] == "thinking_level_calibration"
    assert meta["model_id"] == "stub"
    assert meta["count"] == 3
    assert meta["llm_ok_count"] == 3
    assert meta["fallback_count"] == 0
    assert meta["truth_leak_violations"] == 0
    assert meta["lint_violations"] == 0
    assert meta["leak_encoding_violations"] == 0
    assert meta["solver_parity_ok"] is True
    assert comp["non_leak_summary"]["ok"] is True
    assert comp["non_leak_summary"]["supported_encodings_count"] == len(SUPPORTED_ENCODINGS)
    assert comp["levels"]["low"]["thinking_tokens"] < comp["levels"]["medium"]["thinking_tokens"]
    assert comp["levels"]["medium"]["thinking_tokens"] < comp["levels"]["high"]["thinking_tokens"]

    def _forbid_client(**_kw: Any) -> wte.MeteredThinkingClient:
        raise AssertionError("cache reuse should not invoke client_factory")

    reused = wte.run_thinking_calibration(
        llm_spec="stub",
        tier="easy",
        seeds=[0],
        levels=["low", "medium", "high"],
        out_dir=out_dir,
        jobs=1,
        reuse_cache=True,
        client_factory=_forbid_client,
    )
    assert reused["meta"]["count"] == 3
    assert reused["meta"]["solver_parity_ok"] is True


def test_committed_live_run_provenance_and_metrics() -> None:
    assert RUN_DIR.is_dir()
    for fname in ("meta.json", "levels_comparison.json", "summary.md"):
        fpath = RUN_DIR / fname
        assert fpath.is_file(), f"missing {fname}"
        raw = fpath.read_text(encoding="utf-8")
        assert raw.strip()
        assert EM_DASH not in raw
        assert EN_DASH not in raw
        assert scan_file_secrets(fpath, ROOT) == []

    assert _scan_run_for_secrets(RUN_DIR) is False

    prov = _inspect_run(RUN_DIR / "meta.json", ROOT, ROOT / "data" / "runs" / "committed" / "v1.4")
    assert prov["verified"] is True, f"provenance failed: {prov}"
    assert prov["errors"] == []
    assert prov["secret_leaks"] == []

    meta = json.loads((RUN_DIR / "meta.json").read_text(encoding="utf-8"))
    comp = json.loads((RUN_DIR / "levels_comparison.json").read_text(encoding="utf-8"))

    assert meta["role"] == "world_text"
    assert meta["subrole"] == "thinking_level_calibration"
    assert meta["feature"] == "worldtext_thinking"
    assert meta["model_id"] == "gemini-4-carbon"
    assert meta["llm_spec"] == "gemini:gemini-4-carbon"
    assert meta["tiers_version"] == "v1.4"
    assert meta["tier"] == "medium"
    assert meta["seeds"] == list(EXPECTED_SEEDS)
    assert meta["thinking_levels"] == list(EXPECTED_LEVELS)
    assert meta["count"] == 6
    assert meta["n_worlds"] == 6
    assert meta["llm_ok_count"] == 6
    assert meta["llm_ok_rate"] == 1.0
    assert meta["fallback_count"] == 0
    assert meta["truth_leak_violations"] == 0
    assert meta["lint_violations"] == 0
    assert meta["leak_encoding_violations"] == 0
    assert meta["n_supported_encodings_checked"] == len(SUPPORTED_ENCODINGS)
    assert meta["solver_parity_ok"] is True
    assert meta["fake_env"] is False
    assert meta["smoke"] is False

    usage = meta["usage"]
    assert usage["calls"] == 24
    assert usage["in"] > 0
    assert usage["out"] > 0
    assert usage["thinking"] > 0
    assert usage["total_tokens"] == usage["in"] + usage["out"] + usage["thinking"]
    assert usage["cost_usd"] > 0.0

    lvls = comp["levels"]
    assert set(lvls.keys()) == set(EXPECTED_LEVELS)
    assert lvls["low"]["thinking_tokens"] < lvls["medium"]["thinking_tokens"] < lvls["high"]["thinking_tokens"]
    for lvl in EXPECTED_LEVELS:
        row = lvls[lvl]
        assert row["llm_ok_rate"] == 1.0
        assert row["n_llm_personas_over_20"] == "20/20"
        assert row["fallback_count"] == 0
        assert row["truth_leak_violations"] == 0
        assert row["lint_violations"] == 0
        assert row["leak_encoding_violations"] == 0
        assert row["solver_accuracy"] == 1.0
        assert row["type_token_ratio"] > 0.4
        assert row["distinct_bigrams"] > 500
        assert row["tone_shannon_entropy"] > 1.5

    sp = comp["solver_parity"]
    assert sp["ok"] is True
    assert sp["cross_level_accuracy_spread"] == 0.0
    assert sp["cross_level_score_spread"] <= 0.10


@pytest.mark.parametrize("level", EXPECTED_LEVELS)
@pytest.mark.parametrize("seed", EXPECTED_SEEDS)
def test_committed_world_cells_pass_non_leak_and_solver_parity(level: str, seed: int) -> None:
    wt_path = RUN_DIR / "worlds" / level / "medium" / f"{seed}.worldtext.json"
    tx_path = RUN_DIR / "worlds" / level / "medium" / f"{seed}.text.json"
    assert wt_path.is_file(), f"missing {wt_path}"
    assert tx_path.is_file(), f"missing {tx_path}"

    wt_raw = wt_path.read_text(encoding="utf-8")
    tx_raw = tx_path.read_text(encoding="utf-8")
    for fp, raw in ((wt_path, wt_raw), (tx_path, tx_raw)):
        assert EM_DASH not in raw
        assert EN_DASH not in raw
        assert scan_file_secrets(fp, ROOT) == []

    wt = json.loads(wt_raw)
    tx = json.loads(tx_raw)

    ref_env = Env("medium", seed)
    world = ref_env._world
    mole_id = world.mole
    _, world_secrets = extract_env_secrets(ref_env)
    secret_targets = [mole_id, *world_secrets]

    assert wt["model_id"] == "gemini-4-carbon"
    assert wt["thinking_level"] == level
    assert wt["meta"]["llm_ok"] is True
    assert wt["meta"]["n_fallback_personas"] == 0
    assert len(wt["personas"]) == len(world.employees) == 20

    assert_no_truth(wt, world)
    assert_no_truth(tx, world)
    assert scan_text_for_secret(wt, world_secrets) == []
    assert scan_text_for_secret(tx, world_secrets) == []

    prose_items = (
        [wt["company_blurb"]]
        + [p["bio"] for p in wt["personas"]]
        + [d["culture"] for d in wt["departments"]]
        + list(wt["chatter_templates"])
    )
    for item in prose_items:
        assert item.strip()
        assert lint_text(item) == []
        assert_no_truth(item, world)
        assert scan_text_for_secret(item, secret_targets) == []

    day1_msgs = tx["days"]["1"]
    assert len(day1_msgs) >= 5
    assert lint_messages(day1_msgs) == []
    assert_no_truth(day1_msgs, world)
    assert scan_text_for_secret(day1_msgs, secret_targets) == []

    interviews = tx["interviews"]
    assert len(interviews) == 2
    assert any("|cooperative|" in k for k in interviews)
    assert any("|evasive|" in k for k in interviews)
    for ans in interviews.values():
        assert ans.strip()
        assert lint_text(ans) == []
        assert_no_truth(ans, world)
        assert scan_text_for_secret(ans, secret_targets) == []

    provider = wte.ThinkingCalibratedWorldProvider(
        wt,
        day1_messages=day1_msgs,
        interviews=interviews,
        name=f"gemini-thinking-{level}",
    )
    audit = wte.audit_cell_non_leak(
        tier="medium",
        seed=seed,
        wt=wt,
        day1_messages=day1_msgs,
        interviews=interviews,
        provider=provider,
    )
    assert audit["ok"] is True
    assert audit["encodings_checked"] == len(SUPPORTED_ENCODINGS)

    solver_env = Env("medium", seed, text_provider=provider)
    ep = run_episode(solver_env, SolverPolicy())
    assert ep.correct is True
    assert ep.accused == mole_id
    assert audit_env_outputs(solver_env, step_episode=False) == []


def test_source_files_have_no_comments_em_dashes_or_secrets() -> None:
    targets = [
        ROOT / "canary" / "gemini" / "worldtext_thinking_eval.py",
        Path(__file__).resolve(),
    ]
    for path in targets:
        src = path.read_text(encoding="utf-8")
        assert EM_DASH not in src, f"em dash in {path}"
        assert EN_DASH not in src, f"en dash in {path}"
        assert ("\\" + "u2014") not in src, f"escaped em dash in {path}"
        assert ("\\" + "u2013") not in src, f"escaped en dash in {path}"
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == [], f"found comment in {path}: {comments}"
        assert scan_file_secrets(path, ROOT) == []
