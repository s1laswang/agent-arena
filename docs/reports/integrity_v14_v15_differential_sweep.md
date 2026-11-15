# Paired Differential Exploit & Lexical-Shortcut Sweep: Canary `v1.4` vs `v1.5`

## 1. Executive Summary

- **Versions Audited (Paired Seeds `0..99`):**
  - **`v1.4` (`justSilas` @ `5f9b3297`, `canary/` identical to `9225f2ad`):** Frozen ruleset `TIERS_VERSION = "v1.4"` (tier hash `a8f99c2537c91d72`, `KNOWN_V_MODE = True`).
  - **`v1.5` (`origin/justSilas-v15` @ `de9cc50e`):** `v1.5-candidate` WS2 human-bias social layer (`rumour_rate=2.0`, `rumour_frame_share=0.4`, `grudge_pairs=2`, `grudge_rate=0.5`, `authority_day=3`, `p_misforward=0.15`), loaded strictly in-memory via `git show de9cc50e:canary/...` (`14` Python modules; seamlessly falling back to the embedded `zlib`+`base64` `de9cc50e` source map in `fetch-depth=1` shallow CI checkouts or `.git`-less archives) into the isolated module namespace `_canary_v15_isolated` with `0` checkouts, `0` working-tree modifications (`git status --porcelain` verified unchanged before, during, and after), and `v1.4` tier hash `a8f99c2537c91d72` preserved.
- **Scale & Budget:** `6,600` total deterministic episodes (`6,000` paired strategy episodes across `3` tiers x `10` strategies x `100` paired seeds x `2` versions + `600` full-horizon passive lexical/stream differential scan episodes across `easy`, `medium`, `hard`), `0` LLM/API calls, `96.36s` wall time (`--workers 2`).
- **Reward & Exploit Integrity Verdict: HELD (`0` exploits, `0` score/state invariant violations across `6,000/6,000` strategy episodes).**
  - Abstaining baselines (`do_nothing`, `stop_early`) score **`+0.0000 +- 0.0000`** on `100%` of episodes across both `v1.4` and `v1.5` on every tier (`0` partial-`V` early-quit leaks).
  - Every zero-LLM accusing heuristic (`blind_seat_0`, `accuse_most_talkative`, `accuse_authority_role`, `accuse_first_named_anchor`, `accuse_lexical_hedging`, `log_volume_outlier`, `one_interview_accuse`) scores **strictly negative** on both `v1.4` and `v1.5` (`<= -0.5665` on `easy`, `<= -0.8800` on `medium`, `<= -0.9415` on `hard`), leaving `do_nothing` / `stop_early` (`0.0000`) as the best non-solver strategy on every slice.
  - `reference_solver` maintains a large positive gap over both abstention (`0.0000`) and every accusing heuristic on both `v1.4` and `v1.5`: **`+0.7901` vs `+0.7902` on `easy`**, **`+0.6073` vs `+0.6599` on `medium`**, and **`+0.5521` vs `+0.6053` on `hard`**.
- **Lexical-Shortcut Verdict: NO positive mole-identifying lexical leak in `v1.5` human-bias text (`0` `"mole"` word leaks, `0` secret/seed token leaks, `0` statistically significant sender-token or target-token positive lifts across `15,003` social messages and `2,167` misforwarded documents).**
  - Forward social heuristics are penalized rather than aided by `v1.5` text: `accuse_first_named_anchor` decoy false-accusations jump from **`5.0% -> 28.0%` (`+23.0 pp`) on `medium`** and **`4.0% -> 36.0%` (`+32.0 pp`) on `hard`**, while `accuse_lexical_hedging` mole accuracy drops or stays within random noise (`19.0% -> 15.0%` on `easy`, `6.0% -> 2.0%` on `medium`, `1.0% -> 3.0%` on `hard`) because hedged social chatter dilutes interview hedging cues.
