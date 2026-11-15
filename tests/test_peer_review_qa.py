from __future__ import annotations

from collections import Counter
import dataclasses
import importlib.util
import json
import re
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from typing import Iterator
from urllib.parse import unquote

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOC_REL = "docs/PEER-REVIEW-QA.md"
DOC_PATH = ROOT / DOC_REL
SELF_PATH = Path(__file__).resolve()
HYGIENE_SCRIPT = ROOT / "scripts" / "audit_doc_hygiene.py"
DOC_CMD_SCRIPT = ROOT / "scripts" / "verify_doc_commands.py"
CRAFT_CONSISTENCY_SCRIPT = ROOT / "scripts" / "check_craft_consistency.py"
OPENCODE_TMP = Path("/tmp/opencode")
H = chr(35)


def _load_script_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


hygiene_mod = _load_script_module("audit_doc_hygiene_qa", HYGIENE_SCRIPT)
doc_cmd_mod = _load_script_module("verify_doc_commands_qa", DOC_CMD_SCRIPT)
craft_mod = _load_script_module("check_craft_consistency_qa", CRAFT_CONSISTENCY_SCRIPT)


@pytest.fixture(scope="module")
def doc_text() -> str:
    assert DOC_PATH.is_file(), f"missing {DOC_REL}"
    return DOC_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def paired_rows() -> list[dict]:
    paired_path = ROOT / "data" / "runs" / "committed" / "v1.4" / "paired_table_gemini.json"
    return json.loads(paired_path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def oc_hard_meta() -> dict:
    meta_path = ROOT / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-4-carbon" / "hard" / "meta.json"
    return json.loads(meta_path.read_text(encoding="utf-8"))


@pytest.fixture()
def opencode_tmp() -> Iterator[Path]:
    OPENCODE_TMP.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(OPENCODE_TMP), prefix="test-peer-review-qa-") as tmp_dir:
        yield Path(tmp_dir)


def _pct_band(ratio: float, lo: float, hi: float) -> str:
    return f"{ratio:.0%} [{lo:.0%}, {hi:.0%}]"


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_zero_hash_in_test_and_zero_em_en_dashes_in_both_files(doc_text: str):
    self_text = SELF_PATH.read_text(encoding="utf-8")
    assert H not in self_text, f"unexpected {H!r} character in {SELF_PATH.name}"
    for label, content in ((DOC_REL, doc_text), (SELF_PATH.name, self_text)):
        assert "\u2014" not in content, f"unexpected em dash in {label}"
        assert "\u2013" not in content, f"unexpected en dash in {label}"


def test_q1_to_q8_structure_links_anchors_and_doc_registration(doc_text: str):
    assert DOC_REL in hygiene_mod.ACTIVE_JUDGE_DOCS
    assert DOC_REL in doc_cmd_mod.DEFAULT_DOCS
    assert DOC_REL in doc_cmd_mod.FLAG_CHECK_DOCS

    from canary.rules import TIERS_VERSION

    assert TIERS_VERSION == "v1.4"
    assert 'TIERS_VERSION = "v1.4"' in doc_text
    assert "a8f99c2537c91d72" in doc_text

    doc_slugs = hygiene_mod.extract_heading_slugs(doc_text)
    last_pos = -1
    for q_idx in range(1, 9):
        heading_prefix = f"{H}{H} Q{q_idx}."
        pos = doc_text.find(heading_prefix)
        assert pos > last_pos, f"missing or out-of-order section heading {heading_prefix}"
        last_pos = pos
        table_link = re.search(rf"\[Q{q_idx}\]\({re.escape(H)}([a-z0-9_-]+)\)", doc_text)
        assert table_link is not None, f"missing summary table anchor for Q{q_idx}"
        assert table_link.group(1) in doc_slugs, f"broken Q{q_idx} anchor: {table_link.group(1)}"

    stripped = hygiene_mod._strip_code_preserving_lines(doc_text)
    for label, pat in hygiene_mod.STALE_PR41_PATTERNS:
        assert pat.search(stripped) is None, f"stale token {label!r} in {DOC_REL}"
    assert craft_mod.STALE_GAP_RX.search(stripped) is None

    tracked_files = set(hygiene_mod._git_ls_files(ROOT) or ())
    rel_candidates: list[str] = []
    link_count = 0
    for m in hygiene_mod.MD_PLAIN_LINK_RX.finditer(stripped):
        raw_target = (m.group(1) or m.group(2) or "").strip()
        assert raw_target, "empty markdown link target"
        if any(raw_target.lower().startswith(s) for s in hygiene_mod.EXTERNAL_SCHEMES):
            continue
        link_count += 1
        if raw_target.startswith(H):
            frag = unquote(raw_target[1:])
            assert frag in doc_slugs, f"broken self-anchor {raw_target}"
            continue
        path_part, sep, frag_part = raw_target.partition(H)
        resolved = (DOC_PATH.parent / unquote(path_part)).resolve()
        assert resolved.exists(), f"missing relative link target {raw_target} -> {resolved}"
        rel_to_root = resolved.relative_to(ROOT).as_posix()
        rel_candidates.append(rel_to_root)
        if tracked_files and resolved.is_file():
            assert rel_to_root in tracked_files, f"untracked or gitignored link target: {rel_to_root}"
        if sep and resolved.is_file() and resolved.suffix.lower() == ".md":
            ext_slugs = hygiene_mod.extract_heading_slugs(resolved.read_text(encoding="utf-8"))
            assert unquote(frag_part) in ext_slugs, f"broken cross-doc anchor {raw_target}"
    ignored_set = hygiene_mod._git_ignored_batch(ROOT, rel_candidates)
    assert not ignored_set, f"gitignored link target(s): {sorted(ignored_set)}"
    assert link_count >= 35


