from scripts.gemini_cache import SECRET

KEY = "AIza" + "B" * 35


def test_real_key_shapes_caught():
    assert SECRET.search('{"k": "%s"}' % KEY)
    assert SECRET.search("key=" + KEY + "\n")
    assert SECRET.search('{"x_goog_api_key": 1}')


def test_base64_blob_with_aiza_inside_not_flagged():
    assert not SECRET.search('"thought_signature": "Cq0Bx9' + "AIza" + "Qw" * 30 + '+/9=="')
