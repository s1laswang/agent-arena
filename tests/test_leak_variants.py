from redteam.leak_variants import variants, negatives

T = "KX22TORBHDHA"


def test_corpus_shape():
    v = variants(T)
    names = [n for n, _ in v]
    assert len(names) == len(set(names)) > 50
    assert all(isinstance(t, list) and t and all(isinstance(s, str) for s in t) for _, t in v)
    assert sum(T not in ' '.join(t) for _, t in v) >= 40
    assert not any(T in s or T.lower() in s.lower() for s in negatives(T))
