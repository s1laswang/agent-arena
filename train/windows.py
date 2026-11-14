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
                 bounds: list[tuple[int, int]], asst: list[tuple[int, int]], max_len: int,
                 mode: str = "prefix", overlap: int = 256, return_start: bool = False):
    """Returns list of (input_ids, labels).

    mode="prefix": each window starts as EARLY as fits (max context; many overlapping windows).
    mode="dense" : each window starts at the first message boundary >= (end of previous window
                   - overlap), so chunks barely overlap and most tokens carry loss.
    Both: header in every window, windows end at an assistant turn, each assistant token is
    labelled exactly once (a single turn longer than the budget is skipped)."""
    assert mode in ("prefix", "dense")
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
        if mode == "dense":
            near = [c for c in cands if c >= covered - overlap]
            ws = min(near) if near else max(cands)
        else:
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
        out.append((inp, lab, ws) if return_start else (inp, lab))
        covered, k = we, j + 1
    return out


def record_windows(rec: dict, tokenizer, max_len: int, mode: str = "prefix", overlap: int = 256):
    """HF tokenizer path: apply the model's chat template with tools."""
    tools = rec.get("tools")

    def render(m, gen):
        return tokenizer.apply_chat_template(m, tools=tools, tokenize=False,
                                             add_generation_prompt=gen)
    full, header_end, bounds, asst = char_spans(rec["messages"], render)
    enc = tokenizer(full, add_special_tokens=False, return_offsets_mapping=True)
    return make_windows(enc["input_ids"], [tuple(o) for o in enc["offset_mapping"]],
                        header_end, bounds, asst, max_len, mode, overlap)


def is_accuse(msg: dict) -> bool:
    return any(c.get("function", {}).get("name") == "accuse" for c in msg.get("tool_calls") or [])


def windows_ex(ids, offsets, header_end, bounds, asst, accuse_flags, max_len,
               mode="prefix", overlap=256, oversample_endings=0):
    """make_windows + a per-token accuse mask, + optional ending oversampling.

    Returns list of (input_ids, labels, accuse_mask) where accuse_mask[i] is True iff token i
    lies in an assistant turn whose tool call is `accuse`. With oversample_endings=0 the
    (input_ids, labels) are exactly make_windows(...)'s. oversample_endings=K appends K copies of
    one extra window (max context, prefix-style) labelling only the last 2 assistant turns.
    """
    def tok_at(ch):
        lo, hi = 0, len(offsets)
        while lo < hi:
            mid = (lo + hi) // 2
            if offsets[mid][0] < ch:
                lo = mid + 1
            else:
                hi = mid
        return lo

    h = tok_at(header_end)
    acc = [False] * len(ids)
    for (s, e), f in zip(asst, accuse_flags):
        if f:
            for t in range(tok_at(s), tok_at(e)):
                acc[t] = True
    base = make_windows(ids, offsets, header_end, bounds, asst, max_len, mode, overlap, True)
    if oversample_endings > 0 and asst:
        tail = make_windows(ids, offsets, header_end, bounds, asst[-2:], max_len, "prefix", 0, True)
        base += [tail[-1]] * oversample_endings if tail else []
    return [(inp, lab, [False] * h + acc[ws:ws + len(inp) - h]) for inp, lab, ws in base]


def record_windows_ex(rec: dict, tokenizer, max_len: int, mode: str = "prefix",
                      overlap: int = 256, oversample_endings: int = 0):
    tools = rec.get("tools")

    def render(m, gen):
        return tokenizer.apply_chat_template(m, tools=tools, tokenize=False,
                                             add_generation_prompt=gen)
    msgs = rec["messages"]
    full, header_end, bounds, asst = char_spans(msgs, render)
    flags = [is_accuse(m) for m in msgs[2:] if m["role"] == "assistant"]
    enc = tokenizer(full, add_special_tokens=False, return_offsets_mapping=True)
    return windows_ex(enc["input_ids"], [tuple(o) for o in enc["offset_mapping"]], header_end,
                      bounds, asst, flags, max_len, mode, overlap, oversample_endings)


def token_weights(labels, accuse_mask, accuse_weight: float):
    """Per-token weights: accuse_weight on loss tokens inside accuse turns, 1 on other loss
    tokens, 0 elsewhere."""
    return [0.0 if l == IGNORE else (accuse_weight if a else 1.0)
            for l, a in zip(labels, accuse_mask)]
