# CEO log

## 01:40 kickoff
- The decision: Canary (catch the mole). Spec: docs/CONTRACT.md v0. Plan: docs/PLAN.md. Org: docs/TEAM.md.
- Scaffold on `justSilas`: rules.py, types.py, Env signatures, Makefile, pyproject (uv, Python 3.12). `make test` is green (3 contract tests).
- Facts checked: no Docker on the Mac (HARNESS installs colima). FR8 has 24 free CPU cores on compute06, all GPUs are held by `sky`, /data is not writable (we use ~/agent-arena-data), and the login node has internet.

## Contract changes
(none yet)

## 01:55 v2 (max-score plan)
- Contract v0.1 adds the Mole DSL and Mole Forge: Gemini evolves the mole; the hall of fame becomes the frozen hard tier (CONTRACT §7).
- Every head brief gets a "v2 additions" section: property tests, `make hunt`, hint ablations, CI, J5 forge, CI sizing. P0 still comes first.
- Momin is building "The Sleeper" (a similar concept, far along) on origin/momin plus the sleeper/* branches. Compare at 09:00 on measured numbers.

## 02:05 decisions
- **Contract v0.2 (judge-world integrity), proposed by INTEGRITY and approved:**
  - world RNG = HMAC-SHA256(key, "tier:seed"); public key for dev/train seeds; CANARY_WORLD_SECRET or data/worlds/judge/SALT for judge and held-out seeds, server image only;
  - instance RNG only (never the global random module or hash());
  - the seed is never exposed (opaque episode tokens);
  - identical accuse payloads and errors for every target;
  - judge truth may be committed: the bar (Terminal-Bench style) is that the answer key is unreachable from the agent sandbox.
- HARNESS owns check_isolation.sh and the `make hunt` target.
- OPENAI_API_KEY set by Silas in the shared checkout .env.
- FR8 cancels only job ids listed in ~/agent-arena-data/jobs/OURS.txt.
