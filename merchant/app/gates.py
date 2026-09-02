"""Gate pipeline evaluator — §5 checkout.propose, IN ORDER.
Each verdict writes a ledger entry with a reason."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .config import settings
from .ledger import append_entry
from .models import CartItem, Checkout, Mandate, PolicyRule
from .security import mandate_is_expired


@dataclass
class GateResult:
    allowed: bool
    status: str  # ALLOW -> continue; else a checkout status
    reason: str | None = None
    step_up: bool = False


def _rule(db: Session, rule_type: str) -> PolicyRule | None:
    return db.query(PolicyRule).filter_by(rule_type=rule_type, enabled=True).first()


def evaluate(db: Session, checkout: Checkout, mandate: Mandate, cart_categories: list[str],
             modified_after_proposal: bool) -> GateResult:
    def log(action, decision, reason):
        append_entry(db, actor="merchant_system", action_type=action,
                     decision=decision, reason=reason,
                     checkout_id=checkout.id, mandate_id=mandate.id,
                     payload={"total_paise": checkout.total_paise, "cart_hash": checkout.cart_hash})

    # 1. MANDATE_VALID
    if mandate.status != "ACTIVE" or mandate_is_expired(mandate):
        reason = f"mandate not valid (status={mandate.status})"
        log("GATE_MANDATE_INVALID", "REJECT", reason)
        return GateResult(False, "GATE_REJECTED", reason)
    if mandate.categories is not None and not set(cart_categories).issubset(set(mandate.categories)):
        reason = f"cart categories {cart_categories} not subset of mandate categories {mandate.categories}"
        log("GATE_MANDATE_INVALID", "REJECT", reason)
        return GateResult(False, "GATE_REJECTED", reason)
    log("GATE_MANDATE_VALID", "ALLOW", "mandate ACTIVE, unexpired, categories within scope")

    # 2. HARD CAP — §1: cannot be consented around in-session.
    cap = min(mandate.max_paise or 0, settings.POLICY_PER_TXN_CAP_PAISE)
    if checkout.total_paise > cap:
        reason = "exceeds hard cap — cannot be consented around"
        log("GATE_HARD_CAP", "REJECT", f"{reason} (total {checkout.total_paise} > cap {cap})")
        return GateResult(False, "GATE_REJECTED", reason)
    log("GATE_HARD_CAP", "ALLOW", f"total {checkout.total_paise} <= cap {cap}")

    # 3. DAILY CAP + VELOCITY
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    todays = db.query(Checkout).filter(Checkout.user_id == checkout.user_id,
                                       Checkout.created_at >= today_start).all()
    daily_total = sum(c.total_paise for c in todays if c.id != checkout.id)
    if daily_total + checkout.total_paise > settings.POLICY_DAILY_CAP_PAISE:
        reason = (f"daily cap exceeded ({daily_total}+{checkout.total_paise} > "
                  f"{settings.POLICY_DAILY_CAP_PAISE})")
        log("GATE_DAILY_CAP", "REJECT", reason)
        return GateResult(False, "GATE_REJECTED", reason)
    log("GATE_DAILY_CAP", "ALLOW", f"daily total {daily_total + checkout.total_paise} <= {settings.POLICY_DAILY_CAP_PAISE}")

    hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    recent = db.query(Checkout).filter(Checkout.user_id == checkout.user_id,
                                       Checkout.created_at >= hour_ago,
                                       Checkout.id != checkout.id).count()
    if recent >= settings.POLICY_MAX_TXNS_PER_HOUR:
        reason = f"velocity: {recent} checkouts in last hour >= {settings.POLICY_MAX_TXNS_PER_HOUR}"
        log("GATE_VELOCITY", "REJECT", reason)
        return GateResult(False, "GATE_REJECTED", reason)
    log("GATE_VELOCITY", "ALLOW", f"{recent} checkouts in last hour")

    # 4. CATEGORY allowlist (policy-driven)
    ar = _rule(db, "category_allowlist")
    if ar and ar.enabled:
        allowed = ar.value_json.get("categories", [])
        if not set(cart_categories).issubset(set(allowed)):
            reason = f"category allowlist violation: {cart_categories} not in {allowed}"
            log("GATE_CATEGORY_ALLOWLIST", "REJECT", reason)
            return GateResult(False, "GATE_REJECTED", reason)
        log("GATE_CATEGORY_ALLOWLIST", "ALLOW", f"{cart_categories} within allowlist")

    # 5. STEP-UP triggers — POLICY RULE, not automatic (§1).
    # Defaults: cart_modified_after_proposal (enabled), total_above_paise=0 (disabled).
    for rule in db.query(PolicyRule).filter_by(rule_type="stepup_trigger", enabled=True).all():
        if rule.name == "cart_modified_after_proposal" and rule.value_json.get("enabled") and modified_after_proposal:
            log("GATE_STEPUP", "REJECT", "cart modified after proposal — user cart approval required")
            return GateResult(False, "AWAITING_CART_APPROVAL", step_up=True)
        threshold = rule.value_json.get("total_above_paise", 0) if rule.name == "total_above_paise" else 0
        if threshold and checkout.total_paise > threshold:
            log("GATE_STEPUP", "REJECT", f"total {checkout.total_paise} > step-up threshold {threshold}")
            return GateResult(False, "AWAITING_CART_APPROVAL", step_up=True)
    log("GATE_STEPUP", "ALLOW", "no step-up trigger fired")

    return GateResult(True, "ALLOW")
