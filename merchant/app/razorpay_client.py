import razorpay
from fastapi import HTTPException

from .config import settings


def client() -> razorpay.Client:
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        raise HTTPException(status_code=503, detail="Razorpay keys not configured")
    return razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


def ping() -> tuple[bool, str]:
    """Startup check §8: verify keys work with a lightweight API call."""
    if not settings.RAZORPAY_KEY_ID:
        return False, "RAZORPAY_KEY_ID missing"
    try:
        client().payment_link.fetch_all()  # simple authenticated ping
        return True, "Razorpay keys OK (test mode)"
    except Exception as e:  # noqa: BLE001 - startup banner must never crash boot
        return False, f"Razorpay ping failed: {e}"
