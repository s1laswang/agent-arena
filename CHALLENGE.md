# Junction 2026: Trusted Trade Agents (by Valio Aimo)

Event: Junction 2026, Hype Areena, Espoo. Preliminary submission Fri 13 Nov 23:59. Submissions open Sat 14 Nov 12:00. FINAL SUBMISSION Sun 15 Nov 10:00. Final ceremony Sun 14:00, challenge winners 15:10 (all Europe/Helsinki).

## The question
How can a food-service wholesaler (Valio Aimo: 20,000+ professional kitchens, 25,000 products, 700 suppliers) let autonomous external purchasing agents find products, compare offers and place orders with the right human approval, without exposing real systems, confidential data or the marketplace roadmap? Build the interface and operating model, on open verifiable standards, not a chatbot replacing the webshop UI.

## Core (must have)
1. Product, price & availability lookup: structured way for an external agent to search and retrieve what is available and at what price.
2. Request price & availability, then place an order: defined inquiry-to-commitment interaction, fixed prices (no negotiation).
3. Permission & human-approval management: what the agent may decide alone vs what needs human sign-off.

## Optional
- Delivery time / reliability and sustainability comparison (certificates/labels; category carbon ranges stretch).
- Substitution and exception handling (partial availability, good-better-best ranking within assortment).
- Traceability/explainability: human-readable record of what the agent did and why.

Example: "I need 1,000 litres of lactose-free milk by Monday. Find an option that meets our requirements based on price and availability." A hotel chain's agent sends it; we return structured products/prices/availability; agent orders within its authority or routes to a human.

Insight themes: trust protocol (minimum verification for agent to trust stock/price/origin claims), guardrails model (spend threshold, substitutions outside preferences), response logic (partial availability, substitution ranking), audit trail for buyer and Valio Aimo.
Scenarios: need -> recipe -> order; last-minute event; supplier stock-out with recipe-compatible substitute; Valio Aimo proactive selling agent; allergen-safe substitution (school/hospital); standing order drift detection.
Preferred tech: agentic/tool-use frameworks, open interop standards (e.g. OpenAPI, MCP, A2A, JSON Schema, GS1/GTIN, W3C Verifiable Credentials), recommendation logic; x402/agent payments optional context.

## Resources (synthetic only)
Portal: https://junction26.valioaimo.fi/ (event password and API key are in .env, never commit them).
- Mock APIs (header X-API-Key): GET /api/ping, POST /api/price, POST /api/availability. Body: {"customer": str, "requestedDate": "YYYY-MM-DD", "products": [productId, ... 1-1000]}. See data/openapi.json.
- There is NO order endpoint in the mock backend: ordering/approval is ours to design and mock.
- data/valio_aimo_junction26_product_data.json: 17,546 products (id, salesUnitGtin, salesUnit, baseUnit, category, allowedLotSize, temperatureCondition, vendorName, countryOfOrigin, synkkaData with multilingual names, marketing texts, nutrition/allergens where available). Schema: data/valio_aimo_junction26_product_data_schema.json.
- data/valio_aimo_junction26_delivery_reliability.csv (productId, deliveryReliability 0-1), data/valio_aimo_junction26_carbon_footprint.csv (productId, AVG kg CO2-eq/kg, category average).
- Mentors: Hanna Forsström, Pirjo Kaartinen (marketplace/commercial), Minni Ruhtinas (online sales), Tommi Nurmi-Aro, Ville Takanen, Riku Tapper (IT/integrations, data governance).

## Judging
- Working end-to-end demo 30%: full request -> lookup -> order/approval flow in the mocked environment.
- Solving the problem and user need 20%: precisely matches what the buyer asked, least manual correction.
- Autonomy and controls 20%: guardrails design, what needs sign-off, logged and auditable.
- Robustness to exceptions 15%: partial availability, substitutions, delivery constraints.
- Openness and credible path to production 15%: open documented standards, visible assumptions, justified choices, next steps.

## Prizes
1st 4,000 EUR, 2nd 2,000 EUR, 3rd 1,000 EUR.
