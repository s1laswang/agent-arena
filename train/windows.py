"""Tokenise a chat record and cut it into training windows (pure Python; no torch).

Each window = [header tokens (system+tools+kickoff)] + a contiguous run of later messages that
starts at a message boundary and ENDS at the end of an assistant turn, length <= max_len.
Loss is on assistant tokens only, and each assistant turn is trained exactly once (in the first
window that covers it, with as much preceding context as fits).
"""
from __future__ import annotations

from typing import Callable

IGNORE = -100


def char_spans(msgs: list[dict], render: Callable[[list[dict], bool], str]):
    """render(msgs, add_generation_prompt) -> text. Returns (full_text, header_end_char,
    msg_bounds[(start,end)] for messages[2:], assistant_spans[(start,end)])."""
    full = render(msgs, False)
    header_end = len(render(msgs[:2], False))
    bounds, asst = [], []
    prev = header_end
    for i in range(2, len(msgs)):
        end = len(render(msgs[:i + 1], False))
        if msgs[i]["role"] == "assistant":
            body_start = len(render(msgs[:i], True))  # after "<|im_start|>assistant\n"
            asst.append((body_start, end))
        bounds.append((prev, end))
        prev = end
    assert full.startswith(render(msgs[:2], False)), "chat template is not prefix-stable"
    return full, header_end, bounds, asst


def make_windows(ids: list[int], offsets: list[tuple[int, int]], header_end: int,
                 bounds: list[tuple[int, int]], asst: list[tuple[int, int]], max_len: int):
    """Returns list of (input_ids, labels)."""
    def tok_at(ch: int) -> int:  # first token whose start >= ch
        lo, hi = 0, len(offsets)
        while lo < hi:
            mid = (lo + hi) // 2
            if offsets[mid][0] < ch:
                lo = mid + 1
            else:
                hi = mid
        return lo

    h = tok_at(header_end)
    budget = max_len - h
    if budget <= 0:
        return []
    starts = [tok_at(b[0]) for b in bounds]
    a_tok = [(tok_at(s), tok_at(e)) for s, e in asst]
    a_tok = [(s, e) for s, e in a_tok if e > s]
    out, covered, k = [], h, 0
    while k < len(a_tok):
        s0, e0 = a_tok[k]
        # earliest message start such that the window [ws, e0) fits
        cands = [s for s in starts if s <= s0 and e0 - s <= budget]
        if not cands:  # single turn longer than the budget: skip it
            covered = e0
            k += 1
            continue
        ws = min(cands)
        we, j = e0, k
        while j + 1 < len(a_tok) and a_tok[j + 1][1] - ws <= budget:
            j += 1
            we = a_tok[j][1]
        inp = ids[:h] + ids[ws:we]
        lab = [IGNORE] * len(inp)
        for s, e in a_tok[k:j + 1]:
            for t in range(max(s, covered), e):
                lab[h + t - ws] = ids[t]
        out.append((inp, lab))
        covered, k = we, j + 1
    return out


def record_windows(rec: dict, tokenizer, max_len: int):
    """HF tokenizer path: apply the model's chat template with tools."""
    tools = rec.get("tools")

    def render(m, gen):
        return tokenizer.apply_chat_template(m, tools=tools, tokenize=False,
                                             add_generation_prompt=gen)
    full, header_end, bounds, asst = char_spans(rec["messages"], render)
    enc = tokenizer(full, add_special_tokens=False, return_offsets_mapping=True)
    return make_windows(enc["input_ids"], [tuple(o) for o in enc["offset_mapping"]],
                        header_end, bounds, asst, max_len)
