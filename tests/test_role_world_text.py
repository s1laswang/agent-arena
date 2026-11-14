from __future__ import annotations

import io
import json
from pathlib import Path
import tokenize
from types import SimpleNamespace

import pytest

from canary.agents.world_builder import GeminiWorldText, assert_no_truth
from canary.env import Env
from canary.eval import run_episode
from canary.gemini.ledger import read_ledger
from canary.gemini.provenance import _inspect_run, scan_file_secrets
from canary.gemini.roles_dashboard import _scan_run_for_secrets
from canary.solver.policy import SolverPolicy
from canary.text.lint import lint_messages, lint_text
from scripts import run_role_world_text as mod

ROOT = Path(__file__).resolve().parents[1]
COMMITTED_DIR = ROOT / "results" / "gemini_roles" / "world_text" / "carbon-v14-seeds012"
EXPECTED_SPECS = (("medium", 0), ("medium", 1), ("medium", 2), ("hard", 0), ("hard", 1))


def test_cli_stub_runs_all_five_worlds_keylessly(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    ledger_file = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(ledger_file))
    out_dir = tmp_path / "stub_out"

    rc = mod.main(["--llm", "stub", "--out", str(out_dir), "--jobs", "2"])
    assert rc == 0

    meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    samples = json.loads((out_dir / "samples.json").read_text(encoding="utf-8"))
    summary = (out_dir / "summary.md").read_text(encoding="utf-8")

    assert meta["role"] == "world_text"
    assert meta["subrole"] == "company_personas_chatter"
    assert meta["model_id"] == "stub"
    assert meta["n_worlds"] == 5
    assert meta["llm_ok_count"] == 5
    assert meta["truth_leak_violations"] == 0
    assert meta["lint_violations"] == 0
    assert meta["gemini_provider_fallbacks"] == 0
    assert meta["solver_episodes_verified"] == 5
    assert meta["solver_all_clean"] is True
    assert meta["solver_accuracy"] == 1.0
    assert meta["solver_mean_score"] > 0.0
    assert meta["usage"]["calls"] == 25
    assert meta["usage"]["in"] > 0
    assert meta["usage"]["out"] > 0
    assert len(samples["worlds"]) == 5
    assert summary.startswith("# Role 1: World Text & Workplace Chatter Run")
    assert "\u2014" not in summary
    assert "\u2013" not in summary

    for tier, seed in EXPECTED_SPECS:
        wt_path = out_dir / "worlds" / tier / f"{seed}.worldtext.json"
        txt_path = out_dir / "worlds" / tier / f"{seed}.text.json"
        assert wt_path.is_file()
        assert txt_path.is_file()
        wt = json.loads(wt_path.read_text(encoding="utf-8"))
        cached = json.loads(txt_path.read_text(encoding="utf-8"))
        world = Env(tier, seed)._world
        assert_no_truth(wt, world)
        assert set(cached["days"]) == {"1", "2"}
        assert len(cached["interviews"]) == 2
        for d_key in ("1", "2"):
            assert not lint_messages(cached["days"][d_key])
            assert_no_truth(cached["days"][d_key], world)
        for ans in cached["interviews"].values():
            assert not lint_text(ans)
            assert_no_truth(ans, world)

    ledger_rows = read_ledger([ledger_file])
    assert len(ledger_rows) == 25
    assert all(r["feature"] == "world_text" for r in ledger_rows)


