import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal, get_db
from ..ledger import append_entry
from ..models import Checkout, Mandate, PaymentAttempt
from ..razorpay_client import client as rp_client
from ..security import mandate_is_expired, require_user, verify_webhook_signature

router = APIRouter()


def _mark_paid(db: Session, co: Checkout, payment: dict):
    if co.status == "PAID":
        return
    co.status = "PAID"
    mandate = db.get(Mandate, co.mandate_id)
    if mandate and mandate.status == "ACTIVE":
        mandate.status = "CONSUMED"  # §1 single-use
        mandate.consumed_at = datetime.now(timezone.utc)
    for a in db.query(PaymentAttempt).filter_by(checkout_id=co.id):
        if a.razorpay_order_id == payment.get("order_id"):
            a.status = "PAID"
    append_entry(db, actor="razorpay", action_type="PAYMENT_SUCCESS",
                 checkout_id=co.id, decision="ALLOW",
                 payload={"razorpay_payment_id": payment.get("id"),
                          "order_id": payment.get("order_id")})


def handle_payment_failed(db: Session, co: Checkout, event_payload: dict):
    err = event_payload.get("error", {})
    append_entry(db, actor="razorpay", action_type="PAYMENT_FAILED",
                 checkout_id=co.id, decision="REJECT",
                 reason=f"{err.get('code')}: {err.get('description')}",
                 payload=event_payload)
    for a in db.query(PaymentAttempt).filter_by(checkout_id=co.id):
        if a.razorpay_order_id == event_payload.get("order_id"):
            a.status = "FAILED"
    if co.status != "AWAITING_PAYMENT":
        return
    mandate = db.get(Mandate, co.mandate_id)
    # §5: retry once if retries_used==0 and mandate still valid.
    if co.retries_used == 0 and mandate and mandate.status == "ACTIVE" and not mandate_is_expired(mandate):
        co.retries_used = 1
        append_entry(db, actor="merchant_system", action_type="RETRY_AUTHORIZED",
                     checkout_id=co.id, decision="ALLOW",
                     reason="first failure, mandate still valid",
                     payload={"retries_used": 0, "retries_allowed": 1})
        from .checkout import _create_order
        _create_order(db, co, attempt_no=2, idem_key=f"order-{co.id}-2")
        append_entry(db, actor="merchant_system", action_type="PAYMENT_RETRY_CREATED",
                     checkout_id=co.id, payload={"attempt_no": 2})
    else:
        co.status = "FAILED"
        link = rp_client().payment_link.create({
            "amount": co.total_paise, "currency": "INR",
            "accept_partial": False,
            "expire_by": int((datetime.now(timezone.utc) + timedelta(minutes=30)).timestamp()),
            "reference_id": str(co.id), "description": f"Retry payment for checkout {co.id}",
        })
        co.razorpay_payment_link_id = link["id"]
        co.user_action_url = link["short_url"]
        co.status = "FALLBACK_LINK_ISSUED"
        append_entry(db, actor="merchant_system", action_type="FALLBACK_LINK_ISSUED",
                     checkout_id=co.id,
                     payload={"payment_link_id": link["id"], "url": link["short_url"]})


async def verify_on_timeout(checkout_id: str):
    """§1: asyncio task (not a separate service) — if no webhook within 20s of order
    creation, poll the Razorpay Orders API once and repair state."""
    await asyncio.sleep(settings.WEBHOOK_TIMEOUT_SECONDS)
    db = SessionLocal()
    try:
        co = db.get(Checkout, uuid.UUID(checkout_id))
        if not co or co.status != "AWAITING_PAYMENT" or not co.razorpay_order_id:
            return
        payments = rp_client().order.payments(co.razorpay_order_id)
        for p in payments.get("items", []):
            if p["status"] == "captured":
                _mark_paid(db, co, p)
                append_entry(db, actor="merchant_system", action_type="REPAIR",
                             checkout_id=co.id, decision="REPAIR",
                             reason="verify-on-timeout: captured payment found via poll")
                db.commit()
                return
            if p["status"] == "failed":
                handle_payment_failed(db, co, {"order_id": co.razorpay_order_id,
                                               "error": {"code": p.get("error_code"),
                                                         "description": p.get("error_description") or "failed"}})
                append_entry(db, actor="merchant_system", action_type="REPAIR",
                             checkout_id=co.id, decision="REPAIR",
                             reason="verify-on-timeout: failed payment found via poll")
                db.commit()
                return
        append_entry(db, actor="merchant_system", action_type="REPAIR",
                     checkout_id=co.id, decision="REPAIR",
                     reason="verify-on-timeout: no payment yet, state unchanged")
        db.commit()
    finally:
        db.close()


