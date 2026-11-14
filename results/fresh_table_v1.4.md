# Paired table: seeds 5000-5799, V mode = known, tiers v1.4

Confirmation seeds. They were not used for tuning: the cell was picked on dev seeds 4000–4599, see CONTRACT §14. n = 800 per tier. Easy and medium are unchanged from v1.3; only hard changed. Reproduce with `uv run --python 3.12 python scripts/paired_table.py --seeds 5000:5800 --agents grok_tactics,heuristic,obvious_heuristic,logs_only,logs_minus_decoy,accuse_most_logs,accuse_decoy,restrict_all,probe_all,random,guess_day1,stop_early,do_nothing`. For v1.3 on the same seeds, add `--tiers-version v1.3`. Hard v1.3 is solver .575, grok_tactics .342, paired gap −.233 ± .040.

`stop_early` scores 0 (no accusation). `guess_day1` is the day-1 random accusation.

Diff = agent − solver on the same seed (paired 95% CI). Acc = correct accusations; no-acc = episodes without an accusation.

| tier | agent | mean score | ±95% | diff vs solver (paired) | acc | no-acc | mean accusation day |
|---|---|---|---|---|---|---|---|
| easy | solver | 0.779 | 0.009 | — | 99.6% | 0.2% | 5.0 |
| easy | grok_tactics | 0.690 | 0.013 | -0.089 ± 0.016 | 97.5% | 2.5% | 6.0 |
| easy | heuristic | 0.648 | 0.019 | -0.131 ± 0.020 | 97.9% | 0.0% | 6.9 |
| easy | obvious_heuristic | -0.408 | 0.059 | -1.187 ± 0.059 | 32.8% | 0.0% | 5.2 |
| easy | logs_only | -0.552 | 0.050 | -1.331 ± 0.051 | 27.8% | 0.0% | 10.0 |
| easy | logs_minus_decoy | -0.576 | 0.053 | -1.355 ± 0.054 | 23.8% | 0.0% | 6.0 |
| easy | accuse_most_logs | -0.594 | 0.052 | -1.373 ± 0.053 | 22.8% | 0.0% | 6.0 |
| easy | accuse_decoy | -0.841 | 0.036 | -1.620 ± 0.038 | 8.5% | 0.0% | 4.0 |
| easy | restrict_all | -0.741 | 0.037 | -1.520 ± 0.038 | 19.4% | 0.0% | 6.0 |
| easy | probe_all | 0.000 | 0.000 | -0.779 ± 0.009 | 0.0% | 100.0% | — |
| easy | random | -0.617 | 0.039 | -1.396 ± 0.040 | 6.8% | 27.0% | 6.0 |
| easy | guess_day1 | -0.830 | 0.039 | -1.609 ± 0.040 | 8.5% | 0.0% | 1.0 |
| easy | stop_early | 0.000 | 0.000 | -0.779 ± 0.009 | 0.0% | 100.0% | — |
| easy | do_nothing | 0.000 | 0.000 | -0.779 ± 0.009 | 0.0% | 100.0% | — |
| medium | solver | 0.634 | 0.017 | — | 89.0% | 11.0% | 8.1 |
| medium | grok_tactics | 0.459 | 0.021 | -0.176 ± 0.025 | 76.2% | 23.2% | 8.7 |
| medium | heuristic | -0.007 | 0.054 | -0.641 ± 0.056 | 61.8% | 0.0% | 11.2 |
| medium | obvious_heuristic | -0.921 | 0.025 | -1.556 ± 0.030 | 4.6% | 0.0% | 11.0 |
| medium | logs_only | -0.976 | 0.014 | -1.610 ± 0.022 | 1.4% | 0.0% | 10.0 |
| medium | logs_minus_decoy | -0.963 | 0.018 | -1.597 ± 0.024 | 2.0% | 0.0% | 6.0 |
| medium | accuse_most_logs | -0.968 | 0.017 | -1.602 ± 0.024 | 1.8% | 0.0% | 6.0 |
| medium | accuse_decoy | -0.906 | 0.029 | -1.541 ± 0.033 | 4.9% | 0.0% | 4.0 |
| medium | restrict_all | -0.948 | 0.015 | -1.582 ± 0.023 | 5.2% | 0.0% | 7.0 |
| medium | probe_all | 0.000 | 0.000 | -0.634 ± 0.017 | 0.0% | 100.0% | — |
| medium | random | -0.659 | 0.036 | -1.294 ± 0.041 | 3.8% | 27.5% | 6.0 |
| medium | guess_day1 | -0.902 | 0.030 | -1.537 ± 0.034 | 4.9% | 0.0% | 1.0 |
| medium | stop_early | 0.000 | 0.000 | -0.634 ± 0.017 | 0.0% | 100.0% | — |
| medium | do_nothing | 0.000 | 0.000 | -0.634 ± 0.017 | 0.0% | 100.0% | — |
| hard | solver | 0.556 | 0.024 | — | 94.9% | 1.2% | 8.8 |
| hard | grok_tactics | 0.362 | 0.026 | -0.195 ± 0.033 | 84.2% | 12.0% | 10.2 |
| hard | heuristic | 0.023 | 0.040 | -0.534 ± 0.046 | 77.1% | 0.0% | 15.2 |
| hard | obvious_heuristic | -0.987 | 0.010 | -1.544 ± 0.026 | 0.8% | 0.0% | 11.0 |
| hard | logs_only | -0.977 | 0.014 | -1.533 ± 0.028 | 1.4% | 0.0% | 10.0 |
| hard | logs_minus_decoy | -0.931 | 0.024 | -1.487 ± 0.035 | 3.8% | 0.0% | 6.0 |
| hard | accuse_most_logs | -0.924 | 0.026 | -1.480 ± 0.035 | 4.1% | 0.0% | 6.0 |
| hard | accuse_decoy | -0.947 | 0.022 | -1.504 ± 0.033 | 2.8% | 0.0% | 4.0 |
| hard | restrict_all | -0.994 | 0.005 | -1.550 ± 0.025 | 0.6% | 0.0% | 9.0 |
| hard | probe_all | 0.000 | 0.000 | -0.556 ± 0.024 | 0.0% | 100.0% | — |
| hard | random | -0.798 | 0.031 | -1.354 ± 0.039 | 2.8% | 15.6% | 7.8 |
| hard | guess_day1 | -0.945 | 0.023 | -1.501 ± 0.034 | 2.8% | 0.0% | 1.0 |
| hard | stop_early | 0.000 | 0.000 | -0.556 ± 0.024 | 0.0% | 100.0% | — |
| hard | do_nothing | 0.000 | 0.000 | -0.556 ± 0.024 | 0.0% | 100.0% | — |
