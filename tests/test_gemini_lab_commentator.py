"""Canary Lab Live commentator (G5): episode -> day turns, keyless (no Live call)."""
from canary.gemini.commentator import day_events


def _ep():
    def st(day, tool, args=None, data=None):
        return {"day": day, "tool": tool, "args": args or {}, "result": {"ok": True, "data": data or {}}}
    return {"seed": 1, "tier": "hard", "score": 0.7, "correct": True, "accused": "e02", "final_day": 2, "steps": [
        st(1, "list_employees", data={"employees": [{"id": "e02", "name": "Ada Lovelace"}]}),
        st(1, "search_messages", {"query": "e"}),
        st(1, "plant_canary", {"doc_title": "Memo", "assignment": {"e01": "vA", "e02": "vB", "e03": "vB"}}),
        st(1, "advance_day", data={"V": 0.98}),
        st(2, "check_leak_feed", data={"items": [{"doc_id": "c1", "title": "Memo", "variant": "vB"}]}),
        st(2, "check_leak_feed", data={"items": [{"doc_id": "c1", "title": "Memo", "variant": "vB"}]}),
        st(2, "accuse", {"employee": "e02"})]}


def test_day_events_tell_the_story_without_noise():
    turns = day_events(_ep(), "Gemini")
    assert [t["day"] for t in turns] == [1, 2, None]
    d1, d2, end = (t["text"] for t in turns)
    assert "1 get variant A, 2 get variant B" in d1 and "'e'" not in d1 and "0.98" in d1
    assert d2.count("LEAK FEED") == 1 and "Ada Lovelace (e02)" in d2 and turns[1]["key"]
    assert "CORRECT" in end and "+0.70" in end
