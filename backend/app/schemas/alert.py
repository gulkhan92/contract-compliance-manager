import uuid
from datetime import datetime

from pydantic import BaseModel

from app.db.enums import AlertStatus, AlertType


class AlertSummary(BaseModel):
    id: uuid.UUID
    obligation_id: uuid.UUID
    alert_type: AlertType
    scheduled_for: datetime
    sent_at: datetime | None
    status: AlertStatus
    recipient_user_id: uuid.UUID

    model_config = {"from_attributes": True}


class AlertScanResponse(BaseModel):
    statuses_recomputed: int
    alerts_sent: int
    alerts_failed: int
    alerts_skipped_duplicate: int
