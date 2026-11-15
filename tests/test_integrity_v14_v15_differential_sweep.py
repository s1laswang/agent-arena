from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
import sys
import time
import tokenize

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.integrity_v14_v15_differential_sweep as diff_sweep


EXPECTED_STRATEGIES = (
    "do_nothing",
    "stop_early",
    "blind_seat_0",
    "accuse_most_talkative",
    "accuse_authority_role",
    "accuse_first_named_anchor",
    "accuse_lexical_hedging",
    "log_volume_outlier",
    "one_interview_accuse",
    "reference_solver",
)


@pytest.fixture(scope="module")
def v15_runtime():
    return diff_sweep.load_v15_runtime()


@pytest.fixture(scope="module")
def cli_fast_bundle(tmp_path_factory: pytest.TempPathFactory, v15_runtime) -> dict:
    out_dir = tmp_path_factory.mktemp("diff_fast_cli")
    out_file = out_dir / "fast_diff.json"
    t0 = time.perf_counter()
    rc = diff_sweep.main(["--fast", "--seeds", "0", "--tiers", "easy", "--json-out", str(out_file)])
    elapsed = time.perf_counter() - t0
    assert rc == 0
    payload = json.loads(out_file.read_text(encoding="utf-8"))
    payload["_cli_wall_s"] = elapsed
    return payload


def _batch_git_blobs(repo_root: Path, commit_sha: str, rel_paths: list[str]) -> dict[str, str]:
    stdin_payload = "".join(f"{commit_sha}:{rel_path}\n" for rel_path in rel_paths).encode("utf-8")
    proc = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=repo_root,
        input=stdin_payload,
        capture_output=True,
        check=True,
    )
    buf = proc.stdout
    pos = 0
    out: dict[str, str] = {}
    for rel_path in rel_paths:
        nl = buf.index(b"\n", pos)
        header = buf[pos:nl].decode("utf-8").split()
        assert len(header) >= 3 and header[1] == "blob"
        size = int(header[2])
        body_start = nl + 1
        body_end = body_start + size
        out[rel_path] = buf[body_start:body_end].decode("utf-8")
        pos = body_end + 1
    return out


def test_isolated_git_show_v15_loader_and_v14_hash_preservation(v15_runtime) -> None:
    from canary import env as env_v14
    from canary import rules as rules_v14

    git_v15_sha = diff_sweep.try_resolve_git_commit()
    assert v15_runtime.commit_sha.startswith("de9cc50e")
    assert v15_runtime.pkg_name == "_canary_v15_isolated"
    assert v15_runtime.pkg_name in sys.modules
    assert f"{v15_runtime.pkg_name}.env" in sys.modules
    assert len(v15_runtime.finder.loaded_paths) >= 10
    assert "canary/env.py" in v15_runtime.finder.loaded_paths
    assert "canary/rules.py" in v15_runtime.finder.loaded_paths
    assert v15_runtime.status_unchanged is True

    if git_v15_sha is not None:
        assert v15_runtime.used_embedded_fallback is False
        assert v15_runtime.source_mode == "git_show"
        assert v15_runtime.finder.git_show_paths == v15_runtime.finder.loaded_paths
        embedded_map = diff_sweep.embedded_v15_source_map()
        git_blobs = _batch_git_blobs(REPO_ROOT, git_v15_sha, list(embedded_map))
        for rel_path, embedded_src in embedded_map.items():
            assert embedded_src == git_blobs[rel_path]
    else:
        assert v15_runtime.used_embedded_fallback is True
        assert v15_runtime.source_mode == "embedded_zlib_b64"
        assert v15_runtime.finder.git_show_paths == []

    assert env_v14.Env is not v15_runtime.env_mod.Env
    assert rules_v14.TIERS is not v15_runtime.rules.TIERS
    assert rules_v14.TIERS_VERSION == "v1.4"
    assert diff_sweep.compute_tier_hash(rules_v14.TIERS, rules_v14.KNOWN_V_MODE) == "a8f99c2537c91d72"

    e14 = env_v14.Env("medium", 0)
    e15 = v15_runtime.make_env("medium", 0, social_enabled=True)
    assert not hasattr(e14.p, "social")
    assert e14.p.decoy is True
    assert e15.p.decoy is True
    assert e14._world.mole == e15._world.mole
    assert e14._world.decoy == e15._world.decoy
    assert e15.p.social is True
    assert e15.p.rumour_rate == pytest.approx(2.0)
    assert e15.p.p_misforward == pytest.approx(0.15)
    assert "Office chatter and paperwork mistakes" in e15.instruction()
    assert "Office chatter and paperwork mistakes" not in e14.instruction()