def test_q1_statistical_significance_headline_ordering_and_empty_reply_sensitivity(
    doc_text: str,
    paired_rows: list[dict],
):
    oc_hard = next(
        r for r in paired_rows
        if r["agent"] == "opencode:google/gemini-4-carbon"
        and r["tier"] == "hard"
        and "alternative" not in r["label"]
    )
    oc_alt_hard = next(
        r for r in paired_rows
        if r["agent"] == "opencode:google/gemini-4-carbon"
        and r["tier"] == "hard"
        and "alternative" in r["label"]
    )
    solver_hard = next(
        r for r in paired_rows
        if r["agent"] == "solver" and r["tier"] == "hard"
    )

    assert oc_hard["n"] == 30 and oc_hard["seeds"] == list(range(30))
    assert solver_hard["n"] == 30 and solver_hard["seeds"] == list(range(30))
    assert f"{oc_hard['mean']:+.3f} +/- {oc_hard['ci']:.3f}" in doc_text
    assert f"{solver_hard['mean']:+.3f} +/- {solver_hard['ci']:.3f}" in doc_text

    raw_band = _pct_band(oc_hard["ratio"], oc_hard["ratio_lo"], oc_hard["ratio_hi"])
    la_band = _pct_band(
        oc_hard["post_expected_ratio"],
        oc_hard["post_expected_lo"],
        oc_hard["post_expected_hi"],
    )
    assert raw_band == "65% [24%, 98%]" and la_band == "72% [52%, 91%]"
    assert raw_band in doc_text and la_band in doc_text
    assert doc_text.index(raw_band) < doc_text.index(la_band)
    for ln in doc_text.splitlines():
        if raw_band in ln and la_band in ln:
            assert ln.index(raw_band) < ln.index(la_band), f"luck-adjusted placed before raw on line: {ln}"

    assert f"{oc_hard['post_expected']:+.3f}" in doc_text
    assert f"{oc_hard['diff']:+.3f} +/- {oc_hard['diff_ci']:.3f}" in doc_text
    assert "[-0.371, +0.017]" in doc_text
    assert "92708834" in doc_text

    ref_opt = (ROOT / "docs" / "reports" / "reference_optimality.md").read_text(encoding="utf-8")
    assert "0.956" in ref_opt and "0.986" in ref_opt
    assert "95.6%-98.6%" in doc_text
    assert "8000-8399" in doc_text and "9000-9399" in doc_text

    assert oc_alt_hard["n"] == 30
    assert f"{oc_alt_hard['mean']:+.3f} +/- {oc_alt_hard['ci']:.3f}" in doc_text
    assert _pct_band(oc_alt_hard["ratio"], oc_alt_hard["ratio_lo"], oc_alt_hard["ratio_hi"]) in doc_text
    assert _pct_band(
        oc_alt_hard["post_expected_ratio"],
        oc_alt_hard["post_expected_lo"],
        oc_alt_hard["post_expected_hi"],
    ) in doc_text
    assert f"{oc_alt_hard['post_expected']:+.3f}" in doc_text
    assert f"{oc_alt_hard['diff']:+.3f} +/- {oc_alt_hard['diff_ci']:.3f}" in doc_text


