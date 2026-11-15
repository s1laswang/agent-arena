from __future__ import annotations

import ast
from dataclasses import asdict
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tokenize

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) in sys.path:
    sys.path.remove(str(ROOT))
sys.path.insert(0, str(ROOT))
for _mod_name in [k for k in list(sys.modules) if k == "canary" or k.startswith("canary.")]:
    if not str(getattr(sys.modules[_mod_name], "__file__", "")).startswith(str(ROOT)):
        sys.modules.pop(_mod_name, None)

from canary.env import Env
from canary.social import BIAS_TYPES, make_v16_provider
from canary.social.office_replay import (
    PROVENANCE_BADGES,
    build_office_replay,
    load_episode_record,
    main as office_replay_main,
    render_office_replay_html,
)
from canary.types import EpisodeResult


def test_v5_cocktail_per_day_social_events_and_solver_divergence() -> None:
    replay = build_office_replay(tier="hard", seed=5, variant="v5_full9_cocktail", agent="solver")
    assert replay["tier"] == "hard"
    assert replay["seed"] == 5
    assert replay["variant"] == "v5_full9_cocktail"
    assert replay["provenance"] == "v16-template"

    final_day = replay["episode_summary"]["final_day"]
    assert final_day == 9
    assert [d["day"] for d in replay["days"]] == list(range(1, final_day + 1))

    prim = replay["social_state"]["primary_suspect"]
    sec = replay["social_state"]["secondary_suspect"]
    assert prim is not None and sec is not None
    assert prim != sec
    assert prim != replay["decoy"]
    assert sec != replay["decoy"]

    seen_biases: set[str] = set()
    for day_rec in replay["days"]:
        assert day_rec["social_events"]
        for ev in day_rec["social_events"]:
            assert {"bias", "sender", "target", "channel", "subject", "body"}.issubset(ev.keys())
            assert ev["bias"] in BIAS_TYPES
            assert ev["sender"] != replay["decoy"]
            assert ev["target"] in {prim, sec}
            assert ev["subject"].strip()
            assert ev["body"].strip()
            seen_biases.add(ev["bias"])

    assert seen_biases == set(BIAS_TYPES)
    assert replay["episode_summary"]["correct"] is True
    assert replay["episode_summary"]["fooled_count"] == 0
    assert replay["fooled_moments"] == []

    last_post = replay["days"][-1]["posterior"]
    assert last_post["top_suspect"] == replay["episode_summary"]["accused"]
    assert last_post["p_top_suspect"] > 0.85
    assert last_post["p_primary_suspect"] is not None and last_post["p_primary_suspect"] < 0.01
    assert last_post["p_secondary_suspect"] is not None and last_post["p_secondary_suspect"] < 0.01


