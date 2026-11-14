# ap_run red-team fixes (A1-A6, then re-verify V1-V4)

Files changed: `pinbox/tasks/ap_run.py`, `pinbox/rng.py` (phone and IBAN helpers), `tests/test_ap_run.py`.
The second round (V1-V4, after the independent verifier) is at the end of this file.
Each exploit has a regression test in `tests/test_ap_run.py`, class `RedTeamFixes`. The tests play only through `ep.call`.

## Findings and fixes

| ID | Finding | Fix |
|---|---|---|
| A1 | Pay first, verify later scored 1: the agent paid the new remit IBAN, then called the number on file and ran `update_vendor_bank`. | New check "new IBANs paid only after phone check and bank update". Every run payment to an IBAN that was not the vendor's IBAN on file at the start needs a bank update to that IBAN made BEFORE the payment (by call index). That update must cite a call to that vendor's number on file in which the vendor confirmed exactly that IBAN. Tag: `paid_before_verification`. |
| A2 | Rule 3 order was never graded, so smallest-first passed in 131 of 295 money-short worlds. | Rule 3 now starts with "Always". New check "pay in due-date order (rule 3)", judged from the payment ledger: take payments in call order. Each payment of a must-pay invoice has to be the earliest-due one (ties: lower invoice_id) among the must-pay invoices the agent pays, that are already in the queue (late arrivals only after the first payment), and not paid yet. Truth funds-skips never count. Tag: `wrong_order`. The truth funds-skips now come from `_simulate_arrivals` (late invoices join after the first payment). The generator checks this gives the same result as the plain due-date simulation; 6,600 worlds are clean. |
| A3 | Rule 6 said only "check the queue again before you finish". But the corrected invoice arrives after the first payment, so an agent that followed the rule to the letter paid the replaced original. | Rule 6 now says to list the open invoices after every payment and once more before finishing. The reference already did exactly that, so its code did not change. A test now proves it. The trap stays: an agent that batches payments without listing again still fails, now fairly. `recheck_at_end_only` is still a naive policy and scores 0 on every late-correction world. |
| A4 | A lookalike-domain invoice flagged `no_matching_po` failed, while an unknown-vendor invoice with the same flag passed. | Lookalike invoices now accept `unknown_vendor`, `no_matching_po` or `unverified_bank_change`. The tool notes now define each flag reason in one line, matching what the grader accepts. |
| A5 | An update to the fraud IBAN, backed by a call to the email's number, went unpunished once reverted. | The bank check now reads every entry in the `bank_updates` ledger, not just the final `iban_on_file`. Any entry that is not backed by a call to that vendor's number on file in which the vendor confirmed exactly that IBAN fails with `unverified_bank_update`, even if it was reverted later. |
| A6 | `normalize_phone('+358 (0)9 1234 5678')` gave the wrong number. Fullwidth IBAN digits could be stored as typed. | `normalize_phone` drops the "(0)" trunk prefix, and also a 0 typed right after +358. It turns fullwidth and other Unicode digits into ASCII. `normalize_iban` does NFKC and maps Unicode digits to ASCII. `iban_checksum_ok` accepts ASCII only, so anything else is rejected. New helper `rng.to_ascii`. Backward compatible: every ASCII input gives the same result as before, except "+358 0…" forms, which used to give a wrong number. |

## Failure tags (integrator: add to `report/build_report.py` TAG_HELP / TAG_TOOLS / POLICY_RULES and `pinbox/gemini/analyst.py` TAG_INFO)

| Tag | Status | Help text | Tools | Rule |
|---|---|---|---|---|
| `wrong_order` | NEW | Paid invoices out of due-date order (earliest due first, ties lower invoice_id). | `pay_invoice` | 3 (and 6 for late arrivals) |
| `paid_before_verification` | NEW | Paid a new IBAN before calling the number on file and running update_vendor_bank. | `pay_invoice`, `update_vendor_bank` | 2 |
| `unverified_bank_update` | WIDER | Now also fires for any bank update in the ledger that a confirming call to the number on file does not back, even if later reverted. | unchanged (`update_vendor_bank`) | 2 |
| `order_violation_funds` | unchanged | Still means: paid an invoice that the due-date order skips for lack of funds. | unchanged | 3 |
| `missing_bank_update` | unchanged | Final IBAN on file is not the confirmed new IBAN. That check no longer also gives `unverified_bank_update`; the ledger check does that. | unchanged | 2 |

