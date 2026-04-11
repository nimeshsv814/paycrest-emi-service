from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException

from ...database.mongo import get_db
from ...utils.id import to_object_id
from ...utils.serializers import normalize_doc
from ..audit_service import write_audit_log
from .notifications import create_customer_notification


async def apply_emi_penalty(emi_id: str, admin_id: str | int, penalty_amount: float, reason: str | None = None):
    db = await get_db()
    oid = to_object_id(emi_id)

    emi = await db.emi_schedules.find_one({"_id": oid})
    if not emi:
        raise HTTPException(status_code=404, detail="EMI not found")

    amt = float(penalty_amount)
    if amt <= 0:
        raise HTTPException(status_code=400, detail="penalty_amount must be > 0")

    now = datetime.utcnow()
    await db.emi_schedules.update_one(
        {"_id": oid},
        {
            "$set": {
                "penalty_amount": amt,
                "penalty_reason": reason,
                "penalty_applied_by": str(admin_id),
                "penalty_applied_at": now,
                "updated_at": now,
            }
        },
    )
    await write_audit_log(
        action="emi_penalty_apply",
        actor_role="admin",
        actor_id=admin_id,
        entity_type="emi",
        entity_id=str(emi.get("_id")),
        details={"loan_id": emi.get("loan_id"), "penalty_amount": amt, "reason": reason},
    )
    try:
        await create_customer_notification(
            emi.get("customer_id"),
            title="EMI penalty added",
            message=(
                f"A penalty of INR {amt:,.2f} was added to installment #{emi.get('installment_no')} "
                f"for loan {emi.get('loan_id')}. Reason: {reason or 'EMI overdue'}."
            ),
            kind="warning",
            meta={"loan_id": emi.get("loan_id"), "installment_no": emi.get("installment_no"), "penalty_amount": amt},
        )
    except Exception:
        pass
    emi = await db.emi_schedules.find_one({"_id": oid})
    return normalize_doc(emi)
