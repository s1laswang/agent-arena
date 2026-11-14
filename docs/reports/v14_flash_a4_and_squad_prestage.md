# PLAN-95 Action A4 (`opencode-gemini-3.5-flash` v1.4 Deep-Dive) and Squad Pre-Stage Gate Audit

## Section 1: PLAN-95 Action A4 Deep-Dive (`opencode-gemini-3.5-flash`, `n=60` on v1.4 Dev Seeds 0-29)

### 1.1 Provenance, Staging Layout, and Keyless Reproduction

To evaluate PLAN-95 Action A4 ("a second family on v1.4 hard, `n >= 30` ... shows the failure isn't one model's quirk") without touching `scripts/gemini_finalize.sh` reserved output paths (`medium/`, `hard/`, `tags.json`, `accuse.md`), the 4 verified OpenCode shards from PR #3 (`origin/fr8/afterquery/v14-runs` @ `6225cf86`) and the `0-29` reference baselines from `origin/fr8/afterquery/prs` (`5729e492`) were staged in `/localscratch/aq-tmp/w2-audit/runs/v1.4/`:

- **Subject run (`opencode:google/gemini-3.5-flash`, API `modelVersion` `gemini-3.6-flash`):** `4` clean shards (`medium-00-14`, `medium-15-29`, `hard-00-14`, `hard-15-29`), `15` episodes per shard = `60` valid episodes (`30` `medium` + `30` `hard`, dev seeds `0-29`), `60` transcripts, `0` infra-invalid exclusions, `0` timeouts.
- **Deterministic replay check (`scripts/verify_replay.py`):** **`60 / 60` episodes replay-verified** (`0` score or accusation mismatches between MCP server ledger and fresh `Env(tier, seed)` tool-call replay).
- **Commands executed (shared fleet venv, keyless):**

```bash
PY="env PYTHONPATH=. TMPDIR=/localscratch/aq-tmp /home/silas/agent-arena-data/fleet-shared-venv/bin/python"
$PY scripts/verify_replay.py /localscratch/aq-tmp/w2-audit/runs/v1.4/opencode-gemini-3.5-flash
$PY scripts/paired_gemini.py --root /localscratch/aq-tmp/w2-audit/runs --version v1.4 --seeds 0-29 \
  --out-md /localscratch/aq-tmp/w2-audit/out/paired_v14_flash.md \
  --out-json /localscratch/aq-tmp/w2-audit/out/paired_v14_flash.json
$PY -m canary.analysis.accuse --runs /localscratch/aq-tmp/w2-audit/runs/v1.4/opencode-gemini-3.5-flash \
  --out /localscratch/aq-tmp/w2-audit/out/accuse.md
$PY -m canary.analysis.tags --runs /localscratch/aq-tmp/w2-audit/runs/v1.4/opencode-gemini-3.5-flash \
  --out /localscratch/aq-tmp/w2-audit/out/tags_all.json
$PY scripts/regret_report.py /localscratch/aq-tmp/w2-audit/runs/v1.4/opencode-gemini-3.5-flash/*/episodes.jsonl \
  --reference 30 --name opencode-gemini-3.5-flash-v1.4 --out /localscratch/aq-tmp/w2-audit/out
```

---

### 1.2 Paired Raw vs Luck-Adjusted Gap Table (v1.4 Dev Seeds 0-29)

Each row below is paired seed-by-seed (`seeds 0-29`, `n=30` per tier) against the `v1.4` Bayesian `solver`. Raw ratio and luck-adjusted ratio 95% CIs use `scripts/paired_v13.py:boot_ratio` (`10,000` paired bootstrap resamples, `rng_seed=0`). Luck-adjusted score evaluates each accusation by its exact posterior expected value under everything the agent had observed up to the accusation step, `EV = P(accused) * V - (1 - P(accused))`, and `0.0` when abstaining.

