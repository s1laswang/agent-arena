import pytest

SLOW = {
    "test_staff_vs_all_strategies": 0, "test_fuzz_baselines_every_loss_labeled_no_win_labeled": 0,
    "test_trust_all_is_not_a_winning_strategy": 0, "test_chat_claim_changes_nothing": 0,
    "test_reward_implies_all_done": 0, "test_passk_shape_with_noise": 0, "test_no_false_positive": 0,
    "test_seat_mode_wins": 1, "test_seat_mode_zero": 2, "test_noop_seat_scores_zero_and_oracle_scores_one": 1,
    "test_baselines_score_zero": 1, "test_eval_extra_seat": 0, "test_gullible_zero_on_sleeper_days": 0,
    "test_losing_staff_days_are_all_labeled": 0, "test_decoys_done_by_oracle_and_scored": 0,
    "test_oracle_call_budget": 1, "test_jobs_identical": 0, "test_quarantine_only_then_work_fails_on_rule_alone": 0,
    "test_random_accuse_mostly_zero": 0, "test_trust_all_zero_on_sleeper_days": 0,
    "test_common_words_never_trigger": 0, "test_smoke_stub": 0, "test_ceo_board_notice_seeds": 0,
    "test_eval_strict": 0, "test_trust_all_zero_every_day": 1, "test_oracle_wins_winnable_days": 0,
    "test_oracle_labels_iff_loss": 0, "test_trivial_zero": 1, "test_oracle_seats_work_standalone": 0,
    "test_traps_on_no_sleeper_days_only_and_vibes_accuser_loses": 0,
    "test_no_false_positive_on_oracle_days": 0, "test_oracle_solves_every_ticket": 0,
    "test_noop_seat_fails_its_own_tickets": 0, "test_do_nothing_zero_every_seat": 0, "test_oracle_one": 0,
}


def pytest_collection_modifyitems(items):
    seen = {}
    for it in items:
        n = it.originalname
        if n in SLOW:
            seen[n] = seen.get(n, 0) + 1
            if seen[n] > SLOW[n]:
                it.add_marker(pytest.mark.slow)
