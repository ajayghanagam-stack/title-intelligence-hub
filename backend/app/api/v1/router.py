from fastapi import APIRouter

from app.api.v1.health import router as health_router
from app.api.v1.auth import router as auth_router
from app.api.v1.admin import router as admin_router
from app.api.v1.organizations import router as organizations_router
from app.api.v1.micro_apps import router as micro_apps_router
from app.api.v1.subscriptions import router as subscriptions_router

api_v1_router = APIRouter(prefix="/api/v1")

api_v1_router.include_router(health_router)
api_v1_router.include_router(auth_router)
api_v1_router.include_router(admin_router)
api_v1_router.include_router(organizations_router)
api_v1_router.include_router(micro_apps_router)
api_v1_router.include_router(subscriptions_router)
