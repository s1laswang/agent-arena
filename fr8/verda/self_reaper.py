# Runs ON the Verda instance: delete THIS instance at the hard deadline (cost cap), independent of the laptop.
import os, time, datetime
env = dict(l.strip().split("=", 1) for l in open("/root/.verda_api") if "=" in l)
IID = "3bb74f5a-ae5f-492d-b805-daf2de7d9ebd"
DEADLINE = datetime.datetime.fromisoformat(os.environ.get("REAP_AT_UTC", "2026-11-15T01:23:00+00:00"))   # default 03:23 Helsinki
while datetime.datetime.now(datetime.timezone.utc) < DEADLINE:
    time.sleep(60)
from verda import VerdaClient as C
c = C(env["VERDA_CLIENT_ID"], env["VERDA_CLIENT_SECRET"])
print("self-reaper deleting", IID, datetime.datetime.now(datetime.timezone.utc).isoformat(), flush=True)
c.instances.action(IID, c.constants.instance_actions.DELETE)
