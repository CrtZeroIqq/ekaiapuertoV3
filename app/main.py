"""
EKAIA Puerto - Main Application
FastAPI server for vehicle tracking and license plate recognition
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import HTTPException as FastAPIHTTPException

from app.api.auth import router as auth_router
from app.api.auth import get_current_user   # ⬅️ IMPORTANTE: agregado para proteger "/"
import uvicorn

# 🔧 FIX: YOLOv8 compatibility with PyTorch 2.6+
import torch
_original_load = torch.load
torch.load = lambda *args, **kwargs: _original_load(*args, **{**kwargs, 'weights_only': False})

from app.config import get_settings
from app.models import DatabaseManager
from app.services import (
    get_stream_manager,
    get_detector,
    get_ocr_service,
    start_memory_manager,
    stop_memory_manager,
)
from app.api import streams, detection, websocket, system, analytics, billing, reports, alerts, clients

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown"""

    logger.info("🚀 Starting EKAIA Puerto...")

    db_manager = DatabaseManager(settings.database_url)
    try:
        await db_manager.init_db()
        logger.info("✅ Database initialized")
    except Exception as e:
        logger.error(f"❌ Database init failed: {e}")
        logger.warning("⚠️  Continuing without database...")

    # YOLO
    detector = None
    try:
        logger.info(f"🔍 Loading YOLO model: {settings.yolo_model_path}")
        detector = get_detector(
            settings.yolo_model_path,
            settings.yolo_device,
            settings.yolo_confidence
        )
        logger.info("✅ YOLO model loaded successfully")
    except Exception as e:
        logger.error(f"❌ YOLO init failed: {e}")

    # OCR
    ocr = None
    try:
        logger.info(f"📝 Initializing OCR (GPU={settings.ocr_gpu})")
        ocr = get_ocr_service(use_gpu=settings.ocr_gpu)
        logger.info("✅ OCR service initialized")
    except Exception as e:
        logger.error(f"❌ OCR init failed: {e}")

    # RTSP streams
    stream_manager = get_stream_manager()
    try:
        stream_manager.add_stream("entrada", settings.rtsp_entrada)
        logger.info(f"✅ Entrance stream started: {settings.rtsp_entrada}")
    except Exception as e:
        logger.error(f"❌ Entrance stream failed: {e}")

    try:
        stream_manager.add_stream("salida", settings.rtsp_salida)
        logger.info(f"✅ Exit stream started: {settings.rtsp_salida}")
    except Exception as e:
        logger.error(f"❌ Exit stream failed: {e}")

    # Detection loop
    if detector:
        try:
            from app.api.detection import start_detection_loop
            start_detection_loop()
            logger.info("✅ Detection loop started")
        except Exception as e:
            logger.error(f"❌ Detection loop failed: {e}")

    # Memory manager
    try:
        start_memory_manager()
        logger.info("✅ Memory manager started (5min interval)")
    except Exception as e:
        logger.error(f"❌ Memory manager failed: {e}")

    logger.info("🎯 EKAIA Puerto ready!")

    yield

    # Shutdown
    logger.info("🛑 Shutting down EKAIA Puerto...")
    try:
        from app.api.detection import stop_detection_loop
        stop_detection_loop()
    except:
        pass
    try:
        await stop_memory_manager()
        logger.info("✅ Memory manager stopped")
    except:
        pass
    stream_manager.stop_all()


# Create FastAPI app
app = FastAPI(
    title="EKAIA Puerto",
    description="Logistics platform for vehicle tracking at Iquique Port",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# Routers
app.include_router(auth_router)

@app.get("/login")
async def login_page():
    return FileResponse("frontend/login.html")

@app.get("/users")
async def users_page():
    return FileResponse("frontend/users.html")


# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include other routers
app.include_router(streams.router)
app.include_router(detection.router)
app.include_router(websocket.router)
app.include_router(system.router)
app.include_router(analytics.router)
app.include_router(billing.router)
app.include_router(reports.router)
app.include_router(alerts.router)
app.include_router(clients.router)

# Static files
try:
    app.mount("/static", StaticFiles(directory="frontend"), name="static")
except Exception:
    logger.warning("⚠️  Frontend directory not found")


# -------------------------------------------------------
# 🔐 PROTECCIÓN DEL DASHBOARD (ruta "/")
# -------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def root(user = Depends(get_current_user)):
    """
    Si NO está autenticado -> get_current_user lanza 401
    Y el handler de abajo redirige a /login automáticamente.
    """
    try:
        with open("frontend/index.html", "r") as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>Dashboard</h1>"


# -------------------------------------------------------
# 🔄 HANDLER para redirigir al login cuando 401
#     SOLO en rutas no-API (evita el loop infinito)
# -------------------------------------------------------
@app.exception_handler(FastAPIHTTPException)
async def custom_http_exception_handler(request: Request, exc: FastAPIHTTPException):

    # Si es API (`/api/...`) NO debe redirigir → evitar loop
    if request.url.path.startswith("/api"):
        return HTMLResponse(exc.detail, status_code=exc.status_code)

    # Si no es API y el error es 401 → mandar al login
    if exc.status_code == 401:
        return RedirectResponse(url="/login")

    # Otros errores → respuesta normal
    return HTMLResponse(exc.detail, status_code=exc.status_code)


@app.get("/health")
async def health_check():
    stream_manager = get_stream_manager()
    entrada = stream_manager.get_stream("entrada")
    salida = stream_manager.get_stream("salida")

    try:
        from app.api.detection import get_detection_loop
        detection_loop = get_detection_loop()
        detection_running = detection_loop.is_running
    except:
        detection_running = False

    return {
        "status": "healthy",
        "streams": {
            "entrada": entrada.is_alive() if entrada else False,
            "salida": salida.is_alive() if salida else False
        },
        "detection": {
            "running": detection_running
        }
    }


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
        workers=1,
        log_level="info"
    )
