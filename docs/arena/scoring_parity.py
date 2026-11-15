from __future__ import annotations

import copy
import importlib.util
import inspect
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ARENA_DIR = Path(__file__).resolve().parent
REPO_ROOT = ARENA_DIR.parents[1] if len(ARENA_DIR.parents) >= 2 else ARENA_DIR
if (REPO_ROOT / "canary" / "__init__.py").is_file():
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    loaded_canary = sys.modules.get("canary")
    loaded_file = getattr(loaded_canary, "__file__", None)
    if loaded_file is not None and Path(loaded_file).resolve() != (REPO_ROOT / "canary" / "__init__.py").resolve():
        for mod_key in [k for k in list(sys.modules) if k == "canary" or k.startswith("canary.") or k == "canary_game"]:
            sys.modules.pop(mod_key, None)

from canary import rules
from canary.env import BAD, Env, _SPECS
from canary.eval import MAX_ITERS, make_env, run_episode
from canary.types import EpisodeResult, Step

CANARY_GAME_TIER = "medium"
CANARY_GAME_SEED_MIN = 3000
CANARY_GAME_SEED_MAX = 9999
COMBATANT_ROLES = ("human", "gemini", "solver")
COMBATANT_LABELS = {"human": "Human", "gemini": "Gemini", "solver": "Solver"}
CLIENT_UNAVAILABLE_PREFIX = "Model tried to call unavailable tool"
CRAFT_FINAL_VERDICT_KEYS = ("accused", "correct", "final_day", "tool_calls", "score")
HIDDEN_TRUTH_KEYS = ("mole", "_world", "true_mole")
_HIDDEN_TRUTH_SET = frozenset(HIDDEN_TRUTH_KEYS)


def _parse_int_seed(seed: Any) -> int:
    if isinstance(seed, bool):
        raise ValueError("seed must be an integer")
    try:
        parsed = int(seed)
    except (TypeError, ValueError):
        raise ValueError("seed must be an integer") from None
    if isinstance(seed, float) or str(seed).strip() != str(parsed):
        raise ValueError("seed must be an integer")
    return parsed


def _parse_nonneg_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return int(value)


def _is_done_strict_true(payload: Any) -> bool:
    if not isinstance(payload, Mapping):
        return False
    done_val = payload.get("done")
    return isinstance(done_val, bool) and done_val is True


def find_hidden_truth_keys(
    payload: Any,
    forbidden_keys: Sequence[str] | frozenset[str] = _HIDDEN_TRUTH_SET,
    path: str = "$",
) -> list[str]:
    forbidden = forbidden_keys if isinstance(forbidden_keys, frozenset) else frozenset(str(k) for k in forbidden_keys)
    hits: list[str] = []
    if isinstance(payload, Mapping):
        for raw_key, val in payload.items():
            key_str = raw_key if isinstance(raw_key, str) else str(raw_key)
            child_path = f"{path}.{key_str}"
            if key_str in forbidden:
                hits.append(child_path)
            if isinstance(val, Mapping) or (isinstance(val, Sequence) and not isinstance(val, (str, bytes, bytearray))):
                hits.extend(find_hidden_truth_keys(val, forbidden_keys=forbidden, path=child_path))
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        for idx, item in enumerate(payload):
            if isinstance(item, Mapping) or (isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray))):
                hits.extend(find_hidden_truth_keys(item, forbidden_keys=forbidden, path=f"{path}[{idx}]"))
    return hits


def assert_zero_hidden_truth_pre_done(
    step_payload: Mapping[str, Any],
    forbidden_keys: Sequence[str] = HIDDEN_TRUTH_KEYS,
    step_index: int | None = None,
) -> bool:
    if not isinstance(step_payload, Mapping):
        raise TypeError("step_payload must be a mapping")
    if _is_done_strict_true(step_payload):
        return False
    prefix = f"$[{step_index}]" if step_index is not None else "$"
    hits = find_hidden_truth_keys(step_payload, forbidden_keys=forbidden_keys, path=prefix)
    assert not hits, f"hidden-truth key(s) leaked before done === True: {hits}"
    return True


def verify_pre_done_steps_zero_hidden_truth(
    steps: Sequence[Any],
    forbidden_keys: Sequence[str] = HIDDEN_TRUTH_KEYS,
) -> dict[str, Any]:
    pre_done_checked = 0
    done_skipped = 0
    for idx, raw_step in enumerate(steps):
        if isinstance(raw_step, Step):
            step_res = raw_step.result if isinstance(raw_step.result, Mapping) else {}
            res_data = step_res.get("data") if isinstance(step_res.get("data"), Mapping) else {}
            ep_over = res_data.get("episode_over")
            is_done = isinstance(ep_over, bool) and ep_over is True
            step_map: Mapping[str, Any] = {
                "t": raw_step.t,
                "day": raw_step.day,
                "tool": raw_step.tool,
                "result": raw_step.result,
                "done": is_done,
            }
        elif isinstance(raw_step, Mapping):
            step_map = raw_step
        else:
            raise TypeError(f"step at index {idx} must be a Step or mapping")
        if assert_zero_hidden_truth_pre_done(step_map, forbidden_keys=forbidden_keys, step_index=idx):
            pre_done_checked += 1
        else:
            done_skipped += 1
    return {
        "total_steps": len(steps),
        "pre_done_steps_checked": pre_done_checked,
        "done_steps_skipped": done_skipped,
        "forbidden_keys": list(forbidden_keys),
    }


