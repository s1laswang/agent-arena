"""Thought-signature ablation flag: strips provider_items from assistant turns only, and is off by default."""
import copy

from canary.gemini import ladder
from canary.gemini.ledger import LedgeredClient, strip_signatures
from canary.llm import LLMResponse


class Spy:
    model, provider = "gemini-3.8-flash", "gemini"

    def __init__(self):
        self.seen = []

    def settings(self):
        return {"thought_signature_replay": True, "thinking_level": "medium"}

    def chat(self, messages, **kw):
        self.seen.append(copy.deepcopy(messages))
        return LLMResponse(text="ok", usage={"in": 1, "out": 1})


MSGS = [
    {"role": "system", "content": "s", "provider_items": ["not-assistant-kept"]},
    {"role": "user", "content": "u"},
    {"role": "assistant", "content": None, "tool_calls": [{"id": "1", "name": "status", "args": {"a": 1}}],
     "provider_items": [{"role": "model", "parts": [{"thought_signature": "c2ln"}]}]},
    {"role": "tool", "tool_call_id": "1", "name": "status", "content": "{\"ok\": true}"},
    {"role": "assistant", "content": "done"},
]


def _client(tmp_path, monkeypatch, **kw):
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "l.jsonl"))
    spy = Spy()
    return spy, LedgeredClient(spy, feature="test", **kw)


def test_off_by_default_passes_messages_verbatim(tmp_path, monkeypatch):
    spy, c = _client(tmp_path, monkeypatch)
    assert c.drop_signatures is False
    c.chat(MSGS)
    assert spy.seen[0] == MSGS
    assert c.settings()["thought_signature_replay"] is True
    assert ladder.NO_SIGNATURES is False


def test_flag_strips_only_provider_items_from_assistant(tmp_path, monkeypatch):
    before = copy.deepcopy(MSGS)
    spy, c = _client(tmp_path, monkeypatch, drop_signatures=True)
    c.chat(MSGS)
    sent = spy.seen[0]
    assert MSGS == before  # caller's history untouched
    assert "provider_items" not in sent[2]
    expected = copy.deepcopy(MSGS)
    del expected[2]["provider_items"]
    assert sent == expected  # nothing else changed (system message's key, tool_calls, content kept)
    assert c.settings()["thought_signature_replay"] is False


def test_strip_signatures_is_a_copy():
    out = strip_signatures(MSGS)
    assert out is not MSGS and "provider_items" in MSGS[2] and "provider_items" not in out[2]


def test_ladder_cli_flag_sets_and_records(monkeypatch):
    seen = {}

    def fake_run_grid(out, cells, *a, **k):
        seen["flag"] = ladder.NO_SIGNATURES

    monkeypatch.setenv("CANARY_GEMINI_LEDGER", "/tmp/_never_used_ablation.jsonl")
    # ladder.main() does os.environ.setdefault("CANARY_LLM_MAX_RETRIES", "12"); pin it here so monkeypatch
    # restores it afterwards and it cannot leak into tests/test_llm.py (default 5 retries)
    monkeypatch.setenv("CANARY_LLM_MAX_RETRIES", "12")
    monkeypatch.setattr(ladder, "run_grid", fake_run_grid)
    monkeypatch.setattr(ladder, "NO_SIGNATURES", False)
    ladder.main(["--models", "gemini-3.8-flash", "--levels", "medium", "--tiers", "hard", "--seeds", "0",
                 "--out", "/tmp/_never_used_ablation", "--no-thought-signatures"])
    assert seen["flag"] is True
