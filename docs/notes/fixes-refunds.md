# Red-team fixes: refunds family

Files changed: `pinbox/tasks/refunds.py`, `tests/test_refunds.py`. Nothing else.

## R1 (high): two tickets for the same item

**Problem.** Rule 8 says close a ticket `refunded` "if you refunded at least one of its items". For two
tickets about the same item, the agent refunds the item once, so read literally BOTH tickets are
`refunded`. The grader only accepted one `refunded` and one `denied`, so the literal reading scored 0
(seed 1 d3 TCK-1963/TCK-1967, seed 3 d2 TCK-4347/TCK-4351).

**Fix.** The duplicate-group check now accepts `["denied", "refunded"]` and `["refunded", "refunded"]`.
At least one ticket must say `refunded` (`["denied", "denied"]` still fails with `wrong_resolution`).
"Refunded exactly once" is enforced by the per-order refund check (`double_refund` / `missed_refund`),
so a second refund still scores 0. The check is renamed from "same request in A and B refunded once"
to "same request in A and B closed as refunded at least once".

**Policy text.** Not changed. Both fair readings now pass, so no extra words are needed.

## R2 (low): refunds were graded only by the order total

**Problem.** The same item could be refunded in two calls (33.99 + 0.01), or money could be moved
between items of one order (item A gets 62.99, item B gets 0.01), and still score 1 because only the
set of skus and the order total were checked.

**Fix.** Refunds are now graded per call:
- a sku may appear in at most one successful `issue_refund` call per order, else `double_refund`
  (or `refunded_shipping` when the extra call adds exactly the shipping fee to an otherwise right refund);
- each call's amount must equal the refund due for exactly the skus listed in that call, else
  `wrong_refund_amount` (or `refunded_shipping` when the call is off by exactly the shipping fee).
One call for several items, or one call per item, both still pass when every amount is exact.
The check name now lists the due amount per sku, e.g. `refund order ORD-1: NB-MUG-01 = 14.90 EUR`.

**Tool note text (in the instruction).**
- Old: "You may refund several items of the same order in one call, or make one call per item; the total
  per order is what counts."
- New: "You may refund several items of the same order in one call, or make one call per item. Each
  call's amount must be exactly the refund due for the items listed in that call."

**Tool description.** `issue_refund` parameter `amount`:
- Old: "Total amount in EUR for these items, at most 2 decimals"
- New: "The refund due for exactly these items, in EUR, at most 2 decimals"

## Failure tags

No new or renamed tags. The fixes reuse `double_refund`, `wrong_refund_amount`, `refunded_shipping`
and `wrong_resolution`, which `report/build_report.py` and `pinbox/gemini/analyst.py` already know.

## For the integrator

- `docs/DESIGN.md` line 117-118 is now wrong: "A refund may be split over several calls if the
  per-order total is exact." Suggested: "Several items may share one refund call or have one call
  each, but each call's amount must be exactly the refund due for its items, and each item is
  refunded in one call only. Two tickets for the same item may be closed `refunded`/`denied` or
  `refunded`/`refunded`."
- `docs/EXPLOITS.md`: add the two R2 exploits (split one item over two calls; move money between items)
  as blocked, tests `test_refunds.RedTeamFixes`.
- `harbor/tasks/refunds-*/instruction.md` hold the old tool note. Rebuild them with
  `harbor/build_tasks.py`.

## Tests

New class `RedTeamFixes` in `tests/test_refunds.py` (plays only through `ep.call`):
- both duplicate tickets `refunded` passes (seed 1 d3, seed 3 d2); both `denied` fails; refunding twice fails;
- same item split over two calls fails with `double_refund`;
- money moved between items fails with `wrong_refund_amount`;
- one exact call per item passes; adding shipping to one of those calls fails with `refunded_shipping`;
- the instruction no longer says "the total per order is what counts".

- the earlier duplicate ticket `denied` and the later one `refunded` (a fair newest-first order) passes;
  both closed `refunded` without paying the item fails with `missed_refund`
  (`test_dup_tickets_any_order_but_item_must_be_paid`, added after the verifier pass).

The old test `test_split_refund_of_one_item_is_fine` is now `test_split_refund_of_one_item_is_double_refund`.

Results: `python -m unittest tests.test_core tests.test_refunds`: 75 tests OK (200 seeds x d1-3
invariants included). Probe p8 over 600 worlds: split-item exploit scores 1 in 0 of 596 worlds where it
applies (all `double_refund`); moved-money exploit 1 in 0 of 230 (all `wrong_refund_amount`).
`python -m pinbox eval --families refunds`: reference 1.000; do_nothing, stop_early 25/50/75,
stop_before_last_write, refund_all, deny_all 0.000; every one-rule-removed policy 0.000 on worlds with
its trap and 1.000 on the others.

## Verifier pass 2

The verifier marked R1 and R2 fixed. No change to `pinbox/tasks/refunds.py` was needed.

- **Stale build outputs (low).** `harbor/tasks/refunds-s{1..8}-d{1,2,3}/instruction.md` still hold the old
  tool note, and their `pinbox.zip` files hold the old grader. `docs/DESIGN.md` line 117 still says a refund
  may be split over calls. These files are not owned by this family, so they are left for the integrator:
  rebuild with `harbor/build_tasks.py` and apply the DESIGN.md sentence above.
- **Side note: "earlier ticket denied, later ticket refunded" passes.** This is right, not a gap. Tickets may
  be handled in any order. An agent that goes newest first refunds the item on the later ticket and then
  denies the earlier one under rule 5. The item is still refunded exactly once. New test:
  `test_dup_tickets_any_order_but_item_must_be_paid`.
- **Verifier probe FP4 reports 224 "unexpected" wins.** These are all worlds with no duplicate tickets, where
  the probe acts like the normal policy agent. In all 76 worlds where it finds duplicate tickets it scores 0
  (`missed_refund`). Checked over seeds 0-99 x d1-3.

No new tags and no policy text changes in this pass.

Re-run results:
- `python -m unittest tests.test_core tests.test_refunds`: 76 tests OK.
- Verifier `invariants.py 200`: reference 600/600; do_nothing, stop_early 25/50/75, stop_before_last_write,
  refund_all, deny_all 0/600; every one-rule-removed policy 0 mismatches. "ALL OK".
- Verifier `probes.py` / `run_rest.py`: FN1-FN8 300/300; FP1-FP3 0/300; split_item 0/300 (`double_refund`),
  move_cent 0/118 (`wrong_refund_amount`), merge_extra 0/300, shipping_call 0/300 (`refunded_shipping`).
- Verifier `dup_probe.py`: both refunded 258/258, refunded+denied 258/258 (either order); both denied,
  refund twice, never pay, one pending, one identity each 0/258.
- Verifier `wide.py`: 1200/1200 for each of the three wide careful agents.
- Red-team `p8_refunds_per_item.py`: part (b) finds no world to exploit. `fair/variant.py` for seed 1 d3
  TCK-1967 and seed 3 d2 TCK-4351 closed `refunded`: reward 1.
- `python -m pinbox eval --families refunds`: reference 1.000; every shortcut 0.000; X12, X13, X17 blocked.
