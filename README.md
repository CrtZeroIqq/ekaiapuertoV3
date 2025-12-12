# 🚢 EKAIA Puerto

**Sistema de Control Vehicular Inteligente para Puerto de Iquique**

Plataforma de visión por computadora en tiempo real para detección de vehículos, reconocimiento de patentes (OCR), y tracking logístico.

## 🎯 Características

✅ **Detección en Tiempo Real**
- YOLO personalizado para vehículos y patentes
- Procesamiento GPU (CUDA 12.4+)
- Doble cámara RTSP (Entrada/Salida)

✅ **OCR Inteligente**
- PaddleOCR optimizado para patentes chilenas
- Normalización automática (ABCD12, AB1234)
- Validación de formato

✅ **Tracking Logístico**
- Registro automático entrada/salida
- Cálculo de tiempo dentro del puerto
- Historial completo por vehículo

✅ **Dashboard Profesional**
- Streams en vivo de ambas cámaras
- WebSocket para actualizaciones en tiempo real
- Estadísticas y métricas
- Registro de actividad

✅ **Arquitectura Escalable**
- FastAPI async
- MySQL con índices optimizados
- Cloudflare Tunnel para acceso externo
- Docker Compose para deployment

---

## 📦 Stack Tecnológico

| Componente | Tecnología |
|------------|-----------|
| **ML/CV** | PyTorch, YOLO, PaddleOCR |
| **Backend** | FastAPI, Python 3.11+ |
| **Database** | MySQL 8.0 |
| **Frontend** | HTML5, CSS3, JavaScript (Vanilla) |
| **Streaming** | OpenCV, RTSP, WebSockets |
| **GPU** | NVIDIA CUDA 12.4+ |
| **Deployment** | Docker, Cloudflare Tunnel |

---

## 🚀 Instalación Rápida

### Prerequisitos

- Ubuntu 24.04 (WSL2)
- NVIDIA GPU (RTX 5070 o similar)
- CUDA 12.4+
- Python 3.11+
- Docker & Docker Compose
- Modelo YOLO en `/home/seidgc/ekaia-engine/models/patentes.pt`

### Paso 1: Clonar Repositorio

```bash
git clone <repo-url>
cd ekaia_puerto
```

### Paso 2: Ejecutar Setup

```bash
chmod +x scripts/setup.sh
bash scripts/setup.sh
```

Esto:
- Crea entorno virtual Python
- Instala PyTorch con CUDA 12.4
- Instala todas las dependencias
- Configura MySQL (Docker)
- Inicializa la base de datos

### Paso 3: Configurar .env

```bash
nano .env
```

**Configuración mínima requerida:**

```bash
# Database
DB_PASSWORD=tu_password_seguro

# Cámaras RTSP
RTSP_ENTRADA=rtsp://admin:password@192.168.88.107:554/cam/realmonitor?channel=1&subtype=0
RTSP_SALIDA=rtsp://admin:password@192.168.88.108:554/cam/realmonitor?channel=1&subtype=0

# Modelo YOLO
YOLO_MODEL_PATH=/home/seidgc/ekaia-engine/models/patentes.pt
```

### Paso 4: Iniciar Servidor

```bash
chmod +x scripts/start.sh
bash scripts/start.sh
```

### Paso 5: Acceder al Dashboard

🌐 **Local:** http://localhost:8000
📚 **API Docs:** http://localhost:8000/docs
🔗 **Cloudflare:** https://ekaia.seidev.cl

---

## 📖 Estructura del Proyecto

```
ekaia_puerto/
├── app/
│   ├── main.py                 # FastAPI application
│   ├── config.py               # Configuration management
│   ├── models/
│   │   └── database.py         # SQLAlchemy models
│   ├── services/
│   │   ├── yolo_detector.py    # YOLO detection
│   │   ├── ocr_service.py      # PaddleOCR integration
│   │   ├── tracker.py          # Vehicle tracking logic
│   │   └── rtsp_stream.py      # RTSP stream manager
│   └── api/
│       ├── streams.py          # Stream endpoints
│       ├── detection.py        # Detection API
│       └── websocket.py        # WebSocket real-time
├── frontend/
│   ├── index.html              # Dashboard UI
│   ├── styles.css              # Styling
│   └── dashboard.js            # WebSocket client
├── scripts/
│   ├── setup.sh                # Initial setup
│   ├── start.sh                # Production start
│   └── init.sql                # Database init
├── requirements.txt            # Python dependencies
├── docker-compose.yml          # MySQL + Cloudflare
└── .env                        # Configuration
```

---

## 🔌 API Endpoints

### Streams

```bash
GET /stream/entrada   # MJPEG stream cámara entrada
GET /stream/salida    # MJPEG stream cámara salida
GET /stream/status    # Estado de streams
```

### Detection

```bash
POST /api/detect/entrada        # Detectar en cámara entrada
POST /api/detect/salida         # Detectar en cámara salida
GET  /api/vehicles/inside       # Vehículos dentro del puerto
GET  /api/vehicles/recent-exits # Salidas recientes
GET  /api/vehicles/history/{plate}  # Historial de patente
GET  /api/stats                 # Estadísticas generales
```

### WebSocket

```bash
WS /ws/realtime    # Updates completos cada 2s
WS /ws/stats       # Solo estadísticas cada 5s
```

---

## 🏗️ Arquitectura de Producción

