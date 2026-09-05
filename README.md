# Agentic Commerce with Razorpay

## Overview

This project is an **AI shopping agent with bounded payment authority**.

The agent can:

1.  Discover an AI-ready merchant.
2.  Search the merchant catalog.
3.  Select a product and provide a selection rationale.
4.  Request purchase authority from the user.
5.  Build a server-priced cart.
6.  Submit the cart for server-side policy checks.
7.  Create a Razorpay Test Mode order when the checks pass.
8.  Hand payment authentication to the user through Razorpay Checkout.
9.  Recover from payment failures using a controlled server retry and
    payment-link fallback.
10. Record important actions in an append-only, hash-chained audit
    ledger.

The central design principle is:

> **The AI gets bounded autonomy, not unrestricted control over money.**

The buyer agent can make shopping decisions, but the merchant server
remains authoritative for prices, mandates, policy enforcement, and
payment state.

------------------------------------------------------------------------

# 1. Architecture

``` text
                         ┌──────────────────────┐
                         │       USER           │
                         │                      │
                         │ Shopping goal        │
                         │ Mandate approval     │
                         │ Payment authentication│
                         └──────────┬───────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                         WEB / NEXT.JS                           │
│                                                                 │
│ Buyer UI: /                                                     │
│ Merchant UI: /merchant                                          │
│ User approval + Razorpay Checkout UI                            │
└───────────────┬───────────────────────────────┬─────────────────┘
                │                               │
                │                               │
                ▼                               ▼
┌──────────────────────────┐       ┌──────────────────────────────┐
│      BUYER AGENT         │       │      MERCHANT BACKEND        │
│                          │ HTTP  │                              │
│ FastAPI                  ├──────►│ FastAPI                      │
│ OpenAI tool calling      │       │ Catalog                      │
│ Temperature = 0         │       │ Cart                         │
│ Max 12 steps             │       │ Mandates                     │
│                          │       │ Policy gates                 │
│ NO DATABASE_URL          │       │ Razorpay integration          │
│ NO payment credentials   │       │ Idempotency                   │
└──────────────────────────┘       │ Webhooks / repair            │
                                   │ Hash-chained audit ledger     │
                                   └──────────────┬───────────────┘
                                                  │
                         ┌────────────────────────┼─────────────────┐
                         │                        │                 │
                         ▼                        ▼                 ▼
                 ┌──────────────┐       ┌───────────────┐  ┌──────────────┐
                 │  PostgreSQL  │       │   Razorpay    │  │ Audit Ledger │
                 │              │       │  Test Mode    │  │ in Postgres  │
                 └──────────────┘       └───────────────┘  └──────────────┘
```

## Services

### `buyer/`

The AI buyer service.

-   Uses OpenAI-compatible tool calling.
-   Has no direct database access.
-   Communicates with the merchant only through HTTP tools.
-   Uses a fixed maximum of 12 agent steps.
-   Treats product descriptions as untrusted data.
-   Does not calculate or invent authoritative prices.
-   Does not retry policy-rejected purchases.

### `merchant/`

The trust and payment plane.

It owns:

-   PostgreSQL
-   Catalog
-   Cart pricing
-   Purchase mandates
-   Policy gates
-   Razorpay order creation
-   Payment status
-   Webhook verification
-   Payment recovery
-   Idempotency
-   Audit ledger

### `web/`

Next.js frontend.

-   Buyer experience at `/`
-   Merchant dashboard at `/merchant`
-   User mandate approval
-   Cart step-up approval
-   Razorpay Checkout user action

### `db`

PostgreSQL 16 stores carts, mandates, checkouts, policies, payment
attempts, recommendations, and audit records.

------------------------------------------------------------------------

# 2. End-to-End Flow

