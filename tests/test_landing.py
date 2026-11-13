import pytest

from scripts.landing_table import play


@pytest.mark.parametrize("sid", ["fraud.bank_swap", "fraud.split_under_limit"])
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_fraud_lands_on_staff_not_oracle(sid, seed):
    assert play(seed, sid, "staff") == (1, 0)
    assert play(seed, sid, "oracle") == (0, 1)
