from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..ledger import verify_chain
from ..models import Checkout, DemoSession, LedgerEntry, Mandate, PolicyRule
from ..security import require_user

router = APIRouter()


def _entry_out(e: LedgerEntry) -> dict:
    return {"seq": e.seq, "ts": e.ts, "actor": e.actor, "action_type": e.action_type,
            "decision": e.decision, "reason": e.reason,
            "checkout_id": str(e.checkout_id) if e.checkout_id else None,
            "mandate_id": str(e.mandate_id) if e.mandate_id else None,
            "payload": e.payload_json, "entry_hash": e.entry_hash}


@router.get("/v1/audit/actions")
def audit_by_ref(ref: str = "", db: Session = Depends(get_db), _=Depends(require_user)):
    q = db.query(LedgerEntry).order_by(LedgerEntry.seq)
    if ref:
        q = q.filter((LedgerEntry.checkout_id == ref) | (LedgerEntry.mandate_id == ref))
    return [_entry_out(e) for e in q.all()]


@router.get("/v1/audit/actions/{seq}")
def audit_one(seq: int, db: Session = Depends(get_db), _=Depends(require_user)):
    e = db.get(LedgerEntry, seq)
    if not e:
        raise HTTPException(404, "entry not found")
    out = _entry_out(e)
    # Full decision record: mandates used, rules fired, verdicts, LLM rationale, razorpay ids.
    if e.checkout_id:
        co = db.get(Checkout, e.checkout_id)
        if co:
            out["decision_record"] = {
                "checkout": {"id": str(co.id), "status": co.status,
                             "total_paise": co.total_paise, "rationale": co.rationale,
                             "razorpay_order_id": co.razorpay_order_id,
                             "razorpay_payment_link_id": co.razorpay_payment_link_id,
                             "retries_used": co.retries_used},
                "related_entries": [_entry_out(x) for x in db.query(LedgerEntry)
                                    .filter(LedgerEntry.checkout_id == e.checkout_id)
                                    .order_by(LedgerEntry.seq).all()],
            }
    if e.mandate_id:
        m = db.get(Mandate, e.mandate_id)
        if m:
            out["decision_record"] = out.get("decision_record") or {}
            out["decision_record"]["mandate"] = {
                "id": str(m.id), "kind": m.kind, "status": m.status,
                "max_paise": m.max_paise, "categories": m.categories,
                "expires_at": m.expires_at}
    return out


@router.get("/v1/audit/verify")
def audit_verify(db: Session = Depends(get_db), _=Depends(require_user)):
    return verify_chain(db)


class RuleIn(BaseModel):
    name: str
    rule_type: str
    value_json: dict
    enabled: bool


@router.get("/v1/policies")
def get_policies(db: Session = Depends(get_db), _=Depends(require_user)):
    return [{"id": r.id, "name": r.name, "rule_type": r.rule_type,
             "value_json": r.value_json, "enabled": r.enabled, "updated_at": r.updated_at}
            for r in db.query(PolicyRule).order_by(PolicyRule.id).all()]


@router.put("/v1/policies")
def put_policy(body: RuleIn, db: Session = Depends(get_db), _=Depends(require_user)):
    r = db.query(PolicyRule).filter_by(name=body.name).first()
    if not r:
        r = PolicyRule(name=body.name, rule_type=body.rule_type)
        db.add(r)
    r.rule_type = body.rule_type
    r.value_json = body.value_json
    r.enabled = body.enabled
    db.commit()
    return {"ok": True}


@router.get("/v1/stats/aov")
def aov(db: Session = Depends(get_db), _=Depends(require_user)):
    sessions = db.query(DemoSession).all()
    ai = [s.total_paise for s in sessions if s.with_ai]
    base = [s.total_paise for s in sessions if not s.with_ai]
    return {
        "ai_assisted_aov_paise": sum(ai) // len(ai) if ai else 0,
        "baseline_aov_paise": sum(base) // len(base) if base else 0,
        "is_simulated": True,
    }