def test_q2_seed_lock_solver_dirs_pooled_extension_and_cross_model(
    doc_text: str,
    paired_rows: list[dict],
):
    for lock_tok in ("post-hoc lock", "671ed96", "8fd4dec", "28 s", "dcd8c372"):
        assert lock_tok in doc_text
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", doc_text):
        if "0-29" in sentence and "pre-register" in sentence.lower():
            low = sentence.lower()
            assert (
                "not a pre-registration" in low
                or "not pre-registered" in low
                or "**not** pre-registered" in low
                or "**not** a pre-registration" in low
                or "were dev seeds" in low
                or "gpt-5.5" in low
                or "0-29, 34, 37" in low
            ), f"ambiguous pre-registration claim on 0-29: {sentence}"

    ref_dir = ROOT / "data" / "runs" / "committed" / "v1.4" / "reference"
    ref_0_19 = _read_jsonl(ref_dir / "solver-hard-20261114-121126" / "episodes.jsonl")
    ref_20_29 = _read_jsonl(ref_dir / "solver-hard-seeds20to29" / "episodes.jsonl")
    ref_30_59 = _read_jsonl(ref_dir / "solver-hard-seeds30to59" / "episodes.jsonl")
    assert [e["seed"] for e in ref_0_19] == list(range(0, 20))
    assert [e["seed"] for e in ref_20_29] == list(range(20, 30))
    assert [e["seed"] for e in ref_30_59] == list(range(30, 60))
    for dir_tok in ("solver-hard-20261114-121126", "solver-hard-seeds20to29", "solver-hard-seeds30to59"):
        assert dir_tok in doc_text

    ext_dir = ROOT / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-4-carbon-ext"
    ext_eps = _read_jsonl(ext_dir / "hard" / "episodes.jsonl")
    assert [e["seed"] for e in ext_eps] == [34, 37]
    assert [round(e["score"], 3) for e in ext_eps] == [0.790, 0.700]
    ext_meta = json.loads((ext_dir / "hard" / "meta.json").read_text(encoding="utf-8"))
    assert len(ext_meta["infra_invalid_attempts_excluded"]) == 31
    assert all("infra:provider_quota" in x for x in ext_meta["infra_invalid_attempts_excluded"])

    pooled_rows = json.loads((ext_dir / "paired_table_pooled0to59.json").read_text(encoding="utf-8"))
    oc_pooled = next(
        r for r in pooled_rows
        if r["agent"] == "opencode:google/gemini-4-carbon" and r["tier"] == "hard" and r["n"] == 32
    )
    assert f"{oc_pooled['mean']:+.3f} +/- {oc_pooled['ci']:.3f}" in doc_text
    assert f"{oc_pooled['solver_same_seeds']:+.3f}" in doc_text
    assert _pct_band(oc_pooled["ratio"], oc_pooled["ratio_lo"], oc_pooled["ratio_hi"]) in doc_text
    assert _pct_band(
        oc_pooled["post_expected_ratio"],
        oc_pooled["post_expected_lo"],
        oc_pooled["post_expected_hi"],
    ) in doc_text
    assert f"{oc_pooled['diff']:+.3f} +/- {oc_pooled['diff_ci']:.3f}" in doc_text

    flash_hard = next(
        r for r in paired_rows
        if r["agent"] == "opencode:google/gemini-3.5-flash"
        and r["tier"] == "hard"
        and "alternative" not in r["label"]
    )
    assert f"{flash_hard['mean']:+.3f} +/- {flash_hard['ci']:.3f}" in doc_text
    assert _pct_band(flash_hard["ratio"], flash_hard["ratio_lo"], flash_hard["ratio_hi"]) in doc_text
    assert _pct_band(
        flash_hard["post_expected_ratio"],
        flash_hard["post_expected_lo"],
        flash_hard["post_expected_hi"],
    ) in doc_text

    gap_md = (ROOT / "docs" / "reports" / "gap.md").read_text(encoding="utf-8")
    assert "gpt-5.5 via OpenCode 1.19.5" in gap_md and "$200" in gap_md
    for tok in ("f9fb7a4a", "cf394894", "gpt-5.5", "1.19.5", "$200", "97% [89%, 107%]", "infra:provider_quota"):
        assert tok in doc_text