```
┌─────────────────────────────────────────────────┐
│           Cloudflare Tunnel (HTTPS)             │
│          https://ekaia.seidev.cl                │
└─────────────────┬───────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────┐
│              FastAPI Server                     │
│         (Uvicorn, Single Worker)                │
│                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│  │ Streams  │  │Detection │  │WebSocket │     │
│  │   API    │  │   API    │  │Real-time │     │
│  └──────────┘  └──────────┘  └──────────┘     │
└────────┬──────────────┬───────────────┬────────┘
         │              │               │
    ┌────▼────┐   ┌─────▼─────┐  ┌─────▼─────┐
    │ RTSP    │   │   YOLO    │  │  MySQL    │
    │ Streams │   │ +  OCR    │  │ Database  │
    │Manager  │   │ (GPU)     │  │ (Docker)  │
    └────┬────┘   └───────────┘  └───────────┘
         │
    ┌────▼────────────────┐
    │  Dahua Cameras      │
    │  192.168.88.107/108 │
    └─────────────────────┘
```

### Componentes Clave

1. **RTSP Stream Manager**
   - Thread-safe buffering
   - Auto-reconnect
   - Low-latency (<1s)

2. **YOLO Detector**
   - GPU-accelerated (CUDA)
   - Classes: vehicle (0), plate (1)
   - Singleton pattern

3. **OCR Service**
   - PaddleOCR con GPU
   - Preprocessing: CLAHE, denoising
   - Normalización chilena

4. **Vehicle Tracker**
   - Async SQLAlchemy
   - Tracking por patente
   - Cálculo automático de duración

5. **WebSocket Manager**
   - Broadcasting a múltiples clientes
   - Auto-detección cada 2s
   - Registro automático en DB

---

## ⚙️ Optimizaciones de Rendimiento

### GPU

- **YOLO warmup** en startup
- **Batch processing** disabled (mejor latencia)
- **Stream buffer = 1** (baja latencia)
- **PaddleOCR GPU enabled**

### Database

- **Índices** en: plate, status, timestamp
- **Connection pooling**: 10-20 conexiones
- **Async queries** con aiomysql

### Streaming

- **MJPEG quality = 85%** (balance calidad/bandwidth)
- **Frame drop** si buffer full (latencia > calidad)
- **TCP transport** para confiabilidad

### API

- **Single worker** (GPU exclusivity)
- **WebSocket broadcasting** eficiente
- **Lazy loading** de servicios

---

## 🐛 Troubleshooting

### Error: Stream no conecta

```bash
# Verificar RTSP URL
ffplay rtsp://admin:password@192.168.88.107:554/cam/realmonitor?channel=1&subtype=0

# Verificar logs
docker logs ekaia_mysql
tail -f logs/ekaia.log
```

### Error: GPU no detectada

```bash
# Verificar CUDA
nvidia-smi
python3 -c "import torch; print(torch.cuda.is_available())"

# Reinstalar PyTorch
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
```

### Error: OCR lento

```bash
# Verificar GPU usage
nvidia-smi -l 1

# Ajustar batch size en ocr_service.py
rec_batch_num=6  # Reducir si es necesario
```

### Error: Database connection

```bash
# Verificar MySQL
docker-compose ps
docker-compose logs mysql

# Reset database
docker-compose down -v
docker-compose up -d mysql
python3 -c "from app.models import DatabaseManager; ..."
```

---

## 📊 Monitoreo y Logs

### Logs de Aplicación

```bash
# Ver logs en tiempo real
tail -f logs/ekaia.log

# Filtrar errores
grep ERROR logs/ekaia.log
```

### Métricas GPU

```bash
# Monitor continuo
nvidia-smi -l 1

# Ver procesos
nvidia-smi pmon
```

### Database Stats

```sql
-- Conexión
mysql -u ekaia -p ekaia_puerto

-- Vehículos dentro
SELECT COUNT(*) FROM vehicle_records WHERE status = 'inside';

-- Tiempo promedio hoy
SELECT AVG(duration_minutes) FROM vehicle_records
WHERE DATE(exit_time) = CURDATE();
```

---

## 🔒 Seguridad

### Producción Checklist

- [ ] Cambiar contraseñas por defecto
- [ ] Configurar CORS restrictivo
- [ ] Usar HTTPS (Cloudflare Tunnel)
- [ ] Firewall para RTSP (solo LAN)
- [ ] Backups automáticos MySQL
- [ ] Rate limiting en API
- [ ] Autenticación en dashboard (opcional)

---

## 🚦 Roadmap

- [ ] **Multi-site support** (múltiples puertos)
- [ ] **Advanced analytics** (dashboards BI)
- [ ] **Mobile app** (React Native)
- [ ] **Vehicle classification** (camión/auto/moto)
- [ ] **ANPR confidence scoring**
- [ ] **Integration with ERP systems**
- [ ] **Alertas automáticas** (SMS/Email)
- [ ] **Video recording** on events

---

## 📄 Licencia

Propietario - SEIDEV © 2024

---

## 👤 Autor

**SEIDEV**
📧 Email: contacto@seidev.cl
🌐 Web: https://ekaia.seidev.cl

---

## 🙏 Créditos

- **Ultralytics YOLO** - Object detection
- **PaddleOCR** - OCR engine
- **FastAPI** - Web framework
- **Cloudflare** - CDN & Tunnel