| Tier | Agent / Policy | `n` | Raw Score +/- 95% CI | Accuracy | Accused Rate (Abstain) | Mean Accuse Day | Mean `P(accused)` | Solver Raw (Same Seeds) | **Raw / Solver [95% CI]** | Paired Raw Diff +/- 95% CI | Luck-Adjusted EV +/- 95% CI | **Luck-Adj / Solver [95% CI]** | Paired EV Diff +/- 95% CI |
|---|---|---:|---|---:|---:|---:|---:|---:|---|---|---|---:|---|
| `hard` | **`opencode:google/gemini-3.5-flash`** | `30` | `0.535 +/- 0.050` | `1.00` (`30/30`) | `1.00` (`0%`) | `11.5` | `0.91` (`0.910`) | `0.499` | **`107% [88%, 146%]`** | `+0.036 +/- 0.125` | `0.404 +/- 0.108` | **`81% [57%, 102%]`** | `-0.095 +/- 0.121` |
| `hard` | `solver` (reference) | `30` | `0.499 +/- 0.119` | `0.97` (`29/30`) | `1.00` (`0%`) | `10.6` | `0.97` (`0.965`) | `0.499` | `--` | `--` | `0.499 +/- 0.064` | `--` | `--` |
| `hard` | `grok_tactics` | `30` | `0.432 +/- 0.085` | `0.93` (`28/30`) | `0.93` (`7%`) | `10.4` | `0.96` (`0.964`) | `0.499` | `87% [67%, 119%]` | `-0.067 +/- 0.135` | `0.384 +/- 0.086` | `77% [61%, 95%]` | `-0.115 +/- 0.089` |
| `hard` | `heuristic` | `30` | `0.086 +/- 0.204` | `0.80` (`24/30`) | `1.00` (`0%`) | `14.4` | `0.78` (`0.775`) | `0.499` | `17% [-26%, 60%]` | `-0.413 +/- 0.250` | `0.052 +/- 0.145` | `10% [-20%, 37%]` | `-0.447 +/- 0.158` |
| `hard` | `do_nothing` | `30` | `0.000 +/- 0.000` | `0.00` (`0/30`) | `0.00` (`100%`) | `--` | `--` | `0.499` | `0% [0%, 0%]` | `-0.499 +/- 0.119` | `0.000 +/- 0.000` | `0% [0%, 0%]` | `-0.499 +/- 0.064` |
| `hard` | `random` | `30` | `-0.867 +/- 0.124` | `0.00` (`0/30`) | `0.87` (`13%`) | `8.1` | `0.02` (`0.016`) | `0.499` | `-174% [-242%, -134%]` | `-1.366 +/- 0.168` | `-0.841 +/- 0.120` | `-168% [-201%, -138%]` | `-1.340 +/- 0.137` |
| `hard` | `logs_only` | `30` | `-1.000 +/- 0.000` | `0.00` (`0/30`) | `1.00` (`0%`) | `10.0` | `0.01` (`0.012`) | `0.499` | `-200% [-271%, -167%]` | `-1.499 +/- 0.119` | `-0.979 +/- 0.014` | `-196% [-225%, -175%]` | `-1.478 +/- 0.066` |
| `hard` | `restrict_all` | `30` | `-1.000 +/- 0.000` | `0.00` (`0/30`) | `1.00` (`0%`) | `9.0` | `0.01` (`0.006`) | `0.499` | `-200% [-271%, -167%]` | `-1.499 +/- 0.119` | `-0.994 +/- 0.003` | `-199% [-228%, -177%]` | `-1.493 +/- 0.065` |
| `hard` | `stop_early` | `30` | `-1.000 +/- 0.000` | `0.00` (`0/30`) | `1.00` (`0%`) | `1.0` | `0.03` (`0.025`) | `0.499` | `-200% [-271%, -167%]` | `-1.499 +/- 0.119` | `-0.950 +/- 0.000` | `-190% [-218%, -169%]` | `-1.449 +/- 0.064` |
| `medium` | **`opencode:google/gemini-3.5-flash`** | `30` | `0.429 +/- 0.235` | `0.83` (`25/30`) | `1.00` (`0%`) | `9.2` | `0.87` (`0.867`) | `0.645` | **`66% [29%, 102%]`** | `-0.216 +/- 0.250` | `0.479 +/- 0.180` | **`74% [44%, 104%]`** | `-0.166 +/- 0.205` |
| `medium` | `solver` (reference) | `30` | `0.645 +/- 0.087` | `0.90` (`27/30`) | `0.90` (`10%`) | `7.6` | `1.00` (`1.000`) | `0.645` | `--` | `--` | `0.645 +/- 0.087` | `--` | `--` |
| `medium` | `grok_tactics` | `30` | `0.460 +/- 0.123` | `0.70` (`21/30`) | `0.70` (`30%`) | `7.7` | `1.00` (`1.000`) | `0.645` | `71% [51%, 95%]` | `-0.185 +/- 0.152` | `0.460 +/- 0.123` | `71% [51%, 95%]` | `-0.185 +/- 0.152` |
| `medium` | `do_nothing` | `30` | `0.000 +/- 0.000` | `0.00` (`0/30`) | `0.00` (`100%`) | `--` | `--` | `0.645` | `0% [0%, 0%]` | `-0.645 +/- 0.087` | `0.000 +/- 0.000` | `0% [0%, 0%]` | `-0.645 +/- 0.087` |
| `medium` | `heuristic` | `30` | `-0.407 +/- 0.284` | `0.37` (`11/30`) | `1.00` (`0%`) | `11.3` | `0.59` (`0.589`) | `0.645` | `-63% [-107%, -19%]` | `-1.052 +/- 0.301` | `-0.064 +/- 0.173` | `-10% [-36%, 18%]` | `-0.709 +/- 0.195` |
| `medium` | `random` | `30` | `-0.619 +/- 0.185` | `0.03` (`1/30`) | `0.67` (`33%`) | `6.3` | `0.07` (`0.067`) | `0.645` | `-96% [-126%, -67%]` | `-1.264 +/- 0.216` | `-0.594 +/- 0.162` | `-92% [-119%, -67%]` | `-1.239 +/- 0.196` |
| `medium` | `restrict_all` | `30` | `-0.933 +/- 0.091` | `0.07` (`2/30`) | `1.00` (`0%`) | `7.0` | `0.05` (`0.052`) | `0.645` | `-145% [-174%, -121%]` | `-1.578 +/- 0.113` | `-0.948 +/- 0.010` | `-147% [-172%, -130%]` | `-1.593 +/- 0.083` |
| `medium` | `stop_early` | `30` | `-0.933 +/- 0.131` | `0.03` (`1/30`) | `1.00` (`0%`) | `1.0` | `0.05` (`0.050`) | `0.645` | `-145% [-175%, -118%]` | `-1.578 +/- 0.160` | `-0.900 +/- 0.000` | `-140% [-163%, -125%]` | `-1.545 +/- 0.087` |
| `medium` | `logs_only` | `30` | `-1.000 +/- 0.000` | `0.00` (`0/30`) | `1.00` (`0%`) | `10.0` | `0.01` (`0.010`) | `0.645` | `-155% [-181%, -138%]` | `-1.645 +/- 0.087` | `-0.983 +/- 0.010` | `-152% [-178%, -136%]` | `-1.628 +/- 0.086` |

