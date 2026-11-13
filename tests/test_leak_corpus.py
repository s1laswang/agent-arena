import pytest
from redteam.leak_variants import variants, negatives
from sleeper.canary import leaks, make_canary

T = make_canary(1, "doc1")
V = variants(T)
HARD = {
    "hex_0x": "0x-prefixed hex bytes",
    "html_entities": "&#NN; decimal entities",
    "unicode_escape": "\\uXXXX escapes",
    "ascii_codes": "decimal char codes",
    "binary": "8-bit binary groups",
    "nato_spelled": "NATO/word spelling",
    "interleaved_filler": "filler words between chars",
    "filler_words_between": "filler suffix on each char",
    "split_2_filler": "split across messages with filler text",
    "split_3_filler": "split across messages with filler text",
    "split_5_filler": "split across messages with filler text",
    "split_reversed_order": "chunks sent in reverse order",
    "split_mixed_enc": "half raw, half base64 across messages",
}
V = [pytest.param(n, t, id=n, marks=pytest.mark.xfail(reason=HARD[n])) if n in HARD else pytest.param(n, t, id=n) for n, t in V]


@pytest.mark.parametrize("name,texts", V)
def test_variant_caught(name, texts):
    assert T in leaks(texts, [T])


@pytest.mark.parametrize("text", negatives(T), ids=range(len(negatives(T))))
def test_negative_clean(text):
    assert not leaks([text], [T])
