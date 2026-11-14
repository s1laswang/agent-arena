from train.windows import IGNORE, char_spans, make_windows
from train.render import render_messages
from train.fake import FakeEnv, FakeSolver
from train.export_sft import run_episode


def fake_render(msgs, gen):
    s = ""
    for m in msgs:
        body = m.get("content") or str(m.get("tool_calls"))
        s += f"<{m['role']}>{body}</>"
    return s + ("<assistant>" if gen else "")


def char_tok(text):
    return [ord(c) for c in text], [(i, i + 1) for i in range(len(text))]


def episode_msgs():
    ep = run_episode(FakeEnv("easy", 3), FakeSolver())
    return render_messages("rules", ep.steps)


def test_single_window_labels_exactly_assistant_bodies():
    msgs = episode_msgs()
    full, he, bounds, asst = char_spans(msgs, fake_render)
    ids, offs = char_tok(full)
    ws = make_windows(ids, offs, he, bounds, asst, max_len=10**6)
    assert len(ws) == 1
    inp, lab = ws[0]
    lab_text = "".join(chr(x) for x in lab if x != IGNORE)
    want = "".join(full[s:e] for s, e in asst)
    assert lab_text == want and inp == ids[: asst[-1][1]]


def test_windows_cover_each_assistant_turn_once_and_fit():
    msgs = episode_msgs()
    full, he, bounds, asst = char_spans(msgs, fake_render)
    ids, offs = char_tok(full)
    L = he + 400
    ws = make_windows(ids, offs, he, bounds, asst, max_len=L)
    assert len(ws) > 1
    total = 0
    for inp, lab in ws:
        assert len(inp) <= L and inp[:he] == ids[:he]
        assert lab[-1] != IGNORE  # ends at an assistant turn
        total += sum(1 for x in lab if x != IGNORE)
    assert total == sum(e - s for s, e in asst)


def long_msgs(n_turns=40):
    from canary.types import Step
    steps = [Step(i, 1, "read_access_logs", {"day_from": i, "day_to": i},
                  {"ok": True, "data": {"rows": "x" * (50 + 7 * (i % 5))}, "error": None})
             for i in range(n_turns)]
    return render_messages("rules " * 20, steps)


import pytest


@pytest.mark.parametrize("mode,overlap", [("dense", 0), ("dense", 64), ("prefix", 0)])
def test_dense_each_assistant_token_once(mode, overlap):
    msgs = long_msgs()
    full, he, bounds, asst = char_spans(msgs, fake_render)
    ids, offs = char_tok(full)
    L = he + 700
    ws = make_windows(ids, offs, he, bounds, asst, max_len=L, mode=mode, overlap=overlap)
    want = sorted(t for s, e in asst for t in range(s, e))
    got = []
    for inp, lab in ws:
        assert len(inp) <= L and inp[:he] == ids[:he]
        assert lab[-1] != IGNORE
        # recover absolute positions: window body is a contiguous slice of ids
        body = inp[he:]
        start = next(i for i in range(len(ids)) if ids[i:i + len(body)] == body)
        got += [start + i - he for i, x in enumerate(lab) if x != IGNORE]
    assert sorted(got) == want


def test_dense_has_higher_loss_fraction_than_prefix():
    msgs = long_msgs()
    full, he, bounds, asst = char_spans(msgs, fake_render)
    ids, offs = char_tok(full)
    frac = {}
    for mode in ("prefix", "dense"):
        ws = make_windows(ids, offs, he, bounds, asst, max_len=he + 700, mode=mode)
        frac[mode] = sum(sum(x != IGNORE for x in l) for _, l in ws) / sum(len(i) for i, _ in ws)
    assert frac["dense"] > 1.5 * frac["prefix"]
