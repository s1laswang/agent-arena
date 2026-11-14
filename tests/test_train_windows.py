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
