"""Does the day data carry a surface tell that separates fraud from legit WITHOUT any ground-truth flag?
Scan many days: legit pay amounts vs attacker pay amounts; legit IBANs vs attacker IBANs.
This uses day.tickets[*].legit and the goal only to LABEL for the report; the TELL itself (round amount,
non-FI iban) is visible to the agent in ticket params / events / list_vendors."""
import os
import sys

os.environ.setdefault("GEMINI_API_KEY", "")
from harbor.sidecar import make_world_and_team

salt = "a3f1c0ffee5a1t00000000000000beef"
seats = sys.argv[1].split(",")
start, n = int(sys.argv[2]), int(sys.argv[3])

legit_amt_int = legit_amt_total = atk_amt_int = atk_amt_total = 0
atk_amts = set()
legit_iban_fi = legit_iban_total = atk_iban_fi = atk_iban_total = 0
atk_iban_pref = set()

for seat in seats:
    for seed in range(start, start + n):
        _, world, _ = make_world_and_team(seed, seat, salt=salt)
        day = world.day
        for t in day.tickets:
            for k in ("amount",):
                if "amount" in t.params:
                    a = float(t.params["amount"])
                    if t.legit:
                        legit_amt_total += 1
                        legit_amt_int += a.is_integer()
                    else:
                        atk_amt_total += 1
                        atk_amt_int += a.is_integer()
                        atk_amts.add(a)
            # ibans in ticket params
            ib = t.params.get("iban") or (t.params.get("value") if t.params.get("field") == "iban" else None)
            if isinstance(ib, str) and len(ib) >= 2:
                if t.legit:
                    legit_iban_total += 1
                    legit_iban_fi += ib.startswith("FI")
                else:
                    atk_iban_total += 1
                    atk_iban_fi += ib.startswith("FI")
                    atk_iban_pref.add(ib[:2])
        # attacker ibans also surface in events (invoice scans, chat) and list_vendors; sample event bodies
print("PAYMENT AMOUNTS")
print(f"  legit: {legit_amt_int}/{legit_amt_total} are whole numbers")
print(f"  attack: {atk_amt_int}/{atk_amt_total} are whole numbers; distinct attack amounts: {sorted(atk_amts)[:12]}")
print("IBANs in ticket params")
print(f"  legit: {legit_iban_fi}/{legit_iban_total} start 'FI'")
print(f"  attack: {atk_iban_fi}/{atk_iban_total} start 'FI'; attack prefixes seen: {sorted(atk_iban_pref)}")
