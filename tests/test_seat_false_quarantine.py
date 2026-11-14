from scripts import seat_fq


def test_oracle_seat_not_quarantined_by_procedure_background():
    assert seat_fq.main(range(1000, 1008)) == 0
