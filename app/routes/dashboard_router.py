"""Dashboard routes — per-user statistics."""
import logging

from fastapi import APIRouter

from app.auth.dependencies import CurrentUser
from app.models.schemas import DashboardStats, PublicUser
from app.services.dashboard_service import get_stats

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStats)
async def dashboard_stats(user: PublicUser = CurrentUser):
    return await get_stats(user)