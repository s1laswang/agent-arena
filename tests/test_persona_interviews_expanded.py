from __future__ import annotations

import io
import json
from pathlib import Path
import tokenize

import pytest

from canary.env import Env, TOPICS
from canary.gemini import interview_interrogator as ii
from canary.gemini.provenance import COMMIT_RE, TARGET_MODEL, audit_provenance, scan_file_secrets
from canary.llm import MissingKeyError
from canary.text.lint import lint_text
from canary.text.template import SIGNALS
from scripts.consolidate_world_text import consolidate_world_text

REPO_ROOT = Path(__file__).resolve().parents[1]
WT_ROOT = REPO_ROOT / "results" / "gemini_roles" / "world_text"
ORIG_DIR = WT_ROOT / "persona-interviews-carbon"
HARD14_DIR = WT_ROOT / "persona-interviews-hard14-carbon"
EASY03_HARD79_DIR = WT_ROOT / "persona-interviews-easy03-hard79-carbon"

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)


@pytest.fixture(autouse=True)
def _hermetic_keyless(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    monkeypatch.setattr("canary.llm.base.load_env", lambda: None)
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "ledger.jsonl"))


def _verify_interview_batch(
    run_dir: Path,
    expected_specs: list[tuple[str, int]],
) -> dict[str, object]:
    assert run_dir.is_dir()
    assert not (run_dir / "cache").exists()
    present_files = sorted(p.name for p in run_dir.iterdir() if p.is_file())
    assert present_files == ["interviews.json", "meta.json", "solver_parity.json", "summary.md"]

    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    iv_doc = json.loads((run_dir / "interviews.json").read_text(encoding="utf-8"))
    parity = json.loads((run_dir / "solver_parity.json").read_text(encoding="utf-8"))
    summary_md = (run_dir / "summary.md").read_text(encoding="utf-8")

    n_worlds = len(expected_specs)
    n_samples = n_worlds * len(TOPICS) * len(SIGNALS)

    assert meta["role"] == "world_text"
    assert meta["subrole"] == "persona_interviews"
    assert meta["model_id"] == TARGET_MODEL
    assert meta["llm_spec"] == f"gemini:{TARGET_MODEL}"
    assert COMMIT_RE.fullmatch(str(meta["commit"]))
    assert meta["tiers_version"] == "v1.4"
    assert meta["stub"] is False
    assert meta["fake_env"] is False
    assert meta["smoke"] is False
    assert meta["n_worlds"] == n_worlds
    assert meta["count"] == n_samples
    assert meta["n_samples"] == n_samples
    assert meta["sample_count"] == n_samples
    assert meta["n_interviews_generated"] == n_samples
    assert meta["llm_ok_count"] == n_samples
    assert meta["fallback_count"] == 0
    assert meta["truth_leak_violations"] == 0
    assert meta["prompt_truth_leak_violations"] == 0
    assert meta["lint_violations"] == 0
    assert meta["stego_leak_violations"] == 0
    assert meta["counterfactual_prompt_invariance_rate"] == 1.0
    assert meta["signal_calibration_ok"] is True
    assert meta["solver_parity_ok"] is True

    usage = meta["usage"]
    assert usage["calls"] >= n_samples
    assert usage["in"] > 0
    assert usage["out"] > 0
    assert usage["thinking"] > 0
    assert usage["cost_usd"] > 0.0

    specs_meta = [(w["tier"], int(w["seed"])) for w in meta["world_specs"]]
    specs_iv = [(w["tier"], int(w["seed"])) for w in iv_doc["worlds"]]
    specs_parity = [(w["tier"], int(w["seed"])) for w in parity["per_world"]]
    assert specs_meta == expected_specs
    assert specs_iv == expected_specs
    assert specs_parity == expected_specs

    all_records = [rec for w in iv_doc["worlds"] for rec in w["interviews"]]
    assert len(all_records) == n_samples
    assert {r["topic"] for r in all_records} == set(TOPICS)
    assert {r["signal"] for r in all_records} == set(SIGNALS)
    assert all(r["meta"]["llm_ok"] is True and r["meta"]["used_fallback"] is False for r in all_records)

    recal = ii.calibrate_interview_signals(all_records)
    cal = iv_doc["signal_calibration"]
    assert cal["calibration_ok"] is True
    assert recal["calibration_ok"] is True
    assert cal["signal_classification_accuracy"] == recal["signal_classification_accuracy"]
    assert cal["signal_classification_accuracy"] >= 0.90
    assert cal["pairwise_ordering_rate"] == recal["pairwise_ordering_rate"]
    assert cal["pairwise_ordering_rate"] >= 0.90
    assert cal["unique_answers_ratio"] >= 0.95

    assert iv_doc["audit"]["encodings_checked"] == 37
    assert iv_doc["audit"]["truth_leak_violations"] == 0
    assert iv_doc["audit"]["lint_violations"] == 0
    assert iv_doc["audit"]["stego_leak_violations"] == 0
    assert iv_doc["audit"]["env_surface_stego_violations"] == 0
    assert iv_doc["audit"]["prompt_truth_leak_violations"] == 0

    assert parity["parity_ok"] is True
    assert parity["do_nothing_all_zero"] is True
    assert parity["env_stego_violations"] == 0
    assert parity["persona_solver_accuracy"] == 1.0
    assert parity["template_solver_accuracy"] == 1.0
    assert abs(parity["solver_score_delta"]) <= 0.05
    assert parity["solver_vs_obvious_gap"] > 0.20

    for w_entry in iv_doc["worlds"]:
        env_check = Env(w_entry["tier"], int(w_entry["seed"]))
        aud = ii.audit_interview_records(w_entry["interviews"], env=env_check)
        assert aud["encodings_checked"] == 37
        assert aud["truth_leak_violations"] == 0
        assert aud["lint_violations"] == 0
        assert aud["stego_leak_violations"] == 0
        assert aud["dash_violations"] == 0

    assert EM_DASH not in summary_md
    assert EN_DASH not in summary_md
    assert "`medium` seeds 0,1,2 + `hard` seed 0" not in summary_md

    return {"meta": meta, "interviews": iv_doc, "parity": parity}


