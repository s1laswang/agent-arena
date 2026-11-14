def test_replay_demo_byte_identical():
    from scripts import replay_demo
    assert replay_demo.main() == 0