def test_q3_infra_invalid_attempts_breakdown_and_tamper_guards(doc_text: str, oc_hard_meta: dict, opencode_tmp: Path):
    assert oc_hard_meta["invalid_episodes"] == []
    excluded = oc_hard_meta["infra_invalid_attempts_excluded"]
    assert len(excluded) == 25

    cat_counts: Counter[str] = Counter()
    seeds_seen: set[int] = set()
    for item in excluded:
        seed_match = re.match(r"^opencode-hard-(\d+)-\d+:", item)
        assert seed_match is not None, f"unexpected attempt key: {item}"
        seeds_seen.add(int(seed_match.group(1)))
        cat_match = re.search(r"(infra:[a-z_]+)", item)
        assert cat_match is not None, f"missing infra tag in {item}"
        cat_counts[cat_match.group(1)] += 1

    assert cat_counts == {
        "infra:cli_error_event": 13,
        "infra:empty_model_response": 6,
        "infra:provider_unavailable": 6,
    }
    assert seeds_seen == {3, 14, 15, 18, 19, 23, 24, 25, 26, 27, 29}
    assert len(seeds_seen) == 11

    for tok in (
        "`25`",
        "`13` `infra:cli_error_event`",
        "`6` `infra:empty_model_response`",
        "`6` `infra:provider_unavailable`",
        "`11` unique seeds",
        "agent_killed_server",
        "test_integrity_valid_filter.py",
    ):
        assert tok in doc_text

    from canary.agents.frontier import common as frontier_common

    spoof_stdout = "\n".join(
        json.dumps(ev)
        for ev in (
            {"type": "text", "part": {"text": "The database is locked; usage limit has been reached"}},
            {"type": "tool_use", "part": {"state": {"output": "429 Too Many Requests"}}},
        )
    )
    assert frontier_common.classify_infra(spoof_stdout, "") is None
    kill_stdout = json.dumps(
        {"type": "tool_use", "part": {"state": {"input": {"command": "pkill -f canary.mcp_server"}}}}
    )
    assert frontier_common.agent_touched_server(kill_stdout)

    class _DeadServer:
        url, token = "http://x/mcp", "tok"

        def __init__(self, *args):
            pass

        def start(self, **kwargs):
            return self

        def ledger(self):
            raise RuntimeError("MCP server died during the episode (rc=-9)")

        def stop(self):
            pass

    class _Proc:
        returncode, stderr = 0, ""
        stdout = kill_stdout

    run_dir = opencode_tmp / "kill_check"
    spec = frontier_common.RunSpec(agent="opencode:x/y", tier="easy", seeds=[3], out=run_dir)
    writer = frontier_common.RunWriter(run_dir)
    res = frontier_common.run_one(
        spec,
        3,
        lambda wd, p, u: ["true", p],
        set(),
        writer,
        threading.Lock(),
        runner=lambda *a, **k: _Proc(),
        server_factory=_DeadServer,
        write=False,
    )
    assert "error" not in res.meta
    assert res.meta["note"].startswith("agent_killed_server")
    assert res.score == 0.0


def test_q4_harness_parity_isolation_and_panel_fix_d(doc_text: str, oc_hard_meta: dict):
    assert oc_hard_meta["opencode_permission"] == {"*": "deny", "canary_*": "allow"}
    assert oc_hard_meta["opencode_version"] == "1.18.29"
    assert "1.18.29" in doc_text and "bash" in doc_text and "python3" in doc_text

    iso_files = list((ROOT / "results" / "harbor").rglob("isolation.txt"))
    iso_ok = sum(
        "ISOLATION OK: 11 checks passed, 0 findings" in p.read_text(encoding="utf-8", errors="replace")
        for p in iso_files
    )
    assert len(iso_files) == 61 and iso_ok == 61
    assert "11/11" in doc_text and "61/61" in doc_text

    reh_readme = (ROOT / "results" / "harbor" / "rehearsal-dry" / "README.md").read_text(encoding="utf-8")
    reh_table = (ROOT / "results" / "harbor" / "rehearsal-dry" / "TABLE.md").read_text(encoding="utf-8")
    assert "All 43 trials pass" in reh_readme and "43/43" in doc_text
    assert "+0.467" in reh_table and "+0.398" in reh_table and "85% [11%, 355%]" in reh_table
    assert "+0.467" in doc_text and "+0.398" in doc_text and "85% [11%, 355%]" in doc_text

    oc_eps = _read_jsonl(
        ROOT / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-4-carbon" / "hard" / "episodes.jsonl"
    )
    assert len(oc_eps) == 30
    headline_calls = 0
    inv_arg_calls = 0
    for ep in oc_eps:
        for st in ep["steps"]:
            res = st.get("result") or {}
            err_txt = str(res.get("error") or "")
            if "Model tried to call unavailable tool" in err_txt:
                continue
            headline_calls += 1
            if "invalid arguments" in err_txt:
                inv_arg_calls += 1
    assert headline_calls == 3841 and inv_arg_calls == 28
    assert "`28` of `3,841`" in doc_text

    exp = json.loads((ROOT / "results" / "anticheat" / "exploits.json").read_text(encoding="utf-8"))
    rc = exp["replay_counts"]
    assert rc["replayed"] == 1021 and rc["n"] == 1031 and rc["steps"] == 51814 and rc["step_mismatches"] == 0
    assert "1,021/1,031" in doc_text and "51,814" in doc_text

    from canary.rules import TierParams

    n_params = len(dataclasses.fields(TierParams))
    assert n_params == 34 and f"{n_params}/{n_params}" in doc_text
    for tok in (
        "1bc3e281",
        "afterquery-final",
        "data.detail",
        "254",
        "424",
        "0.26",
        "0.24",
        "39/39",
        "512836b9",
        "10800.0",
        "W1",
        "W2",
        "W3",
        "W4",
        "access_constraints",
        "canary_level = 1",
        "never binds",
    ):
        assert tok in doc_text