- **Issues-Only Findings (`5` structural/implementation issues documented in Section 5; `0` protected files edited):**
  1. `ISS-DIFF-01`: Rumour/authority target anti-correlation (`P(mole | rumour target) < 1/N`) and top-named social target decoy oracle (`95.0%` `medium`, `99.0%` `hard` decoy; `0.0%` mole).
  2. `ISS-DIFF-02`: `Env._grudges()` excludes `decoy`, yielding `P(decoy | grudge participant) = 0/400 = 0.0000` on `medium` and `hard`.
  3. `ISS-DIFF-03`: `p_misforward=0.15` mutates `self._held` and couples into `self._dyn`, desynchronizing paired leak sequences on `82%-96%` of seeds and access-log streams on `98%-100%` of seeds despite the `canary/env.py:356-357` comment claiming leak/log streams remain unchanged.
  4. `ISS-DIFF-04`: Machine-readable social subject prefixes (`rumour: eXX`, `unverified accusation: eXX`, `grudge: eXX`) and `m{day}-s{k}` message IDs expose explicit `eXX` anchors on Day 2 (`mean_day = 2.02-2.04` vs `4.00` in `v1.4`).
  5. `ISS-DIFF-05`: `TemplateProvider` interview answers have `81.25%` hedge recall (`0.0%` cooperative false positives) and `0/16` literal `"evasive"` occurrences, whereas `SolverPolicy._ingest` checks `"evasive" in sig` (`False` on `100%` of `TemplateProvider` answers during offline `regret`/`accuse` transcript replay).

## 2. Reproduce Commands (Keyless, Zero API Calls)

Fast subset (`<2s`, `88` episodes in both full clones via `git show` and `fetch-depth=1` shallow CI or `.git`-less checkouts via embedded `de9cc50e` `zlib`+`base64` fallback):

```bash
/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/integrity_v14_v15_differential_sweep.py --fast
/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/integrity_v14_v15_differential_sweep.py --fast --shallow-fallback
/tmp/fleet-silas/shared/agent-arena-venv/bin/python -m pytest -p no:cacheprovider -q tests/test_integrity_v14_v15_differential_sweep.py
```

Full `6,600`-episode paired sweep across seeds `0..99` on `easy,medium,hard`:

```bash
/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/integrity_v14_v15_differential_sweep.py --full
```

## 3. Paired 10-Strategy Sweep (`v1.4` vs `v1.5`, Seeds `0..99`, `6,000` Strategy Episodes)

Every `(tier, seed)` pair (`n=100` per tier) verified `100.0%` identical underlying world truth (`true_mole` and `true_decoy` match `100/100` on `easy`, `medium`, and `hard`) and `0` score invariant violations.

### 3.1 `easy` Tier (`n_employees = 12`, Prior `1/N = 8.33%`, No Decoy, Seeds `0..99`)

| Strategy | `v1.4` Mean Score (`+-95% CI`) | `v1.5` Mean Score (`+-95% CI`) | Paired `v1.5 - v1.4` (`+-95% CI`, `W/T/L`) | `v1.4` Acc | `v1.5` Acc | Same Accused | `v1.4` Gap vs Solver | `v1.5` Gap vs Solver |
|---|---|---|---|---|---|---|---|---|
| `do_nothing` | `+0.0000 +- 0.0000` | `+0.0000 +- 0.0000` | `+0.0000 +- 0.0000` (`0/100/0`) | `0.0%` | `0.0%` | `100.0%` | `+0.7901 +- 0.0240` | `+0.7902 +- 0.0211` |
| `stop_early` | `+0.0000 +- 0.0000` | `+0.0000 +- 0.0000` | `+0.0000 +- 0.0000` (`0/100/0`) | `0.0%` | `0.0%` | `100.0%` | `+0.7901 +- 0.0240` | `+0.7902 +- 0.0211` |
| `blind_seat_0` | `-0.8600 +- 0.1005` | `-0.8600 +- 0.1005` | `+0.0000 +- 0.0000` (`0/100/0`) | `7.0%` | `7.0%` | `100.0%` | `+1.6501 +- 0.1039` | `+1.6502 +- 0.1030` |
| `accuse_most_talkative` | `-0.8385 +- 0.1012` | `-0.7870 +- 0.1137` | `+0.0515 +- 0.1059` (`6/90/4`) | `9.0%` | `12.0%` | `40.0%` | `+1.6286 +- 0.1025` | `+1.5772 +- 0.1166` |
| `accuse_authority_role` | `-0.8315 +- 0.1056` | `-0.9060 +- 0.0807` | `-0.0745 +- 0.0724` (`1/95/4`) | `9.0%` | `5.0%` | `68.0%` | `+1.6216 +- 0.1146` | `+1.6962 +- 0.0863` |
| `accuse_first_named_anchor` | `-0.7950 +- 0.1149` | `-0.8630 +- 0.0984` | `-0.0680 +- 0.1492` (`7/83/10`) | `11.0%` | `7.0%` | `9.0%` | `+1.5851 +- 0.1159` | `+1.6532 +- 0.1060` |
| `accuse_lexical_hedging` | `-0.6450 +- 0.1444` | `-0.7185 +- 0.1320` | `-0.0735 +- 0.1159` (`5/88/7`) | `19.0%` | `15.0%` | `59.0%` | `+1.4351 +- 0.1453` | `+1.5087 +- 0.1372` |
| `log_volume_outlier` | `-0.6230 +- 0.1441` | `-0.5665 +- 0.1520` | `+0.0565 +- 0.1449` (`11/82/7`) | `21.0%` | `24.0%` | `72.0%` | `+1.4131 +- 0.1448` | `+1.3567 +- 0.1543` |
| `one_interview_accuse` | `-0.7800 +- 0.1233` | `-0.7800 +- 0.1233` | `+0.0000 +- 0.0000` (`0/100/0`) | `11.0%` | `11.0%` | `100.0%` | `+1.5701 +- 0.1242` | `+1.5702 +- 0.1238` |
| **`reference_solver`** | **`+0.7901 +- 0.0240`** | **`+0.7902 +- 0.0211`** | **`+0.0001 +- 0.0190` (`11/76/13`)** | **`99.0%`** | **`100.0%`** | **`99.0%`** | baseline | baseline |