def craft_final_verdict_from_env(env: Env, tool_calls: int | None = None) -> dict[str, Any]:
    verdict = env.verdict()
    calls = len(env.history) if tool_calls is None else _parse_nonneg_int(tool_calls, "tool_calls")
    return {
        "accused": verdict["accused"],
        "correct": verdict["correct"],
        "final_day": verdict["final_day"],
        "tool_calls": calls,
        "score": verdict["score"],
    }


def craft_final_verdict_from_episode(ep: EpisodeResult | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(ep, EpisodeResult):
        score_val = 0.0 if ep.score == 0.0 else float(ep.score)
        return {
            "accused": ep.accused,
            "correct": ep.correct,
            "final_day": ep.final_day,
            "tool_calls": len(ep.steps),
            "score": score_val,
        }
    if not isinstance(ep, Mapping):
        raise TypeError(f"unsupported episode type: {type(ep).__name__}")
    source = ep["final"] if "score" not in ep and isinstance(ep.get("final"), Mapping) else ep
    if source.get("tool_calls") is not None:
        calls = _parse_nonneg_int(source["tool_calls"], "tool_calls")
    elif "steps" in source and source["steps"] is not None:
        calls = len(source["steps"])
    else:
        raise ValueError("episode mapping must provide tool_calls or steps")
    correct = source["correct"]
    if not isinstance(correct, bool):
        raise ValueError("correct must be a boolean")
    final_day = _parse_nonneg_int(source["final_day"], "final_day")
    if final_day < 1:
        raise ValueError("final_day must be >= 1")
    score_raw = source["score"]
    if not isinstance(score_raw, (int, float)) or isinstance(score_raw, bool) or not math.isfinite(float(score_raw)):
        raise ValueError("score must be a finite number")
    clean_score = 0.0 if float(score_raw) == 0.0 else float(score_raw)
    return {
        "accused": source.get("accused"),
        "correct": correct,
        "final_day": final_day,
        "tool_calls": calls,
        "score": clean_score,
    }


def validate_craft_final_verdict(
    payload: Any,
    *,
    env: Env | None = None,
    episode: EpisodeResult | Mapping[str, Any] | None = None,
    tool_calls: int | None = None,
    exact_keys: bool = True,
) -> dict[str, Any]:
    assert isinstance(payload, Mapping), "craft final verdict must be a mapping"
    expected_key_set = set(CRAFT_FINAL_VERDICT_KEYS)
    actual_key_set = set(payload.keys())
    if exact_keys:
        assert actual_key_set == expected_key_set, (
            f"craft final verdict keys {sorted(actual_key_set)} != {sorted(expected_key_set)}"
        )
    else:
        missing = sorted(expected_key_set - actual_key_set)
        assert not missing, f"craft final verdict missing required keys: {missing}"

    core_slice = {k: payload[k] for k in CRAFT_FINAL_VERDICT_KEYS}
    assert find_hidden_truth_keys(core_slice) == [], "craft final verdict contains hidden-truth keys"

    accused = payload["accused"]
    correct = payload["correct"]
    final_day = payload["final_day"]
    calls = payload["tool_calls"]
    score = payload["score"]

    assert accused is None or (isinstance(accused, str) and len(accused.strip()) > 0), (
        "accused must be None or non-empty employee id"
    )
    assert isinstance(correct, bool), "correct must be a boolean"
    assert isinstance(final_day, int) and not isinstance(final_day, bool) and final_day >= 1, (
        "final_day must be an integer >= 1"
    )
    assert isinstance(calls, int) and not isinstance(calls, bool) and calls >= 0, (
        "tool_calls must be an integer >= 0"
    )
    assert isinstance(score, (int, float)) and not isinstance(score, bool) and math.isfinite(float(score)), (
        "score must be a finite number"
    )

    if accused is None:
        assert correct is False, "correct must be False when accused is None"
        assert float(score) == 0.0, "score must be 0.0 when accused is None"
    if correct is True:
        assert accused is not None, "accused must not be None when correct is True"

    clean_score = 0.0 if float(score) == 0.0 else float(score)
    normalized = {
        "accused": accused,
        "correct": correct,
        "final_day": final_day,
        "tool_calls": calls,
        "score": clean_score,
    }

    if tool_calls is not None:
        assert normalized["tool_calls"] == _parse_nonneg_int(tool_calls, "tool_calls")

    if env is not None:
        expected_env = craft_final_verdict_from_env(env, tool_calls=tool_calls)
        assert normalized == expected_env, f"craft final {normalized} != Env.verdict() {expected_env}"

    if episode is not None:
        expected_ep = craft_final_verdict_from_episode(episode)
        assert normalized == expected_ep, f"craft final {normalized} != run_episode {expected_ep}"

    return normalized


def _expected_known_v(env: Env) -> float:
    if not rules.KNOWN_V_MODE:
        return round(env.V, 10)
    surfaced = sum(1 for item in env._feed if item["surfaced_day"] <= env.day)
    return round(max(0.0, 1.0 - env.p.leak_damage * surfaced - env._costs), 10)


def _is_client_only_step(tool: Any, result: Any) -> bool:
    return (
        tool not in _SPECS
        and isinstance(result, dict)
        and result.get("ok") is False
        and isinstance(result.get("error"), str)
        and result["error"].startswith(CLIENT_UNAVAILABLE_PREFIX)
    )


def actions_from_episode(ep: EpisodeResult | Mapping[str, Any]) -> list[list[Any]]:
    raw_steps = ep.steps if isinstance(ep, EpisodeResult) else ep.get("steps", [])
    actions: list[list[Any]] = []
    for st in raw_steps:
        if isinstance(st, Step):
            tool, args, res = st.tool, st.args, st.result
        else:
            tool, args, res = st["tool"], st.get("args", {}), st.get("result")
        if _is_client_only_step(tool, res):
            continue
        actions.append([tool, copy.deepcopy(args)])
    return actions


def record_policy_actions(tier: str, seed: int, policy: Any) -> tuple[EpisodeResult, list[list[Any]]]:
    ep = run_episode(make_env(tier, _parse_int_seed(seed), "template"), policy)
    return ep, actions_from_episode(ep)


class RecordedActionsPolicy:
    name = "recorded_actions"

    def __init__(self, actions: Sequence[Sequence[Any]], name: str = "recorded_actions") -> None:
        self.name = name
        normalized: list[tuple[Any, Any]] = []
        for idx, item in enumerate(actions):
            if not isinstance(item, Sequence) or isinstance(item, (str, bytes)) or len(item) != 2:
                raise ValueError(f"action at index {idx} must be a 2-item [tool, args] pair")
            normalized.append((item[0], copy.deepcopy(item[1])))
        self._actions = normalized
        self._idx = 0
        self.tools_spec: list[dict[str, Any]] = []
        self.instruction = ""

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        self._idx = 0
        self.tools_spec = list(tools_spec)
        self.instruction = instruction

    def act(self, history: list[Step]) -> tuple[Any, Any]:
        if self._idx >= len(self._actions):
            raise StopIteration("recorded actions exhausted before episode end")
        tool, args = self._actions[self._idx]
        self._idx += 1
        return tool, copy.deepcopy(args)


def run_recorded_actions(
    tier: str,
    seed: int,
    actions: Sequence[Sequence[Any]],
    name: str = "recorded_actions",
) -> EpisodeResult:
    policy = RecordedActionsPolicy(actions, name=name)
    env = make_env(tier, _parse_int_seed(seed), "template")
    if len(actions) < MAX_ITERS:
        return run_episode(env, policy)
    return run_episode(env, policy, max_iters=len(actions) + 1)


class ArenaSession:
    def __init__(self, tier: str, seed: Any) -> None:
        self.tier = str(tier)
        self.seed = _parse_int_seed(seed)
        self.env = Env(self.tier, self.seed)
        self.actions: list[list[Any]] = []

    def spec_json(self) -> str:
        return json.dumps({
            "tier": self.tier,
            "seed": self.seed,
            "tiers_version": rules.TIERS_VERSION,
            "tools": self.env.tools_spec(),
            "instruction": self.env.instruction(),
        })

    def peek_status_json(self) -> str:
        return json.dumps(self.env.peek_status())

    def call_json(self, tool: str, args_json: str) -> str:
        try:
            args = json.loads(args_json) if args_json else {}
        except ValueError:
            return json.dumps({
                "ok": False,
                "data": {},
                "error": "arguments are not valid JSON",
                "done": self.env.done,
            })
        res = self.env.call(tool, args)
        self.actions.append([tool, args])
        return json.dumps(
            {"ok": res.ok, "data": res.data, "error": res.error, "done": self.env.done},
            default=str,
        )

    def final_json(self) -> str:
        if not self.env.done:
            return json.dumps({"error": "the episode is not over yet"})
        return json.dumps(craft_final_verdict_from_env(self.env, len(self.actions)))

    def reveal_json(self) -> str:
        if not self.env.done:
            return json.dumps({"error": "the episode is not over yet"})
        verdict = self.env.verdict()
        final = craft_final_verdict_from_env(self.env, len(self.actions))
        return json.dumps({
            "seed": self.seed,
            "tier": self.tier,
            "tiers_version": rules.TIERS_VERSION,
            "final": final,
            "you": {
                "score": verdict["score"],
                "end_reason": verdict["end_reason"],
                "accused": verdict["accused"],
                "correct": verdict["correct"],
                "final_day": verdict["final_day"],
                "tool_calls": len(self.actions),
                "true_V": verdict["V"],
                "visible_V": self.env.visible_V(),
            },
            "mole": self.env._world.mole,
        })

    def actions_json(self) -> str:
        return json.dumps({
            "tier": self.tier,
            "seed": self.seed,
            "tiers_version": rules.TIERS_VERSION,
            "actions": self.actions,
        })


ArenaGame = ArenaSession


def _load_module_from_path(module_name: str, file_path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load module {module_name} from {file_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_canary_game_module() -> Any | None:
    existing = sys.modules.get("canary_game")
    if existing is not None:
        return existing
    for candidate in (REPO_ROOT / "game" / "canary_game.py", ARENA_DIR / "canary_game.py"):
        if candidate.is_file():
            mod = _load_module_from_path("canary_game", candidate)
            sys.modules.setdefault("canary_game", mod)
            return mod
    return None


def discover_arena_game_module(arena_dir: Path | str | None = None) -> Any | None:
    if arena_dir is not None:
        target = Path(arena_dir) / "arena_game.py"
        if not target.is_file():
            return None
        return _load_module_from_path(f"arena_game_{ abs(hash(str(target.resolve()))) }", target)
    for mod_name in ("docs.arena.arena_game", "arena_game"):
        existing = sys.modules.get(mod_name)
        if existing is not None:
            return existing
    default_target = ARENA_DIR / "arena_game.py"
    if not default_target.is_file():
        return None
    mod = _load_module_from_path("arena_game", default_target)
    sys.modules.setdefault("arena_game", mod)
    return mod


def _instantiate_discovered_game(game_cls: Any, mod: Any, tier: str, seed: int) -> Any:
    sig = inspect.signature(game_cls)
    params = [
        p for p in sig.parameters.values()
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    names = [p.name for p in params]
    if len(names) >= 2 and names[0] == "tier":
        return game_cls(tier, seed)
    if "tier" in sig.parameters:
        return game_cls(seed, tier=tier)
    mod_tier = getattr(mod, "TIER", CANARY_GAME_TIER)
    if tier != mod_tier:
        raise ValueError(f"module Game only supports tier {mod_tier}")
    return game_cls(seed)


def _call_discovered_replay(
    replay_fn: Any,
    mod: Any,
    tier: str,
    seed: int,
    actions: list[list[Any]],
) -> dict[str, Any]:
    sig = inspect.signature(replay_fn)
    params = [
        p for p in sig.parameters.values()
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    names = [p.name for p in params]
    if len(names) >= 3 and names[0] == "tier":
        out = replay_fn(tier, seed, actions)
    elif "tier" in sig.parameters:
        out = replay_fn(seed, actions, tier=tier)
    else:
        mod_tier = getattr(mod, "TIER", CANARY_GAME_TIER)
        if tier != mod_tier:
            raise ValueError(f"module replay only supports tier {mod_tier}")
        out = replay_fn(seed, actions)
    if isinstance(out, str):
        return json.loads(out)
    return dict(out)


def verify_arena_game_entrypoints(
    tier: str,
    seed: int,
    actions: Sequence[Sequence[Any]],
    expected: Mapping[str, Any] | None = None,
    arena_dir: Path | str | None = None,
    arena_mod: Any | None = None,
) -> dict[str, Any]:
    mod = arena_mod if arena_mod is not None else discover_arena_game_module(arena_dir)
    if mod is None:
        return {"present": False, "checked": False, "game_checked": False, "replay_checked": False}

    parsed_seed = _parse_int_seed(seed)
    norm_actions = [[step[0], copy.deepcopy(step[1])] for step in actions]
    if expected is None:
        session = ArenaSession(tier, parsed_seed)
        steps_expected = [
            json.loads(session.call_json(tool, json.dumps(args)))
            for tool, args in norm_actions
        ]
        verdict = session.env.verdict()
        expected = {
            "done": session.env.done,
            "score": verdict["score"],
            "correct": verdict["correct"],
            "accused": verdict["accused"],
            "end_reason": verdict["end_reason"],
            "final_day": verdict["final_day"],
            "tool_calls": len(norm_actions),
            "mole": session.env._world.mole,
            "steps": steps_expected,
        }

    expected_final = {
        "accused": expected["accused"],
        "correct": expected["correct"],
        "final_day": expected["final_day"],
        "tool_calls": expected["tool_calls"],
        "score": expected["score"],
    }

    game_cls = getattr(mod, "Game", None)
    replay_fn = getattr(mod, "replay", None)
    game_checked = False
    replay_checked = False
    skipped_reasons: list[str] = []

    if game_cls is not None:
        try:
            g = _instantiate_discovered_game(game_cls, mod, tier, parsed_seed)
        except ValueError as exc:
            skipped_reasons.append(f"Game skipped: {exc}")
        else:
            if hasattr(g, "reveal_json") and not getattr(getattr(g, "env", None), "done", False):
                pre = json.loads(g.reveal_json())
                assert "error" in pre
                assert_zero_hidden_truth_pre_done(pre)
            if hasattr(g, "final_json") and not getattr(getattr(g, "env", None), "done", False):
                pre_final = json.loads(g.final_json())
                assert "error" in pre_final
                assert_zero_hidden_truth_pre_done(pre_final)
            for idx, (tool, args) in enumerate(norm_actions):
                if hasattr(g, "call_json"):
                    step_out = json.loads(g.call_json(tool, json.dumps(args)))
                    assert_zero_hidden_truth_pre_done(step_out, step_index=idx)
                    if "steps" in expected:
                        exp_step = expected["steps"][idx]
                        assert step_out["ok"] == exp_step["ok"]
                        assert step_out["data"] == exp_step["data"]
                        assert step_out["error"] == exp_step["error"]
                else:
                    res = g.call(tool, args)
                    step_done_now = bool(getattr(getattr(g, "env", g), "done", False))
                    assert_zero_hidden_truth_pre_done(
                        {"ok": res.ok, "data": res.data, "error": res.error, "done": step_done_now},
                        step_index=idx,
                    )
                    if "steps" in expected:
                        exp_step = expected["steps"][idx]
                        assert res.ok == exp_step["ok"]
                        assert res.data == exp_step["data"]
                        assert res.error == exp_step["error"]
                is_done = getattr(getattr(g, "env", g), "done", False)
                if hasattr(g, "reveal_json") and not is_done:
                    mid = json.loads(g.reveal_json())
                    assert "error" in mid
                    assert_zero_hidden_truth_pre_done(mid, step_index=idx)
                if hasattr(g, "final_json") and not is_done:
                    mid_final = json.loads(g.final_json())
                    assert "error" in mid_final
                    assert_zero_hidden_truth_pre_done(mid_final, step_index=idx)
            if expected["done"]:
                if hasattr(g, "final_json"):
                    fin_payload = json.loads(g.final_json())
                    assert validate_craft_final_verdict(fin_payload) == expected_final
                if hasattr(g, "reveal_json"):
                    rev = json.loads(g.reveal_json())
                    assert "error" not in rev
                    if isinstance(rev.get("final"), Mapping):
                        assert validate_craft_final_verdict(rev["final"]) == expected_final
                    you = rev["you"] if isinstance(rev.get("you"), Mapping) else (
                        rev["final"] if isinstance(rev.get("final"), Mapping) and "score" not in rev else rev
                    )
                    assert you["score"] == expected["score"]
                    assert you["correct"] == expected["correct"]
                    assert you["accused"] == expected["accused"]
                    if "end_reason" in you:
                        assert you["end_reason"] == expected["end_reason"]
                    assert you["final_day"] == expected["final_day"]
                    assert you["tool_calls"] == expected["tool_calls"]
                    assert validate_craft_final_verdict(
                        you,
                        exact_keys=(set(you.keys()) == set(CRAFT_FINAL_VERDICT_KEYS)),
                    ) == expected_final
                    if "mole" in rev and "mole" in expected:
                        assert rev["mole"] == expected["mole"]
                elif hasattr(g, "env"):
                    gv = g.env.verdict()
                    assert gv["score"] == expected["score"]
                    assert gv["correct"] == expected["correct"]
                    assert gv["accused"] == expected["accused"]
                    assert gv["end_reason"] == expected["end_reason"]
                    assert gv["final_day"] == expected["final_day"]
                    assert craft_final_verdict_from_env(g.env, len(norm_actions)) == expected_final
            game_checked = True

    if replay_fn is not None:
        try:
            rep = _call_discovered_replay(replay_fn, mod, tier, parsed_seed, norm_actions)
        except ValueError as exc:
            skipped_reasons.append(f"replay skipped: {exc}")
        else:
            if isinstance(rep.get("final"), Mapping):
                assert validate_craft_final_verdict(rep["final"]) == expected_final
            target = rep["you"] if isinstance(rep.get("you"), Mapping) else (
                rep["final"] if isinstance(rep.get("final"), Mapping) and "score" not in rep else rep
            )
            assert target["score"] == expected["score"]
            assert target["correct"] == expected["correct"]
            assert target["accused"] == expected["accused"]
            if "end_reason" in target:
                assert target["end_reason"] == expected["end_reason"]
            assert target["final_day"] == expected["final_day"]
            if "tool_calls" in target:
                assert target["tool_calls"] == expected["tool_calls"]
                assert validate_craft_final_verdict(
                    target,
                    exact_keys=(set(target.keys()) == set(CRAFT_FINAL_VERDICT_KEYS)),
                ) == expected_final
            replay_checked = True

    return {
        "present": True,
        "checked": bool(game_checked or replay_checked),
        "game_checked": game_checked,
        "replay_checked": replay_checked,
        "skipped_reasons": skipped_reasons,
    }


def verify_action_list_parity(
    tier: str,
    seed: int,
    actions: Sequence[Sequence[Any]],
    arena_dir: Path | str | None = None,
) -> dict[str, Any]:
    parsed_seed = _parse_int_seed(seed)
    norm_actions: list[list[Any]] = []
    for idx, item in enumerate(actions):
        if not isinstance(item, Sequence) or isinstance(item, (str, bytes)) or len(item) != 2:
            raise ValueError(f"action at index {idx} must be a 2-item [tool, args] pair")
        norm_actions.append([item[0], copy.deepcopy(item[1])])

    session = ArenaSession(tier, parsed_seed)
    spec = json.loads(session.spec_json())
    assert spec["tier"] == tier and spec["seed"] == parsed_seed
    assert session.env.history == [] and session.actions == []
    assert spec["tools"] == Env(tier, parsed_seed + 1).tools_spec()
    assert find_hidden_truth_keys(spec) == []
    assert find_hidden_truth_keys(json.loads(session.peek_status_json())) == []

    reveal_refusals_checked = 0
    if not session.env.done:
        initial_reveal = json.loads(session.reveal_json())
        assert initial_reveal == {"error": "the episode is not over yet"}
        assert "you" not in initial_reveal and "final" not in initial_reveal
        assert_zero_hidden_truth_pre_done(initial_reveal)
        initial_final = json.loads(session.final_json())
        assert initial_final == {"error": "the episode is not over yet"}
        assert_zero_hidden_truth_pre_done(initial_final)
        reveal_refusals_checked += 1

    step_outputs: list[dict[str, Any]] = []
    status_known_v_checks = 0
    unsurfaced_leak_steps = 0
    detail_error_steps = 0
    pre_done_steps_checked = 0

    for idx, (tool, args) in enumerate(norm_actions):
        assert not session.env.done, f"action at step {idx} occurs after episode already ended"
        args_json = json.dumps(args)
        out = json.loads(session.call_json(tool, args_json))
        step_outputs.append(out)
        if assert_zero_hidden_truth_pre_done(out, step_index=idx):
            pre_done_steps_checked += 1
        else:
            assert find_hidden_truth_keys(out) == []

        expected_visible_v = _expected_known_v(session.env)
        assert session.env.visible_V() == expected_visible_v
        peek = json.loads(session.peek_status_json())
        assert peek["V"] == expected_visible_v
        assert find_hidden_truth_keys(peek) == []

        has_unsurfaced = any(f["surfaced_day"] > session.env.day for f in session.env._feed)
        if has_unsurfaced:
            unsurfaced_leak_steps += 1
            if rules.KNOWN_V_MODE:
                assert expected_visible_v > round(session.env.V, 10) or expected_visible_v == 0.0

        if tool == "status" and out["ok"]:
            assert out["data"]["V"] == expected_visible_v
            if has_unsurfaced and rules.KNOWN_V_MODE and expected_visible_v > 0.0:
                assert out["data"]["V"] > round(session.env.V, 10)
            status_known_v_checks += 1
        elif tool == "advance_day" and out["ok"] and "V" in out["data"]:
            assert out["data"]["V"] == expected_visible_v
            status_known_v_checks += 1

        if out["error"] == BAD:
            detail_error_steps += 1
            assert out["ok"] is False
            assert isinstance(out["data"], dict) and set(out["data"]) == {"detail"}
            detail = out["data"]["detail"]
            assert isinstance(detail, str) and len(detail.strip()) > 0
            if session.env._world.mole not in args_json:
                assert session.env._world.mole not in detail

        if not session.env.done:
            mid_reveal = json.loads(session.reveal_json())
            assert mid_reveal == {"error": "the episode is not over yet"}
            assert "you" not in mid_reveal and "final" not in mid_reveal
            assert_zero_hidden_truth_pre_done(mid_reveal, step_index=idx)
            mid_final = json.loads(session.final_json())
            assert mid_final == {"error": "the episode is not over yet"}
            assert_zero_hidden_truth_pre_done(mid_final, step_index=idx)
            reveal_refusals_checked += 1

    eval_res = run_recorded_actions(tier, parsed_seed, norm_actions)
    assert len(session.actions) == len(norm_actions)
    assert len(session.env.history) == len(norm_actions)
    assert len(eval_res.steps) == len(norm_actions)

    for idx, eval_step in enumerate(eval_res.steps):
        expected_step = json.loads(json.dumps(eval_step.result, default=str))
        assert step_outputs[idx]["ok"] == expected_step["ok"]
        assert step_outputs[idx]["data"] == expected_step["data"]
        assert step_outputs[idx]["error"] == expected_step["error"]

    verdict = session.env.verdict()
    true_v = round(float(eval_res.meta["V"]), 10)
    final_visible_v = session.env.visible_V()
    assert verdict["V"] == true_v
    assert verdict["score"] == eval_res.score
    assert verdict["correct"] == eval_res.correct
    assert verdict["accused"] == eval_res.accused
    assert verdict["final_day"] == eval_res.final_day

    craft_final = craft_final_verdict_from_env(session.env, len(session.actions))
    assert validate_craft_final_verdict(
        craft_final,
        env=session.env,
        episode=eval_res,
        tool_calls=len(norm_actions),
    ) == craft_final
    assert craft_final_verdict_from_episode(eval_res) == craft_final

    if session.env.done:
        assert verdict["end_reason"] == eval_res.end_reason
        session_final = json.loads(session.final_json())
        assert validate_craft_final_verdict(
            session_final,
            env=session.env,
            episode=eval_res,
            tool_calls=len(norm_actions),
        ) == craft_final
        reveal = json.loads(session.reveal_json())
        assert "error" not in reveal
        assert reveal["mole"] == session.env._world.mole
        assert validate_craft_final_verdict(
            reveal["final"],
            env=session.env,
            episode=eval_res,
            tool_calls=len(norm_actions),
        ) == craft_final
        you = reveal["you"]
        assert validate_craft_final_verdict(
            you,
            env=session.env,
            episode=eval_res,
            tool_calls=len(norm_actions),
            exact_keys=False,
        ) == craft_final
        assert you["score"] == eval_res.score
        assert you["correct"] == eval_res.correct
        assert you["accused"] == eval_res.accused
        assert you["end_reason"] == eval_res.end_reason
        assert you["final_day"] == eval_res.final_day
        assert you["tool_calls"] == len(eval_res.steps)
        assert you["true_V"] == true_v
        assert you["visible_V"] == final_visible_v
        if eval_res.end_reason == "accused":
            if eval_res.correct:
                assert eval_res.score == true_v
            else:
                assert eval_res.score == float(session.env.p.wrong_accusation_score)
        else:
            assert eval_res.score == 0.0
    else:
        assert verdict["end_reason"] is None
        assert eval_res.end_reason == "error"
        assert eval_res.score == 0.0
        unfinished_reveal = json.loads(session.reveal_json())
        assert unfinished_reveal == {"error": "the episode is not over yet"}
        assert json.loads(session.final_json()) == {"error": "the episode is not over yet"}

    canary_game_checked = False
    if tier == CANARY_GAME_TIER and CANARY_GAME_SEED_MIN <= parsed_seed <= CANARY_GAME_SEED_MAX:
        cg_mod = _load_canary_game_module()
        if cg_mod is not None:
            cg = cg_mod.Game(parsed_seed)
            assert cg.env.history == [] and cg.actions == []
            assert json.loads(cg.reveal_json()) == {"error": "the episode is not over yet"}
            for idx, (tool, args) in enumerate(norm_actions):
                cg_out = json.loads(cg.call_json(tool, json.dumps(args)))
                assert_zero_hidden_truth_pre_done(cg_out, step_index=idx)
                assert cg_out == step_outputs[idx]
                if not cg.env.done:
                    assert json.loads(cg.reveal_json()) == {"error": "the episode is not over yet"}
            assert len(cg.actions) == len(eval_res.steps)
            if cg.env.done:
                cg_rev = json.loads(cg.reveal_json())
                assert "error" not in cg_rev
                assert cg_rev["mole"] == session.env._world.mole
                assert validate_craft_final_verdict(
                    cg_rev["you"],
                    env=session.env,
                    episode=eval_res,
                    tool_calls=len(norm_actions),
                    exact_keys=False,
                ) == craft_final
                assert cg_rev["you"]["score"] == eval_res.score
                assert cg_rev["you"]["correct"] == eval_res.correct
                assert cg_rev["you"]["accused"] == eval_res.accused
                assert cg_rev["you"]["end_reason"] == eval_res.end_reason
                assert cg_rev["you"]["final_day"] == eval_res.final_day
                assert cg_rev["you"]["tool_calls"] == len(eval_res.steps)
            assert cg_mod.replay(parsed_seed, norm_actions) == verdict
            canary_game_checked = True

    arena_game_report = verify_arena_game_entrypoints(
        tier,
        parsed_seed,
        norm_actions,
        expected={
            "done": session.env.done,
            "score": eval_res.score,
            "correct": eval_res.correct,
            "accused": eval_res.accused,
            "end_reason": verdict["end_reason"],
            "final_day": eval_res.final_day,
            "tool_calls": len(eval_res.steps),
            "mole": session.env._world.mole,
            "steps": step_outputs,
        },
        arena_dir=arena_dir,
    )

    return {
        "ok": True,
        "tier": tier,
        "seed": parsed_seed,
        "done": session.env.done,
        "score": eval_res.score,
        "correct": eval_res.correct,
        "accused": eval_res.accused,
        "end_reason": eval_res.end_reason,
        "final_day": eval_res.final_day,
        "tool_calls": len(eval_res.steps),
        "final": craft_final,
        "visible_v": final_visible_v,
        "true_v": true_v,
        "status_known_v_checks": status_known_v_checks,
        "unsurfaced_leak_steps": unsurfaced_leak_steps,
        "detail_error_steps": detail_error_steps,
        "reveal_refusals_checked": reveal_refusals_checked,
        "pre_done_steps_checked": pre_done_steps_checked,
        "canary_game_checked": canary_game_checked,
        "arena_game": arena_game_report,
    }


def _normalize_combatant(raw: EpisodeResult | Mapping[str, Any], role: str) -> dict[str, Any]:
    label = COMBATANT_LABELS[role]
    if isinstance(raw, EpisodeResult):
        score = float(raw.score)
        correct = bool(raw.correct)
        accused = raw.accused
        end_reason = str(raw.end_reason)
        final_day = int(raw.final_day)
        tool_calls = len(raw.steps)
        agent = str(raw.agent)
    elif isinstance(raw, Mapping):
        source = raw["final"] if "score" not in raw and isinstance(raw.get("final"), Mapping) else raw
        if set(source.keys()) == set(CRAFT_FINAL_VERDICT_KEYS):
            validate_craft_final_verdict(source)
        score = float(source["score"])
        correct = bool(source.get("correct", False))
        accused = source.get("accused")
        if "end_reason" in source and source["end_reason"] is not None:
            end_reason = str(source["end_reason"])
        elif "end_reason" in raw and raw["end_reason"] is not None:
            end_reason = str(raw["end_reason"])
        else:
            end_reason = "accused" if (correct or accused is not None) else "horizon"
        final_day = int(source["final_day"])
        if source.get("tool_calls") is not None:
            tool_calls = int(source["tool_calls"])
        elif "steps" in source and source["steps"] is not None:
            tool_calls = len(source["steps"])
        elif "steps" in raw and raw["steps"] is not None:
            tool_calls = len(raw["steps"])
        else:
            raise ValueError(f"{role} result mapping must provide tool_calls or steps")
        agent = str(raw.get("agent", source.get("agent", role)))
    else:
        raise TypeError(f"unsupported result type for {role}: {type(raw).__name__}")

    clean_score = 0.0 if score == 0.0 else round(score, 10)
    final_shape = validate_craft_final_verdict({
        "accused": accused,
        "correct": correct,
        "final_day": final_day,
        "tool_calls": tool_calls,
        "score": clean_score,
    })
    return {
        "role": role,
        "label": label,
        "agent": agent,
        "score": clean_score,
        "correct": correct,
        "accused": accused,
        "end_reason": end_reason,
        "final_day": final_day,
        "tool_calls": tool_calls,
        "final": final_shape,
        "rank_key": [1 if correct else 0, -final_day, -tool_calls, clean_score],
    }


def _combatant_rank_tuple(entry: Mapping[str, Any]) -> tuple[bool, int, int, float]:
    return (
        bool(entry["correct"]),
        -int(entry["final_day"]),
        -int(entry["tool_calls"]),
        float(entry["score"]),
    )


def _format_combatant_share_segment(entry: Mapping[str, Any]) -> str:
    score_val = 0.0 if float(entry["score"]) == 0.0 else float(entry["score"])
    if entry["correct"]:
        outcome = f"caught d{entry['final_day']}"
    elif entry["accused"] is not None or entry["end_reason"] == "accused":
        outcome = f"wrong d{entry['final_day']}"
    elif entry["end_reason"] == "tool_cap":
        outcome = f"cap d{entry['final_day']}"
    else:
        outcome = f"abstain d{entry['final_day']}"
    return f"{entry['label']} {score_val:+.3f} ({outcome}, {entry['tool_calls']} calls)"


def duel_end_screen_summary(
    tier: str,
    seed: int,
    human_res: EpisodeResult | Mapping[str, Any],
    gemini_res: EpisodeResult | Mapping[str, Any],
    solver_res: EpisodeResult | Mapping[str, Any],
) -> dict[str, Any]:
    parsed_seed = _parse_int_seed(seed)
    combatants = {
        "human": _normalize_combatant(human_res, "human"),
        "gemini": _normalize_combatant(gemini_res, "gemini"),
        "solver": _normalize_combatant(solver_res, "solver"),
    }
    ranking = sorted(
        COMBATANT_ROLES,
        key=lambda role: _combatant_rank_tuple(combatants[role]),
        reverse=True,
    )
    caught_first = ranking[0]
    top_tuple = _combatant_rank_tuple(combatants[caught_first])
    tied_leaders = [role for role in COMBATANT_ROLES if _combatant_rank_tuple(combatants[role]) == top_tuple]
    any_caught = any(combatants[role]["correct"] for role in COMBATANT_ROLES)

    scores = {role: combatants[role]["score"] for role in COMBATANT_ROLES}
    score_ranking = sorted(COMBATANT_ROLES, key=lambda role: scores[role], reverse=True)

    segments = " vs ".join(_format_combatant_share_segment(combatants[role]) for role in COMBATANT_ROLES)
    caught_badge = caught_first if any_caught else "none"
    share_line = f"Canary Arena [{tier} seed {parsed_seed}] | {segments} | Caught first: {caught_badge}"
    assert share_line.isascii() and "\n" not in share_line

    return {
        "tier": str(tier),
        "seed": parsed_seed,
        "scores": scores,
        "human": combatants["human"],
        "gemini": combatants["gemini"],
        "solver": combatants["solver"],
        "caught_first": caught_first,
        "caught_first_key": list(combatants[caught_first]["rank_key"]),
        "caught_first_tied": tied_leaders,
        "any_caught": any_caught,
        "ranking": ranking,
        "score_winner": score_ranking[0],
        "score_deltas": {
            "human_vs_gemini": round(scores["human"] - scores["gemini"], 10),
            "human_vs_solver": round(scores["human"] - scores["solver"], 10),
            "gemini_vs_solver": round(scores["gemini"] - scores["solver"], 10),
        },
        "share_line": share_line,
    }