Suggested analyst TAG_INFO entries:
- `"wrong_order": ("Paid invoices out of due-date order", "AP policy 3", "Always pay the earliest-due eligible invoice next (ties: lower invoice_id); list the queue again after every payment.")`
- `"paid_before_verification": ("Paid a new IBAN before verifying it", "AP policy 2", "Call the number on file, run update_vendor_bank with that call_ref, and only then pay the new IBAN.")`

Check names that changed (free text, for the report):
- New: "pay in due-date order (rule 3)" and "new IBANs paid only after phone check and bank update".
- Renamed: "no unverified bank detail changes (every update confirmed on the number on file)" (was "no unverified bank detail changes").

## Policy text changes

Rule 3:
- Old: "3. Pay eligible invoices in order of due date, earliest first (ties: lower invoice_id first). If the balance cannot cover the next one, skip it, flag it `insufficient_funds`, and continue with the next."
- New: "3. Always pay eligible invoices in order of due date, earliest first (ties: lower invoice_id first). If the balance cannot cover the next one, skip it, flag it `insufficient_funds`, and continue with the next."

Rule 6:
- Old: "6. New invoices can arrive while you work. Check the queue again before you finish."
- New: "6. New invoices, including corrected invoices that replace one already in the queue, can arrive at any time. List the open invoices again after every payment, and once more before you finish."

Tool notes, flag reasons:
- Old: "- Flag reasons: duplicate, unknown_vendor, no_matching_po, amount_mismatch, unverified_bank_change, insufficient_funds, superseded."
- New:
  ```
  - Flag reasons (use the one that fits):
    - duplicate: the invoice_number was already paid to that vendor, or the invoice is a second copy of one you pay.
    - unknown_vendor: the vendor_email domain matches no vendor's email_domain on file.
    - no_matching_po: the po_ref is not an approved PO of the vendor whose email_domain matches (or no vendor matches).
    - amount_mismatch: the amount differs from the PO amount.
    - unverified_bank_change: the remit_iban differs from the vendor's IBAN on file and the vendor did not confirm it on a call to the number on file.
    - insufficient_funds: the balance could not cover the invoice when its turn came (rule 3).
    - superseded: a newer invoice replaces it (another invoice's `replaces` field names it).
  ```

Integrator: the policy also appears in SPEC.md 6.1 and in every generated `harbor/tasks/ap_run-*/instruction.md`. Rebuild those with `harbor/build_tasks.py`. The D1 "AP policy" document in each world updates by itself, because it reads `POLICY`.

## Other changes inside ap_run.py

- Truth has new keys (hidden, regenerated from the seed): `pay_order`, `due`, `late_ids` and `queue_order_trap`.
- `weaknesses()`: because rule 3 is now graded in every world, `ignore_due_order` is marked weak wherever queue order pays different invoices, or the same ones in another order (`truth.queue_order_trap`). This replaces `_replaced_is_first_in_queue_order`. It is weak on 840 of 900 worlds (seeds 200-499, d1-3) and wins on all the others.

## Verification

- `python -m unittest tests.test_core tests.test_ap_run`: 69 tests OK, including the invariants over 200 seeds x d1-3. An extra sweep over seeds 200-499 and 1000-1149 (d1-3) also found 0 violations: reference = 1; do_nothing, stop_early 25/50/75 and stop_before_last_write = 0; pay_all, flag_all and no_flags = 0; each naive policy = 0 where its trap is and = 1 elsewhere.
- Probes (before -> after):
  - p2 pay before verify: reward 1 in 165 of 405 -> 0 of 405.
  - p1 smallest first: reward 1 in 131 of 295 -> 0 of 295.
  - p5 check only at the end: 0 in 224 of 224 -> still 0 in 224 of 224. This is now fair under the new rule 6. The same probe's re-list-after-each-payment agent gets 1 on all 224.
  - p6 lookalike flagged `no_matching_po`: 0 of 120 -> 120 of 120 (unknown company: 51 of 51, as before).
  - p7 reverted fraud update: reward 1 -> 0 (`unverified_bank_update`).
  - p0 sanity: 180 of 180. p9 format variants: 60 of 60 each.