def test_ten_strategies_fast_paired_sweep_invariants(cli_fast_bundle: dict, v15_runtime) -> None:
    from canary.env import Env as EnvV14

    assert cli_fast_bundle["_cli_wall_s"] < 1.8
    assert tuple(cli_fast_bundle["strategy_names"]) == EXPECTED_STRATEGIES
    assert cli_fast_bundle["llm_api_calls"] == 0
    assert cli_fast_bundle["v14_tier_hash_preserved"] is True
    assert cli_fast_bundle["working_tree_unchanged"] is True
    assert cli_fast_bundle["total_invariant_violations"] == 0
    assert cli_fast_bundle["total_strategy_episodes"] == 20
    assert cli_fast_bundle["total_passive_scan_episodes"] == 2

    tdata = cli_fast_bundle["strategy_sweep"]["tiers"]["easy"]
    strats = tdata["strategies"]
    assert set(strats) == set(EXPECTED_STRATEGIES)
    for sname in EXPECTED_STRATEGIES:
        assert strats[sname]["same_world_truth_rate"] == 1.0
        assert strats[sname]["v14"]["invariant_violations"] == 0
        assert strats[sname]["v15"]["invariant_violations"] == 0

    assert strats["do_nothing"]["v14"]["mean_score"] == 0.0
    assert strats["do_nothing"]["v15"]["mean_score"] == 0.0
    assert strats["do_nothing"]["v14"]["abstain_rate"] == 1.0
    assert strats["stop_early"]["v14"]["mean_score"] == 0.0
    assert strats["stop_early"]["v15"]["mean_score"] == 0.0
    assert strats["stop_early"]["v14"]["abstain_rate"] == 1.0
    assert strats["reference_solver"]["v14"]["mean_score"] > 0.4
    assert strats["reference_solver"]["v15"]["mean_score"] > 0.4

    se_ep_14 = diff_sweep.run_single_episode(EnvV14("easy", 0), diff_sweep.make_strategy("stop_early", 0, "v1.4"))
    se_ep_15 = diff_sweep.run_single_episode(
        v15_runtime.make_env("easy", 0, social_enabled=True),
        diff_sweep.make_strategy("stop_early", 0, "v1.5", v15_runtime),
    )
    assert se_ep_14["quit_early"] is True and se_ep_14["done"] is False and se_ep_14["score"] == 0.0
    assert se_ep_15["quit_early"] is True and se_ep_15["done"] is False and se_ep_15["score"] == 0.0


def test_lexical_hygiene_zero_knob_parity_and_interview_audit(cli_fast_bundle: dict) -> None:
    lex = cli_fast_bundle["lexical_and_stream_audit"]
    iv = lex["interview_template_audit"]
    assert iv["evasive_templates_total"] == 16
    assert iv["cooperative_templates_total"] == 16
    assert iv["cooperative_hedge_false_positive_rate"] == 0.0
    assert iv["evasive_hedge_recall"] >= 0.80
    assert iv["evasive_contains_literal_evasive_word"] == 0
    assert iv["solver_v14_marks_template_evasive"] is False
    assert iv["solver_v15_marks_template_evasive"] is False

    tlex = lex["tiers"]["easy"]
    assert tlex["zero_knob_parity"]["all_exact"] is True
    assert tlex["zero_knob_parity"]["social_no_misforward_stream_identical"] is True
    assert tlex["secret_hygiene"]["clean"] is True
    assert tlex["secret_hygiene"]["mole_word_leaks"] == 0
    assert tlex["secret_hygiene"]["secret_token_leaks"] == 0
    assert tlex["secret_hygiene"]["social_messages_scanned"] > 0


