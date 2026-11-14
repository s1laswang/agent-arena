from harbor.opencode.instruction import SEATS, seat_instruction
from sleeper.company import tools_for


def test_every_seat():
    for seat in SEATS:
        t = seat_instruction(seat)
        assert "Payments over 10000 EUR need controller approval" in t
        assert "Verify the IBAN by call-back" in t
        assert "reward is 1 only if" in t and "end_turn" in t
        for tool in tools_for(seat):
            assert tool["name"] in t
        assert "the sleeper is" not in t.lower() and "is the sleeper" not in t.lower()