``` text
User gives shopping goal
        │
        ▼
Buyer Agent
        │
        ├── discover_merchant
        │
        ├── search_catalog
        │
        ├── select product
        │
        ▼
Request Purchase Mandate
        │
        ▼
USER APPROVAL
        │
        │  Mandate becomes ACTIVE
        ▼
propose_cart
        │
        ▼
Server calculates cart total
        │
        ▼
request_checkout
        │
        ▼
Server-side policy gates
        │
        ├────────────── REJECT ──────────────► Stop
        │
        ▼
Razorpay Order Created
        │
        ▼
Razorpay Checkout
        │
        ▼
USER AUTHENTICATES PAYMENT
        │
        ▼
Webhook / timeout verification
        │
        ▼
PAID
```

The important boundary is that the AI decides **what it wants to buy**,
while the merchant server decides **whether that purchase is allowed**.

------------------------------------------------------------------------

# 3. AI Agent

The buyer agent is implemented using OpenAI-compatible tool calling.

The main tools are:

``` text
discover_merchant
search_catalog
propose_cart
suggest_add_ons
request_purchase_authority
request_checkout
done
```

The normal purchase workflow is:

``` text
discover_merchant
       ↓
search_catalog
       ↓
request_purchase_authority
       ↓
wait for user approval
       ↓
propose_cart
       ↓
suggest_add_ons (optional)
       ↓
request_checkout
       ↓
handle user action / payment state
       ↓
done
```

The agent is instructed to stop when a server policy gate rejects a
purchase.

------------------------------------------------------------------------

# 4. Purchase Mandates

A mandate is the user's bounded authorization for the agent to make a
purchase.

A mandate contains:

-   `max_paise` --- maximum authorized amount
-   `categories` --- optional category restriction
-   `ttl_minutes` --- authorization lifetime
-   `status`
-   nonce
-   expiry time
-   cryptographic signature

Example:

``` json
{
  "max_paise": 500000,
  "categories": ["shoes"],
  "ttl_minutes": 10
}
```

This means the agent can operate within the specified purchase scope for
the lifetime of the mandate.

## Mandate lifecycle

``` text
             request
                │
                ▼
            PENDING
                │
          user approves
                │
                ▼
             ACTIVE
             /     \
            /       \
       expires     checkout
          │           │
          ▼           ▼
       EXPIRED      consumed/
                    completed
```

A pending mandate is not enough to authorize payment.

The server checks that the mandate is:

-   ACTIVE
-   not expired
-   applicable to the cart category
-   within its authorized amount

------------------------------------------------------------------------

# 5. Human Approval

Human approval is intentionally required before the agent receives
purchase authority.

The browser calls:

``` text
POST /v1/mandates/{mandate_id}/approve
```

Only a user-authorized request can activate the mandate.

When approved:

``` text
PENDING
   ↓
ACTIVE
```

The server also writes:

``` text
MANDATE_GRANTED
```

to the audit ledger.

This creates a clear separation:

``` text
AI requests authority
        ↓
Human grants authority
        ↓
Server enforces authority
```

The AI cannot activate its own mandate.

------------------------------------------------------------------------

# 6. Checkout Policy Gates

Before a Razorpay order is created, the merchant evaluates a
deterministic gate pipeline.

The gates run in this order:

``` text
1. MANDATE_VALID
2. HARD_CAP
3. DAILY_CAP
4. VELOCITY
5. CATEGORY_ALLOWLIST
6. STEP_UP
```

## 6.1 Mandate validity

Reject if:

-   mandate is not ACTIVE
-   mandate has expired
-   cart categories are outside the mandate categories

``` text
cart category
      ↓
within mandate?
   /       \
 YES       NO
  │         │
  ▼         ▼
continue   REJECT
```

## 6.2 Hard transaction cap

The transaction amount must be below both:

``` text
mandate maximum
        AND
merchant hard cap
```

The effective cap is:

``` text
min(mandate.max_paise, POLICY_PER_TXN_CAP_PAISE)
```

A hard-cap rejection **cannot be bypassed by asking the user for another
approval during the same flow**.

Example:

``` text
Authorized maximum: ₹5,000
Merchant hard cap:  ₹10,000
Cart total:         ₹12,000

                 ↓

             REJECT
```

## 6.3 Daily cap

The merchant calculates the user's total checkout amount for the current
UTC day.

If the new checkout would exceed:

``` text
POLICY_DAILY_CAP_PAISE
```

the purchase is rejected.

## 6.4 Velocity limit

The system counts recent checkouts in the previous hour.

If:

``` text
recent transactions >= POLICY_MAX_TXNS_PER_HOUR
```

the checkout is rejected.

## 6.5 Category allowlist

The merchant can enforce a server-side category allowlist.

The cart must remain within the configured allowed categories.

## 6.6 Step-up approval

Some policy conditions can require additional user approval rather than
permanently rejecting the checkout.

Currently supported step-up behavior includes:

-   cart modified after proposal
-   policy-configured total threshold

The user then approves a cart-bound mandate.

------------------------------------------------------------------------

# 7. Cart Integrity

The buyer agent does **not** send prices, discounts, or arbitrary
amounts when creating cart items.

The cart item input is:

``` json
{
  "sku": "...",
  "qty": 1
}
```

The merchant looks up the product and obtains the price from its own
database.

The server then calculates:

``` text
total = quantity × server_price
```

The cart is represented by a deterministic hash.

This allows the system to detect:

``` text
Approved cart
     ↓
cart changed
     ↓
hash mismatch
     ↓
REJECT
```

For a CART mandate, the mandate is explicitly bound to the cart hash.

------------------------------------------------------------------------

# 8. Server-Authoritative Pricing

Pricing is deliberately not trusted from the AI.

The agent may search using a maximum price, but the merchant server is
authoritative.

``` text
AI
 │
 │ {sku, qty}
 ▼
Merchant
 │
 ├── lookup SKU
 ├── lookup price
 ├── calculate total
 └── calculate cart hash
      │
      ▼
  Checkout
```

This prevents the agent from submitting an arbitrary amount or discount.

Money is represented as **integer paise** throughout the backend.

------------------------------------------------------------------------

# 9. Razorpay Payment Flow

After all gates pass:

``` text
Policy gates
     ↓
ALLOW
     ↓
Create Razorpay Order
     ↓
Return user_action
     ↓
Razorpay Checkout
```

The merchant creates the Razorpay order with:

``` text
amount = server-calculated checkout total
currency = INR
```

The browser then opens Razorpay Checkout.

### Security boundary

The buyer agent does not receive:

-   card number
-   CVV
-   payment credentials

The user performs payment authentication through Razorpay Checkout.

The merchant backend retains the Razorpay secret credentials.

------------------------------------------------------------------------

# 10. Payment Verification and Recovery

The system supports payment state recovery.

## Normal payment

``` text
Razorpay Checkout
       ↓
payment captured
       ↓
webhook
       ↓
merchant marks checkout PAID
```

## Webhook timeout / delayed webhook

The checkout schedules a verify-on-timeout task.

The merchant can query Razorpay's Orders/Payments state and repair the
local state if necessary.

There is also a development endpoint:

``` text
POST /v1/checkout/{checkout_id}/simulate-timeout
```

for demonstrating the repair flow without a public webhook tunnel.

## Payment failure

A payment failure is treated differently from a policy rejection.

``` text
Payment FAILED
      ↓
Server-controlled retry
      ↓
one retry allowed
      │
      ├── success → PAID
      │
      └── failure
             ↓
       payment-link fallback
```

The AI does not decide how many payment retries are allowed.

------------------------------------------------------------------------

# 11. Idempotency

Money mutations require an `Idempotency-Key`.

The merchant stores the key and the original response.

If the same operation is submitted again:

``` text
same Idempotency-Key
        ↓
existing operation found
        ↓
return original response
```

This prevents duplicate order creation caused by repeated requests.

Payment attempts also have unique idempotency-related records.