def test_provenance_badges_decoy_scrub_tags_and_zero_live_gemini(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _forbid_live_client(*_a: object, **_kw: object) -> None:
        raise AssertionError("live LLM client creation is forbidden in office_replay")

    monkeypatch.setattr("canary.llm.get_client", _forbid_live_client)
    monkeypatch.delenv("CANARY_OFFLINE", raising=False)
    monkeypatch.delenv("SLEEPER_OFFLINE", raising=False)

    rep_ctrl = build_office_replay(tier="hard", seed=2, variant="v0_v14_control", agent="solver")
    rep_tpl = build_office_replay(tier="hard", seed=2, variant="v5_full9_cocktail", agent="solver")
    stub_cache = tmp_path / "stub_cache"
    rep_stub = build_office_replay(
        tier="hard",
        seed=2,
        variant="v16-gemini-stub:v5_full9_cocktail",
        agent="solver",
        cache_dir=stub_cache,
    )
    monkeypatch.setenv("CANARY_OFFLINE", "1")
    rep_stub_offline = build_office_replay(
        tier="hard",
        seed=2,
        variant="v16-gemini-stub:v5_full9_cocktail",
        agent="solver",
        cache_dir=stub_cache,
    )
    rep_coerced = build_office_replay(
        tier="hard",
        seed=2,
        variant="v16-gemini:v5_full9_cocktail",
        agent="solver",
        cache_dir=tmp_path / "coerced_cache",
    )

    assert rep_ctrl["provenance"] == "v14-control"
    assert rep_tpl["provenance"] == "v16-template"
    assert rep_stub["provenance"] == "v16-gemini-stub"
    assert rep_stub_offline["provenance"] == "v16-gemini-stub"
    assert rep_coerced["provenance"] == "v16-gemini-stub"
    assert {rep_ctrl["provenance"], rep_tpl["provenance"], rep_stub["provenance"]} == set(PROVENANCE_BADGES)

    assert rep_ctrl["social_state"]["primary_suspect"] is None
    assert all(d["social_events"] == [] for d in rep_ctrl["days"])

    assert rep_ctrl["solver_reference_summary"] == rep_tpl["solver_reference_summary"]
    assert rep_tpl["solver_reference_summary"] == rep_stub["solver_reference_summary"]
    for d_ctrl, d_tpl, d_stub in zip(rep_ctrl["days"], rep_tpl["days"], rep_stub["days"]):
        assert d_ctrl["posterior"]["top_suspect"] == d_tpl["posterior"]["top_suspect"] == d_stub["posterior"]["top_suspect"]
        assert d_ctrl["posterior"]["p_top_suspect"] == pytest.approx(d_tpl["posterior"]["p_top_suspect"])
        assert d_tpl["posterior"]["p_top_suspect"] == pytest.approx(d_stub["posterior"]["p_top_suspect"])

    decoy_id = rep_tpl["decoy"]
    assert decoy_id is not None

    tpl_decoy_msgs = [m for d in rep_tpl["days"] for m in d["messages"] if m["sender"] == decoy_id]
    tpl_non_decoy_msgs = [m for d in rep_tpl["days"] for m in d["messages"] if m["sender"] != decoy_id]
    assert tpl_decoy_msgs and all(m["tag"] == "decoy" for m in tpl_decoy_msgs)
    assert any(m["has_decoy_vocab"] for m in tpl_decoy_msgs)
    assert tpl_non_decoy_msgs and all(m["tag"] == "scrubbed-non-decoy" for m in tpl_non_decoy_msgs)
    assert all(not m["has_decoy_vocab"] for m in tpl_non_decoy_msgs)
    assert any(m["scrubbed_rewrite"] for m in tpl_non_decoy_msgs)

    ctrl_non_decoy = [m for d in rep_ctrl["days"] for m in d["messages"] if m["sender"] != decoy_id]
    assert ctrl_non_decoy and all(m["tag"] == "non-decoy" for m in ctrl_non_decoy)
    assert any(m["has_decoy_vocab"] for m in ctrl_non_decoy)

    stub_social = [m for d in rep_stub["days"] for m in d["messages"] if m["is_social"]]
    tpl_social = [m for d in rep_tpl["days"] for m in d["messages"] if m["is_social"]]
    assert len(stub_social) == len(tpl_social) > 0
    assert any(ms["body"] != mt["body"] for ms, mt in zip(stub_social, tpl_social))
    assert all(m["provenance"] == "v16-gemini-stub" for m in stub_social)
    assert rep_stub_offline["days"] == rep_stub["days"]


def test_fooled_moment_detector_on_rumour_follower_and_recorded_jsonl(tmp_path: Path) -> None:
    rf_replay = build_office_replay(
        tier="hard",
        seed=5,
        variant="v5_full9_cocktail",
        agent="rumour_follower",
    )
    prim = rf_replay["social_state"]["primary_suspect"]
    sec = rf_replay["social_state"]["secondary_suspect"]
    assert prim is not None and sec is not None
    assert rf_replay["episode_summary"]["accused"] == prim
    assert rf_replay["episode_summary"]["correct"] is False
    assert rf_replay["episode_summary"]["fooled_count"] == 1
    fm0 = rf_replay["fooled_moments"][0]
    assert fm0["tool"] == "accuse"
    assert fm0["target"] == prim
    assert fm0["target_role"] == "primary_suspect"
    assert fm0["solver_p_target"] < 0.05
    assert fm0["prior_social_mentions"] >= 5

    prov = make_v16_provider("v5_full9_cocktail")
    env = Env("hard", 5, text_provider=prov)
    env.call("list_employees", {})
    env.call("advance_day", {})
    env.call("interview", {"employee": prim, "topic": "recent_documents"})
    env.call("advance_day", {})
    env.call("advance_day", {})
    env.call("restrict_access", {"employee": sec})
    env.call("advance_day", {})
    env.call("advance_day", {})
    env.call("accuse", {"employee": prim})
    custom_ep: EpisodeResult = env.result("gullible_investigator")

    direct_replay = build_office_replay(
        tier="hard",
        seed=5,
        variant="v5_full9_cocktail",
        episode=custom_ep,
    )
    assert direct_replay["episode_summary"]["final_day"] == 6
    assert direct_replay["episode_summary"]["fooled_count"] == 3
    tools_targets = [(f["day"], f["tool"], f["target"], f["target_role"]) for f in direct_replay["fooled_moments"]]
    assert tools_targets == [
        (2, "interview", prim, "primary_suspect"),
        (4, "restrict_access", sec, "secondary_suspect"),
        (6, "accuse", prim, "primary_suspect"),
    ]
    assert all(f["solver_p_target"] < 0.05 for f in direct_replay["fooled_moments"])

    jsonl_path = tmp_path / "episodes.jsonl"
    other_ep = EpisodeResult(
        tier="easy",
        seed=1,
        agent="other",
        steps=[],
        score=0.0,
        accused=None,
        correct=False,
        final_day=1,
        end_reason="horizon",
        meta={},
    )
    jsonl_path.write_text(
        json.dumps(asdict(other_ep), sort_keys=True) + "\n"
        + json.dumps(asdict(custom_ep), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    loaded = load_episode_record(jsonl_path, tier="hard", seed=5)
    assert loaded.agent == "gullible_investigator"
    jsonl_replay = build_office_replay(
        tier="hard",
        seed=5,
        variant="v5_full9_cocktail",
        episode_path=jsonl_path,
    )
    assert jsonl_replay["fooled_moments"] == direct_replay["fooled_moments"]


def test_self_contained_html_exporter_and_cli(tmp_path: Path) -> None:
    replay = build_office_replay(
        tier="hard",
        seed=5,
        variant="v5_full9_cocktail",
        agent="rumour_follower",
    )
    out_html = tmp_path / "fooled_replay.html"
    rendered = render_office_replay_html(replay, out_path=out_html)
    assert out_html.is_file()
    assert rendered == out_html.read_text(encoding="utf-8")
    assert "<!doctype html>" in rendered.lower()
    assert "http://" not in rendered and "https://" not in rendered
    assert "\u2014" not in rendered
    assert "v16-template" in rendered
    assert "data-testid='fooled-banner'" in rendered
    assert "data-day-row='1'" in rendered
    assert f"data-day-row='{replay['episode_summary']['final_day']}'" in rendered

    match = re.search(
        r'<script id="office-replay-data" type="application/json">(.*?)</script>',
        rendered,
        flags=re.S,
    )
    assert match is not None
    embedded = json.loads(match.group(1))
    assert embedded["seed"] == 5
    assert embedded["variant"] == "v5_full9_cocktail"
    assert len(embedded["days"]) == replay["episode_summary"]["final_day"]

    cli_html = tmp_path / "cli_office_replay.html"
    cli_json = tmp_path / "cli_office_replay.json"
    rc = office_replay_main([
        "--tier",
        "hard",
        "--seed",
        "5",
        "--variant",
        "v5_full9_cocktail",
        "--out",
        str(cli_html),
        "--json-out",
        str(cli_json),
    ])
    assert rc == 0
    assert cli_html.is_file() and cli_json.is_file()
    parsed_json = json.loads(cli_json.read_text(encoding="utf-8"))
    assert parsed_json["episode_summary"]["final_day"] == 9

    sub_out = Path("/tmp/opencode/test_office_replay_cli.html")
    try:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT)
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "canary.social.office_replay",
                "--tier",
                "hard",
                "--seed",
                "5",
                "--variant",
                "v5_full9_cocktail",
                "--out",
                str(sub_out),
            ],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        summary = json.loads(proc.stdout.strip())
        assert summary["seed"] == 5
        assert summary["variant"] == "v5_full9_cocktail"
        assert summary["provenance"] == "v16-template"
        assert sub_out.is_file()
    finally:
        sub_out.unlink(missing_ok=True)


def test_code_and_doc_hygiene_rules() -> None:
    py_files = [
        ROOT / "canary" / "social" / "office_replay.py",
        ROOT / "tests" / "test_v16_office_replay.py",
    ]
    for path in py_files:
        text = path.read_text(encoding="utf-8")
        assert "\u2014" not in text, path.name
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        comment_tokens = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert not comment_tokens, (path.name, comment_tokens[:3])

    mod_path = ROOT / "canary" / "social" / "office_replay.py"
    tree = ast.parse(mod_path.read_text(encoding="utf-8"), filename=str(mod_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in ("_world", "mole"), node.attr
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert "world" not in node.module, node.module

    doc_path = ROOT / "docs" / "v16-office-replay.md"
    if doc_path.is_file():
        doc_text = doc_path.read_text(encoding="utf-8")
        assert "\u2014" not in doc_text
