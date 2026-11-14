"""Zero-API tests: the Gemini frontier backend (gemini-4-*): defaults, request shape, thought-signature replay."""
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from canary.agents.llm_policy import LLMPolicy
from canary.agents.loop import run_episode
from fake_env import FakeEnv

TOOLS = [{"name": "status", "description": "get status", "input_schema": {"type": "object", "properties": {}}},
         {"name": "accuse", "description": "accuse", "input_schema": {
             "type": "object", "properties": {"employee": {"type": "string"}}, "required": ["employee"]}}]


def _resp(*parts, cached=0):
    from google.genai import types
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)), finish_reason="STOP")],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=1000, candidates_token_count=20, thoughts_token_count=30,
            cached_content_token_count=cached))


def _fc(name, args, sig=b"SIG", cid=None):
    from google.genai import types
    return types.Part(function_call=types.FunctionCall(id=cid, name=name, args=args), thought_signature=sig)


class FakeSDK:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []
        self.models = NS(generate_content=self._gen)

    def _gen(self, **req):
        self.requests.append(req)
        return self.responses.pop(0)


def test_default_model_is_gemini_4_carbon(monkeypatch):
    from canary.llm import default_gemini_model
    from canary.llm.gemini_backend import GeminiClient
    monkeypatch.delenv("CANARY_GEMINI_MODEL", raising=False)
    assert GeminiClient(None, sdk_client=FakeSDK([])).model == "gemini-4-carbon" == default_gemini_model()
    from canary.agents.play import resolve_agent
    assert resolve_agent("gemini") == "gemini:gemini-4-carbon"
    monkeypatch.setenv("CANARY_GEMINI_MODEL", "gemini-4-argon")
    assert GeminiClient(None, sdk_client=FakeSDK([])).model == "gemini-4-argon"


def test_gemini4_request_shape_no_temperature_thinking(monkeypatch):
    from google.genai import types
    from canary.llm.gemini_backend import GeminiClient
    monkeypatch.delenv("CANARY_GEMINI_THINKING_LEVEL", raising=False)
    sdk = FakeSDK([_resp(types.Part(text="plan", thought=True), _fc("status", {}), cached=800)])
    c = GeminiClient("gemini-4-carbon", sdk_client=sdk)
    r = c.chat([{"role": "system", "content": "SYS"}, {"role": "user", "content": "go"}], tools=TOOLS, temperature=0.0)
    cfg = sdk.requests[0]["config"]
    assert cfg.temperature is None                                  # Gemini 3+: keep the API default
    assert cfg.thinking_config.include_thoughts is True and cfg.thinking_config.thinking_level is None
    assert cfg.thinking_config.thinking_budget is None and cfg.system_instruction == "SYS"
    assert cfg.automatic_function_calling.disable is True
    assert [t.name for t in r.tool_calls] == ["status"] and r.tool_calls[0].id.startswith("gen_")
    assert r.thoughts == "plan" and r.text == ""
    assert r.usage["in"] == 1000 and r.usage["out"] == 50 and r.usage["cached_in"] == 800
    assert r.usage["cost_usd"] == pytest.approx((1000 * 2 + 50 * 10) / 1e6)
    assert r.usage["cost_usd_est"] == pytest.approx((200 * 2 + 800 * 0.1 + 50 * 10) / 1e6)
    assert r.provider_items[0]["parts"][1]["thought_signature"]       # JSON-safe (base64)
    json.dumps(r.provider_items)
    s = c.settings()
    assert s["thought_signature_replay"] and "medium" in s["thinking_level"] and "not sent" in s["temperature"]
    monkeypatch.setenv("CANARY_GEMINI_THINKING_LEVEL", "high")
    c2 = GeminiClient("gemini-4-carbon", sdk_client=FakeSDK([_resp(_fc("status", {}))]))
    c2.chat([{"role": "user", "content": "go"}], tools=TOOLS)
    assert c2.sdk.requests[0]["config"].thinking_config.thinking_level == types.ThinkingLevel.HIGH
    with pytest.raises(ValueError):
        GeminiClient("gemini-4-carbon", sdk_client=FakeSDK([]), thinking_level="max")