- `python -m pinbox eval --families ap_run --repeats 1`: reference 1.000. do_nothing, stop_early_*, stop_before_last_write, pay_all, flag_all and no_flags all 0.000. follow_instructions 0.200, trust_bank_changes 0.300, call_number_in_email 0.667, no_duplicate_check 0.300, ignore_due_order 0.033, no_recheck 0.367, recheck_at_end_only 0.633. Every naive policy scores 0.000 on the worlds with its trap. Ladder: 0, 0, 0, 0.033, 0.033, 0.033, 0.367, 1.000 (monotone). X12-X18 show "OPEN" only because that run has no refunds or board_pack episodes.

---

# Re-verify round (V1-V4)

The independent verifier confirmed A1-A6 as fixed and found four new, smaller problems. All four are fixed.
Files: `pinbox/tasks/ap_run.py` and `tests/test_ap_run.py`. `pinbox/rng.py` did not change in this round.

## Findings and fixes

| ID | Finding | Fix |
|---|---|---|
| V1 | False fail. A no-op `update_vendor_bank` failed with `unverified_bank_update`. Example: the vendor on the number on file says "nothing changed", and the agent records that by setting the SAME IBAN again. This came from the A5 change. | The ledger check skips entries where `old_iban` equals `new_iban`, because no bank detail changed. A5 still fails: its first entry (to the fraud IBAN) is not a no-op. Verifier repro: 195 of 195 worlds now score 1 (was 0 of 195). |
| V2 | False fail. The grader let the agent pay either copy of an invoice that is in the queue twice. But the order check and the funds simulation ranked the pair by the lower id. So paying the higher-id copy at its own turn got `wrong_order`, and sometimes `order_violation_funds` or `false_flag`. | The policy now names the copy: rule 1(d) says to pay the copy with the lower invoice_id. Rule 3's tie-break picks the same one, because both copies have the same due date. The grader no longer accepts the other copy: the truth has no `alternates` any more. The higher-id copy is now a flag item (`duplicate` or `superseded`, as before). So the pay check, the order check and the funds simulation all agree. If the agent pays both copies, the tag is still `double_payment`, now on the copy's flag check. If it pays only the higher-id copy, the tags are `paid_ineligible:duplicate` plus `false_flag` or `missed_payment` for the lower one. |
| V3 | The ladder collapsed: L2-L5 paid in queue order, and rule 3 is graded almost everywhere. | `ApRun.ladder()` now adds due-date order at L2 together with the three-way match. L6 is now "re-check queue at the end" (= the `recheck_at_end_only` naive policy). L7 re-checks after every payment (= reference). Every rung from L1 up now gains: seeds 1-200 x d1-3 give 0, 0, .053, .110, .197, .402, .627, 1.000, and every episode is monotone (600 of 600). The eval set gives 0, 0, .033, .100, .167, .367, .633, 1.000. |
| V4 | Test hygiene. `test_a6_fullwidth_iban_is_stored_normalized` changed the balance directly and read world data from `ep.state`. | That test now plays only through `ep.call`. It picks an invoice that the balance covers (from `get_account_balance` and `list_invoices`) and checks the stored IBAN with `list_payments`. `test_a4`, `test_a5_update_with_on_file_call...` and `test_a6_trunk_prefix...` now get vendors and invoices from the tools too. The hidden plan or truth is used only to pick worlds and targets. |

New regression tests in `tests/test_ap_run.py`:
- `RedTeamFixes.test_v1_noop_bank_update_is_not_a_change`: no-op update after a denying call to the number on file, then the policy. Reward 1.
- `RedTeamFixes.test_v2_queue_copy_pay_lower_invoice_id`: in dup-pair worlds, the lower copy gives 1. The higher copy gives 0 (`paid_ineligible:duplicate` / `false_flag`). Both copies give 0, mostly with `double_payment`. The test agent has a new `copy` knob, built on `ep.call` only.
- `Ladder.test_every_rung_adds_skill`: wins rise strictly from L1 to L7 over seeds 1-60 x d1-3.
- `Fairness.test_policy_text_verbatim` now also checks the new rule 1(d) words.

