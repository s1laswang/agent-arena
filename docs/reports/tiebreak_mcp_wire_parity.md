# Deterministic Keyless MCP Wire-JSON Equivalence Adapter & Parity Audit (`v1.4`)

Keyless offline audit proving that all `4` verified Canary compact non-LLM policies (`CompactLinearDAggerPolicy`, `TinyMLPPolicy`, `ScalingLogisticPolicy`, `EmpiricalBayesPolicy`) operate purely on JSON-serialized responses of the `13` public MCP tools (`0` Python object attribute leaks, `0` shared `Env` references, `0` `canary.world` / `canary.solver` inference imports) with **`360/360` (`100.0%`) bit-identical tool call sequences and episode rewards** vs direct `Env` execution on world-paired `HELDOUT_SEEDS 800000..800029` (`n=90` per policy, `30`/tier, `world_secret_tag` `sha256:ebf2f09716cf76d3`).

- **Seed & Secret Provenance (Panel Fix A)**: All `360` primary parity episodes (`720` `Env` rollouts + `360` fresh `Env` replays) strictly evaluate world-paired `HELDOUT_SEEDS 800000..800029` under shared `sha256:ebf2f09716cf76d3`, all policy weights come strictly from disjoint `TRAIN_SEEDS [100000, 200000)`, the synthetic taint-stripping probe uses only `TRAIN_SEEDS 106500..106502`, and **`0` `JUDGE_SEEDS` (`900k+`) are touched**. Where `DEV_SEEDS 0..29` appear in separate Canary frontier reports, they are **post-hoc locked, not pre-registered**.
- **Strict Track Separation (Panel Fix E)**: `0 / 19` historical open-weight `Qwen2.5` runs in `experiment_ledger.json` exceed untrained `base` (`0.000`), so the `README.md` Qwen addendum remains withheld (`HOLD_README_QWEN_ADDENDUM_UNTIL_V100`). All `4` policies audited here are non-LLM structured/neural policies (`is_open_weight_llm = False`) strictly separated from open-weight `Qwen2.5` LoRA runs.

## 1. MCP Wire-JSON Equivalence Boundary Architecture (`MCPWireServerBoundary` + `Wire*Policy`)

In Harbor and `canary.mcp_server`, an investigator communicates with `Env` exclusively over JSON-RPC 2.0 `initialize`, `tools/list`, and `tools/call` frames (`TextContent` JSON `{ok, data, error}`). `scripts/tiebreak_mcp_wire_parity.py` enforces two independent, composable JSON wire boundaries:

1. **Transport Boundary (`MCPWireServerBoundary` + `MCPWireClientAdapter`)**: Wraps `Env` behind a `str -> str` JSON-RPC 2.0 handler (`allow_nan=False`, zero custom serializer hooks). The client holds no reference to `Env`; it parses `instructions` from `initialize`, verifies that `tools/list` exposes the exact `13` public MCP tools (`status, list_employees, list_documents, read_access_logs, search_messages, read_message, interview, plant_canary, check_leak_feed, restrict_access, unrestrict_access, advance_day, accuse`), serializes every `(tool, args)` call to JSON text, parses `CallToolResult.content[0].text` (`json.loads(json.dumps(obs))`), verifies `structuredContent` and `isError` parity, scans every wire frame for forbidden server keys (`mole`, `_world`, `world_seed`, `ledger`, `verdict`, `true_V`, unsurfaced leaks), and records observations in slotted `WireStep` objects (`__slots__ = ('t', 'day', 'tool', 'args', 'result')`, no `__dict__`).
2. **Policy Inference Boundary (`WireCompactLinearDAggerPolicy`, `WireTinyMLPPolicy`, `WireScalingLogisticPolicy`, `WireEmpiricalBayesPolicy`)**: AST-isolated `Policy` subclasses that round-trip `tools_spec`, `instruction`, incremental `history` steps, and outgoing `(tool, args)` through strict `json.loads(json.dumps(..., allow_nan=False))` before `super().reset(...)` and `super().act(...)`, stripping any Python subclass attributes or extra envelope keys even when invoked directly via `canary.eval.run_episode`.

## 2. Headline Held-Out Parity Summary (`HELDOUT_SEEDS 800000..800029`, `n=90` / Policy, `360` Total)