def test_q5_causal_gap_parity_disclosures_and_negative_ablations(
    doc_text: str,
    paired_rows: list[dict],
):
    oc_med = next(
        r for r in paired_rows
        if r["agent"] == "opencode:google/gemini-4-carbon"
        and r["tier"] == "medium"
        and "alternative" not in r["label"]
    )
    inproc_hard = next(
        r for r in paired_rows
        if r["agent"] == "gemini:gemini-4-carbon" and r["tier"] == "hard"
    )
    inproc_med = next(
        r for r in paired_rows
        if r["agent"] == "gemini:gemini-4-carbon" and r["tier"] == "medium"
    )

    assert f"{oc_med['mean']:+.3f} +/- {oc_med['ci']:.3f}" in doc_text
    assert _pct_band(oc_med["ratio"], oc_med["ratio_lo"], oc_med["ratio_hi"]) in doc_text
    assert _pct_band(
        oc_med["post_expected_ratio"],
        oc_med["post_expected_lo"],
        oc_med["post_expected_hi"],
    ) in doc_text

    assert f"{inproc_hard['mean']:+.3f} +/- {inproc_hard['ci']:.3f}" in doc_text
    assert _pct_band(inproc_hard["ratio"], inproc_hard["ratio_lo"], inproc_hard["ratio_hi"]) in doc_text
    assert _pct_band(
        inproc_hard["post_expected_ratio"],
        inproc_hard["post_expected_lo"],
        inproc_hard["post_expected_hi"],
    ) in doc_text
    assert f"{inproc_med['mean']:+.3f} +/- {inproc_med['ci']:.3f}" in doc_text
    assert _pct_band(inproc_med["ratio"], inproc_med["ratio_lo"], inproc_med["ratio_hi"]) in doc_text

    fa = json.loads((ROOT / "results" / "failure_analysis_v1.4.json").read_text(encoding="utf-8"))
    gap = fa["summary"]["gap"]
    oc = fa["summary"]["opencode"]
    inp = fa["summary"]["inproc"]
    sol = fa["summary"]["solver"]

    skill_sum = gap["penalty"] + gap["abstain"] + gap["leak"] + gap["restrict"] + gap["canary"]
    assert abs(skill_sum - gap["la_gap"]) < 1e-9
    assert abs((gap["la_gap"] + gap["luck"]) - gap["raw_gap"]) < 1e-9

    for val_str in (
        f"{gap['raw_gap']:.2f} V",
        f"{gap['penalty']:+.2f} V",
        f"{gap['abstain']:+.2f} V",
        f"{gap['leak']:+.2f} V",
        f"{gap['restrict']:+.2f} V",
        f"{abs(gap['canary']):.2f} V",
        f"{gap['la_gap']:+.2f} V",
        f"{gap['luck']:+.2f} V",
        f"{inp['canaries']:.1f}",
        f"{oc['canaries']:.1f}",
        f"{sol['canaries']:.1f}",
        f"{inp['interviews']:.0f}",
        f"{oc['interviews']:.0f}",
        f"{oc['capacity_used']:.0%}",
        f"{sol['capacity_used']:.0%}",
        f"{len(oc['not_isolated'])}/{oc['accused']}",
        f"{len(sol['not_isolated'])}/{sol['accused']}",
    ):
        assert val_str in doc_text

    fg_md = (ROOT / "docs" / "reports" / "failure_gallery.md").read_text(encoding="utf-8")
    assert "295" in fg_md and "0.0e+00" in fg_md
    assert "295" in doc_text and "0.0e+00" in doc_text

    ladder = json.loads((ROOT / "results" / "gemini" / "ladder.json").read_text(encoding="utf-8"))
    assert len(ladder["rows"]) == 42 and sum(r["n"] for r in ladder["rows"]) == 587
    assert "587" in doc_text and "42" in doc_text and "106% [94%, 126%]" in doc_text

    abl = json.loads((ROOT / "results" / "gemini" / "ablations.json").read_text(encoding="utf-8"))
    assert abl["thought_signatures"]["off"]["episodes_attempted"] == 10
    assert abl["thought_signatures"]["off"]["valid_episodes"] == 0
    assert abl["thought_signatures"]["on"]["api_calls"] == 628
    assert abl["explicit_cache"]["atlas_plus_gallery"]["pct_saved"] == 62.9
    assert abl["explicit_cache"]["programme"]["pct_saved"] == 75.9
    assert abl["explicit_cache"]["programme"]["calls"] == 29150
    for abl_tok in ("10/10", "0/628", "62.9%", "75.9%", "29,150"):
        assert abl_tok in doc_text

    gap_md = (ROOT / "docs" / "reports" / "gap.md").read_text(encoding="utf-8")
    for neg_tok in ("108%", "+0.012", "84% [52%, 128%]", "n=13"):
        assert neg_tok in gap_md and neg_tok in doc_text
    assert "+0.012 +/- 0.029" in doc_text


