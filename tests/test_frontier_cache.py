import tarfile

import pytest

from lab import frontier_cache as fc


def test_export_only_used_and_refuses_secrets(tmp_path):
    cache = tmp_path / "c"
    cache.mkdir()
    (cache / "a.json").write_text("{}")
    (cache / "b.json").write_text("{}")
    out = fc.export(tmp_path, "finance_ap-s1-t0", {"a", "missing"}, cache)
    assert out.name == "cache-s1-t0.tar.gz"
    assert tarfile.open(out).getnames() == ["a.json"]
    (cache / "a.json").write_text('{"api_key": "x"}')
    with pytest.raises(SystemExit):
        fc.export(tmp_path, "finance_ap-s1-t0", {"a"}, cache)
