from __future__ import annotations

from datetime import datetime

from ...database.mongo import get_db
from .constants import EMI_ESCALATION_CLOSED, EMI_ESCALATION_OPEN, EMI_STATUS_OVERDUE, EMI_STATUS_PENDING
from .helpers import _customer_query


async def refresh_overdue_statuses(now: datetime | None = None) -> dict:
    db = await get_db()
    now = now or datetime.utcnow()

    res = await db.emi_schedules.update_many(
        {"status": EMI_STATUS_PENDING, "due_date": {"$lt": now}},
        {"$set": {"status": EMI_STATUS_OVERDUE, "updated_at": now}},
    )
    return {"marked_overdue": int(res.modified_count)}


async def refresh_escalations(now: datetime | None = None, *, limit_loans: int = 1000) -> dict:
    """Create/update escalation cases for loans with 3+ consecutive missed EMIs."""
    db = await get_db()
    now = now or datetime.utcnow()

    active_loans: list[dict] = []
    for loan in await db.personal_loans.find({"status": "active"}).to_list(length=limit_loans):
        loan = {**loan, "loan_collection": "personal_loans"}
        active_loans.append(loan)
    for loan in await db.vehicle_loans.find({"status": "active"}).to_list(length=limit_loans):
        loan = {**loan, "loan_collection": "vehicle_loans"}
        active_loans.append(loan)
    for loan in await db.education_loans.find({"status": "active"}).to_list(length=limit_loans):
        loan = {**loan, "loan_collection": "education_loans"}
        active_loans.append(loan)
    for loan in await db.home_loans.find({"status": "active"}).to_list(length=limit_loans):
        loan = {**loan, "loan_collection": "home_loans"}
        active_loans.append(loan)

    opened = 0
    updated = 0
    closed = 0

    for loan in active_loans:
        loan_id = loan.get("loan_id")
        cust_id = loan.get("customer_id")
        loan_collection = loan.get("loan_collection")
        if loan_id is None or cust_id is None or not loan_collection:
            continue

        unpaid = (
            await db.emi_schedules.find(
                {
                    "loan_id": loan_id,
                    "customer_id": cust_id,
                    "status": {"$in": [EMI_STATUS_PENDING, EMI_STATUS_OVERDUE]},
                }
            )
            .sort("due_date", 1)
            .to_list(length=60)
        )

        consecutive_missed = 0
        first_missed_due = None
        for e in unpaid:
            due = e.get("due_date")
            if due and due < now:
                if first_missed_due is None:
                    first_missed_due = due
                consecutive_missed += 1
            else:
                break

        esc = await db.emi_escalations.find_one({"loan_id": loan_id, "customer_id": cust_id, "status": EMI_ESCALATION_OPEN})

        if consecutive_missed >= 3:
            if not esc:
                await db.emi_escalations.insert_one(
                    {
                        "loan_id": loan_id,
                        "loan_collection": loan_collection,
                        "customer_id": cust_id,
                        "status": EMI_ESCALATION_OPEN,
                        "consecutive_missed_emis": consecutive_missed,
                        "first_missed_due_date": first_missed_due,
                        "opened_at": now,
                        "updated_at": now,
                    }
                )
                opened += 1
            else:
                await db.emi_escalations.update_one(
                    {"_id": esc["_id"]},
                    {"$set": {"consecutive_missed_emis": consecutive_missed, "updated_at": now}},
                )
                updated += 1

            await db[loan_collection].update_one(
                {"loan_id": loan_id},
                {"$set": {"emi_escalated": True, "emi_escalated_at": now, "emi_consecutive_missed": consecutive_missed}},
            )
        else:
            if esc:
                await db.emi_escalations.update_one(
                    {"_id": esc["_id"]},
                    {"$set": {"status": EMI_ESCALATION_CLOSED, "closed_at": now, "updated_at": now}},
                )
                closed += 1
            await db[loan_collection].update_one(
                {"loan_id": loan_id},
                {"$set": {"emi_escalated": False, "emi_consecutive_missed": consecutive_missed}},
            )

    return {"opened": opened, "updated": updated, "closed": closed}


async def list_emi_monitoring(limit_loans: int = 500) -> dict:
    """Admin EMI monitoring dashboard based on `emi_schedules` + active loans."""
    db = await get_db()
    now = datetime.utcnow()

    active_loans: list[dict] = []
    for loan in await db.personal_loans.find({"status": "active"}).to_list(length=limit_loans):
        loan = {**loan, "loan_collection": "personal_loans"}
        active_loans.append(loan)
    for loan in await db.vehicle_loans.find({"status": "active"}).to_list(length=limit_loans):
        loan = {**loan, "loan_collection": "vehicle_loans"}
        active_loans.append(loan)
    for loan in await db.education_loans.find({"status": "active"}).to_list(length=limit_loans):
        loan = {**loan, "loan_collection": "education_loans"}
        active_loans.append(loan)
    for loan in await db.home_loans.find({"status": "active"}).to_list(length=limit_loans):
        loan = {**loan, "loan_collection": "home_loans"}
        active_loans.append(loan)

    results = []
    total_overdue_installments = 0
    total_penalty_amount = 0.0
    escalation_loans = 0

    for loan in active_loans:
        loan_id = loan.get("loan_id")
        cust_id = loan.get("customer_id")
        if loan_id is None or cust_id is None:
            continue

        unpaid = (
            await db.emi_schedules.find(
                {
                    "loan_id": loan_id,
                    "customer_id": cust_id,
                    "status": {"$in": [EMI_STATUS_PENDING, EMI_STATUS_OVERDUE]},
                }
            )
            .sort("due_date", 1)
            .to_list(length=1000)
        )

        overdue = [e for e in unpaid if e.get("due_date") and e["due_date"] < now]
        overdue_count = len(overdue)
        total_overdue_installments += overdue_count
        total_penalty_amount += float(sum(float(e.get("penalty_amount") or 0) for e in overdue))

        consecutive_missed = 0
        for e in unpaid:
            due = e.get("due_date")
            if due and due < now:
                consecutive_missed += 1
            else:
                break

        if consecutive_missed >= 3:
            escalation_loans += 1

        account_frozen = False
        try:
            user = await db.users.find_one(_customer_query(cust_id))
            account_frozen = bool((user or {}).get("account_frozen"))
        except Exception:
            account_frozen = False

        overdue_preview = [
            {
                "emi_id": str(e["_id"]),
                "installment_no": e.get("installment_no"),
                "due_date": e.get("due_date"),
                "emi_amount": e.get("emi_amount"),
                "penalty_amount": e.get("penalty_amount"),
                "status": e.get("status"),
            }
            for e in overdue[:10]
        ]

        results.append(
            {
                "loan_id": loan_id,
                "customer_id": cust_id,
                "loan_collection": loan.get("loan_collection"),
                "emi_per_month": loan.get("emi_per_month"),
                "overdue_installments": overdue_count,
                "consecutive_missed_emis": consecutive_missed,
                "next_due_date": unpaid[0]["due_date"] if unpaid else None,
                "account_frozen": account_frozen,
                "recommended_action": (
                    "Freeze + auto-debit + severe notice"
                    if consecutive_missed >= 2
                    else "Reminder + optional penalty"
                ),
                "overdue_emis": overdue_preview,
            }
        )

    return {
        "generated_at": now,
        "active_loans": len(active_loans),
        "total_overdue_installments": total_overdue_installments,
        "total_penalty_amount": round(total_penalty_amount, 2),
        "escalation_loans": escalation_loans,
        "loans": results,
    }
