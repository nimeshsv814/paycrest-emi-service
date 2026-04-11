from pydantic import BaseModel, Field
from typing import Optional

class ApplyPenaltyPayload(BaseModel):
    penalty_amount: float = Field(..., gt=0)
    reason: str = Field(..., min_length=3, max_length=300)

class ProcessDefaultsPayload(BaseModel):
    grace_days: Optional[int] = Field(None, ge=0, le=30)
    penalty_rate: Optional[float] = Field(None, ge=0.0, le=1.0)
    freeze_after_missed: Optional[int] = Field(None, ge=1, le=12)