def test_public_facts_isolation_never_sends_truth_to_client(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    captured_prompts: list[str] = []

    class InspectingStub(mod.DeterministicWorldTextStub):
        def _chat(self, messages, tools, temperature, response_schema, max_tokens, seed):
            for m in messages:
                if m.get("role") == "user":
                    captured_prompts.append(str(m.get("content") or ""))
            return super()._chat(messages, tools, temperature, response_schema, max_tokens, seed)

    world = Env("medium", 0)._world
    res = mod.run_single_world(
        tier="medium",
        seed=0,
        llm_spec="stub",
        worlds_dir=tmp_path / "worlds",
        run_id_prefix="iso",
        client_factory=lambda **kw: mod.MeteredWorldTextClient(InspectingStub()),
    )
    assert res["world_builder"]["llm_ok"] is True
    assert res["integrity"]["truth_leak_violations"] == 0
    assert res["integrity"]["lint_violations"] == 0
    assert len(captured_prompts) == 5
    for p_txt in captured_prompts:
        assert '"mole"' not in p_txt
        assert '"mole_strategy"' not in p_txt
        assert '"ledger"' not in p_txt
    assert world.mole in {e.id for e in world.employees}


def test_metered_client_scrubs_dashes_and_retries_invalid_gemini_output(monkeypatch):
    monkeypatch.setattr(mod.time, "sleep", lambda _: None)

    class FakeGeminiBackend:
        provider = "gemini"
        model = "gemini-4-carbon"

        def __init__(self):
            self.calls = 0

        def chat(self, messages, **kw):
            self.calls += 1
            if self.calls == 1:
                bad = {"answer": "Wait\u2014maybe a spy accessed the sheet."}
                return SimpleNamespace(
                    text=json.dumps(bad),
                    tool_calls=[],
                    usage={"in": 100, "out": 25, "cost_usd": 0.0005},
                    raw=None,
                )
            good = {"answer": "I reviewed Q1 forecast\u2014nothing unusual\u2013happy to share logs."}
            return SimpleNamespace(
                text=json.dumps(good),
                tool_calls=[],
                usage={"in": 110, "out": 30, "cost_usd": 0.0006},
                raw=None,
            )

    backend = FakeGeminiBackend()
    client = mod.MeteredWorldTextClient(backend)
    resp = client.chat(
        [{"role": "system", "content": "Interview."}, {"role": "user", "content": "Ask e00."}],
        response_schema={"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]},
    )
    parsed = json.loads(resp.text)
    assert backend.calls == 2
    assert "\u2014" not in parsed["answer"]
    assert "\u2013" not in parsed["answer"]
    assert not lint_text(parsed["answer"])
    assert client.usage_totals["calls"] == 2
    assert client.usage_totals["in"] == 210
    assert client.usage_totals["out"] == 55


def test_no_code_comments_or_em_dashes_or_secrets():
    for rel in ("scripts/run_role_world_text.py", "tests/test_role_world_text.py"):
        fp = ROOT / rel
        src = fp.read_text(encoding="utf-8")
        assert "\u2014" not in src, f"em dash in {rel}"
        assert "\u2013" not in src, f"en dash in {rel}"
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [t for t in tokens if t.type == tokenize.COMMENT]
        assert not comments, f"found code comment in {rel}: {comments[0]}"
        assert scan_file_secrets(fp, ROOT) == []


@pytest.mark.skipif(not COMMITTED_DIR.exists(), reason="committed carbon world_text run folder not generated yet")
def test_committed_carbon_world_text_run_artifacts(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")

    for fname in ("meta.json", "summary.md", "samples.json"):
        fpath = COMMITTED_DIR / fname
        assert fpath.is_file(), f"missing {fname}"
        txt = fpath.read_text(encoding="utf-8")
        assert txt.strip(), f"empty {fname}"
        assert "\u2014" not in txt, f"em dash in {fname}"
        assert "\u2013" not in txt, f"en dash in {fname}"
        assert scan_file_secrets(fpath, ROOT) == []

    assert _scan_run_for_secrets(COMMITTED_DIR) is False

    meta = json.loads((COMMITTED_DIR / "meta.json").read_text(encoding="utf-8"))
    assert meta["role"] == "world_text"
    assert meta["model_id"] == "gemini-4-carbon"
    assert len(meta["commit"]) >= 7 and meta["commit"] != "unknown"
    assert meta["timestamp"]
    assert meta["command"]
    assert meta["n_worlds"] == 5
    assert meta["llm_ok_count"] == 5
    assert meta["truth_leak_violations"] == 0
    assert meta["lint_violations"] == 0
    assert meta["gemini_provider_fallbacks"] == 0
    assert meta["usage"]["calls"] >= 25
    assert meta["usage"]["in"] > 0
    assert meta["usage"]["out"] > 0
    assert meta["usage"]["cost_usd"] > 0.0

    prov = _inspect_run(COMMITTED_DIR / "meta.json", ROOT, ROOT / "data" / "runs" / "committed" / "v1.4")
    assert prov["verified"] is True, f"provenance failed: {prov}"
    assert prov["errors"] == []

    samples = json.loads((COMMITTED_DIR / "samples.json").read_text(encoding="utf-8"))
    assert len(samples["worlds"]) == 5

    for tier, seed in EXPECTED_SPECS:
        wt_path = COMMITTED_DIR / "worlds" / tier / f"{seed}.worldtext.json"
        txt_path = COMMITTED_DIR / "worlds" / tier / f"{seed}.text.json"
        assert wt_path.is_file(), f"missing {wt_path}"
        assert txt_path.is_file(), f"missing {txt_path}"
        wt_raw = wt_path.read_text(encoding="utf-8")
        txt_raw = txt_path.read_text(encoding="utf-8")
        assert "\u2014" not in wt_raw and "\u2013" not in wt_raw
        assert "\u2014" not in txt_raw and "\u2013" not in txt_raw

        wt = json.loads(wt_raw)
        assert wt["meta"]["llm_ok"] is True
        assert wt["meta"]["n_fallback_personas"] == 0

        ref_env = Env(tier, seed)
        world = ref_env._world
        assert_no_truth(wt, world)

        cached = json.loads(txt_raw)
        assert set(cached["days"]) == {"1", "2"}
        assert len(cached["interviews"]) == 2
        for d_key in ("1", "2"):
            msgs = cached["days"][d_key]
            assert len(msgs) >= 1
            assert not lint_messages(msgs)
            assert_no_truth(msgs, world)
        has_coop = any("|cooperative|" in k for k in cached["interviews"])
        has_evas = any("|evasive|" in k for k in cached["interviews"])
        assert has_coop and has_evas
        for ans in cached["interviews"].values():
            assert ans.strip()
            assert not lint_text(ans)
            assert_no_truth(ans, world)

        ep = run_episode(Env(tier, seed, text_provider=GeminiWorldText(wt, name="gemini-world:gemini-4-carbon")), SolverPolicy())
        assert ep.end_reason != "error"
        assert ep.correct is True
