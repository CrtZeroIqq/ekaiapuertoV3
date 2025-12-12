# 🏗️ EKAIA Puerto - Arquitectura Técnica

## 📐 Diseño del Sistema

### Visión General

```
┌─────────────────────────────────────────────────────────┐
│                    EKAIA PUERTO                         │
│         Sistema Logístico Portuario Inteligente        │
└─────────────────────────────────────────────────────────┘

                    ┌─────────────┐
                    │  Cloudflare │
                    │   Tunnel    │
                    └──────┬──────┘
                           │ HTTPS
            ┌──────────────┼──────────────┐
            │                              │
    ┌───────▼────────┐           ┌────────▼───────┐
    │  Web Dashboard │           │  External APIs │
    │   (Browser)    │           │   (Mobile)     │
    └───────┬────────┘           └────────┬───────┘
            │                              │
            └──────────────┬───────────────┘
                           │
                  ┌────────▼─────────┐
                  │   FastAPI App    │
                  │  (app/main.py)   │
                  └────────┬─────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
  ┌─────▼─────┐    ┌──────▼──────┐   ┌──────▼──────┐
  │  Streams  │    │ Detection   │   │  WebSocket  │
  │    API    │    │     API     │   │  Real-time  │
  └─────┬─────┘    └──────┬──────┘   └──────┬──────┘
        │                  │                  │
  ┌─────▼──────────────────▼──────────────────▼─────┐
  │              Service Layer                      │
  │  ┌──────────┐ ┌──────────┐ ┌──────────────┐   │
  │  │ RTSP     │ │  YOLO    │ │   Tracker    │   │
  │  │ Manager  │ │ Detector │ │   Service    │   │
  │  └─────┬────┘ └─────┬────┘ └──────┬───────┘   │
  │        │            │              │            │
  │  ┌─────▼────┐ ┌─────▼─────┐ ┌─────▼──────┐   │
  │  │ Camera   │ │    OCR    │ │   MySQL    │   │
  │  │ Streams  │ │  Service  │ │  Database  │   │
  │  └──────────┘ └───────────┘ └────────────┘   │
  └─────────────────────────────────────────────────┘
           │              │              │
  ┌────────▼────┐  ┌──────▼──────┐  ┌──▼────┐
  │   Dahua     │  │  NVIDIA GPU │  │ MySQL │
  │ 107 / 108   │  │  RTX 5070   │  │Docker │
  └─────────────┘  └─────────────┘  └───────┘
```

---

## 🔄 Flujo de Datos

### 1. Detección en Tiempo Real

```
Cámara RTSP → RTSPStream → Frame Buffer → YOLO Detector
                                              ↓
                                         Detections
                                              ↓
                    ┌─────────────────────────┴─────────────┐
                    │                                       │
              Vehicle (class 0)                    Plate (class 1)
                    │                                       │
                    └──────────────┬────────────────────────┘
                                   │
                            OCR Service
                            (PaddleOCR)
                                   │
                         Normalized Plate Text
                                   │
                            Vehicle Tracker
                                   │
                    ┌──────────────┴─────────────┐
                    │                            │
              Entry Camera                  Exit Camera
                    │                            │
              register_entry()            register_exit()
                    │                            │
                    └──────────┬─────────────────┘
                               │
                          MySQL Insert
                               │
                      Vehicle Record Created
                               │
                          WebSocket Push
                               │
                      Dashboard Update
```

### 2. Streaming Pipeline

```
RTSP Source (Dahua)
    │ rtsp://192.168.88.107:554/...
    │
    ▼
cv2.VideoCapture (FFmpeg backend)
    │ TCP transport, H.264 codec
    │
    ▼
Background Thread (read_loop)
    │ Continuous frame grab
    │ Auto-reconnect on failure
    │
    ▼
Queue (buffer_size=2)
    │ Drop old frames if full
    │ Minimize latency
    │
    ▼
Latest Frame (last_frame)
    │
    ├──► YOLO Detection (GPU)
    │
    ├──► JPEG Encoding (quality=85)
    │       │
    │       ▼
    │    MJPEG Stream (/stream/entrada)
    │       │
    │       ▼
    │    Browser <img> tag
    │
    └──► WebSocket Processing
            │
            ▼
         Dashboard Updates
```

---

## 🧩 Módulos Detallados

### RTSPStream (`app/services/rtsp_stream.py`)

**Propósito:** Gestión robusta de streams RTSP con auto-reconexión

**Características:**
- Thread-safe buffering
- Auto-reconnect con backoff exponencial
- Low-latency mode (buffer=1)
- MJPEG generation para HTTP streaming

**Patrón de Diseño:** Producer-Consumer con Queue

```python
class RTSPStream:
    - connect() → Abre VideoCapture
    - _read_loop() → Thread background
    - read() → Consume frame (blocking)
    - generate_jpeg_stream() → Generator MJPEG
```

**Optimizaciones:**
- Buffer size = 1 (latencia < 500ms)
- Frame dropping si queue full
- Reconnect inteligente (max 10 fallos)

---

