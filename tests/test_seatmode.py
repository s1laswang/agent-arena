from harbor.opencode.seatmode import new_session
from sleeper.scripted import NoopAgent, OracleAgent, make_team


def play(sess, agent):
    while not sess.over:
        agent.turn(sess.seat, {}, sess.tools(), sess.call)
    return sess.result().reward


import pytest


@pytest.mark.xfail(strict=False, reason="bootstrap day gives the controller no own ticket; 40-60 generator fixes")
def test_oracle_seat_wins():
    s = new_session(1, "controller", make_team(OracleAgent))
    assert play(s, OracleAgent()) == 1


def test_noop_seat_loses():
    s = new_session(1, "controller", make_team(OracleAgent))
    assert play(s, NoopAgent()) == 0