def test_shallow_ci_detached_repo_fallback(
    tmp_path: Path, cli_fast_bundle: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from canary import env as env_v14
    from canary import rules as rules_v14

    shallow_tmp = tmp_path / "shallow_ci_detached"
    shallow_tmp.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=shallow_tmp, check=True)
    (shallow_tmp / "README.txt").write_text("shallow depth=1 detached checkout\n", encoding="utf-8")

    assert not (shallow_tmp / ".git" / "refs" / "remotes").exists()
    assert diff_sweep.try_resolve_git_commit(repo_root=shallow_tmp) is None
    assert diff_sweep.resolve_git_commit(repo_root=shallow_tmp) == diff_sweep.EMBEDDED_V15_COMMIT_FULL
    with pytest.raises(RuntimeError):
        diff_sweep.resolve_git_commit(ref="refs/heads/missing-v15-ref", fallback=None, repo_root=shallow_tmp)

    nogit_tmp = tmp_path / "nogit_archive"
    nogit_tmp.mkdir(parents=True)
    (nogit_tmp / "archive_marker.txt").write_text("exported archive without .git\n", encoding="utf-8")
    assert diff_sweep.resolve_head_commit(nogit_tmp) == "nogit0000"
    assert diff_sweep.try_resolve_git_commit(repo_root=nogit_tmp) is None
    assert diff_sweep.resolve_git_commit(repo_root=nogit_tmp) == diff_sweep.EMBEDDED_V15_COMMIT_FULL
    assert "archive_marker.txt:" in diff_sweep.git_status_porcelain(nogit_tmp)

    saved_cache = dict(diff_sweep._RUNTIME_CACHE)
    saved_meta_path = list(sys.meta_path)
    saved_v15_mods = {
        k: v
        for k, v in sys.modules.items()
        if k == "_canary_v15_isolated" or k.startswith("_canary_v15_isolated.")
    }
    try:
        rt_shallow = diff_sweep.load_v15_runtime(repo_root=nogit_tmp)
        assert rt_shallow.used_embedded_fallback is True
        assert rt_shallow.source_mode == "embedded_zlib_b64"
        assert rt_shallow.commit_sha == diff_sweep.EMBEDDED_V15_COMMIT_FULL
        assert rt_shallow.finder.git_show_paths == []
        assert len(rt_shallow.finder.loaded_paths) >= 10
        assert "canary/env.py" in rt_shallow.finder.loaded_paths
        assert "canary/rules.py" in rt_shallow.finder.loaded_paths
        assert rt_shallow.status_unchanged is True
        assert env_v14.Env is not rt_shallow.env_mod.Env
        assert rules_v14.TIERS is not rt_shallow.rules.TIERS
        assert diff_sweep.compute_tier_hash(rules_v14.TIERS, rules_v14.KNOWN_V_MODE) == "a8f99c2537c91d72"

        ep_shallow = diff_sweep.run_single_episode(
            rt_shallow.make_env("easy", 0, social_enabled=True),
            rt_shallow.make_solver(),
        )
        expected_solver_score = cli_fast_bundle["strategy_sweep"]["tiers"]["easy"]["strategies"]["reference_solver"]["v15"]["mean_score"]
        assert ep_shallow["violations"] == []
        assert round(ep_shallow["score"], 4) == expected_solver_score

        def _fast_nogit_audit(
            tiers: list[str],
            seeds: list[int],
            v15_ref: str = "origin/justSilas-v15",
            workers: int = 1,
            repo_root: Path = REPO_ROOT,
            force_embedded: bool = False,
        ) -> dict:
            assert force_embedded is True
            resolved_nogit = repo_root.resolve()
            rt_check = diff_sweep.load_v15_runtime(
                ref=v15_ref,
                repo_root=resolved_nogit,
                force_embedded=force_embedded,
            )
            out = dict(cli_fast_bundle)
            out.pop("_cli_wall_s", None)
            out["shallow_checkout_fallback"] = rt_check.used_embedded_fallback
            out["v15_source_mode"] = rt_check.source_mode
            out["v15_commit_sha"] = rt_check.commit_sha[:8]
            out["v15_modules_loaded"] = len(rt_check.finder.loaded_paths)
            out["v15_git_show_modules_loaded"] = len(rt_check.finder.git_show_paths)
            out["v14_head_sha"] = diff_sweep.resolve_head_commit(resolved_nogit)[:8]
            out["tiers_tested"] = tiers
            out["seed_range"] = [seeds[0], seeds[-1]]
            out["n_seeds"] = len(seeds)
            return out

        fb_json = tmp_path / "shallow_cli_out.json"
        with monkeypatch.context() as mp:
            mp.setattr(diff_sweep, "run_differential_audit", _fast_nogit_audit)
            rc_fb = diff_sweep.main(
                [
                    "--fast",
                    "--seeds",
                    "0",
                    "--tiers",
                    "easy",
                    "--repo-root",
                    str(nogit_tmp),
                    "--shallow-fallback",
                    "--json-out",
                    str(fb_json),
                ]
            )
        assert rc_fb == 0
        fb_payload = json.loads(fb_json.read_text(encoding="utf-8"))
        assert fb_payload["shallow_checkout_fallback"] is True
        assert fb_payload["v15_available"] is True
        assert fb_payload["v14_head_sha"] == "nogit000"
        assert fb_payload["v15_source_mode"] == "embedded_zlib_b64"
        assert fb_payload["v15_commit_sha"] == "de9cc50e"
        assert fb_payload["v15_modules_loaded"] >= 10
        assert fb_payload["v15_git_show_modules_loaded"] == 0
        assert fb_payload["v14_tier_hash_preserved"] is True
        assert fb_payload["working_tree_unchanged"] is True
        assert fb_payload["total_invariant_violations"] == 0
        assert fb_payload["total_strategy_episodes"] == 20
        assert fb_payload["total_passive_scan_episodes"] == 2
    finally:
        for mod_key in [
            k
            for k in list(sys.modules)
            if k == "_canary_v15_isolated" or k.startswith("_canary_v15_isolated.")
        ]:
            sys.modules.pop(mod_key, None)
        sys.modules.update(saved_v15_mods)
        sys.meta_path[:] = saved_meta_path
        diff_sweep._RUNTIME_CACHE.clear()
        diff_sweep._RUNTIME_CACHE.update(saved_cache)


