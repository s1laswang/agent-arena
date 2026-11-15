# Canary Arena

Static pixel-art game for the Canary env (index.html, js/, assets/, data/). Open index.html directly or serve the folder on GitHub Pages. No server, no keys, no network.

Modes: Duel vs Gemini (replays data/gemini-N.json, the committed run on the same seed), Be the Mole (hunter ported from the heuristic baseline), Living Office (preview, not in the judged env).

Data: data/*.json are extracted from the committed episode files; js/data.js is the same data bundled so file:// works. Sources are cited on the end screen. Art: Kenney.nl (CC0), see ASSETS.md.

Engine: js/engine.js re-implements the hard-tier rules from canary/rules.py (leak chance 0.65, delay 2 or 3 days, fingerprint 95%, canary cost 0.01, leak damage 0.05). Leaks in your own duel run are simulated, they are not Gemini's leaks.
