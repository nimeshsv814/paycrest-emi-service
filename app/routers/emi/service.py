from ...database.mongo import get_db


async def list_emi_monitoring() -> list:
    try:
        from ...services.emi.monitoring import get_emi_monitoring_list
        db = await get_db()
        return await get_emi_monitoring_list(db)
    except (ImportError, AttributeError):
        db = await get_db()
        docs = await db.emi_schedules.find(
            {"status": {"$in": ["overdue", "escalated", "defaulted"]}}
        ).to_list(length=500)
        from ...utils.serializers import normalize_doc
        return [normalize_doc(d) for d in docs]


async def apply_emi_penalty(
    emi_id: str,
    admin_id,
    penalty_amount: float,
    reason: str,
) -> dict:
    try:
        from ...services.emi.penalties import apply_penalty
        db = await get_db()
        return await apply_penalty(db, emi_id, admin_id, penalty_amount, reason)
    except (ImportError, AttributeError):
        db = await get_db()
        from bson import ObjectId
        from ...utils.serializers import normalize_doc
        try:
            filt = {"_id": ObjectId(emi_id)}
        except Exception:
            filt = {"emi_id": emi_id}
        await db.emi_schedules.update_one(
            filt,
            {
                "$inc": {"penalty_amount": penalty_amount},
                "$set": {"penalty_reason": reason, "status": "penalized"},
            },
        )
        updated = await db.emi_schedules.find_one(filt)
        return normalize_doc(updated) if updated else {"emi_id": emi_id, "status": "penalized"}


async def refresh_overdue_statuses() -> dict:
    try:
        from ...services.emi.schedule import refresh_overdue
        db = await get_db()
        return await refresh_overdue(db)
    except (ImportError, AttributeError):
        return {"status": "skipped", "reason": "refresh_overdue not available"}


async def refresh_escalations() -> dict:
    try:
        from ...services.emi.schedule import refresh_escalations as _refresh
        db = await get_db()
        return await _refresh(db)
    except (ImportError, AttributeError):
        return {"status": "skipped", "reason": "refresh_escalations not available"}


async def process_emi_defaults(
    admin_id,
    grace_days: int = 3,
    penalty_rate: float = 0.02,
    freeze_after_missed: int = 2,
) -> dict:
    try:
        from ...services.emi.defaults import process_defaults
        db = await get_db()
        return await process_defaults(
            db,
            admin_id=admin_id,
            grace_days=grace_days,
            penalty_rate=penalty_rate,
            freeze_after_missed=freeze_after_missed,
        )
    except (ImportError, AttributeError):
        try:
            from ...services.emi.penalties import process_defaults as _pd
            db = await get_db()
            return await _pd(db, admin_id=admin_id, grace_days=grace_days)
        except (ImportError, AttributeError):
            return {"status": "skipped", "reason": "process_defaults not available"}