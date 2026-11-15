#!/usr/bin/env bash
# WS4 v3 tiebreaker readout (read-only): builds fr8/analysis/out/ws4_table_v3.md from whatever eval runs are present.
# Rows: base / v1 / v2 (+ Verda off30) / v3-4k-s0 (Verda H100) / v3-8k-sN (Verda) / v3-4k-s1 (FR8 44572, if pulled).
# Seeds never pooled across v3 seeds; one model's runs on disjoint held-out seed ranges are pooled (first (tier,seed) wins).
# Env (labels only): S0_STEPS, S1_STEPS, K8S1_STEPS, K8S2_STEPS, K8S1_GPU, K8S2_GPU, FR8_S1_DIR
#   bash fr8/analysis/ws4_v3_readout.sh [OUT.md]
set -euo pipefail
cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
OUT=${1:-fr8/analysis/out/ws4_table_v3.md}
W=data/fr8/ws4; J=data/fr8/j4/run-44397/runs
have() { [ -s "$1/episodes.jsonl" ]; }
# a bare NAME (no "/") is searched for under any Verda box dir: data/fr8/verda/{runs,*/runs,*}/NAME
find_run() { local d; for d in data/fr8/verda/runs/$1 data/fr8/verda/*/runs/$1 data/fr8/verda/*/$1; do have "$d" && { echo "$d"; return; }; done; }
pool() { local out="" d; for d in "$@"; do [[ $d == */* ]] || d=$(find_run "$d"); [ -n "$d" ] && have "$d" && out="${out:+$out,}$d"; done; echo "$out"; }
ARGS=(); INFO=()
add() { local label=$1 info=$2; shift 2; local dirs; dirs=$(pool "$@"); [ -n "$dirs" ] || return 0
        ARGS+=("$label=$dirs"); INFO+=(--info "$label=$info"); }
add base     "V100 · Qwen2.5-1.5B-Instruct, 0 steps · 4k"          $W/ws4-base-v14 $W/ws4-base-v14-off6
add v1       "V100 · J4 SFT LoRA 44397 · 4k"                        $J/eval-lora $J/eval-lora-par
add v2       "V100 SFT LoRA 44410 (eval V100 + A100 68bbe201 off30) · 4k" $W/ws4-v2-44410 v2-off30
add v3-4k-s0 "H100 · ${S0_STEPS:-609} GRPO steps · 4k"              v3-verda-s0 v3-4k-s0-off30
[ -n "${FR8_S1_DIR:-}" ] && add v3-4k-s1 "V100 (FR8 44572) · ${S1_STEPS:-?} GRPO steps · 4k · partial" "$FR8_S1_DIR"
add v3-8k-s1 "${K8S1_GPU:-A100-80} · ${K8S1_STEPS:-?} GRPO steps · 8k" v3-verda-8k-s1
add v3-8k-s2 "${K8S2_GPU:-H100} · ${K8S2_STEPS:-?} GRPO steps · 8k"    v3-verda-8k-s2
python3 -m fr8.analysis.ws4_table "${ARGS[@]}" --pair base,v2,v3-4k-s0 "${INFO[@]}" --out "$OUT" >/dev/null
# Bar: v3 held-out mean > 0 with the 95% CI excluding 0 (all-tier row).
python3 - "$OUT" <<'EOF'
import sys
rows = [l.split("|")[1:-1] for l in open(sys.argv[1]) if l.startswith("| v3") and "| all |" in l]
lines = []
for r in rows:
    m, h = (float(x) for x in r[5].replace("−", "-").split("±"))
    lines.append(f"- {r[0].strip()}: {m:+.3f} ± {h:.3f} (n={r[4].strip()}) → bar {'MET' if m - h > 0 else 'NOT met'}")
txt = "\n**Bar (v3 held-out mean > 0, 95% CI excludes 0):**\n" + ("\n".join(lines) or "- no v3 rows yet") + "\n"
open(sys.argv[1], "a").write(txt)
EOF
cat "$OUT"
