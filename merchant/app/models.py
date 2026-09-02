import uuid
from datetime import datetime, timezone

from sqlalchemy import (BigInteger, Boolean, CHAR, DateTime, Float, ForeignKey,
                        Integer, Text, UniqueConstraint)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    price_paise: Mapped[int] = mapped_column(Integer)  # server truth, integer paise
    category: Mapped[str] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text))
    rating: Mapped[float] = mapped_column(Float)
    stock: Mapped[int] = mapped_column(Integer)
    image_url: Mapped[str] = mapped_column(Text, nullable=True)
    is_injection_fixture: Mapped[bool] = mapped_column(Boolean, default=False)


class Cart(Base):
    __tablename__ = "carts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(Text, default="demo-user")
    status: Mapped[str] = mapped_column(Text, default="DRAFT")  # DRAFT|READY|CONVERTED|EXPIRED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CartItem(Base):
    __tablename__ = "cart_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cart_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("carts.id"))
    sku: Mapped[str] = mapped_column(Text)
    qty: Mapped[int] = mapped_column(Integer)
    unit_price_paise: Mapped[int] = mapped_column(Integer)  # copied at add-time from server


class Mandate(Base):
    __tablename__ = "mandates"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(Text, default="demo-user")
    kind: Mapped[str] = mapped_column(Text)  # INTENT|CART
    status: Mapped[str] = mapped_column(Text, default="PENDING")  # PENDING|ACTIVE|CONSUMED|EXPIRED|REJECTED
    max_paise: Mapped[int | None] = mapped_column(Integer, nullable=True)
    categories: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    cart_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    cart_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    nonce: Mapped[str] = mapped_column(Text, unique=True)  # §1: single-use enforced by DB unique constraint
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    signature: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PolicyRule(Base):
    __tablename__ = "policy_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    rule_type: Mapped[str] = mapped_column(Text)  # per_txn_cap|daily_cap|velocity|category_allowlist|stepup_trigger|discount_cap
    value_json: Mapped[dict] = mapped_column(JSONB)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Checkout(Base):
    __tablename__ = "checkouts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(Text, default="demo-user")
    cart_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    mandate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    # PROPOSED|GATE_REJECTED|AWAITING_CART_APPROVAL|CART_APPROVED|ORDER_CREATED|AWAITING_PAYMENT|PAID|FAILED|FALLBACK_LINK_ISSUED|EXPIRED
    status: Mapped[str] = mapped_column(Text, default="PROPOSED")
    total_paise: Mapped[int] = mapped_column(Integer)
    cart_hash: Mapped[str] = mapped_column(CHAR(64))
    retries_used: Mapped[int] = mapped_column(Integer, default=0)
    razorpay_order_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    razorpay_payment_link_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_action_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PaymentAttempt(Base):
    __tablename__ = "payment_attempts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    checkout_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("checkouts.id"))
    razorpay_order_id: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(Text, unique=True)  # §1 idempotency via UNIQUE index
    status: Mapped[str] = mapped_column(Text, default="CREATED")  # CREATED|PAID|FAILED
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)


class LedgerEntry(Base):
    __tablename__ = "ledger"
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    actor: Mapped[str] = mapped_column(Text)  # agent|user|merchant_system|razorpay
    action_type: Mapped[str] = mapped_column(Text)
    checkout_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    mandate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    decision: Mapped[str | None] = mapped_column(Text, nullable=True)  # NULL|ALLOW|REJECT|REPAIR
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSONB)
    prev_entry_hash: Mapped[str] = mapped_column(CHAR(64))
    entry_hash: Mapped[str] = mapped_column(CHAR(64))


class CoOccurrence(Base):
    __tablename__ = "co_occurrences"
    sku_a: Mapped[str] = mapped_column(Text, primary_key=True)
    sku_b: Mapped[str] = mapped_column(Text, primary_key=True)
    pair_count: Mapped[int] = mapped_column(Integer)


class RecommendationLog(Base):
    __tablename__ = "recommendations_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    checkout_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    sku_suggested: Mapped[str] = mapped_column(Text)
    score: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DemoSession(Base):
    __tablename__ = "demo_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    with_ai: Mapped[bool] = mapped_column(Boolean)
    total_paise: Mapped[int] = mapped_column(Integer)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    response_json: Mapped[dict] = mapped_column(JSONB)