def test_expanded_persona_interviews_hard14_artifacts() -> None:
    expected = [("hard", 1), ("hard", 2), ("hard", 3), ("hard", 4)]
    bundle = _verify_interview_batch(HARD14_DIR, expected)
    meta = bundle["meta"]
    assert isinstance(meta, dict)
    assert meta["signal_calibration_accuracy"] == 1.0
    assert meta["pairwise_signal_ordering_rate"] == 1.0


def test_expanded_persona_interviews_easy03_hard79_artifacts() -> None:
    expected = [
        ("easy", 0),
        ("easy", 1),
        ("easy", 2),
        ("easy", 3),
        ("hard", 7),
        ("hard", 8),
        ("hard", 9),
    ]
    bundle = _verify_interview_batch(EASY03_HARD79_DIR, expected)
    meta = bundle["meta"]
    assert isinstance(meta, dict)
    assert meta["signal_calibration_accuracy"] == 1.0
    assert meta["pairwise_signal_ordering_rate"] == 1.0


def test_non_overlapping_expanded_interviews_provenance_consolidation_and_replay(tmp_path: Path) -> None:
    batch_dirs = [ORIG_DIR, HARD14_DIR, EASY03_HARD79_DIR]
    seen_worlds: set[tuple[str, int]] = set()
    for bdir in batch_dirs:
        iv_doc = json.loads((bdir / "interviews.json").read_text(encoding="utf-8"))
        batch_worlds = {(str(w["tier"]), int(w["seed"])) for w in iv_doc["worlds"]}
        assert seen_worlds.isdisjoint(batch_worlds)
        seen_worlds |= batch_worlds
    assert len(seen_worlds) == 15

    prov = audit_provenance(REPO_ROOT)
    assert prov["verified"] is True
    assert prov["secret_leaks"] == []
    by_rel = {r["run_dir"]: r for r in prov["runs"]}
    for rel_dir, exp_count in (
        ("results/gemini_roles/world_text/persona-interviews-hard14-carbon", 32),
        ("results/gemini_roles/world_text/persona-interviews-easy03-hard79-carbon", 56),
    ):
        assert rel_dir in by_rel
        assert by_rel[rel_dir]["verified"] is True
        assert by_rel[rel_dir]["role"] == "world_text"
        assert by_rel[rel_dir]["model_id"] == TARGET_MODEL
        assert by_rel[rel_dir]["count"] == exp_count

    suite = consolidate_world_text(root=REPO_ROOT, write_files=False)
    assert suite["leak_and_safety_audit"]["all_clean"] is True
    piv_suite = suite["persona_interviews_suite"]
    assert piv_suite["n_batches"] >= 3
    assert piv_suite["unique_worlds"] >= 15
    assert piv_suite["total_interviews"] >= 120
    assert piv_suite["signal_calibration_accuracy"] >= 0.95
    assert piv_suite["counterfactual_invariance_rate"] == 1.0
    assert piv_suite["persona_solver_accuracy"] == 1.0

    synth_cache = tmp_path / "replay_cache"
    for bdir in (HARD14_DIR, EASY03_HARD79_DIR):
        iv_doc = json.loads((bdir / "interviews.json").read_text(encoding="utf-8"))
        for w_entry in iv_doc["worlds"]:
            tier = str(w_entry["tier"])
            seed = int(w_entry["seed"])
            iv_map: dict[str, dict[str, object]] = {}
            for rec in w_entry["interviews"]:
                ckey = f"{rec['employee']}|{rec['topic']}|{rec['signal']}|{rec['day']}"
                iv_map[ckey] = {
                    "answer": rec["answer"],
                    "stance": rec["stance"],
                    "tone_applied": rec["tone_applied"],
                    "llm_ok": True,
                    "used_fallback": False,
                    "raw_violations": 0,
                }
            cfile = synth_cache / tier / f"{seed}.interviews.json"
            cfile.parent.mkdir(parents=True, exist_ok=True)
            cfile.write_text(
                json.dumps(
                    {
                        "provider": f"persona-interviews:{TARGET_MODEL}",
                        "model_id": TARGET_MODEL,
                        "interviews": iv_map,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            prov_replay = ii.PersonaInterviewProvider(
                llm=f"gemini:{TARGET_MODEL}",
                cache_dir=synth_cache,
                worlds_dir=None,
            )
            replay_env = Env(tier, seed, text_provider=prov_replay)
            sample_rec = w_entry["interviews"][0]
            replayed_ans = prov_replay.interview_answer(
                replay_env._facts(int(sample_rec["day"])),
                str(sample_rec["employee"]),
                str(sample_rec["topic"]),
                str(sample_rec["signal"]),
            )
            assert replayed_ans == sample_rec["answer"]
            assert prov_replay.cache_hits == 1
            assert not lint_text(replayed_ans)

            with pytest.raises(MissingKeyError):
                prov_replay.interview_answer(
                    replay_env._facts(4),
                    "e99",
                    "workload",
                    "evasive",
                )


def test_expanded_persona_interviews_hygiene() -> None:
    self_path = REPO_ROOT / "tests" / "test_persona_interviews_expanded.py"
    src = self_path.read_text(encoding="utf-8")
    assert EM_DASH not in src
    assert EN_DASH not in src
    tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
    assert comments == []
    assert scan_file_secrets(self_path, REPO_ROOT) == []

    for bdir in (HARD14_DIR, EASY03_HARD79_DIR):
        for fpath in sorted(bdir.rglob("*")):
            if not fpath.is_file():
                continue
            raw = fpath.read_text(encoding="utf-8")
            assert EM_DASH not in raw
            assert EN_DASH not in raw
            assert scan_file_secrets(fpath, REPO_ROOT) == []
