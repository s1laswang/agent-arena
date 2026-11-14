"""WS3 charts: CPU RL mole training curve + GRPO LLM mole curves (FR8 44424-44426). -> results/ws3_*.png"""
import json
from pathlib import Path
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt


def smooth(xs, k=10):
    return [sum(xs[max(0, i - k + 1):i + 1]) / len(xs[max(0, i - k + 1):i + 1]) for i in range(len(xs))]


Path("results").mkdir(exist_ok=True)
c = [json.loads(l) for l in open("data/rl_mole/curve.jsonl")]
fig, ax = plt.subplots(figsize=(7, 4))
it = [r["iter"] for r in c]
for k, lab in (("solver_score", "solver"), ("grok_tactics_score", "grok_tactics"), ("hinted_heuristic_score", "hinted_heuristic"), ("solver_acc", "solver accuracy")):
    ax.plot(it, smooth([r[k] for r in c]), label=lab, ls="--" if k == "solver_acc" else "-")
ax.axhline(0.75, color="gray", lw=0.8, ls=":", label="catchability floor 0.75")
ax.set(xlabel="iteration (48 train seeds each)", ylabel="score / accuracy (10-iter mean)", title="CPU RL mole (REINFORCE), hard tier")
ax.legend(fontsize=8); fig.tight_layout(); fig.savefig("results/ws3_rl_mole_curve.png", dpi=130)

fig, axs = plt.subplots(1, 2, figsize=(10, 4))
for j, s in ((44424, 0), (44425, 1), (44426, 2)):
    rows = [json.loads(l) for l in open(f"data/grpo_mole/curve-{j}.jsonl")]
    st = [r["step"] for r in rows]
    axs[0].plot(st, smooth([r["valid"] for r in rows], 20), label=f"seed {s} valid fraction")
    vr = [(r["reward"] + (1 - r["valid"])) / r["valid"] if r["valid"] > 0 else float("nan") for r in rows]
    axs[1].plot(st, smooth([x for x in vr], 20), label=f"seed {s}")
axs[0].set(xlabel="GRPO step", title="Qwen2.5-0.5B mole: valid action JSON"); axs[0].legend(fontsize=8)
axs[1].set(xlabel="GRPO step", title="reward among valid completions (flat)"); axs[1].legend(fontsize=8)
fig.tight_layout(); fig.savefig("results/ws3_grpo_mole_curves.png", dpi=130)
print("wrote results/ws3_rl_mole_curve.png results/ws3_grpo_mole_curves.png")