### YOLODetector (`app/services/yolo_detector.py`)

**Propósito:** Detección GPU-accelerated de vehículos y patentes

**Modelo:** Ultralytics YOLOv8 custom trained
- Class 0: Vehicle
- Class 1: License Plate

**Características:**
- GPU warmup en startup
- Singleton pattern (evita reload)
- NMS con IoU threshold
- Bounding box normalizado

**Optimizaciones:**
- torch.cuda + CUDA 12.4
- stream=False (mejor para single frame)
- conf threshold ajustable (.env)

```python
class YOLODetector:
    - __init__() → Load model + warmup
    - detect() → Run inference
    - detect_plates() → Filter class 1
    - draw_detections() → Visualización
```

**Performance:**
- Inference time: ~50ms @ 640x640
- GPU memory: ~2GB
- Throughput: 20 FPS

---

### LicensePlateOCR (`app/services/ocr_service.py`)

**Propósito:** Reconocimiento de patentes chilenas

**Motor:** PaddleOCR (más rápido que EasyOCR)

**Pipeline:**
1. **Preprocessing**
   - Resize (min height 60px)
   - Grayscale conversion
   - CLAHE (contrast enhancement)
   - Fast NL Means denoising
   - Otsu binarization

2. **OCR Inference**
   - PaddleOCR con GPU
   - Angle classification enabled
   - Detection + Recognition

3. **Postprocessing**
   - Normalización (remove spaces, special chars)
   - Correction (O→0, I→1, S→5)
   - Validación formato chileno

**Patrones Soportados:**
- ABCD12 (4 letras + 2 dígitos)
- AB1234 (2 letras + 4 dígitos)
- ABC123 (3 letras + 3 dígitos)

```python
class LicensePlateOCR:
    - preprocess_plate() → Image enhancement
    - extract_text() → OCR inference
    - normalize_text() → Format correction
    - validate_plate() → Pattern matching
```

**Performance:**
- OCR time: ~100-150ms per plate
- Accuracy: >95% en condiciones óptimas
- GPU usage: ~1GB

---

### VehicleTracker (`app/services/tracker.py`)

**Propósito:** Lógica de tracking entrada/salida

**Database:** MySQL async con SQLAlchemy

**Operaciones:**

1. **register_entry()**
   - Busca vehículo ya dentro
   - Si existe → update entry_time
   - Si no → create nuevo record
   - Status = INSIDE

2. **register_exit()**
   - Busca record INSIDE con misma patente
   - Update exit_time
   - Calcula duration_minutes
   - Status = EXITED

3. **get_vehicles_inside()**
   - Query WHERE status=INSIDE
   - Ordenado por entry_time DESC

**Estados:**
- `INSIDE` - Vehículo en puerto
- `EXITED` - Vehículo salió
- `UNKNOWN` - Sin entrada registrada

```python
class VehicleTracker:
    - register_entry() → Entrada
    - register_exit() → Salida + duration
    - get_vehicles_inside() → Lista actual
    - get_stats() → Métricas dashboard
```

---

## 🗄️ Modelo de Datos

### Tabla: vehicle_records

```sql
CREATE TABLE vehicle_records (
    id INT PRIMARY KEY AUTO_INCREMENT,
    plate VARCHAR(20) NOT NULL,

    entry_time DATETIME,
    exit_time DATETIME,
    duration_minutes FLOAT,

    status ENUM('inside', 'exited', 'unknown'),

    entry_camera VARCHAR(50) DEFAULT 'entrada',
    exit_camera VARCHAR(50) DEFAULT 'salida',

    entry_confidence FLOAT,
    exit_confidence FLOAT,

    created_at DATETIME DEFAULT NOW(),
    updated_at DATETIME DEFAULT NOW() ON UPDATE NOW(),

    INDEX idx_plate (plate),
    INDEX idx_status (status),
    INDEX idx_entry_time (entry_time)
);
```

### Tabla: detection_logs

```sql
CREATE TABLE detection_logs (
    id INT PRIMARY KEY AUTO_INCREMENT,
    camera VARCHAR(50) NOT NULL,
    plate VARCHAR(20) NOT NULL,
    confidence FLOAT NOT NULL,
    ocr_text VARCHAR(100),
    bbox VARCHAR(200),  -- JSON: [x1,y1,x2,y2]
    timestamp DATETIME DEFAULT NOW(),

    INDEX idx_camera (camera),
    INDEX idx_timestamp (timestamp)
);
```

---

## 🌐 API Endpoints

### Streams

| Endpoint | Method | Descripción |
|----------|--------|-------------|
| `/stream/entrada` | GET | MJPEG stream cámara entrada |
| `/stream/salida` | GET | MJPEG stream cámara salida |
| `/stream/status` | GET | Estado conexión streams |

### Detection

| Endpoint | Method | Descripción |
|----------|--------|-------------|
| `/api/detect/{camera}` | POST | Ejecutar detección manual |
| `/api/vehicles/inside` | GET | Vehículos dentro |
| `/api/vehicles/recent-exits` | GET | Últimas salidas |
| `/api/vehicles/history/{plate}` | GET | Historial patente |
| `/api/stats` | GET | Estadísticas generales |