### 3.2 `medium` Tier (`n_employees = 20`, Prior `1/N = 5.00%`, Decoy + Framing, Seeds `0..99`)

| Strategy | `v1.4` Mean Score (`+-95% CI`) | `v1.5` Mean Score (`+-95% CI`) | Paired `v1.5 - v1.4` (`+-95% CI`, `W/T/L`) | `v1.4` Acc / Decoy | `v1.5` Acc / Decoy | Same Accused | `v1.4` Gap vs Solver | `v1.5` Gap vs Solver |
|---|---|---|---|---|---|---|---|---|
| `do_nothing` | `+0.0000 +- 0.0000` | `+0.0000 +- 0.0000` | `+0.0000 +- 0.0000` (`0/100/0`) | `0.0%` / `0.0%` | `0.0%` / `0.0%` | `100.0%` | `+0.6073 +- 0.0522` | `+0.6599 +- 0.0417` |
| `stop_early` | `+0.0000 +- 0.0000` | `+0.0000 +- 0.0000` | `+0.0000 +- 0.0000` (`0/100/0`) | `0.0%` / `0.0%` | `0.0%` / `0.0%` | `100.0%` | `+0.6073 +- 0.0522` | `+0.6599 +- 0.0417` |
| `blind_seat_0` | `-0.8800 +- 0.0936` | `-0.8800 +- 0.0936` | `+0.0000 +- 0.0000` (`0/100/0`) | `6.0%` / `7.0%` | `6.0%` / `7.0%` | `100.0%` | `+1.4873 +- 0.1125` | `+1.5399 +- 0.0979` |
| `accuse_most_talkative` | `-1.0000 +- 0.0000` | `-1.0000 +- 0.0000` | `+0.0000 +- 0.0000` (`0/100/0`) | `0.0%` / `99.0%` | `0.0%` / `97.0%` | `98.0%` | `+1.6073 +- 0.0522` | `+1.6599 +- 0.0417` |
| `accuse_authority_role` | `-0.9036 +- 0.0828` | `-0.9424 +- 0.0645` | `-0.0388 +- 0.0535` (`0/98/2`) | `5.0%` / `33.0%` | `3.0%` / `30.0%` | `67.0%` | `+1.5109 +- 0.1052` | `+1.6023 +- 0.0728` |
| `accuse_first_named_anchor` | `-0.9808 +- 0.0376` | `-0.9608 +- 0.0541` | `+0.0200 +- 0.0663` (`2/97/1`) | `1.0%` / **`5.0%`** | `2.0%` / **`28.0%`** | `3.0%` | `+1.5881 +- 0.0618` | `+1.6207 +- 0.0689` |
| `accuse_lexical_hedging` | `-0.8836 +- 0.0908` | `-0.9612 +- 0.0535` | `-0.0776 +- 0.0749` (`0/96/4`) | `6.0%` / `9.0%` | `2.0%` / `11.0%` | `66.0%` | `+1.4909 +- 0.1009` | `+1.6211 +- 0.0638` |
| `log_volume_outlier` | `-0.9816 +- 0.0361` | `-0.9812 +- 0.0368` | `+0.0004 +- 0.0518` (`1/98/1`) | `1.0%` / `71.0%` | `1.0%` / `70.0%` | `76.0%` | `+1.5889 +- 0.0619` | `+1.6411 +- 0.0531` |
| `one_interview_accuse` | `-0.9200 +- 0.0772` | `-0.9200 +- 0.0772` | `+0.0000 +- 0.0000` (`0/100/0`) | `4.0%` / `6.0%` | `4.0%` / `6.0%` | `100.0%` | `+1.5273 +- 0.1006` | `+1.5799 +- 0.0908` |
| **`reference_solver`** | **`+0.6073 +- 0.0522`** | **`+0.6599 +- 0.0417`** | **`+0.0526 +- 0.0487` (`39/40/21`)** | **`86.0%` / `0.0%`** | **`93.0%` / `0.0%`** | **`87.0%`** | baseline | baseline |

