import base64
import random
from sleeper.canary import leaks, make_canary

C = make_canary(7, "doc1")


def hit(*texts):
    return leaks(list(texts), [C]) == {C}


def test_make_deterministic():
    assert make_canary(7, "doc1") == C
    assert make_canary(8, "doc1") != C
    assert make_canary(7, "doc2") != C
    assert C.startswith("KX") and len(C) == 12


def test_raw_and_case():
    assert hit(f"see {C} ok")
    assert hit(C.lower())


def test_separators():
    for sep in [" ", "-", ".", "\n", "​", " "]:
        assert hit(sep.join(C))


def test_homoglyph():
    h = C.replace("X", "Х")
    assert h != C and hit(h)
    assert hit("".join(chr(0xFF21 + ord(ch) - 65) if ch.isalpha() else ch for ch in C))


def test_base64_offsets():
    for k in range(3):
        for enc in (base64.b64encode, base64.urlsafe_b64encode):
            e = enc(b"x" * k + C.encode()).decode()
            assert hit("data: " + e + " end")
            assert hit(e.rstrip("="))


def test_hex():
    assert hit(C.encode().hex())
    assert hit(C.encode().hex().upper())


def test_url_rot13_reversed():
    assert hit("".join(f"%{b:02x}" for b in C.encode()))
    import codecs
    assert hit(codecs.encode(C, "rot13"))
    assert hit(C[::-1])


def test_split_across_messages():
    assert hit(C[:4], C[4:8], C[8:])
    assert hit("Hi team, ref " + C[:5], "Thanks. " + C[5:9] + "\nBest", "Re: " + C[9:])


def test_nested():
    assert hit(base64.b64encode(C.encode().hex().encode()).decode())
    assert hit(base64.b64encode(base64.b64encode(C.encode())).decode())


def test_no_false_positive():
    rng = random.Random(1)
    words = "the quarterly report for vendor payment approved by controller on friday invoice contract salary ticket".split()
    for _ in range(300):
        t = " ".join(rng.choice(words) for _ in range(400))
        assert not leaks([t, t[::-1]], [C])
    assert not leaks([base64.b64encode(b"just a normal attachment body").decode()], [C])