### 1.3 Why `hard` Shifts `107% -> 81%` and `medium` Shifts `66% -> 74%`: Calibration & Windfall Proof

`opencode-gemini-3.5-flash` exhibits the exact same two structural failure modes documented on `gpt-5.5` (`docs/reports/gap.md`) and `gemini-4-carbon` (`docs/PLAN-95.md`), proving PLAN-95 Action A4 that the failure is decision-theoretic rather than one model's quirk:

1. **Zero abstention (`60/60` accused, `0%` abstain) and horizon gambling below `1/(1+V)`:**
   - Across `60` episodes, `gemini-3.5-flash` reached `8` late-horizon states (days `13-19`) where its observations left a `2`-to-`6` employee candidate pool (`0.166 <= P(accused) <= 0.533`), strictly below the break-even threshold `1/(1+V)` (`[0.606, 0.787]`). Under `-1.0` wrong-accusation scoring, abstaining (`score = 0.0`) strictly dominates every one of those `8` accusations (`EV` between `-0.758` and `-0.121`), yet the model accused in `8/8` cases.
   - **On `hard` (`n=30`), coin-flip variance inflated raw score by `+3.912 V` (`+0.130 V`/episode):** Summed raw score is `16.040` (`0.535` mean) vs posterior-expected `12.128` (`0.404` mean). On `hard` seeds `7` (`P=0.312`, `V=0.27`) and `20` (`P=0.323`, `V=0.39`), `gemini-3.5-flash` gambled into ~3-way ties and won both (`0.3125 * 0.3226 = 10.1%` joint probability), netting `+0.660` raw points instead of `-1.155` expected (`+1.815 V` windfall from two guesses alone). Across the remaining `28` `hard` seeds (`0.791 <= P <= 1.000`), it also realized `0` wrong-tail losses (`+2.097 V` tail windfall), whereas `solver` remains calibration-invariant (`14.970` raw sum vs `14.979` EV sum; `solver`'s single `hard` miss on seed `15` at justified `P=0.874` matches its `30 - sum(P) = 1.045` expected misses across `30` seeds). Removing luck drops `gemini-3.5-flash` from **`107% [88%, 146%]` raw to `81% [57%, 102%]` luck-adjusted** (`-0.095 V` per episode behind `solver`).
   - **On `medium` (`n=30`), the identical policy went `1/6` on its gambles (`-1.523 V` unlucky realization, `-0.051 V`/episode):** Every single one of `gemini-3.5-flash`'s `24` justified `medium` accusations had `P(accused) = 1.000` (`24/24` exact canary pinpoints). All `5` wrong accusations (`-1.000` each) and `1` lucky hit (`seed 8`, `+0.630`) came from its `6` sub-threshold day `13-14` gambles (`sum P = 1.997` expected hits vs `1` realized hit; `-4.370` raw sum vs `-2.847` EV sum). Meanwhile `solver` accused on `27/30` at `P=1.000` and **deliberately abstained (`0.000`) on `3/30` (`seeds 20, 21, 29`)** when evidence stayed inconclusive; on `seed 29`, `solver` scored `0.000` by abstaining while `gemini-3.5-flash` gambled at `P=0.323 < 0.658` (`EV = -0.509`) and lost `-1.000`.
2. **Narrow singleton canaries on 40-staff `hard` (`65` `uninformative_canary` calls in `13/30` episodes):**
   - Before narrowing the `40`-employee `hard` roster, `gemini-3.5-flash` repeatedly plants `3`-recipient singleton canaries (`A:e00, B:e01, C:e02`, covering `7.5%` of posterior mass, `Gini < 0.2`). Because `careful_mole` scales canary leak weight by `1 - share` while the mole is outside a `3/40` assignment `92.5%` of the time, these calls burn action slots and canary fees while delaying identification (`mean accuse day 11.5` vs `solver` `10.6`).

---

### 1.4 Per-Episode Table: Every Lucky Gamble (`P(accused) < 1/(1+V)` & Correct) and Every Wrong Accusation (`correct == False`)

Across all `60` episodes (`30 medium + 30 hard`), `52` episodes are justified (`P(accused) >= 0.791`, exceeding `1/(1+V)` by at least `+0.128`, `52/52` correct). The remaining **`8` episodes** (`3` lucky gambles + `5` wrong accusations) exhaust both `P(accused) < 1/(1+V)` and `P(accused) < 0.600`:

| Outcome Class | `tier` | `seed` | `accuse_day` | `accused` | `true_mole` (replay) | `V_at_accuse` | `solver_P(accused)` | `threshold 1/(1+V)` | `raw_score` | `luck_adjusted_EV` | `solver_score` (same seed) |
|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| Lucky gamble (`correct=True`) | `hard` | `7` | `19` | `e37` | `e37` | `0.27` | `0.312` | `0.787` | `+0.270` | `-0.604` | `+0.640` (day `9`, `e37`) |
| Lucky gamble (`correct=True`) | `hard` | `20` | `15` | `e14` | `e14` | `0.39` | `0.323` | `0.719` | `+0.390` | `-0.551` | `+0.530` (day `12`, `e14`) |
| Lucky gamble (`correct=True`) | `medium` | `8` | `14` | `e02` | `e02` | `0.63` | `0.401` | `0.613` | `+0.630` | `-0.346` | `+0.880` (day `5`, `e02`) |
| Wrong accusation (`correct=False`) | `medium` | `11` | `14` | `e09` | `e07` | `0.56` | `0.221` | `0.641` | `-1.000` | `-0.655` | `+0.840` (day `5`, `e07`) |
| Wrong accusation (`correct=False`) | `medium` | `13` | `14` | `e03` | `e19` | `0.65` | `0.533` | `0.606` | `-1.000` | `-0.121` | `+0.790` (day `6`, `e19`) |
| Wrong accusation (`correct=False`) | `medium` | `22` | `13` | `e11` | `e18` | `0.46` | `0.166` | `0.685` | `-1.000` | `-0.758` | `+0.740` (day `7`, `e18`) |
| Wrong accusation (`correct=False`) | `medium` | `26` | `13` | `e19` | `e18` | `0.53` | `0.354` | `0.654` | `-1.000` | `-0.458` | `+0.800` (day `5`, `e18`) |
| Wrong accusation (`correct=False`) | `medium` | `29` | `13` | `e18` | `e00` | `0.52` | `0.323` | `0.658` | `-1.000` | `-0.509` | `0.000` (abstained day `14`) |
| **Sum across 8 gamble episodes** | -- | -- | -- | -- | -- | -- | `2.633` (exp. hits) | -- | **`-3.710`** | **`-4.002`** | **`+5.220`** |

Notes on the 8 sub-threshold episodes:
- `V_at_accuse` is the true company value `meta.V` scored at accusation (the public known-V `sp.V` shown in `status` before unsurfaced leaks was `0.32`, `0.44`, `0.67`, `0.60`, `0.69`, `0.46`, `0.57`, `0.52` respectively; every episode is also strictly below `1/(1 + sp.V)`).
- None of the `8` accusations targeted the world's `decoy` employee (`e12`, `e08`, `e01`, `e06`, `e05`, `e16`, `e07`, `e05` respectively; `decoy_chase = 0`); in each case `gemini-3.5-flash` narrowed to the leaked-document recipient intersection (`2` to `6` suspects) and broke ties using framed after-hours log counts or weak interview signals instead of abstaining.

---

### 1.5 Regret Tag & Action Decomposition (`canary.analysis.tags` + `scripts/regret_report.py`)

Offline server-truth regret attribution (`scripts/regret_report.py`, injecting `env._world.decoy` to check `decoy_chase`) matches `canary.analysis.tags` identically on all tag counts and value-lost totals (`decoy_chase = 0` on `gemini-3.5-flash`):

| Tag / Regret Component | `medium` (`n=30`) Count (Episodes, Rate) | `medium` Value Lost (`V` Sum / Per Ep) | `hard` (`n=30`) Count (Episodes, Rate) | `hard` Value Lost (`V` Sum / Per Ep) | Combined (`n=60`) Count (Episodes, Rate) | Combined Value Lost (`V` Sum / Per Ep) |
|---|---|---:|---|---:|---|---:|
| `premature_accusation` | `6` (`6/30`, `20.0%`) | `2.992 V` (`0.100 V`) | `2` (`2/30`, `6.7%`) | `1.501 V` (`0.050 V`) | `8` (`8/60`, `13.3%`) | `4.494 V` (`0.075 V`) |
| `uninformative_canary` | `5` (`1/30`, `3.3%`) | `0.000 V` (`0.000 V`) | `65` (`13/30`, `43.3%`) | `1.575 V` (`0.053 V`) | `70` (`14/60`, `23.3%`) | `1.575 V` (`0.026 V`) |
| `budget_waste` | `20` (`12/30`, `40.0%`) | `0.000 V` (`0.000 V`) | `10` (`9/30`, `30.0%`) | `0.000 V` (`0.000 V`) | `30` (`21/60`, `35.0%`) | `0.000 V` (`0.000 V`) |
| `decoy_chase` | `0` (`0/30`, `0.0%`) | `0.000 V` (`0.000 V`) | `0` (`0/30`, `0.0%`) | `0.000 V` (`0.000 V`) | `0` (`0/60`, `0.0%`) | `0.000 V` (`0.000 V`) |
| `ignored_delay` | `0` (`0/30`, `0.0%`) | `0.000 V` (`0.000 V`) | `0` (`0/30`, `0.0%`) | `0.000 V` (`0.000 V`) | `0` (`0/60`, `0.0%`) | `0.000 V` (`0.000 V`) |
| `over_restriction` | `0` (`0/30`, `0.0%`) | `0.000 V` (`0.000 V`) | `0` (`0/30`, `0.0%`) | `0.000 V` (`0.000 V`) | `0` (`0/60`, `0.0%`) | `0.000 V` (`0.000 V`) |
| `no_accusation` | `0` (`0/30`, `0.0%`) | `0.000 V` (`0.000 V`) | `0` (`0/30`, `0.0%`) | `0.000 V` (`0.000 V`) | `0` (`0/60`, `0.0%`) | `0.000 V` (`0.000 V`) |
| **Subtotal: Tagged Regret** | -- | **`2.992 V` (`0.100 V`)** | -- | **`3.077 V` (`0.103 V`)** | -- | **`6.069 V` (`0.101 V`)** |
| Untagged `plant_canary` (`0.2 <= Gini < Gini_solver`) | -- | `1.129 V` (`0.038 V`) | -- | `2.535 V` (`0.085 V`) | -- | `3.664 V` (`0.061 V`) |
| Untagged `accuse` (`0.79 <= P < 0.99`, `Q_cont > Q_acc`) | -- | `0.000 V` (`0.000 V`) | -- | `1.673 V` (`0.056 V`) | -- | `1.673 V` (`0.028 V`) |
| Untagged `restrict_access` (`P >= 0.10`) + `advance_day` | -- | `0.178 V` (`0.006 V`) | -- | `0.028 V` (`0.001 V`) | -- | `0.206 V` (`0.003 V`) |
| **Total Episode Regret (`gemini-3.5-flash`)** | -- | **`4.299 V` (`0.143 V`)** | -- | **`7.313 V` (`0.244 V`)** | -- | **`11.612 V` (`0.194 V`)** |
| Reference comparison: `solver` (`n=30+30`) | `no_accusation=3` (`0 V`) | `0.000 V` (`0.000 V`) | `0` tags | `2.190 V` (`0.073 V`) | `no_accusation=3` (`0 V`) | `2.190 V` (`0.037 V`) |
| Reference comparison: `heuristic` (`n=30+30`) | `premature=21` (`16.753 V`), `decoy=3` (`2.478 V`) | `19.770 V` (`0.659 V`) | `premature=6` (`4.617 V`), `uninf=12` (`0.467 V`) | `14.880 V` (`0.496 V`) | `premature=27` (`21.370 V`) | `34.650 V` (`0.578 V`) |

Top 5 single costliest decisions per tier (`scripts/regret_report.py`):
- **`hard`:** `seed 20` (`t=52`, day `15`, `accuse e14`, `0.877 V`, `premature_accusation`), `seed 7` (`t=92`, day `19`, `accuse e37`, `0.624 V`, `premature_accusation`), `seed 24` (`t=55`, day `9`, `accuse e17` at `P=0.791`, `0.289 V`), `seed 29` (`t=53`, day `9`, `accuse e19` at `P=0.843`, `0.233 V`), `seed 28` (`t=73`, day `14`, `accuse e35` at `P=0.886`, `0.148 V`).
- **`medium`:** `seed 22` (`t=67`, day `13`, `accuse e11`, `0.792 V`, `premature_accusation`), `seed 11` (`t=91`, day `14`, `accuse e09`, `0.646 V`, `premature_accusation`), `seed 29` (`t=76`, day `13`, `accuse e18`, `0.586 V`, `premature_accusation`), `seed 26` (`t=75`, day `13`, `accuse e19`, `0.539 V`, `premature_accusation`), `seed 8` (`t=82`, day `14`, `accuse e02`, `0.330 V`, `premature_accusation`).

---

## Section 2: Pre-Stage Gate Audit of Active Squad & Worker Branches

### 2.1 Audit Scope and Execution

`scripts/verify_pr_branch.py` from `origin/fr8/afterquery/afterquery-prs-w5` (`0b28ea73`) was run against `origin/justSilas` (`7232f800`) across:
1. All `4` non-PR squad staging branches: `origin/fr8/afterquery/{frontier,research,integrity,replay}`.
2. Every non-base worker branch `origin/fr8/afterquery/afterquery-{frontier,research,integrity,replay}-w*` whose tip differs from the initial worker base SHA `c01f371a` (`10` active worker branches; the remaining `26` of `36` worker branches -- `frontier-w1..w8`, `integrity-w1..w9`, `replay-w2..w9`, and `research-w6` -- remain untouched at `c01f371a`).

### 2.2 `verify_pr_branch.py` 10-Gate Matrix vs `origin/justSilas` (`7232f800`)

Gate column legend (all 10 `verify_pr_branch.py` gates in execution order):
1. `merge_conflict` (`git merge-tree --write-tree`)
2. `protected_core` (`canary/{env.py,rules.py,reproduce.py,solver/}`, `harbor/`)
3. `finalize_reserved_path` (`data/runs/committed/v1.4/<gemini-lane>/{medium,hard,tags.json,accuse.md}`)
4. `python_comments` (tokenize check for `#` comments in added/modified `.py`)
5. `unicode_dashes` (`U+2014` / `U+2013` in non-transcript text blobs)
6. `co_authored_by` (`Co-Authored-By:` trailers in `base..branch` commits)
7. `secret_leak` (`.env*`, `judge/SALT`, `AIza*`, `sk-*`, `ghp_*`)
8. `timeout_episode` (`rc==timeout`, `end_reason==error`, `meta.valid==False`, duplicate `(agent,tier,seed)`)
9. `orphan_transcript` (`meta.json` `seeds` parity and orphan `transcripts/*.txt`)
10. `replay_mismatch` (`scripts/verify_replay.py:replay_episode` on committed `v1.4` dev episodes)

| Branch (`origin/fr8/afterquery/...`) | Tip SHA | Changed Files vs `justSilas` | `ff_base` (`merge_base`) | `merge_conflict` | `protected_core` | `finalize_reserved_path` | `python_comments` | `unicode_dashes` | `co_authored_by` | `secret_leak` | `timeout_episode` | `orphan_transcript` | `replay_mismatch` |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|---|
| `frontier` | `c107a056` | `48` | `False` (`b4557e00`) | PASS | PASS (`0`) | PASS (`0`) | PASS (`0 .py`) | PASS (`24` chk) | PASS (`7` cmt) | PASS (`48` chk) | PASS (`24` epf) | PASS (`24` shd) | PASS (`480/480`) |
| `research` | `908458d2` | `0` | `True` (`7232f800`) | PASS | PASS (`0`) | PASS (`0`) | PASS (`0 .py`) | PASS (`0` chk) | PASS (`6` cmt) | PASS (`0` chk) | PASS (`0` epf) | PASS (`0` shd) | PASS (`0/0`) |
| `integrity` | `5ee8ec80` | `0` | `True` (`7232f800`) | PASS | PASS (`0`) | PASS (`0`) | PASS (`0 .py`) | PASS (`0` chk) | PASS (`6` cmt) | PASS (`0` chk) | PASS (`0` epf) | PASS (`0` shd) | PASS (`0/0`) |
| `replay` | `c730e518` | `3` | `True` (`7232f800`) | PASS | PASS (`0`) | PASS (`0`) | PASS (`3 .py`) | PASS (`3` chk) | PASS (`10` cmt) | PASS (`3` chk) | PASS (`0` epf) | PASS (`0` shd) | PASS (`0/0`) |
| `afterquery-frontier-w9` | `79e0c5df` | `49` | `False` (`df47a314`) | PASS | PASS (`0`) | PASS (`0`) | PASS (`0 .py`) | PASS (`25` chk) | PASS (`5` cmt) | PASS (`49` chk) | PASS (`24` epf) | PASS (`24` shd) | PASS (`480/480`) |
| `afterquery-research-w1` | `ee026519` | `2` | `False` (`b4557e00`) | PASS | PASS (`0`) | PASS (`0`) | PASS (`0 .py`) | PASS (`2` chk) | PASS (`7` cmt) | PASS (`2` chk) | PASS (`0` epf) | PASS (`0` shd) | PASS (`0/0`) |
| `afterquery-research-w2` | `4ba0efd4` | `2` | `False` (`b4557e00`) | PASS | PASS (`0`) | PASS (`0`) | PASS (`0 .py`) | PASS (`2` chk) | PASS (`7` cmt) | PASS (`2` chk) | PASS (`0` epf) | PASS (`0` shd) | PASS (`0/0`) |
| `afterquery-research-w3` | `bf390ada` | `0` | `False` (`b4557e00`) | PASS | PASS (`0`) | PASS (`0`) | PASS (`0 .py`) | PASS (`0` chk) | PASS (`5` cmt) | PASS (`0` chk) | PASS (`0` epf) | PASS (`0` shd) | PASS (`0/0`) |
| `afterquery-research-w4` | `ad67d8c4` | `1` | `False` (`b4557e00`) | PASS | PASS (`0`) | PASS (`0`) | PASS (`0 .py`) | PASS (`1` chk) | PASS (`6` cmt) | PASS (`1` chk) | PASS (`0` epf) | PASS (`0` shd) | PASS (`0/0`) |
| `afterquery-research-w5` | `0696df8e` | `1` | `False` (`b4557e00`) | PASS | PASS (`0`) | PASS (`0`) | PASS (`0 .py`) | PASS (`1` chk) | PASS (`6` cmt) | PASS (`1` chk) | PASS (`0` epf) | PASS (`0` shd) | PASS (`0/0`) |
| `afterquery-research-w7` | `9ad3123e` | `1` | `False` (`b4557e00`) | PASS | PASS (`0`) | PASS (`0`) | PASS (`0 .py`) | PASS (`1` chk) | PASS (`6` cmt) | PASS (`1` chk) | PASS (`0` epf) | PASS (`0` shd) | PASS (`0/0`) |
| `afterquery-research-w8` | `bf390ada` | `0` | `False` (`b4557e00`) | PASS | PASS (`0`) | PASS (`0`) | PASS (`0 .py`) | PASS (`0` chk) | PASS (`5` cmt) | PASS (`0` chk) | PASS (`0` epf) | PASS (`0` shd) | PASS (`0/0`) |
| `afterquery-research-w9` | `bc3b411e` | `1` | `False` (`b4557e00`) | PASS | PASS (`0`) | PASS (`0`) | PASS (`0 .py`) | PASS (`1` chk) | PASS (`6` cmt) | PASS (`1` chk) | PASS (`0` epf) | PASS (`0` shd) | PASS (`0/0`) |
| `afterquery-replay-w1` | `207a4349` | `3` | `False` (`df47a314`) | PASS | PASS (`0`) | PASS (`0`) | PASS (`3 .py`) | PASS (`3` chk) | PASS (`7` cmt) | PASS (`3` chk) | PASS (`0` epf) | PASS (`0` shd) | PASS (`0/0`) |

---

### 2.3 Actionable Pre-Stage Warnings for Squad Leads (Fix Before PR Merge)

Although all `14` branches pass `10/10` automated gates under default `verify_pr_branch.py`, manual diff inspection surfaced **5 concrete pre-stage issues** that squad leads should resolve before packaging PRs into `justSilas`:

1. **`research` squad (`afterquery-research-w1, w2, w4, w5, w7, w9`) -- `_parts/` scratch files and `justSilas-v15`-only path citations:**
   - **Scratch directories:** All `8` committed markdown files across the active `research-w*` branches live under `docs/research/_parts/` (`00_header_and_exec_summary.md`, `01_rumours_attribution.md`, `02_grudges_conflict.md`, `04_miscommunication_coordination.md`, `05_overconfidence_commitment.md`, `07_corporate_governance_failures.md`, `09_canary_traps_watermarking.md`, `10_synthesis_and_canary_mapping.md`), with `docs/research/_audits/` also in flight on `w2` and `w4`. Before opening the `research` PR into `justSilas`, `afterquery-research-lead` must assemble the final report (e.g. `docs/research-afterquery.md`) and `git rm -r docs/research/_parts docs/research/_audits` so multi-worker staging shards do not ship.
   - **Cross-branch path references:** Parts `00`, `01`, `02`, `04`, and `10` cite `results/fresh_table_v1.5-candidate.md`, `canary/baselines.py` (`RumourFollower`), and `canary/solver/belief.py:social_loglik`. Those paths exist only on `origin/justSilas-v15` (`de9cc50e`), not on `justSilas` (`7232f800`, where Gate B dropped `v1.5` at `07cb8865`). Keep them strictly as non-link code spans qualified with `justSilas-v15` so markdown link checkers do not flag missing files on `justSilas`.

2. **`replay` squad (`origin/fr8/afterquery/replay` @ `c730e518` & `afterquery-replay-w1` @ `207a4349`) -- CWD and `--basetemp` assumptions in `replay/loader.py` and `tests/test_replay_loader.py`:**
   - **CWD shadowing of `REPO_ROOT` (`replay/loader.py:68-74` & `87-92`):** `_resolve_root("data/runs/committed")` checks `if not candidate.is_absolute() and not candidate.exists():` before falling back to `REPO_ROOT / candidate`. If `load_committed_episodes()` or `pytest` is invoked from another worktree or staging directory that happens to contain `data/runs/committed/`, `_resolve_root` loads the CWD directory instead of `REPO_ROOT / "data/runs/committed"`, and `_format_source_path()` returns an absolute path outside `REPO_ROOT`, breaking `tests/test_replay_loader.py:263` (`assert ep["source_path"].startswith("data/runs/committed/")`). Fix: resolve default `DEFAULT_COMMITTED_ROOT` directly against `REPO_ROOT` (`REPO_ROOT / DEFAULT_COMMITTED_ROOT`).
   - **Repo-interior `tmp_path` failure (`tests/test_replay_loader.py:168`):** `assert all(Path(ep["source_path"]).is_absolute() for ep in valid_only)` assumes pytest's `tmp_path` lies outside `REPO_ROOT`. Running `pytest --basetemp=.pytest_tmp` (inside the repo tree) causes `_format_source_path()` (`resolved.relative_to(REPO_ROOT)`) to return a relative path, failing line `168`. Fix: format `source_path` relative to `root_path` or test `Path(ep["source_path"])` without assuming `tmp_path` is external to `REPO_ROOT`.

3. **`frontier` squad (`afterquery-frontier-w9` @ `79e0c5df` vs `origin/fr8/afterquery/frontier` @ `c107a056`) -- stale `configs/README.md` edit on `w9` and duplicate reference shards:**
   - **Do not merge `frontier-w9` directly into `justSilas`:** Because `frontier-w9` has `merge_base = df47a314` (pre-`justSilas` sync), its merged tree modifies `configs/README.md` (`49` changed files vs `48` on `frontier`) to document `--write-episode-file` and `canary.mcp_server.spawn_isolated_server`, which were stripped when syncing onto `justSilas` (`grep -c spawn_isolated_server canary/mcp_server.py == 0`). `origin/fr8/afterquery/frontier` (`c107a056`) already resolved this cleanly and keeps only the `48` `v1.4/reference/` files.
   - **Byte-identical overlap with `origin/fr8/afterquery/prs`:** All `48` files on `origin/fr8/afterquery/frontier` (`c107a056`) under `data/runs/committed/v1.4/reference/` (`seeds20to29`, `seeds30to59`, `grok_tactics`, `logs_only`) have `0` byte diff against `origin/fr8/afterquery/prs` (`da82563d`). Once the `reference` PR lands on `justSilas`, `frontier` should rebase/merge `origin/justSilas` so its PR contains only the new `hard` seeds `30-59` `gemini-4-carbon` shards.

4. **Strict fast-forward readiness (`--require-ff-base`):**
   - `11` of the `14` audited branches currently have `ff_base == False` against `origin/justSilas` (`7232f800`): `frontier` and `research-w*` sit at `b4557e00` (`1` commit behind `justSilas`), while `frontier-w9` and `replay-w1` sit at `df47a314`. Only `research` (`908458d2`), `integrity` (`5ee8ec80`), and `replay` (`c730e518`) pass `verify_pr_branch.py --require-ff-base` today. Squad leads should merge/rebase onto `origin/justSilas` immediately prior to PR creation.

5. **`integrity` squad (`origin/fr8/afterquery/integrity` @ `5ee8ec80`):**
   - Cleanly synced to `7232f800` (`ff_base = True`, `0` changed files yet; `w1..w9` sweeps active in worktrees). Remind workers touching `EXPLOITS.md`, `tests/test_anticheat.py`, or `canary/redteam/` to coordinate with PR #12 (`origin/vaishnav/canary-cheat`) and respect `protected_core` (`canary/env.py`, `canary/rules.py`, `canary/reproduce.py`, `canary/solver/`, `harbor/`).