@router.post("/v1/webhooks/razorpay")
async def razorpay_webhook(request: Request, db: Session = Depends(get_db),
                           x_razorpay_signature: str | None = Header(None)):
    raw = await request.body()  # §1: verify RAW body BEFORE parsing.
    if not verify_webhook_signature(raw, x_razorpay_signature):
        append_entry(db, actor="razorpay", action_type="WEBHOOK_INVALID_SIGNATURE",
                     decision="REJECT", reason="HMAC verification failed",
                     payload={"raw_len": len(raw)})
        db.commit()
        return JSONResponse(status_code=400, content={"error": "invalid signature"})
    event = json.loads(raw)
    etype = event.get("event")
    payload = event.get("payload", {})
    append_entry(db, actor="razorpay", action_type=f"WEBHOOK_{etype}",
                 payload={"event": etype})
    payment = payload.get("payment", {}).get("entity", {}) if "payment" in payload else {}
    order_id = payment.get("order_id")
    co = None
    if order_id:
        co = db.query(Checkout).filter_by(razorpay_order_id=order_id).first()
    if co is None and "payment_link" in payload:
        # Fallback-link payments carry a link-generated order id; resolve via reference_id.
        link_entity = payload["payment_link"].get("entity", {})
        ref = link_entity.get("reference_id")
        if ref:
            co = db.get(Checkout, uuid.UUID(ref))
    if co:
        if etype == "payment.captured":
            _mark_paid(db, co, payment)
        elif etype == "payment.failed":
            handle_payment_failed(db, co, payment)
    db.commit()
    return {"status": "ok"}


@router.post("/v1/checkout/{checkout_id}/simulate-timeout")
async def simulate_timeout(checkout_id: str, db: Session = Depends(get_db),
                           _=Depends(require_user)):
    """[DEV] runs verify-on-timeout logic immediately (no ngrok needed)."""
    co = db.get(Checkout, uuid.UUID(checkout_id))
    if not co:
        return {"error": "checkout not found"}
    payments = rp_client().order.payments(co.razorpay_order_id) if co.razorpay_order_id else {"items": []}
    for p in payments.get("items", []):
        if p["status"] == "captured":
            _mark_paid(db, co, p)
            break
        if p["status"] == "failed":
            handle_payment_failed(db, co, {"order_id": co.razorpay_order_id,
                                           "error": {"code": p.get("error_code"),
                                                     "description": p.get("error_description") or "failed"}})
            break
    append_entry(db, actor="merchant_system", action_type="REPAIR",
                 checkout_id=co.id, decision="REPAIR",
                 reason="simulate-timeout manual repair",
                 payload={"status": co.status, "razorpay_order_id": co.razorpay_order_id})
    db.commit()
    return {"checkout_id": str(co.id), "status": co.status,
            "user_action": ({"type": "payment_link", "url": co.user_action_url}
                            if co.status == "FALLBACK_LINK_ISSUED" else
                            {"type": "razorpay_checkout", "order_id": co.razorpay_order_id,
                             "key_id": settings.RAZORPAY_KEY_ID, "amount_paise": co.total_paise}
                            if co.status == "AWAITING_PAYMENT" else None)}