def test_thought_signatures_replayed_through_policy():
    from google.genai import types
    from canary.llm.gemini_backend import GeminiClient
    sdk = FakeSDK([_resp(types.Part(text="t1", thought=True), _fc("status", {}, sig=b"S1")),
                   _resp(_fc("accuse", {"employee": "e03"}, sig=b"S2"))])
    client = GeminiClient("gemini-4-carbon", sdk_client=sdk)
    pol = LLMPolicy("gemini:gemini-4-carbon", client=client)
    res = run_episode(FakeEnv(), pol, "x")
    assert [s.tool for s in res.steps] == ["status", "accuse"] and res.correct
    second = sdk.requests[1]["contents"]
    assert [c.role for c in second] == ["user", "model", "user"]
    model_turn = second[1]
    assert model_turn.parts[0].thought is True and model_turn.parts[1].thought_signature == b"S1"   # verbatim
    fr = second[2].parts[0].function_response
    assert fr.name == "status" and fr.id is None and fr.response["ok"] is True   # local gen_ id never sent
    json.dumps(pol.transcript)                                       # transcript stays JSON-serialisable


def test_parallel_calls_and_api_ids_roundtrip():
    from canary.llm.gemini_backend import GeminiClient
    sdk = FakeSDK([_resp(_fc("status", {}, cid="a1"), _fc("status", {}, sig=None, cid="a2")),
                   _resp(_fc("accuse", {"employee": "e03"}))])
    pol = LLMPolicy("gemini:gemini-4-carbon", client=GeminiClient("gemini-4-carbon", sdk_client=sdk))
    res = run_episode(FakeEnv(), pol, "x")
    assert [s.tool for s in res.steps] == ["status", "status", "accuse"]
    last_user = sdk.requests[1]["contents"][-1]
    assert [p.function_response.id for p in last_user.parts] == ["a1", "a2"]   # one user turn, API ids kept


@pytest.mark.parametrize("tier", ["medium", "hard"])
def test_gemini_request_parity_with_mcp_prompt_and_tools(tier, monkeypatch):
    """What the in-process Gemini loop sends == the OpenCode task prompt + the MCP tools (byte-identical text)."""
    monkeypatch.setenv("CANARY_ALLOW_DEV", "1")
    from canary.agents.frontier.common import episode_prompt
    from canary.env import Env
    from canary.llm.gemini_backend import GeminiClient
    env = Env(tier, 0)
    sdk = FakeSDK([_resp(_fc("status", {}))])
    pol = LLMPolicy("gemini:gemini-4-carbon", client=GeminiClient("gemini-4-carbon", sdk_client=sdk))
    pol.reset(env.tools_spec(), env.instruction())
    pol.act([])
    cfg = sdk.requests[0]["config"]
    assert cfg.system_instruction.encode() == episode_prompt(tier, 0).encode()
    fds = cfg.tools[0].function_declarations
    sent = [{"name": f.name, "description": f.description, "input_schema": f.parameters_json_schema} for f in fds]
    want = [{"name": t["name"], "description": t.get("description", ""), "input_schema": t.get("input_schema") or t.get("parameters")}
            for t in env.tools_spec()]
    assert json.dumps(sent, sort_keys=True) == json.dumps(want, sort_keys=True) and len(sent) == 13


def test_empty_model_turn_is_not_sent_as_empty_part():
    from canary.llm.gemini_backend import to_gemini_contents
    _, contents = to_gemini_contents([{"role": "user", "content": "go"}, {"role": "assistant", "content": ""},
                                      {"role": "user", "content": "Please call a tool now"}])
    assert [c.role for c in contents] == ["user", "user"]


def test_play_meta_records_gemini_settings(tmp_path, monkeypatch):
    from google.genai import types
    from canary.agents import play
    from canary.llm.gemini_backend import GeminiClient
    monkeypatch.delenv("CANARY_GEMINI_THINKING_LEVEL", raising=False)
    sdk = FakeSDK([_resp(types.Part(text="t", thought=True), _fc("accuse", {"employee": "e03"}))])
    out = play.main(["--agent", "gemini:gemini-4-carbon", "--seeds", "0", "--fake", "--out", str(tmp_path / "g")],
                    client=GeminiClient("gemini-4-carbon", sdk_client=sdk))
    m = json.loads((out / "meta.json").read_text())
    assert m["model"] == "gemini-4-carbon" and m["provider"] == "gemini" and m["reasoning_effort"] is None
    assert m["provider_settings"]["thought_signature_replay"] is True and m["api"] == "generateContent"
    ep = json.loads((out / "episodes.jsonl").read_text().splitlines()[0])
    assert ep["meta"]["finish_reasons"] and ep["meta"]["provider_settings"]["include_thoughts"] is True


