

def pytest_collection_modifyitems(config, items):
    import pathlib
    import pytest

    slow = set(pathlib.Path(__file__).with_name("slow.txt").read_text().split())
    for it in items:
        if it.nodeid.split("[")[0] in slow:
            it.add_marker(pytest.mark.slow)