| Policy (`run_id`) | Wire Adapter Class | Params | Train Seeds | Direct `Env` Score (`95% CI`) | MCP Wire Score (`95% CI`) | Tool-Seq Parity | Bit-Identical Reward | Max `|Delta|` | Wire Calls / KiB | Fresh Replay |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| `CompactLinearDAggerPolicy` (`compact-linear-dagger-v14`) | `WireCompactLinearDAggerPolicy` | `785` | `109000..109509` | `+0.6632 [+0.6071, +0.7194]` | `+0.6632 [+0.6071, +0.7194]` | **`90/90 (100.0%)`** | **`90/90 (100.0%)`** | `0.00000` | `4,696` / `8,831.1 KiB` | `90/90` |
| `TinyMLPPolicy` (`tiny-mlp-dagger-v14`) | `WireTinyMLPPolicy` | `12,293` | `107000..107599` | `+0.6292 [+0.5649, +0.6935]` | `+0.6292 [+0.5649, +0.6935]` | **`90/90 (100.0%)`** | **`90/90 (100.0%)`** | `0.00000` | `5,009` / `7,636.2 KiB` | `90/90` |
| `ScalingLogisticPolicy` (`scaling-logistic-v14`) | `WireScalingLogisticPolicy` | `82` | `107000..108999` | `+0.6107 [+0.5420, +0.6794]` | `+0.6107 [+0.5420, +0.6794]` | **`90/90 (100.0%)`** | **`90/90 (100.0%)`** | `0.00000` | `3,707` / `9,023.4 KiB` | `90/90` |
| `EmpiricalBayesPolicy` (`empirical-bayes-v14`) | `WireEmpiricalBayesPolicy` | `11` | `102000..102779` | `+0.6223 [+0.5726, +0.6721]` | `+0.6223 [+0.5726, +0.6721]` | **`90/90 (100.0%)`** | **`90/90 (100.0%)`** | `0.00000` | `5,287` / `12,710.5 KiB` | `90/90` |
| **Pooled Total (`4` Policies)** | `4` `Wire*Policy` adapters | n/a | `102000..109509` | `+0.6314` | `+0.6314` | **`360/360 (100.0%)`** | **`360/360 (100.0%)`** | `0.00000` | `18,699` / `38,201.2 KiB` | `360/360` |

## 3. Per-Tier Breakdown (`easy`, `medium`, `hard`, `30` Held-Out Seeds / Tier / Policy)

| Policy | Tier (`n=30`) | Direct Score (`95% CI`) | MCP Wire Score (`95% CI`) | Accuracy | Wrong / Abstain | Mean Calls / Mean Wire Bytes | Seq & Reward Parity | Trace Digest (`sha256[:16]`) |
|---|---|---:|---:|---:|---:|---:|---:|---|
| `CompactLinearDAggerPolicy` | `easy` | `+0.8203 [+0.7961, +0.8446]` | `+0.8203 [+0.7961, +0.8446]` | `1.000` | `0.000` / `0.000` | `23.8` / `38,447.0 B` | `30/30` & `30/30` | `0xdfc26eb65a3bf6c7` |
| `CompactLinearDAggerPolicy` | `medium` | `+0.6790 [+0.6024, +0.7556]` | `+0.6790 [+0.6024, +0.7556]` | `0.933` | `0.000` / `0.067` | `55.2` / `91,776.5 B` | `30/30` & `30/30` | `0xc677626e4fe33726` |
| `CompactLinearDAggerPolicy` | `hard` | `+0.4903 [+0.3666, +0.6140]` | `+0.4903 [+0.3666, +0.6140]` | `0.967` | `0.033` / `0.000` | `77.5` / `171,210.0 B` | `30/30` & `30/30` | `0x9144f06994a2bd2d` |
| `TinyMLPPolicy` | `easy` | `+0.8107 [+0.7795, +0.8418]` | `+0.8107 [+0.7795, +0.8418]` | `1.000` | `0.000` / `0.000` | `29.2` / `39,099.6 B` | `30/30` & `30/30` | `0x7fc982e35a5748af` |
| `TinyMLPPolicy` | `medium` | `+0.5840 [+0.5006, +0.6674]` | `+0.5840 [+0.5006, +0.6674]` | `0.900` | `0.000` / `0.100` | `68.4` / `95,955.2 B` | `30/30` & `30/30` | `0x100f43d769a371d2` |
| `TinyMLPPolicy` | `hard` | `+0.4930 [+0.3411, +0.6449]` | `+0.4930 [+0.3411, +0.6449]` | `0.933` | `0.067` / `0.000` | `69.4` / `125,594.0 B` | `30/30` & `30/30` | `0x65295c26b4471179` |
| `ScalingLogisticPolicy` | `easy` | `+0.8127 [+0.7956, +0.8297]` | `+0.8127 [+0.7956, +0.8297]` | `1.000` | `0.000` / `0.000` | `20.0` / `38,267.5 B` | `30/30` & `30/30` | `0xa97273fede7b80dc` |
| `ScalingLogisticPolicy` | `medium` | `+0.5573 [+0.4146, +0.7001]` | `+0.5573 [+0.4146, +0.7001]` | `0.833` | `0.033` / `0.133` | `42.6` / `95,246.1 B` | `30/30` & `30/30` | `0xabcae8cde909b828` |
| `ScalingLogisticPolicy` | `hard` | `+0.4620 [+0.3433, +0.5807]` | `+0.4620 [+0.3433, +0.5807]` | `0.933` | `0.033` / `0.033` | `60.9` / `174,485.2 B` | `30/30` & `30/30` | `0x9f72a36a5be29142` |
| `EmpiricalBayesPolicy` | `easy` | `+0.7287 [+0.6499, +0.8075]` | `+0.7287 [+0.6499, +0.8075]` | `0.933` | `0.000` / `0.067` | `37.1` / `64,502.4 B` | `30/30` & `30/30` | `0x9ff4b2d837952d36` |
| `EmpiricalBayesPolicy` | `medium` | `+0.5697 [+0.4608, +0.6785]` | `+0.5697 [+0.4608, +0.6785]` | `0.800` | `0.000` / `0.200` | `65.4` / `142,011.1 B` | `30/30` & `30/30` | `0x1d8a41417e21ccd8` |
| `EmpiricalBayesPolicy` | `hard` | `+0.5687 [+0.5188, +0.6185]` | `+0.5687 [+0.5188, +0.6185]` | `1.000` | `0.000` / `0.000` | `73.7` / `227,339.0 B` | `30/30` & `30/30` | `0x003b9f2e0dc78a96` |

