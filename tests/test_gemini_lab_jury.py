"""Keyless unit tests for canary.gemini.jury: blind causal packing, Fleiss' kappa, calibration, ledgering,
and 0-call --replay reproduction."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from canary.gemini.jury import (
    CODE_TAGS,
    TAXONOMY,
    JuryOps,
    ReplayMiss,
    assert_blind_view_clean,
    build_blind_view,
    build_parser,
    calibration_curve,
    cohens_kappa,
    fleiss_kappa,
    load_all_episodes,
    majority_vote,
    run,
)

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_RUN = ROOT / "data" / "runs" / "committed" / "codex-gpt-5.5"


@pytest.fixture(autouse=True)
def _isolated_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "ledger.jsonl"))


@pytest.fixture(scope="module")
def sample_eps():
    eps, counts = load_all_episodes(committed_dir=SAMPLE_RUN, ladder_gz=Path("/nonexistent"), ladder30_dir=None)
    assert eps and counts["committed_valid"] == len(eps)
    return eps


def test_blind_view_has_no_regret_tags_top_mole_or_true_mole(sample_eps):
    checked = 0
    for ep in sample_eps[:8]:
        # Inject adversarial tokens into rationale to verify sanitization too
        if ep.steps:
            ep.steps[0].rationale = "If e01 is the mole: REGRET top=e01 true_mole premature_accusation"
        for s in ep.steps:
            if s.regret >= 0.01 or s.tool in ("accuse", "plant_canary"):
                view = build_blind_view(ep, s.t)
                assert_blind_view_clean(view)
                for forbidden in ("REGRET", "top=", "mole:", "true_mole", "correct=", "score="):
                    assert forbidden not in view
                for tg in CODE_TAGS:
                    assert tg not in view
                # Causal check: no steps after s.t appear
                for later in ep.steps:
                    if later.t > s.t:
                        assert f"\nt{later.t} d" not in view
                checked += 1
    assert checked > 0


def test_fleiss_and_cohens_kappa_exact_values():
    # Perfect agreement -> kappa = 1.0
    perf = [["premature_accusation"] * 3, ["uninformative_canary"] * 3, ["not_a_mistake"] * 3]
    fk = fleiss_kappa(perf, TAXONOMY)
    assert fk["kappa"] == pytest.approx(1.0) and fk["p_observed"] == pytest.approx(1.0)
    ck = cohens_kappa([r[0] for r in perf], [r[1] for r in perf], TAXONOMY)
    assert ck["kappa"] == pytest.approx(1.0) and ck["agree_rate"] == pytest.approx(1.0)

    # Complete 1-1-1 disagreement on 3 balanced items -> observed agreement = 0, kappa < 0
    dis = [
        ["premature_accusation", "uninformative_canary", "not_a_mistake"],
        ["uninformative_canary", "not_a_mistake", "premature_accusation"],
        ["not_a_mistake", "premature_accusation", "uninformative_canary"],
    ]
    fk_dis = fleiss_kappa(dis, TAXONOMY)
    assert fk_dis["p_observed"] == pytest.approx(0.0)
    assert fk_dis["kappa"] == pytest.approx(-0.5, abs=1e-3)


def test_majority_vote_and_calibration():
    mv_unan = majority_vote([
        {"label": "premature_accusation", "confidence": 0.9},
        {"label": "premature_accusation", "confidence": 0.8},
        {"label": "premature_accusation", "confidence": 0.7},
    ])
    assert mv_unan["label"] == "premature_accusation" and mv_unan["agreement_type"] == "unanimous"
    assert mv_unan["confidence"] == pytest.approx(0.8)

    mv_maj = majority_vote([
        {"label": "uninformative_canary", "confidence": 0.75},
        {"label": "uninformative_canary", "confidence": 0.85},
        {"label": "not_a_mistake", "confidence": 0.95},
    ])
    assert mv_maj["label"] == "uninformative_canary" and mv_maj["agreement_type"] == "majority"

    mv_split = majority_vote([
        {"label": "other", "confidence": 0.55, "rank_tiebreak": 1},
        {"label": "uninformative_canary", "confidence": 0.90, "rank_tiebreak": 2},
        {"label": "not_a_mistake", "confidence": 0.60, "rank_tiebreak": 3},
    ])
    assert mv_split["label"] == "uninformative_canary" and mv_split["agreement_type"] == "split"

    cal = calibration_curve([(0.9, True)] * 9 + [(0.9, False)] * 1 + [(0.2, True)] * 1 + [(0.2, False)] * 4)
    assert cal["ece"] == pytest.approx(0.0, abs=1e-6)


def test_no_carbon_guard(tmp_path):
    ops = JuryOps(cache_file=tmp_path / "responses.jsonl.gz", replay=True)
    with pytest.raises(ValueError, match="forbidden"):
        ops._check_model("gemini-4-carbon")


class FakeJuryClient:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls = 0
        self.caches_created = 0
        self.models = SimpleNamespace(generate_content=self._gen)
        self.caches = SimpleNamespace(create=self._create_cache, delete=lambda name: None)

    def _create_cache(self, model, config):
        self.caches_created += 1
        return SimpleNamespace(name=f"cachedContents/fake-{self.caches_created}",
                               usage_metadata=SimpleNamespace(total_token_count=5000))

    def _gen(self, model, contents, config):
        self.calls += 1
        if self.fail:
            raise RuntimeError("fake network disabled during --replay")
        txt = "\n".join(p.text for c in contents for p in c.parts if getattr(p, "text", None))
        if "plant_canary(" in txt.splitlines()[-3] if len(txt.splitlines()) >= 3 else "plant_canary" in txt:
            lbl = "uninformative_canary" if "hydrogen" in model or "argon" in model else "other"
        elif "accuse(" in txt:
            lbl = "premature_accusation"
        else:
            lbl = "not_a_mistake"
        payload = {"label": lbl, "confidence": 0.82, "rationale": "Judged strictly from causal observations."}
        um = SimpleNamespace(prompt_token_count=800, candidates_token_count=35,
                             thoughts_token_count=40, cached_content_token_count=0)
        return SimpleNamespace(text=json.dumps(payload), usage_metadata=um, model_version=model)


def test_end_to_end_pipeline_and_zero_call_replay(tmp_path, sample_eps, monkeypatch):
    import canary.gemini.jury as jury_mod

    monkeypatch.setattr(
        jury_mod, "load_all_episodes",
        lambda **kw: (sample_eps[:4], {"committed_valid": 4, "committed_excluded_infra": 0,
                                        "ladder_valid": 0, "ladder_excluded_infra": 0,
                                        "ladder30_valid": 0, "ladder30_deduped": 0}),
    )
    fake_live = FakeJuryClient()
    orig_init = JuryOps.__init__

    def patched_init(self, *a, **kw):
        orig_init(self, *a, **kw)
        if not self.replay:
            self._client = fake_live

    monkeypatch.setattr(JuryOps, "__init__", patched_init)

    out1 = tmp_path / "out1"
    args1 = build_parser().parse_args([
        "--out", str(out1),
        "--limit-steps", "6",
        "--thinking-levels", "low", "medium",
        "--concurrency", "4",
    ])
    rep1 = run(args1)
    assert fake_live.calls == 6 * 3 * 2
    assert (out1 / "jury.json").exists()
    assert (out1 / "jury.md").exists()
    assert (out1 / "calibration.png").exists()
    assert (out1 / "responses.jsonl.gz").exists()
    assert rep1["carbon_used"] is False

    ledger_rows = [json.loads(ln) for ln in (tmp_path / "ledger.jsonl").read_text().splitlines() if ln.strip()]
    assert len(ledger_rows) == fake_live.calls
    assert all(r["feature"] == "jury" and r["ok"] for r in ledger_rows)

    # Offline --replay: must succeed with 0 calls even when client raises on any call
    fake_dead = FakeJuryClient(fail=True)

    def patched_replay_init(self, *a, **kw):
        orig_init(self, *a, **kw)
        self._client = fake_dead

    monkeypatch.setattr(JuryOps, "__init__", patched_replay_init)
    out2 = tmp_path / "out2"
    args2 = build_parser().parse_args([
        "--out", str(out2),
        "--cache-file", str(out1 / "responses.jsonl.gz"),
        "--limit-steps", "6",
        "--thinking-levels", "low", "medium",
        "--replay",
    ])
    rep2 = run(args2)
    assert fake_dead.calls == 0
    assert rep2["spend"]["calls"] == 0 and rep2["spend"]["replayed"] == 6 * 3 * 2
    assert rep2["primary_jury"]["majority_vote"]["all_accuracy"] == rep1["primary_jury"]["majority_vote"]["all_accuracy"]
    assert rep2["primary_jury"]["fleiss_kappa"]["all_9class"]["kappa"] == rep1["primary_jury"]["fleiss_kappa"]["all_9class"]["kappa"]

    # Missing key in replay raises ReplayMiss
    empty_ops = JuryOps(cache_file=tmp_path / "empty.jsonl.gz", replay=True)
    with pytest.raises(ReplayMiss):
        empty_ops.judge_step("gemini-3.8-flash", "medium", sample_eps[0], sample_eps[0].steps[0].t, {}, "sha")


def test_committed_scale_jury_artifacts():
    out = ROOT / "results" / "gemini" / "scale" / "jury"
    for fname in ("jury.json", "jury.md", "calibration.png", "responses.jsonl.gz"):
        assert (out / fname).exists(), f"missing {out / fname}"
    data = json.loads((out / "jury.json").read_text())
    assert data["carbon_used"] is False
    assert data["blind"] is True
    assert set(data["primary_jury"]["judges"]) == {"gemini-4-hydrogen", "gemini-4-argon", "gemini-3.8-flash"}
    assert data["corpus"]["high_regret_steps"] >= 1401
    assert data["corpus"]["tagged_high_regret_steps"] >= 394
    assert data["total_judgments"] >= 4203
    assert len(data["thinking_grid"]) == 9
    assert (out / "calibration.png").stat().st_size > 10_000

