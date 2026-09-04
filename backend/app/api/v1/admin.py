from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import require_role
from app.db.enums import UserRole
from app.db.models import User

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/ping")
async def ping(
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN))],
) -> dict[str, str]:
    return {"status": "ok", "org_id": str(current_user.org_id)}