def test_q6_reward_integrity_and_final_58716742_hunt(doc_text: str):
    exploits_md_doc = (ROOT / "docs" / "EXPLOITS.md").read_text(encoding="utf-8")
    hist_nums = [int(m.group(1)) for m in re.finditer(r"^\|\s*(\d+)\s*\|", exploits_md_doc, re.MULTILINE)]
    assert hist_nums == list(range(52))
    assert "`52`" in doc_text

    gd1 = json.loads(
        (ROOT / "results" / "solver_range" / "guess_day1_hard_judge40.json").read_text(encoding="utf-8")
    )
    assert gd1["builds"] == 300 and f"{gd1['mean']:.3f}" in doc_text

    judge_md = (ROOT / "results" / "judge_table.md").read_text(encoding="utf-8")
    assert "| guess_day1 | baseline | 40 | 0 | -0.950" in judge_md
    assert "-0.950 +/- 0.098" in doc_text

    tamper = json.loads(
        (ROOT / "results" / "harbor_negative" / "c1-tamper" / "result.json").read_text(encoding="utf-8")
    )
    tamper_eval = next(iter(tamper["stats"]["evals"].values()))
    assert tamper_eval["metrics"][0]["mean"] == 0.0
    assert "c1-tamper" in doc_text

    exp = json.loads((ROOT / "results" / "anticheat" / "exploits.json").read_text(encoding="utf-8"))
    assert exp["all_blocked"] is True
    assert exp["replay_all_consistent"] is True
    assert exp["harbor_all_consistent"] is True
    assert len(exp["rows"]) == 99 and sum(r["n"] for r in exp["rows"]) == 3960
    hard_attack = [r for r in exp["rows"] if r["tier"] == "hard" and r["kind"] == "attack"]
    hard_swarm = [r for r in exp["rows"] if r["tier"] == "hard" and r["kind"] == "swarm"]
    assert len(hard_attack) == 14 and len(hard_swarm) == 1
    assert "`99` rows x `40` judge seeds = `3,960` runs" in doc_text
    assert "`14` scripted attack probes + `1` swarm probe" in doc_text

    exp_md = (ROOT / "results" / "anticheat" / "exploits.md").read_text(encoding="utf-8")
    assert "80 of 80 trials and 18 of 18 job summaries consistent." in exp_md
    assert "80/80" in doc_text and "18/18" in doc_text

    corpus_txt = (ROOT / "results" / "anticheat" / "corpus_eval.txt").read_text(encoding="utf-8")
    assert '"rows": 129' in corpus_txt and "runs=1161 changed=0 accepted=0" in corpus_txt
    assert "129" in doc_text and "1,161" in doc_text

    swarm = json.loads((ROOT / "results" / "gemini" / "swarm.json").read_text(encoding="utf-8"))
    wb = sum(w["finished"] for w in swarm["waves"] if w["mode"] == "whitebox")
    bb = sum(w["finished"] for w in swarm["waves"] if w["mode"] == "blackbox")
    reruns = sum(w["mcp_reruns"] for w in swarm["waves"])
    assert wb == 75 and bb == 16 and wb + bb == 91 and reruns == 9
    assert swarm["counts"]["attempts"] == 100 and swarm["counts"]["tool_calls"] == 4325
    assert swarm["counts"]["exploits"] == 0 and swarm["counts"]["invariant_violations"] == 0
    assert swarm["positive_control"]["attackers_found"] == 4 and swarm["positive_control"]["attempts"] == 4
    for sw_tok in ("`91`", "`75`", "`16`", "`9`", "`100` attempts", "4,325", "4/4"):
        assert sw_tok in doc_text

    integrity_md = (ROOT / "docs" / "reports" / "integrity.md").read_text(encoding="utf-8")
    hunt_md = (ROOT / "results" / "anticheat" / "judge_hunt.md").read_text(encoding="utf-8")
    assert "12 of 12 held" in hunt_md and "52 s" in hunt_md
    for int_tok in ("afterquery-final", "1bc3e281", "4 min 57 s", "1,057", "PASS=20, FAIL=0", "424"):
        assert int_tok in integrity_md
    for doc_tok in ("58716742", "12/12", "52 s", "0.000", "4 min 57 s", "1,057", "PASS=20", "FAIL=0", "424"):
        assert doc_tok in doc_text


