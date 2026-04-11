from fastapi import APIRouter, Depends
from app.core.security import require_roles
from app.models.enums import Roles
from app.routers.emi.service import (
    apply_emi_penalty,
    list_emi_monitoring,
    process_emi_defaults,
    refresh_escalations,
    refresh_overdue_statuses,
)
from app.routers.emi.schemas import ApplyPenaltyPayload, ProcessDefaultsPayload

router = APIRouter(tags=["emi"])


@router.get("/monitoring")
async def emi_monitoring(user=Depends(require_roles(Roles.ADMIN))):
    return await list_emi_monitoring()


@router.post("/{emi_id}/apply-penalty")
async def apply_penalty(emi_id: str, payload: ApplyPenaltyPayload, user=Depends(require_roles(Roles.ADMIN))):
    return await apply_emi_penalty(emi_id, user["_id"], payload.penalty_amount, payload.reason)


@router.post("/_refresh-overdue")
async def refresh_overdue(user=Depends(require_roles(Roles.ADMIN))):
    return await refresh_overdue_statuses()


@router.post("/_refresh-escalations")
async def refresh_escalation_cases(user=Depends(require_roles(Roles.ADMIN))):
    return await refresh_escalations()


@router.post("/_process-defaults")
async def process_defaults(payload: ProcessDefaultsPayload | None = None, user=Depends(require_roles(Roles.ADMIN))):
    return await process_emi_defaults(
        admin_id=user["_id"],
        grace_days=(payload.grace_days if payload and payload.grace_days is not None else 3),
        penalty_rate=(payload.penalty_rate if payload and payload.penalty_rate is not None else 0.02),
        freeze_after_missed=(payload.freeze_after_missed if payload and payload.freeze_after_missed is not None else 2),
    )


