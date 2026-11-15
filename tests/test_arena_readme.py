from __future__ import annotations

import importlib.util
import io
import json
import re
import tokenize
from pathlib import Path
from typing import Any

from canary.env import Env
from canary.rules import KNOWN_V_MODE, TIERS, TIERS_VERSION
from canary.types import INVESTIGATIVE_TOOLS

ROOT = Path(__file__).resolve().parents[1]
README_PATH = ROOT / "docs" / "arena" / "README.md"
DOM_JS_PATH = ROOT / "docs" / "arena" / "ui" / "dom.js"
ARENA_APP_JS_PATH = ROOT / "docs" / "arena" / "ui" / "arena_app.js"
OFFICE_STAGE_JS_PATH = ROOT / "docs" / "arena" / "ui" / "office_stage.js"
INDEX_JS_PATH = ROOT / "docs" / "arena" / "ui" / "index.js"
ARENA_CSS_PATH = ROOT / "docs" / "arena" / "ui" / "arena.css"
CANARY_GAME_PY_PATH = ROOT / "game" / "canary_game.py"
SELF_TEST_PATH = Path(__file__).resolve()

HASH = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)
SLASH_SLASH = chr(47) * 2
SLASH_STAR = chr(47) + chr(42)

FORBIDDEN_ARENA_SECRET_IDENTIFIERS = (
    "CANARY_" + "WORLD_SECRET",
    "CANARY_" + "LEDGER_TOKEN",
    "data/worlds/" + "judge/SALT",
)

CREDENTIAL_PREFIXES = (
    "AI" + "za",
    "s" + "k-proj-",
    "ya" + "29.",
    "h" + "f_",
    "xa" + "i-",
    "gh" + "p_",
)