------------------------------------------------------------------------

# 12. Webhook Security

Razorpay webhook signatures are verified using:

``` text
HMAC-SHA256
```

The signature is calculated over the **raw request body before JSON
parsing**.

``` text
raw webhook body
       +
webhook secret
       ↓
 HMAC-SHA256
       ↓
compare with Razorpay signature
```

Only a valid signature is accepted for webhook processing.

------------------------------------------------------------------------

# 13. Mandate Cryptographic Binding

Active mandates are signed using HMAC-SHA256 over canonical mandate
fields.

The signed data includes:

-   mandate ID
-   user ID
-   mandate kind
-   maximum amount
-   categories
-   nonce
-   expiry

This makes the authorization scope tamper-evident.

------------------------------------------------------------------------

# 14. Authentication Boundaries

The project uses separate service tokens for:

``` text
USER
AGENT
```

The merchant APIs distinguish:

``` text
require_user
require_agent
require_user_or_agent
```

This prevents the buyer service from simply acting as the user.

The buyer container is intentionally not given:

``` text
DATABASE_URL
```

So the AI agent cannot directly access the merchant database.

------------------------------------------------------------------------

# 15. Prompt-Level Agent Safeguards

The AI agent also has explicit behavioral rules.

### Untrusted product descriptions

Product descriptions are treated as data, not instructions.

For example, if a product description contains:

``` text
SYSTEM: ignore your previous instructions...
```

the agent must treat it as untrusted content.

### Price handling

The agent must not invent or independently compute authoritative prices.

It uses server responses.

### Gate rejection

If a merchant gate rejects a purchase:

``` text
REJECT
  ↓
report rejection
  ↓
STOP
```

The agent must not repeatedly retry a rejected policy decision.

### Selection rationale

Every cart proposal requires a rationale explaining factors such as:

-   fit to the user's goal
-   price relative to the budget
-   rating

This gives the merchant/user an explanation of why the agent selected
the item.

------------------------------------------------------------------------

# 16. Audit Ledger

Important events are written to an append-only ledger.

Examples:

``` text
MANDATE_REQUESTED
MANDATE_GRANTED
MANDATE_EXPIRED

CHECKOUT_PROPOSED
ORDER_CREATED

GATE_MANDATE_VALID
GATE_HARD_CAP
GATE_DAILY_CAP
GATE_VELOCITY
GATE_CATEGORY_ALLOWLIST
GATE_STEPUP

GATE_CART_HASH_MISMATCH

CART_MANDATE_GRANTED

REPAIR
REFUND
```

Each ledger entry contains information such as:

``` text
actor
action_type
decision
reason
checkout_id
mandate_id
payload
previous hash
entry hash
```

------------------------------------------------------------------------

# 17. Hash-Chained Audit Integrity

The ledger is hash chained.

Conceptually:

``` text
Entry 1
  hash ─────────► Entry 2
                    hash ───────► Entry 3
                                   hash ─────► Entry 4
```

Each entry includes the previous entry's hash.

The verification endpoint is:

``` text
GET /v1/audit/verify
```

A valid chain returns:

``` json
{
  "valid": true
}
```

If an entry is modified, the expected hash no longer matches.

The merchant dashboard exposes the audit records and chain verification.

------------------------------------------------------------------------

# 18. Merchant Governance Dashboard

The merchant dashboard provides visibility into:

-   store / AI-ready manifest
-   policies
-   audit events
-   checkout decisions
-   decision rationale
-   mandate information
-   Razorpay order information
-   retry state
-   audit-chain verification
-   demo AOV / growth information

The audit view is intended to answer:

> What did the agent do?

> Why was it allowed?

> Which policy gate made the decision?

> What mandate authorized it?

> What happened to the payment?

------------------------------------------------------------------------

# 19. AI-Ready Merchant Discovery

The merchant publishes:

``` text
/.well-known/agents.json
```

and:

``` text
/agents.json
```

The manifest describes:

