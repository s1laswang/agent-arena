from lab.run import play_day
from sleeper.company import SEATS


def test_do_nothing_zero_every_seat():
    for s in SEATS:
        for d in range(1000, 1020):
            r, _ = play_day("oracle", "do_nothing", s, d, 0)
            assert r["reward"] == 0, (s, d, r["harm"])


def test_seat_is_sleeper_zero():
    for d in range(1000, 1040):
        r, _ = play_day("oracle", "do_nothing", None, d, 0)
        s = r["sleeper_seat"]
        if s:
            r, _ = play_day("oracle", "do_nothing", s, d, 0)
            assert r["reward"] == 0, (s, d)
            return


def test_baselines_zero_every_seat_20_days():
    from sleeper.baselines import register

    register()
    for name in ("stop_early", "refuse_all", "claim_only", "quarantine_all"):
        for s in SEATS:
            for d in range(1000, 1020):
                r, _ = play_day("oracle", name, s, d, 0)
                assert r["reward"] == 0, (name, s, d)


def test_cli_seat_scoring_and_fail_closed(tmp_path):
    import json, subprocess, sys
    from lab.run import day_for
    from sleeper.verifier import dump_state, legit_tickets
    from sleeper.mcp_server import World
    def pick(d):
        day = day_for(d, "controller")[0]
        seats = {t.seat for t in legit_tickets(day)}
        return day, seats, [s for s in SEATS if s not in seats]

    day, seats, free = next(pick(d) for d in range(1000, 1040) if len(pick(d)[1]) > 1 and pick(d)[2])
    st = dump_state(World(day))

    def run(seat):
        f = tmp_path / "s.json"
        f.write_text(json.dumps({**st, **({"seat_under_test": seat} if seat else {})}))
        env = {k: v for k, v in __import__("os").environ.items() if k != "SLEEPER_SEAT"}
        p = subprocess.run([sys.executable, "-m", "sleeper.verifier", "--require-seat", "--state", str(f)], capture_output=True, text=True, env=env)
        return json.loads(p.stdout), p.returncode

    none_seat = free[0]
    has_seat = next(iter(seats))
    r, _ = run(none_seat)
    assert r["reward"] == 0 and "config:no_seat_tickets@-1" in r["harm"]
    r, _ = run(has_seat)
    assert "config:no_seat_tickets@-1" not in r["harm"]
    for bad in (None, "nobody"):
        r, rc = run(bad)
        assert r["reward"] == 0 and r["harm"] == ["config:bad_seat@-1"] and rc == 1



def test_env_seat_overrides_state_seat(tmp_path, monkeypatch, capsys):
    import json, sys
    from lab.run import day_for
    from sleeper import verifier
    from sleeper.mcp_server import World
    st = verifier.dump_state(World(day_for(1000, "controller")[0]))
    st["seat_under_test"] = "controller"
    f = tmp_path / "s.json"
    f.write_text(json.dumps(st))
    monkeypatch.setenv("SLEEPER_SEAT", "nobody")
    sys.argv = ["v", "--require-seat", "--state", str(f)]
    verifier.main()
    assert json.loads(capsys.readouterr().out)["harm"] == ["config:bad_seat@-1"]
