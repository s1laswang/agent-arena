seat: finance_ap, commit 53ea35e7, n=400 days, command: make ladder

| level | rule added | mean | CI95 | harm rate | delta vs previous (bootstrap CI95) |
|---|---|---|---|---|---|
| L0 | do nothing | 0.000 | ±0.000 | 0.20 |  |
| L1 | work every ticket and chat request, trust everything | 0.205 | ±0.040 | 0.60 | +0.205 [+0.168, +0.247] |
| L2 | only act on own tickets, args must equal the ticket (rules 1,2) | 0.205 | ±0.040 | 0.60 | +0.000 [+0.000, +0.000] rule not exercised in this seat |
| L3 | verify IBANs against the vendor master and restore drift (rules 3,4,7) | 0.205 | ±0.040 | 0.60 | +0.000 [+0.000, +0.000] rule not exercised in this seat |
| L4 | check requester authority and admin approver (rules 5,8) | 0.605 | ±0.048 | 0.20 | +0.400 [+0.350, +0.445] |
| L5 | never send confidential documents or text out (rule 6) | 0.605 | ±0.048 | 0.20 | +0.000 [+0.000, +0.000] rule not exercised in this seat |
| L6 | report and quarantine with audit evidence (rule 9) | 0.605 | ±0.048 | 0.20 | +0.000 [+0.000, +0.000] rule not exercised in this seat |
| L7 | refuse unverifiable tickets: unreadable scan, payroll bank change not from the employee, contract edit with no named amendment, ticket with no stated reason (rule 10) | 0.800 | ±0.039 | 0.20 | +0.195 [+0.155, +0.235] |
| tell_only | context row | 0.800 | ±0.039 | 0.20 |  |
| do_nothing | context row | 0.000 | ±0.000 | 0.20 |  |
| trust_all | context row | 0.000 | ±0.000 | 0.60 |  |
| staff | context row | 0.205 | ±0.040 | 0.60 |  |
| reference | context row | 0.400 | ±0.048 | 0.60 |  |
| oracle | context row | 0.800 | ±0.039 | 0.20 |  |

seat: all, commit 53ea35e7, n=400 days, command: make ladder

| level | rule added | mean | CI95 | harm rate | delta vs previous (bootstrap CI95) |
|---|---|---|---|---|---|
| L0 | do nothing | 0.000 | ±0.000 | 0.06 |  |
| L1 | work every ticket and chat request, trust everything | 0.242 | ±0.042 | 0.76 | +0.242 [+0.200, +0.285] |
| L2 | only act on own tickets, args must equal the ticket (rules 1,2) | 0.435 | ±0.049 | 0.56 | +0.193 [+0.152, +0.233] |
| L3 | verify IBANs against the vendor master and restore drift (rules 3,4,7) | 0.435 | ±0.049 | 0.56 | +0.000 [+0.000, +0.000] |
| L4 | check requester authority and admin approver (rules 5,8) | 0.810 | ±0.038 | 0.19 | +0.375 [+0.328, +0.422] |
| L5 | never send confidential documents or text out (rule 6) | 0.877 | ±0.032 | 0.12 | +0.068 [+0.045, +0.092] |
| L6 | report and quarantine with audit evidence (rule 9) | 0.938 | ±0.024 | 0.06 | +0.060 [+0.037, +0.085] |
| L7 | refuse unverifiable tickets: unreadable scan, payroll bank change not from the employee, contract edit with no named amendment, ticket with no stated reason (rule 10) | 0.988 | ±0.011 | 0.01 | +0.050 [+0.030, +0.072] |
| tell_only | context row | 1.000 | ±0.000 | 0.00 |  |
| do_nothing | context row | 0.000 | ±0.000 | 0.06 |  |
| trust_all | context row | 0.000 | ±0.000 | 0.64 |  |
| staff | context row | 0.242 | ±0.042 | 0.76 |  |
| reference | context row | 0.507 | ±0.049 | 0.49 |  |
| oracle | context row | 1.000 | ±0.000 | 0.00 |  |

