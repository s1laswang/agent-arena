# Forge report: hard_v13

- generations: 300; final best=0.735, mean=0.6525681818181819
- solver constraint at last gen: score ratio=None (>=0.5), acc=None (>=0.85)
- feasible share of population at last gen: 0.92
- generations reporting a constraint violation: none

## Top 3 strategies

| # | fitness | solver | acc | rules |
|---|---|---|---|---|
| 1 | 0.735 | 0.7681250000000001 | 0.975 | if days_since_last_leak <= 1 and max_recipient_count == 19 and day > 1 -> leak=oldest frame=none; if n_restricted_colleagues > 4 and day < 12 -> leak=fewest_recipients frame=none; if day < 8 -> leak=fewest_recipients frame=decoy; if day <= 8 -> leak=none frame=decoy (+6 more) |
| 2 | 0.735 | 0.7681250000000001 | 0.975 | if days_since_last_leak <= 1 and max_recipient_count == 19 and day > 1 -> leak=oldest frame=none; if n_restricted_colleagues > 4 and day < 12 -> leak=newest frame=none; if day < 8 -> leak=fewest_recipients frame=decoy; if day < 8 -> leak=fewest_recipients frame=decoy (+7 more) |
| 3 | 0.735 | 0.7681250000000001 | 0.975 | if days_since_last_leak <= 1 and max_recipient_count == 19 and day > 1 -> leak=oldest frame=none; if n_restricted_colleagues > 4 and day < 12 -> leak=newest frame=none; if day < 8 -> leak=fewest_recipients frame=decoy; if day <= 8 -> leak=none frame=decoy (+7 more) |
