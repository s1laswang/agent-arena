# Failure gallery

    python -m canary.analysis.gallery --runs data/runs/committed/<agent> [--tier hard] [--out data/analysis]

Writes gallery.json and gallery.md from episodes.jsonl using canary.solver.regret.attribute. One entry per label: count, episodes_with, the decision, the worst example (agent, tier, seed, day, step, tool, args, solver belief then, regret, what went wrong).

Self-check, exit code 1 on failure: every losing episode (score < 1) has at least one label, every label has an example. Unlabelled losses are listed by agent, tier and seed: add a tag for them in canary/analysis/tags.py WHY and canary/solver/regret.py.

On codex:gpt-5.5 committed runs (10 episodes) it finds 3 labels and 4 unlabelled losses, so the self-check currently fails there.
