from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException

from ...database.mongo import get_db
from ...utils.dates import next_month_date
from ...utils.serializers import normalize_doc
from .constants import EMI_STATUS_OVERDUE, EMI_STATUS_PAID, EMI_STATUS_PENDING


async def ensure_emi_schedule_generated(loan_collection: str, loan: dict) -> int:
    """Generate EMI schedule documents for a loan if not already present.

    Returns number of installments created (0 if schedule already existed).
    """
    db = await get_db()
    loan_id = loan.get("loan_id")
    if loan_id is None:
        raise HTTPException(status_code=400, detail="Loan missing loan_id")

    existing = await db.emi_schedules.count_documents({"loan_id": loan_id})
    if existing > 0:
        return 0

    tenure = int(loan.get("tenure_months") or 0)
    if tenure <= 0:
        raise HTTPException(status_code=400, detail="Invalid tenure_months for EMI schedule generation")

    emi_amount = float(loan.get("emi_per_month") or 0)
    if emi_amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid emi_per_month for EMI schedule generation")

    principal = float(loan.get("approved_amount") or loan.get("loan_amount") or 0)
    if principal <= 0:
        raise HTTPException(status_code=400, detail="Invalid principal for EMI schedule generation")

    annual_rate = float(loan.get("interest_rate") or 0)
    if annual_rate <= 0:
        raise HTTPException(status_code=400, detail="Invalid interest_rate for EMI schedule generation")

    monthly_rate = annual_rate / 12.0 / 100.0

    first_due = loan.get("next_emi_date") or next_month_date()
    if isinstance(first_due, str):
        # tolerate string dates if stored inconsistently
        first_due = datetime.fromisoformat(first_due.replace("Z", "+00:00"))

    now = datetime.utcnow()
    docs = []
    due = first_due
    opening_balance = principal
    for installment_no in range(1, tenure + 1):
        interest_component = round(opening_balance * monthly_rate, 2)
        principal_component = round(float(emi_amount) - interest_component, 2)
        if installment_no == tenure:
            # avoid rounding drift on last installment
            principal_component = round(opening_balance, 2)
            interest_component = round(float(emi_amount) - principal_component, 2)
        closing_balance = round(max(0.0, opening_balance - principal_component), 2)

        docs.append(
            {
                "loan_id": loan_id,
                "loan_collection": loan_collection,
                "customer_id": loan.get("customer_id"),
                "installment_no": installment_no,
                "due_date": due,
                "emi_amount": emi_amount,
                "opening_balance": round(opening_balance, 2),
                "principal_amount": principal_component,
                "interest_amount": interest_component,
                "closing_balance": closing_balance,
                "status": EMI_STATUS_PENDING,
                "paid_amount": None,
                "paid_emi_amount": None,
                "paid_penalty_amount": None,
                "paid_at": None,
                "penalty_amount": 0.0,
                "penalty_reason": None,
                "penalty_applied_by": None,
                "penalty_applied_at": None,
                "created_at": now,
                "updated_at": now,
            }
        )
        due = next_month_date(due)
        opening_balance = closing_balance

    await db.emi_schedules.insert_many(docs)
    return len(docs)


async def pay_next_installment(
    loan_id: int,
    customer_id: str | int,
    *,
    paid_total_amount: float,
    paid_emi_amount: float,
    paid_penalty_amount: float,
):
    """Mark the earliest non-paid EMI installment as paid (best-effort)."""
    db = await get_db()
    now = datetime.utcnow()
    emi = await db.emi_schedules.find_one(
        {
            "loan_id": loan_id,
            "customer_id": customer_id,
            "status": {"$in": [EMI_STATUS_PENDING, EMI_STATUS_OVERDUE]},
        },
        sort=[("due_date", 1)],
    )
    if not emi:
        return None

    await db.emi_schedules.update_one(
        {"_id": emi["_id"]},
        {
            "$set": {
                "status": EMI_STATUS_PAID,
                "paid_amount": float(paid_total_amount),
                "paid_emi_amount": float(paid_emi_amount),
                "paid_penalty_amount": float(paid_penalty_amount),
                "paid_at": now,
                "updated_at": now,
            }
        },
    )
    emi["status"] = EMI_STATUS_PAID
    emi["paid_amount"] = float(paid_total_amount)
    emi["paid_emi_amount"] = float(paid_emi_amount)
    emi["paid_penalty_amount"] = float(paid_penalty_amount)
    emi["paid_at"] = now
    emi["updated_at"] = now
    return normalize_doc(emi)
