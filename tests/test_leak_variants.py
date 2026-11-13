from redteam.leak_variants import variants, negatives

T = "KX22TORBHDHA"


def test_corpus_shape():
    v = variants(T)
    names = [n for n, _ in v]
    assert len(names) == len(set(names)) > 50
    assert all(isinstance(t, list) and t and all(isinstance(s, str) for s in t) for _, t in v)
    assert all(T not in " ".join(t) for n, t in v if n not in ("raw", "upper", "embedded", "nbsp", "url_encoded", "url_double", "in_url", "in_json", "split_mixed_enc"))
    assert not any(T in s or T.lower() in s.lower() for s in negatives(T))