## 4. Public 13-Tool Surface, Anti-Leakage Telemetry, Taint-Stripping & AST Isolation Gates

| Security / Equivalence Gate | Scope Audited | Result | Details |
|---|---|---|---|
| Public 13-Tool MCP Schema Surface | `360` `tools/list` handshakes | **`360/360 (100.0%)`** | Exact 13 public MCP tools advertised; `0` hidden `verdict`/`ledger`/`peek_status` endpoints |
| Wire Payload Anti-Leakage Scan | `18,699` `tools/call` frames + `360` init frames | **`0` leaks** | `0` `mole`/`_world`/`world_seed`/`ledger`/`true_V` keys; `0` unsurfaced leaks (`surfaced_day > day`) |
| Python Reference Disjointness | `360` `Env` vs `WireStep` graphs | **`0` shared refs** | `id(...)` intersection between server `Env` mutable containers and client `WireStep`s is empty |
| Tainted-Subclass & Rogue-Key Stripping | `12` `TRAIN_SEEDS` (`106500..106502`) red-team probes + `4` type traps | **`12/12 (100.0%)`** | Strips custom `Step`/`dict` `.mole`/`._world` attrs and rogue envelope keys; rejects `object()`, `NaN`, `Inf` |
| Strict AST Inference Isolation | `11` modules, `14` policy classes (incl. `4` `Wire*Policy`) | **`PASS` (`0` leaks)** | `check_ast_inference_isolation(..., extra_paths=[Path('scripts/tiebreak_mcp_wire_parity.py')], strict=True)` |

### Public MCP Tool Invocation Distribution Across All `360` Held-Out Wire Episodes

| MCP Tool | `CompactLinearDAgger` | `TinyMLP` | `ScalingLogistic` | `EmpiricalBayes` | Pooled Calls (`360` Eps) |
|---|---:|---:|---:|---:|---:|
| `status` | `685` | `695` | `90` | `719` | `2,189` |
| `list_employees` | `90` | `90` | `90` | `90` | `360` |
| `list_documents` | `685` | `695` | `718` | `719` | `2,817` |
| `read_access_logs` | `510` | `605` | `544` | `629` | `2,288` |
| `search_messages` | `508` | `180` | `0` | `360` | `1,048` |
| `read_message` | `0` | `0` | `0` | `0` | `0` |
| `interview` | `0` | `515` | `0` | `462` | `977` |
| `plant_canary` | `848` | `839` | `919` | `870` | `3,476` |
| `check_leak_feed` | `685` | `695` | `628` | `719` | `2,727` |
| `restrict_access` | `0` | `0` | `0` | `0` | `0` |
| `unrestrict_access` | `0` | `0` | `0` | `0` | `0` |
| `advance_day` | `597` | `608` | `633` | `637` | `2,475` |
| `accuse` | `88` | `87` | `85` | `82` | `342` |

## 5. Offline Reproduction & Fast Verification Commands

```bash
python scripts/tiebreak_mcp_wire_parity.py --check
pytest -q tests/test_tiebreak_mcp_wire_parity.py
python scripts/verify_tiebreak_submission.py --strict
```
