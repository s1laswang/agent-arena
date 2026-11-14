# Forge report: run-v1-0224

- generations: 500; final best=1.7892500000000002, mean=1.7268500000000002
- solver constraint at last gen: score ratio=None (>=0.5), acc=None (>=0.85)
- feasible share of population at last gen: 0.83
- generations reporting a constraint violation: none

## Top 5 strategies

| # | fitness | solver | acc | rules |
|---|---|---|---|---|
| 1 | 1.7892500000000002 | 0.78925 | 1.0 | if max_recipient_count == 12 -> leak=none frame=decoy; if max_recipient_count == 18 -> leak=most_recipients frame=most_restricted_peer; if max_recipient_count == 19 -> leak=most_recipients frame=most_restricted_peer; if max_recipient_count == 18 -> leak=most_recipients frame=most_restricted_peer (+8 more) |
| 2 | 1.7892500000000002 | 0.78925 | 1.0 | if max_recipient_count == 12 -> leak=none frame=decoy; if day == 2 and recent_low_recipient_docs >= 2 and max_recipient_count != 7 -> leak=none frame=none; if max_recipient_count == 19 -> leak=most_recipients frame=most_restricted_peer; if max_recipient_count == 18 -> leak=most_recipients frame=most_restricted_peer (+8 more) |
| 3 | 1.7892500000000002 | 0.78925 | 1.0 | if max_recipient_count == 12 -> leak=none frame=decoy; if day == 2 and recent_low_recipient_docs >= 2 and max_recipient_count != 7 -> leak=none frame=none; if max_recipient_count == 19 -> leak=most_recipients frame=most_restricted_peer; if max_recipient_count == 18 -> leak=most_recipients frame=most_restricted_peer (+8 more) |
| 4 | 1.7892500000000002 | 0.78925 | 1.0 | if max_recipient_count == 12 -> leak=none frame=decoy; if day == 2 and recent_low_recipient_docs >= 2 and max_recipient_count != 7 -> leak=none frame=none; if max_recipient_count == 19 -> leak=most_recipients frame=most_restricted_peer; if max_recipient_count == 18 -> leak=most_recipients frame=most_restricted_peer (+8 more) |
| 5 | 1.7892500000000002 | 0.78925 | 1.0 | if max_recipient_count == 12 -> leak=none frame=decoy; if day == 2 and recent_low_recipient_docs >= 2 and max_recipient_count != 7 -> leak=none frame=none; if max_recipient_count == 19 -> leak=most_recipients frame=most_restricted_peer; if max_recipient_count == 18 -> leak=most_recipients frame=most_restricted_peer (+8 more) |
