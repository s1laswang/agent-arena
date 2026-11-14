# Shared-verifier test.sh: direct Docker reproduction (EXPLOITS #42)

Harbor 0.25 on our Docker Desktop / Windows host does not run test.sh at all in shared mode (see EXPLOITS #42). That is why `build.py --verifier shared` now refuses unless you pass `--unsafe-shared-not-for-judging`. This log checks the shared-mode branch of `harbor/template/tests/test.sh` directly, in the agent image (`main`), Sat 14 Nov ~20:35, with this branch's code.

**Setup** (each step is something a hostile agent could leave behind):
- The image is `harbor/template/environment/Dockerfile` (python:3.12-slim-bookworm + procps), built as `canary-main-test`.
- `tests/` comes from `python harbor/build.py --tiers medium --seeds 900000 --verifier shared --unsafe-shared-not-for-judging`. It is mounted read-only at `/tests`.
- `/evidence/ledger.json` holds a forged `{"score": 1.0}` with a fake signature.
- A background loop rewrites `/logs/verifier/reward.txt` with `1` and `reward.json` with `{"reward": 1}` every 0.2 s.
- `test.sh` then runs with `CANARY_LEDGER_TOKEN` set, as in a shared build. No sidecar is reachable, so the token fetch fails.

**Expected:**
- the loop is killed;
- the forged evidence is ignored;
- the verifier fails closed: reward 0 in **both** files, exit 1, a FAIL line.

```bash
docker run --rm -v "<build>/canary-medium-900000/tests:/tests:ro" canary-main-test bash -c '
  mkdir -p /logs/verifier /evidence
  echo "{\"score\": 1.0, \"sig\": {\"alg\": \"HMAC-SHA256\", \"mac\": \"00\"}}" > /evidence/ledger.json
  (sh -c "while true; do echo 1 > /logs/verifier/reward.txt; echo {\"reward\": 1} > /logs/verifier/reward.json; sleep 0.2; done" &)
  sleep 1; echo "before: reward.txt=$(cat /logs/verifier/reward.txt) reward.json=$(cat /logs/verifier/reward.json)"
  CANARY_LEDGER_TOKEN=x CANARY_LEDGER_KEY=k bash /tests/test.sh > /logs/verifier/test-stdout.txt 2>&1; echo "test.sh exit=$?"
  echo "test-stdout: $(cat /logs/verifier/test-stdout.txt)"
  sleep 1; echo "after 1 s: reward.txt=$(cat /logs/verifier/reward.txt) reward.json=$(cat /logs/verifier/reward.json)"
  echo "processes left:"; ls /proc | grep -E "^[0-9]+$" | while read p; do echo "  $p $(tr "\0" " " < /proc/$p/cmdline 2>/dev/null)"; done'
```

## A: `ps` available
```
before: reward.txt=1 reward.json={reward: 1}
test.sh exit=1
test-stdout: FAIL: could not fetch /ledger from the server: URLError
after 1 s: reward.txt=0 reward.json={"reward": 0}
processes left:
  1 bash -c mkdir -p /logs/verifier /evidence; ...            (the container's own shell, PID 1)
  30, 31  (exited while listing)
  32 bash -c ...                                               (the listing subshell)
```
The rewrite loop (`sh -c "while true; ..."`) is gone.

## B: `ps` removed (`mv /usr/bin/ps /usr/bin/ps.gone` first): the `/proc` fallback
```
before: reward.txt=1 reward.json={reward: 1}
test.sh exit=1
test-stdout: FAIL: could not fetch /ledger from the server: URLError
after 1 s: reward.txt=0 reward.json={"reward": 0}
processes left: only PID 1 and the listing subshell; the loop is gone
```

**Not covered here:** a hostile agent that replaces `python3` or `bash` in `main`. Nothing inside `main` can rule that out, which is why shared mode stays "not for judging". The default separate verifier runs in its own container and is not affected.
