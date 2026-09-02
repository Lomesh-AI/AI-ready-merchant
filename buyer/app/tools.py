"""Buyer agent tools — §6. Each tool is an HTTP call to the merchant using
AGENT_SERVICE_TOKEN. The buyer has NO catalog knowledge in code (§11) and NO
tool schema accepts any amount/price/discount parameter (§1)."""
import asyncio
import os

import httpx

AGENT_SERVICE_TOKEN = os.environ.get("AGENT_SERVICE_TOKEN", "agent-service-token-1")
MERCHANT_BASE_URL = os.environ.get("MERCHANT_BASE_URL", "http://merchant:8000")
MAX_STEPS = 12


def _headers(idem: str | None = None) -> dict:
    h = {"Authorization": f"Bearer {AGENT_SERVICE_TOKEN}"}
    if idem:
        h["Idempotency-Key"] = idem
    return h


async def http(method: str, path: str, json_body: dict | None = None, idem: str | None = None) -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.request(method, MERCHANT_BASE_URL + path, json=json_body,
                            headers=_headers(idem))
        try:
            return {"status_code": r.status_code, **r.json()}
        except Exception:  # noqa: BLE001
            return {"status_code": r.status_code, "error": r.text}


# --- Tool implementations -------------------------------------------------

async def discover_merchant(url: str | None = None) -> dict:
    base = url or MERCHANT_BASE_URL
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(base + "/.well-known/agents.json")
        return r.json()


async def search_catalog(query: str, category: str | None = None,
                         max_paise: int | None = None) -> dict:
    body: dict = {"query": query}
    if category:
        body["category"] = category
    if max_paise is not None:
        body["max_paise"] = max_paise
    return await http("POST", "/v1/catalog/search", body)


async def propose_cart(items: list[dict], rationale: str) -> dict:
    if not rationale or not rationale.strip():
        return {"error": "rationale is REQUIRED for propose_cart — §6"}
    cart = await http("POST", "/v1/carts", {})
    if "cart_id" not in cart:
        return cart
    added = await http("POST", f"/v1/carts/{cart['cart_id']}/items", {"items": items})
    if added.get("status_code", 200) >= 400:
        return added
    return await http("POST", f"/v1/carts/{cart['cart_id']}/ready")


async def suggest_add_ons(cart_id: str) -> dict:
    return await http("GET", f"/v1/recommendations?cart_id={cart_id}")


async def request_purchase_authority(scope: dict) -> dict:
    return await http("POST", "/v1/mandates/request",
                      {"scope": {"max_paise": scope.get("max_paise"),
                                 "categories": scope.get("categories", []),
                                 "ttl_minutes": scope.get("ttl_minutes", 10)}})


async def poll_mandate(mandate_id: str) -> dict:
    """Poll every 2s up to 120s until ACTIVE — §6."""
    for _ in range(60):
        m = await http("GET", f"/v1/mandates/{mandate_id}")
        if m.get("status") in ("ACTIVE", "EXPIRED", "REJECTED", "CONSUMED"):
            return m
        await asyncio.sleep(2)
    return {"status": "TIMEOUT"}


async def request_checkout(cart_id: str, mandate_id: str) -> dict:
    return await http("POST", "/v1/checkout/propose",
                      {"cart_id": cart_id, "mandate_id": mandate_id,
                       "rationale": "see prior propose_cart rationale"},
                      idem=f"checkout-{cart_id}-{mandate_id}")


async def poll_checkout(checkout_id: str) -> dict:
    """Poll every 2s until PAID / FALLBACK_LINK_ISSUED / GATE_REJECTED / FAILED — §6."""
    for _ in range(90):
        c = await http("GET", f"/v1/checkout/{checkout_id}")
        if c.get("status") in ("PAID", "FALLBACK_LINK_ISSUED", "GATE_REJECTED", "FAILED"):
            return c
        await asyncio.sleep(2)
    return {"status": "TIMEOUT"}