def test_q7_ws4_small_model_tiebreaker_honesty(doc_text: str):
    ws4_md = (ROOT / "fr8" / "analysis" / "out" / "ws4_table_v3.md").read_text(encoding="utf-8")
    assert "| base |" in ws4_md and "| all | 36 | 0.000" in ws4_md
    assert "| v2 |" in ws4_md and "| all | 172 | -0.457" in ws4_md
    assert "| v3-4k-s0 |" in ws4_md and "| all | 180 | -0.147" in ws4_md
    assert "| v3-8k-s2 |" in ws4_md and "| all | 90 | -0.050" in ws4_md
    assert "| v3-8k-s1 |" in ws4_md and "| all | 90 | -0.777" in ws4_md

    fr8_md = (ROOT / "docs" / "reports" / "fr8.md").read_text(encoding="utf-8")
    assert "0.19" in fr8_md and "0.89" in fr8_md and "115" in fr8_md

    j4_md = (ROOT / "fr8" / "analysis" / "out" / "j4_proxy.md").read_text(encoding="utf-8")
    assert "| valid_rate | 0.082 | 0.996 | 0.991 |" in j4_md
    assert "| solver_tool_agreement | 0.000 | 0.861 | 0.808 |" in j4_md

    for ws4_tok in (
        "NOT met",
        "no held-out reward gain over base",
        "n=36",
        "0.000",
        "3%",
        "n=172",
        "-0.457 +/- 0.086",
        "n=180",
        "-0.147 +/- 0.063",
        "+0.310 +/- 0.107",
        "100%",
        "0.19 -> 0.89",
        "n=25",
        "-0.240 +/- 0.171",
        "n=90",
        "-0.050 +/- 0.049",
        "-0.777 +/- 0.118",
        "two-sample",
        "115/115",
        "0.08 -> 0.99",
        "0.00 -> ~0.85",
    ):
        assert ws4_tok in doc_text


