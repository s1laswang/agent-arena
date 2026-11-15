from __future__ import annotations

from dataclasses import asdict
import io
import json
from pathlib import Path
import re
import tokenize
from typing import Any

import pytest

from canary.env import Env
from canary.eval import run_episode
from canary.solver.policy import SolverPolicy
from canary.types import EpisodeResult, Step, ToolResult

REPO_ROOT = Path(__file__).resolve().parents[1]
MM_ROOT = REPO_ROOT / "results" / "gemini" / "roles_carbon" / "multimodal_evidence"
RUN_DIR = MM_ROOT / "memo-watermark-hard-seeds10to14-carbon"

SIX_WATERMARK_ABLATION_RUNS = (
    "memo-watermark-ablation-carbon",
    "memo-watermark-hard-ablation-carbon",
    "memo-watermark-hard-seeds5to9-carbon",
    "memo-watermark-hard-seeds10to14-carbon",
    "memo-watermark-med-seeds6to11-carbon",
    "scanned-evidence-ablation-carbon",
)

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
HASH_CHAR = chr(35)
COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GOOGLE_KEY_RE = re.compile(r"(?<![A-Za-z0-9_\-])AIza[0-9A-Za-z_\-]{8,60}(?![A-Za-z0-9_\-=])")
SK_KEY_RE = re.compile(r"(?<![A-Za-z0-9_])sk-[A-Za-z0-9_\-]{12,}")
OAUTH_RE = re.compile(r"(?<![A-Za-z0-9_])ya29\.[0-9A-Za-z_\-]{12,}")


@pytest.fixture(autouse=True)
def _keyless_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)


def _scan_secrets(text: str) -> list[str]:
    hits: list[str] = []
    if GOOGLE_KEY_RE.search(text):
        hits.append("google_api_key")
    if SK_KEY_RE.search(text):
        hits.append("sk_api_key")
    if OAUTH_RE.search(text):
        hits.append("oauth_token")
    return hits


class _RedactedLeakEnv:
    def __init__(self, env: Env) -> None:
        self._env = env
        self._history: list[Step] = []
        self.surfaced: list[tuple[str, int, str | None]] = []
        self._seen_docs: set[str] = set()

    @property
    def tier(self) -> str:
        return self._env.tier

    @property
    def seed(self) -> int:
        return self._env.seed

    @property
    def p(self) -> Any:
        return self._env.p

    @property
    def done(self) -> bool:
        return self._env.done

    @property
    def history(self) -> list[Step]:
        return self._history

    def tools_spec(self) -> list[dict[str, Any]]:
        return self._env.tools_spec()

    def instruction(self) -> str:
        return self._env.instruction()

    def peek_status(self) -> dict[str, Any]:
        return self._env.peek_status()

    def verdict(self) -> dict[str, Any]:
        return self._env.verdict()

    def score(self) -> float:
        return self._env.score()

    def result(self, agent_name: str) -> EpisodeResult:
        res = self._env.result(agent_name)
        return EpisodeResult(
            tier=res.tier,
            seed=res.seed,
            agent=res.agent,
            steps=list(self._history),
            score=res.score,
            accused=res.accused,
            correct=res.correct,
            final_day=res.final_day,
            end_reason=res.end_reason,
            meta=dict(res.meta),
        )

    def call(self, tool: str, args: dict[str, Any]) -> ToolResult:
        step_idx = len(self._history)
        day_before = int(self._env.peek_status().get("day", 1))
        raw_res = self._env.call(tool, args)
        if tool == "check_leak_feed" and raw_res.ok:
            redacted_items: list[dict[str, Any]] = []
            for item in raw_res.data.get("items", []):
                doc_id = str(item["doc_id"])
                if doc_id not in self._seen_docs:
                    self._seen_docs.add(doc_id)
                    raw_day = item.get("day_surfaced", item.get("surfaced_day"))
                    raw_var = item.get("variant")
                    norm_var = str(raw_var).strip().upper() if raw_var else None
                    self.surfaced.append((doc_id, int(raw_day), norm_var))
                redacted_items.append({k: v for k, v in item.items() if k != "variant"})
            public_res = ToolResult(True, {"items": redacted_items}, raw_res.error)
        else:
            public_res = raw_res
        self._history.append(
            Step(
                t=step_idx,
                day=day_before,
                tool=tool,
                args=dict(args),
                result=asdict(public_res),
            )
        )
        return public_res


