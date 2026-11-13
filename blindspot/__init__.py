"""Blind Spot: one working day in a small company's finance back office.

Ivar's branch of the Junction 2026 AfterQuery "Break the Agent" project.

The agent under test plays the accounts-payable seat of a fictional company
(Kestrel Components Oy). Its ticket queue looks routine, but some tickets carry
hazards modelled on real, documented corporate failures: fat-finger amounts,
currency/unit mix-ups, duplicate invoices, spreadsheet totals that skip rows,
"we always skip that check" process drift, approvals given because everyone
assumed someone else checked, accidental leaks of confidential files, and
classic invoice/bank-detail fraud. Most hazards are honest mistakes or
structural gaps, not villains. See data/failures/ and docs/FAILURE-RESEARCH.md.

The reward reads only the final state of the company systems plus the
append-only action ledger (blindspot.verify).
"""

__version__ = "0.1.0"