### 3.3 `hard` Tier (`n_employees = 40`, Prior `1/N = 2.50%`, Decoy + Framing + Imperfect Fingerprint, Seeds `0..99`)

| Strategy | `v1.4` Mean Score (`+-95% CI`) | `v1.5` Mean Score (`+-95% CI`) | Paired `v1.5 - v1.4` (`+-95% CI`, `W/T/L`) | `v1.4` Acc / Decoy | `v1.5` Acc / Decoy | Same Accused | `v1.4` Gap vs Solver | `v1.5` Gap vs Solver |
|---|---|---|---|---|---|---|---|---|
| `do_nothing` | `+0.0000 +- 0.0000` | `+0.0000 +- 0.0000` | `+0.0000 +- 0.0000` (`0/100/0`) | `0.0%` / `0.0%` | `0.0%` / `0.0%` | `100.0%` | `+0.5521 +- 0.0612` | `+0.6053 +- 0.0300` |
| `stop_early` | `+0.0000 +- 0.0000` | `+0.0000 +- 0.0000` | `+0.0000 +- 0.0000` (`0/100/0`) | `0.0%` / `0.0%` | `0.0%` / `0.0%` | `100.0%` | `+0.5521 +- 0.0612` | `+0.6053 +- 0.0300` |
| `blind_seat_0` | `-0.9600 +- 0.0552` | `-0.9600 +- 0.0552` | `+0.0000 +- 0.0000` (`0/100/0`) | `2.0%` / `3.0%` | `2.0%` / `3.0%` | `100.0%` | `+1.5121 +- 0.0824` | `+1.5653 +- 0.0629` |
| `accuse_most_talkative` | `-1.0000 +- 0.0000` | `-1.0000 +- 0.0000` | `+0.0000 +- 0.0000` (`0/100/0`) | `0.0%` / `100.0%` | `0.0%` / `99.0%` | `99.0%` | `+1.5521 +- 0.0612` | `+1.6053 +- 0.0300` |
| `accuse_authority_role` | `-0.9815 +- 0.0363` | `-0.9815 +- 0.0363` | `+0.0000 +- 0.0515` (`1/98/1`) | `1.0%` / `22.0%` | `1.0%` / `20.0%` | `60.0%` | `+1.5336 +- 0.0740` | `+1.5868 +- 0.0454` |
| `accuse_first_named_anchor` | `-1.0000 +- 0.0000` | `-0.9415 +- 0.0655` | `+0.0585 +- 0.0655` (`3/97/0`) | `0.0%` / **`4.0%`** | `3.0%` / **`36.0%`** | `5.0%` | `+1.5521 +- 0.0612` | `+1.5468 +- 0.0685` |
| `accuse_lexical_hedging` | `-0.9815 +- 0.0363` | `-0.9415 +- 0.0655` | `+0.0400 +- 0.0755` (`3/96/1`) | `1.0%` / `5.0%` | `3.0%` / `9.0%` | `65.0%` | `+1.5336 +- 0.0707` | `+1.5468 +- 0.0690` |
| `log_volume_outlier` | `-0.9635 +- 0.0503` | `-0.9635 +- 0.0503` | `+0.0000 +- 0.0515` (`1/98/1`) | `2.0%` / `79.0%` | `2.0%` / `72.0%` | `81.0%` | `+1.5156 +- 0.0776` | `+1.5688 +- 0.0568` |
| `one_interview_accuse` | `-1.0000 +- 0.0000` | `-1.0000 +- 0.0000` | `+0.0000 +- 0.0000` (`0/100/0`) | `0.0%` / `3.0%` | `0.0%` / `3.0%` | `100.0%` | `+1.5521 +- 0.0612` | `+1.6053 +- 0.0300` |
| **`reference_solver`** | **`+0.5521 +- 0.0612`** | **`+0.6053 +- 0.0300`** | **`+0.0532 +- 0.0627` (`39/30/31`)** | **`96.0%` / `0.0%`** | **`99.0%` / `0.0%`** | **`95.0%`** | baseline | baseline |