class _ReplayVisionPolicy:
    def __init__(self, variant_by_doc: dict[str, str | None], name: str) -> None:
        self.variant_by_doc = variant_by_doc
        self.solver = SolverPolicy()
        self.name = name
        self._augmented_steps: list[Step] = []

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        self._augmented_steps = []
        self.solver.reset(tools_spec, instruction)

    def act(self, history: list[Step]) -> tuple[str, dict[str, Any]]:
        if len(history) < len(self._augmented_steps):
            self._augmented_steps = []
        for st in history[len(self._augmented_steps):]:
            if st.tool == "check_leak_feed" and isinstance(st.result, dict) and st.result.get("ok"):
                data = st.result.get("data") or {}
                aug_items: list[dict[str, Any]] = []
                for it in data.get("items") or []:
                    assert "variant" not in it
                    entry = dict(it)
                    pred_var = self.variant_by_doc.get(str(entry["doc_id"]))
                    if pred_var is not None:
                        entry["variant"] = pred_var
                    aug_items.append(entry)
                new_res = dict(st.result)
                new_res["data"] = {**data, "items": aug_items}
                self._augmented_steps.append(
                    Step(t=st.t, day=st.day, tool=st.tool, args=st.args, result=new_res)
                )
            else:
                self._augmented_steps.append(st)
        return self.solver.act(self._augmented_steps)


def test_hard_seeds10to14_compact_schema_manifest_and_vision_calls() -> None:
    assert RUN_DIR.is_dir()
    files = sorted(p.name for p in RUN_DIR.iterdir())
    assert files == ["comparison.json", "meta.json", "summary.md", "vision_calls.jsonl"]
    assert list(RUN_DIR.rglob("*.png")) == []
    assert not (RUN_DIR / "memos").exists()

    for artifact in RUN_DIR.iterdir():
        txt = artifact.read_text(encoding="utf-8")
        assert EM_DASH not in txt
        assert EN_DASH not in txt
        assert "results/gemini_roles/" not in txt
        assert _scan_secrets(txt) == []

    meta = json.loads((RUN_DIR / "meta.json").read_text(encoding="utf-8"))
    comp = json.loads((RUN_DIR / "comparison.json").read_text(encoding="utf-8"))
    summary_md = (RUN_DIR / "summary.md").read_text(encoding="utf-8")
    vision_calls = [
        json.loads(ln)
        for ln in (RUN_DIR / "vision_calls.jsonl").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]

    assert meta["role"] == "multimodal_evidence"
    assert meta["subrole"] == "visual_memo_blind_ablation"
    assert meta["model_id"] == "gemini-4-carbon"
    assert meta["tiers_version"] == "v1.4"
    assert meta["tier"] == "hard"
    assert meta["seeds"] == [10, 11, 12, 13, 14]
    assert meta["n_episodes"] == 5
    assert meta["part_from_bytes"] is True
    assert COMMIT_RE.fullmatch(meta["commit"]) is not None
    assert meta["git_sha"] == meta["commit"] == comp["commit"]
    assert "results/gemini/roles_carbon/multimodal_evidence/memo-watermark-hard-seeds10to14-carbon" in meta["command"]
    assert "results/gemini/roles_carbon/multimodal_evidence/memo-watermark-hard-seeds10to14-carbon" in summary_md

    assert meta["n_images_read_by_model"] == 39
    assert meta["n_canary_memos_read_by_model"] == 6
    assert meta["variant_vision_accuracy"] == 1.0
    assert meta["canary_variant_vision_accuracy"] == 1.0
    assert meta["multimodal_mean_score"] == pytest.approx(0.376)
    assert meta["blind_mean_score"] == pytest.approx(0.234)
    assert meta["blind_ablation_mean_score"] == pytest.approx(0.234)
    assert meta["oracle_mean_score"] == pytest.approx(0.376)
    assert meta["multimodal_accuracy"] == 1.0
    assert meta["blind_accuracy"] == pytest.approx(0.6)
    assert meta["oracle_accuracy"] == 1.0
    assert meta["oracle_score_recovery_ratio"] == pytest.approx(1.0)

    memos = meta["memos"]
    assert len(memos) == 39
    assert len(vision_calls) == 39
    assert comp["memos"] == memos
    assert comp["vision_calls"] == vision_calls

    manifest = meta["image_manifest"]
    assert manifest["count"] == 39
    assert manifest["mime_type"] == "image/png"
    assert manifest["total_bytes"] == 1225250
    assert manifest["dimensions"] == [[880, 620]]
    assert len(manifest["images"]) == 39
    assert [img["path"] for img in manifest["images"]] == sorted(m["path"] for m in memos)
    assert sum(int(img["bytes"]) for img in manifest["images"]) == manifest["total_bytes"]

    manifest_by_path = {img["path"]: img for img in manifest["images"]}
    for m, vc in zip(memos, vision_calls):
        assert m["seed"] == vc["seed"]
        assert m["doc_id"] == vc["doc_id"]
        assert m["day_surfaced"] == vc["day_surfaced"]
        assert m["is_canary_memo"] == vc["is_canary_memo"]
        assert m["path"] == vc["memo_path"]
        img = manifest_by_path[m["path"]]
        assert img["size"] == [880, 620] == m["size"] == vc["memo_size"]
        assert img["width"] == 880 and img["height"] == 620
        assert img["bytes"] == m["bytes"] == vc["memo_bytes"] > 0
        assert SHA256_RE.fullmatch(img["sha256"]) is not None
        assert img["sha256"] == m["sha256"] == vc["memo_sha256"]
        assert vc["model_id"] == "gemini-4-carbon"
        assert vc["tier"] == "hard"
        assert vc["variant_exact_match"] is True
        assert vc["predicted_variant"] == vc["expected_variant"]
        assert vc["model_response"]["observed_doc_id"] == vc["doc_id"]
        assert vc["model_response"]["observed_day_surfaced"] == vc["day_surfaced"]
        assert vc["usage"]["in"] > 0 and vc["usage"]["out"] > 0

    canary_variants = {vc["expected_variant"] for vc in vision_calls if vc["is_canary_memo"]}
    assert canary_variants == {"A", "B", "C"}

    usage = meta["usage"]
    assert usage["calls"] == 39
    assert usage["in"] == 74256 == sum(vc["usage"]["in"] for vc in vision_calls)
    assert usage["out"] == 4966 == sum(vc["usage"]["out"] for vc in vision_calls)
    assert usage["thinking"] == 3691 == sum(vc["usage"]["thinking"] for vc in vision_calls)
    assert usage["cost_usd"] == pytest.approx(0.235082, abs=1e-6)


