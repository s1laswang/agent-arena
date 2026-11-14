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


from train.windows import windows_ex, is_accuse, token_weights


def _setup(n_turns=12):
    from canary.types import Step
    steps = [Step(i, 1, "read_access_logs", {"day_from": i}, {"ok": True, "data": {"r": "x" * 60}, "error": None})
             for i in range(n_turns)]
    steps.append(Step(n_turns, 2, "accuse", {"employee": "e07"}, {"ok": True, "data": {"episode_over": True}, "error": None}))
    msgs = render_messages("rules", steps)
    full, he, bounds, asst = char_spans(msgs, fake_render)
    flags = [is_accuse(m) for m in msgs[2:] if m["role"] == "assistant"]
    ids, offs = char_tok(full)
    return full, he, bounds, asst, flags, ids, offs


@pytest.mark.parametrize("mode", ["prefix", "dense"])
def test_default_flags_reproduce_old_windows(mode):
    full, he, bounds, asst, flags, ids, offs = _setup()
    old = make_windows(ids, offs, he, bounds, asst, he + 400, mode)
    new = windows_ex(ids, offs, he, bounds, asst, flags, he + 400, mode)
    assert [(i, l) for i, l, _ in new] == old


@pytest.mark.parametrize("mode", ["prefix", "dense"])
def test_accuse_weights_land_on_accuse_tokens_only(mode):
    full, he, bounds, asst, flags, ids, offs = _setup()
    acc_text = full[asst[-1][0]:asst[-1][1]]
    assert "accuse" in acc_text and flags[-1] and not any(flags[:-1])
    got = ""
    for inp, lab, m in windows_ex(ids, offs, he, bounds, asst, flags, he + 400, mode):
        w = token_weights(lab, m, 20.0)
        assert all((wi == 20.0) == (l != IGNORE and mi) for wi, l, mi in zip(w, lab, m))
        got += "".join(chr(l) for l, wi in zip(lab, w) if wi == 20.0)
    assert got == acc_text


def test_oversample_endings_adds_k_tail_windows():
    full, he, bounds, asst, flags, ids, offs = _setup()
    base = windows_ex(ids, offs, he, bounds, asst, flags, he + 400, "dense")
    more = windows_ex(ids, offs, he, bounds, asst, flags, he + 400, "dense", oversample_endings=3)
    assert len(more) == len(base) + 3
    for inp, lab, m in more[-3:]:
        lab_text = "".join(chr(x) for x in lab if x != IGNORE)
        assert lab_text == "".join(full[s:e] for s, e in asst[-2:]) or lab_text == full[asst[-1][0]:asst[-1][1]]
        assert any(m) and len(inp) <= he + 400 and inp[:he] == ids[:he]
