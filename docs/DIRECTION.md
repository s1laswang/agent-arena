# Team direction (set by the coordinator, Fri 13 Nov 23:25)

Silas wants this to be genuinely ambitious and scalable, not a neat demo. Full research: docs/research.md (pass 2 "Three ambitious visions" at the top).

## The product: Open Trade Agent Profile (OTAP)
An open, documented profile any European supplier or wholesaler can implement so external AI buyer agents can discover, quote, order and get approval safely. Valio Aimo's gateway is the reference implementation.
Building blocks (reuse, do not invent): MCP (and an A2A agent card) for agent access, OpenAPI for HTTP, GS1 GTIN product identity, Peppol BIS Order / Order Response semantics for order and response documents, JWS-signed fixed-price quotes with expiry, AP2-style mandates / W3C Verifiable Credentials for "which company's agent, under which limits", and a hash-chained append-only audit log.
Discovery: a wholesaler publishes a manifest (e.g. /.well-known/otap.json) listing capabilities, endpoints, signing keys and policies.

## What must work end to end (30% of score, non-negotiable)
Buyer request -> search/lookup (real mock price + availability APIs) -> signed quote -> mandate/policy check -> auto-order OR pending_approval -> human approves that exact quote -> Peppol-style order response -> audit trail + evidence pack.
Demo story: "1,000 L lactose-free milk by Monday" with partial availability, split plan and good-better-best substitutes (out-of-preference substitute stops for a human); one allergen-safe moment (missing allergen data = unknown, never safe); one prompt-injection in supplier text that gets blocked.

## Openness proof
A second toy wholesaler implementing the same profile (different synthetic catalog subset). The same buyer agent orders from it with zero code changes. A conformance test runner checks any implementation against the profile.

## Scale proof: agent market wind tunnel on FR8
Thousands of simulated buyer agents (varied mandates, kitchens, needs), hostile supplier text, stock-out and price shocks run against the gateway on the FR8 "freighter" cluster (ssh freighter, Slurm). Output: hard numbers for the pitch (orders/s, % correctly escalated, injection block rate, mandate violations caught, substitution acceptability).
FR8 rules: ssh freighter, Slurm. CPU partition `normal` (3 idle nodes, 48+ cores) is free to use. GPU partition `gpu`: compute03/04 have 4x Tesla V100 32GB each; request 1 GPU per job (--gres=gpu:1, no fast interconnect), use AMP, and only with Silas's approval because his own `sky` jobs currently hold all 8 GPUs. NEVER cancel, requeue or touch other jobs. Always set --time (default kill after 1 h, max 24 h); never run heavy work on the login node. Code in ~/junction-aimo/ on freighter; data, models, outputs and logs in /data/silas/junction-aimo/ (/home is 92-94% full); copy hot data to $SCRATCH at job start and copy results back. Software: module load pytorch-volta (PyTorch 2.5.1, CUDA 12.6, transformers/accelerate/peft); no system CUDA. Monitor: squeue -u silas, sacct -j <id>.

## Cut list
Anything that does not serve the live end-to-end demo, the openness proof or the wind tunnel numbers. No negotiation (prices are fixed).
