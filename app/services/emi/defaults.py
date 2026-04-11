from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException

from ...database.mongo import get_db
from ...utils.dates import next_month_date
from ..audit_service import write_audit_log
from ..wallet_service import debit_wallet
from .constants import DEFAULT_EMI_GRACE_DAYS, DEFAULT_FREEZE_AFTER_MISSED, DEFAULT_PENALTY_RATE
from .helpers import _customer_query
from .monitoring import list_emi_monitoring, refresh_overdue_statuses
from .notifications import create_customer_notification
from .penalties import apply_emi_penalty
from .schedule import pay_next_installment


async def process_emi_defaults(
    *,
    admin_id: str | int | None = None,
    grace_days: int = DEFAULT_EMI_GRACE_DAYS,
    penalty_rate: float = DEFAULT_PENALTY_RATE,
    freeze_after_missed: int = DEFAULT_FREEZE_AFTER_MISSED,
) -> dict:
    db = await get_db()
    now = datetime.utcnow()
    await refresh_overdue_statuses(now)

    monitoring = await list_emi_monitoring()
    processed = 0
    reminders_sent = 0
    penalties_added = 0
    frozen_accounts = 0
    auto_debits_success = 0
    insufficient_cases = 0

    for loan_row in monitoring.get("loans", []):
        overdue_count = int(loan_row.get("overdue_installments") or 0)
        if overdue_count <= 0:
            continue

        overdue_items = loan_row.get("overdue_emis") or []
        if not overdue_items:
            continue
        processed += 1
        first_overdue = overdue_items[0]
        due_date = first_overdue.get("due_date")
        if not isinstance(due_date, datetime):
            continue

        days_overdue = (now - due_date).days
        if days_overdue < max(1, int(grace_days)):
            continue

        loan_id = loan_row.get("loan_id")
        customer_id = loan_row.get("customer_id")
        loan_collection = loan_row.get("loan_collection")
        emi_amount = float(first_overdue.get("emi_amount") or 0.0)
        penalty_amount = float(first_overdue.get("penalty_amount") or 0.0)
        emi_id = first_overdue.get("emi_id")

        if emi_id and emi_amount > 0 and penalty_amount <= 0:
            penalty_to_add = round(max(1.0, emi_amount * max(0.0, float(penalty_rate))), 2)
            try:
                await apply_emi_penalty(
                    str(emi_id),
                    str(admin_id or "system"),
                    penalty_to_add,
                    reason=f"Auto-penalty after {days_overdue} overdue days",
                )
                penalties_added += 1
                penalty_amount = penalty_to_add
            except Exception:
                pass

        try:
            await create_customer_notification(
                customer_id,
                title="EMI payment reminder",
                message=(
                    f"Your loan {loan_id} EMI is overdue by {days_overdue} day(s). "
                    f"Please maintain wallet balance for auto-debit."
                ),
                kind="warning",
                meta={"loan_id": loan_id, "days_overdue": days_overdue, "loan_collection": loan_collection},
            )
            reminders_sent += 1
        except Exception:
            pass

        if overdue_count < max(1, int(freeze_after_missed)):
            continue

        # Freeze account transactions after repeated misses.
        try:
            user = await db.users.find_one(_customer_query(customer_id))
            if user and not bool(user.get("account_frozen")):
                await db.users.update_one(
                    {"_id": user["_id"]},
                    {
                        "$set": {
                            "account_frozen": True,
                            "account_frozen_at": now,
                            "account_frozen_reason": "Repeated EMI defaults",
                        }
                    },
                )
                frozen_accounts += 1
        except Exception:
            pass

        total_due = round(emi_amount + penalty_amount, 2)
        if total_due <= 0:
            continue

        try:
            wallet_txn = await debit_wallet(
                customer_id,
                total_due,
                f"Auto-debit for overdue EMI loan {loan_id}",
            )
            loan = await db[loan_collection].find_one({"loan_id": loan_id, "customer_id": customer_id})
            if loan:
                remaining_tenure = int(loan.get("remaining_tenure") or 0) - 1
                remaining_amount = float(loan.get("remaining_amount") or 0) - emi_amount
                await db[loan_collection].update_one(
                    {"_id": loan["_id"]},
                    {
                        "$set": {
                            "remaining_tenure": remaining_tenure,
                            "remaining_amount": remaining_amount,
                            "status": "completed" if remaining_tenure <= 0 else "active",
                            "next_emi_date": next_month_date(),
                            "total_paid": float(loan.get("total_paid") or 0) + total_due,
                            "penalties_paid_total": float(loan.get("penalties_paid_total") or 0) + penalty_amount,
                        }
                    },
                )
            await pay_next_installment(
                loan_id,
                customer_id,
                paid_total_amount=total_due,
                paid_emi_amount=emi_amount,
                paid_penalty_amount=penalty_amount,
            )
            await create_customer_notification(
                customer_id,
                title="Auto-debit successful",
                message=f"INR {total_due:,.2f} was auto-debited towards overdue EMI for loan {loan_id}.",
                kind="success",
                meta={"loan_id": loan_id, "amount": total_due, "wallet_transaction_id": wallet_txn.get("transaction_id")},
            )
            auto_debits_success += 1
        except HTTPException:
            insufficient_cases += 1
            severe_message = (
                f"Your account is frozen due to repeated EMI defaults. "
                f"Insufficient wallet balance for auto-debit of INR {total_due:,.2f}."
            )
            if str(loan_collection) == "home_loans":
                severe_message += " Property recovery/auction process may be initiated."
            else:
                severe_message += " Recovery complaint process may be initiated."
            try:
                await create_customer_notification(
                    customer_id,
                    title="Urgent EMI default action",
                    message=severe_message,
                    kind="error",
                    meta={"loan_id": loan_id, "loan_collection": loan_collection, "amount_due": total_due},
                )
            except Exception:
                pass

    await write_audit_log(
        action="emi_default_process",
        actor_role="admin" if admin_id else "system",
        actor_id=admin_id or "system",
        entity_type="emi",
        entity_id="bulk",
        details={
            "processed_loans": processed,
            "reminders_sent": reminders_sent,
            "penalties_added": penalties_added,
            "frozen_accounts": frozen_accounts,
            "auto_debits_success": auto_debits_success,
            "insufficient_cases": insufficient_cases,
            "grace_days": grace_days,
            "penalty_rate": penalty_rate,
            "freeze_after_missed": freeze_after_missed,
        },
    )

    return {
        "processed_loans": processed,
        "reminders_sent": reminders_sent,
        "penalties_added": penalties_added,
        "frozen_accounts": frozen_accounts,
        "auto_debits_success": auto_debits_success,
        "insufficient_cases": insufficient_cases,
        "grace_days": grace_days,
        "penalty_rate": penalty_rate,
        "freeze_after_missed": freeze_after_missed,
        "generated_at": now,
    }
