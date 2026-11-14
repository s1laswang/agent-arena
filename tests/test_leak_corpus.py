import pytest
from redteam.leak_variants import variants, negatives
from sleeper.canary import leaks, make_canary

T = make_canary(1, "doc1")
V = variants(T)
V = [pytest.param(n, t, id=n) for n, t in V]


@pytest.mark.parametrize("name,texts", V)
def test_variant_caught(name, texts):
    assert T in leaks(texts, [T])


@pytest.mark.parametrize("text", negatives(T), ids=range(len(negatives(T))))
def test_negative_clean(text):
    assert not leaks([text], [T])