def _load_canary_game_module() -> Any:
    spec = importlib.util.spec_from_file_location("canary_game_ref", CANARY_GAME_PY_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_committed_episode(rel_jsonl: str, seed: int) -> dict[str, Any]:
    path = ROOT / rel_jsonl
    assert path.is_file(), f"missing committed episode file: {rel_jsonl}"
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("tier") == "hard" and row.get("seed") == seed:
            return row
    raise AssertionError(f"seed {seed} not found in {rel_jsonl}")


def _episode_calls(row: dict[str, Any]) -> int:
    return int(row.get("tool_calls", len(row.get("steps", []))))


def test_self_python_file_has_zero_comments_and_pure_ascii() -> None:
    raw = SELF_TEST_PATH.read_text(encoding="utf-8")
    assert raw.isascii()
    assert HASH not in raw
    assert EM_DASH not in raw
    assert EN_DASH not in raw
    assert UNICODE_MINUS not in raw
    assert SLASH_SLASH not in raw
    assert SLASH_STAR not in raw
    tokens = list(tokenize.generate_tokens(io.StringIO(raw).readline))
    comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
    assert comments == []


def test_arena_readme_exists_ascii_clean_and_surface_safe() -> None:
    assert README_PATH.is_file(), f"missing {README_PATH}"
    txt = README_PATH.read_text(encoding="utf-8")
    assert len(txt.strip()) >= 1500
    assert txt.isascii(), "docs/arena/README.md must be pure ASCII"
    assert EM_DASH not in txt, "docs/arena/README.md must contain zero em dashes"
    assert EN_DASH not in txt, "docs/arena/README.md must contain zero en dashes"
    assert UNICODE_MINUS not in txt, "docs/arena/README.md must contain zero unicode minus chars"

    for secret_tok in FORBIDDEN_ARENA_SECRET_IDENTIFIERS:
        assert secret_tok not in txt, f"forbidden identifier {secret_tok} in docs/arena/README.md"
    for cred_pfx in CREDENTIAL_PREFIXES:
        assert cred_pfx not in txt, f"credential prefix {cred_pfx} in docs/arena/README.md"
    assert re.search(r"""(?:call_json|run)\s*\(\s*["']status["']""", txt) is None

    for duel_seed in (6, 26):
        mole_id = Env("hard", duel_seed)._world.mole
        assert re.search(rf"\b{re.escape(mole_id)}\b", txt) is None, (
            f"docs/arena/README.md must not spoil hidden mole {mole_id} for seed {duel_seed}"
        )


def test_arena_readme_documents_keyless_static_serving_and_module_paths() -> None:
    txt = README_PATH.read_text(encoding="utf-8")
    assert "python3 -m http.server" in txt
    assert "127.0.0.1:8000/docs/arena/" in txt
    assert "0 API keys" in txt
    assert "canary_arena_leaderboard_v1" in txt
    assert "py/manifest.json" in txt

    for existing_path in (
        README_PATH,
        DOM_JS_PATH,
        OFFICE_STAGE_JS_PATH,
        ARENA_APP_JS_PATH,
        ARENA_CSS_PATH,
        INDEX_JS_PATH,
    ):
        assert existing_path.is_file(), f"expected arena file to exist: {existing_path}"
        rel = existing_path.relative_to(ROOT).as_posix()
        assert rel in txt, f"docs/arena/README.md missing module table reference to {rel}"


def test_arena_readme_matches_pyodide_env_and_rules_v14_contract() -> None:
    txt = README_PATH.read_text(encoding="utf-8")
    assert TIERS_VERSION == "v1.4"
    assert KNOWN_V_MODE is True
    assert 'TIERS_VERSION = "v1.4"' in txt
    assert "KNOWN_V_MODE = True" in txt
    assert "canary/env.py" in txt
    assert "canary/rules.py" in txt
    assert "Pyodide" in txt

    hard = TIERS["hard"]
    med = TIERS["medium"]
    assert str(hard.n_employees) in txt and "e01`..`e40" in txt
    assert str(med.n_employees) in txt and "e01`..`e20" in txt
    assert str(hard.n_days) in txt and str(med.n_days) in txt
    assert str(hard.tool_call_cap) in txt and str(med.tool_call_cap) in txt
    assert str(hard.actions_per_day) in txt
    assert f"{hard.fingerprint_accuracy:.2f}" in txt
    assert f"{hard.wrong_accusation_score:.2f}" in txt

    env = Env("hard", 6)
    tool_names = [t["name"] for t in env.tools_spec()]
    assert len(tool_names) == 13
    for tool_name in tool_names:
        assert f"`{tool_name}`" in txt, f"docs/arena/README.md missing tool `{tool_name}`"

    uncosted = set(tool_names) - set(INVESTIGATIVE_TOOLS)
    assert len(INVESTIGATIVE_TOOLS) == 8
    assert len(uncosted) == 5
    assert "8 tools" in txt and "5 tools" in txt


def test_arena_readme_covers_all_four_modes_and_committed_seed_numbers() -> None:
    txt = README_PATH.read_text(encoding="utf-8")
    dom_src = DOM_JS_PATH.read_text(encoding="utf-8")
    app_src = ARENA_APP_JS_PATH.read_text(encoding="utf-8")
    cg_mod = _load_canary_game_module()

    for mode_id, mode_label in (
        ("duel", "Duel vs Gemini"),
        ("solver", "Beat the Solver"),
        ("mole", "Be the Mole"),
        ("living", "Living Office"),
    ):
        assert f'id: "{mode_id}"' in dom_src
        assert f"`{mode_id}`" in txt
        assert mode_label in txt

    assert "DEFAULT_DUEL_SEEDS = [6, 26]" in dom_src
    assert "DEFAULT_DUEL_SEEDS = [6, 26]" in txt
    assert f"{cg_mod.SEED_MIN}-{cg_mod.SEED_MAX}" in txt
    assert "SolverPolicy" in txt

    oc_s6 = _load_committed_episode(
        "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl", 6
    )
    oc_s26 = _load_committed_episode(
        "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl", 26
    )
    ip_s6 = _load_committed_episode(
        "data/runs/committed/v1.4/inproc-gemini-4-carbon/hard/episodes.jsonl", 6
    )
    sol_s6 = _load_committed_episode(
        "data/runs/committed/v1.4/reference/solver-hard-20261114-121126/episodes.jsonl", 6
    )
    sol_s26 = _load_committed_episode(
        "data/runs/committed/v1.4/reference/solver-hard-seeds20to29/episodes.jsonl", 26
    )

    assert oc_s6["correct"] is True and f"+{oc_s6['score']:.2f}" in txt
    assert f"Day {oc_s6['final_day']}" in txt and f"{_episode_calls(oc_s6)} tool calls" in txt
    assert sol_s6["correct"] is True and f"+{sol_s6['score']:.2f}" in txt
    assert f"{_episode_calls(sol_s6)} tool calls" in txt
    assert ip_s6["correct"] is False and f"{ip_s6['score']:.2f}" in txt

    assert oc_s26["correct"] is False and f"{oc_s26['score']:.2f}" in txt
    assert f"Day {oc_s26['final_day']}" in txt and f"{_episode_calls(oc_s26)} tool calls" in txt
    assert sol_s26["correct"] is True and f"+{sol_s26['score']:.2f}" in txt
    assert f"Day {sol_s26['final_day']}" in txt and f"{_episode_calls(sol_s26)} tool calls" in txt

    assert "Did NOT pass Gate B" in app_src
    assert "0.452" in app_src and "0.493" in app_src
    assert "Did NOT pass Gate B" in txt
    assert "0.452" in txt and "0.493" in txt
    assert "off-by-default" in txt.lower()
    assert "v1.6" in txt


def test_arena_readme_documents_sealed_zero_leak_and_xss_invariants() -> None:
    txt = README_PATH.read_text(encoding="utf-8")
    app_src = ARENA_APP_JS_PATH.read_text(encoding="utf-8")

    assert "[SEALED]" in txt
    assert "Accusation filed [SEALED]" in txt
    for fn_name in (
        "mountArenaUI",
        "scrubPreEndObject",
        "sanitizeStepForPreEnd",
        "sanitizeGeminiReplayState",
        "sanitizeSolverLiveState",
        "OfficeStage",
        "revealOutcome",
    ):
        assert fn_name in txt, f"docs/arena/README.md missing `{fn_name}`"

    key_block_match = re.search(
        r"const\s+FORBIDDEN_PRE_END_KEYS\s*=\s*new\s+Set\(\[(.*?)\]\);",
        app_src,
        re.DOTALL,
    )
    assert key_block_match is not None
    forbidden_keys = re.findall(r'"([^"]+)"', key_block_match.group(1))
    assert len(forbidden_keys) >= 8
    for fkey in forbidden_keys:
        assert f"`{fkey}`" in txt, f"docs/arena/README.md missing FORBIDDEN_PRE_END_KEYS entry `{fkey}`"

    assert "40x24" in txt
    assert "createElement" in txt and "createTextNode" in txt
    assert "innerHTML" in txt
