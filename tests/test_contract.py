from canary.rules import TIERS, JUDGE_SEEDS, DEV_SEEDS, TRAIN_SEEDS, HELDOUT_SEEDS
from canary.types import INVESTIGATIVE_TOOLS, EpisodeResult


def test_tiers_shape():
    assert set(TIERS) == {"easy", "medium", "hard"}
    for t in TIERS.values():
        assert 2 <= t.max_variants < t.n_employees, "unique-copy-per-person canary makes the task trivial"
        assert 0 < t.p_leak <= 1 and t.n_days > 0 and t.tool_call_cap > 0


def test_seed_sets_disjoint():
    sets = [set(DEV_SEEDS), set(JUDGE_SEEDS), set(TRAIN_SEEDS), set(HELDOUT_SEEDS)]
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            assert not sets[i] & sets[j]


def test_types_import():
    assert "accuse" not in INVESTIGATIVE_TOOLS
    assert "score" in EpisodeResult.__dataclass_fields__
