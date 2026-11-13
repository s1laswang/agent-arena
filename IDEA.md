# The idea (start here)

**Challenge:** Valio Aimo "Trusted Trade Agents" (Junction 2026). Full brief in `CHALLENGE.md`.
Judging: end-to-end demo 30%, real need 20%, autonomy and controls 20%, robustness 15%, openness 15%.
Deadlines: preliminary submission Fri 13 Nov 23:59, final Sun 15 Nov 10:00 (Helsinki).

## One-liner
An open standard, plus its reference implementation, that lets any company's AI buying agent safely discover, quote, order and get human approval from any European food wholesaler. Valio Aimo is the first implementation.

## Why it matters
Restaurant and kitchen buyers will soon send AI agents to do their ordering. Today every wholesaler would need a custom, unsafe integration for every agent. Nothing proves which company's agent is acting, under what limits, at what agreed price, or who approved it. We fix that layer for the whole industry, not just one shop.

## What we build
1. **OTAP, the Open Trade Agent Profile.** It's assembled from existing standards: MCP and A2A for agent access, OpenAPI, GS1 GTIN product IDs, Peppol BIS Order and Order Response, JWS-signed fixed-price quotes with expiry, mandates as W3C Verifiable Credentials ("this agent may spend up to X on dairy"), and a hash-chained audit log. Wholesalers publish it at `/.well-known/otap.json`.
2. **Valio Aimo gateway (the reference implementation).** It runs on the real mock price and availability API with 17.5k products: search, unit conversion, substitutes, signed quotes, a policy engine, an approval inbox, Peppol-style order responses, and an audit trail plus a downloadable evidence pack.
3. **Openness proof.** A second toy wholesaler implements the same profile, the same buyer agent orders from it with zero code changes, and a conformance test runner checks any implementation.
4. **Scale proof: an agent-market wind tunnel on the FR8 cluster.** Thousands of simulated buyer agents with varied mandates face hostile supplier text, stock-outs and price shocks. That gives us hard numbers for the pitch: orders per second, % correctly escalated to a human, injection block rate, and mandate violations caught.

## Demo story (3 minutes)
"1,000 L lactose-free milk by Monday." Stock covers only part of the order, so the agent builds a split plan with good, better and best substitutes. Any substitute outside the buyer's preferences stops for human approval. An item with missing allergen data is treated as unknown, never safe. A prompt injection hidden in supplier product text gets blocked and logged. The human approves the exact signed quote, the order response comes back, and we show the audit trail and evidence pack.

## Repo map
- `docs/DIRECTION.md`: the locked direction the build agents follow.
- `docs/research.md`: deep field research and ranked problems.
- `docs/interfaces.md`: API contracts between components.
- `AGENTS.md`: team rules (branches, merging, secrets).
- `team/*` branches: gateway, catalog, buyer, trust, frontend, pitch, windtunnel. These are in progress and get merged into main by gateway.
- Data: put the large Valio files in `data/` (gitignored). Put the API key in `.env`, never commit it, and ask Silas for it.

## Open questions to brainstorm
- Is OTAP the right framing for judges, or should we lead with the buyer agent experience?
- Which single "wow" moment do we open the pitch with?
- Which wind tunnel numbers are most convincing?
- What should the second wholesaler be (another dairy, a produce supplier, Metro-like)?
- Who presents, and who runs the live demo?
- Anything to cut so the end-to-end demo is bulletproof by Sunday 10:00?
