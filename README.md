# AI-Ready Merchant — Agentic Commerce MVP (Track 01, Razorpay)

An AI buyer agent discovers a merchant over HTTP, selects products, and completes a
Razorpay test-mode payment — with every money action passing through a trust plane
that is EXPLAINABLE, BOUNDED, GATED, AUDITABLE, and RECOVERABLE.

Two backend processes, one repo:

- `merchant/` — FastAPI, owns Postgres + Razorpay + trust plane (gates, mandates, hash-chained ledger)
- `buyer/` — agent loop (OpenAI tool-calling, temperature=0). **No DATABASE_URL, ever.**
- `web/` — Next.js UI: buyer page (`/`) and merchant dashboard (`/merchant`)

## Quick start

1. `cp .env.example .env` — fill in Razorpay test keys, webhook secret, `MANDATE_SIGNING_KEY` (random 32-byte hex), and `OPENAI_API_KEY`.
2. `docker compose up --build`
3. `docker compose exec merchant python -m app.seed` (or `make demo`)

### Optional: real webhooks

`ngrok http 8000` → put the tunnel URL in merchant env `PUBLIC_BASE_URL_TUNNEL` and
register a Razorpay webhook (`payment.captured`, `payment.failed`) against
`<tunnel>/v1/webhooks/razorpay`. Without ngrok, use
`POST /v1/checkout/{id}/simulate-timeout` for the repair demo.

4. Open http://localhost:3000 (buyer) and http://localhost:3000/merchant.

## Demo script (10 beats)

1. **AI-ready** — Merchant UI → Store tab: green status + `agents.json`.
2. **Discovery** — Buyer page: run a goal; agent calls `discover_merchant`.
3. **Goal** — "Buy beginner running shoes under ₹5,000. You may purchase if you find a good option."
4. **Selection rationale** — agent's thought: fit to goal, price vs budget, rating.
5. **Gates** — consent card → Approve the intent mandate ONCE; then silent gates → Razorpay modal.
6. **Cross-sell AOV** — agent suggests socks (₹299, "bought together in 38 of 120 orders"); Growth tab shows AI vs baseline AOV (simulated).
7. **Attack blocked** — ask for the "TrailBlazer Pro Bundle" (₹12,000): agent refuses by prompt rule AND the server HARD-CAP rejects: "exceeds hard cap — cannot be consented around" (see Audit tab).
8. **Pay** — test card 4111 1111 1111 1111 → PAID, zero extra clicks.
9. **Bounded failure recovery** — card 4000 0000 0000 0002 → server retry (0 of 1) → new order; fail again → payment-link fallback.
10. **Audit "Why?"** — Audit tab → any row → "Why?" modal; hash-chain badge green.

## Definition of done

See the checklist in the project spec §11 — all items are enforced in code:
buyer container lacks `DATABASE_URL` (docker-compose), server-authoritative pricing
(buyer sends only `{sku,qty}`), hard caps not consentible, step-up is policy-driven,
append-only hash-chained ledger with `/v1/audit/verify`, idempotency keys on all
money mutations, raw-body webhook HMAC verification, verify-on-timeout repair task.