def test_hard_seeds10to14_keyless_env_replay_parity() -> None:
    comp = json.loads((RUN_DIR / "comparison.json").read_text(encoding="utf-8"))
    vision_calls = [
        json.loads(ln)
        for ln in (RUN_DIR / "vision_calls.jsonl").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    assert [row["seed"] for row in comp["per_seed"]] == [10, 11, 12, 13, 14]

    for row in comp["per_seed"]:
        seed = int(row["seed"])
        seed_vcs = [vc for vc in vision_calls if int(vc["seed"]) == seed]
        pred_by_doc = {str(vc["doc_id"]): vc["predicted_variant"] for vc in seed_vcs}

        mm_env = _RedactedLeakEnv(Env("hard", seed))
        mm_ep = run_episode(mm_env, _ReplayVisionPolicy(pred_by_doc, "multimodal_carbon"))
        assert mm_env.surfaced == [
            (str(vc["doc_id"]), int(vc["day_surfaced"]), vc["expected_variant"])
            for vc in seed_vcs
        ]
        assert mm_ep.score == pytest.approx(row["multimodal_carbon"]["score"])
        assert mm_ep.correct is row["multimodal_carbon"]["correct"]
        assert mm_ep.accused == row["multimodal_carbon"]["accused"]
        assert mm_ep.final_day == row["multimodal_carbon"]["final_day"]
        assert len(mm_ep.steps) == row["multimodal_carbon"]["tool_calls"]

        bl_env = _RedactedLeakEnv(Env("hard", seed))
        bl_ep = run_episode(bl_env, _ReplayVisionPolicy({}, "blind_no_vision"))
        assert bl_ep.score == pytest.approx(row["blind_no_vision"]["score"])
        assert bl_ep.correct is row["blind_no_vision"]["correct"]
        assert bl_ep.accused == row["blind_no_vision"]["accused"]
        assert bl_ep.final_day == row["blind_no_vision"]["final_day"]
        assert len(bl_ep.steps) == row["blind_no_vision"]["tool_calls"]

        orc_ep = run_episode(Env("hard", seed), SolverPolicy())
        assert orc_ep.score == pytest.approx(row["text_oracle"]["score"])
        assert orc_ep.correct is row["text_oracle"]["correct"]
        assert orc_ep.accused == row["text_oracle"]["accused"]
        assert orc_ep.final_day == row["text_oracle"]["final_day"]
        assert len(orc_ep.steps) == row["text_oracle"]["tool_calls"]


def test_pooled_six_folders_27_worlds_140_scans_watermark_vision_accuracy() -> None:
    assert len(SIX_WATERMARK_ABLATION_RUNS) == 6
    unique_episodes: dict[tuple[str, int], dict[str, Any]] = {}
    raw_folder_scans = 0
    raw_folder_exact = 0

    for run_name in SIX_WATERMARK_ABLATION_RUNS:
        run_dir = MM_ROOT / run_name
        assert run_dir.is_dir(), run_dir
        comp = json.loads((run_dir / "comparison.json").read_text(encoding="utf-8"))
        default_tier = str(comp["tier"])
        raw_folder_scans += len(comp["vision_calls"])
        raw_folder_exact += sum(1 for vc in comp["vision_calls"] if vc["variant_exact_match"])
        for row in comp["per_seed"]:
            tier = str(row.get("tier") or default_tier)
            seed = int(row["seed"])
            key = (tier, seed)
            mm_ep = row["multimodal_carbon"]
            bl_ep = row["blind_no_vision"]
            orc_ep = row["text_oracle"]
            entry = {
                "mm_score": float(mm_ep["score"]),
                "bl_score": float(bl_ep["score"]),
                "orc_score": float(orc_ep["score"]),
                "n_memos": int(mm_ep["n_memos_inspected"]),
                "n_canary": int(mm_ep["n_canary_memos_inspected"]),
                "vision_exact": int(mm_ep["vision_exact_matches"]),
                "canary_exact": int(mm_ep["canary_vision_exact_matches"]),
                "mm_correct": bool(mm_ep["correct"]),
                "bl_correct": bool(bl_ep["correct"]),
                "orc_correct": bool(orc_ep["correct"]),
            }
            if key in unique_episodes:
                assert unique_episodes[key] == entry, key
            else:
                unique_episodes[key] = entry

    assert len(unique_episodes) == 27
    expected_keys = {("medium", s) for s in range(12)} | {("hard", s) for s in range(15)}
    assert set(unique_episodes.keys()) == expected_keys

    rows = [unique_episodes[k] for k in sorted(unique_episodes)]
    total_scans = sum(int(r["n_memos"]) for r in rows)
    total_exact = sum(int(r["vision_exact"]) for r in rows)
    total_canary = sum(int(r["n_canary"]) for r in rows)
    total_canary_exact = sum(int(r["canary_exact"]) for r in rows)
    mm_mean = sum(float(r["mm_score"]) for r in rows) / len(rows)
    bl_mean = sum(float(r["bl_score"]) for r in rows) / len(rows)
    orc_mean = sum(float(r["orc_score"]) for r in rows) / len(rows)

    assert total_scans == 140
    assert total_exact == 140
    assert 100.0 * total_exact / total_scans == pytest.approx(100.0, abs=1e-9)
    assert total_canary == 45
    assert total_canary_exact == 45
    assert raw_folder_scans == 156
    assert raw_folder_exact == 156
    assert round(mm_mean, 4) == 0.6263
    assert round(bl_mean, 4) == 0.1822
    assert round(orc_mean, 4) == 0.6263
    assert 100.0 * (mm_mean / orc_mean) == pytest.approx(100.0, abs=1e-9)
    assert sum(1 for r in rows if r["mm_correct"]) == 27
    assert sum(1 for r in rows if r["bl_correct"]) == 10
    assert sum(1 for r in rows if r["orc_correct"]) == 27

    hard_rows = [unique_episodes[("hard", s)] for s in range(15)]
    assert sum(int(r["n_memos"]) for r in hard_rows) == 82
    assert sum(int(r["vision_exact"]) for r in hard_rows) == 82
    assert round(sum(float(r["mm_score"]) for r in hard_rows) / 15, 4) == 0.5387
    assert round(sum(float(r["bl_score"]) for r in hard_rows) / 15, 4) == 0.3280
    assert round(sum(float(r["orc_score"]) for r in hard_rows) / 15, 4) == 0.5387


def test_this_file_has_zero_comments_dashes_or_secrets() -> None:
    src = Path(__file__).resolve().read_text(encoding="utf-8")
    assert HASH_CHAR not in src
    assert EM_DASH not in src
    assert EN_DASH not in src
    tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
    assert comments == []
    assert _scan_secrets(src) == []