## 4. Lexical Shortcut, Secret-Token & Stream-Coupling Differential Audit (`600` Passive Scan Episodes, Seeds `0..99`)

### 4.1 Secret Hygiene, Lexical Token Lift & Zero-Knob Parity

Across `300` paired full-horizon worlds (`600` passive episodes, `15,003` social messages, and `2,167` misforwarded documents on `v1.5`):

| Metric | `easy` (`n=12`, Seeds `0..99`) | `medium` (`n=20`, Seeds `0..99`) | `hard` (`n=40`, Seeds `0..99`) |
|---|---|---|---|
| Zero-knob parity (`v1.5` social OFF vs `v1.4` exact match) | `5/5` (`True`) | `5/5` (`True`) | `5/5` (`True`) |
| Social ON + `p_misforward=0.0` leak/log stream parity vs `v1.4` | `5/5` (`True`) | `5/5` (`True`) | `5/5` (`True`) |
| Social messages scanned (`v1.5`) | `4,307` | `4,335` | `6,361` |
| Misforwarded docs scanned (`v1.5`) | `631` | `575` | `961` |
| Literal `"mole"` word leaks in messages/docs | `0` | `0` | `0` |
| `world_seed` / secret-token leaks | `0` | `0` | `0` |
| Significant positive sender-token mole leaks (99% lower CI `> 1.25x` prior) | `0` | `0` | `0` |
| Significant positive target-token mole leaks (99% lower CI `> 1.25x` prior) | `0` | `0` | `0` |
| Unconditional mole prior `1/N` | `0.083333` | `0.050000` | `0.025000` |
| `P(mole | social message sender)` | `0.094962 +- 0.008755` (`409/4,307`) | `0.051211 +- 0.006562` (`222/4,335`) | `0.030184 +- 0.004205` (`192/6,361`) |
| **`P(mole | rumour target)`** | **`0.051491 +- 0.008163`** (`145/2,816`) | **`0.025321 +- 0.005815`** (`71/2,804`) | **`0.014779 +- 0.003652`** (`62/4,195`) |
| **`P(decoy | rumour target)`** | `0.000000` (no decoy) | **`0.441512 +- 0.018380`** (`1,238/2,804`) | **`0.406436 +- 0.014863`** (`1,705/4,195`) |
| `P(mole | Day-3 authority target)` | `0.080000 +- 0.053173` (`8/100`) | `0.030000 +- 0.033435` (`3/100`) | `0.010000 +- 0.019502` (`1/100`) |
| `P(decoy | Day-3 authority target)` | `0.000000` (`0/100`) | **`0.500000 +- 0.098000`** (`50/100`) | **`0.390000 +- 0.095599`** (`39/100`) |
| **`P(decoy | grudge participant)`** | `0.000000` (`0/400`) | **`0.000000`** (`0/400`) | **`0.000000`** (`0/400`) |
| **`P(mole | top-named social target)`** | `0.080000 +- 0.053173` (`8/100`) | **`0.000000`** (`0/100`) | **`0.000000`** (`0/100`) |
| **`P(decoy | top-named social target)`** | `0.000000` (`0/100`) | **`0.950000 +- 0.042717`** (`95/100`) | **`0.990000 +- 0.019502`** (`99/100`) |
| Day-1 empty `self._held` set changed (`p_misforward=0.15`) | `6.0% +- 4.65%` (`6/100`) | `11.0% +- 6.13%` (`11/100`) | `17.0% +- 7.36%` (`17/100`) |
| **Paired leak sequence diverged (`v1.4` vs `v1.5`)** | **`93.0% +- 5.00%`** (`93/100`) | **`82.0% +- 7.53%`** (`82/100`) | **`96.0% +- 3.84%`** (`96/100`) |
| **Paired access-log stream diverged (`v1.4` vs `v1.5`)** | **`100.0% +- 0.00%`** (`100/100`) | **`98.0% +- 2.74%`** (`98/100`) | **`100.0% +- 0.00%`** (`100/100`) |