# ---------------- OpenCode + Gemini over MCP (command, env isolation, usage, infra classification)
def test_opencode_gemini_cmd_env_isolation(monkeypatch):
    from canary.agents.frontier import opencode_run
    from canary.agents.frontier.common import REPO_ROOT, assert_clean, make_clean_workdir
    monkeypatch.setenv("GEMINI_API_KEY", "g-test-key")
    wd = make_clean_workdir()
    cmd = opencode_run.build_cmd(wd, "PROMPT", "gemini-4-carbon", "http://127.0.0.1:9/mcp")
    assert cmd[:4] == ["opencode", "run", "--model", "google/gemini-4-carbon"] and cmd[-1] == "PROMPT"
    assert opencode_run.DEFAULT_MODEL == "google/gemini-4-carbon"
    assert_clean(wd, opencode_run.FILES)
    env, cleanup = opencode_run.child_env_extra("google/gemini-4-carbon")(wd)
    home = Path(env["XDG_DATA_HOME"]).parent
    assert env["GOOGLE_GENERATIVE_AI_API_KEY"] == "g-test-key" and env["OPENCODE_DISABLE_CLAUDE_CODE"] == "1"
    assert cleanup == [home] and wd not in home.parents and REPO_ROOT not in home.parents
    assert {env["XDG_CONFIG_HOME"], env["XDG_STATE_HOME"]} == {str(home / "config"), str(home / "state")}
    env2, _ = opencode_run.child_env_extra("openai/x")(wd)
    assert "GOOGLE_GENERATIVE_AI_API_KEY" not in env2


def test_run_seeds_passes_child_env_extra_and_cleans_up(tmp_path, monkeypatch):
    from canary.agents.frontier import opencode_run
    from canary.agents.frontier.common import RunSpec, run_seeds
    monkeypatch.setenv("GEMINI_API_KEY", "g-test-key")
    seen = {}

    class FakeServer:
        def __init__(self, tier, seed):
            self.tier, self.seed, self.token, self.url = tier, seed, "SECRETTOKEN", "http://127.0.0.1:1/mcp"

        def start(self, **kw):
            return self

        def ledger(self):
            return {"score": 0.7, "done": True, "end_reason": "accused", "accused": "e01", "accused_correct": True,
                    "tier": self.tier, "final_day": 5, "V": 0.7, "ledger": []}

        def stop(self):
            pass

    sig = "A" * 300
    out = "\n".join([
        json.dumps({"type": "tool_use", "part": {"type": "tool", "tool": "canary_status", "state": {
            "status": "completed", "input": {}, "output": json.dumps({"ok": True, "data": {"day": 1}})},
            "metadata": {"google": {"thoughtSignature": sig}}}}),
        json.dumps({"type": "step_finish", "part": {"type": "step-finish", "tokens": {
            "input": 1000, "output": 10, "reasoning": 90, "cache": {"read": 4000, "write": 0}}, "cost": 0.01}})])

    def runner(argv, cwd, env, **kw):
        seen["env"] = env
        assert Path(env["XDG_DATA_HOME"]).parent.exists() and "GEMINI_API_KEY" not in env
        return type("P", (), {"returncode": 0, "stdout": out, "stderr": ""})()

    spec = RunSpec("opencode:google/gemini-4-carbon", "medium", [0], tmp_path / "r",
                   child_env_extra=opencode_run.child_env_extra("google/gemini-4-carbon"))
    res = run_seeds(spec, lambda wd, p, url: opencode_run.build_cmd(wd, p, "google/gemini-4-carbon", url),
                    opencode_run.FILES, runner=runner, server_factory=FakeServer)
    assert res[0].score == 0.7 and [s.tool for s in res[0].steps] == ["status"]
    assert not Path(seen["env"]["XDG_DATA_HOME"]).parent.exists()           # per-episode OpenCode home removed
    u = res[0].meta["usage"]
    assert (u["in"], u["cached_in"], u["out"], u["llm_calls"]) == (5000, 4000, 100, 1)
    assert u["cost_usd_est"] == pytest.approx((1000 * 2 + 4000 * 0.1 + 100 * 10) / 1e6, abs=1e-4)
    tr = (tmp_path / "r" / "transcripts" / "0.txt").read_text()
    assert sig not in tr and "thoughtSignature" in tr                        # opaque blob compacted


def test_classify_infra_only_uses_cli_error_events():
    from canary.agents.frontier.common import classify_infra
    tool_out = json.dumps({"type": "tool_use", "part": {"state": {"output": "UNAVAILABLE RESOURCE_EXHAUSTED"}}})
    assert classify_infra(tool_out, "") is None                               # env text never classified
    err = json.dumps({"type": "error", "error": {"name": "APIError", "data": {"message": "RESOURCE_EXHAUSTED"}}})
    assert classify_infra(err, "") == "provider_rate_limit"
    err2 = json.dumps({"type": "error", "error": {"data": {"message": "The model is overloaded"}}})
    assert classify_infra(err2, "") == "provider_unavailable"
    assert classify_infra(json.dumps({"type": "error", "error": {"name": "Weird"}}), "") == "cli_error_event"
