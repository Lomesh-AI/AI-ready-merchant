from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from sqlalchemy import text

from .config import settings
from .db import Base, engine
from .razorpay_client import ping


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)  # §2: create_all; no Alembic
    ok, msg = ping()
    print("=" * 60)
    print(f"  MERCHANT  |  Razorpay test keys: {'OK' if ok else 'NOT VERIFIED'} — {msg}")
    print(f"  Public base URL: {settings.PUBLIC_BASE_URL}"
          + (f"  | tunnel: {settings.PUBLIC_BASE_URL_TUNNEL}" if settings.PUBLIC_BASE_URL_TUNNEL else ""))
    print("=" * 60)
    yield


app = FastAPI(title="Acme Outdoors Merchant (agentic-commerce MVP)", lifespan=lifespan)

from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

# The user's BROWSER posts mandate/step-up approvals directly to this origin (§5 [USER]).
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

from .routers import catalog, carts, checkout, governance, growth, mandates, webhooks  # noqa: E402

app.include_router(catalog.router)
app.include_router(carts.router)
app.include_router(mandates.router)
app.include_router(checkout.router)
app.include_router(webhooks.router)
app.include_router(growth.router)
app.include_router(governance.router)


@app.get("/healthz")
def healthz():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}


# P1 spike: minimal HTML test page that opens Checkout.js against a manually
# supplied order id / key id. Kept for the P1 webhook proof.
TEST_PAGE = """
<!doctype html><html><head><script src="https://checkout.razorpay.com/v1/checkout.js"></script></head>
<body style="font-family:sans-serif;max-width:600px;margin:40px auto">
<h3>P1 Razorpay Spike — Checkout.js test</h3>
<p>Test cards: SUCCESS 4111 1111 1111 1111 · FAILURE 4000 0000 0000 0002</p>
Order ID: <input id="oid" size="40"><br>Amount (paise): <input id="amt"><br>
<button onclick="new Razorpay({key:KEY_ID,order_id:oid.value,amount:amt.value,handler:a=>document.body.append(' OK '+a.razorpay_payment_id)}).open()">Pay</button>
<p>Replace KEY_ID with your RAZORPAY_KEY_ID.</p>
</body></html>
"""


@app.get("/dev/razorpay-test", response_class=HTMLResponse)
def razorpay_test():
    return TEST_PAGE.replace("KEY_ID", settings.RAZORPAY_KEY_ID)