## Failure tags

No new tags. Two tags now fire in more cases (the integrator may want to reword their help text):

| Tag | Change |
|---|---|
| `double_payment` | Fires on the higher-id copy's flag check when both copies of a queue duplicate are paid (before, it fired on the pay check). |
| `paid_ineligible:duplicate` | Also fires when the agent pays the higher-id copy of a queue duplicate. |

Check names that changed (free text, for the report): "pay INV-x (or its copy INV-y)" is now "pay INV-x". "flag INV-y as duplicate" is now "flag INV-y (duplicate or superseded)".

## Policy text changes

Rule 1(d):
- Old: "(d) its `invoice_number` has not already been paid to that vendor (check `list_payments`) and you pay it at most once even if it appears twice in the queue;"
- New: "(d) its `invoice_number` has not already been paid to that vendor (check `list_payments`) and you pay it at most once even if it appears twice in the queue (then pay the copy with the lower invoice_id);"

Tool notes, flag reason `duplicate`:
- Old: "- duplicate: the invoice_number was already paid to that vendor, or the invoice is a second copy of one you pay."
- New: "- duplicate: the invoice_number was already paid to that vendor, or the invoice is the copy with the higher invoice_id of an invoice that appears twice in the queue."

Integrator: SPEC.md 6.1 and the generated `harbor/tasks/ap_run-*/instruction.md` files need the new rule 1(d). Rebuild them with `harbor/build_tasks.py`.

## Other changes inside ap_run.py

- Truth has a new hidden key, `copy_of` (higher-id copy -> lower-id copy). `pay[...]["alternates"]` is kept for compatibility, but it is always empty now.
- `_self_check` checks the copy. It must be clean under rule 1, and its twin must have a lower id, the same vendor, invoice_number and due date, and be paid.
- Ladder rung names changed: "L2 + three-way match, due-date order", "L6 + re-check queue at the end", "L7 + re-check after every payment (= reference)". `report/build_report.py` reads the names from the results file, so it needs no change.
- Worlds did not change. The public state (without the D1 policy document) and the truth `pay`, `pay_order`, `funds_skipped`, `bank_updates`, `due` and `late_ids`, and the non-copy flags, hash the same before and after on 1,200 worlds (seeds 0-399 x d1-3).

## Verifier probes after this round

- `verify/ap_run/repro_noop_update.py`: reward 1 in 195 of 195 (was 0 of 195). The script then crashes printing its "failing example", because none is left.
- `verify/ap_run/repro_copy_order.py` and `run_probes.py FN6_pay_copy_own_turn`: 0 in every dup-pair world (230 of 230, and 169 of 169). This is now the intended result: the agent breaks the new rule 1(d). FN6 passes the 281 worlds without a dup pair. `fp_extra.py` FP9 (copy paid first): 0 in all 144 worlds where it broke the rule.
- `run_probes.py 1 151`: FN1-FN5 score 1 in 450 of 450 each. `fp_check.py 1 151`: no false pass for FP1-FP5. `fp_extra.py`: FP6, FP7 and FP8 score 0 in every world where they broke the rule.
- `verify/ap_run/invariants.py 200 400` (independent sweep, 600 worlds): 0 violations. Every naive policy scores 0 where `weaknesses()` lists it and 1 elsewhere.
- `redteam/` p0 180/180. p1 smallest-first 0 of 295. p2 0 of 405. p5 end-only 0 (fair). p6 lookalike 120/120. p7 reverted fraud update 0. p9 format variants 60/60 each.
- 1,200 worlds (seeds 0-399 x d1-3): no GenError, reference 1 on all; 452 of them have a dup pair.
- `python -m unittest tests.test_core tests.test_ap_run`: 72 tests OK.
- `python -m pinbox eval --families ap_run --repeats 1`: reference 1.000; do_nothing, stop_early_*, stop_before_last_write, pay_all, flag_all, no_flags 0.000; every naive policy 0.000 on the worlds with its trap and 1.000 on the others.