def test_cli_fast_json_smoke(cli_fast_bundle: dict) -> None:
    assert cli_fast_bundle["_cli_wall_s"] < 1.8
    assert cli_fast_bundle["v15_available"] is True
    assert cli_fast_bundle["total_strategy_episodes"] == 20
    assert cli_fast_bundle["total_passive_scan_episodes"] == 2
    assert cli_fast_bundle["total_invariant_violations"] == 0
    assert cli_fast_bundle["v14_tier_hash_preserved"] is True
    assert cli_fast_bundle["working_tree_unchanged"] is True
    summary_text = diff_sweep.format_console_summary(cli_fast_bundle)
    assert "reference_solver" in summary_text
    assert "Paired Differential Sweep" in summary_text


def test_exclusive_files_hygiene_and_report_completeness() -> None:
    script_path = REPO_ROOT / "scripts" / "integrity_v14_v15_differential_sweep.py"
    report_path = REPO_ROOT / "docs" / "reports" / "integrity_v14_v15_differential_sweep.md"
    test_path = Path(__file__).resolve()

    for owned_path in (script_path, report_path, test_path):
        assert owned_path.stat().st_size <= 200 * 1024

    script_txt = script_path.read_text(encoding="utf-8")
    report_txt = report_path.read_text(encoding="utf-8")
    test_txt = test_path.read_text(encoding="utf-8")

    for forbidden_dash in ("\u2014", "\u2013"):
        assert forbidden_dash not in script_txt
        assert forbidden_dash not in report_txt
        assert forbidden_dash not in test_txt

    hash_char = chr(35)
    assert hash_char not in script_txt
    assert hash_char not in test_txt

    for py_txt in (script_txt, test_txt):
        comment_toks = [
            tok for tok in tokenize.generate_tokens(io.StringIO(py_txt).readline)
            if tok.type == tokenize.COMMENT
        ]
        assert comment_toks == []

    for sname in EXPECTED_STRATEGIES:
        assert sname in report_txt

    for required_tok in (
        "9225f2ad",
        "de9cc50e",
        "a8f99c2537c91d72",
        "_canary_v15_isolated",
        "6,000",
        "6,600",
        "ISS-DIFF-01",
        "ISS-DIFF-02",
        "ISS-DIFF-03",
        "ISS-DIFF-04",
        "ISS-DIFF-05",
    ):
        assert required_tok in report_txt