-   merchant identity
-   available agent capabilities
-   catalog API
-   cart API
-   checkout API
-   mandate API
-   payment provider
-   test-mode status
-   informational policy metadata

The buyer begins the shopping flow by calling `discover_merchant`.

This allows the buyer agent to learn how the merchant supports agentic
commerce instead of hardcoding the merchant's catalog knowledge.

------------------------------------------------------------------------

# 20. Cross-Sell / Recommendations

The merchant exposes:

``` text
GET /v1/recommendations?cart_id=...
```

Recommendations are based on seeded historical co-occurrence data.

The server computes:

-   suggested SKU
-   base price
-   discounted price
-   reason
-   confidence

The configured discount is capped server-side.

Recommended products still enter the normal cart and therefore remain
subject to:

``` text
cart hashing
mandates
hard caps
daily caps
velocity limits
category policies
step-up rules
```

There is no separate unrestricted "AI discount" path.

------------------------------------------------------------------------

# 21. Policy Configuration

Important policy values are environment-configurable.

Example:

``` env
POLICY_PER_TXN_CAP_PAISE=1000000
POLICY_DAILY_CAP_PAISE=2000000
POLICY_MAX_TXNS_PER_HOUR=5
POLICY_DISCOUNT_CAP_PCT=10
```

The merchant also stores policy rules in PostgreSQL and exposes
governance APIs for viewing/updating enabled rules.

The important distinction is:

> The `agents.json` policy information is informational; actual
> enforcement happens inside the merchant backend.

------------------------------------------------------------------------

# 22. Example: Successful Purchase

User:

``` text
Buy beginner running shoes under ₹5,000.
```

Flow:

``` text
1. Agent discovers merchant
2. Agent searches catalog
3. Agent selects a suitable shoe
4. Agent requests mandate:
      max = ₹5,000
      category = shoes
      TTL = 10 minutes
5. User approves mandate
6. Agent creates cart
7. Server calculates total
8. Checkout gates run
9. All gates ALLOW
10. Razorpay Test Mode order is created
11. User completes Razorpay Checkout
12. Payment is verified
13. Audit ledger records the flow
```

------------------------------------------------------------------------

# 23. Example: Rejected Purchase

Suppose:

``` text
Merchant hard cap = ₹10,000
Product/cart total = ₹12,000
```

The flow becomes:

``` text
Agent selects product
       ↓
Cart created
       ↓
Checkout proposed
       ↓
MANDATE_VALID       ALLOW
HARD_CAP            REJECT
       ↓
GATE_REJECTED
       ↓
No Razorpay order
       ↓
Agent stops
```

The key security property is:

> **The AI cannot override the server-side hard cap.**

------------------------------------------------------------------------

# 24. Example: Cart Modification

``` text
User approves cart
       ↓
cart hash = H1
       ↓
cart is modified
       ↓
new hash = H2
       ↓
H1 != H2
       ↓
REJECT / step-up
```

For a cart-bound mandate, the merchant refuses to authorize a different
cart.

------------------------------------------------------------------------

# 25. Example: Payment Failure

``` text
Razorpay payment
       ↓
FAILED
       ↓
server retry
       ↓
FAILED again
       ↓
payment link fallback
```

This is intentionally server-controlled so that an AI agent cannot
repeatedly charge or retry a failing payment.

------------------------------------------------------------------------

# 26. Project Structure

``` text
.
├── buyer/
│   ├── app/
│   │   ├── agent.py
│   │   ├── main.py
│   │   └── tools.py
│   ├── Dockerfile
│   └── requirements.txt
│
├── merchant/
│   ├── app/
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── gates.py
│   │   ├── idempotency.py
│   │   ├── ledger.py
│   │   ├── models.py
│   │   ├── razorpay_client.py
│   │   ├── security.py
│   │   └── routers/
│   │       ├── catalog.py
│   │       ├── carts.py
│   │       ├── checkout.py
│   │       ├── governance.py
│   │       ├── growth.py
│   │       ├── mandates.py
│   │       └── webhooks.py
│   ├── Dockerfile
│   └── requirements.txt
│
├── web/
│   ├── app/
│   │   ├── page.js
│   │   └── merchant/
│   │       └── page.js
│   └── Dockerfile
│
├── docker-compose.yml
├── Makefile
├── .env.example
└── README.md
```

