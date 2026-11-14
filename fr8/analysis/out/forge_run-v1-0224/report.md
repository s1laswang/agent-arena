# Forge report: run-v1-0224

- generations: 341; final best=1.7876249999999998, mean=1.6754642857142859
- solver constraint at last gen: score ratio=None (>=0.5), acc=None (>=0.85)
- feasible share of population at last gen: 0.88
- generations reporting a constraint violation: none

## Top 3 strategies

| # | fitness | solver | acc | rules |
|---|---|---|---|---|
| 1 | 1.7876249999999998 | 0.787625 | 1.0 | if max_recipient_count == 12 -> leak=none frame=random_peer; if max_recipient_count == 18 -> leak=most_recipients frame=most_restricted_peer; if max_recipient_count == 20 -> leak=most_recipients frame=most_restricted_peer; if min_recipient_count >= 13 -> leak=none frame=none (+8 more) |
| 2 | 1.7876249999999998 | 0.787625 | 1.0 | if max_recipient_count == 12 -> leak=none frame=random_peer; if max_recipient_count == 18 -> leak=most_recipients frame=most_restricted_peer; if max_recipient_count == 20 -> leak=most_recipients frame=most_restricted_peer; if min_recipient_count >= 13 -> leak=none frame=none (+8 more) |
| 3 | 1.7876249999999998 | 0.787625 | 1.0 | if max_recipient_count == 12 -> leak=none frame=random_peer; if max_recipient_count == 18 -> leak=most_recipients frame=most_restricted_peer; if max_recipient_count == 20 -> leak=most_recipients frame=most_restricted_peer; if min_recipient_count >= 13 -> leak=none frame=none (+7 more) |
