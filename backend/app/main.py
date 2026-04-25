from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.auth import require_session
from app.routers.access import router as access_router
from app.routers.bootstrap import router as bootstrap_router
from app.routers.ebill import public_router as ebill_public_router
from app.routers.ebill import router as ebill_router
from app.routers.health import router as health_router
from app.routers.menu import router as menu_router
from app.routers.orders import router as orders_router
from app.routers.reports import router as reports_router
from app.routers.settings import router as settings_router
from app.routers.sync import router as sync_router


app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(access_router, prefix="/api")
app.include_router(ebill_public_router)
app.include_router(bootstrap_router, prefix="/api", dependencies=[Depends(require_session)])
app.include_router(menu_router, prefix="/api", dependencies=[Depends(require_session)])
app.include_router(orders_router, prefix="/api", dependencies=[Depends(require_session)])
app.include_router(sync_router, prefix="/api", dependencies=[Depends(require_session)])
app.include_router(reports_router, prefix="/api", dependencies=[Depends(require_session)])
app.include_router(settings_router, prefix="/api", dependencies=[Depends(require_session)])
app.include_router(ebill_router, prefix="/api", dependencies=[Depends(require_session)])