### WebSocket

| Endpoint | Protocolo | Descripción |
|----------|-----------|-------------|
| `/ws/realtime` | WS | Updates cada 2s (detections + stats) |
| `/ws/stats` | WS | Solo stats cada 5s |

---

## ⚡ Optimizaciones Implementadas

### 1. GPU Acceleration

```python
# YOLO warmup en startup
def _warmup(self):
    dummy = np.zeros((640, 640, 3), dtype=np.uint8)
    self.model.predict(dummy, device=self.device, verbose=False)

# PaddleOCR GPU mode
self.ocr = PaddleOCR(use_gpu=True, ...)
```

### 2. Async I/O

```python
# FastAPI async endpoints
@router.post("/api/detect/{camera}")
async def detect_on_camera(db: AsyncSession = Depends(get_db)):
    tracker = VehicleTracker(db)
    await tracker.register_entry(...)

# Async database queries
async with self.db.execute(stmt) as result:
    vehicles = result.scalars().all()
```

### 3. Connection Pooling

```python
# MySQL pool
self.engine = create_async_engine(
    database_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True
)
```

### 4. Singleton Services

```python
# Evitar reload de modelos
_detector_instance = None
def get_detector():
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = YOLODetector(...)
    return _detector_instance
```

### 5. Frame Dropping

```python
# Priorizar latencia sobre completitud
try:
    self.frame_queue.put(frame, block=False)
except Full:
    self.frame_queue.get_nowait()  # Drop old
    self.frame_queue.put(frame)
```

---

## 🔐 Seguridad

### 1. SQL Injection Prevention

```python
# SQLAlchemy ORM (parametrized queries)
stmt = select(VehicleRecord).where(
    VehicleRecord.plate == plate  # Safe parameter binding
)
```

### 2. Environment Variables

```python
# Secrets en .env (no hardcoded)
settings = get_settings()
rtsp_url = settings.rtsp_entrada  # From .env
```

### 3. CORS Configuration

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://ekaia.seidev.cl"],  # Whitelist
    allow_credentials=True,
)
```

---

## 📊 Métricas de Performance

### Latency Budget

| Componente | Target | Actual |
|------------|--------|--------|
| RTSP Frame Grab | <100ms | ~50ms |
| YOLO Inference | <100ms | ~50ms |
| OCR Processing | <200ms | ~150ms |
| DB Insert | <50ms | ~20ms |
| **Total Pipeline** | **<500ms** | **~270ms** |

### Throughput

- **Detections/sec:** 3-4 (limited by OCR)
- **Streams FPS:** 25 FPS (original)
- **WebSocket Updates:** 0.5 Hz (cada 2s)

### Resource Usage

- **GPU Memory:** ~4GB
- **CPU:** ~40% (4 cores)
- **RAM:** ~2GB
- **Network:** ~5 Mbps per stream

---

## 🚀 Escalabilidad

### Vertical Scaling

1. **GPU Upgrade**
   - RTX 5090 → 2x throughput
   - Multi-GPU support posible

2. **CPU Cores**
   - Más workers FastAPI
   - Parallel stream processing

### Horizontal Scaling

1. **Multiple Instances**
   ```
   NGINX Load Balancer
        ↓
   ┌────┴────┬────────┬────────┐
   │ Worker1 │Worker2 │Worker3 │
   └────┬────┴────┬───┴────┬───┘
        └─────────┴────────┘
              MySQL
   ```

2. **Distributed Processing**
   - Redis pub/sub para events
   - Celery para async tasks
   - Kubernetes deployment

---

## 📖 Extensiones Futuras

### 1. Advanced Analytics

```python
# app/services/analytics.py
class VehicleAnalytics:
    - peak_hours() → Horarios punta
    - avg_duration_by_type() → Por tipo vehículo
    - congestion_forecast() → ML prediction
```

### 2. Multi-Camera Support

```python
# Configuración dinámica
cameras = {
    "entrada_norte": "rtsp://...",
    "entrada_sur": "rtsp://...",
    "salida_1": "rtsp://...",
    "salida_2": "rtsp://..."
}
```

### 3. Vehicle Classification

```python
# YOLOv8 extended classes
classes = {
    0: "car",
    1: "truck",
    2: "motorcycle",
    3: "bus",
    4: "license_plate"
}
```

### 4. Integration APIs

```python
# ERP Integration
@router.post("/api/webhook/sap")
async def sap_webhook(data: dict):
    # Sync con SAP ERP
    ...
```

---

## 📚 Referencias Técnicas

- **YOLOv8:** https://github.com/ultralytics/ultralytics
- **PaddleOCR:** https://github.com/PaddlePaddle/PaddleOCR
- **FastAPI:** https://fastapi.tiangolo.com
- **SQLAlchemy Async:** https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
- **OpenCV RTSP:** https://docs.opencv.org/4.x/d8/dfe/classcv_1_1VideoCapture.html