### 4.2 Why `v1.5` Human-Bias Text Creates Zero Positive Shortcut for Simple Heuristics

1. **Sender-level hedging and talkativeness are diluted or decoy-trapped:** Every `v1.5` rumour/authority/grudge template contains speculative hedging (`"Not saying ... for sure"`, `"Could be"`, `"haven't verified"`, `"No hard proof"`, `"Wouldn't surprise me"`), but senders are drawn uniformly among non-targets (`P(mole | social sender) = 0.0950` vs `0.0833` on `easy`, `0.0512` vs `0.0500` on `medium`, `0.0302` vs `0.0250` on `hard`). Attributing hedged language to speakers (`accuse_lexical_hedging`) adds uniform noise that degrades accuracy on `easy` (`19.0% -> 15.0%`) and `medium` (`6.0% -> 2.0%`), while `accuse_most_talkative` remains `97.0%-99.0%` trapped by the angry decoy on `medium`/`hard`.
2. **Target-level anchoring is anti-correlated with the mole:** Because `seed_rumour` (`rumour_frame_share = 0.4`) targets `decoy` on `medium`/`hard` and a non-mole `random_peer` on `easy`, `accuse_first_named_anchor` shifts from `mean_day = 4.00` (general `{other} is covering` chatter in `v1.4`) to `mean_day = 2.02-2.04` (Day-1 `rumour:` / `grudge:` in `v1.5`), increasing decoy false accusations by `+23.0 pp` (`medium`) and `+32.0 pp` (`hard`) while keeping mole accuracy at `2.0%-3.0%`.
3. **Why `reference_solver` moved `+0.0526` (`medium`) and `+0.0532` (`hard`) on seeds `0..99`:** `SolverPolicy` ingests `0` social messages in live play (`decoy_queries()` only searches `ANGER_WORDS`), and when `p_misforward` is set to `0.0` (with rumours, grudges, and Day-3 authority still active), `reference_solver` scores match `v1.4` `100%` (`0` differences). The `+0.05` shift under full `v1.5-candidate` comes strictly from `p_misforward=0.15` expanding `self._held` and shifting `self._dyn` leak/log draws (`ISS-DIFF-03`), producing symmetric `39/40/21` (`medium`) and `39/30/31` (`hard`) win/tie/loss dispersion across `100` seeds rather than any lexical shortcut.

## 5. Issues-Only Findings for Silas (Zero Protected Edits)

1. **`ISS-DIFF-01` (Medium, Statistical Inversion Side-Channel): Rumour & Authority Target Anti-Correlation (`P(mole | rumour target) < 1/N`, Top-Named Target = `95%-99%` Decoy).**
   - **Location:** `canary/env.py:376-407`, `canary/mole/dsl.py:169-174` (`origin/justSilas-v15 @ de9cc50e`).
   - **Evidence:** Seeded rumours (`40%`) never target the mole (`P(mole | rumour target) = 0.0515`, `0.0253`, `0.0148` vs priors `0.0833`, `0.0500`, `0.0250` on `easy`, `medium`, `hard`). Over seeds `0..99`, the top-named social target is the true mole on `0/100` (`0.0%`) of `medium` and `hard` episodes and is the true decoy on `95/100` (`medium`) and `99/100` (`hard`).
   - **Suggested Direction (Report-Only):** Sample focal office gossip targets from a mole-blind prior over all `self._ids` (including the mole at `1/N`) unless an evolved mole pays an observable/costed DSL trade-off.