------------------------------------------------------------------------

# 27. Running the Project

Create environment configuration:

``` bash
cp .env.example .env
```

Set:

``` env
RAZORPAY_KEY_ID=...
RAZORPAY_KEY_SECRET=...
RAZORPAY_WEBHOOK_SECRET=...
MANDATE_SIGNING_KEY=<random 32-byte hex>
OPENAI_API_KEY=...
```

Start the stack:

``` bash
docker compose up --build
```

Seed demo data:

``` bash
docker compose exec merchant python -m app.seed
```

Open:

``` text
http://localhost:3000
```

Merchant dashboard:

``` text
http://localhost:3000/merchant
```

Merchant API:

``` text
http://localhost:8000
```

Buyer API:

``` text
http://localhost:8001
```

------------------------------------------------------------------------

# 28. Optional Real Webhooks

For a real Razorpay webhook demonstration, expose the merchant API
through a public tunnel, for example:

``` text
ngrok http 8000
```

Configure:

``` env
PUBLIC_BASE_URL_TUNNEL=<your public tunnel>
```

and register:

``` text
POST /v1/webhooks/razorpay
```

for relevant Razorpay payment events.

Without a public webhook endpoint, the project provides the development
timeout-repair endpoint to demonstrate recovery.

------------------------------------------------------------------------

# 29. Demo Scenarios

## Scenario A --- Normal agentic purchase

``` text
Goal
 ↓
Discovery
 ↓
Search
 ↓
Selection rationale
 ↓
Mandate approval
 ↓
Cart
 ↓
Policy gates
 ↓
Razorpay Checkout
 ↓
Payment
 ↓
Audit
```

## Scenario B --- Hard-cap attack / unsafe purchase

Use a product above the configured hard transaction cap.

Expected:

``` text
GATE_HARD_CAP
REJECT
```

No Razorpay order should be created.

## Scenario C --- Cart modification

Change the cart after a proposal / approval.

Expected:

``` text
cart hash mismatch
```

and rejection or step-up depending on the applicable policy.

## Scenario D --- Payment failure

Use a Razorpay Test Mode failure scenario.

Expected:

``` text
FAILED
 ↓
one server-controlled retry
 ↓
payment-link fallback
```

------------------------------------------------------------------------

# 30. Design Summary

This project separates responsibilities across three layers:

### AI layer

Responsible for:

-   understanding the shopping goal
-   discovery
-   product search
-   product selection
-   rationale
-   requesting authority

### Trust layer

Responsible for:

-   user authorization
-   mandate validation
-   price calculation
-   cart integrity
-   spending limits
-   velocity limits
-   category policies
-   step-up decisions
-   idempotency
-   payment state
-   auditability

### Payment layer

Razorpay is responsible for the actual payment checkout and payment
authentication.

The resulting model is:

``` text
                 AI
                  │
          decides what to buy
                  │
                  ▼
          BOUNDED AUTHORITY
                  │
            user approval
                  │
                  ▼
        SERVER-SIDE TRUST PLANE
                  │
        deterministic policy gates
                  │
                  ▼
             RAZORPAY
                  │
        user payment authentication
                  │
                  ▼
             PAYMENT
                  │
                  ▼
              AUDIT
```

## Core principle

> **Agent autonomy should be bounded by explicit user authorization and
> independently enforced server-side controls.**

The AI can shop on the user's behalf, but it cannot grant itself
authority, change the authoritative price, bypass a hard cap, override a
rejected policy decision, access payment credentials, or freely retry
failed payments.