def test_q8_reproducibility_pooled_rows_bands_and_fresh_clone_1bc3e281(doc_text: str):
    ext_dir = ROOT / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-4-carbon-ext"
    pooled_rows = json.loads((ext_dir / "paired_table_pooled0to59.json").read_text(encoding="utf-8"))
    oc_pooled = next(
        r for r in pooled_rows
        if r["agent"] == "opencode:google/gemini-4-carbon" and r["tier"] == "hard" and r["n"] == 32
    )
    sv_pooled = next(
        r for r in pooled_rows
        if r["agent"] == "solver" and r["tier"] == "hard" and r["n"] == 60
    )
    assert f"{oc_pooled['mean']:+.3f} +/- {oc_pooled['ci']:.3f}" in doc_text
    assert f"{sv_pooled['mean']:+.3f} +/- {sv_pooled['ci']:.3f}" in doc_text
    assert "n=32" in doc_text and "n=60" in doc_text and "HEADLINE" in doc_text

    sr_hard = json.loads((ROOT / "results" / "solver_range" / "solver_hard_judge40.json").read_text(encoding="utf-8"))
    sr_med = json.loads((ROOT / "results" / "solver_range" / "solver_medium_judge40.json").read_text(encoding="utf-8"))
    sr_easy = json.loads((ROOT / "results" / "solver_range" / "solver_easy_judge40.json").read_text(encoding="utf-8"))
    assert sr_hard["builds"] == sr_med["builds"] == sr_easy["builds"] == 300
    lo_4sd = sr_hard["mean"] - 4.0 * sr_hard["sd"]
    hi_4sd = sr_hard["mean"] + 4.0 * sr_hard["sd"]
    assert f"{sr_hard['mean']:+.3f}" in doc_text and f"{sr_hard['sd']:.3f}" in doc_text
    assert f"[{lo_4sd:+.2f}, {hi_4sd:+.2f}]" in doc_text
    assert f"{sr_med['mean']:+.3f}" in doc_text and f"{sr_easy['mean']:+.3f}" in doc_text

    ora = json.loads((ROOT / "results" / "oracle_range_v1.4.json").read_text(encoding="utf-8"))
    solver_ora = next(r for r in ora["rows"] if r["agent"] == "solver" and r["tier"] == "hard")
    assert solver_ora["builds"] == 200
    k10 = solver_ora["k10"]
    assert f"{k10['p5']:+.2f}" in doc_text and f"{k10['p95']:+.2f}" in doc_text
    assert f"{k10['mean']:+.3f}" in doc_text and f"{k10['sd']:.3f}" in doc_text

    fc_readme = (ROOT / "results" / "fresh_clone" / "README.md").read_text(encoding="utf-8")
    fc_log = ROOT / "results" / "fresh_clone" / "linux_x86_64_afterquery_final_1bc3e281.log.txt"
    assert fc_log.is_file()
    for fc_tok in ("1bc3e281", "3 s", "27 s", "118 s", "3 PASS, 1 WARN, 0 FAIL", "175 s", "100 passed"):
        assert fc_tok in fc_readme and fc_tok in doc_text

    for hw_tok in (
        "GOOGLE_GENERATIVE_AI_API_KEY",
        "--api-key-name GOOGLE_GENERATIVE_AI_API_KEY",
        "--agent-setup-timeout-multiplier 3",
        "make lab-replay",
        "make game-serve",
        "3000",
        "0.79",
        "e09",
    ):
        assert hw_tok in doc_text


def test_cli_commands_and_negative_verifier_guards(opencode_tmp: Path):
    cmd_results = doc_cmd_mod.verify_repo(ROOT, docs=(DOC_REL,))
    assert len(cmd_results) == 4
    for res in cmd_results:
        assert res.status == "PASS", f"{res.name} status={res.status}: {res.details}"

    stale_root = opencode_tmp / "stale_guard"
    (stale_root / "docs").mkdir(parents=True)
    (stale_root / "README.md").write_text(f"{H} Canary\n", encoding="utf-8")
    (stale_root / DOC_REL).write_text(
        f"{H} QA\nBroken [self]({H}missing-slug) and stale 51-attacker claim.\n",
        encoding="utf-8",
    )
    stale_res = {r.name: r for r in hygiene_mod.audit_doc_hygiene(stale_root)}
    assert stale_res[hygiene_mod.CHECK_ANCHORS].status == "FAIL"
    assert stale_res[hygiene_mod.CHECK_STALE_PR41].status == "FAIL"

    bad_cmd_root = opencode_tmp / "bad_cmd_guard"
    (bad_cmd_root / "docs").mkdir(parents=True)
    (bad_cmd_root / "scripts").mkdir(parents=True)
    shutil.copy2(ROOT / "Makefile", bad_cmd_root / "Makefile")
    shutil.copy2(ROOT / "scripts" / "demo_replay.py", bad_cmd_root / "scripts" / "demo_replay.py")
    (bad_cmd_root / DOC_REL).write_text(
        f"{H} QA\n```bash\nuv run python scripts/demo_replay.py --bogus-qa-flag 1\n```\n",
        encoding="utf-8",
    )
    bad_cmd_res = {r.name: r for r in doc_cmd_mod.verify_repo(bad_cmd_root, docs=(DOC_REL,))}
    assert bad_cmd_res["CLI Long-Flag Check"].status == "FAIL"