2. **`ISS-DIFF-02` (Medium, Structural Exclusion Side-Channel): `Env._grudges()` Excludes `decoy` (`P(decoy | grudge participant) = 0.0%`).**
   - **Location:** `canary/env.py:367-374` (`origin/justSilas-v15 @ de9cc50e`).
   - **Evidence:** `pool = [e for e in self._ids if e != self._world.decoy]` guarantees `0/400` (`0.0%`) grudge participants are the decoy across seeds `0..99` on both `medium` and `hard`.
   - **Suggested Direction (Report-Only):** Draw grudge pairs uniformly from `list(self._ids)` without excluding `self._world.decoy`.

3. **`ISS-DIFF-03` (Low-Medium, Paired-Stream Coupling vs Code Comment): `p_misforward=0.15` Perturbs `self._dyn` Leak and Access-Log RNG Streams.**
   - **Location:** `canary/env.py:356-365, 625-668` (`origin/justSilas-v15 @ de9cc50e`).
   - **Evidence:** Lines `356-357` state `"with them ON the leak/log streams are still unchanged"`. While true for `rumour_rate`, `grudge_rate`, and `authority_day` alone (`5/5` exact leak/log stream matches per tier when `p_misforward=0.0`), `p_misforward=0.15` appends `forwarded_to` into `self._held[x]` (`day1_empty_held` changes on `6%` `easy`, `11%` `medium`, `17%` `hard` of seeds `0..99`), altering `_mole_view` `leakable` lists and `rng.choice(held)` bit consumption on `self._dyn`. Consequently, leak sequences diverge on `93%` (`easy`), `82%` (`medium`), and `96%` (`hard`) of paired episodes and access-log streams diverge on `100%`, `98%`, and `100%`.
   - **Suggested Direction (Report-Only):** Update the `canary/env.py` comment to note that `p_misforward > 0` intentionally changes `self._held` (and thus downstream leak/access-log draws), or isolate per-employee daily access-log RNG streams (`f"{world_seed}:log:{day}:{emp}"`) if strict cross-version noise pairing is desired in `v1.6`.

4. **`ISS-DIFF-04` (Low-Medium, Surface Format Tell): Structured Social Subjects (`rumour: eXX`, `unverified accusation: eXX`, `grudge: eXX`) and `-s` Message IDs.**
   - **Location:** `canary/text/template.py:221-231` (`origin/justSilas-v15 @ de9cc50e`).
   - **Evidence:** Explicit `e\d{2}` IDs and prefix tags shift `accuse_first_named_anchor` from `mean_day = 4.00` (`v1.4`) to `mean_day = 2.02-2.04` (`v1.5`) and allow 1-call substring filtering of all social chatter without reading natural-language bodies.
   - **Suggested Direction (Report-Only):** Merge social messages into standard `m{day}-{idx}` numbering and naturalistic workplace subjects in `v1.6`.

5. **`ISS-DIFF-05` (Low, Offline Transcript Attribution Mismatch in `v1.4` and `v1.5`): `SolverPolicy._ingest` Checks Literal `"evasive"` Against `TemplateProvider` Answers.**
   - **Location:** `canary/solver/policy.py:210-211` (`v1.4` `justSilas @ 9225f2ad`), `canary/solver/policy.py:217-218` (`v1.5` `de9cc50e`), and `canary/text/template.py:59-108`.
   - **Evidence:** Across the `32` `TemplateProvider` interview templates (`16` evasive, `16` cooperative), `0/16` evasive templates contain the literal substring `"evasive"` (`solver_v14_marks_template_evasive = False`, `solver_v15_marks_template_evasive = False`), whereas `13/16` (`81.25%`) match simple conversational hedge phrases with `0/16` (`0.0%`) cooperative false positives. Live `SolverPolicy` never calls `interview`, and live `Env` reward integrity is unaffected (`interview_lr <= 1.5` keeps `one_interview_accuse` at `-0.7800` to `-1.0000`), but offline replay in `canary.solver.regret` / `canary.analysis.accuse` treats all `TemplateProvider` interviews in LLM transcripts as cooperative (`evasive=False`).
   - **Suggested Direction (Report-Only):** If offline regret attribution should credit `interview` evidence on `TemplateProvider` episodes, classify `TemplateProvider` evasive templates (or record public template polarity) in `canary/analysis` rather than checking `"evasive" in sig` alone.
