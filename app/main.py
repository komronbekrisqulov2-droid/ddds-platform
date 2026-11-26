import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

from app.config import STATIC_DIR, UPLOADS_DIR, CACHE_DIR, DEBUG
from app.routes.views import views_router
from app.routes.api import api_router
from app.routes.websocket import ws_router
from app.state_engine import state_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure all directories exist
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 60)
    print(" 🚀 DDDS Cloud (Distributed Dual-Display Smart Classroom)")
    print(" 🏛 Universitet Smart Auditoriyalari Boshqaruv Platformasi")
    print(f" 📡 Faol Auditoriyalar: {list(state_manager.rooms.keys())}")
    print("=" * 60)
    yield
    print("🛑 DDDS Cloud to'xtatildi.")


app = FastAPI(
    title="DDDS Cloud",
    description="Distributed Dual-Display Smart Classroom Platform",
    version="2.0.0",
    lifespan=lifespan
)

# GZip compression for ultra-fast payload delivery (< 1000 bytes skipped)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# CORS Middleware for intranet Wi-Fi / LAN multi-device access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Static and Media paths
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")
app.mount("/cache", StaticFiles(directory=str(CACHE_DIR)), name="cache")

# Include Routers
app.include_router(views_router)
app.include_router(api_router)
app.include_router(ws_router)

